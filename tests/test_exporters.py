"""Synthetic, independently authored fixtures; no business drafts or media."""

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from news_video_batch.domain import ValidationError
from news_video_batch import exporters


def make_template(count=2):
    return {
        "schema_version": 1, "name": "Synthetic test", "width": 1080, "height": 1920,
        "slots": [
            {"id": f"s{i}", "purpose": "caption", "mode": "generated", "allow_repeat": False,
             "max_chars": 200, "max_lines": 3, "max_chars_per_line": 200, "order": i + 1,
             "start_ms": i * 1000, "duration_ms": 1000, "track": 0, "segment": i,
             "sequence": "captions", "sequence_index": i + 1}
            for i in range(count)
        ],
    }


def make_draft(count=2):
    content = {"text": "原文", "styles": [{"range": [0, 2], "size": 24, "fill": {"alpha": 1}}]}
    return {
        "canvas_config": {"width": 1080, "height": 1920},
        "tracks": [{"type": "text", "segments": [
            {"material_id": "shared", "target_timerange": {"start": i * 1000000, "duration": 1000000}}
            for i in range(count)
        ]}],
        "materials": {"texts": [{"id": "shared", "type": "text", "content": json.dumps(content, ensure_ascii=False)}]},
    }


class ExporterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.source.mkdir()
        self.destination = self.root / "result"
        self.destination.mkdir()
        self.news = {"id": "demo", "title": "原创新闻", "source": "原创示例", "date": "2026-01-01"}
        self.template = make_template()
        self.texts = {"s0": "第一段正文", "s1": "第二段正文"}
        self.draft = make_draft()

    def write_source(self):
        (self.source / "draft_content.json").write_text(json.dumps(self.draft, ensure_ascii=False), encoding="utf-8")

    def export_jianying(self):
        self.write_source()
        return exporters.write_jianying(self.news, self.template, self.texts, self.destination, self.source)

    def test_demo_outputs_are_readable_complete_and_timed(self):
        result = exporters.write_demo(self.news, self.template, self.texts, self.destination)
        self.assertTrue(result["verified"])
        self.assertEqual(set(result["files"]), {"draft.json", "preview.html", "captions.srt"})
        draft = json.loads((self.destination / "draft.json").read_text(encoding="utf-8"))
        self.assertEqual([s["text"] for s in draft["slots"]], list(self.texts.values()))
        self.assertEqual([s["start_ms"] for s in draft["slots"]], [0, 1000])
        srt = (self.destination / "captions.srt").read_text(encoding="utf-8")
        self.assertEqual(srt, "1\n00:00:00,000 --> 00:00:01,000\n第一段正文\n\n2\n00:00:01,000 --> 00:00:02,000\n第二段正文\n")

    def test_preview_escapes_html_and_script_payload_without_network(self):
        self.news["title"] = "</title><script>alert(1)</script> @@ROWS@@"
        self.texts["s0"] = "</script><img src=x onerror=alert(1)>"
        exporters.write_demo(self.news, self.template, self.texts, self.destination)
        preview = (self.destination / "preview.html").read_text(encoding="utf-8")
        self.assertNotIn("<img src=x", preview)
        self.assertNotIn("<script>alert(1)", preview)
        self.assertIn("\\u003c/script\\u003e", preview)
        self.assertIn("&lt;/title&gt;", preview)
        self.assertIn("@@ROWS@@", preview)
        self.assertIn("connect-src 'none'", preview)
        self.assertNotIn("fetch(", preview)
        self.assertEqual(preview.count('<script id="draft-data"'), 1)

    def test_srt_includes_only_explicit_sequences(self):
        for slot in self.template["slots"]:
            del slot["sequence"]
            del slot["sequence_index"]
        exporters.write_demo(self.news, self.template, self.texts, self.destination)
        self.assertEqual((self.destination / "captions.srt").read_text(encoding="utf-8"), "")

    def test_shared_material_becomes_distinct_per_segment_and_source_unchanged(self):
        self.write_source()
        original = (self.source / "draft_content.json").read_bytes()
        result = exporters.write_jianying(self.news, self.template, self.texts, self.destination, self.source)
        saved = json.loads((self.destination / "draft_content.json").read_text(encoding="utf-8"))
        ids = [s["material_id"] for s in saved["tracks"][0]["segments"]]
        materials = {m["id"]: json.loads(m["content"]) for m in saved["materials"]["texts"]}
        self.assertEqual(len(set(ids)), 2)
        self.assertEqual([materials[i]["text"] for i in ids], list(self.texts.values()))
        self.assertEqual([s["target_timerange"] for s in saved["tracks"][0]["segments"]],
                         [s["target_timerange"] for s in self.draft["tracks"][0]["segments"]])
        self.assertEqual((self.source / "draft_content.json").read_bytes(), original)
        self.assertNotIn("原文", (self.destination / "draft_content.json").read_text(encoding="utf-8"))
        self.assertIn("GUI unverified", result["verification_scope"])

    def test_non_bmp_style_range_uses_utf16_and_keeps_visual_style(self):
        self.texts["s0"] = "示例😀\n新闻"
        self.export_jianying()
        saved = json.loads((self.destination / "draft_content.json").read_text(encoding="utf-8"))
        content = json.loads(saved["materials"]["texts"][0]["content"])
        self.assertEqual(content["styles"][0], {"range": [0, 7], "size": 24, "fill": {"alpha": 1}})

    def test_coverage_requires_all_segments_and_exact_timing(self):
        self.write_source()
        cases = []
        fewer = make_template(1)
        cases.append((fewer, {"s0": "第一段正文"}))
        timing = copy.deepcopy(self.template)
        timing["slots"][0]["duration_ms"] = 900
        for slot in timing["slots"]:
            slot.pop("sequence")
            slot.pop("sequence_index")
        cases.append((timing, self.texts))
        for template, texts in cases:
            with self.subTest(template=template), self.assertRaises(ValidationError):
                exporters.write_jianying(self.news, template, texts, self.destination, self.source)
        self.assertFalse(any(self.destination.iterdir()))

    def test_text_track_index_does_not_count_video_tracks(self):
        self.draft["tracks"].insert(0, {"type": "video", "segments": []})
        self.export_jianying()
        saved = json.loads((self.destination / "draft_content.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["tracks"][0], {"type": "video", "segments": []})

    def test_rich_unknown_and_incomplete_styles_fail_closed(self):
        contents = [
            {"text": "原文", "styles": {}},
            {"text": "原文", "styles": []},
            {"text": "原文", "styles": [{"range": [0, 1]}, {"range": [1, 2]}]},
            {"text": "原文", "styles": [{"range": [0, 1]}]},
            {"text": "原文", "styles": [{"range": [False, 2]}]},
            {"text": "原文", "styles": [{"range": [0, 2], "hidden_text": "原文"}]},
            {"text": "原文", "rich_text": "原文"},
        ]
        for content in contents:
            with self.subTest(content=content):
                self.draft["materials"]["texts"][0]["content"] = json.dumps(content)
                with self.assertRaises(ValidationError):
                    self.export_jianying()
        self.assertFalse(any(self.destination.iterdir()))

    def test_compound_track_linked_speech_and_unsupported_metadata_rejected(self):
        for variant in ("track", "speech", "animation", "mirror"):
            self.draft = make_draft()
            if variant == "track":
                self.draft["tracks"][0]["type"] = "text_template"
            elif variant == "speech":
                self.draft["materials"]["texts"][0]["words"] = {"text": "原文"}
            elif variant == "animation":
                self.draft["tracks"][0]["segments"][0]["extra_material_refs"] = ["animation"]
            else:
                self.draft["materials"]["texts"][0]["recognize_text"] = "原文"
            with self.subTest(variant=variant), self.assertRaises(ValidationError):
                self.export_jianying()

    def test_only_referenced_local_assets_copied_and_verified(self):
        (self.source / "assets").mkdir()
        image = self.source / "assets" / "test.png"
        image.write_bytes(b"synthetic byte fixture, not a distributable media file")
        (self.source / "private.local.json").write_text('{"internal":"do not copy"}', encoding="utf-8")
        (self.source / "draft_meta_info.json").write_text('{"history":"do not copy"}', encoding="utf-8")
        self.draft["materials"]["videos"] = [{"id": "background", "path": "assets/test.png"}]
        result = self.export_jianying()
        self.assertEqual((self.destination / "assets" / "test.png").read_bytes(), image.read_bytes())
        self.assertFalse((self.destination / "private.local.json").exists())
        self.assertFalse((self.destination / "draft_meta_info.json").exists())
        self.assertIn("assets/test.png", result["files"])

    def test_absolute_traversal_remote_missing_and_nonmedia_assets_rejected(self):
        paths = ["../escape.png", "C:/external/image.png", "/absolute/image.png", "\\\\server\\image.png",
                 "https://example.invalid/image.png", "assets/missing.png", "settings.json", "assets/./x.png"]
        for path in paths:
            self.draft["materials"]["videos"] = [{"id": "v", "path": path}]
            with self.subTest(path=path), self.assertRaises(ValidationError):
                self.export_jianying()
        self.assertFalse(any(self.destination.iterdir()))

    def test_nested_font_paths_are_checked(self):
        content = json.loads(self.draft["materials"]["texts"][0]["content"])
        content["styles"][0]["font"] = {"path": "C:/outside/font.ttf"}
        self.draft["materials"]["texts"][0]["content"] = json.dumps(content)
        with self.assertRaises(ValidationError):
            self.export_jianying()

    def test_unknown_asset_path_structures_and_remote_metadata_fail_closed(self):
        cases = [{"path": ["assets/test.png"]}, {"path": {"local": "assets/test.png"}},
                 {"resource_url": "HTTPS://example.invalid/media"},
                 {"resource_url": "ftp://example.invalid/media"}, {"resource_url": "/external/media"}]
        for entry in cases:
            self.draft["materials"]["videos"] = [{"id": "v", **entry}]
            with self.subTest(entry=entry), self.assertRaises(ValidationError):
                self.export_jianying()
        self.assertFalse(any(self.destination.iterdir()))

    def test_destination_must_be_empty_separate_and_outside_editor(self):
        sentinel = self.destination / "keep.txt"
        sentinel.write_text("preserve", encoding="utf-8")
        with self.assertRaises(ValidationError):
            exporters.write_demo(self.news, self.template, self.texts, self.destination)
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "preserve")
        self.write_source()
        nested = self.source / "output"
        nested.mkdir()
        with self.assertRaises(ValidationError):
            exporters.write_jianying(self.news, self.template, self.texts, nested, self.source)
        editor = self.root / "com.lveditor.draft" / "new"
        editor.mkdir(parents=True)
        with self.assertRaises(ValidationError):
            exporters.write_demo(self.news, self.template, self.texts, editor)

    def test_symbolic_link_source_is_rejected_when_supported(self):
        self.write_source()
        link = self.root / "source-link"
        try:
            link.symlink_to(self.source, target_is_directory=True)
        except OSError:
            self.skipTest("Operating system does not permit symbolic links for this test user")
        with self.assertRaises(ValidationError):
            exporters.write_jianying(self.news, self.template, self.texts, self.destination, link)

    def test_reparse_point_ancestor_is_rejected(self):
        real_lstat = Path.lstat

        def fake_lstat(path):
            if path == self.root:
                return type("ReparseStat", (), {"st_mode": 0, "st_file_attributes": 0x400})()
            return real_lstat(path)

        with mock.patch.object(Path, "lstat", fake_lstat):
            with self.assertRaisesRegex(ValidationError, "junctions"):
                exporters.write_demo(self.news, self.template, self.texts, self.destination)

    def test_saved_draft_is_reread_and_corruption_fails(self):
        real_write = exporters._write_json

        def corrupt(path, draft):
            damaged = copy.deepcopy(draft)
            damaged["tracks"][0]["segments"][0]["target_timerange"]["start"] = 123
            real_write(path, damaged)

        with mock.patch.object(exporters, "_write_json", corrupt):
            with self.assertRaisesRegex(ValidationError, "differs"):
                self.export_jianying()

    def test_nonplaintext_input_fails_without_copying(self):
        (self.source / "draft_content.json").write_bytes(b"not plaintext draft JSON\x00\xff")
        with self.assertRaisesRegex(ValidationError, "plaintext"):
            exporters.write_jianying(self.news, self.template, self.texts, self.destination, self.source)
        self.assertFalse(any(self.destination.iterdir()))

    def test_ambiguous_and_nonstandard_json_is_rejected(self):
        cases = ['{"tracks": [], "tracks": []}', '{"tracks": [], "duration": NaN}']
        for value in cases:
            (self.source / "draft_content.json").write_text(value, encoding="utf-8")
            with self.subTest(value=value), self.assertRaises(ValidationError):
                exporters.write_jianying(self.news, self.template, self.texts, self.destination, self.source)
        self.assertFalse(any(self.destination.iterdir()))

    def test_bad_segment_reference_and_nonobject_segments_fail_clearly(self):
        self.draft["tracks"][0]["segments"][0]["material_id"] = []
        with self.assertRaises(ValidationError):
            self.export_jianying()
        self.draft = make_draft()
        self.draft["tracks"].append({"type": "video", "segments": ["unsupported"]})
        with self.assertRaises(ValidationError):
            self.export_jianying()


if __name__ == "__main__":
    unittest.main()
