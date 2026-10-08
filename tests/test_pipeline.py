import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from news_video_batch.domain import ValidationError, load_template
from news_video_batch.pipeline import run_batch, verify_batch
from news_video_batch.providers import LocalNewsSource, OfflineModel


DATA = Path(__file__).resolve().parents[1] / "src/news_video_batch/data"


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.output = Path(self.temporary.name) / "中文 带空格" / "batch"
        self.template = load_template(DATA / "template.json")

    def run_demo(self, **kwargs):
        return run_batch(source=LocalNewsSource(DATA / "news.json"), model=kwargs.pop("model", OfflineModel()),
                         template=self.template, destination=self.output, **kwargs)

    def test_offline_batch_has_two_articles_and_verifiable_hashes(self):
        with patch("urllib.request.OpenerDirector.open", side_effect=AssertionError("No network in demo")):
            manifest = self.run_demo()
        self.assertEqual(verify_batch(self.output), manifest)
        self.assertEqual(len(manifest["articles"]), 2)
        self.assertFalse(manifest["jianying_gui_verified"])
        self.assertFalse(manifest["video_rendered"])
        self.assertTrue((self.output / "demo-library/preview.html").is_file())

    def test_existing_output_never_overwritten(self):
        self.output.mkdir(parents=True)
        marker = self.output / "keep.txt"
        marker.write_text("keep", encoding="utf-8")
        with self.assertRaises(ValidationError):
            self.run_demo()
        self.assertEqual(marker.read_text(), "keep")

    def test_failure_on_second_article_removes_entire_staged_batch(self):
        class FailingModel:
            count = 0

            def generate(self, news, template):
                self.count += 1
                if self.count == 2:
                    raise ValidationError("Synthetic generation error")
                return news["demo_texts"]

        with self.assertRaises(ValidationError):
            self.run_demo(model=FailingModel())
        self.assertFalse(self.output.exists())
        self.assertEqual(list(self.output.parent.glob(".nvbatch-*")), [])

    def test_model_cannot_override_fixed_fields(self):
        class MaliciousModel:
            def generate(self, news, template):
                return {**news["demo_texts"], "brand_open": "changed"}

        with self.assertRaisesRegex(ValidationError, "generated slot"):
            self.run_demo(model=MaliciousModel())
        self.assertFalse(self.output.exists())

    def test_exporter_must_verify_saved_data(self):
        with patch("news_video_batch.exporters.write_demo", return_value={"verified": False}):
            with self.assertRaisesRegex(ValidationError, "verification"):
                self.run_demo()

    def test_manifest_detects_tampering_and_extra_files(self):
        self.run_demo()
        path = self.output / "demo-library/texts.json"
        original = path.read_bytes()
        path.write_bytes(b"modified")
        with self.assertRaisesRegex(ValidationError, "changed"):
            verify_batch(self.output)
        path.write_bytes(original)
        (self.output / "unexpected.txt").write_text("unexpected")
        with self.assertRaisesRegex(ValidationError, "unlisted"):
            verify_batch(self.output)

    def test_manifest_rejects_traversal(self):
        self.run_demo()
        path = self.output / "manifest.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["sha256"] = {"../outside.txt": "0" * 64}
        path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(ValidationError, "Unsafe"):
            verify_batch(self.output)

    def test_jianying_requires_template_before_source_is_loaded(self):
        with self.assertRaisesRegex(ValidationError, "requires"):
            self.run_demo(export_kind="jianying")

    def test_jianying_cannot_write_inside_template(self):
        template_dir = self.output.parent
        template_dir.mkdir(parents=True)
        with self.assertRaisesRegex(ValidationError, "outside"):
            self.run_demo(export_kind="jianying", jianying_template=template_dir)


if __name__ == "__main__":
    unittest.main()
