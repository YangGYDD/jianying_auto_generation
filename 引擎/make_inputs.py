# -*- coding: utf-8 -*-
"""第一段流水线: 从新闻记录生成 输入/<类型>/<新闻>/ 文件夹(含豆包写好的文案).

用法:
    python make_inputs.py <新闻记录.json> [--root <工具根目录>]

新闻记录.json 格式(列表, 每条):
    {"seq": "344", "title": "...", "type": "金融", "source": "...",
     "date": "2026-08-06", "link": "https://...", "summary": "..."}

模板处理:
    - 自动化可为本次运行指定一个模板, 本批全部新闻统一使用
    - 也可在全部已注册模板中随机混用, 每条新闻仍只使用一套模板
    - 未指定时仍按记录的"类型"选择, 没有对应类型模板时用"默认"模板兜底
    - 文案按所选模板的版式(文字槽位要求)生成
    - 每条新闻的文件夹里写入 模板.txt/类型.txt, 供第二段使用
"""
import json
import datetime
import hashlib
import os
import random
import re
import sys

ENGINE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ENGINE_DIR)
from news_text import (  # noqa: E402
    CONTENT_CATEGORY_KEY,
    load_config,
    normalize_content_category,
    summarize_record,
)
import template_registry as reg  # noqa: E402

INVALID_CHARS = re.compile(r'[\\/:*?"<>|\s]+')


def clean_folder_name(seq: str, title: str) -> str:
    t = INVALID_CHARS.sub("", title)[:14] or "未命名新闻"
    return f"{seq}_{t}"


def encode_value(text: str) -> str:
    """info.txt 一行一条, 真实换行要转成字面 \\n"""
    return text.replace("\r", "").replace("\n", "\\n")


def _iter_episode_paths(input_dir: str):
    if not os.path.isdir(input_dir):
        return
    for name in os.listdir(input_dir):
        p = os.path.join(input_dir, name)
        if not os.path.isdir(p):
            continue
        if os.path.isfile(os.path.join(p, "info.txt")):
            yield p
        else:
            for sub in os.listdir(p):
                sp = os.path.join(p, sub)
                if os.path.isfile(os.path.join(sp, "info.txt")):
                    yield sp


def _read_dedupe_key(folder: str) -> str:
    path = os.path.join(folder, "新闻指纹.txt")
    if not os.path.isfile(path):
        return ""
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            return f.read().strip()
    except OSError:
        return ""


def find_episode_by_key(input_dir: str, key: str) -> str:
    if not key:
        return ""
    for folder in _iter_episode_paths(input_dir):
        if _read_dedupe_key(folder) == key:
            return folder
    return ""


