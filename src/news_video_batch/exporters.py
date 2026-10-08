"""Portable offline artifacts and an intentionally narrow plaintext draft adapter.

This module is independently implemented using the Python standard library.
Saving and rereading JSON is not a claim of compatibility with a video editor.
"""

from __future__ import annotations

import copy
import hashlib
import html
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import uuid

from .domain import ValidationError, validate_template, validate_texts


MAX_DRAFT_BYTES = 20 * 1024 * 1024
MAX_ASSET_BYTES = 256 * 1024 * 1024
MAX_TOTAL_ASSET_BYTES = 512 * 1024 * 1024
_ASSET_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".mp4", ".mov", ".m4v", ".wav", ".mp3", ".m4a", ".aac", ".ogg", ".ttf", ".otf"}
_EDITOR_DIRECTORIES = {"com.lveditor.draft", "jianyingpro", "capcut"}


def _reject_links(path: Path) -> None:
    """Reject symlinks and Windows junction/reparse points, including ancestors."""
    for candidate in (path, *path.parents):
        try:
            info = candidate.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400):
            raise ValidationError("Paths through symbolic links or junctions are not supported.")


def _empty_destination(destination: Path) -> Path:
    destination = Path(destination).absolute()
    _reject_links(destination)
    if destination == Path(destination.anchor) or not destination.is_dir():
        raise ValidationError("The exporter destination must be an existing empty directory.")
    if any(part.casefold() in _EDITOR_DIRECTORIES for part in destination.parts):
        raise ValidationError("Export into a separate working directory, outside installed editor draft folders.")
    if any(destination.iterdir()):
        raise ValidationError("The exporter destination must be empty; existing files are never overwritten.")
    return destination.resolve()


def _write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def _json_loads(value: str) -> object:
    def unique_pairs(pairs):
        result = {}
        for key, item in pairs:
            if key in result:
                raise ValidationError("Draft JSON contains a duplicate key.")
            result[key] = item
        return result

    def reject_constant(_value):
        raise ValidationError("Draft JSON contains a non-finite number.")

    return json.loads(value, object_pairs_hook=unique_pairs, parse_constant=reject_constant)


def _read_json(path: Path) -> dict:
    try:
        if path.stat().st_size > MAX_DRAFT_BYTES:
            raise ValidationError("Draft JSON exceeds the supported size limit.")
        value = _json_loads(path.read_text(encoding="utf-8-sig"))
    except (UnicodeError, json.JSONDecodeError, OSError) as exc:
        raise ValidationError("Cannot read a plaintext UTF-8 draft JSON file; encrypted drafts are unsupported.") from exc
    if not isinstance(value, dict):
        raise ValidationError("Draft JSON must contain an object.")
    return value


def _srt_time(milliseconds: int) -> str:
    seconds, ms = divmod(milliseconds, 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02}:{minutes:02}:{seconds:02},{ms:03}"


def _captions(template: dict, texts: dict) -> str:
    slots = template["slots"]
    selected = [slot for slot in slots if slot.get("sequence")]
    selected.sort(key=lambda slot: (slot["start_ms"], slot["order"]))
    return "\n".join(
        f"{index}\n{_srt_time(slot['start_ms'])} --> "
        f"{_srt_time(slot['start_ms'] + slot['duration_ms'])}\n{texts[slot['id']]}\n"
        for index, slot in enumerate(selected, 1)
    )


