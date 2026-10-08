"""Build an allowlisted source ZIP, then verify every archived byte against its manifest."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

try:
    from .check_public import ROOT, MAX_FILE_BYTES, PublicSafetyError, collect_public, scan_content, is_link
except ImportError:
    from check_public import ROOT, MAX_FILE_BYTES, PublicSafetyError, collect_public, scan_content, is_link


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def verify_package(path: Path) -> dict:
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise PublicSafetyError("Archive contains duplicate member names")
        for name in names:
            p = PurePosixPath(name)
            if p.is_absolute() or ".." in p.parts or "\\" in name or ":" in name:
                raise PublicSafetyError("Archive contains an unsafe member name")
        manifest = json.loads(archive.read("PACKAGE_MANIFEST.json"))
        if manifest.get("schema_version") != 1 or manifest.get("visibility") not in {"public-ready", "private-internal"}:
            raise PublicSafetyError("Archive manifest schema/visibility is invalid")
        expected = manifest.get("files", {})
        if set(names) != set(expected) | {"PACKAGE_MANIFEST.json"}:
            raise PublicSafetyError("Archive membership does not match manifest")
        for name, record in expected.items():
            data = archive.read(name)
            if len(data) != record["size"] or sha256(data) != record["sha256"]:
                raise PublicSafetyError("Archive member integrity check failed: " + name)
        if manifest["visibility"] == "public-ready" and any(name.startswith("PRIVATE_INTERNAL/") for name in names):
            raise PublicSafetyError("Public archive contains private data")
        return manifest


def build_package(root: Path, output: Path, internal_dir: Path | None = None) -> dict:
    files = collect_public(root)
    visibility = "public-ready"
    if internal_dir is not None:
        visibility = "private-internal"
        if "private" not in output.stem.lower():
            raise PublicSafetyError("Internal archive output filename must contain 'private'")
        if is_link(internal_dir):
            raise PublicSafetyError("Internal directory must not be a link/junction")
        internal_dir = internal_dir.resolve(strict=True)
        if not internal_dir.is_dir():
            raise PublicSafetyError("Internal directory must be a directory")
        # Explicit extras remain text-only and secret-free. Credentials must be provisioned separately.
        for path in sorted(internal_dir.rglob("*")):
            if is_link(path) or not path.resolve().is_relative_to(internal_dir):
                raise PublicSafetyError("Internal files must not be links/junctions")
            if path.is_dir():
                continue
            name = "PRIVATE_INTERNAL/" + path.relative_to(internal_dir).as_posix()
            if path.suffix.lower() not in {".md", ".txt", ".json", ".csv"} or path.stat().st_size > MAX_FILE_BYTES:
                raise PublicSafetyError("Internal extras must be small UTF-8 md/txt/json/csv files")
            data = path.read_bytes()
            errors = scan_content(name, data)
            if errors:
                raise PublicSafetyError("\n".join(errors))
            files[name] = data
        files["PRIVATE_INTERNAL/PRIVATE_NOTICE.txt"] = b"PRIVATE INTERNAL PACKAGE. Do not publish. Supply credentials separately.\n"
    manifest = {
        "schema_version": 1,
        "visibility": visibility,
        "verification": "Every member was read back and compared by byte length and SHA256; this is not business acceptance.",
        "files": {name: {"size": len(data), "sha256": sha256(data)} for name, data in sorted(files.items())},
    }
    output = output.absolute()
    if output.suffix.lower() != ".zip":
        raise PublicSafetyError("Output must be a .zip file")
    if output.exists() or output.with_suffix(output.suffix + ".sha256").exists():
        raise PublicSafetyError("Output or checksum already exists; choose a new output filename")
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=".package-", suffix=".tmp", dir=output.parent)
    os.close(fd)
    temporary = Path(temp_name)
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, data in sorted(files.items()):
                info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                archive.writestr(info, data)
            archive.writestr("PACKAGE_MANIFEST.json", json.dumps(manifest, indent=2, ensure_ascii=False).encode("utf-8"))
        verified = verify_package(temporary)
        # Exclusive create protects existing deliverables, including concurrent builds.
        with output.open("xb") as target:
            target.write(temporary.read_bytes())
        checksum = sha256(output.read_bytes())
        with output.with_suffix(output.suffix + ".sha256").open("x", encoding="utf-8") as target:
            target.write(checksum + "  " + output.name + "\n")
        return {"path": str(output), "sha256": checksum, "visibility": visibility, "files": len(verified["files"])}
    finally:
        temporary.unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--internal-dir", type=Path, help="explicit secret-free internal extras; requires 'private' in output filename")
    args = parser.parse_args(argv)
    try:
        result = build_package(args.root, args.output, args.internal_dir)
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        print(f"PACKAGE FAILED: {exc}")
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
