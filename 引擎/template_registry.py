# -*- coding: utf-8 -*-
"""模板库与素材池管理: 注册表读写、按类型选模板(用最少优先)、
素材池取素材(用最少优先, 循环复用)与使用计数."""
import json
import os

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".flv", ".wmv", ".ts"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".gif"}
MEDIA_EXTS = VIDEO_EXTS | IMAGE_EXTS

REGISTRY_FILE = "模板清单.json"
USE_RECORDS_FILE = "使用记录.json"
DEFAULT_TYPE = "默认"


# ---------- 目录 ----------
def lib_dir(root: str) -> str:
    return os.path.join(root, "模板库")


def pool_root(root: str) -> str:
    return os.path.join(root, "素材库")


def template_dir(root: str, name: str) -> str:
    return os.path.join(lib_dir(root), name)


def template_draft_dir(root: str, name: str) -> str:
    return os.path.join(template_dir(root, name), "草稿")


# ---------- 注册表 ----------
def load_registry(root: str) -> list:
    path = os.path.join(lib_dir(root), REGISTRY_FILE)
    if not os.path.isfile(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_registry(root: str, registry: list) -> None:
    os.makedirs(lib_dir(root), exist_ok=True)
    path = os.path.join(lib_dir(root), REGISTRY_FILE)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(registry, f, ensure_ascii=False, indent=2)


def find_entry(registry: list, name: str):
    for e in registry:
        if e["名字"] == name:
            return e
    return None


def is_enabled(entry: dict) -> bool:
    """旧模板清单没有启用字段时按启用处理。"""
    return isinstance(entry, dict) and entry.get("启用", True) is not False


def enabled_entries(registry: list) -> list:
    return [entry for entry in registry if is_enabled(entry)]


def templates_of_type(registry: list, type_name: str) -> list:
    return [e for e in registry if is_enabled(e) and e.get("类型") == type_name]


def pick_template(registry: list, type_name: str) -> str:
    """按类型选模板: 使用次数最少优先; 该类型无模板时用默认模板兜底."""
    candidates = templates_of_type(registry, type_name)
    if not candidates and type_name != DEFAULT_TYPE:
        candidates = templates_of_type(registry, DEFAULT_TYPE)
    if not candidates:
        raise RuntimeError("模板库为空, 请先注册模板 (双击 模板管理.bat)")
    best = min(candidates, key=lambda e: (e.get("使用次数", 0), e["名字"]))
    return best["名字"]


def fallback_template(registry: list) -> str:
    """优先使用名为“默认”的健康模板，否则使用次数最少的健康模板。"""
    enabled = enabled_entries(registry)
    if not enabled:
        raise RuntimeError("没有可用模板, 请查看报告中的模板停用原因")
    default_entry = find_entry(enabled, DEFAULT_TYPE)
    if default_entry is not None:
        return default_entry["名字"]
    return min(enabled, key=lambda entry: (entry.get("使用次数", 0), entry["名字"]))["名字"]


def increment_template_use(registry: list, name: str) -> None:
    e = find_entry(registry, name)
    if e is not None:
        e["使用次数"] = e.get("使用次数", 0) + 1


# ---------- 槽位配置 ----------
def load_slots(root: str, template_name: str) -> dict:
    path = os.path.join(template_dir(root, template_name), "slots.json")
    if not os.path.isfile(path):
        raise FileNotFoundError(f"模板 [{template_name}] 缺少 slots.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def slot_specs_from_slots(slots: dict) -> dict:
    """文字槽位 -> {键名: 文案要求}, 供豆包生成文案"""
    specs = {s["键名"]: (s.get("文案要求", "一段简短的新闻文案, 不超过12个字")
                        + f"；文字轨道{s['轨道序号'] + 1}，片段"
                        + "、".join(str(i + 1) for i in s["片段"]))
             for s in slots.get("文字槽位", [])}
    return specs or None


# ---------- 素材池 ----------
def pool_dir(root: str, type_name: str) -> str:
    return os.path.join(pool_root(root), type_name)


def load_use_records(root: str) -> dict:
    path = os.path.join(pool_root(root), USE_RECORDS_FILE)
    if not os.path.isfile(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_use_records(root: str, records: dict) -> None:
    os.makedirs(pool_root(root), exist_ok=True)
    path = os.path.join(pool_root(root), USE_RECORDS_FILE)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)


def list_pool_files(root: str, type_name: str) -> list:
    """列出某类型素材池内的媒体文件(绝对路径), 按文件名排序"""
    d = pool_dir(root, type_name)
    if not os.path.isdir(d):
        return []
    return sorted(
        os.path.join(d, f) for f in os.listdir(d)
        if os.path.isfile(os.path.join(d, f))
        and os.path.splitext(f)[1].lower() in MEDIA_EXTS
    )


def _rel_key(root: str, path: str) -> str:
    return os.path.relpath(path, pool_root(root)).replace("\\", "/")


def pick_from_pool(root: str, type_name: str, count: int, use_records: dict) -> list:
    """从类型素材池取 count 个素材: 使用次数最少优先, 不够时循环复用.
    选中的素材立即在 use_records 中计数+1(内存中), 调用方负责落盘."""
    files = list_pool_files(root, type_name)
    if not files and type_name != DEFAULT_TYPE:
        files = list_pool_files(root, DEFAULT_TYPE)   # 兜底池
    if not files:
        return []
    selected = []
    for _ in range(count):
        best = min(files, key=lambda p: (use_records.get(_rel_key(root, p), 0), p))
        selected.append(best)
        use_records[_rel_key(root, best)] = use_records.get(_rel_key(root, best), 0) + 1
    return selected
