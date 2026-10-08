"""输入一段文字，沿用原版模板文案与草稿流水线。"""
import argparse
import json
from pathlib import Path
import tempfile
import sys

# The original bundled Python uses an isolated search path.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from model_api import load_api_config, read_input, ValidationError
from make_inputs import build_inputs

ROOT = Path(__file__).resolve().parent.parent

def run(text, config, template, generate_drafts=False):
    if not isinstance(text, str) or not text.strip() or len(text) > 30000:
        raise ValidationError('输入文字必须为1至30000字符')
    # Unprovided source/date remain empty, never invented.
    records = [{'seq': 'text', 'title': '用户输入', 'summary': text,
                'source': '', 'date': '', 'link': '', 'type': ''}]
    with tempfile.TemporaryDirectory(prefix='nvb-text-') as folder:
        record_file = Path(folder) / 'records.json'
        record_file.write_text(json.dumps(records, ensure_ascii=False), encoding='utf-8')
        result = build_inputs(str(record_file), str(ROOT), allow_existing=True,
                              template_override=template, api_config=config)
    if result['failed'] or not result['generated_items']:
        return 2
    if generate_drafts:
        from pipeline import BatchRunner
        return BatchRunner(str(ROOT)).run(episode_dirs=[item['folder'] for item in result['generated_items']])
    print('文案输入已准备，未调用剪映；--generate-drafts 可继续原版草稿流程。')
    return 0

def main(argv=None):
    if argv is None and len(sys.argv) == 1:
        print("输入文字生成草稿（使用你自己的API账户）")
        filename = input("文字文件路径（UTF-8；直接回车退出）：").strip().strip('"')
        if not filename:
            return 0
        template = input("已注册模板名称（直接回车为默认）：").strip() or "默认"
        config = input("API配置文件（直接回车为model_api.local.json）：").strip().strip('"') or str(ROOT / "model_api.local.json")
        argv = ['--text-file', filename, '--template', template, '--api-config', config, '--generate-drafts']
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--text')
    source.add_argument('--text-file', type=Path)
    parser.add_argument('--api-config', required=True, type=Path)
    parser.add_argument('--template', required=True)
    parser.add_argument('--generate-drafts', action='store_true')
    args = parser.parse_args(argv)
    try:
        config = load_api_config(args.api_config)
        text = args.text if args.text is not None else read_input(args.text_file)
        return run(text, config, args.template, args.generate_drafts)
    except (ValidationError, ValueError, OSError, UnicodeError):
        print('输入或配置无效，或文件操作失败；请检查文字、API配置、模板及本地权限。')
        return 2

if __name__ == '__main__':
    raise SystemExit(main())
