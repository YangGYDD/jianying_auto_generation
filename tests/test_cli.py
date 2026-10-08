"""Exercise documented CLI workflows using real local files, without network."""

from contextlib import chdir, redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from news_video_batch import cli
from news_video_batch.domain import ValidationError
from news_video_batch.pipeline import _check_new_destination, _is_link_or_reparse


def invoke(*args):
    output, errors = io.StringIO(), io.StringIO()
    with redirect_stdout(output), redirect_stderr(errors):
        code = cli.main(list(args))
    return code, output.getvalue(), errors.getvalue()


class CliTests(unittest.TestCase):
    def test_default_doctor_checks_installed_data_without_network(self):
        with patch.dict("os.environ", {}, clear=True), patch("urllib.request.build_opener", side_effect=AssertionError("network forbidden")):
            code, output, errors = invoke("doctor")
        self.assertEqual((code, errors), (0, ""))
        status = json.loads(output)
        self.assertEqual(status["status"], "ok")
        self.assertFalse(status["network_tested"])
        self.assertEqual(status["slot_count"], 9)

    def test_demo_ignores_online_environment_and_runs_from_unrelated_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            destination = Path(temp) / "demo"
            # Deliberately invalid values prove that demo never loads environment config.
            with patch.dict("os.environ", {"NVB_DOUBAO_API_KEY": "test-" + "\ninvalid", "NVB_DINGTALK_OPERATOR_ID": "test-" + "\ninvalid"}), patch("urllib.request.build_opener", side_effect=AssertionError("network forbidden")), chdir(temp):
                code, _, errors = invoke("demo", "--output", str(destination))
            self.assertEqual((code, errors), (0, ""))
            code, output, errors = invoke("verify", str(destination))
            self.assertEqual((code, errors), (0, ""))
            self.assertIn("PASS", output)
            manifest = json.loads((destination / "manifest.json").read_text(encoding="utf-8"))
            self.assertFalse(manifest["video_rendered"])
            self.assertFalse(manifest["jianying_gui_verified"])
            self.assertEqual(len(manifest["articles"]), 2)

    def test_init_then_documented_run_and_existing_output_protection(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict("os.environ", {}, clear=True):
            local, output = Path(temp) / "local", Path(temp) / "batch"
            self.assertEqual(invoke("init", "--directory", str(local))[0], 0)
            self.assertEqual({path.name for path in local.iterdir()}, {"news.json", "template.json", "config.example.json", "background.svg", "ASSETS.txt"})
            args = ("run", "--news", str(local / "news.json"), "--template", str(local / "template.json"), "--output", str(output))
            self.assertEqual(invoke(*args)[0], 0)
            manifest = (output / "manifest.json").read_bytes()
            code, _, errors = invoke(*args)
            self.assertEqual(code, 2)
            self.assertIn("already exists", errors)
            self.assertEqual((output / "manifest.json").read_bytes(), manifest)

    def test_second_article_failure_leaves_no_final_or_staging_batch(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict("os.environ", {}, clear=True):
            root = Path(temp)
            news = json.loads(cli._data_path("news.json").read_text(encoding="utf-8"))
            # The first article is valid; the second fails after staging has been written.
            key = next(iter(news[1]["demo_texts"]))
            news[1]["demo_texts"][key] = "X" * 1000
            source = root / "news.json"
            source.write_text(json.dumps(news), encoding="utf-8")
            output = root / "batch"
            code, _, errors = invoke("run", "--news", str(source), "--output", str(output))
            self.assertEqual(code, 2)
            self.assertIn("limit", errors)
            self.assertFalse(output.exists())
            self.assertEqual(list(root.glob(".nvbatch-*")), [])

    def test_file_error_does_not_disclose_private_path(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict("os.environ", {}, clear=True):
            private = Path(temp) / "private-account-marker" / "news.json"
            code, output, errors = invoke("doctor", "--news", str(private))
        self.assertEqual((code, output), (2, ""))
        self.assertNotIn("private-account-marker", errors)
        self.assertNotIn("Traceback", errors)

    def test_deep_input_returns_actionable_error_without_traceback(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict("os.environ", {}, clear=True):
            source = Path(temp) / "news.json"
            source.write_text("[" * 2000 + "]" * 2000, encoding="utf-8")
            code, output, errors = invoke("doctor", "--news", str(source))
        self.assertEqual((code, output), (2, ""))
        self.assertIn("ERROR", errors)
        self.assertNotIn("Traceback", errors)

    def test_online_doctor_does_not_connect_even_with_complete_configuration(self):
        with patch.dict("os.environ", {"NVB_DOUBAO_API_KEY": "test-key", "NVB_DOUBAO_MODEL": "test-model"}, clear=True), patch("urllib.request.build_opener", side_effect=AssertionError("network forbidden")):
            code, output, errors = invoke("doctor", "--model", "doubao")
        self.assertEqual((code, errors), (0, ""))
        self.assertFalse(json.loads(output)["network_tested"])

    def test_windows_junction_attribute_is_checked_without_new_pathlib_api(self):
        # Simulate the Windows 3.11 stat result; this requires no symlink privilege.
        details = SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0x400)
        with patch.object(Path, "lstat", return_value=details):
            self.assertTrue(_is_link_or_reparse(Path("test-junction")))
            with self.assertRaisesRegex(ValidationError, "junctions"):
                _check_new_destination(Path("test-junction/output"))

    def test_jianying_success_does_not_advertise_nonexistent_preview(self):
        # The exporter has separate file-level integration tests; exercise CLI wording.
        with patch.dict("os.environ", {}, clear=True), patch("news_video_batch.pipeline.run_batch", return_value={"articles": [{"id": "test-news"}]}):
            code, output, errors = invoke("run", "--output", "test-output", "--export", "jianying", "--jianying-template", "test-template")
        self.assertEqual((code, errors), (0, ""))
        self.assertIn("saved-structure checks", output)
        self.assertNotIn("preview.html", output)

    def test_verify_rejects_symlink_loop_before_resolving_it(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            link = root / "loop.txt"
            try:
                link.symlink_to("loop.txt")
            except OSError:
                self.skipTest("This environment does not grant symbolic link creation")
            (root / "manifest.json").write_text(json.dumps({"sha256": {"loop.txt": "0" * 64}}), encoding="utf-8")
            code, _, errors = invoke("verify", str(root))
            self.assertEqual(code, 2)
            self.assertIn("Manifest path leaves batch directory", errors)
            self.assertNotIn("Traceback", errors)


if __name__ == "__main__":
    unittest.main()
