"""Validated portable news and per-segment text contracts.

No editor SDK or internal business schema is required by this module.
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any


class ValidationError(ValueError):
    """An actionable input error safe to show without a traceback."""


_ID = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")
_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)),
             *(f"lpt{i}" for i in range(1, 10))}


def safe_id(value: Any, label: str = "id") -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value) or value.lower() in _RESERVED:
        raise ValidationError(f"{label} must be 1-64 ASCII letters, digits, _ or -; no device names")
    return value


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict:
    result: dict = {}
    for key, value in pairs:
        if key in result:
            raise ValidationError("JSON has a duplicate key")
        result[key] = value
    return result


def read_json(path: Path) -> Any:
    try:
        if path.stat().st_size > 8 * 1024 * 1024:
            raise ValidationError("JSON input exceeds 8 MiB")
        return json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=_unique_pairs)
    except (OSError, UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValidationError(f"Cannot read UTF-8 JSON ({type(exc).__name__}); check input file") from None


def _string(value: Any, label: str, maximum: int = 20000) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValidationError(f"{label} must be a nonempty string (maximum {maximum} characters)")
    if any(ord(c) < 32 and c not in "\n\t" for c in value):
        raise ValidationError(f"{label} contains unsupported control characters")
    return value


def _integer(value: Any, label: str, minimum: int = 0, maximum: int = 86400000) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValidationError(f"{label} must be an integer from {minimum} to {maximum}")
    return value


def validate_news(records: Any) -> list[dict]:
    if not isinstance(records, list) or not 1 <= len(records) <= 1000:
        raise ValidationError("News must be a JSON array containing 1-1000 records")
    seen: set[str] = set()
    for record in records:
        if not isinstance(record, dict):
            raise ValidationError("Each news record must be an object")
        identifier = safe_id(record.get("id"), "news.id")
        # Windows output directories are case-insensitive.
        if identifier.casefold() in seen:
            raise ValidationError("News IDs must be unique (case-insensitive)")
        seen.add(identifier.casefold())
        for field in ("title", "summary", "source", "date"):
            _string(record.get(field), f"news.{field}")
        try:
            if date.fromisoformat(record["date"]).isoformat() != record["date"]:
                raise ValueError
        except ValueError:
            raise ValidationError("news.date must be YYYY-MM-DD") from None
        if "url" in record and record["url"]:
            _string(record["url"], "news.url", 2048)
            if not record["url"].startswith(("https://", "http://")):
                raise ValidationError("news.url must use http or https")
        if "demo_texts" in record:
            if not isinstance(record["demo_texts"], dict):
                raise ValidationError("news.demo_texts must be a string map")
            for key, value in record["demo_texts"].items():
                safe_id(key, "demo_texts key")
                _string(value, "demo_texts value")
    return records


def load_news(path: Path) -> list[dict]:
    return validate_news(read_json(Path(path)))


def validate_template(template: Any) -> dict:
    if not isinstance(template, dict) or type(template.get("schema_version")) is not int or template["schema_version"] != 1:
        raise ValidationError("Template schema_version must be 1")
    _string(template.get("name"), "template.name", 120)
    for key in ("width", "height"):
        _integer(template.get(key), key, 64, 8192)
    slots = template.get("slots")
    if not isinstance(slots, list) or not 1 <= len(slots) <= 200:
        raise ValidationError("Template needs 1-200 text slots")
    ids: set[str] = set()
    orders: set[int] = set()
    targets: set[tuple[int, int]] = set()
    sequences: dict[str, list[dict]] = {}
    for slot in slots:
        if not isinstance(slot, dict):
            raise ValidationError("Each slot must be an object")
        identifier = safe_id(slot.get("id"), "slot.id")
        if identifier in ids:
            raise ValidationError("Duplicate slot ID")
        ids.add(identifier)
        _string(slot.get("purpose"), "slot.purpose", 1000)
        if slot.get("mode") not in ("fixed", "generated"):
            raise ValidationError("slot.mode must be fixed or generated")
        if type(slot.get("allow_repeat")) is not bool:
            raise ValidationError("slot.allow_repeat must be true or false")
        for key in ("max_chars", "max_chars_per_line"):
            _integer(slot.get(key), key, 1, 20000)
        _integer(slot.get("max_lines"), "max_lines", 1, 100)
        if "exact_lines" in slot:
            _integer(slot["exact_lines"], "exact_lines", 1, slot["max_lines"])
        for key in ("track", "segment", "start_ms"):
            _integer(slot.get(key), key)
        _integer(slot.get("duration_ms"), "duration_ms", 1)
        _integer(slot.get("order"), "order", 1, 200)
        if slot["start_ms"] + slot["duration_ms"] > 86400000:
            raise ValidationError("Slot end exceeds 24 hours")
        if slot["order"] in orders:
            raise ValidationError("Slot order must be unique")
        orders.add(slot["order"])
        target = (slot["track"], slot["segment"])
        if target in targets:
            raise ValidationError("Each text segment must have exactly one slot")
        targets.add(target)
        if slot["mode"] == "fixed":
            _validate_one_text(slot, slot.get("text"))
        elif "text" in slot:
            raise ValidationError("Generated slot cannot contain fixed text")
        if "sequence" in slot:
            name = safe_id(slot["sequence"], "sequence")
            _integer(slot.get("sequence_index"), "sequence_index", 1, 200)
            sequences.setdefault(name, []).append(slot)
        elif "sequence_index" in slot:
            raise ValidationError("sequence_index requires sequence")
    if orders != set(range(1, len(slots) + 1)):
        raise ValidationError("Slot order must be contiguous from 1")
    for group in sequences.values():
        group.sort(key=lambda x: x["sequence_index"])
        if [s["sequence_index"] for s in group] != list(range(1, len(group) + 1)):
            raise ValidationError("Sequence indices must be contiguous from 1")
        for previous, current in zip(group, group[1:]):
            if (current["order"] <= previous["order"] or current["track"] != previous["track"]
                    or current["segment"] != previous["segment"] + 1
                    or current["start_ms"] != previous["start_ms"] + previous["duration_ms"]):
                raise ValidationError("Sequence must follow consecutive segments on one track with contiguous time and increasing order")
    # Different segments on the same text track must not overlap.
    by_track: dict[int, list[dict]] = {}
    for slot in slots:
        by_track.setdefault(slot["track"], []).append(slot)
    for group in by_track.values():
        group.sort(key=lambda x: x["start_ms"])
        if any(b["start_ms"] < a["start_ms"] + a["duration_ms"] for a, b in zip(group, group[1:])):
            raise ValidationError("Segments on the same text track overlap")
    return template


def load_template(path: Path) -> dict:
    return validate_template(read_json(Path(path)))


def _validate_one_text(slot: dict, text: Any) -> str:
    _string(text, f"text for {slot['id']}")
    if "\t" in text or "\\n" in text:
        raise ValidationError(f"{slot['id']}: use actual newlines; tabs and literal \\n are not supported")
    lines = text.split("\n")
    if any(not line.strip() or line != line.strip() for line in lines):
        raise ValidationError(f"{slot['id']}: no blank lines or outer whitespace")
    if sum(map(len, lines)) > slot["max_chars"]:
        raise ValidationError(f"{slot['id']}: total character limit exceeded")
    if len(lines) > slot["max_lines"] or ("exact_lines" in slot and len(lines) != slot["exact_lines"]):
        raise ValidationError(f"{slot['id']}: line count violates template")
    if any(len(line) > slot["max_chars_per_line"] for line in lines):
        raise ValidationError(f"{slot['id']}: per-line character limit exceeded")
    return text


def validate_texts(template: dict, texts: Any) -> dict[str, str]:
    validate_template(template)
    if not isinstance(texts, dict) or set(texts) != {s["id"] for s in template["slots"]}:
        raise ValidationError("Text keys must exactly match template slot IDs")
    previous: dict[str, dict] = {}
    for slot in sorted(template["slots"], key=lambda s: s["order"]):
        text = _validate_one_text(slot, texts[slot["id"]])
        if slot["mode"] == "fixed" and text != slot["text"]:
            raise ValidationError(f"{slot['id']}: fixed text was changed")
        normalized = re.sub(r"\s+", "", text).casefold()
        if normalized in previous and not (slot["allow_repeat"] and previous[normalized]["allow_repeat"]):
            raise ValidationError(f"Duplicate content in {previous[normalized]['id']} and {slot['id']}; both slots must explicitly allow repeats")
        previous[normalized] = slot
    return dict(texts)