def _preview(draft: dict) -> str:
    # Escape JSON's HTML-significant characters before placing it in a script.
    payload = json.dumps(draft, ensure_ascii=False).replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    title = html.escape(draft["news"]["title"])
    rows = "".join(
        f"<li><b>{html.escape(slot['id'])}</b> · {slot['start_ms'] / 1000:g}–"
        f"{(slot['start_ms'] + slot['duration_ms']) / 1000:g}s"
        f"<pre>{html.escape(slot['text'])}</pre></li>"
        for slot in draft["slots"]
    )
    page = """<!doctype html>
<html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; connect-src 'none'">
<title>离线新闻流程预览 · @@TITLE@@</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#eef2f5;color:#142a38;font:16px/1.6 system-ui,sans-serif}
main{max-width:1050px;margin:auto;padding:32px}h1{line-height:1.25;font-size:30px}p{max-width:75ch}
.layout{display:grid;grid-template-columns:minmax(230px,360px) 1fr;gap:28px;align-items:start}
#stage{background:linear-gradient(145deg,#143b55,#14686d);color:white;aspect-ratio:9/16;padding:28px 22px;
position:relative;border-radius:20px;overflow:auto;box-shadow:0 15px 35px #1234}
.brand{font-size:12px;letter-spacing:3px;color:#a8e9db;border-bottom:1px solid #ffffff40;padding-bottom:12px}
#active{display:flex;flex-direction:column;gap:14px;margin-top:24px}.slot{white-space:pre-wrap;overflow-wrap:anywhere}
.slot:first-child{font-size:26px;font-weight:700}.empty{opacity:.7}footer{margin-top:22px;font-size:12px;color:#bfe3df}
button{background:#164d62;color:white;border:0;border-radius:7px;padding:9px 18px;font:inherit;cursor:pointer}
input{width:100%;margin:16px 0}output{font-variant-numeric:tabular-nums}ol{padding-left:24px}
li{padding:10px;border-bottom:1px solid #cad6dd}pre{font:inherit;white-space:pre-wrap;overflow-wrap:anywhere;margin:5px 0}
.note{padding:12px 16px;background:#fff;border-left:4px solid #248878}noscript{color:#922}
@media(max-width:650px){main{padding:20px}.layout{grid-template-columns:1fr}#stage{max-width:360px;width:100%;margin:auto}}
</style><main><h1>@@TITLE@@</h1>
<p class="note">离线示例：展示文字、顺序与时间。页面可直接打开，无需联网。此预览不是成片，也不模拟剪映排版或证明剪映兼容性。</p>
<div class="layout"><section><div id="stage"><div class="brand">NEWS / OFFLINE DEMO</div><div id="active" aria-live="polite"></div>
<footer>原创示例视觉 · 本地处理</footer></div><label for="timeline">时间轴</label>
<input id="timeline" type="range" min="0" max="1" value="0" step="100"><button id="play" type="button">播放</button>
<output id="clock"></output></section><section><h2>全部文字片段</h2><ol>@@ROWS@@</ol>
<noscript>浏览器禁用脚本时仍可查看右侧完整片段清单。</noscript></section></div></main>
<script id="draft-data" type="application/json">@@PAYLOAD@@</script><script>
'use strict';
const draft=JSON.parse(document.getElementById('draft-data').textContent);
const slider=document.getElementById('timeline'), clock=document.getElementById('clock'), active=document.getElementById('active'), button=document.getElementById('play');
const duration=Math.max(...draft.slots.map(s=>s.start_ms+s.duration_ms));slider.max=duration;
let timer=null;
function render(){const t=Number(slider.value);active.replaceChildren();for(const s of draft.slots){if(t>=s.start_ms&&t<s.start_ms+s.duration_ms){const div=document.createElement('div');div.className='slot';div.textContent=s.text;active.appendChild(div);}}
if(!active.childNodes.length){const div=document.createElement('div');div.className='empty';div.textContent='当前时间没有文字片段';active.appendChild(div);}clock.textContent=` ${(t/1000).toFixed(1)} / ${(duration/1000).toFixed(1)} 秒`;}
function stop(){clearInterval(timer);timer=null;button.textContent='播放';}
slider.addEventListener('input',()=>{stop();render();});
button.addEventListener('click',()=>{if(timer){stop();return;}if(Number(slider.value)>=duration)slider.value=0;button.textContent='暂停';render();timer=setInterval(()=>{slider.value=Math.min(duration,Number(slider.value)+100);render();if(Number(slider.value)>=duration)stop();},100);});render();
</script></html>
"""
    replacements = {"@@TITLE@@": title, "@@ROWS@@": rows, "@@PAYLOAD@@": payload}
    return re.sub(r"@@(?:TITLE|ROWS|PAYLOAD)@@", lambda match: replacements[match.group()], page)


