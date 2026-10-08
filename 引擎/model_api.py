"""Standalone API client for the original text-input workflow (stdlib only)."""
from __future__ import annotations
import http.client
import json
import os
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request
from urllib.parse import urlsplit

class ValidationError(ValueError):
    pass

MAX_RESPONSE_BYTES = 4 * 1024 * 1024

def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValidationError("JSON contains a duplicate key.")
        result[key] = value
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

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Do not forward credentials, including on same-origin redirects.
        return None

def _post_json(url: str, payload: dict, headers: dict, timeout: float, service: str) -> dict:
    """Bounded HTTPS request; expose status only, never server text or request URLs."""
    if urllib.parse.urlsplit(url).scheme != "https":
        raise ValidationError("Online providers require HTTPS.")
    try:
        req = urllib.request.Request(url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                                     headers={"Content-Type": "application/json", "Accept": "application/json", **headers},
                                     method="POST")
        opener = urllib.request.build_opener(_NoRedirect())
        with opener.open(req, timeout=timeout) as response:
            if not 200 <= response.status < 300:
                raise ValidationError(f"{service} returned an unsuccessful HTTP status.")
            raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ValidationError(f"{service} response exceeds 4 MiB.")
        result = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
        if not isinstance(result, dict):
            raise ValidationError(f"{service} returned an invalid JSON object.")
        return result
    except urllib.error.HTTPError as error:
        status = error.code if type(error.code) is int else "error"
        error.close()
        raise ValidationError(f"{service} HTTP {status}; check credentials, permissions or service limits. Redirects are blocked.") from None
    except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException):
        raise ValidationError(f"{service} connection failed or timed out; check network and timeout configuration.") from None
    except (UnicodeError, json.JSONDecodeError, ValueError, RecursionError) as error:
        if isinstance(error, ValidationError):
            raise
        raise ValidationError(f"{service} returned unreadable JSON.") from None

def load_api_config(path: Path, environ=None) -> dict:
    try:
        with path.open('rb') as handle:
            raw = handle.read(65537)
        if len(raw) > 65536:
            raise ValidationError('API configuration exceeds 64 KiB.')
        value = json.loads(raw.decode('utf-8-sig'), object_pairs_hook=_unique_object)
    except (OSError, UnicodeError, ValueError, RecursionError):
        raise ValidationError('Cannot read API configuration as UTF-8 JSON.') from None
    if not isinstance(value, dict) or set(value) - {'endpoint', 'api_key', 'model', 'max_tokens', 'timeout_seconds'}:
        raise ValidationError('Unknown API configuration fields.')
    cfg = {'endpoint': '', 'api_key': '', 'model': '', 'max_tokens': 4096, 'timeout_seconds': 60, **value}
    env = os.environ if environ is None else environ
    for key in ('endpoint', 'api_key', 'model'):
        cfg[key] = env.get('NVB_API_' + key.upper(), cfg[key])
        _text(cfg[key], key, 2048, ascii_only=True)
        if not cfg[key]:
            raise ValidationError(f'API configuration requires {key}.')
    try:
        url = urlsplit(cfg['endpoint'])
        port = url.port
        if url.scheme != 'https' or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError()
    except ValueError:
        raise ValidationError('endpoint must be a complete HTTPS chat/completions URL without credentials, query or fragment.') from None
    _integer(cfg['max_tokens'], 'max_tokens', 1, 16384)
    _integer(cfg['timeout_seconds'], 'timeout_seconds', 1, 120)
    return cfg

def read_input(path: Path) -> str:
    with path.open('rb') as handle:
        raw = handle.read(120001)
    if len(raw) > 120000:
        raise ValidationError('Input file exceeds 120000 bytes.')
    return raw.decode('utf-8-sig')
