# -*- coding: utf-8 -*-
import json
import os
import sys
import tempfile
import unittest
from unittest import mock


ENGINE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ENGINE_DIR not in sys.path:
    sys.path.insert(0, ENGINE_DIR)

import dingtalk_client  # noqa: E402
import make_inputs  # noqa: E402
import news_text  # noqa: E402


class DingTalkChoiceTests(unittest.TestCase):
    def test_single_and_multi_select_values_are_preserved(self):
        raw_records = [
            {"fields": {"新闻分类": {"name": "电池行业新闻", "id": "one"}}},
            {"fields": {"新闻分类": [
                {"name": "客户行业新闻", "id": "two"},
                {"name": "电池行业新闻", "id": "one"},
            ]}},
            {"fields": {"新闻分类": None}},
        ]

        records = dingtalk_client.normalize_records(
            raw_records, {"筛选分类": "新闻分类"}
        )

        self.assertEqual(records[0]["news_categories"], ["电池行业新闻"])
        self.assertEqual(records[1]["news_categories"], ["客户行业新闻", "电池行业新闻"])
        self.assertEqual(records[1]["news_category"], "客户行业新闻、电池行业新闻")
        self.assertEqual(records[2]["news_categories"], [])


class ContentClassificationTests(unittest.TestCase):
    def test_duplicate_copy_is_retried_then_rejected_if_still_repeated(self):
        repeated = json.dumps({"正文1": "同一句", "正文2": "同一句"})
        distinct = json.dumps({"正文1": "首屏信息", "正文2": "后续信息"})
        args = {"record": {"title": "新闻", "summary": "内容"}, "cfg": {},
                "slot_specs": {"正文1": "首屏", "正文2": "次屏"}}
        with mock.patch.object(news_text, "_call_doubao", side_effect=[repeated, distinct]) as call:
            result = news_text.summarize_record(**args)
            self.assertNotEqual(result["正文1"], result["正文2"])
            self.assertEqual(call.call_count, 2)
        with mock.patch.object(news_text, "_call_doubao", return_value=repeated) as call:
            with self.assertRaisesRegex(ValueError, "连续返回重复文案"):
                news_text.summarize_record(**args)
            self.assertEqual(call.call_count, 2)

    def test_empty_and_non_text_copy_is_rejected(self):
        for value in (None, "", [], {}):
            with self.subTest(value=value), mock.patch.object(
                    news_text, "_call_doubao", return_value=json.dumps({"标题": value})):
                with self.assertRaisesRegex(ValueError, "缺少有效文字"):
                    news_text.summarize_record({}, cfg={}, slot_specs={"标题": "短标题"})

    def _summarize(self, reply):
        with mock.patch.object(news_text, "_call_doubao", return_value=json.dumps(
                reply, ensure_ascii=False)) as call:
            result = news_text.summarize_record(
                {"title": "测试", "summary": "测试正文"},
                cfg={},
                slot_specs={"大标题": "不超过12个字"},
            )
        self.assertEqual(call.call_count, 1)
        self.assertIn("锂电行业", call.call_args.args[1])
        self.assertIn("新能源", call.call_args.args[1])
        return result

    def test_valid_category_is_kept_in_the_existing_copy_request(self):
        result = self._summarize({"大标题": "电池突破", "内容分类": "电池"})
        self.assertEqual(result["内容分类"], "电池")

    def test_missing_or_invalid_category_falls_back_to_lithium_industry(self):
        for value in (None, "其他分类", ""):
            with self.subTest(value=value):
                reply = {"大标题": "行业动态"}
                if value is not None:
                    reply["内容分类"] = value
                result = self._summarize(reply)
                self.assertEqual(result["内容分类"], "锂电行业")


class MaterialCategoryTests(unittest.TestCase):
    def test_content_category_drives_material_folder_not_template_type(self):
        registry = [{"名字": "默认", "类型": "默认", "使用次数": 0}]
        with tempfile.TemporaryDirectory() as root:
            records_file = os.path.join(root, "records.json")
            with open(records_file, "w", encoding="utf-8") as handle:
                json.dump([{
                    "seq": "1",
                    "title": "储能项目",
                    "source": "测试",
                    "date": "2026-09-01",
                    "summary": "正文",
                    "link": "https://example.com/news",
                    "_dedupe_key": "key-1",
                }], handle, ensure_ascii=False)

            with mock.patch.object(make_inputs, "load_config", return_value={"doubao": {}}), \
                    mock.patch.object(make_inputs.reg, "load_registry", return_value=registry), \
                    mock.patch.object(make_inputs.reg, "find_entry", return_value=registry[0]), \
                    mock.patch.object(make_inputs.reg, "load_slots", return_value={}), \
                    mock.patch.object(make_inputs.reg, "slot_specs_from_slots", return_value={"大标题": "标题"}), \
                    mock.patch.object(make_inputs.reg, "increment_template_use"), \
                    mock.patch.object(make_inputs.reg, "save_registry"), \
                    mock.patch.object(make_inputs, "summarize_record", return_value={
                        "大标题": "储能项目", "内容分类": "新能源",
                    }):
                result = make_inputs.build_inputs(
                    records_file, root, allow_existing=True, template_override="默认"
                )

            item = result["generated_items"][0]
            self.assertEqual(item["content_category"], "新能源")
            self.assertEqual(os.path.basename(os.path.dirname(item["folder"])), "新能源")
            with open(os.path.join(item["folder"], "类型.txt"), "r", encoding="utf-8") as handle:
                self.assertEqual(handle.read(), "新能源")
            with open(os.path.join(item["folder"], "info.txt"), "r", encoding="utf-8-sig") as handle:
                self.assertIn("内容分类=新能源", handle.read())

    def test_random_mode_excludes_disabled_templates(self):
        registry = [
            {"名字": "健康模板", "类型": "默认", "使用次数": 0, "启用": True},
            {"名字": "停用模板", "类型": "默认", "使用次数": 0, "启用": False},
        ]
        with tempfile.TemporaryDirectory() as root:
            records_file = os.path.join(root, "records.json")
            with open(records_file, "w", encoding="utf-8") as handle:
                json.dump([{"seq": "1", "title": "测试", "summary": "正文"}], handle,
                          ensure_ascii=False)

            with mock.patch.object(make_inputs, "load_config", return_value={"doubao": {}}), \
                    mock.patch.object(make_inputs.reg, "load_registry", return_value=registry), \
                    mock.patch.object(make_inputs.reg, "load_slots", return_value={}), \
                    mock.patch.object(make_inputs.reg, "slot_specs_from_slots", return_value={"大标题": "标题"}), \
                    mock.patch.object(make_inputs.reg, "increment_template_use"), \
                    mock.patch.object(make_inputs.reg, "save_registry") as save_registry, \
                    mock.patch.object(make_inputs.random, "shuffle"), \
                    mock.patch.object(make_inputs, "summarize_record", return_value={
                        "大标题": "测试", "内容分类": "电池",
                    }):
                result = make_inputs.build_inputs(
                    records_file, root, allow_existing=True, random_templates=True
                )

            self.assertEqual(result["generated_items"][0]["template"], "健康模板")
            saved_registry = save_registry.call_args.args[1]
            self.assertEqual([entry["名字"] for entry in saved_registry], ["健康模板", "停用模板"])


if __name__ == "__main__":
    unittest.main()
