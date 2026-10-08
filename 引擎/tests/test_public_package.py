import sys
from pathlib import Path
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'tools'))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from check_public import collect_public, PublicSafetyError
from build_package import build
import schedule_task

class PublicPackageTests(unittest.TestCase):
    def test_config_is_not_selected_outside_allowed_roots(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'README.md').write_text('test')
            (root/'model_api.local.json').write_text('private local configuration')
            self.assertEqual(set(collect_public(root)),{'README.md'})
    def test_config_in_engine_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'引擎').mkdir();(root/'引擎/config.json').write_text('{}')
            with self.assertRaises(PublicSafetyError): collect_public(root)
    def test_package_roundtrip_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'project';root.mkdir();(root/'README.md').write_text('original source')
            output=Path(tmp)/'package.zip'
            self.assertIn('README.md',build(output,root))
            with self.assertRaises(FileExistsError):build(output,root)
    def test_task_uses_local_venv_and_separate_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            python=Path(tmp)/'.venv/Scripts/python.exe';python.parent.mkdir(parents=True);python.write_text('fixture')
            self.assertIn(str(python),schedule_task.task_command(tmp))
            self.assertEqual(schedule_task.TASK_NAME,'NewsVideoBatchAuto_OpenSource')
