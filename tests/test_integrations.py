"""Offline contract and boundary tests. No real credentials or service requests."""

import copy
import http.client
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

from news_video_batch.config import ARK_ENDPOINT, load_config, validate_config, validate_connection_config
from news_video_batch.domain import ValidationError
from news_video_batch.providers import (
    DingTalkNewsSource, DoubaoModel, LocalNewsSource, OfflineModel, _NoRedirect, _post_json,
)


NEWS = {"id": "fixture-1", "title": "Library opens", "summary": "Doors opened. Readers arrived.",
        "source": "Original fictional fixture", "date": "2026-01-01"}
TEMPLATE = {"slots": [
    {"id": "brand", "mode": "fixed", "text": "Sample", "purpose": "brand", "order": 1, "allow_repeat": True},
    {"id": "lead", "mode": "generated", "purpose": "title", "order": 2},
    {"id": "first", "mode": "generated", "purpose": "body", "order": 3},
    {"id": "second", "mode": "generated", "purpose": "body", "order": 4},
]}


def ding_config(**updates):
    cfg = load_config(environ={})["dingtalk"]
    cfg.update({"app_key": "test-app", "app_secret": "test-secret", "base_id": "test-base",
                "sheet_id": "test-sheet", "operator_id": "test-operator"})
    cfg.update(updates)
    return cfg


def doubao_config(**updates):
    cfg = load_config(environ={})["doubao"]
    cfg.update({"api_key": "test-key", "model": "test-model"})
    cfg.update(updates)
    return cfg


def record(identifier="fixture-1", **updates):
    fields = {key: value for key, value in NEWS.items() if key != "id"}
    fields.update(updates)
    return {"id": identifier, "fields": fields}


