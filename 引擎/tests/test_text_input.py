import sys,json,tempfile,unittest,types,ast
from pathlib import Path
from unittest.mock import patch,MagicMock
engine=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(engine))
import text_input,news_text
class Integration(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
  lib=self.root/'模板库';(lib/'原创测试').mkdir(parents=True)
  (lib/'模板清单.json').write_text(json.dumps([{'名字':'原创测试','类型':['默认']}]),encoding='utf8')
  slots={'文字槽位':[{'键名':k,'轨道序号':0,'片段':[i],'文案要求':'独立文案'} for i,k in enumerate(['正文1','正文2'])]}
  (lib/'原创测试'/'slots.json').write_text(json.dumps(slots),encoding='utf8')
  self.cfg={'endpoint':'https://example.invalid/v1/chat/completions','api_key':'test-placeholder','model':'user/model'}
  self.response={'choices':[{'finish_reason':'stop','message':{'content':json.dumps({'正文1':'前段内容\n第二行','正文2':'后段进展','内容分类':'电池'})}}]}
 def test_real_input_writer_and_original_reader(self):
  with patch.object(text_input,'ROOT',self.root),patch('model_api._post_json',return_value=self.response) as post:
   self.assertEqual(text_input.run('这是用户直接输入的事实材料',self.cfg,'原创测试'),0)
  files=list((self.root/'输入').rglob('info.txt'));self.assertEqual(len(files),1)
  # Execute the unchanged original reader function only; no DLL/GUI loading.
  tree=ast.parse((engine/'pipeline.py').read_text(encoding='utf-8-sig'))
  func=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='read_info_txt')
  scope={};exec(compile(ast.Module(body=[func],type_ignores=[]),'original-reader','exec'),scope)
  info=scope['read_info_txt'](str(files[0]));self.assertEqual(info['正文1'],'前段内容\n第二行');self.assertEqual(info['内容分类'],'电池')
  self.assertEqual((files[0].parent/'模板.txt').read_text(encoding='utf8'),'原创测试')
  self.assertIn('这是用户直接输入的事实材料',post.call_args.args[1]['messages'][1]['content'])
  self.assertNotIn('thinking',post.call_args.args[1])
 def test_original_runner_receives_only_new_episode(self):
  runner=MagicMock();runner.run.return_value=0;factory=MagicMock(return_value=runner)
  with patch.object(text_input,'ROOT',self.root),patch('model_api._post_json',return_value=self.response),patch.dict(sys.modules,{'pipeline':types.SimpleNamespace(BatchRunner=factory)}):
   self.assertEqual(text_input.run('材料',self.cfg,'原创测试',True),0)
  episodes=runner.run.call_args.kwargs['episode_dirs'];self.assertEqual(len(episodes),1);self.assertTrue((Path(episodes[0])/'info.txt').exists())
 def test_doubao_keeps_original_thinking_option(self):
  cfg={**self.cfg,'endpoint':'https://ark.cn-beijing.volces.com/api/v3/chat/completions'}
  with patch('model_api._post_json',return_value=self.response) as post:
   news_text._call_doubao(cfg,'test')
  self.assertEqual(post.call_args.args[1]['thinking'],{'type':'disabled'})
 def test_api_failure_does_not_create_episode(self):
  with patch.object(text_input,'ROOT',self.root),patch('model_api._post_json',side_effect=ValueError('API unavailable')):
   self.assertEqual(text_input.run('材料',self.cfg,'原创测试'),2)
  self.assertFalse(list((self.root/'输入').rglob('info.txt')))
if __name__=='__main__':unittest.main()
