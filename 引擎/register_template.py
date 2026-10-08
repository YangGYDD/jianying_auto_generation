# -*- coding: utf-8 -*-
"""模板注册器: 由“模板管理”调用，分析剪映草稿并注册进模板库.

用法:
    python register_template.py                            # 交互模式
    python register_template.py "<草稿名称>" --type 金融    # 直接注册

    流程: 解密草稿 -> 分析轨道结构 -> 自动生成 slots.json(含各文字位文案要求)
      -> 复制并本地化到 模板库/<模板名>/草稿/ -> 更新 模板库/模板清单.json
已有模板不受影响; 同名注册会询问是否覆盖(保留原使用次数).
"""
import json
import os
import re
import shutil
import sys
import datetime
import tempfile

ENGINE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ENGINE_DIR)
import pyJianYingDraft as draft  # noqa: E402
from jycrypto import JianyingCrypto, find_jianying_dir  # noqa: E402
import template_registry as reg  # noqa: E402
from localize_template import localize  # noqa: E402
from template_health import (  # noqa: E402
    analyze_slots,
    derive_text_spec as _derive_text_spec,
    validate_slots,
)

ROOT = os.environ.get("TOOL_ROOT") or os.path.dirname(ENGINE_DIR)
INVALID_CHARS = re.compile(r'[\\/:*?"<>|]+')


def find_drafts_dir() -> str:
    p = os.path.join(os.environ.get("LOCALAPPDATA", ""),
                     "JianyingPro", "User Data", "Projects", "com.lveditor.draft")
    if not os.path.isdir(p):
        raise FileNotFoundError(f"未找到剪映草稿目录: {p}")
    return p


def list_drafts(drafts_dir: str):
    out = []
    for name in sorted(os.listdir(drafts_dir)):
        p = os.path.join(drafts_dir, name)
        if os.path.isfile(os.path.join(p, "draft_content.json")):
            out.append((name, os.path.getmtime(os.path.join(p, "draft_content.json"))))
    return out


def derive_text_spec(texts: list) -> str:
    return _derive_text_spec(texts)


def analyze(plain_json: dict) -> dict:
    """分析草稿结构, 生成 slots.json 内容。"""
    return analyze_slots(plain_json)


def _ask_type() -> str:
    print()
    print("模板类型即新闻文件里\"类型\"字段的值 (如: 金融 / 科技)。")
    print(f"没有对应类型模板的新闻会用\"{reg.DEFAULT_TYPE}\"模板兜底。")
    t = input("请输入本模板的类型 (直接回车 = 默认): ").strip()
    return INVALID_CHARS.sub("", t) or reg.DEFAULT_TYPE


