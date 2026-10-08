# -*- coding: utf-8 -*-
"""钉钉多维表只读客户端。

使用内部应用 access token 读取指定表格，不执行任何写入操作。
"""
import json
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request


API_ROOT = "https://api.dingtalk.com"
TOKEN_PATH = "/v1.0/oauth2/accessToken"
RECORDS_PATH = "/v1.0/notable/bases/{base_id}/sheets/{table_id}/records/list"


class DingTalkError(RuntimeError):
    def __init__(self, message, code="", status_code=None):
        self.code = code or "DINGTALK_ERROR"
        self.status_code = status_code
        super().__init__(message)


def _redact(text, cfg):
    value = str(text or "")
    for key in (cfg.get("app_key", ""), cfg.get("app_secret", "")):
        if key:
            value = value.replace(key, "[已隐藏]")
    return value


class DingTalkClient:
    def __init__(self, cfg, timeout=30):
        self.cfg = cfg
        self.timeout = timeout
        self._token = None

    def _json_request(self, method, url, body=None, headers=None):
        request_headers = {"Accept": "application/json"}
        request_headers.update(headers or {})
        data = None
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            request_headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=request_headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8", errors="replace")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                detail = json.loads(raw)
                code = detail.get("code") or detail.get("errorCode") or "HTTP_ERROR"
                message = detail.get("message") or detail.get("errorMsg") or raw
            except (TypeError, ValueError):
                code, message = "HTTP_ERROR", raw or str(exc)
            message = _redact(message, self.cfg)
            if code == "Forbidden.AccessDenied.AccessTokenPermissionDenied" \
                    or "Notable.Base.Read.All" in message:
                message = (
                    "钉钉应用权限尚未生效：请在当前 appkey 对应应用的权限管理中开通 "
                    "Notable.Base.Read.All（多维表格读取），并发布/生效应用版本后再重试"
                )
            raise DingTalkError(message, code, exc.code) from None
        except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
            raise DingTalkError("网络连接钉钉失败: " + _redact(exc, self.cfg), "NETWORK_ERROR") from None
        except (ValueError, TypeError) as exc:
            raise DingTalkError("钉钉返回数据无法解析: " + str(exc), "INVALID_RESPONSE") from None

    def access_token(self):
        if self._token:
            return self._token
        app_key = self.cfg.get("app_key", "").strip()
        app_secret = self.cfg.get("app_secret", "").strip()
        if not app_key or not app_secret:
            raise DingTalkError("未配置钉钉应用凭证", "CONFIG_ERROR")
        data = self._json_request(
            "POST",
            API_ROOT + TOKEN_PATH,
            {"appKey": app_key, "appSecret": app_secret},
        )
        token = data.get("accessToken") or data.get("access_token")
        if not token:
            raise DingTalkError("钉钉未返回访问令牌", "TOKEN_ERROR")
        self._token = token
        return token

    @staticmethod
    def _records_from_payload(payload):
        if isinstance(payload, list):
            return payload
        if not isinstance(payload, dict):
            return []
        for key in ("records", "items"):
            if isinstance(payload.get(key), list):
                return payload[key]
        for key in ("data", "result"):
            nested = payload.get(key)
            if isinstance(nested, list):
                return nested
            if isinstance(nested, dict):
                found = DingTalkClient._records_from_payload(nested)
                if found:
                    return found
        return []

    @staticmethod
    def _next_page(payload):
        if not isinstance(payload, dict):
            return "", False
        for container in (payload, payload.get("data"), payload.get("result")):
            if not isinstance(container, dict):
                continue
            token = (container.get("nextPageToken") or container.get("nextToken")
                     or container.get("pageToken") or "")
            has_more = container.get("hasMore")
            if has_more is not None or token:
                if has_more is None:
                    has_more = bool(token)
                return str(token or ""), bool(has_more)
        return "", False

    def list_records(self, max_results=100, field_ids=None):
        base_id = self.cfg.get("base_id", "").strip()
        table_id = self.cfg.get("table_id", "").strip()
        operator_id = self.cfg.get("operator_id", "").strip()
        if not base_id or not table_id:
            raise DingTalkError("未配置钉钉 base_id 或 table_id", "CONFIG_ERROR")
        if not operator_id:
            raise DingTalkError("未配置钉钉 operator_id；请填写操作者的 unionId", "CONFIG_ERROR")
        page_token = ""
        all_records = []
        seen_tokens = set()
        while True:
            query = {"operatorId": operator_id}
            path = RECORDS_PATH.format(base_id=urllib.parse.quote(base_id, safe=""),
                                       table_id=urllib.parse.quote(table_id, safe=""))
            url = API_ROOT + path + "?" + urllib.parse.urlencode(query)
            body = {
                "maxResults": max(1, min(int(max_results), 100)),
                "nextToken": page_token,
            }
            selected_fields = [str(value).strip() for value in (field_ids or []) if str(value).strip()]
            if selected_fields:
                body["fieldIdOrNames"] = selected_fields[:100]
            payload = self._request_records_page(url, body)
            all_records.extend(self._records_from_payload(payload))
            next_token, has_more = self._next_page(payload)
            if not has_more or not next_token or next_token in seen_tokens:
                break
            seen_tokens.add(next_token)
            page_token = next_token
        return all_records

    @staticmethod
    def _is_retryable(exc):
        """钉钉偶发 internalError 时重试；权限和参数错误直接返回。"""
        if not isinstance(exc, DingTalkError):
            return False
        code = str(exc.code or "").lower()
        return (
            exc.status_code in (408, 425, 429, 500, 502, 503, 504)
            or code in {"internalerror", "serviceunavailable", "too_many_requests", "throttled"}
            or "qpslimit" in code
            or "internalerror" in code
        )

    def _request_records_page(self, url, body):
        """读取单页记录，处理钉钉接口的临时服务端故障。"""
        max_attempts = 4
        for attempt in range(1, max_attempts + 1):
            try:
                return self._json_request(
                    "POST", url, body=body,
                    headers={"x-acs-dingtalk-access-token": self.access_token()},
                )
            except DingTalkError as exc:
                if not self._is_retryable(exc) or attempt >= max_attempts:
                    raise
                delay = 2 ** (attempt - 1)
                print(f"钉钉读取暂时失败，{delay} 秒后自动重试（第 {attempt}/{max_attempts - 1} 次）")
                time.sleep(delay)


