# -*- coding: utf-8 -*-
import json
import os
import sys
import tempfile
import unittest


ENGINE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ENGINE_DIR not in sys.path:
    sys.path.insert(0, ENGINE_DIR)

from pipeline import BatchRunner, DraftVerificationError  # noqa: E402
import pyJianYingDraft as draft
from template_health import analyze_slots


class IdentityCrypto:
    @staticmethod
    def encrypt(data):
        return data

    @staticmethod
    def decrypt(data):
        return data


class DraftVerificationTests(unittest.TestCase):
    def test_real_writer_keeps_sequential_text_distinct(self):
        source = draft.ScriptFile(1080, 1920, 30, False)
        track = source.append_track(draft.TrackSpec(draft.TrackType.text))
        source.add_segment(draft.TextSegment("原文一", draft.Timerange(0, 1000000)), track)
        source.add_segment(draft.TextSegment("原文二", draft.Timerange(1000000, 1000000)), track)
        plain = source.dumps()
        slots = analyze_slots(json.loads(plain))
        runner = self._runner()
        runner.template_plain = lambda name: plain
        runner._collect_materials = lambda *args: ({}, [])
        info = {"文字位1": "第一段新闻", "文字位2": "第二段进展"}
        with tempfile.TemporaryDirectory() as target:
            runner._fill_draft(target, info, target, slots, "默认")
            with open(os.path.join(target, "draft_content.json"), encoding="utf-8") as handle:
                written = json.load(handle)
            texts = {m["id"]: json.loads(m["content"])["text"]
                     for m in written["materials"]["texts"]}
            self.assertEqual([texts[s["material_id"]]
                              for s in written["tracks"][0]["segments"]],
                             ["第一段新闻", "第二段进展"])
            self.assertEqual([s["target_timerange"] for s in written["tracks"][0]["segments"]],
                             [s["target_timerange"] for s in json.loads(plain)["tracks"][0]["segments"]])

    def test_text_verification_rejects_overwritten_or_missing_copy(self):
        with tempfile.TemporaryDirectory() as target:
            data = {
                "tracks": [{"type": "text", "segments": [
                    {"material_id": "one"}, {"material_id": "two"}]}],
                "materials": {"texts": [
                    {"id": "one", "content": json.dumps({"text": "第一屏正文"})},
                    {"id": "two", "content": json.dumps({"text": "第一屏正文"})}]},
            }
            slots = {"素材槽位": [], "文字槽位": [
                {"键名": key, "轨道类型": "text", "轨道序号": 0, "片段": [i]}
                for i, key in enumerate(("正文1", "正文2"))]}
            path = os.path.join(target, "draft_content.json")
            def save():
                with open(path, "w", encoding="utf-8") as handle:
                    json.dump(data, handle)
            save()
            info = {"正文1": "第一屏正文", "正文2": "第二屏正文"}
            with self.assertRaisesRegex(DraftVerificationError, "正文2.*不一致"):
                self._runner()._verify_written_draft(target, slots, {}, info)
            data["materials"]["texts"][1]["content"] = json.dumps({"text": "第二屏正文"})
            save()
            self._runner()._verify_written_draft(target, slots, {}, info)
            with self.assertRaisesRegex(DraftVerificationError, "缺少有效文案"):
                self._runner()._verify_written_draft(target, slots, {}, {"正文1": "第一屏正文"})

    @staticmethod
    def _runner():
        runner = BatchRunner.__new__(BatchRunner)
        runner.crypto = IdentityCrypto()
        return runner

    @staticmethod
    def _write_draft(target, material_path):
        data = {
            "tracks": [{
                "type": "video",
                "attribute": 1,
                "segments": [{"material_id": "replacement-id"}],
            }],
            "materials": {
                "videos": [{"id": "replacement-id", "path": material_path}],
                "texts": [],
            },
        }
        with open(os.path.join(target, "draft_content.json"), "wb") as handle:
            handle.write(json.dumps(data).encode("utf-8"))

    def test_assigned_slot_must_reference_the_copied_material(self):
        with tempfile.TemporaryDirectory() as target:
            copied = os.path.join(target, "materials", "video", "主视频1_test.mp4")
            os.makedirs(os.path.dirname(copied))
            with open(copied, "wb") as handle:
                handle.write(b"video")
            self._write_draft(target, copied)
            slots = {
                "文字槽位": [],
                "素材槽位": [{
                    "键名": "主视频1", "轨道类型": "video", "轨道序号": 0, "片段": 0,
                }],
            }

            message = self._runner()._verify_written_draft(
                target, slots, {"主视频1": {"slot": slots["素材槽位"][0], "path": copied}}
            )

            self.assertIn("1 个已分配槽位", message)

    def test_template_material_left_in_slot_fails_verification(self):
        with tempfile.TemporaryDirectory() as target:
            copied = os.path.join(target, "materials", "video", "主视频1_test.mp4")
            os.makedirs(os.path.dirname(copied))
            with open(copied, "wb") as handle:
                handle.write(b"video")
            self._write_draft(target, os.path.join(target, "template-original.mp4"))
            slot = {"键名": "主视频1", "轨道类型": "video", "轨道序号": 0, "片段": 0}
            slots = {"文字槽位": [], "素材槽位": [slot]}

            with self.assertRaisesRegex(DraftVerificationError, "仍未指向新素材"):
                self._runner()._verify_written_draft(
                    target, slots, {"主视频1": {"slot": slot, "path": copied}}
                )


if __name__ == "__main__":
    unittest.main()