class ConfigTests(unittest.TestCase):
    def test_no_implicit_file_read_and_no_network(self):
        with patch("pathlib.Path.open", side_effect=AssertionError("must not read")), patch("urllib.request.build_opener", side_effect=AssertionError("must not connect")):
            cfg = load_config(environ={})
            validate_connection_config(cfg)
        self.assertEqual(cfg["doubao"]["api_key"], "")

    def test_environment_override_and_explicit_empty_clear(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "config.local.json"
            path.write_text(json.dumps({"doubao": {"api_key": "test-local", "model": "test-model"}}), encoding="utf-8")
            cfg = load_config(path, {"NVB_DOUBAO_API_KEY": "test-env", "NVB_DOUBAO_MODEL": ""})
        self.assertEqual(cfg["doubao"]["api_key"], "test-env")
        self.assertEqual(cfg["doubao"]["model"], "")

    def test_strict_types_and_unknown_fields(self):
        cases = [[], {"unknown": "value"}, {"schema_version": True}, {"schema_version": 2},
                 {"doubao": {"unknown": "secret"}}, {"doubao": None},
                 {"dingtalk": {"field_mapping": {"summary": ""}}},
                 {"dingtalk": {"page_size": True}}, {"dingtalk": {"max_pages": 0}},
                 {"doubao": {"timeout_seconds": float("nan")}}, {"doubao": {"timeout_seconds": 0}},
                 {"doubao": {"max_tokens": "4096"}}, {"doubao": {"api_key": "test-" + "\nheader"}},
                 {"doubao": {"endpoint": "https://ark.cn-beijing.volces.com.attacker.example/api/v3/chat/completions"}}]
        for value in cases:
            with self.subTest(value=value), self.assertRaises(ValidationError):
                validate_config(value)

    def test_duplicate_keys_and_oversized_file_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "config.local.json"
            for contents in ('{"doubao":{},"doubao":{}}', " " * 65537):
                path.write_text(contents, encoding="utf-8")
                with self.assertRaises(ValidationError):
                    load_config(path, {})

    def test_doctor_requires_selected_online_config_without_network(self):
        with patch("urllib.request.build_opener", side_effect=AssertionError("must not connect")):
            cfg = load_config(environ={})
            with self.assertRaisesRegex(ValidationError, "app_key"):
                validate_connection_config(cfg, source="dingtalk")
            with self.assertRaisesRegex(ValidationError, "api_key"):
                validate_connection_config(cfg, model="doubao")

    def test_missing_file_error_does_not_disclose_path(self):
        with self.assertRaises(ValidationError) as caught:
            load_config(Path("private-account-test/missing.json"), {})
        self.assertNotIn("private-account-test", str(caught.exception))


class TransportTests(unittest.TestCase):
    def test_post_uses_timeout_and_blocks_redirect_handler(self):
        with patch("urllib.request.build_opener") as build:
            response = build.return_value.open.return_value.__enter__.return_value
            response.status = 200
            response.read.return_value = b'{"ok":true}'
            result = _post_json(ARK_ENDPOINT, {"prompt": "fixture"}, {"Authorization": "Bearer test-key"}, 17, "Test")
            self.assertTrue(result["ok"])
            self.assertIsInstance(build.call_args.args[0], _NoRedirect)
            self.assertEqual(build.return_value.open.call_args.kwargs, {"timeout": 17})
            self.assertEqual(response.read.call_args.args, (4 * 1024 * 1024 + 1,))

    def test_no_redirect_is_followed_even_same_origin(self):
        request = urllib.request.Request(ARK_ENDPOINT, headers={"Authorization": "Bearer test-key"})
        handler = _NoRedirect()
        for destination in (ARK_ENDPOINT + "/redirect", "https://attacker.example", "http://attacker.example"):
            for status in (301, 302, 303, 307, 308):
                with self.subTest(destination=destination, status=status):
                    self.assertIsNone(handler.redirect_request(request, None, status, "redirect", {}, destination))

    def test_service_exception_text_never_exposed(self):
        marker = "SECRET-test-marker"
        failures = [TimeoutError(marker), urllib.error.URLError(marker),
                    http.client.IncompleteRead(marker.encode(), 200),
                    urllib.error.HTTPError("https://private.example/" + marker, 403, marker, {}, io.BytesIO(marker.encode()))]
        for failure in failures:
            with self.subTest(error=type(failure).__name__), patch("urllib.request.build_opener") as build:
                build.return_value.open.side_effect = failure
                with self.assertRaises(ValidationError) as caught:
                    _post_json(ARK_ENDPOINT, {}, {}, 5, "Test")
                self.assertNotIn(marker, str(caught.exception))

    def test_bad_and_oversized_responses_fail_closed(self):
        for raw in (b"not-json", b"[]", b'\xff', b'{"x":1,"x":2}', b" " * (4 * 1024 * 1024 + 1)):
            with self.subTest(size=len(raw)), patch("urllib.request.build_opener") as build:
                response = build.return_value.open.return_value.__enter__.return_value
                response.status, response.read.return_value = 200, raw
                with self.assertRaises(ValidationError):
                    _post_json(ARK_ENDPOINT, {}, {}, 5, "Test")


class SourceTests(unittest.TestCase):
    def test_local_file_uses_shared_news_validation(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "news.json"
            path.write_text(json.dumps([NEWS]), encoding="utf-8")
            self.assertEqual(LocalNewsSource(path).load(), [NEWS])

    def test_dingtalk_pagination_mapping_and_encoded_identifiers(self):
        mapping = load_config(environ={})["dingtalk"]["field_mapping"]
        mapping["title"] = "headline"
        pages = [{"accessToken": "test-token"},
                 {"records": [record(headline="Headline")], "hasMore": True, "nextToken": "next-page"},
                 {"records": [record("fixture-2", headline="Second")], "hasMore": False}]
        with patch("news_video_batch.providers._post_json", side_effect=pages) as post:
            rows = DingTalkNewsSource(ding_config(sheet_id="test sheet/#", operator_id="test-&operator", field_mapping=mapping)).load()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["title"], "Headline")
        self.assertIn("test%20sheet%2F%23", post.call_args_list[1].args[0])
        self.assertIn("test-%26operator", post.call_args_list[1].args[0])
        self.assertEqual(post.call_args_list[2].args[1]["nextToken"], "next-page")
        self.assertEqual(post.call_args_list[1].args[2], {"x-acs-dingtalk-access-token": "test-token"})

    def test_dingtalk_stops_on_repeated_tokens_or_page_limit(self):
        looping = [{"accessToken": "test-token"},
                   {"records": [record()], "hasMore": True, "nextToken": "loop"},
                   {"records": [record("fixture-2")], "hasMore": True, "nextToken": "loop"}]
        with patch("news_video_batch.providers._post_json", side_effect=looping), self.assertRaisesRegex(ValidationError, "repeated"):
            DingTalkNewsSource(ding_config()).load()
        with patch("news_video_batch.providers._post_json", side_effect=looping[:2]), self.assertRaisesRegex(ValidationError, "max_pages"):
            DingTalkNewsSource(ding_config(max_pages=1)).load()

    def test_dingtalk_rejects_malformed_duplicate_or_unsupported_data(self):
        pages = [{"records": [], "hasMore": "false"}, {"records": [{}], "hasMore": False},
                 {"records": [record(), record()], "hasMore": False},
                 {"records": [record(), record("FIXTURE-1")], "hasMore": False},
                 {"records": [record(title=[{"text": "rich text unsupported"}])], "hasMore": False},
                 {"records": [record(date="invalid")], "hasMore": False},
                 {"records": [record("../escape")], "hasMore": False},
                 {"records": [record("CON")], "hasMore": False},
                 {"records": [], "hasMore": True}]
        for page in pages:
            with self.subTest(page=page), patch("news_video_batch.providers._post_json", side_effect=[{"accessToken": "test-token"}, page]), self.assertRaises(ValidationError):
                DingTalkNewsSource(ding_config()).load()


class ModelTests(unittest.TestCase):
    def test_offline_fixture_requires_exact_generated_keys(self):
        fixture = {"lead": "A", "first": "B", "second": "C"}
        news = dict(NEWS, demo_texts=fixture)
        result = OfflineModel().generate(news, TEMPLATE)
        self.assertEqual(result, fixture)
        self.assertIsNot(result, fixture)
        news["demo_texts"] = {**fixture, "brand": "changed"}
        with self.assertRaises(ValidationError):
            OfflineModel().generate(news, TEMPLATE)

    def test_offline_excerpts_preserve_order_without_truncation_or_padding(self):
        template = copy.deepcopy(TEMPLATE)
        template["slots"][2]["max_chars"] = 2
        self.assertEqual(OfflineModel().generate(NEWS, template),
                         {"lead": "Library opens", "first": "Doors opened.", "second": "Readers arrived."})
        with self.assertRaisesRegex(ValidationError, "too few sentences"):
            OfflineModel().generate(dict(NEWS, summary="Only one sentence."), template)

    def test_doubao_only_requests_generated_keys_and_sends_news_without_fixture(self):
        result = {"lead": "A", "first": "B", "second": "C"}
        response = {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(result)}}]}
        with patch("news_video_batch.providers._post_json", return_value=response) as post:
            actual = DoubaoModel(doubao_config()).generate(dict(NEWS, demo_texts={"secret_fixture": "unshared"}), TEMPLATE)
        self.assertEqual(actual, result)
        payload = post.call_args.args[1]
        self.assertFalse(payload["stream"])
        user_input = json.loads(payload["messages"][1]["content"])
        self.assertNotIn("demo_texts", user_input["news"])
        self.assertEqual({slot["id"] for slot in user_input["generated_slots"]}, set(result))

    def test_doubao_rejects_truncated_or_inexact_response(self):
        contents = ['{"lead":"A"}', '{"lead":"A","first":"B","second":"C","brand":"oops"}',
                    '```json\n{}\n```', '{"lead":"A","lead":"B"}', '[]', 'null']
        responses = [{"choices": [{"finish_reason": "stop", "message": {"content": value}}]} for value in contents]
        responses += [{"choices": []}, {"choices": [{"finish_reason": "length", "message": {"content": "{}"}}]}]
        for response in responses:
            with self.subTest(response=response), patch("news_video_batch.providers._post_json", return_value=response), self.assertRaises(ValidationError):
                DoubaoModel(doubao_config()).generate(NEWS, TEMPLATE)


if __name__ == "__main__":
    unittest.main()
