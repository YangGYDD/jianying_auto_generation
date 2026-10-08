# -*- coding: utf-8 -*-
"""模板管理入口：注册新模板或删除已有模板。"""
import json
import os
import shutil
import stat
import sys
import uuid

ENGINE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ENGINE_DIR)

import register_template  # noqa: E402
import template_registry as reg  # noqa: E402


ROOT = os.environ.get("TOOL_ROOT") or os.path.dirname(ENGINE_DIR)


class TemplateManagementError(RuntimeError):
    pass


def _configured_default_template(root: str) -> str:
    path = os.path.join(root, "引擎", "config.json")
    try:
        with open(path, "r", encoding="utf-8-sig") as handle:
            config = json.load(handle)
        return str(config.get("automation", {}).get("default_template", "")).strip()
    except (OSError, TypeError, ValueError):
        return ""


def protected_template_names(root: str) -> set:
    names = {reg.DEFAULT_TYPE}
    configured_default = _configured_default_template(root)
    if configured_default:
        names.add(configured_default)
    return names


def set_automation_template(root: str, name: str) -> str:
    name = str(name or "").strip()
    entry = reg.find_entry(reg.load_registry(root), name)
    if entry is None:
        raise TemplateManagementError(f"模板 [{name}] 不在模板清单中")
    if not reg.is_enabled(entry):
        raise TemplateManagementError(f"模板 [{name}] 已停用，不能用于自动化")
    if not os.path.isdir(reg.template_dir(root, name)):
        raise TemplateManagementError(f"模板 [{name}] 的目录不存在")

    path = os.path.join(root, "引擎", "config.json")
    with open(path, "r", encoding="utf-8-sig") as handle:
        config = json.load(handle)
    automation = config.setdefault("automation", {})
    previous = str(automation.get("default_template", "")).strip()
    automation["template_mode"] = "single"
    automation["default_template"] = name

    temp_path = path + f".{uuid.uuid4().hex}.tmp"
    try:
        with open(temp_path, "w", encoding="utf-8") as handle:
            json.dump(config, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temp_path, path)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)
    return previous


def _safe_template_path(root: str, name: str) -> str:
    library = os.path.abspath(reg.lib_dir(root))
    target = os.path.abspath(reg.template_dir(root, name))
    if os.path.dirname(target) != library:
        raise TemplateManagementError("模板名称对应的目录不安全，已拒绝删除")
    return target


def _remove_path(path: str) -> None:
    if os.path.isdir(path) and not os.path.islink(path):
        def remove_readonly(func, item, _exc_info):
            os.chmod(item, stat.S_IWRITE)
            func(item)

        shutil.rmtree(path, onerror=remove_readonly)
    elif os.path.lexists(path):
        os.remove(path)


def delete_template(root: str, name: str) -> dict:
    """删除一套非默认模板，并在清单写入失败时恢复模板目录。"""
    root = os.path.abspath(root)
    name = str(name or "").strip()
    registry = reg.load_registry(root)
    entry = reg.find_entry(registry, name)
    if entry is None:
        raise TemplateManagementError(f"模板 [{name}] 不在模板清单中")
    if name in protected_template_names(root):
        raise TemplateManagementError(f"模板 [{name}] 是系统默认模板，不能删除")
    if len(registry) <= 1:
        raise TemplateManagementError("模板库至少要保留一套模板")

    target = _safe_template_path(root, name)
    library = os.path.abspath(reg.lib_dir(root))
    os.makedirs(library, exist_ok=True)
    staging = ""
    if os.path.lexists(target):
        staging = os.path.join(library, f".template_delete_{uuid.uuid4().hex}")
        os.replace(target, staging)

    updated_registry = [item for item in registry if item.get("名字") != name]
    try:
        reg.save_registry(root, updated_registry)
    except Exception:
        if staging and os.path.lexists(staging) and not os.path.lexists(target):
            os.replace(staging, target)
        raise

    warning = ""
    if staging:
        try:
            _remove_path(staging)
        except Exception as exc:
            warning = f"模板已从清单删除，但临时目录清理失败: {exc}"
    return {
        "entry": dict(entry),
        "directory_existed": bool(staging),
        "warning": warning,
    }


