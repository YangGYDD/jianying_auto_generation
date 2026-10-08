"""Allowlist and content checks for the distributable source tree (stdlib only)."""
from __future__ import annotations

import argparse
import json
import re
import stat
import subprocess
import tarfile
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
MAX_FILE_BYTES = 2 * 1024 * 1024
TOP_FILES = {
    "README.md", "LICENSE", "THIRD_PARTY_NOTICES.md", "CONTRIBUTING.md",
    "SECURITY.md", ".gitignore", "requirements.txt", "运行环境.bat",
    "输入文字生成草稿.bat", "模板管理.bat", "立即执行自动化.bat", "生产文案.bat",
    "安装每日8点任务.bat", "取消每日8点任务.bat", "查看自动任务.bat", "立即运行已安装任务.bat",
}
EXTENSIONS = {
    "引擎": {".py", ".json"}, "tools": {".py"}, "docs": {".md", ".json"},
    "licenses": {".txt"}, "examples": {".json", ".txt"}, ".github": {".yml", ".yaml"},
}

IGNORED_PARTS = {"__pycache__", ".pytest_cache"}
FORBIDDEN_NAMES = {"config.json", "config.local.json", ".env", "credentials.json", "token.json"}
SENSITIVE_KEYS = re.compile(
    r"^(?:api[_-]?key|access[_-]?token|refresh[_-]?token|app[_-]?secret|client[_-]?secret|"
    r"password|secret|token|app[_-]?key|client[_-]?id|corp[_-]?id|operator[_-]?id|"
    r"user[_-]?id|union[_-]?id|base[_-]?id|sheet[_-]?id|table[_-]?id|open[_-]?conversation[_-]?id)$", re.I)
ASSIGNMENT = re.compile(
    r'''["']?\b(api_key|access_token|refresh_token|app_secret|client_secret|password|secret|token|app_key|client_id|corp_id|operator_id|user_id|union_id)["']?\s*[:=]\s*["']([^"'\r\n]*)["']''', re.I)
TOKEN_PATTERNS = (
    ("private key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("service token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{25,}|github_pat_[A-Za-z0-9_]{30,}|sk-[A-Za-z0-9_-]{24,})\b")),
    ("credential URL", re.compile(r"https?://[^\s/:]+:[^\s/@]+@", re.I)),
    ("personal absolute path", re.compile(r"(?:[A-Za-z]:[/\\]+Users[/\\]+(?!Public\b|Example\b|<)[^/\\\s\"']+|/(?:home|Users)/[^/\s\"']+)", re.I)),
    ("signed URL", re.compile(r"[?&](?:access_token|api_key|signature|sign)=[A-Za-z0-9%_+/-]{12,}", re.I)),
)


class PublicSafetyError(ValueError):
    """Candidate content cannot be distributed safely by this checker."""


def placeholder(value: str) -> bool:
    """Only explicit invented examples are exempt; arbitrary short values are not."""
    lowered = value.lower()
    return not value or lowered in {"dummy", "example", "test", "redacted", "placeholder"} or lowered.startswith(("dummy-", "test-", "example-", "fake-", "<", "${"))


def allowed_name(name: str) -> bool:
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or "\\" in name or ":" in name:
        return False
    if any(part.lower() in FORBIDDEN_NAMES for part in path.parts):
        return False
    if name == "引擎/pyJianYingDraft/LICENSE":
        return True
    if name in TOP_FILES:
        return True
    if path.parts and path.parts[0] == "src":
        if len(path.parts) < 3 or path.parts[1] != "news_video_batch":
            return False
        if path.suffix == ".txt" and path.name != "ASSETS.txt":
            return False
    return len(path.parts) > 1 and path.parts[0] in EXTENSIONS and path.suffix in EXTENSIONS[path.parts[0]]