def main():
    drafts_dir = find_drafts_dir()

    # 命令行参数: 草稿名 与 --type / --name
    args = sys.argv[1:]
    cli_type = None
    if "--type" in args:
        i = args.index("--type")
        cli_type = INVALID_CHARS.sub("", args[i + 1].strip()) if i + 1 < len(args) else None
        del args[i:i + 2]
    cli_name = None
    if "--name" in args:
        i = args.index("--name")
        cli_name = INVALID_CHARS.sub("", args[i + 1].strip()) if i + 1 < len(args) else None
        del args[i:i + 2]

    # 1) 确定目标草稿
    if args:
        target = args[0]
        if not os.path.isfile(os.path.join(drafts_dir, target, "draft_content.json")):
            print(f"剪映草稿目录中没有找到草稿: {target}")
            sys.exit(1)
    else:
        drafts = list_drafts(drafts_dir)
        if not drafts:
            print("剪映草稿目录中没有草稿")
            sys.exit(1)
        print("检测到以下剪映草稿 (按最近修改排序):")
        order = sorted(drafts, key=lambda x: x[1], reverse=True)
        for i, (name, mt) in enumerate(order, 1):
            ts = datetime.datetime.fromtimestamp(mt).strftime("%Y-%m-%d %H:%M")
            print(f"  [{i}] {name}  (修改于 {ts})")
        choice = input("输入序号选择要注册为模板的草稿: ").strip()
        try:
            target = order[int(choice) - 1][0]
        except (ValueError, IndexError):
            print("输入无效")
            sys.exit(1)

    tpl_name = cli_name or INVALID_CHARS.sub("", target)
    src = os.path.join(drafts_dir, target)
    print(f"\n正在解密并分析草稿: {target}")

    # 2) 解密分析
    crypto = JianyingCrypto(find_jianying_dir())
    with open(os.path.join(src, "draft_content.json"), "rb") as f:
        raw = f.read()
    try:
        plain = json.loads(crypto.decrypt(raw).decode("utf-8"))
    except RuntimeError as e:
        print(f"解密失败: {e}")
        print("提示: 该草稿可能由更高版本剪映加密, 请确认剪映版本为 10.3~10.6.5")
        sys.exit(1)

    slots = analyze(plain)
    canvas = plain.get("canvas_config", {})
    print(f"画布: {canvas.get('width')}x{canvas.get('height')} | "
          f"时长: {plain.get('duration', 0)/1e6:.1f}s")
    print(f"识别到 {len(slots['文字槽位'])} 个文字槽位, {len(slots['素材槽位'])} 个素材槽位:")
    for s in slots["文字槽位"]:
        print(f"  [文字] {s['键名']}: {s['文案要求']}")
    for s in slots["素材槽位"]:
        print(f"  [素材] {s['键名']}")

    # 3) 类型与重名处理
    registry = reg.load_registry(ROOT)
    old_entry = reg.find_entry(registry, tpl_name)
    if old_entry is not None:
        if not sys.stdin.isatty():
            print(f"模板名 [{tpl_name}] 已存在, 非交互模式不覆盖, 退出")
            sys.exit(1)
        ans = input(f"模板名 [{tpl_name}] 已存在, 覆盖它? (y/N): ").strip().lower()
        if ans != "y":
            print("已取消")
            sys.exit(0)

    if cli_type is not None:
        tpl_type = cli_type
    elif old_entry is not None and sys.stdin.isatty():
        keep = input(f"沿用原类型 [{old_entry.get('类型')}]? (Y/n): ").strip().lower()
        tpl_type = old_entry.get("类型", reg.DEFAULT_TYPE) if keep != "n" else _ask_type()
    elif old_entry is not None:
        tpl_type = old_entry.get("类型", reg.DEFAULT_TYPE)
    elif sys.stdin.isatty():
        tpl_type = _ask_type()
    else:
        print("非交互模式必须用 --type 指定类型")
        sys.exit(1)

    # 4) 复制模板并把本机缓存路径改为模板相对路径
    dst = reg.template_dir(ROOT, tpl_name)
    os.makedirs(reg.lib_dir(ROOT), exist_ok=True)
    staging_parent = tempfile.mkdtemp(prefix=".template_register_", dir=reg.lib_dir(ROOT))
    staging_dst = os.path.join(staging_parent, "template")
    try:
        os.makedirs(staging_dst)
        draft_dst = os.path.join(staging_dst, "草稿")
        shutil.copytree(src, draft_dst)
        localize_stats = localize(draft_dst)
        missing = sorted(set(localize_stats.get("missing", [])))
        if missing:
            print("模板注册失败: 以下素材未随草稿复制到模板目录, 无法保证换电脑后可用:")
            for name in missing:
                print(f"  - {name}")
            sys.exit(1)

        print(f"素材路径已本地化: 改写 {localize_stats['rewritten']} 处, "
              f"已有相对路径 {localize_stats['already_ok']} 处")

        # 写入 slots.json (含类型)
        slots_out = {"类型": tpl_type}
        slots_out.update(slots)
        with open(os.path.join(draft_dst, "draft_content.json"), "rb") as f:
            localized_plain = json.loads(crypto.decrypt(f.read()).decode("utf-8"))
        slot_errors = validate_slots(slots_out, localized_plain)
        if slot_errors:
            raise RuntimeError("模板槽位检查失败: " + "；".join(slot_errors))
        with open(os.path.join(staging_dst, "slots.json"), "w", encoding="utf-8") as f:
            json.dump(slots_out, f, ensure_ascii=False, indent=2)

        # 全部校验通过后再替换正式目录, 覆盖失败不会丢失旧模板。
        if os.path.exists(dst):
            shutil.rmtree(dst)
        shutil.move(staging_dst, dst)
    finally:
        shutil.rmtree(staging_parent, ignore_errors=True)

    # 5) 更新注册表
    if old_entry is not None:
        old_entry["类型"] = tpl_type
        old_entry["启用"] = True
        old_entry.pop("停用原因", None)
        print(f"已覆盖原模板 [{tpl_name}] (使用次数保留: {old_entry.get('使用次数', 0)})")
    else:
        registry.append({"名字": tpl_name, "类型": tpl_type, "使用次数": 0, "启用": True})
    reg.save_registry(ROOT, registry)

    same_type = [e["名字"] for e in registry
                 if reg.is_enabled(e) and e.get("类型") == tpl_type]
    print(f"\n注册完成! 模板 [{tpl_name}] 类型 [{tpl_type}]")
    print(f"该类型现有模板: {', '.join(same_type)} (手动运行时会出现在模板选择清单)")
    print("建议: 先试跑一条新闻, 检查文字位置是否符合预期;")
    print("      若个别文字位不理想, 可手工修改该模板 slots.json 中的文案要求。")


if __name__ == "__main__":
    main()
