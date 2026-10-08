"""Explicit, strict local configuration; never discover business configuration."""

from __future__ import annotations

import copy
import json
import math
import os
from pathlib import Path
import re

from .domain import ValidationError


ARK_ENDPOINT = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
DEFAULT_CONFIG = {
    "schema_version": 1,
    "dingtalk": {
        "app_key": "", "app_secret": "", "base_id": "", "sheet_id": "", "operator_id": "",
        "field_mapping": {"id": "", "title": "title", "summary": "summary", "source": "source", "date": "date", "url": ""},
        "page_size": 100, "max_pages": 20, "timeout_seconds": 30,
    },
    "doubao": {"api_key": "", "model": "", "endpoint": ARK_ENDPOINT, "timeout_seconds": 60, "max_tokens": 4096},
}
ENVIRONMENT_KEYS = {
    "NVB_DINGTALK_APP_KEY": ("dingtalk", "app_key"),
    "NVB_DINGTALK_APP_SECRET": ("dingtalk", "app_secret"),
    "NVB_DINGTALK_BASE_ID": ("dingtalk", "base_id"),
    "NVB_DINGTALK_SHEET_ID": ("dingtalk", "sheet_id"),
    "NVB_DINGTALK_OPERATOR_ID": ("dingtalk", "operator_id"),
    "NVB_DOUBAO_API_KEY": ("doubao", "api_key"),
    "NVB_DOUBAO_MODEL": ("doubao", "model"),
}


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValidationError("JSON contains a duplicate key.")
        result[key] = value
    return result


def _merge(base: dict, values: object) -> dict:
    if not isinstance(values, dict) or set(values) - set(base):
        raise ValidationError("Configuration contains an unknown field or invalid object.")
    result = copy.deepcopy(base)
    for key, value in values.items():
        result[key] = _merge(base[key], value) if isinstance(base[key], dict) else value
    return result


def _text(value: object, label: str, maximum: int = 512, ascii_only: bool = False) -> None:
    if (not isinstance(value, str) or len(value) > maximum
            or any(ord(char) < 32 or ord(char) == 127 for char in value)
            or (value and value != value.strip())
            or (ascii_only and not value.isascii())):
        raise ValidationError(f"Invalid configuration value for {label}.")


def _integer(value: object, label: str, lower: int, upper: int) -> None:
    if type(value) is not int or not lower <= value <= upper:
        raise ValidationError(f"{label} must be an integer from {lower} to {upper}.")


def validate_config(values: dict) -> dict:
    """Return a complete independent configuration and reject ambiguous values."""
    result = _merge(DEFAULT_CONFIG, values)
    if type(result["schema_version"]) is not int or result["schema_version"] != 1:
        raise ValidationError("Configuration schema_version must be 1.")
    ding, doubao = result["dingtalk"], result["doubao"]
    for key in ("app_key", "app_secret"):
        _text(ding[key], f"dingtalk.{key}", ascii_only=True)
    for key in ("base_id", "sheet_id", "operator_id"):
        _text(ding[key], f"dingtalk.{key}")
    for key, value in ding["field_mapping"].items():
        _text(value, f"dingtalk.field_mapping.{key}")
        if key not in ("id", "url") and not value:
            raise ValidationError("DingTalk required field mappings must not be empty.")
    _integer(ding["page_size"], "dingtalk.page_size", 1, 100)
    _integer(ding["max_pages"], "dingtalk.max_pages", 1, 100)
    _text(doubao["api_key"], "doubao.api_key", ascii_only=True)
    _text(doubao["model"], "doubao.model", 256, ascii_only=True)
    if doubao["model"] and not re.fullmatch(r"[A-Za-z0-9_.:-]+", doubao["model"]):
        raise ValidationError("Invalid configuration value for doubao.model.")
    if doubao["endpoint"] != ARK_ENDPOINT:
        raise ValidationError("Only the documented official Beijing Ark endpoint is supported.")
    _integer(doubao["max_tokens"], "doubao.max_tokens", 1, 16384)
    for label, section in (("dingtalk", ding), ("doubao", doubao)):
        timeout = section["timeout_seconds"]
        if type(timeout) not in (float, int) or not math.isfinite(timeout) or not 1 <= timeout <= 120:
            raise ValidationError(f"{label}.timeout_seconds must be a finite number from 1 to 120.")
    return result


def load_config(path: Path | None = None, environ: dict | None = None) -> dict:
    """Load only an explicitly named file, then override with supported env vars."""
    values = {}
    if path is not None:
        try:
            with Path(path).open("rb") as handle:
                raw = handle.read(65537)
            if len(raw) > 65536:
                raise ValidationError("Configuration exceeds 64 KiB.")
            values = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_unique_object)
        except (OSError, UnicodeError, json.JSONDecodeError, RecursionError):
            raise ValidationError("Cannot read configuration: check file access and valid UTF-8 JSON.") from None
    # Validate the file before overlays, so an environment variable cannot hide a typo.
    result = validate_config(values)
    env = os.environ if environ is None else environ
    for name, (section, key) in ENVIRONMENT_KEYS.items():
        if name in env:
            result[section][key] = env[name]
    return validate_config(result)


def require_provider_config(section: str, values: dict) -> dict:
    """Validate direct provider use without silently loading process environment."""
    result = validate_config({section: values})[section]
    required = ("app_key", "app_secret", "base_id", "sheet_id", "operator_id") if section == "dingtalk" else ("api_key", "model")
    missing = [key for key in required if not result[key]]
    if missing:
        raise ValidationError(f"{section} configuration is missing: {', '.join(missing)}.")
    return result


def validate_connection_config(config: dict, source: str = "local", model: str = "offline") -> None:
    """Doctor/preflight validation only; this function never accesses the network."""
    cfg = validate_config(config)
    if source not in ("local", "dingtalk") or model not in ("offline", "doubao"):
        raise ValidationError("Unknown source or model selection.")
    if source == "dingtalk":
        require_provider_config("dingtalk", cfg["dingtalk"])
    if model == "doubao":
        require_provider_config("doubao", cfg["doubao"])
