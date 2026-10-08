# -*- coding: utf-8 -*-
"""新闻视频自动化总入口。

流程: 读取钉钉多维表 -> 抓取公开网页 -> 豆包文案 -> 剪映草稿（当前关闭重复新闻跳过）。
单条失败会进入报告并由发布时间更早的新闻补位；不导出 MP4。
"""
import argparse
import datetime
import json
import msvcrt
import os
import re
import sys
import tempfile
import traceback

ENGINE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ENGINE_DIR)

from automation_state import AutomationState  # noqa: E402
from dingtalk_client import DingTalkClient, DingTalkError, normalize_records  # noqa: E402
from make_inputs import build_inputs, find_episode_by_key  # noqa: E402
from news_text import load_config  # noqa: E402
from pipeline import BatchRunner  # noqa: E402
import template_registry as reg  # noqa: E402
from web_news import fetch_news, news_key, normalize_url  # noqa: E402


class RunLock:
    def __init__(self, path):
        self.path = path
        self.handle = None

    def __enter__(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self.handle = open(self.path, "a+b")
        self.handle.seek(0)
        if os.path.getsize(self.path) == 0:
            self.handle.write(b"0")
            self.handle.flush()
        try:
            self.handle.seek(0)
            msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            self.handle.close()
            self.handle = None
            raise RuntimeError("已有另一个自动化任务正在运行, 本次跳过")
        return self

    def __exit__(self, exc_type, exc, tb):
        if self.handle:
            try:
                self.handle.seek(0)
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
            finally:
                self.handle.close()


def _short_error(exc):
    value = str(exc).replace("\r", " ").replace("\n", " ").strip()
    return value[:500] or exc.__class__.__name__


def _report(root, run_mode, entries, meta, count_overrides=None):
    report_dir = os.path.join(root, "报告")
    os.makedirs(report_dir, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(report_dir, f"自动化报告_{stamp}.txt")
    counts = {}
    for entry in entries:
        counts[entry["status"]] = counts.get(entry["status"], 0) + 1
    counts.update(count_overrides or {})
    labels = {
        "success": "成功",
        "category_filtered": "新闻分类跳过",
        "invalid_date": "发布时间无效跳过",
        "duplicate": "重复跳过",
        "fetch_failed": "网页抓取失败",
        "input_failed": "文案生成失败",
        "draft_failed": "剪映草稿失败",
        "pending": "待处理",
    }
    with open(path, "w", encoding="utf-8-sig") as f:
        f.write("新闻视频自动化运行报告\n")
        f.write(f"运行时间: {datetime.datetime.now():%Y-%m-%d %H:%M:%S}\n")
        f.write(f"运行方式: {run_mode}\n")
        f.write("=" * 58 + "\n")
        for key in ("success", "category_filtered", "invalid_date", "duplicate", "fetch_failed",
                    "input_failed", "draft_failed", "pending"):
            f.write(f"{labels[key]}: {counts.get(key, 0)}\n")
        if meta:
            f.write("\n运行说明:\n")
            for item in meta:
                f.write(f"- {item}\n")
        f.write("\n逐条结果:\n")
        for entry in entries:
            f.write(f"\n[{labels.get(entry['status'], entry['status'])}] {entry.get('title') or '(无标题)'}\n")
            if entry.get("url"):
                f.write(f"原文: {entry['url']}\n")
            if entry.get("template"):
                f.write(f"使用模板: {entry['template']}\n")
            if entry.get("source_category"):
                f.write(f"钉钉新闻分类: {entry['source_category']}\n")
            if entry.get("content_category"):
                f.write(f"内容分类/素材库: {entry['content_category']}\n")
            if entry.get("error"):
                f.write(f"原因: {entry['error']}\n")
            if entry.get("draft_folder"):
                f.write(f"剪映草稿: {entry['draft_folder']}\n")
            if entry.get("details"):
                f.write("处理明细:\n")
                for detail in entry["details"]:
                    f.write(f"  - {detail}\n")
    return path, counts


def _record_entry(record, status, error="", draft_folder="", template_name="", details=None):
    return {
        "status": status,
        "title": record.get("title", ""),
        "url": record.get("link", ""),
        "error": error,
        "draft_folder": draft_folder,
        "template": template_name,
        "source_category": record.get("news_category", ""),
        "content_category": record.get("content_category", ""),
        "key": record.get("_dedupe_key", ""),
        "details": list(details or []),
    }


def _make_input_file(root, records):
    handle = tempfile.NamedTemporaryFile(
        "w", suffix=".json", delete=False, encoding="utf-8", dir=root
    )
    try:
        json.dump(records, handle, ensure_ascii=False)
    finally:
        handle.close()
    return handle.name


def _publish_time_value(value):
    """把钉钉日期字段统一成可降序比较的时间值。"""
    if isinstance(value, datetime.datetime):
        try:
            return value.timestamp()
        except (ValueError, OSError):
            return None
    if isinstance(value, datetime.date):
        try:
            return datetime.datetime.combine(value, datetime.time()).timestamp()
        except (ValueError, OSError):
            return None
    text = str(value or "").strip()
    if not text:
        return None
    numeric_text = re.fullmatch(r"(\d+)(?:\.0+)?", text)
    if numeric_text:
        digits_text = numeric_text.group(1)
        number = int(digits_text)
        if len(digits_text) >= 13:
            return number / 1000.0
        if len(digits_text) == 10:
            return float(number)
        if len(digits_text) == 8 and 19000000 <= number <= 29991231:
            try:
                return datetime.datetime.strptime(digits_text, "%Y%m%d").timestamp()
            except (ValueError, OSError):
                return None
    date_text = (text.replace("年", "-").replace("月", "-")
                 .replace("日", "").replace("/", "-"))
    for candidate in (date_text.replace("Z", "+00:00"), date_text[:10]):
        try:
            parsed = datetime.datetime.fromisoformat(candidate)
            return parsed.timestamp()
        except (ValueError, OSError):
            continue
    digits = re.sub(r"\D", "", text)
    if digits:
        number = int(digits)
        if len(digits) == 8 and 19000000 <= number <= 29991231:
            try:
                return datetime.datetime.strptime(digits, "%Y%m%d").timestamp()
            except (ValueError, OSError):
                pass
    return None


def partition_by_publish_time(records):
    """返回按发布时间降序的有效记录，以及发布时间无效的记录。"""
    valid = []
    invalid = []
    for index, record in enumerate(records):
        value = _publish_time_value(record.get("date"))
        if value is None:
            invalid.append(record)
        else:
            valid.append((value, index, record))
    valid.sort(key=lambda item: (-item[0], item[1]))
    return [record for _, _, record in valid], invalid


def _record_news_categories(record):
    values = record.get("news_categories")
    if not isinstance(values, (list, tuple, set)):
        values = [values] if values else []
    if not values and record.get("news_category"):
        values = re.split(r"[,，;；|、\r\n]+", str(record["news_category"]))
    cleaned = [str(value).strip() for value in values if str(value).strip()]
    return list(dict.fromkeys(cleaned))


def partition_by_news_category(records, allowed_categories):
    """按钉钉新闻分类精确筛选，兼容单选和多选记录。"""
    allowed = {str(value).strip() for value in allowed_categories if str(value).strip()}
    matched = []
    skipped = []
    for record in records:
        categories = _record_news_categories(record)
        if allowed.intersection(categories):
            matched.append(record)
        else:
            skipped.append(record)
    return matched, skipped


def sort_by_publish_time(records):
    """按发布时间从新到旧排序，并跳过发布时间无效的记录。"""
    valid, _ = partition_by_publish_time(records)
    return valid


def _validate_template(root, template_name):
    registry = reg.load_registry(root)
    enabled = reg.enabled_entries(registry)
    if not enabled:
        raise RuntimeError("没有可用模板, 请查看自动化报告中的模板停用原因")
    name = str(template_name or "").strip()
    entry = reg.find_entry(registry, name)
    if entry is None:
        available = "、".join(item["名字"] for item in enabled)
        raise ValueError(f"模板 [{name}] 不存在, 可用模板: {available}")
    if not reg.is_enabled(entry):
        reason = entry.get("停用原因") or "模板体检未通过"
        raise ValueError(f"模板 [{name}] 已停用: {reason}")
    return name


def _resolve_template(root, requested_template):
    """指定模板不可用时自动改用健康的默认模板。"""
    try:
        return _validate_template(root, requested_template), ""
    except (RuntimeError, ValueError) as exc:
        registry = reg.load_registry(root)
        fallback = reg.fallback_template(registry)
        note = f"模板 [{requested_template}] 不可用，已自动改用 [{fallback}]：{_short_error(exc)}"
        return fallback, note


def choose_template(root, default_template):
    """手动运行时按编号选择本次整批统一使用的模板。"""
    registry = reg.enabled_entries(reg.load_registry(root))
    if not registry:
        raise RuntimeError("没有可用模板, 请查看模板停用原因")
    try:
        default_template = _validate_template(root, default_template)
    except (RuntimeError, ValueError):
        default_template = reg.fallback_template(registry)
    default_index = next(
        index for index, entry in enumerate(registry, 1)
        if entry["名字"] == default_template
    )
    print()
    print("请选择本次所有新闻统一使用的模板：")
    for index, entry in enumerate(registry, 1):
        marker = "（默认）" if entry["名字"] == default_template else ""
        print(f"  {index}. {entry['名字']}（素材类型：{entry.get('类型') or reg.DEFAULT_TYPE}）{marker}")
    while True:
        try:
            value = input(f"请输入模板编号（直接回车使用 {default_index}. {default_template}）：").strip()
        except EOFError:
            value = ""
        if not value:
            return default_template
        if value.isdigit() and 1 <= int(value) <= len(registry):
            return registry[int(value) - 1]["名字"]
        print(f"请输入 1 到 {len(registry)} 之间的模板编号。")


def choose_template_mode():
    """手动运行时选择整批统一模板或随机混用模板。"""
    print()
    print("请选择本次模板使用方式：")
    print("  1. 全部新闻统一使用一个模板（默认）")
    print("  2. 在全部模板中随机混用")
    while True:
        try:
            value = input("请输入方式编号（直接回车选择 1）：").strip()
        except EOFError:
            value = ""
        if value in ("", "1"):
            return "single"
        if value == "2":
            return "random"
        print("请输入 1 或 2。")


def run(root, run_mode="手动", max_news_override=None, template_mode_override=None,
        template_override=None, interactive=False):
    root = os.path.abspath(root)
    lock_path = os.path.join(root, "报告", "自动化运行.lock")
    try:
        lock = RunLock(lock_path)
        lock.__enter__()
    except RuntimeError as exc:
        print(str(exc))
        return 1

    state = None
    runner = None
    entries = []
    meta = []
    report_count_overrides = {}
    try:
        try:
            cfg = load_config()
            table_cfg = cfg.get("dingtalk_news_table", {})
            auto_cfg = cfg.get("automation", {})
            timeout = int(auto_cfg.get("request_timeout_seconds", 30))
            configured_max = int(auto_cfg.get("max_news_per_run", 5))
            max_news = (max_news_override if max_news_override is not None
                        else configured_max)
            if not 1 <= max_news <= 100:
                raise ValueError("目标草稿数量必须是 1 到 100 之间的整数")
            max_chars = int(auto_cfg.get("max_article_chars", 8000))
            skip_duplicate_news = bool(auto_cfg.get("skip_duplicate_news", True))
            allowed_categories = auto_cfg.get("allowed_news_categories", ["电池行业新闻"])
            if isinstance(allowed_categories, str):
                allowed_categories = [allowed_categories]
            allowed_categories = [
                str(value).strip() for value in allowed_categories if str(value).strip()
            ]
            if not allowed_categories:
                raise ValueError("至少需要配置一个允许处理的钉钉新闻分类")
            configured_mode = str(auto_cfg.get("template_mode", "single")).strip().lower()
            template_mode = (str(template_mode_override).strip().lower()
                             if template_mode_override is not None else configured_mode)
            if template_mode not in ("single", "random"):
                raise ValueError("模板使用方式必须是 single 或 random")

            # 文案生成前先完成模板体检，避免按坏模板版式调用模型。
            runner = BatchRunner(root)
            health = getattr(runner, "template_health", {}) or {}
            for item in health.get("repaired", []):
                groups = "、".join(item.get("groups", []))
                meta.append(f"模板 [{item.get('name')}] 已自动修复: {groups}")
            for item in health.get("disabled", []):
                meta.append(
                    f"模板 [{item.get('name')}] 已自动停用并排除: {item.get('reason')}"
                )

            configured_template = auto_cfg.get("default_template", reg.DEFAULT_TYPE)
            selected_template = None
            if template_mode == "single":
                requested_template = (
                    template_override if template_override is not None else configured_template
                )
                if interactive and template_override is None:
                    selected_template = choose_template(root, configured_template)
                    fallback_note = ""
                else:
                    selected_template, fallback_note = _resolve_template(root, requested_template)
                if fallback_note:
                    meta.append(fallback_note)
                    print(fallback_note)
                meta.append(f"模板方式: 全部新闻统一使用 [{selected_template}]")
                print(f"本次统一使用模板: {selected_template}")
            else:
                if template_override is not None:
                    raise ValueError("随机混用模板时不能同时指定统一模板")
                registry = reg.enabled_entries(reg.load_registry(root))
                if not registry:
                    raise RuntimeError("模板体检后没有可用模板")
                meta.append(f"模板方式: 在 {len(registry)} 套健康模板中随机混用")
                print(f"本次将在 {len(registry)} 套健康模板中随机混用")
            if not skip_duplicate_news:
                meta.append("重复新闻跳过已关闭，本次允许重新生成")
            state = AutomationState(root)
            client = DingTalkClient(table_cfg, timeout=timeout)
            field_ids = list((table_cfg.get("字段") or {}).values())
            # 为了按发布时间排序，必须先读完整张表；用大分页避免数量较小时触发钉钉 QPS 限制。
            raw_records = client.list_records(max_results=100, field_ids=field_ids)
            all_records = normalize_records(raw_records, table_cfg.get("字段", {}))
            category_records, category_skipped_records = partition_by_news_category(
                all_records, allowed_categories
            )
            records, invalid_date_records = partition_by_publish_time(category_records)
            total_records = len(all_records)
            empty_category_count = sum(
                1 for record in category_skipped_records if not _record_news_categories(record)
            )
            other_category_count = len(category_skipped_records) - empty_category_count
            report_count_overrides["category_filtered"] = len(category_skipped_records)
            for record in invalid_date_records:
                entries.append(_record_entry(
                    record, "invalid_date", "发布时间为空或无法识别"
                ))
            meta.append(f"目标: 成功创建 {max_news} 个剪映草稿")
            meta.append(f"钉钉新闻分类筛选: {'、'.join(allowed_categories)}")
            meta.append(
                f"钉钉读取到 {total_records} 条记录，分类符合 {len(category_records)} 条，"
                f"分类为空跳过 {empty_category_count} 条，其他分类跳过 {other_category_count} 条"
            )
            meta.append(
                f"符合分类的记录中，发布时间有效 {len(records)} 条，"
                f"发布时间无效跳过 {len(invalid_date_records)} 条"
            )
        except DingTalkError as exc:
            msg = _short_error(exc)
            meta.append(f"钉钉读取失败 [{exc.code}]: {msg}")
            path, counts = _report(root, run_mode, [], meta)
            print(f"钉钉读取失败: {msg}")
            print(f"报告已保存: {path}")
            return 2
        except Exception as exc:
            meta.append("自动化启动检查失败: " + _short_error(exc))
            path, counts = _report(root, run_mode, [], meta)
            print(f"启动失败: {_short_error(exc)}")
            print(f"报告已保存: {path}")
            return 2

        if not category_records:
            meta.append("没有符合钉钉新闻分类筛选条件的记录")
        elif not records:
            meta.append("没有发布时间有效的新闻可供处理")

        success_count = 0
        next_record_index = 0
        seen_keys = set()
        engine_start_error = ""
        template_retry_queue = []
        template_retry_count = 0

        while success_count < max_news and (
                next_record_index < len(records) or template_retry_queue):
            needed = max_news - success_count
            prepared = []
            while template_retry_queue and len(prepared) < needed:
                prepared.append(template_retry_queue.pop(0))
            while len(prepared) < needed and next_record_index < len(records):
                index = next_record_index + 1
                raw = dict(records[next_record_index])
                next_record_index += 1
                table_title = (raw.get("title") or "").strip()
                url = normalize_url(raw.get("link"))
                raw["link"] = url
                if not url:
                    record = dict(raw)
                    hint_key = news_key("", table_title)
                    record["_dedupe_key"] = hint_key
                    error = "缺少有效新闻链接"
                    state.mark(hint_key, record, "fetch_failed", error=error)
                    entries.append(_record_entry(record, "fetch_failed", error))
                    print(f"[{index}/{len(records)}] 网页抓取失败: {table_title[:32] or '(无标题)'}")
                    continue
                hint_key = news_key(url, table_title)
                previous_hint = state.get(hint_key) if skip_duplicate_news and table_title else None
                if previous_hint and previous_hint.get("status") == "success":
                    raw["_dedupe_key"] = hint_key
                    entries.append(_record_entry(raw, "duplicate", "本地记录已成功生成过"))
                    print(f"[{index}/{len(records)}] 重复跳过: {table_title[:32] or url[:32]}")
                    continue
                try:
                    fetched = fetch_news(url, timeout=timeout, max_chars=max_chars)
                    title = table_title or fetched["title"]
                    if not title:
                        raise ValueError("表格和网页都没有标题")
                    key = news_key(url, title)
                    record = dict(raw)
                    record.update({
                        "title": title,
                        "source": raw.get("source") or fetched.get("source", ""),
                        "date": raw.get("date") or fetched.get("date", ""),
                        "summary": (raw.get("summary") or "").strip(),
                        "type": (raw.get("type") or "").strip(),
                        "link": url,
                        "_dedupe_key": key,
                    })
                    if record["summary"]:
                        record["summary"] += "\n\n网页正文:\n" + fetched["summary"]
                    else:
                        record["summary"] = fetched["summary"]
                    if skip_duplicate_news and key in seen_keys:
                        entries.append(_record_entry(record, "duplicate", "本次钉钉记录中重复"))
                        print(f"[{index}/{len(records)}] 重复跳过: {title[:32]}")
                        continue
                    previous = state.get(key)
                    if skip_duplicate_news and previous and previous.get("status") == "success":
                        entries.append(_record_entry(record, "duplicate", "本地记录已成功生成过"))
                        print(f"[{index}/{len(records)}] 重复跳过: {title[:32]}")
                        continue
                    seen_keys.add(key)
                    state.mark(key, record, "pending")
                    prepared.append(record)
                    print(f"[{index}/{len(records)}] 网页抓取成功: {title[:32]}")
                except Exception as exc:
                    record = dict(raw)
                    record["_dedupe_key"] = hint_key
                    error = _short_error(exc)
                    state.mark(hint_key, record, "fetch_failed", error=error)
                    entries.append(_record_entry(record, "fetch_failed", error))
                    print(f"[{index}/{len(records)}] 网页抓取失败: {table_title[:32] or url[:32]}")

            if not prepared:
                continue

            input_file = _make_input_file(root, prepared)
            try:
                try:
                    input_result = build_inputs(
                        input_file, root,
                        allow_existing=(not skip_duplicate_news or any(
                            record.get("_template_retry_count") for record in prepared
                        )),
                        template_override=selected_template,
                        random_templates=(template_mode == "random"),
                    )
                except Exception as exc:
                    for record in prepared:
                        error = _short_error(exc)
                        state.mark(record["_dedupe_key"], record, "input_failed", error=error)
                        entries.append(_record_entry(record, "input_failed", error))
                    input_result = {"generated_items": [], "failed_items": []}
                generated = list(input_result.get("generated_items", []))
                for item in input_result.get("failed_items", []):
                    record = item["record"]
                    error = item.get("error", "文案生成失败")
                    state.mark(record["_dedupe_key"], record, "input_failed", error=error)
                    entries.append(_record_entry(
                        record, "input_failed", error,
                        template_name=item.get("template", ""),
                    ))
                # 崩溃后已经写入输入目录但状态尚未更新时，利用新闻指纹继续补做剪映草稿。
                for item in input_result.get("skipped_items", []):
                    record = item.get("record", {})
                    reason = item.get("reason", "文案未生成")
                    recover_existing = skip_duplicate_news and reason in ("已生成过", "文件夹已存在")
                    folder = ""
                    if recover_existing:
                        folder = item.get("folder") or find_episode_by_key(
                            os.path.join(root, "输入"), record.get("_dedupe_key", "")
                        )
                    if folder and record.get("_dedupe_key") and state.get(record["_dedupe_key"]):
                        generated.append({
                            "record": record,
                            "folder": folder,
                            "folder_name": os.path.basename(folder),
                            "template": item.get("template", ""),
                        })
                    elif record.get("_dedupe_key"):
                        state.mark(record["_dedupe_key"], record, "input_failed", error=reason)
                        entries.append(_record_entry(
                            record, "input_failed", reason,
                            template_name=item.get("template", ""),
                        ))
            finally:
                try:
                    os.remove(input_file)
                except OSError:
                    pass

            if not generated:
                continue

            if runner is None:
                try:
                    runner = BatchRunner(root)
                except Exception as exc:
                    engine_start_error = _short_error(exc)
                    for item in generated:
                        record = item["record"]
                        state.mark(record["_dedupe_key"], record, "draft_failed",
                                   error=engine_start_error, input_folder=item["folder"])
                        entries.append(_record_entry(
                            record, "draft_failed", engine_start_error,
                            template_name=item.get("template", ""),
                        ))
                    meta.append("剪映生成引擎无法启动，已停止后续文案调用: " + engine_start_error)
                    break

            failed_for_template_retry = []
            try:
                for item in generated:
                    state.mark(item["record"]["_dedupe_key"], item["record"], "pending",
                               input_folder=item["folder"])
                runner.run([item["folder"] for item in generated])
                result_by_name = {name: (status, warns) for name, status, warns in runner.last_results}
                for item in generated:
                    record = item["record"]
                    name = item["folder_name"]
                    status, warns = result_by_name.get(name, ("失败: 未返回结果", []))
                    if status == "成功":
                        draft_folder = os.path.join(runner.drafts_dir, name)
                        state.mark(record["_dedupe_key"], record, "success",
                                   input_folder=item["folder"], draft_folder=draft_folder)
                        entries.append(_record_entry(
                            record, "success", draft_folder=draft_folder,
                            template_name=item.get("template", ""),
                            details=warns,
                        ))
                        success_count += 1
                    else:
                        error = status.removeprefix("失败: ")
                        state.mark(record["_dedupe_key"], record, "draft_failed",
                                   error=error, input_folder=item["folder"])
                        entries.append(_record_entry(
                            record, "draft_failed", error,
                            template_name=item.get("template", ""),
                            details=warns,
                        ))
                        failed_for_template_retry.append(item)
            except Exception as exc:
                error = _short_error(exc)
                for item in generated:
                    record = item["record"]
                    state.mark(record["_dedupe_key"], record, "draft_failed",
                               error=error, input_folder=item["folder"])
                    entries.append(_record_entry(
                        record, "draft_failed", error,
                        template_name=item.get("template", ""),
                    ))

            # 极少数模板可能在写草稿后的反向核验阶段才暴露问题。
            # 统一模式在下一轮自动切换模板；随机模式下一轮会自动排除它。
            if template_mode == "single" and selected_template:
                latest_registry = reg.load_registry(root)
                selected_entry = reg.find_entry(latest_registry, selected_template)
                if selected_entry is not None and not reg.is_enabled(selected_entry):
                    previous_template = selected_template
                    try:
                        selected_template = reg.fallback_template(latest_registry)
                        note = (
                            f"模板 [{previous_template}] 生成后核验失败并已停用，"
                            f"后续新闻自动改用 [{selected_template}]"
                        )
                    except RuntimeError:
                        selected_template = None
                        note = f"模板 [{previous_template}] 已停用，当前没有其他健康模板可用"
                    meta.append(note)
                    print(note)

            latest_registry = reg.load_registry(root)
            healthy_templates = reg.enabled_entries(latest_registry)
            for item in failed_for_template_retry:
                failed_template = reg.find_entry(latest_registry, item.get("template", ""))
                if failed_template is None or reg.is_enabled(failed_template) or not healthy_templates:
                    continue
                record = dict(item["record"])
                retry_count = int(record.get("_template_retry_count", 0)) + 1
                if retry_count >= len(latest_registry):
                    continue
                record["_template_retry_count"] = retry_count
                template_retry_queue.append(record)
                template_retry_count += 1
                print(
                    f"模板 [{item.get('template')}] 已停用，新闻 [{record.get('title', '')[:24]}] "
                    "将在健康模板中重新生成"
                )

        meta.append(f"共按发布时间从新到旧尝试 {next_record_index} 条有效新闻")
        if template_retry_count:
            meta.append(f"因模板停用自动重新分配 {template_retry_count} 条次新闻")
        if success_count >= max_news:
            meta.append(f"已达到目标: 成功创建 {success_count} 个剪映草稿")
        elif not engine_start_error:
            meta.append(
                f"有效新闻已全部尝试，未达到目标: 目标 {max_news} 个，"
                f"实际成功 {success_count} 个"
            )

        path, counts = _report(root, run_mode, entries, meta, report_count_overrides)
        if success_count >= max_news:
            print(f"自动化处理完成: 已成功创建 {success_count} 个剪映草稿")
            print(f"报告已保存: {path}")
            return 0
        print(f"自动化处理未达到目标: 目标 {max_news} 个, 实际成功 {success_count} 个")
        print(f"报告已保存: {path}")
        return 1
    except Exception as exc:
        error = _short_error(exc)
        meta.append("未预期错误: " + error)
        traceback.print_exc()
        path, counts = _report(root, run_mode, entries, meta, report_count_overrides)
        print(f"自动化运行失败: {error}")
        print(f"报告已保存: {path}")
        return 2
    finally:
        if state:
            state.close()
        lock.__exit__(None, None, None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=os.path.dirname(ENGINE_DIR))
    parser.add_argument("--manual", action="store_true", help="标记为业务人员手动运行")
    parser.add_argument("--count", type=int, default=None,
                        help="本次要成功创建的剪映草稿数量 (1-100; 不填使用配置默认值)")
    parser.add_argument("--template", default=None,
                        help="统一模板模式使用的模板名")
    parser.add_argument("--template-mode", choices=("single", "random"), default=None,
                        help="模板方式: single=统一模板, random=随机混用")
    args = parser.parse_args()
    if args.count is not None and not 1 <= args.count <= 100:
        parser.error("--count 目标草稿数量必须是 1 到 100 之间的整数")
    print("=" * 58)
    print("        新闻视频自动化生成")
    print("=" * 58)
    selected_template = args.template
    template_mode = args.template_mode
    if template_mode == "random" and selected_template is not None:
        parser.error("--template-mode random 不能与 --template 同时使用")
    if args.manual and template_mode is None:
        template_mode = "single" if selected_template is not None else choose_template_mode()
    return run(
        args.root,
        "手动" if args.manual else "每天08:00定时",
        args.count,
        template_mode,
        selected_template,
        interactive=args.manual,
    )


if __name__ == "__main__":
    sys.exit(main())
