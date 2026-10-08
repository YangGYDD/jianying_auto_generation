"""Small explicit CLI: local/offline/demo are the defaults."""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import sys
from importlib.resources import files
from pathlib import Path

from . import __version__
from .domain import ValidationError, load_news, load_template


def _data_path(name: str) -> Path:
    return Path(str(files("news_video_batch").joinpath("data", name)))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="News to per-segment drafts; offline by default")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    doctor = commands.add_parser("doctor", help="Check local prerequisites without network requests")
    init = commands.add_parser("init", help="Copy original example inputs into a new local directory")
    init.add_argument("--directory", type=Path, required=True)
    demo = commands.add_parser("demo", help="Run the included fictional news through the offline pipeline")
    demo.add_argument("--output", type=Path, default=Path("outputs/demo"))
    run = commands.add_parser("run", help="Generate a batch with explicitly selected adapters")
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--export", choices=("demo", "jianying"), default="demo")
    run.add_argument("--jianying-template", type=Path)
    verify = commands.add_parser("verify", help="Verify saved batch files against their SHA256 manifest")
    verify.add_argument("directory", type=Path)
    for command in (doctor, run):
        command.add_argument("--config", type=Path)
        command.add_argument("--source", choices=("local", "dingtalk"), default="local")
        command.add_argument("--model", choices=("offline", "doubao"), default="offline")
        command.add_argument("--news", type=Path, default=_data_path("news.json"))
        command.add_argument("--template", type=Path, default=_data_path("template.json"))
    return parser


def main(argv: list[str] | None = None) -> int:
    from .config import load_config, validate_connection_config
    from .pipeline import run_batch, verify_batch
    from .providers import DingTalkNewsSource, DoubaoModel, LocalNewsSource, OfflineModel

    args = _parser().parse_args(argv)
    try:
        if args.command == "init":
            from .pipeline import _check_new_destination

            destination = _check_new_destination(args.directory)
            destination.mkdir(parents=True)
            for name in ("news.json", "template.json", "config.example.json", "background.svg", "ASSETS.txt"):
                shutil.copyfile(_data_path(name), destination / name)
            print("Example files copied. Rename config.example.json to config.local.json only for online use.")
            return 0
        if args.command == "verify":
            manifest = verify_batch(args.directory)
            print(f"PASS: {len(manifest['sha256'])} saved files match the batch manifest. No GUI or factual review implied.")
            return 0
        if args.command == "demo":
            config = load_config(environ={})
            args.source, args.model = "local", "offline"
            args.news, args.template = _data_path("news.json"), _data_path("template.json")
            args.export, args.jianying_template = "demo", None
        else:
            config = load_config(args.config)
        validate_connection_config(config, source=args.source, model=args.model)
        template = load_template(args.template)
        if args.command == "doctor":
            if not (3, 11) <= sys.version_info[:2] < (3, 14):
                raise ValidationError("Supported Python versions: 3.11-3.13")
            if args.source == "local":
                load_news(args.news)
            print(json.dumps({"status": "ok", "python": platform.python_version(),
                              "system": platform.system(), "source": args.source,
                              "model": args.model, "slot_count": len(template["slots"]),
                              "network_tested": False, "jianying_gui_tested": False}, ensure_ascii=False, indent=2))
            return 0
        if args.jianying_template and args.export != "jianying":
            raise ValidationError("--jianying-template requires --export jianying")
        source = LocalNewsSource(args.news) if args.source == "local" else DingTalkNewsSource(config["dingtalk"])
        model = OfflineModel() if args.model == "offline" else DoubaoModel(config["doubao"])
        manifest = run_batch(source=source, model=model, template=template, destination=args.output,
                             export_kind=args.export, jianying_template=args.jianying_template,
                             source_name=args.source, model_name=args.model)
        print(f"PASS: saved and verified {len(manifest['articles'])} articles in {args.output}")
        if args.export == "demo":
            print("Open each preview.html for the offline demo. This is draft data; no MP4 or Jianying GUI verification.")
        else:
            print("Jianying draft files passed saved-structure checks. Open and review them in your own Jianying version; no MP4 or GUI verification.")
        return 0
    except ValidationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except (OSError, UnicodeError) as exc:
        # Do not print OS/network exception bodies or local absolute paths.
        print(f"ERROR: file operation failed ({type(exc).__name__}); check permissions and choose a new output directory", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
