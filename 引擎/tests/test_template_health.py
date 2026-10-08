# -*- coding: utf-8 -*-
import json
import os
import sys
import tempfile
import unittest


ENGINE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ENGINE_DIR not in sys.path:
    sys.path.insert(0, ENGINE_DIR)

import template_health  # noqa: E402
import template_registry as reg  # noqa: E402


def sample_draft():
    return {
        "materials": {"texts": []},
        "tracks": [
            {"type": "video", "attribute": 1, "segments": [{}, {}, {}, {}]},
            {"type": "video", "segments": [{}, {}, {}]},
            {"type": "text", "segments": [{}, {}]},
        ],
    }


class AnalyzeSlotsTests(unittest.TestCase):
    def test_each_text_segment_gets_its_own_slot(self):
        slots = template_health.analyze_slots(sample_draft())["文字槽位"]
        self.assertEqual([slot["片段"] for slot in slots], [[0], [1]])
        self.assertEqual(len({slot["键名"] for slot in slots}), 2)

    def test_main_and_overlay_tracks_use_global_video_indexes(self):
        slots = template_health.analyze_slots(sample_draft())
        material_slots = slots["素材槽位"]

        self.assertEqual(
            [(slot["键名"], slot["轨道序号"], slot["片段"])
             for slot in material_slots],
            [
                ("主视频1", 0, 0), ("主视频2", 0, 1),
                ("主视频3", 0, 2), ("主视频4", 0, 3),
                ("贴片视频1", 1, 0), ("贴片视频2", 1, 1),
                ("贴片视频3", 1, 2),
            ],
        )

    def test_slot_names_stay_unique_across_multiple_tracks(self):
        draft = {
            "materials": {"texts": []},
            "tracks": [
                {"type": "video", "segments": [{}, {}]},
                {"type": "video", "segments": [{}]},
                {"type": "video", "attribute": 1, "segments": [{}]},
                {"type": "video", "attribute": 1, "segments": [{}, {}]},
            ],
        }

        slots = template_health.analyze_slots(draft)["素材槽位"]

        self.assertEqual(
            [slot["键名"] for slot in slots],
            ["贴片视频1", "贴片视频2", "贴片视频3", "主视频1", "主视频2", "主视频3"],
        )
        self.assertEqual(len({slot["键名"] for slot in slots}), len(slots))
        self.assertEqual(len({(slot["轨道序号"], slot["片段"]) for slot in slots}), len(slots))


class SlotValidationTests(unittest.TestCase):
    def test_legacy_auto_slot_migrates_without_renaming_other_fields(self):
        draft = sample_draft()
        slots = template_health.analyze_slots(draft)
        slots["文字槽位"] = [{
            "键名": "文字位1", "轨道类型": "text", "轨道序号": 0,
            "片段": [0, 1], "文案要求": "旧要求"}]
        repaired, groups = template_health.repair_slots(slots, draft, "科技")
        self.assertEqual(groups, ["文字槽位"])
        self.assertEqual([s["键名"] for s in repaired["文字槽位"]],
                         ["文字位1", "文字位1_片段2"])
        self.assertEqual([s["片段"] for s in repaired["文字槽位"]], [[0], [1]])
        again, groups = template_health.repair_slots(repaired, draft, "科技")
        self.assertEqual(again, repaired)
        self.assertEqual(groups, [])

    def test_duplicate_targets_and_missing_track_are_rejected(self):
        slots = template_health.analyze_slots(sample_draft())
        for slot in slots["素材槽位"][4:]:
            slot["轨道序号"] = 0

        errors = template_health.validate_slots(slots, sample_draft())

        self.assertTrue(any("重复目标" in error for error in errors))
        self.assertTrue(any("漏掉" in error for error in errors))

    def test_repair_keeps_valid_custom_text_slots(self):
        draft = sample_draft()
        bad_slots = {
            "类型": "科技",
            "文字槽位": [
                {
                    "键名": "上屏标题", "轨道类型": "text", "轨道序号": 0,
                    "片段": [0], "文案要求": "不超过8个字",
                },
                {
                    "键名": "下屏标题", "轨道类型": "text", "轨道序号": 0,
                    "片段": [1], "文案要求": "不超过10个字",
                },
            ],
            "素材槽位": [
                {"键名": f"主视频{index + 1}", "轨道类型": "video", "轨道序号": 0,
                 "片段": index}
                for index in range(4)
            ] + [
                {"键名": f"贴片视频{index + 1}", "轨道类型": "video", "轨道序号": 0,
                 "片段": index}
                for index in range(3)
            ],
        }

        repaired, groups = template_health.repair_slots(bad_slots, draft, "科技")

        self.assertEqual(groups, ["素材槽位"])
        self.assertEqual(repaired["文字槽位"], bad_slots["文字槽位"])
        self.assertEqual([slot["轨道序号"] for slot in repaired["素材槽位"][-3:]], [1, 1, 1])
        self.assertEqual(template_health.validate_slots(repaired, draft), [])


class FakeCrypto:
    def decrypt(self, data):
        if data == b"unsupported":
            raise RuntimeError("模拟不支持的加密版本")
        return data

    def encrypt(self, data):
        return data


class PreflightTests(unittest.TestCase):
    def test_preflight_repairs_slots_and_quarantines_unreadable_template(self):
        with tempfile.TemporaryDirectory() as root:
            registry = [
                {"名字": "可修复", "类型": "科技", "使用次数": 0},
                {"名字": "高版本", "类型": "科技", "使用次数": 0},
            ]
            reg.save_registry(root, registry)
            draft = sample_draft()
            bad_slots = template_health.analyze_slots(draft)
            for slot in bad_slots["素材槽位"][4:]:
                slot["轨道序号"] = 0
            bad_slots["类型"] = "科技"

            for name, content in (("可修复", json.dumps(draft).encode("utf-8")),
                                  ("高版本", b"unsupported")):
                draft_dir = reg.template_draft_dir(root, name)
                os.makedirs(draft_dir, exist_ok=True)
                with open(os.path.join(draft_dir, "draft_content.json"), "wb") as handle:
                    handle.write(content)
            with open(os.path.join(reg.template_dir(root, "可修复"), "slots.json"),
                      "w", encoding="utf-8") as handle:
                json.dump(bad_slots, handle, ensure_ascii=False)

            result = template_health.preflight_templates(root, FakeCrypto())

            self.assertEqual(result["valid"], ["可修复"])
            self.assertEqual([item["name"] for item in result["disabled"]], ["高版本"])
            self.assertEqual(result["repaired"][0]["groups"], ["素材槽位"])
            repaired = reg.load_slots(root, "可修复")
            self.assertEqual(template_health.validate_slots(repaired, draft), [])
            updated = reg.load_registry(root)
            self.assertTrue(reg.find_entry(updated, "可修复")["启用"])
            self.assertFalse(reg.find_entry(updated, "高版本")["启用"])


if __name__ == "__main__":
    unittest.main()
