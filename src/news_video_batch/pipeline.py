"""All-or-nothing batch orchestration with verified, hashed deliverables."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tempfile
from pathlib import Path

from . import __version__
from .domain import ValidationError, validate_news, validate_template, validate_texts


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _is_link_or_reparse(path: Path) -> bool:
    """Detect Windows junctions on Python 3.11 as well as symbolic links.

    Path.is_junction was added in 3.12. lstat exposes the reparse attribute on
    supported Windows versions, so no link target has to be followed here.
    """
    try:
        details = path.lstat()
    except (FileNotFoundError, NotADirectoryError):
        return False
    return stat.S_ISLNK(details.st_mode) or bool(
        getattr(details, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    )


def _check_new_destination(destination: Path) -> Path:
    raw = destination.absolute()
    for parent in (raw, *raw.parents):
        if _is_link_or_reparse(parent):
            raise ValidationError("Output path must not contain symbolic links or junctions")
    if raw.exists():
        raise ValidationError("Output directory already exists; choose a new directory")
    return raw


def run_batch(*, source, model, template: dict, destination: Path,
              export_kind: str = "demo", jianying_template: Path | None = None,
              source_name: str = "local", model_name: str = "offline") -> dict:
    """Sources and models are small load()/generate() adapters; no implicit network."""
    from .exporters import write_demo, write_jianying

    validate_template(template)
    final_path = _check_new_destination(Path(destination))
    if export_kind not in ("demo", "jianying"):
        raise ValidationError("Unknown export kind")
    if export_kind == "jianying" and jianying_template is None:
        raise ValidationError("Jianying export requires an explicitly supplied template directory")
    if export_kind == "jianying":
        template_path = Path(jianying_template).resolve()
        # Avoid writing a batch into the source template, even if the writer copies selectively.
        if final_path.resolve().is_relative_to(template_path):
            raise ValidationError("Output must be outside the Jianying template directory")
    records = validate_news(source.load())
    final_path.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".nvbatch-", dir=final_path.parent))
    try:
        entries: list[dict] = []
        for news in records:
            generated = model.generate(news, template)
            generated_ids = {s["id"] for s in template["slots"] if s["mode"] == "generated"}
            if not isinstance(generated, dict) or set(generated) != generated_ids:
                raise ValidationError("Model response must exactly match generated slot IDs")
            texts = {s["id"]: s["text"] for s in template["slots"] if s["mode"] == "fixed"}
            texts.update(generated)
            texts = validate_texts(template, texts)
            folder = staging / news["id"]
            folder.mkdir()
            if export_kind == "demo":
                result = write_demo(news, template, texts, folder)
            else:
                result = write_jianying(news, template, texts, folder, Path(jianying_template))
            if not result.get("verified"):
                raise ValidationError("Exporter did not confirm saved content verification")
            write_json(folder / "texts.json", texts)
            # The persisted text map itself must survive a JSON round trip unchanged.
            if json.loads((folder / "texts.json").read_text(encoding="utf-8")) != texts:
                raise ValidationError("Saved text map differs from generated values")
            entries.append({"id": news["id"], "export": result, "slot_count": len(texts)})
        hashes = {}
        for file in sorted(staging.rglob("*")):
            if _is_link_or_reparse(file):
                raise ValidationError("Exporter created an unsupported symbolic link")
            if file.is_file():
                hashes[file.relative_to(staging).as_posix()] = hashlib.sha256(file.read_bytes()).hexdigest()
        manifest = {
            "schema_version": 1,
            "tool_version": __version__,
            "source": source_name,
            "model": model_name,
            "export_kind": export_kind,
            "verification": "saved-text-and-timing",
            "jianying_gui_verified": False,
            "video_rendered": False,
            "articles": entries,
            "sha256": hashes,
        }
        write_json(staging / "manifest.json", manifest)
        verify_batch(staging)
        # Reserve destination exclusively, then use os.replace for completed staged contents.
        # On Windows rename refuses any existing directory. On POSIX guard with exclusive mkdir.
        if os.name == "nt":
            # Windows directory rename itself refuses an existing destination.
            staging.rename(final_path)
        else:
            final_path.mkdir(exist_ok=False)
            try:
                os.replace(staging, final_path)
            except BaseException:
                final_path.rmdir()  # Only the empty directory created by this call.
                raise
        return manifest
    except BaseException:
        if staging.exists():
            shutil.rmtree(staging)
        raise


def verify_batch(directory: Path) -> dict:
    """Check saved files against manifest; not a claim of factual/visual acceptance."""
    from .domain import read_json

    directory = Path(directory)
    manifest = read_json(directory / "manifest.json")
    if not isinstance(manifest, dict) or not isinstance(manifest.get("sha256"), dict) or not manifest["sha256"]:
        raise ValidationError("Invalid batch manifest")
    expected: set[str] = set()
    for name, digest in manifest["sha256"].items():
        if not isinstance(name, str) or "\\" in name or ":" in name:
            raise ValidationError("Unsafe manifest path")
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts or name != relative.as_posix():
            raise ValidationError("Unsafe manifest path")
        file = directory / relative
        if any(_is_link_or_reparse(p) for p in (file, *file.parents)) or not file.resolve().is_relative_to(directory.resolve()):
            raise ValidationError("Manifest path leaves batch directory")
        if not isinstance(digest, str) or not file.is_file() or hashlib.sha256(file.read_bytes()).hexdigest() != digest:
            raise ValidationError("Batch file is missing or has changed")
        expected.add(name)
    actual = {p.relative_to(directory).as_posix() for p in directory.rglob("*") if p.is_file()}
    if actual != expected | {"manifest.json"}:
        raise ValidationError("Batch contains unlisted files")
    return manifest