def write_demo(news: dict, template: dict, texts: dict, destination: Path) -> dict:
    """Write a portable demonstration, standalone HTML preview, and SRT captions."""
    validate_template(template)
    validate_texts(template, texts)
    destination = _empty_destination(destination)
    draft = {
        "schema_version": 1,
        "kind": "portable-news-demo",
        "limitations": "Offline text/timing preview; not a video or a Jianying draft.",
        "news": {key: news[key] for key in ("id", "title", "source", "date")},
        "template": template["name"],
        "canvas": {"width": template["width"], "height": template["height"]},
        "slots": [dict(slot, text=texts[slot["id"]]) for slot in sorted(template["slots"], key=lambda item: item["order"])],
    }
    _write_json(destination / "draft.json", draft)
    saved = _read_json(destination / "draft.json")
    if saved != draft:
        raise ValidationError("Saved demo failed JSON verification.")
    preview = _preview(saved)
    captions = _captions(template, texts)
    (destination / "preview.html").write_text(preview, encoding="utf-8")
    (destination / "captions.srt").write_text(captions, encoding="utf-8")
    if (destination / "preview.html").read_text(encoding="utf-8") != preview or (destination / "captions.srt").read_text(encoding="utf-8") != captions:
        raise ValidationError("Saved preview or captions failed readback verification.")
    return {"kind": "demo", "verified": True, "files": ["draft.json", "preview.html", "captions.srt"]}


def _utf16_length(text: str) -> int:
    try:
        return len(text.encode("utf-16-le")) // 2
    except UnicodeEncodeError as exc:
        raise ValidationError("Text contains an unsupported Unicode surrogate.") from exc


def _text_content(material: dict) -> dict:
    if not isinstance(material.get("content"), str):
        raise ValidationError("Text material content must be a plaintext JSON string.")
    try:
        content = _json_loads(material["content"])
    except (ValueError, TypeError) as exc:
        raise ValidationError("Text material content is not supported JSON.") from exc
    if not isinstance(content, dict) or set(content) - {"text", "styles"} or not isinstance(content.get("text"), str):
        raise ValidationError("Only plain text content with optional styles is supported.")
    length = _utf16_length(content["text"])
    if "styles" in content:
        styles = content["styles"]
        if not isinstance(styles, list) or len(styles) != 1 or not isinstance(styles[0], dict):
            raise ValidationError("Only a single style covering the entire text is supported.")
        span = styles[0].get("range")
        if not isinstance(span, list) or any(type(value) is not int for value in span) or span != [0, length]:
            raise ValidationError("Text style must cover the full text in UTF-16 units.")
        allowed_style = {"range", "font", "size", "fill", "bold", "italic", "underline", "strikethrough", "stroke", "shadow", "color", "letter_spacing"}
        if set(styles[0]) - allowed_style:
            raise ValidationError("This text style contains unsupported fields.")
    for key in ("text_keyframe", "text_keyframes", "words", "text_to_audio_ids", "text", "recognize_text", "recognized_text"):
        if material.get(key):
            raise ValidationError("Text keyframes, speech alignment, and linked speech are unsupported.")
    return content


