import sys,unittest,tempfile,json,urllib.error,io
from pathlib import Path
from unittest.mock import patch,MagicMock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import model_api
class APIClientTests(unittest.TestCase):
 def test_config_file_and_environment(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp)/'api.local.json';p.write_text(json.dumps({'endpoint':'https://example.invalid/v1/chat/completions','api_key':'test-placeholder','model':'vendor/model'}),encoding='utf8')
   cfg=model_api.load_api_config(p,{'NVB_API_MODEL':'other/model'})
   self.assertEqual(cfg['model'],'other/model')
   with self.assertRaises(model_api.ValidationError):model_api.load_api_config(p,{'NVB_API_ENDPOINT':'http://example.invalid'})
 def test_unknown_config_rejected(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp)/'api.local.json';p.write_text('{"unexpected":1}',encoding='utf8')
   with self.assertRaises(model_api.ValidationError):model_api.load_api_config(p,{})
 def test_response_and_payload(self):
  response=MagicMock();response.__enter__.return_value=response;response.status=200;response.read.return_value=b'{"ok":true}'
  opener=MagicMock();opener.open.return_value=response
  with patch.object(model_api.urllib.request,'build_opener',return_value=opener):
   self.assertEqual(model_api._post_json('https://example.invalid',{'model':'test-model'},{'Authorization':'Bearer test-placeholder'},15,'Model'),{'ok':True})
  req=opener.open.call_args.args[0];self.assertEqual(req.get_method(),'POST');self.assertEqual(json.loads(req.data)['model'],'test-model')
 def test_http_error_never_exposes_response(self):
  opener=MagicMock();opener.open.side_effect=urllib.error.HTTPError('https://example.invalid',401,'private-message',{},io.BytesIO(b'private-response'))
  with patch.object(model_api.urllib.request,'build_opener',return_value=opener),self.assertRaises(model_api.ValidationError) as error:
   model_api._post_json('https://example.invalid',{}, {},15,'Model')
  self.assertNotIn('private',str(error.exception));self.assertIn('401',str(error.exception))
 def test_redirect_not_followed(self):
  self.assertIsNone(model_api._NoRedirect().redirect_request(None,None,302,'',{},'https://example.invalid/other'))
 def test_oversize_response_rejected(self):
  response=MagicMock();response.__enter__.return_value=response;response.status=200;response.read.return_value=b'x'*(model_api.MAX_RESPONSE_BYTES+1)
  opener=MagicMock();opener.open.return_value=response
  with patch.object(model_api.urllib.request,'build_opener',return_value=opener),self.assertRaises(model_api.ValidationError):
   model_api._post_json('https://example.invalid',{}, {},15,'Model')
if __name__=='__main__':unittest.main()
