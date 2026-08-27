import base64
import json
import unittest
from unittest.mock import patch, Mock
from voiceinput.config import defaults
from voiceinput.providers import websocket_asr, xf_url, tencent_url, rewrite

class FakeSocket:
    def __init__(self,messages):
        self.messages=iter(messages)
        self.sent=[]
        self.closed=False
    def recv(self): return json.dumps(next(self.messages))
    def send(self,value): self.sent.append(value)
    def send_binary(self,value): self.sent.append(value)
    def close(self): self.closed=True

class ProtocolTests(unittest.TestCase):
    def profile(self,name):
        p=defaults()["profiles"][name]
        p.update(api_key="fake",api_secret="fake-secret",app_id="123")
        return p

    def test_xf_signed_url(self):
        from urllib.parse import urlparse,parse_qs
        url=xf_url(self.profile("讯飞"))
        query=parse_qs(urlparse(url).query)
        auth=base64.b64decode(query["authorization"][0]).decode()
        self.assertIn('algorithm="hmac-sha256"',auth)
        self.assertIn('signature="',auth)
        self.assertNotIn("fake-secret",url)

    def test_tencent_signed_url(self):
        from urllib.parse import urlparse,parse_qs
        url=tencent_url(self.profile("腾讯云"))
        self.assertTrue(urlparse(url).path.endswith("/123"))
        values=parse_qs(urlparse(url).query)
        self.assertEqual(values["voice_format"],["1"])
        self.assertIn("signature",values)
        self.assertNotIn("fake-secret",url)

    def test_ali_confirmed_sentences_only(self):
        fake=FakeSocket([
            {"header":{"event":"task-started"}},
            {"header":{"event":"result-generated"},"payload":{"output":{"sentence":{"sentence_id":0,"text":"草稿","sentence_end":False}}}},
            {"header":{"event":"result-generated"},"payload":{"output":{"sentence":{"sentence_id":0,"text":"洛阳","sentence_end":True}}}},
            {"header":{"event":"task-finished"}}])
        with patch("websocket.create_connection",return_value=fake):
            self.assertEqual(websocket_asr("阿里云",self.profile("阿里云"),b"\0"*640),"洛阳")
        request=json.loads(fake.sent[0])
        self.assertEqual(request["header"]["action"],"run-task")
        self.assertEqual(request["payload"]["model"],"fun-asr-realtime")
        self.assertTrue(fake.closed)

    def test_ali_failure_closes(self):
        fake=FakeSocket([{"header":{"event":"task-failed","error_code":"bad-key"}}])
        with patch("websocket.create_connection",return_value=fake),self.assertRaises(RuntimeError):
            websocket_asr("阿里云",self.profile("阿里云"),b"\0"*640)
        self.assertTrue(fake.closed)

    def test_xf_result_decode(self):
        result=dict(sn=0,ws=[dict(cw=[dict(w="河南洛阳")])])
        fake=FakeSocket([{"header":{"code":0,"status":2},"payload":{"result":{"text":base64.b64encode(json.dumps(result).encode()).decode()}}}])
        with patch("websocket.create_connection",return_value=fake):
            self.assertEqual(websocket_asr("讯飞",self.profile("讯飞"),b"\0"*640),"河南洛阳")
        self.assertTrue(fake.closed)

    def test_tencent_final_only(self):
        fake=FakeSocket([{"code":0},{"code":0,"result":{"slice_type":1,"index":0,"voice_text_str":"草稿"}},
            {"code":0,"result":{"slice_type":2,"index":0,"voice_text_str":"洛阳"}}, {"code":0,"final":1}])
        with patch("websocket.create_connection",return_value=fake):
            self.assertEqual(websocket_asr("腾讯云",self.profile("腾讯云"),b"\0"*640),"洛阳")

    def test_text_completion(self):
        p=self.profile("阿里云")
        p["text_key"]="fake-text-key"
        with patch("voiceinput.providers.post_json",return_value=({"choices":[{"message":{"content":"普通话书面表达。"}}]},{})) as request:
            self.assertEqual(rewrite(p,"洛阳话"),"普通话书面表达。")
            self.assertIn("洛阳",request.call_args.args[2]["messages"][0]["content"])
            self.assertEqual(request.call_args.args[1]["Authorization"],"Bearer fake-text-key")

    def test_empty_completion_rejected(self):
        p=self.profile("阿里云")
        p["text_key"]="fake-text-key"
        with patch("voiceinput.providers.post_json",return_value=({"choices":[{"message":{"content":" "}}]},{})),self.assertRaises(ValueError):
            rewrite(p,"你好")

if __name__=="__main__": unittest.main()
