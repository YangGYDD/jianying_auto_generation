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

import automation  # noqa: E402


class FakeState:
    def __init__(self, root):
        self.root = root
        self.values = {}

    def get(self, key):
        return self.values.get(key)

    def mark(self, key, record, status, **details):
        self.values[key] = {"status": status, "record": record, **details}

    def close(self):
        pass


class AutomationRunTests(unittest.TestCase):
    def _run_scenario(self, records, target=5, fetch_fail=(), input_fail=(), draft_fail=()):
        fetch_fail = set(fetch_fail)
        input_fail = set(input_fail)
        draft_fail = set(draft_fail)
        capture = {
            "fetch_order": [], "entries": [], "meta": [], "counts": {},
            "draft_batches": [],
        }

        normalized_records = []
        for source in records:
            record = dict(source)
            record.setdefault("news_categories", ["电池行业新闻"])
            record.setdefault("news_category", "、".join(record["news_categories"]))
            normalized_records.append(record)

        cfg = {
            "dingtalk_news_table": {"字段": {}},
            "automation": {
                "request_timeout_seconds": 1,
                "max_news_per_run": target,
                "max_article_chars": 1000,
                "skip_duplicate_news": False,
                "template_mode": "single",
                "default_template": "默认",
                "allowed_news_categories": ["电池行业新闻"],
            },
        }

        class FakeDingTalkClient:
            def __init__(self, table_cfg, timeout):
                pass

            def list_records(self, max_results, field_ids):
                return normalized_records

        def fake_fetch(url, timeout, max_chars):
            title = url.rsplit("/", 1)[-1]
            capture["fetch_order"].append(title)
            if title in fetch_fail:
                raise RuntimeError("模拟网页失败")
            return {"title": title, "source": "测试", "date": "", "summary": "正文"}

        def fake_build_inputs(records_file, root, **kwargs):
            with open(records_file, "r", encoding="utf-8") as handle:
                batch = json.load(handle)
            generated = []
            failed = []
            for record in batch:
                title = record["title"]
                if title in input_fail:
                    failed.append({"record": record, "error": "模拟文案失败", "template": "默认"})
                    continue
                folder = os.path.join(root, "模拟输入", title)
                record["content_category"] = "电池"
                generated.append({
                    "record": record,
                    "folder": folder,
                    "folder_name": title,
                    "template": "默认",
                    "content_category": "电池",
                })
            return {
                "generated_items": generated,
                "failed_items": failed,
                "skipped_items": [],
            }

        class FakeBatchRunner:
            def __init__(self, root):
                self.drafts_dir = os.path.join(root, "模拟剪映草稿")
                self.last_results = []

            def run(self, folders):
                names = [os.path.basename(folder) for folder in folders]
                capture["draft_batches"].append(names)
                self.last_results = [
                    (name, "失败: 模拟草稿失败" if name in draft_fail else "成功", [])
                    for name in names
                ]
                return 1 if any(name in draft_fail for name in names) else 0

        def fake_report(root, run_mode, entries, meta, count_overrides=None):
            capture["entries"] = [dict(entry) for entry in entries]
            capture["meta"] = list(meta)
            counts = {}
            for entry in entries:
                counts[entry["status"]] = counts.get(entry["status"], 0) + 1
            counts.update(count_overrides or {})
            capture["counts"] = counts
            return os.path.join(root, "模拟报告.txt"), counts

        with tempfile.TemporaryDirectory() as root, \
                mock.patch.object(automation, "load_config", return_value=cfg), \
                mock.patch.object(automation, "DingTalkClient", FakeDingTalkClient), \
                mock.patch.object(automation, "normalize_records", side_effect=lambda rows, fields: rows), \
                mock.patch.object(automation, "AutomationState", FakeState), \
                mock.patch.object(automation, "_validate_template", side_effect=lambda root, name: name), \
                mock.patch.object(automation, "fetch_news", side_effect=fake_fetch), \
                mock.patch.object(automation, "build_inputs", side_effect=fake_build_inputs), \
                mock.patch.object(automation, "BatchRunner", FakeBatchRunner), \
                mock.patch.object(automation, "_report", side_effect=fake_report):
            exit_code = automation.run(root, max_news_override=target)
        return exit_code, capture

    def test_failures_are_backfilled_until_five_drafts_succeed(self):
        records = [
            {
                "title": "分类为空", "link": "https://news/Y", "date": "2026-09-03",
                "news_categories": [], "news_category": "",
            },
            {
                "title": "其他分类", "link": "https://news/X", "date": "2026-09-02",
                "news_categories": ["客户行业新闻"], "news_category": "客户行业新闻",
            },
            {"title": "H", "link": "https://news/H", "date": "2026-08-24"},
            {"title": "I", "link": "https://news/I", "date": "2026-08-23"},
            {"title": "无效", "link": "https://news/INVALID", "date": "无法识别"},
            {"title": "C", "link": "https://news/C", "date": "2026-08-29"},
            {"title": "A", "link": "https://news/A", "date": "2026-08-31"},
            {"title": "F", "link": "https://news/F", "date": "2026-08-26"},
            {"title": "D", "link": "https://news/D", "date": "2026-08-28"},
            {"title": "B", "link": "https://news/B", "date": "2026-08-30"},
            {"title": "G", "link": "https://news/G", "date": "2026-08-25"},
            {"title": "E", "link": "https://news/E", "date": "2026-08-27"},
        ]

        exit_code, result = self._run_scenario(
            records,
            fetch_fail={"A"},
            input_fail={"B"},
            draft_fail={"C"},
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(result["fetch_order"], list("ABCDEFGH"))
        statuses = [entry["status"] for entry in result["entries"]]
        self.assertEqual(statuses.count("invalid_date"), 1)
        self.assertEqual(statuses.count("fetch_failed"), 1)
        self.assertEqual(statuses.count("input_failed"), 1)
        self.assertEqual(statuses.count("draft_failed"), 1)
        self.assertEqual(statuses.count("success"), 5)
        self.assertEqual(result["counts"]["category_filtered"], 2)
        self.assertTrue(all(entry.get("content_category") == "电池"
                            for entry in result["entries"] if entry["status"] == "success"))
        self.assertEqual(result["draft_batches"], [["C", "D", "E", "F"], ["G", "H"]])
        self.assertTrue(any("已达到目标" in item for item in result["meta"]))

    def test_exhaustion_reports_fewer_than_target_as_failure(self):
        records = [
            {"title": "A", "link": "https://news/A", "date": "2026-08-31"},
            {"title": "B", "link": "https://news/B", "date": "2026-08-30"},
            {"title": "C", "link": "https://news/C", "date": "2026-08-29"},
        ]

        exit_code, result = self._run_scenario(records, target=5, draft_fail={"B"})

        self.assertEqual(exit_code, 1)
        statuses = [entry["status"] for entry in result["entries"]]
        self.assertEqual(statuses.count("success"), 2)
        self.assertEqual(statuses.count("draft_failed"), 1)
        self.assertTrue(any("目标 5 个，实际成功 2 个" in item for item in result["meta"]))


class PublishTimeTests(unittest.TestCase):
    def test_invalid_dates_are_removed_and_valid_dates_are_descending(self):
        records = [
            {"title": "日期", "date": "2026年08月30日"},
            {"title": "空", "date": ""},
            {"title": "时间", "date": "2026-08-31 08:30:00"},
            {"title": "错误", "date": "昨天"},
            {"title": "紧随", "date": "20260829"},
        ]

        valid, invalid = automation.partition_by_publish_time(records)

        self.assertEqual([record["title"] for record in valid], ["时间", "日期", "紧随"])
        self.assertEqual([record["title"] for record in invalid], ["空", "错误"])


class NewsCategoryFilterTests(unittest.TestCase):
    def test_exact_single_or_multi_select_match_is_required(self):
        records = [
            {"title": "单选", "news_categories": ["电池行业新闻"]},
            {"title": "多选", "news_categories": ["客户行业新闻", "电池行业新闻"]},
            {"title": "相似文字", "news_categories": ["电池行业新闻扩展"]},
            {"title": "其他", "news_categories": ["客户行业新闻"]},
            {"title": "空", "news_categories": []},
        ]

        matched, skipped = automation.partition_by_news_category(records, ["电池行业新闻"])

        self.assertEqual([record["title"] for record in matched], ["单选", "多选"])
        self.assertEqual(
            [record["title"] for record in skipped], ["相似文字", "其他", "空"]
        )


class TemplateFallbackTests(unittest.TestCase):
    def test_disabled_selected_template_falls_back_to_default(self):
        with tempfile.TemporaryDirectory() as root:
            automation.reg.save_registry(root, [
                {"名字": "默认", "类型": "默认", "使用次数": 0, "启用": True},
                {
                    "名字": "坏模板", "类型": "科技", "使用次数": 0,
                    "启用": False, "停用原因": "轨道重复",
                },
            ])

            selected, note = automation._resolve_template(root, "坏模板")

            self.assertEqual(selected, "默认")
            self.assertIn("已自动改用 [默认]", note)

    def test_postcheck_quarantine_retries_same_news_with_fallback_template(self):
        records = [{
            "title": "A", "link": "https://news/A", "date": "2026-09-03",
            "news_categories": ["电池行业新闻"], "news_category": "电池行业新闻",
        }]
        cfg = {
            "dingtalk_news_table": {"字段": {}},
            "automation": {
                "request_timeout_seconds": 1,
                "max_news_per_run": 1,
                "max_article_chars": 1000,
                "skip_duplicate_news": False,
                "template_mode": "single",
                "default_template": "坏模板",
                "allowed_news_categories": ["电池行业新闻"],
            },
        }
        used_templates = []
        captured_entries = []

        class FakeDingTalkClient:
            def __init__(self, table_cfg, timeout):
                pass

            def list_records(self, max_results, field_ids):
                return records

        def fake_build_inputs(records_file, root, template_override=None, **_kwargs):
            with open(records_file, "r", encoding="utf-8") as handle:
                record = json.load(handle)[0]
            used_templates.append(template_override)
            folder_name = f"A_{template_override}"
            return {
                "generated_items": [{
                    "record": record,
                    "folder": os.path.join(root, "模拟输入", folder_name),
                    "folder_name": folder_name,
                    "template": template_override,
                }],
                "failed_items": [],
                "skipped_items": [],
            }

        class QuarantiningRunner:
            def __init__(self, root):
                self.root = root
                self.drafts_dir = os.path.join(root, "模拟剪映草稿")
                self.template_health = {}
                self.last_results = []

            def run(self, folders):
                name = os.path.basename(folders[0])
                if name.endswith("坏模板"):
                    registry = automation.reg.load_registry(self.root)
                    entry = automation.reg.find_entry(registry, "坏模板")
                    entry["启用"] = False
                    entry["停用原因"] = "生成后核验失败"
                    automation.reg.save_registry(self.root, registry)
                    self.last_results = [(name, "失败: 生成后核验失败", [])]
                    return 1
                self.last_results = [(name, "成功", ["素材核验通过"])]
                return 0

        def fake_report(root, run_mode, entries, meta, count_overrides=None):
            captured_entries.extend(dict(entry) for entry in entries)
            return os.path.join(root, "报告.txt"), {}

        with tempfile.TemporaryDirectory() as root:
            automation.reg.save_registry(root, [
                {"名字": "默认", "类型": "默认", "使用次数": 0, "启用": True},
                {"名字": "坏模板", "类型": "科技", "使用次数": 0, "启用": True},
            ])
            with mock.patch.object(automation, "load_config", return_value=cfg), \
                    mock.patch.object(automation, "DingTalkClient", FakeDingTalkClient), \
                    mock.patch.object(automation, "normalize_records", side_effect=lambda rows, fields: rows), \
                    mock.patch.object(automation, "AutomationState", FakeState), \
                    mock.patch.object(automation, "fetch_news", return_value={
                        "title": "A", "source": "测试", "date": "", "summary": "正文",
                    }), \
                    mock.patch.object(automation, "build_inputs", side_effect=fake_build_inputs), \
                    mock.patch.object(automation, "BatchRunner", QuarantiningRunner), \
                    mock.patch.object(automation, "_report", side_effect=fake_report):
                exit_code = automation.run(root, max_news_override=1)

        self.assertEqual(exit_code, 0)
        self.assertEqual(used_templates, ["坏模板", "默认"])
        self.assertEqual([entry["status"] for entry in captured_entries],
                         ["draft_failed", "success"])


if __name__ == "__main__":
    unittest.main()
