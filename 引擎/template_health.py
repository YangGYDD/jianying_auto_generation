# -*- coding: utf-8 -*-
"""模板结构分析、槽位校验、自动修复与健康状态管理。"""
import json
import os
import re
import tempfile

import template_registry as reg


class TemplateHealthError(RuntimeError):
    pass


def derive_text_spec(texts: list) -> str:
    """根据模板原文案推导文案长度要求。"""
    real = [str(text) for text in texts if str(text).strip()]
    if not real:
        return "一段简短的新闻文案, 不超过12个字"
    sample = real[0]
    lines = sample.split("\n")
    if len(lines) == 1:
        limit = max(6, len(lines[0].strip()) + 2)
        return f"短语型文案, 不超过{limit}个字, 凝练有冲击力"
    max_len = max(len(line.strip()) for line in lines) + 2
    return f"恰好{len(lines)}行, 行间用\\n分隔, 每行不超过{max_len}个字"


def analyze_slots(plain_json: dict) -> dict:
    """按同类型轨道的全局序号生成唯一且完整的槽位配置。"""
    if not isinstance(plain_json, dict):
        raise TemplateHealthError("草稿内容不是有效对象")

    id_to_text = {}
    materials = plain_json.get("materials", {})
    if not isinstance(materials, dict):
        materials = {}
    for text_material in materials.get("texts", []) or []:
        if not isinstance(text_material, dict):
            continue
        try:
            content = json.loads(text_material.get("content", "{}"))
            id_to_text[text_material.get("id", "")] = content.get("text", "")
        except (json.JSONDecodeError, TypeError, AttributeError):
            id_to_text[text_material.get("id", "")] = ""

    text_slots = []
    material_slots = []
    text_track_index = 0
    video_track_index = 0
    main_slot_index = 0
    overlay_slot_index = 0

    tracks = plain_json.get("tracks", [])
    if not isinstance(tracks, list):
        raise TemplateHealthError("草稿轨道列表格式不正确")

    for track in tracks:
        if not isinstance(track, dict):
            continue
        track_type = track.get("type")
        segments = track.get("segments", [])
        if not isinstance(segments, list):
            segments = []

        if track_type == "text":
            for segment_index, segment in enumerate(segments):
                text = (id_to_text.get(segment.get("material_id", ""), "")
                        if isinstance(segment, dict) else "")
                text_slots.append({
                    "键名": f"文字位{len(text_slots) + 1}",
                    "轨道类型": "text",
                    "轨道序号": text_track_index,
                    "片段": [segment_index],
                    "文案要求": derive_text_spec([text]),
                    "原文案示例": text[:40],
                })
            text_track_index += 1
            continue

        if track_type != "video":
            continue

        is_main = track.get("attribute") == 1
        for segment_index in range(len(segments)):
            if is_main:
                main_slot_index += 1
                key = f"主视频{main_slot_index}"
            else:
                overlay_slot_index += 1
                key = f"贴片视频{overlay_slot_index}"
            material_slots.append({
                "键名": key,
                "轨道类型": "video",
                "轨道序号": video_track_index,
                "片段": segment_index,
            })
        video_track_index += 1

    if not text_slots and not material_slots:
        raise TemplateHealthError("草稿没有可替换的文字或视频轨道")
    return {"文字槽位": text_slots, "素材槽位": material_slots}


def _tracks_by_type(plain_json: dict, track_type: str) -> list:
    tracks = plain_json.get("tracks", [])
    if not isinstance(tracks, list):
        return []
    return [track for track in tracks
            if isinstance(track, dict) and track.get("type") == track_type]


def _expected_targets(plain_json: dict, track_type: str) -> set:
    targets = set()
    for track_index, track in enumerate(_tracks_by_type(plain_json, track_type)):
        segments = track.get("segments", [])
        if isinstance(segments, list):
            targets.update((track_type, track_index, index)
                           for index in range(len(segments)))
    return targets


