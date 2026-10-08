# -*- coding: utf-8 -*-
"""Windows 任务计划程序管理入口。"""
import argparse
import os
import subprocess
import sys

ENGINE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_ROOT = os.path.dirname(ENGINE_DIR)
TASK_NAME = "NewsVideoBatchAuto_OpenSource"


def _time_value(value):
    parts = str(value or "08:00").split(":")
    if len(parts) != 2:
        return "08:00"
    try:
        hour, minute = int(parts[0]), int(parts[1])
    except ValueError:
        return "08:00"
    return f"{hour:02d}:{minute:02d}" if 0 <= hour <= 23 and 0 <= minute <= 59 else "08:00"


def task_command(root):
    python = os.path.join(root, ".venv", "Scripts", "python.exe")
    if not os.path.isfile(python):
        python = os.path.join(root, "runtime", "python.exe")
    if not os.path.isfile(python):
        python = sys.executable
    automation = os.path.join(root, "引擎", "automation.py")
    return f'"{python}" "{automation}" --root "{root}"'


def _run(args):
    try:
        result = subprocess.run(args, capture_output=True, text=True, encoding="mbcs", errors="replace")
    except FileNotFoundError:
        return 1, "Windows 任务计划程序不可用"
    output = (result.stdout or "") + (result.stderr or "")
    return result.returncode, output.strip()


def install(root, start_time):
    code, output = _run([
        "schtasks", "/Create", "/SC", "DAILY", "/ST", _time_value(start_time),
        "/TN", TASK_NAME, "/TR", task_command(root), "/IT", "/F",
    ])
    if code:
        print("定时任务安装失败")
        if output:
            print(output)
        print("请确认当前 Windows 用户有创建任务计划的权限")
        return code
    print(f"已安装每天 {_time_value(start_time)} 自动执行任务")
    print("任务会使用当前 Windows 用户运行，电脑需保持开机、联网并保持该用户登录")
    return 0


def remove():
    code, output = _run(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"])
    if code:
        print("没有删除任务，可能该任务尚未安装")
        if output:
            print(output)
        return 0
    print("已取消每天自动执行任务")
    return 0


def query():
    code, output = _run(["schtasks", "/Query", "/TN", TASK_NAME, "/FO", "LIST"])
    if code:
        print("每天自动执行任务尚未安装")
        return 1
    print(output)
    return 0


def run_now():
    code, output = _run(["schtasks", "/Run", "/TN", TASK_NAME])
    if code:
        print("立即启动定时任务失败，请先安装任务")
        if output:
            print(output)
        return code
    print("已要求任务立即启动，请查看 报告/自动化报告_*.txt")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("install", "remove", "query", "run-now"))
    parser.add_argument("--root", default=DEFAULT_ROOT)
    parser.add_argument("--time", default="08:00")
    args = parser.parse_args()
    if args.action == "install":
        return install(os.path.abspath(args.root), args.time)
    if args.action == "remove":
        return remove()
    if args.action == "query":
        return query()
    return run_now()


if __name__ == "__main__":
    sys.exit(main())