def _index_draft(draft: dict) -> tuple[list[list[dict]], dict[str, dict]]:
    if not isinstance(draft.get("tracks"), list) or not isinstance(draft.get("materials"), dict):
        raise ValidationError("Unsupported draft structure: tracks and materials are required.")
    materials = draft["materials"]
    if any(materials.get(key) for key in ("text_templates", "drafts", "nested_drafts")):
        raise ValidationError("Compound text templates and nested drafts are unsupported.")
    text_materials = materials.get("texts")
    if not isinstance(text_materials, list):
        raise ValidationError("Unsupported draft structure: materials.texts is required.")
    lookup = {}
    for material in text_materials:
        if not isinstance(material, dict) or not isinstance(material.get("id"), str) or not material["id"] or material["id"] in lookup:
            raise ValidationError("Text material IDs must be present and unique.")
        _text_content(material)
        lookup[material["id"]] = material
    tracks = []
    for track in draft["tracks"]:
        if not isinstance(track, dict) or track.get("type") not in {"text", "video", "audio"} or not isinstance(track.get("segments"), list):
            raise ValidationError("Only simple text, video, and audio tracks are supported.")
        if any(not isinstance(segment, dict) for segment in track["segments"]):
            raise ValidationError("Every track segment must be a JSON object.")
        if track["type"] != "text":
            continue
        for segment in track["segments"]:
            if not isinstance(segment.get("material_id"), str) or segment["material_id"] not in lookup:
                raise ValidationError("Every text segment must reference one known text material.")
            if any(segment.get(key) for key in ("extra_material_refs", "common_keyframes", "keyframes", "text_template_resource")):
                raise ValidationError("Animated, linked, and compound text segments are unsupported.")
            timing = segment.get("target_timerange")
            if not isinstance(timing, dict) or set(timing) != {"start", "duration"} or any(type(timing.get(key)) is not int for key in ("start", "duration")) or timing["start"] < 0 or timing["duration"] <= 0:
                raise ValidationError("Every text segment requires an integer microsecond target_timerange.")
        tracks.append(track["segments"])
    if not tracks:
        raise ValidationError("The draft has no supported text tracks.")
    return tracks, lookup


def _collect_assets(value: object, template_dir: Path) -> list[tuple[Path, Path]]:
    """Find and validate local dependencies, without copying unrelated files."""
    paths: dict[str, tuple[Path, Path]] = {}

    def visit(node: object) -> None:
        if isinstance(node, dict):
            for key, item in node.items():
                if (key == "path" or key.endswith("_path")) and not isinstance(item, str):
                    raise ValidationError("Asset path fields must be strings; unknown path structures are unsupported.")
                if isinstance(item, str) and item and (key == "path" or key.endswith("_path")):
                    normalized = item.replace("\\", "/")
                    relative = PurePosixPath(normalized)
                    if relative.is_absolute() or ":" in normalized or any(part in {"..", "."} for part in normalized.split("/")) or any(not part for part in normalized.split("/")):
                        raise ValidationError("Asset paths must be relative files inside the supplied template directory.")
                    local_relative = Path(*relative.parts)
                    if local_relative.suffix.lower() not in _ASSET_SUFFIXES:
                        raise ValidationError("Unsupported asset file type; only local media and font files are copied.")
                    asset = template_dir / local_relative
                    _reject_links(asset)
                    if not asset.is_file() or not asset.resolve().is_relative_to(template_dir.resolve()):
                        raise ValidationError("A referenced local asset is missing or outside the template directory.")
                    if asset.stat().st_size > MAX_ASSET_BYTES:
                        raise ValidationError("A template asset exceeds the supported size limit.")
                    folded = normalized.casefold()
                    if folded in paths and paths[folded][1] != local_relative:
                        raise ValidationError("Asset names collide on a case-insensitive filesystem.")
                    paths[folded] = (asset, local_relative)
                elif isinstance(item, str):
                    if key != "text" and re.match(r"^(?:[a-zA-Z]:[\\/]|/|\\\\|[a-z][a-z0-9+.-]*://|file:)", item.strip(), re.IGNORECASE):
                        raise ValidationError("External paths and remote dependencies in draft metadata are unsupported.")
                    # Material content stores its style (including font paths) as JSON text.
                    if key == "content":
                        try:
                            nested = _json_loads(item)
                        except json.JSONDecodeError:
                            continue
                        visit(nested)
                else:
                    visit(item)
        elif isinstance(node, list):
            for item in node:
                visit(item)

    visit(value)
    result = list(paths.values())
    if sum(asset.stat().st_size for asset, _ in result) > MAX_TOTAL_ASSET_BYTES:
        raise ValidationError("Template assets exceed the total supported size limit.")
    return result


