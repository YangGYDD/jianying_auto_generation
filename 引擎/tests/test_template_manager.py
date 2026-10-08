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

import template_manager  # noqa: E402
import template_registry as reg  # noqa: E402


class DeleteTemplateTests(unittest.TestCase):
    @staticmethod
    def _write_registry(root, entries):
        os.makedirs(reg.lib_dir(root), exist_ok=True)
        reg.save_registry(root, entries)

    def test_custom_template_removes_directory_and_registry_entry(self):
        with tempfile.TemporaryDirectory() as root:
            entries = [
                {"名字": "默认", "类型": "默认", "使用次数": 1},
                {"名字": "新闻模板", "类型": "默认", "使用次数": 2},
            ]
            self._write_registry(root, entries)
            custom_dir = reg.template_dir(root, "新闻模板")
            os.makedirs(custom_dir)
            with open(os.path.join(custom_dir, "slots.json"), "w", encoding="utf-8") as handle:
                json.dump({}, handle)

            result = template_manager.delete_template(root, "新闻模板")

            self.assertTrue(result["directory_existed"])
            self.assertFalse(os.path.exists(custom_dir))
            self.assertEqual([item["名字"] for item in reg.load_registry(root)], ["默认"])

    def test_system_default_template_is_protected(self):
        with tempfile.TemporaryDirectory() as root:
            entries = [
                {"名字": "默认", "类型": "默认", "使用次数": 0},
                {"名字": "新闻模板", "类型": "默认", "使用次数": 0},
            ]
            self._write_registry(root, entries)

            with self.assertRaises(template_manager.TemplateManagementError):
                template_manager.delete_template(root, "默认")

            self.assertEqual(len(reg.load_registry(root)), 2)

    def test_configured_default_template_is_protected(self):
        with tempfile.TemporaryDirectory() as root:
            entries = [
                {"名字": "默认", "类型": "默认", "使用次数": 0},
                {"名字": "定时模板", "类型": "默认", "使用次数": 0},
            ]
            self._write_registry(root, entries)
            engine_dir = os.path.join(root, "引擎")
            os.makedirs(engine_dir)
            with open(os.path.join(engine_dir, "config.json"), "w", encoding="utf-8") as handle:
                json.dump({"automation": {"default_template": "定时模板"}}, handle)

            with self.assertRaises(template_manager.TemplateManagementError):
                template_manager.delete_template(root, "定时模板")

    def test_missing_template_directory_can_be_removed_from_registry(self):
        with tempfile.TemporaryDirectory() as root:
            entries = [
                {"名字": "默认", "类型": "默认", "使用次数": 0},
                {"名字": "缺失模板", "类型": "默认", "使用次数": 0},
            ]
            self._write_registry(root, entries)

            result = template_manager.delete_template(root, "缺失模板")

            self.assertFalse(result["directory_existed"])
            self.assertEqual([item["名字"] for item in reg.load_registry(root)], ["默认"])


class TemplateManagerMenuTests(unittest.TestCase):
    def test_register_option_routes_to_existing_registration_flow(self):
        with tempfile.TemporaryDirectory() as root, \
                mock.patch.object(template_manager, "ROOT", root), \
                mock.patch.object(template_manager.register_template, "main", return_value=0) as register, \
                mock.patch("builtins.input", return_value="1"):
            exit_code = template_manager.main()

        self.assertEqual(exit_code, 0)
        register.assert_called_once_with()
        self.assertEqual(template_manager.register_template.ROOT, root)

    def test_configure_option_sets_the_scheduled_template(self):
        with tempfile.TemporaryDirectory() as root:
            entries = [
                {"名字": "默认", "类型": "默认", "使用次数": 0, "启用": True},
                {"名字": "新闻模板", "类型": "默认", "使用次数": 0, "启用": True},
            ]
            os.makedirs(reg.template_dir(root, "新闻模板"))
            reg.save_registry(root, entries)
            engine_dir = os.path.join(root, "引擎")
            os.makedirs(engine_dir)
            config_path = os.path.join(engine_dir, "config.json")
            with open(config_path, "w", encoding="utf-8") as handle:
                json.dump({
                    "doubao": {"api_key": "test-keep-me"},
                    "automation": {"default_template": "默认", "max_news_per_run": 5},
                }, handle)

            with mock.patch.object(template_manager, "ROOT", root), \
                    mock.patch("builtins.input", side_effect=["3", "2"]):
                exit_code = template_manager.main()

            with open(config_path, "r", encoding="utf-8") as handle:
                config = json.load(handle)
            self.assertEqual(exit_code, 0)
            self.assertEqual(config["automation"]["default_template"], "新闻模板")
            self.assertEqual(config["automation"]["template_mode"], "single")
            self.assertEqual(config["automation"]["max_news_per_run"], 5)
            self.assertEqual(config["doubao"]["api_key"], "test-keep-me")


if __name__ == "__main__":
    unittest.main()