def _is_index(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def validate_slot_group(slots, plain_json: dict, group_name: str) -> list:
    """校验一类槽位的格式、边界、重复目标和轨道覆盖范围。"""
    expected_type = "text" if group_name == "文字槽位" else "video"
    if not isinstance(slots, list):
        return [f"{group_name}不是列表"]

    errors = []
    keys = set()
    targets = set()
    tracks = _tracks_by_type(plain_json, expected_type)

    for slot_index, slot in enumerate(slots, 1):
        label = f"{group_name}第{slot_index}项"
        if not isinstance(slot, dict):
            errors.append(f"{label}不是对象")
            continue
        key = str(slot.get("键名", "")).strip()
        if not key:
            errors.append(f"{label}缺少键名")
        elif key in keys:
            errors.append(f"{group_name}存在重复键名[{key}]")
        else:
            keys.add(key)

        if slot.get("轨道类型") != expected_type:
            errors.append(f"槽位[{key or slot_index}]轨道类型应为{expected_type}")
            continue
        track_index = slot.get("轨道序号")
        if not _is_index(track_index) or track_index >= len(tracks):
            errors.append(f"槽位[{key or slot_index}]轨道序号超出范围")
            continue
        segments = tracks[track_index].get("segments", [])
        segment_indexes = slot.get("片段") if expected_type == "text" else [slot.get("片段")]
        if expected_type == "text" and not isinstance(segment_indexes, list):
            errors.append(f"文字槽位[{key or slot_index}]片段应为列表")
            continue
        for segment_index in segment_indexes:
            if not _is_index(segment_index) or segment_index >= len(segments):
                errors.append(f"槽位[{key or slot_index}]片段序号超出范围")
                continue
            target = (expected_type, track_index, segment_index)
            if target in targets:
                errors.append(
                    f"{group_name}存在重复目标: 轨道{track_index}片段{segment_index}"
                )
            targets.add(target)

    expected = _expected_targets(plain_json, expected_type)
    missing = expected - targets
    extra = targets - expected
    if missing:
        errors.append(f"{group_name}漏掉{len(missing)}个轨道片段")
    if extra:
        errors.append(f"{group_name}包含{len(extra)}个无效轨道片段")
    return errors


def validate_slots(slots: dict, plain_json: dict) -> list:
    if not isinstance(slots, dict):
        return ["slots.json不是有效对象"]
    errors = []
    errors.extend(validate_slot_group(slots.get("文字槽位"), plain_json, "文字槽位"))
    errors.extend(validate_slot_group(slots.get("素材槽位"), plain_json, "素材槽位"))

    all_keys = []
    for group_name in ("文字槽位", "素材槽位"):
        group = slots.get(group_name, [])
        if isinstance(group, list):
            all_keys.extend(str(slot.get("键名", "")).strip()
                            for slot in group if isinstance(slot, dict))
    duplicate_keys = sorted({key for key in all_keys if key and all_keys.count(key) > 1})
    if duplicate_keys:
        errors.append("文字与素材槽位键名重复: " + "、".join(duplicate_keys))
    return list(dict.fromkeys(errors))


def repair_slots(current_slots, plain_json: dict, template_type: str) -> tuple:
    """只重建校验失败的槽位组，尽量保留人工调整过的文案要求。"""
    expected = analyze_slots(plain_json)
    current = dict(current_slots) if isinstance(current_slots, dict) else {}
    repaired_groups = []
    output = dict(current)
    output["类型"] = str(current.get("类型") or template_type or reg.DEFAULT_TYPE)

    for group_name in ("文字槽位", "素材槽位"):
        group_errors = validate_slot_group(current.get(group_name), plain_json, group_name)
        if group_errors:
            output[group_name] = expected[group_name]
            repaired_groups.append(group_name)

    # 旧版自动槽位按整条轨道合并；拆分它们，保留人工命名槽位的业务含义。
    text_slots = output.get("文字槽位", [])
    used_keys = {slot["键名"] for slot in text_slots}
    expected_by_target = {(slot["轨道序号"], slot["片段"][0]): slot
                          for slot in expected["文字槽位"]}
    migrated = []
    for slot in text_slots:
        if re.fullmatch(r"文字位\d+", slot["键名"]) and len(slot["片段"]) > 1:
            for position, index in enumerate(slot["片段"]):
                replacement = dict(slot)
                replacement["片段"] = [index]
                if position:
                    key = f"{slot['键名']}_片段{index + 1}"
                    while key in used_keys:
                        key += "_新"
                    replacement["键名"] = key
                    used_keys.add(key)
                original = expected_by_target[(slot["轨道序号"], index)]
                replacement["文案要求"] = original["文案要求"]
                replacement["原文案示例"] = original["原文案示例"]
                migrated.append(replacement)
            if "文字槽位" not in repaired_groups:
                repaired_groups.append("文字槽位")
        else:
            migrated.append(slot)
    output["文字槽位"] = migrated

    if validate_slots(output, plain_json):
        output["文字槽位"] = expected["文字槽位"]
        output["素材槽位"] = expected["素材槽位"]
        repaired_groups = ["文字槽位", "素材槽位"]

    final_errors = validate_slots(output, plain_json)
    if final_errors:
        raise TemplateHealthError("槽位自动修复后仍不正确: " + "；".join(final_errors))
    return output, list(dict.fromkeys(repaired_groups))


def _load_slots_file(path: str):
    try:
        with open(path, "r", encoding="utf-8-sig") as handle:
            return json.load(handle)
    except (OSError, ValueError, TypeError):
        return None


def _atomic_write_json(path: str, data) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix=".slots_", suffix=".json", dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temp_path, path)
    except Exception:
        try:
            os.remove(temp_path)
        except OSError:
            pass
        raise