def _verify_jianying(saved: dict, expected: dict, template: dict, texts: dict) -> None:
    if saved != expected:
        raise ValidationError("Saved Jianying draft differs from the expected JSON.")
    tracks, materials = _index_draft(saved)
    seen = set()
    for slot in template["slots"]:
        segment = tracks[slot["track"]][slot["segment"]]
        material_id = segment["material_id"]
        if material_id in seen:
            raise ValidationError("Saved draft still shares a material between text segments.")
        seen.add(material_id)
        content = _text_content(materials[material_id])
        timing = {"start": slot["start_ms"] * 1000, "duration": slot["duration_ms"] * 1000}
        if content["text"] != texts[slot["id"]] or segment["target_timerange"] != timing:
            raise ValidationError("Saved text or timing failed per-segment verification.")


def _file_digest(path: Path) -> bytes:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").digest()


def write_jianying(news: dict, template: dict, texts: dict, destination: Path, template_dir: Path) -> dict:
    """Selectively clone a user's plaintext draft and replace every text segment.

    `verified` means a JSON readback check, never editor/GUI verification.
    """
    del news  # The draft format does not need article metadata.
    validate_template(template)
    validate_texts(template, texts)
    destination = _empty_destination(destination)
    template_dir = Path(template_dir).absolute()
    _reject_links(template_dir)
    if not template_dir.is_dir():
        raise ValidationError("The supplied template directory does not exist.")
    template_dir = template_dir.resolve()
    if destination.is_relative_to(template_dir) or template_dir.is_relative_to(destination):
        raise ValidationError("Template and output directories must be separate and cannot contain each other.")
    source = template_dir / "draft_content.json"
    _reject_links(source)
    original = _read_json(source)
    draft = copy.deepcopy(original)
    tracks, lookup = _index_draft(draft)
    expected_coverage = {(ti, si) for ti, track in enumerate(tracks) for si in range(len(track))}
    actual_coverage = {(slot["track"], slot["segment"]) for slot in template["slots"]}
    if actual_coverage != expected_coverage:
        raise ValidationError("Slots must cover every text segment exactly once; text tracks are indexed from zero by type.")
    replacements = []
    for slot in template["slots"]:
        segment = tracks[slot["track"]][slot["segment"]]
        if segment["target_timerange"] != {"start": slot["start_ms"] * 1000, "duration": slot["duration_ms"] * 1000}:
            raise ValidationError("Slot timing must exactly match the source draft; the adapter never moves segments.")
        material = copy.deepcopy(lookup[segment["material_id"]])
        content = _text_content(material)
        content["text"] = texts[slot["id"]]
        if "styles" in content:
            content["styles"][0]["range"] = [0, _utf16_length(content["text"])]
        material["id"] = str(uuid.uuid4()).upper()
        material["content"] = json.dumps(content, ensure_ascii=False, separators=(",", ":"))
        segment["material_id"] = material["id"]
        replacements.append(material)
    # Drop old text materials so unused original wording is not carried forward.
    draft["materials"]["texts"] = replacements
    assets = _collect_assets(draft, template_dir)
    for asset, relative in assets:
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(asset, target)
        if _file_digest(target) != _file_digest(asset):
            raise ValidationError("Copied asset failed byte-for-byte verification.")
    _write_json(destination / "draft_content.json", draft)
    _verify_jianying(_read_json(destination / "draft_content.json"), draft, template, texts)
    return {
        "kind": "jianying-experimental",
        "verified": True,
        "verification_scope": "JSON readback, every text segment, original timing, style ranges, and copied asset bytes; editor GUI unverified.",
        "files": ["draft_content.json", *sorted(relative.as_posix() for _, relative in assets)],
    }
