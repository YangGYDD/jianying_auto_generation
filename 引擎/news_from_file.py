# -*- coding: utf-8 -*-
"""第一段(业务机版): 读取"新闻数据"文件夹中由爬取系统导出的新闻文件,
调用豆包生成文案, 在 输入/<类型>/<新闻>/ 下产出文件夹.

支持的导出格式:
  1) JSON: 列表, 每条 {"序号/seq","标题/title","类型/type","来源/source",
                       "日期/date","链接/link","摘要/summary"}
  2) CSV:  表头含 序号|标题|类型|来源|日期|链接|摘要 (或英文键名),
           逗号分隔, UTF-8 编码

"类型"字段(如 金融/科技)决定使用哪套模板和哪个素材池;
无对应类型模板时用默认模板兜底。

处理过的文件会自动移入 新闻数据/已处理/, 不会重复处理.

用法:
    python news_from_file.py [--root <工具根目录>] [--count <数量>]
"""
import argparse
import csv
import json
import os
import shutil
import sys

ENGINE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ENGINE_DIR)
from make_inputs import build_inputs  # noqa: E402

KEY_MAP = {
    "序号": "seq", "seq": "seq", "id": "seq",
    "标题": "title", "title": "title",
    "类型": "type", "分类": "type", "type": "type", "category": "type",
    "来源": "source", "source": "source",
    "日期": "date", "date": "date",
    "链接": "link", "link": "link", "url": "link",
    "摘要": "summary", "summary": "summary", "简介": "summary",
}
DEFAULT_COUNT = 5
MAX_COUNT = 100


def normalize_record(raw: dict, index: int) -> dict:
    rec = {}
    for k, v in raw.items():
        std = KEY_MAP.get(str(k).strip().lower()) or KEY_MAP.get(str(k).strip())
        if std:
            rec[std] = str(v).strip() if v is not None else ""
    if "title" not in rec or not rec.get("title"):
        raise ValueError(f"第{index}条缺少标题字段")
    rec.setdefault("seq", str(index))
    return rec


def load_news_file(path: str) -> list:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".json":
        with open(path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
        if isinstance(data, dict):
            data = data.get("records") or data.get("新闻") or [data]
        return [normalize_record(r, i) for i, r in enumerate(data, 1)]
    if ext == ".csv":
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
        return [normalize_record(r, i) for i, r in enumerate(rows, 1)]
    raise ValueError(f"不支持的文件类型: {ext} (支持 .json / .csv)")


def write_news_file(path: str, records: list) -> None:
    """把未处理记录写回原文件，避免限量处理时丢失后续新闻。"""
    ext = os.path.splitext(path)[1].lower()
    temp_path = path + ".tmp"
    if ext == ".json":
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False, indent=2)
    elif ext == ".csv":
        fields = ["序号", "标题", "类型", "来源", "日期", "链接", "摘要"]
        with open(temp_path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            for record in records:
                writer.writerow({
                    "序号": record.get("seq", ""),
                    "标题": record.get("title", ""),
                    "类型": record.get("type", ""),
                    "来源": record.get("source", ""),
                    "日期": record.get("date", ""),
                    "链接": record.get("link", ""),
                    "摘要": record.get("summary", ""),
                })
    else:
        raise ValueError(f"不支持的文件类型: {ext}")
    os.replace(temp_path, path)


def record_identity(record: dict) -> tuple:
    return (
        str(record.get("seq", "")),
        str(record.get("link", "")),
        str(record.get("title", "")),
    )


def handled_identities(stats: dict) -> set:
    """返回本次已经生成或明确跳过的记录；失败记录要留在源文件重试。"""
    identities = set()
    for key in ("generated_items", "skipped_items"):
        for item in stats.get(key, []):
            record = item.get("record") or {}
            identities.add(record_identity(record))
    return identities


def count_arg(value: str) -> int:
    try:
        count = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("数量必须是整数") from exc
    if not 1 <= count <= MAX_COUNT:
        raise argparse.ArgumentTypeError(f"数量必须是 1 到 {MAX_COUNT} 之间的整数")
    return count


def main():
    parser = argparse.ArgumentParser(description="从新闻数据文件生成文案输入")
    parser.add_argument("--root", default=os.path.dirname(ENGINE_DIR),
                        help="工具根目录")
    parser.add_argument("--count", type=count_arg, default=DEFAULT_COUNT,
                        help="每次最多处理的新闻数量 (默认 5)")
    args = parser.parse_args()
    root = os.path.abspath(args.root)

    news_dir = os.path.join(root, "新闻数据")
    done_dir = os.path.join(news_dir, "已处理")
    os.makedirs(news_dir, exist_ok=True)
    os.makedirs(done_dir, exist_ok=True)

    files = sorted(
        f for f in os.listdir(news_dir)
        if os.path.isfile(os.path.join(news_dir, f))
        and os.path.splitext(f)[1].lower() in (".json", ".csv")
    )
    print("=" * 52)
    print("      新闻文案生成 (读取导出文件)")
    print("=" * 52)
    if not files:
        print(f"\n\"新闻数据\"文件夹里没有待处理的新闻文件。\n"
              f"请把爬取系统导出的 .json 或 .csv 文件放到:\n  {news_dir}\n然后再运行。")
        return 0

    total_ok, total_fail, total_retry, total_pending = 0, 0, 0, 0
    remaining_budget = args.count
    for fn in files:
        if remaining_budget <= 0:
            break
        path = os.path.join(news_dir, fn)
        print(f"\n>>> 处理文件: {fn}")
        try:
            records = load_news_file(path)
        except Exception as e:
            print(f"    文件解析失败: {e}")
            total_fail += 1
            continue
        selected = records[:remaining_budget]
        remaining_budget -= len(selected)
        stats = build_inputs_from_records(selected, root)
        handled = handled_identities(stats)
        remaining = [record for record in records
                     if record_identity(record) not in handled]
        # 失败记录和本次限量后未处理的记录都留在原文件中。
        if stats.get("failed", 0) or remaining:
            write_news_file(path, remaining)
        if stats.get("failed", 0):
            print(f"    本次处理 {len(selected)} 条, 有 {stats['failed']} 条失败, "
                  "失败记录保留在“新闻数据”中, 下次可重试")
            total_retry += 1
            continue
        if remaining:
            print(f"    本次处理 {len(selected)} 条, 剩余 {len(remaining)} 条下次处理")
            total_pending += 1
            continue
        # 文件内所有记录都已生成或明确跳过后才归档。
        shutil.move(path, os.path.join(done_dir, fn))
        total_ok += 1

    print()
    print(f"文件处理完毕: {total_ok} 个文件已归档, {total_fail} 个解析失败, "
          f"{total_retry} 个待重试, {total_pending} 个还有未处理记录")
    print("下一步: 业务人员往 输入/ 各文件夹放入素材, 然后双击「双击生成.bat」")
    return 0 if total_fail == 0 and total_retry == 0 else 1


def build_inputs_from_records(records: list, root: str) -> dict:
    """把记录列表写成临时 json 后复用 make_inputs 的生成逻辑"""
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                     encoding="utf-8", dir=root) as f:
        json.dump(records, f, ensure_ascii=False)
        tmp = f.name
    try:
        return build_inputs(tmp, root)
    finally:
        os.remove(tmp)


if __name__ == "__main__":
    sys.exit(main())