def build_inputs(records_file: str, root: str, allow_existing: bool = False,
                 template_override: str = None, random_templates: bool = False,
                 api_config: dict = None) -> dict:
    input_dir = os.path.join(root, "输入")
    os.makedirs(input_dir, exist_ok=True)
    cfg = api_config if api_config is not None else load_config()["doubao"]

    full_registry = reg.load_registry(root)
    registry = reg.enabled_entries(full_registry)
    if not registry:
        raise RuntimeError("没有可用模板, 请查看自动化报告中的模板停用原因")
    if random_templates and template_override is not None:
        raise ValueError("随机混用模板时不能同时指定统一模板")
    forced_template = None
    if template_override is not None:
        template_name = str(template_override).strip()
        forced_template = reg.find_entry(registry, template_name)
        if forced_template is None:
            available = "、".join(entry["名字"] for entry in registry)
            raise ValueError(f"指定模板 [{template_name}] 不可用, 可用模板: {available}")

    with open(records_file, "r", encoding="utf-8") as f:
        records = json.load(f)
    print(f"共 {len(records)} 条新闻记录")

    ok, skipped, failed = 0, 0, 0
    generated_items, failed_items, skipped_items = [], [], []
    random_order = list(registry) if random_templates else []
    random_index = 0
    if random_order:
        random.shuffle(random_order)
    existing_paths = list(_iter_episode_paths(input_dir))
    existing_folders = {os.path.basename(p) for p in existing_paths}
    existing_keys = {_read_dedupe_key(p) for p in existing_paths}
    existing_keys.discard("")
    for i, rec in enumerate(records, 1):
        title = rec.get("title", "").strip()
        seq = str(rec.get("seq", i)).strip() or str(i)
        news_type = (rec.get("type") or "").strip()
        label = f"[{i}/{len(records)}] {title[:30]}"

        dedupe_key = str(rec.get("_dedupe_key", "")).strip()
        # 自动化记录用“规范化链接+标题”指纹去重; 旧格式文件仍按序号兼容。
        if not allow_existing and ((dedupe_key and dedupe_key in existing_keys) or (
                not dedupe_key and any(f.startswith(seq + "_") for f in existing_folders))):
            print(f"{label} -> 序号 {seq} 已生成过, 跳过")
            skipped += 1
            skipped_items.append({
                "record": rec,
                "reason": "已生成过",
                "folder": find_episode_by_key(input_dir, dedupe_key) if dedupe_key else "",
            })
            continue

        # 随机模式按打乱后的模板清单循环，避免少量新闻碰巧全部使用同一模板。
        if random_templates:
            if random_index and random_index % len(random_order) == 0:
                random.shuffle(random_order)
            tpl_entry = random_order[random_index % len(random_order)]
            random_index += 1
            tpl_name = tpl_entry["名字"]
        elif forced_template:
            tpl_entry = forced_template
            tpl_name = forced_template["名字"]
        else:
            tpl_name = reg.pick_template(registry, news_type or reg.DEFAULT_TYPE)
            tpl_entry = reg.find_entry(registry, tpl_name)
        slots = reg.load_slots(root, tpl_name)
        slot_specs = reg.slot_specs_from_slots(slots)
        fallback = (not forced_template and not random_templates and bool(news_type)
                    and not reg.templates_of_type(registry, news_type))

        try:
            result = summarize_record(rec, cfg, slot_specs)
        except Exception as e:
            print(f"{label} -> 文案生成失败: {e}")
            failed += 1
            failed_items.append({"record": rec, "error": str(e), "template": tpl_name})
            continue

        if "skip" in result:
            print(f"{label} -> 模型判定信息不足, 跳过: {result['skip']}")
            skipped += 1
            skipped_items.append({"record": rec, "reason": result["skip"], "template": tpl_name})
            continue

        content_category = normalize_content_category(result.get(CONTENT_CATEGORY_KEY))
        result[CONTENT_CATEGORY_KEY] = content_category
        rec["content_category"] = content_category
        material_type = content_category

        # 文件夹: 输入/<类型>/<序号>_<标题>/
        type_dir_name = INVALID_CHARS.sub("", material_type) or reg.DEFAULT_TYPE
        folder_title = result.get("大标题") or next(iter(result.values()))
        folder_name = clean_folder_name(seq, folder_title)
        if allow_existing:
            base_folder_name = folder_name + datetime.datetime.now().strftime("_%Y%m%d_%H%M%S")
            folder_name = base_folder_name
            copy_index = 2
            while folder_name in existing_folders:
                folder_name = f"{base_folder_name}_{copy_index}"
                copy_index += 1
        folder = os.path.join(input_dir, type_dir_name, folder_name)
        if not allow_existing and os.path.exists(folder) and dedupe_key and dedupe_key not in existing_keys:
            folder_name += "_" + hashlib.sha256(dedupe_key.encode("utf-8")).hexdigest()[:8]
            folder = os.path.join(input_dir, type_dir_name, folder_name)
        if not allow_existing and (
                os.path.exists(folder) or (folder_name in existing_folders and not dedupe_key)):
            print(f"{label} -> 文件夹已存在, 跳过")
            skipped += 1
            skipped_items.append({"record": rec, "reason": "文件夹已存在", "template": tpl_name})
            continue

        os.makedirs(folder, exist_ok=True)
        # 记录本条新闻选定的模板与类型 (第二段据此生成)
        with open(os.path.join(folder, "模板.txt"), "w", encoding="utf-8") as f:
            f.write(tpl_name)
        with open(os.path.join(folder, "类型.txt"), "w", encoding="utf-8") as f:
            f.write(material_type)
        # 文案
        lines = [
            f"# 新闻: {title}",
            f"# 来源: {rec.get('source', '')}  日期: {(rec.get('date') or '')[:10]}",
            f"# 素材类型: {material_type}  使用模板: {tpl_name}",
            "# 以下为系统生成的文案, 可手工微调; 素材可不放(自动从素材池取)",
        ]
        lines += [f"{k}={encode_value(v)}" for k, v in result.items()]
        with open(os.path.join(folder, "info.txt"), "w", encoding="utf-8-sig", newline="") as f:
            f.write("\n".join(lines) + "\n")
        # 原文链接(供找素材参考)
        with open(os.path.join(folder, "原文链接.txt"), "w", encoding="utf-8") as f:
            f.write(f"标题: {title}\n来源: {rec.get('source', '')}\n日期: {(rec.get('date') or '')[:10]}\n"
                    f"链接: {rec.get('link', '')}\n摘要: {rec.get('summary', '')}\n")
        if dedupe_key:
            with open(os.path.join(folder, "新闻指纹.txt"), "w", encoding="utf-8") as f:
                f.write(dedupe_key)

        reg.increment_template_use(full_registry, tpl_name)
        existing_folders.add(folder_name)
        if dedupe_key:
            existing_keys.add(dedupe_key)
        extra = " (该类型无模板, 用默认模板兜底)" if fallback else ""
        print(f"{label} -> 已生成 {type_dir_name}/{folder_name} [模板:{tpl_name}]{extra}")
        ok += 1
        generated_items.append({
            "record": rec,
            "folder": folder,
            "folder_name": folder_name,
            "template": tpl_name,
            "content_category": content_category,
        })

    # 停用模板仍需保留在清单中，后续修复后可由体检自动恢复。
    reg.save_registry(root, full_registry)
    print()
    print(f"完成: 生成 {ok} 条, 跳过 {skipped} 条, 失败 {failed} 条")
    print("如需手工指定素材, 请放入对应新闻文件夹; 自动化流程会继续生成剪映草稿")
    return {
        "generated": ok,
        "skipped": skipped,
        "failed": failed,
        "generated_items": generated_items,
        "failed_items": failed_items,
        "skipped_items": skipped_items,
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(64)
    records_file = os.path.abspath(sys.argv[1])
    root = os.path.dirname(ENGINE_DIR)
    if "--root" in sys.argv:
        root = os.path.abspath(sys.argv[sys.argv.index("--root") + 1])
    result = build_inputs(records_file, root)
    sys.exit(0 if result["failed"] == 0 else 1)
