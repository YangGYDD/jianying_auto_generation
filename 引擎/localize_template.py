# -*- coding: utf-8 -*-
"""模板素材本地化: 把草稿 JSON 中指向本机缓存的素材绝对路径,
改写为草稿相对路径(##__draftpath_placeholder_UUID_##/...),
使模板文件夹复制到其他电脑后素材依然有效.

前提: 相应素材文件已存在于模板文件夹内 (materials/ 或 Resources/ 下).

用法:
    python localize_template.py <模板草稿文件夹>
"""
import json
import os
import re
import sys

ENGINE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ENGINE_DIR)
from jycrypto import JianyingCrypto, find_jianying_dir  # noqa: E402

PLACEHOLDER_RE = re.compile(r"##__draftpath_placeholder_([0-9A-Fa-f-]+)_##")
SEARCH_SUBDIRS = ["materials/video", "materials/audio", "materials/image",
                  "materials/beat", "Resources/local", "Resources"]
MEDIA_MATERIAL_KEYS = {"videos", "audios", "images", "beats"}


def find_local_file(tpl_dir: str, basename: str):
    """在模板文件夹内查找同名文件, 返回相对子路径(正斜杠)或 None"""
    for sub in SEARCH_SUBDIRS:
        cand = os.path.join(tpl_dir, sub, basename)
        if os.path.isfile(cand):
            return f"{sub}/{basename}"
    # 兜底: 递归搜索(限两层)
    for base, dirs, files in os.walk(tpl_dir):
        rel = os.path.relpath(base, tpl_dir).replace("\\", "/")
        if rel.count("/") > 1 or rel.startswith("工程备份"):
            dirs[:] = []
            continue
        if basename in files:
            return f"{rel}/{basename}" if rel != "." else basename
    return None


def localize(tpl_dir: str) -> dict:
    content_path = os.path.join(tpl_dir, "draft_content.json")
    crypto = JianyingCrypto(find_jianying_dir())
    with open(content_path, "rb") as f:
        raw = f.read()
    try:
        plain = crypto.decrypt(raw).decode("utf-8")
    except RuntimeError as e:
        print(f"解密失败: {e}")
        print("提示: 草稿可能由更高版本剪映加密")
        sys.exit(1)
    data = json.loads(plain)

    # 复用草稿中已有的占位符 UUID, 没有则生成一个
    existing_uuid = None
    m = PLACEHOLDER_RE.search(plain)
    if m:
        existing_uuid = m.group(1)
    else:
        import uuid
        existing_uuid = str(uuid.uuid4()).upper()
    prefix = f"##__draftpath_placeholder_{existing_uuid}_##"

    stats = {"rewritten": 0, "already_ok": 0, "missing": []}

    def fix_path(p: str):
        if not isinstance(p, str) or not p:
            return p
        if p.startswith("##"):
            stats["already_ok"] += 1
            return p
        if "/" not in p and "\\" not in p:
            return p
        base = os.path.basename(p.replace("\\", "/"))
        rel = find_local_file(tpl_dir, base)
        if rel is None:
            stats["missing"].append(base)
            return p
        stats["rewritten"] += 1
        return f"{prefix}/{rel}"

    # 只处理真正随草稿携带的媒体; effects/transitions/hsl 中的 path
    # 是剪映内部缓存标识, 不应按普通文件检查。
    for key in MEDIA_MATERIAL_KEYS:
        mat_list = data.get("materials", {}).get(key, [])
        if not isinstance(mat_list, list):
            continue
        for mat in mat_list:
            if isinstance(mat, dict) and isinstance(mat.get("path"), str):
                mat["path"] = fix_path(mat["path"])

    new_plain = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    encrypted = crypto.encrypt(new_plain.encode("utf-8"))
    # 备份原文件
    bak = content_path + ".pre_localize.bak"
    if not os.path.exists(bak):
        with open(bak, "wb") as f:
            f.write(raw)
    with open(content_path, "wb") as f:
        f.write(encrypted)
    return stats


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(64)
    tpl_dir = os.path.abspath(sys.argv[1])
    if not os.path.isfile(os.path.join(tpl_dir, "draft_content.json")):
        print(f"不是有效的草稿文件夹: {tpl_dir}")
        sys.exit(1)
    print(f"正在本地化模板: {tpl_dir}")
    stats = localize(tpl_dir)
    print(f"完成: 改写 {stats['rewritten']} 处路径, "
          f"已是相对路径 {stats['already_ok']} 处")
    if stats["missing"]:
        print("警告: 以下素材在模板文件夹中找不到本地文件, 到其他电脑会缺失:")
        for m in set(stats["missing"]):
            print("  -", m)