def _value_to_text(value):
    """兼容文本、链接字段、富文本数组和日期字段。"""
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return str(value).strip()
    if isinstance(value, list):
        return " ".join(x for x in (_value_to_text(v) for v in value) if x).strip()
    if isinstance(value, dict):
        for key in ("text", "value", "url", "link", "name", "title", "content", "timestamp"):
            if value.get(key) is not None:
                return _value_to_text(value[key])
        return " ".join(x for x in (_value_to_text(v) for v in value.values()) if x).strip()
    return str(value).strip()


def _value_to_url(value):
    """链接单元格可能同时含显示文本和真实 URL，优先取 URL。"""
    if isinstance(value, dict):
        for key in ("url", "link", "href"):
            if value.get(key):
                return _value_to_text(value[key])
        return _value_to_text(value)
    if isinstance(value, list):
        for item in value:
            result = _value_to_url(item)
            if result.startswith(("http://", "https://")):
                return result
        return _value_to_text(value)
    return _value_to_text(value)


def _value_to_choices(value):
    """把钉钉单选、多选或普通文本字段统一为独立选项列表。"""
    choices = []

    def collect(item):
        if item is None:
            return
        if isinstance(item, list):
            for child in item:
                collect(child)
            return
        if isinstance(item, dict):
            for key in ("values", "options", "items"):
                if item.get(key) is not None:
                    collect(item[key])
                    return
            for key in ("name", "text", "label", "title", "value", "content"):
                if item.get(key) is not None:
                    collect(item[key])
                    return
            return
        text = str(item).strip()
        if not text:
            return
        if text[:1] in ("[", "{"):
            try:
                collect(json.loads(text))
                return
            except (TypeError, ValueError):
                pass
        choices.extend(
            part.strip() for part in re.split(r"[,，;；|、\r\n]+", text)
            if part.strip()
        )

    collect(value)
    return list(dict.fromkeys(choices))


def normalize_records(raw_records, field_ids):
    mapping = {
        "seq": field_ids.get("序号", ""),
        "source": field_ids.get("来源", ""),
        "date": field_ids.get("日期", ""),
        "title": field_ids.get("标题", ""),
        "link": field_ids.get("链接", ""),
        "summary": field_ids.get("摘要", ""),
        "type": field_ids.get("类型", ""),
    }
    category_field = field_ids.get("筛选分类", "")
    output = []
    for index, raw in enumerate(raw_records, 1):
        raw = raw if isinstance(raw, dict) else {}
        fields = raw.get("fields") or raw.get("values") or raw
        if not isinstance(fields, dict):
            fields = {}
        record = {}
        for key, field_id in mapping.items():
            value = fields.get(field_id) if field_id else ""
            record[key] = _value_to_url(value) if key == "link" else _value_to_text(value)
        categories = _value_to_choices(fields.get(category_field) if category_field else None)
        record["news_categories"] = categories
        record["news_category"] = "、".join(categories)
        record["seq"] = record["seq"] or str(index)
        record["_record_id"] = _value_to_text(raw.get("recordId") or raw.get("id"))
        output.append(record)
    return output
