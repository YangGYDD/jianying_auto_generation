import copy
import json
import tempfile
import unittest
from pathlib import Path

from news_video_batch.domain import (
    ValidationError, load_news, load_template, read_json, safe_id,
    validate_news, validate_template, validate_texts,
)


DATA = Path(__file__).resolve().parents[1] / "src/news_video_batch/data"


class DomainTests(unittest.TestCase):
    def setUp(self):
        self.template = load_template(DATA / "template.json")
        self.news = load_news(DATA / "news.json")
        self.texts = {s["id"]: s["text"] for s in self.template["slots"] if s["mode"] == "fixed"}
        self.texts.update(self.news[0]["demo_texts"])

    def test_original_fixture_has_independent_bodies_and_repeatable_brand(self):
        self.assertEqual(validate_texts(self.template, self.texts), self.texts)
        self.assertEqual(self.texts["brand_open"], self.texts["brand_close"])
        self.assertNotEqual(self.texts["body_first"], self.texts["body_second"])

    def test_fixed_brand_cannot_be_overridden(self):
        self.texts["brand_open"] = "另一品牌"
        with self.assertRaisesRegex(ValidationError, "fixed text"):
            validate_texts(self.template, self.texts)

    def test_generated_duplicate_normalizes_spaces_and_newlines(self):
        self.texts["body_second"] = self.texts["body_first"]
        with self.assertRaisesRegex(ValidationError, "Duplicate content"):
            validate_texts(self.template, self.texts)

    def test_repeat_requires_both_slots_to_opt_in(self):
        self.template["slots"][0]["allow_repeat"] = False
        with self.assertRaisesRegex(ValidationError, "both slots"):
            validate_texts(self.template, self.texts)

    def test_missing_and_extra_text_keys(self):
        for value in ({k: v for k, v in self.texts.items() if k != "headline"},
                      {**self.texts, "extra": "text"}):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                validate_texts(self.template, value)

    def test_limits_do_not_truncate_or_reflow(self):
        for key, value in (("headline", "长" * 17), ("body_first", "单行"),
                           ("body_first", "一\n二\n三"), ("body_first", "一" * 17 + "\n二"),
                           ("headline", " 标题"), ("headline", "标题\\n后文"), ("headline", "标\t题")):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                validate_texts(self.template, {**self.texts, key: value})

    def test_total_length_limit_independent_of_line_limit(self):
        self.template["slots"][3]["max_chars"] = 3
        with self.assertRaisesRegex(ValidationError, "total character"):
            validate_texts(self.template, self.texts)

    def test_subtitle_order_time_and_target_rules(self):
        for field, value in (("sequence_index", 5), ("start_ms", 4001),
                             ("track", 10), ("segment", 8), ("order", 6)):
            altered = copy.deepcopy(self.template)
            altered["slots"][6][field] = value
            with self.subTest(field=field), self.assertRaises(ValidationError):
                validate_template(altered)

    def test_duplicate_slot_and_target_rejected(self):
        for mutate in (lambda s: s.update(id="brand_open"),
                       lambda s: s.update(track=0, segment=0),
                       lambda s: s.update(order=1)):
            altered = copy.deepcopy(self.template)
            mutate(altered["slots"][1])
            with self.assertRaises(ValidationError):
                validate_template(altered)

    def test_boolean_is_not_integer_and_invalid_mode_rejected(self):
        for field, value in (("order", True), ("duration_ms", 0), ("start_ms", -1),
                             ("mode", "AI"), ("allow_repeat", "false"), ("exact_lines", 99)):
            altered = copy.deepcopy(self.template)
            altered["slots"][1][field] = value
            with self.subTest(field=field), self.assertRaises(ValidationError):
                validate_template(altered)

    def test_same_track_overlap_rejected(self):
        self.template["slots"][8]["start_ms"] = 5999
        with self.assertRaisesRegex(ValidationError, "overlap"):
            validate_template(self.template)

    def test_original_synthetic_regression_sizes_9_13_6(self):
        # These are fabricated contracts, not the three private business templates.
        for count in (9, 13, 6):
            base = self.template["slots"][1]
            slots = []
            for index in range(count):
                slot = {**base, "id": f"slot_{index}", "order": index + 1, "track": 0,
                        "segment": index, "start_ms": index * 1000, "duration_ms": 1000}
                slots.append(slot)
            template = {**self.template, "slots": slots}
            texts = {s["id"]: f"独立片段{i + 1}" for i, s in enumerate(slots)}
            with self.subTest(count=count):
                self.assertEqual(len(validate_texts(template, texts)), count)

    def test_news_device_names_traversal_case_collision_and_date(self):
        for identifier in ("../bad", "CON", "aux", "a/b", "a:b", "中文"):
            with self.subTest(identifier=identifier), self.assertRaises(ValidationError):
                safe_id(identifier)
        with self.assertRaises(ValidationError):
            validate_news([self.news[0], {**self.news[0], "id": "DEMO-LIBRARY"}])
        with self.assertRaises(ValidationError):
            validate_news([{**self.news[0], "date": "2026-02-30"}])

    def test_duplicate_json_keys_rejected_and_utf8_bom_supported(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "input.json"
            path.write_text('{"a":1,"a":2}', encoding="utf-8")
            with self.assertRaisesRegex(ValidationError, "duplicate key"):
                read_json(path)
            path.write_text(json.dumps(self.news, ensure_ascii=False), encoding="utf-8-sig")
            self.assertEqual(len(load_news(path)), 2)


if __name__ == "__main__":
    unittest.main()