def _short_reason(exc: Exception) -> str:
    text = str(exc).replace("\r", " ").replace("\n", " ").strip()
    return (text or exc.__class__.__name__)[:300]


def preflight_templates(root: str, crypto, registry=None, repair: bool = True) -> dict:
    """体检全部模板；可修复槽位自动修复，其余模板停用并写明原因。"""
    registry = list(registry if registry is not None else reg.load_registry(root))
    result = {"valid": [], "disabled": [], "repaired": []}
    registry_changed = False

    for entry in registry:
        name = str(entry.get("名字", "")).strip()
        try:
            if not name:
                raise TemplateHealthError("模板清单存在空模板名")
            content_path = os.path.join(reg.template_draft_dir(root, name), "draft_content.json")
            if not os.path.isfile(content_path):
                raise TemplateHealthError("模板草稿文件不存在")
            with open(content_path, "rb") as handle:
                raw = handle.read()
            plain_bytes = crypto.decrypt(raw)
            try:
                plain_json = json.loads(plain_bytes.decode("utf-8"))
            except (UnicodeDecodeError, ValueError, TypeError) as exc:
                raise TemplateHealthError(f"草稿JSON无法读取: {exc}") from exc
            if not isinstance(plain_json, dict):
                raise TemplateHealthError("草稿JSON根节点不是对象")

            # 加密器自身也做解密回环，这里确保模板能重新写成当前剪映可读格式。
            crypto.encrypt(plain_bytes)

            slots_path = os.path.join(reg.template_dir(root, name), "slots.json")
            current_slots = _load_slots_file(slots_path)
            errors = validate_slots(current_slots, plain_json)
            repaired_groups = []
            if errors:
                if not repair:
                    raise TemplateHealthError("槽位配置不正确: " + "；".join(errors))
                repaired_slots, repaired_groups = repair_slots(
                    current_slots, plain_json, entry.get("类型") or reg.DEFAULT_TYPE
                )
                _atomic_write_json(slots_path, repaired_slots)
            if repaired_groups:
                result["repaired"].append({"name": name, "groups": repaired_groups})

            if entry.get("启用") is not True or entry.get("停用原因"):
                entry["启用"] = True
                entry.pop("停用原因", None)
                registry_changed = True
            result["valid"].append(name)
        except Exception as exc:
            reason = _short_reason(exc)
            if entry.get("启用") is not False or entry.get("停用原因") != reason:
                entry["启用"] = False
                entry["停用原因"] = reason
                registry_changed = True
            result["disabled"].append({"name": name or "(未命名)", "reason": reason})

    if registry_changed:
        reg.save_registry(root, registry)
    result["registry"] = registry
    return result
