"""Build only scanned source files and verify exact ZIP payload after writing."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile
from check_public import collect_public, PublicSafetyError

ROOT=Path(__file__).resolve().parents[1]
def build(output, root=ROOT):
    files=collect_public(root)
    # No user overrides or internal payloads are accepted by this public packager.
    manifest={name:hashlib.sha256(data).hexdigest() for name,data in files.items()}
    output=Path(output);output.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(output,'x',zipfile.ZIP_DEFLATED) as z:
        for name,data in files.items():z.writestr(name,data)
        z.writestr('SOURCE_MANIFEST.json',json.dumps(manifest,ensure_ascii=False,indent=2))
    with zipfile.ZipFile(output) as z:
        if set(z.namelist())!=set(files)|{'SOURCE_MANIFEST.json'}:raise PublicSafetyError('ZIP members differ')
        for name,digest in manifest.items():
            if hashlib.sha256(z.read(name)).hexdigest()!=digest:raise PublicSafetyError('ZIP bytes differ')
    digest=hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix(output.suffix+'.sha256').write_text(digest+'  '+output.name+'\n',encoding='utf8')
    print(f'PASS: {len(files)} scanned files; ZIP roundtrip verified; SHA256 {digest}')
    return manifest

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',required=True,type=Path)
    build(parser.parse_args().output)