def is_link(path: Path) -> bool:
    # Path.is_junction was added in Python 3.12; st_file_attributes covers 3.11 too.
    return path.is_symlink() or bool(getattr(path.lstat(), "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def scan_content(name: str, data: bytes) -> list[str]:
    errors = []
    if len(data) > MAX_FILE_BYTES:
        return [f"{name}: exceeds the 2 MiB source-file limit"]
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return [f"{name}: binary or non-UTF-8 content is excluded"]
    if "\x00" in text:
        errors.append(f"{name}: binary content is excluded")
    for reason, pattern in TOKEN_PATTERNS:
        if pattern.search(text):
            errors.append(f"{name}: possible {reason} (value withheld)")
    for match in ASSIGNMENT.finditer(text):
        if not placeholder(match.group(2)):
            errors.append(f"{name}: nonblank credential/account literal in {match.group(1)} (value withheld)")
    if name.endswith(".json"):
        try:
            obj = json.loads(text)
        except json.JSONDecodeError:
            errors.append(f"{name}: invalid JSON")
        else:
            def walk(value):
                if isinstance(value, dict):
                    for key, item in value.items():
                        sensitive = SENSITIVE_KEYS.match(key) or (key == "model" and name.endswith("config.example.json"))
                        if sensitive and item is not None and item != "":
                            if name.endswith("config.example.json") or not (isinstance(item, str) and placeholder(item)):
                                errors.append(f"{name}: nonblank sensitive JSON field {key} (value withheld)")
                        walk(item)
                elif isinstance(value, list):
                    for item in value:
                        walk(item)
            walk(obj)
    if name.endswith(".svg") and re.search(r"<(?:script|foreignObject)\b|(?:href\s*=\s*[\"'](?:https?:|//|file:))|\bon\w+\s*=", text, re.I):
        errors.append(f"{name}: active or externally referenced SVG is excluded")
    return list(dict.fromkeys(errors))


def collect_public(root: Path) -> dict[str, bytes]:
    root = root.resolve()
    collected = {}
    errors = []
    for name in sorted(TOP_FILES | EXTENSIONS.keys()):
        candidate = root / name
        if not candidate.exists() and not candidate.is_symlink():
            continue
        paths = [candidate] if not candidate.is_dir() or is_link(candidate) else candidate.rglob("*")
        for path in paths:
            relative = path.relative_to(root).as_posix()
            if any(part in IGNORED_PARTS or part.endswith(".egg-info") for part in path.relative_to(root).parts):
                continue
            if is_link(path) or not path.resolve().is_relative_to(root):
                errors.append(f"{relative}: links/junctions are excluded")
                continue
            if path.is_dir():
                continue
            if not path.is_file() or not allowed_name(relative):
                errors.append(f"{relative}: file is not on the public allowlist")
                continue
            if path.stat().st_size > MAX_FILE_BYTES:
                errors.append(f"{relative}: exceeds the 2 MiB source-file limit")
                continue
            data = path.read_bytes()
            errors.extend(scan_content(relative, data))
            collected[relative] = data
    if not collected:
        errors.append("No public source files found")
    if errors:
        raise PublicSafetyError("\n".join(errors))
    return dict(sorted(collected.items()))


def check_tracked(root: Path, public: dict[str, bytes]) -> None:
    """Prevent git from publishing extra files outside the packaging allowlist."""
    result = subprocess.run(["git", "ls-files", "-z"], cwd=root, capture_output=True, check=False)
    if result.returncode != 0:
        raise PublicSafetyError("Git tracked-file check requires an initialized repository")
    names = result.stdout.decode("utf-8").split("\0")
    bad = [name for name in names if name and name not in public]
    if bad:
        raise PublicSafetyError("Tracked files outside public allowlist: " + ", ".join(bad))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--tracked", action="store_true", help="also reject tracked files outside the public allowlist")
    args = parser.parse_args(argv)
    try:
        files = collect_public(args.root)
        if args.tracked:
            check_tracked(args.root, files)
    except (OSError, PublicSafetyError) as exc:
        print(f"PUBLIC CHECK FAILED: {exc}")
        return 1
    print(f"PUBLIC CHECK PASSED: {len(files)} UTF-8 source/example files; no excluded files selected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
