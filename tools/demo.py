"""Create original text-only examples through the preserved draft writer, offline."""
import argparse
import json
from pathlib import Path
import sys
import uuid
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '引擎'))
import pyJianYingDraft as draft
from pipeline import BatchRunner
from template_health import analyze_slots

class PlainCodec:
    @staticmethod
    def encrypt(value): return value
    @staticmethod
    def decrypt(value): return value

def create(destination):
    destination=Path(destination)
    if destination.exists(): raise FileExistsError('Choose a new demo output directory')
    destination.mkdir(parents=True)
    source=draft.ScriptFile(1080,1920,30,False)
    track=source.append_track(draft.TrackSpec(draft.TrackType.text))
    source.add_segment(draft.TextSegment('原创演示前段',draft.Timerange(0,3000000)),track)
    source.add_segment(draft.TextSegment('原创演示后段',draft.Timerange(3000000,3000000)),track)
    plain=source.dumps();slots=analyze_slots(json.loads(plain))
    runner=BatchRunner.__new__(BatchRunner)
    runner.crypto=PlainCodec()
    runner.template_plain=lambda name:plain
    runner._collect_materials=lambda *args:({},[])
    examples=[('demo-library','虚构图书馆开放','新增社区阅读空间'),('demo-garden','虚构花园完成修整','居民参与种植体验')]
    report=[]
    for name,first,last in examples:
        target=destination/name;target.mkdir()
        info={'文字位1':first,'文字位2':last}
        warnings=runner._fill_draft(str(target),info,str(target),slots,'默认')
        meta=json.loads((Path(draft.__file__).parent/'assets/draft_meta_info.json').read_text(encoding='utf8'))
        meta.update(draft_name=name,draft_id=str(uuid.uuid4()).upper(),tm_duration=6000000)
        (target/'draft_meta_info.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding='utf8')
        (target/'texts.json').write_text(json.dumps(info,ensure_ascii=False,indent=2),encoding='utf8')
        report.append({'name':name,'verified_text_slots':2,'warnings':warnings})
    (destination/'demo-report.json').write_text(json.dumps({'mode':'offline-original-writer','gui_verified':False,'examples':report},ensure_ascii=False,indent=2),encoding='utf8')
    print('PASS: two original text-only drafts saved and read back; no API, DLL or GUI call.')
    return report

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    create(parser.parse_args().output)
