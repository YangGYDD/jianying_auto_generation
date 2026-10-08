from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from tools.build_package import build_package, verify_package
from tools.check_public import PublicSafetyError, check_distribution, collect_public, scan_content


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "README.md").write_text("# Original example\n", encoding="utf-8")
        (self.root / "src" / "news_video_batch").mkdir(parents=True)
        (self.root / "src" / "news_video_batch" / "__init__.py").write_text("# Original source\n", encoding="utf-8")

    def test_public_pack_excludes_local_config_history_and_outputs(self):
        (self.root / "config.json").write_text('{"private":true}', encoding="utf-8")
        for name in ("local", "outputs", "work", "history"):
            (self.root / name).mkdir()
            (self.root / name / "private.json").write_text("{}", encoding="utf-8")
        output = self.root / "outputs" / "public.zip"
        result = build_package(self.root, output)
        manifest = verify_package(output)
        self.assertEqual(manifest["visibility"], "public-ready")
        self.assertEqual(set(manifest["files"]), {"README.md", "src/news_video_batch/__init__.py"})
        self.assertEqual(hashlib.sha256(output.read_bytes()).hexdigest(), result["sha256"])
        self.assertIn(result["sha256"], output.with_suffix(".zip.sha256").read_text())

    def test_runtime_dependency_declaration_is_in_public_source(self):
        (self.root / "requirements.txt").write_text("# Standard library only.\n", encoding="utf-8")
        self.assertIn("requirements.txt", collect_public(self.root))

    def test_public_candidate_sensitive_json_is_rejected_without_echo(self):
        (self.root / "tests").mkdir()
        value = "unreviewed" + "-credential-value"
        path = self.root / "tests" / "fixture.json"
        path.write_text(json.dumps({"api_key": value}), encoding="utf-8")
        with self.assertRaises(PublicSafetyError) as raised:
            collect_public(self.root)
        self.assertNotIn(value, str(raised.exception))

    def test_dummy_fixture_allowed_but_config_example_must_be_blank(self):
        self.assertEqual(scan_content("tests/fixture.json", b'{"api_key":"dummy-offline-value"}'), [])
        self.assertTrue(scan_content("src/data/config.example.json", b'{"api_key":"dummy-offline-value"}'))
        self.assertEqual(scan_content("src/data/config.example.json", b'{"api_key":""}'), [])
        self.assertTrue(scan_content("src/data/config.example.json", b'{"model":"example-endpoint"}'))

    def test_source_literal_and_token_pattern_rejected(self):
        source = "api_key" + ' = "' + "unreviewed-value" + '"'
        self.assertTrue(scan_content("src/example.py", source.encode()))
        marker = "gh" + "p_" + "x" * 36
        self.assertTrue(scan_content("tests/fixture.json", json.dumps({"value": marker}).encode()))

    def test_binary_large_file_active_svg_and_unknown_type_rejected(self):
        self.assertTrue(scan_content("examples/payload.json", bytes([255])))
        self.assertTrue(scan_content("README.md", b"a" * (2 * 1024 * 1024 + 1)))
        self.assertTrue(scan_content("examples/asset.svg", b'<svg><script>alert(1)</script></svg>'))
        (self.root / "src" / "bad.zip").write_bytes(b"bad")
        with self.assertRaises(PublicSafetyError):
            collect_public(self.root)

    def test_explicit_internal_pack_is_labelled_and_never_implicit(self):
        internal = self.root / "internal"
        internal.mkdir()
        (internal / "review.md").write_text("Private deployment notes", encoding="utf-8")
        with self.assertRaises(PublicSafetyError):
            build_package(self.root, self.root / "public.zip", internal)
        result = build_package(self.root, self.root / "private-build.zip", internal)
        self.assertEqual(result["visibility"], "private-internal")
        manifest = verify_package(self.root / "private-build.zip")
        self.assertIn("PRIVATE_INTERNAL/review.md", manifest["files"])
        self.assertIn("PRIVATE_INTERNAL/PRIVATE_NOTICE.txt", manifest["files"])

    def test_internal_pack_also_rejects_credentials(self):
        internal = self.root / "internal"
        internal.mkdir()
        unreviewed = "live" + "-unreviewed-value"
        payload = {"access_token": unreviewed}
        (internal / "config.json").write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaises(PublicSafetyError):
            build_package(self.root, self.root / "private-build.zip", internal)
        self.assertFalse((self.root / "private-build.zip").exists())

    def test_existing_output_not_overwritten(self):
        output = self.root / "existing.zip"
        output.write_bytes(b"preserve")
        with self.assertRaises(PublicSafetyError):
            build_package(self.root, output)
        self.assertEqual(output.read_bytes(), b"preserve")

    def test_saved_package_tampering_detected(self):
        output = self.root / "public.zip"
        build_package(self.root, output)
        tampered = self.root / "tampered.zip"
        with zipfile.ZipFile(output) as original, zipfile.ZipFile(tampered, "w") as changed:
            for name in original.namelist():
                changed.writestr(name, b"changed" if name == "README.md" else original.read(name))
        with self.assertRaises(PublicSafetyError):
            verify_package(tampered)

    def test_symlink_refused(self):
        path = self.root / "src" / "linked.py"
        try:
            path.symlink_to(self.root / "README.md")
        except OSError:
            self.skipTest("OS does not grant symlink creation")
        with self.assertRaises(PublicSafetyError):
            collect_public(self.root)

    def test_wheel_unreviewed_member_rejected_and_original_accepted(self):
        public = collect_public(self.root)
        wheel = self.root / "demo.whl"
        with zipfile.ZipFile(wheel, "w") as archive:
            archive.writestr("news_video_batch/__init__.py", public["src/news_video_batch/__init__.py"])
            archive.writestr("demo.dist-info/METADATA", "Name: demo\n")
        self.assertEqual(check_distribution(wheel, public), 2)
        with zipfile.ZipFile(wheel, "a") as archive:
            archive.writestr("secret.json", "{}")
        with self.assertRaises(PublicSafetyError):
            check_distribution(wheel, public)


if __name__ == "__main__":
    unittest.main()