def count_input_references(root: str, template_name: str) -> int:
    count = 0
    input_dir = os.path.join(root, "输入")
    if not os.path.isdir(input_dir):
        return 0
    for base, _dirs, files in os.walk(input_dir):
        if "模板.txt" not in files:
            continue
        try:
            with open(os.path.join(base, "模板.txt"), "r", encoding="utf-8-sig") as handle:
                if handle.read().strip() == template_name:
                    count += 1
        except OSError:
            continue
    return count


def choose_action() -> str:
    print("=" * 52)
    print("                  模板管理")
    print("=" * 52)
    print("  1. 注册新模板")
    print("  2. 删除已有模板")
    print("  3. 设置自动化模板")
    print("  0. 退出")
    while True:
        choice = input("请选择操作（直接回车退出）：").strip()
        if choice in ("", "0"):
            return "exit"
        if choice == "1":
            return "register"
        if choice == "2":
            return "delete"
        if choice == "3":
            return "configure"
        print("请输入 0、1、2 或 3。")


def configure_automation_template(root: str) -> int:
    registry = reg.enabled_entries(reg.load_registry(root))
    if not registry:
        print("没有可用于自动化的模板。")
        return 0

    current = _configured_default_template(root)
    print()
    print("请选择自动化固定使用的模板：")
    for index, entry in enumerate(registry, 1):
        marker = " [当前]" if entry["名字"] == current else ""
        print(f"  [{index}] {entry['名字']}{marker}")

    while True:
        choice = input("输入模板序号（直接回车取消）：").strip()
        if not choice:
            print("已取消设置。")
            return 0
        try:
            selected = registry[int(choice) - 1]["名字"]
        except (ValueError, IndexError):
            print(f"请输入 1 到 {len(registry)} 之间的模板序号。")
            continue
        break

    set_automation_template(root, selected)
    print(f"自动化模板已设置为 [{selected}]，下次运行生效。")
    return 0


def delete_interactive(root: str) -> int:
    registry = reg.load_registry(root)
    if not registry:
        print("模板库为空，没有可删除的模板。")
        return 0

    protected = protected_template_names(root)
    print()
    print("已有模板：")
    for index, entry in enumerate(registry, 1):
        name = entry.get("名字", "")
        status = []
        if name in protected:
            status.append("系统默认，不可删除")
        if not os.path.exists(_safe_template_path(root, name)):
            status.append("目录缺失")
        if not reg.is_enabled(entry):
            reason = str(entry.get("停用原因") or "模板体检未通过")
            status.append(f"已自动停用：{reason}")
        suffix = f" [{'；'.join(status)}]" if status else ""
        print(
            f"  [{index}] {name}（类型：{entry.get('类型') or reg.DEFAULT_TYPE}，"
            f"使用次数：{entry.get('使用次数', 0)}）{suffix}"
        )

    while True:
        choice = input("输入要删除的模板序号（直接回车取消）：").strip()
        if not choice:
            print("已取消删除。")
            return 0
        try:
            selected = registry[int(choice) - 1]
        except (ValueError, IndexError):
            print(f"请输入 1 到 {len(registry)} 之间的模板序号。")
            continue
        break

    name = selected["名字"]
    if name in protected:
        print(f"模板 [{name}] 是系统默认模板，不能删除。")
        return 0

    references = count_input_references(root, name)
    print()
    print(f"将删除模板 [{name}] 的模板文件和模板清单记录。")
    print("已经生成的剪映草稿不会被删除。")
    if references:
        print(f"注意：输入文件夹中有 {references} 条旧记录仍引用该模板，删除后不能用它们重新生成草稿。")
    confirm = input("此操作无法撤销；请输入 DELETE 确认删除：").strip()
    if confirm != "DELETE":
        print("确认文字不匹配，已取消删除。")
        return 0

    result = delete_template(root, name)
    if result["directory_existed"]:
        print(f"模板 [{name}] 已删除。")
    else:
        print(f"模板 [{name}] 的目录原本不存在，已清理模板清单记录。")
    if result["warning"]:
        print("警告：" + result["warning"])
    return 0


def main() -> int:
    try:
        action = choose_action()
        if action == "exit":
            print("已退出模板管理。")
            return 0
        if action == "register":
            register_template.ROOT = ROOT
            return register_template.main() or 0
        if action == "delete":
            return delete_interactive(ROOT)
        return configure_automation_template(ROOT)
    except (TemplateManagementError, OSError, ValueError) as exc:
        print(f"模板管理失败：{exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
