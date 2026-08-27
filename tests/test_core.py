import copy
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch, Mock
import wave
from array import array

from voiceinput.audio import Segmenter
from voiceinput.config import defaults, validate, ready, endpoint, ConfigStore
from voiceinput.hotkeys import ChordState, parse_hotkey
from voiceinput.engine import Session, polish_or_original
from voiceinput.providers import XfResults, wav_bytes, transcribe, rewrite

class HotkeysTests(unittest.TestCase):
    def test_chord_repeat_release(self):
        events=[]
        state=ChordState("ctrl+alt+v",events.append)
        for key in ("ctrl","alt","v","v"):
            state.feed(key,True)
        state.feed("ctrl",False)
        state.feed("v",False)
        self.assertEqual(events,[True,False])

    def test_mouse_and_key_validation(self):
        self.assertEqual(parse_hotkey("mouse_x1"),frozenset({"mouse_x1"}))
        for value in ("a","shift+a","ctrl","ctrl+ctrl+v","mouse_left","f25"):
            with self.subTest(value=value),self.assertRaises(ValueError): parse_hotkey(value)

class AudioTests(unittest.TestCase):
    loud=array("h",[1000]*320).tobytes()
    silence=b"\0"*640

    def test_silence_is_bounded(self):
        seg=Segmenter()
        for _ in range(10000): self.assertIsNone(seg.feed(self.silence))
        self.assertEqual(len(seg.frames),0)
        self.assertLessEqual(len(seg.pre),10)

    def test_pauseilence_and_flush(self):
        seg=Segmenter(silence_ms=300)
        for _ in range(10): self.assertIsNone(seg.feed(self.loud))
        results=[seg.feed(self.silence) for _ in range(15)]
        self.assertEqual(len(results[-1]),25*640)
        self.assertIsNone(seg.flush())

    def test_max_segment(self):
        seg=Segmenter(max_seconds=3)
        results=[seg.feed(self.loud) for _ in range(150)]
        self.assertEqual(len(results[-1]),150*640)

    def test_wav(self):
        with wave.open(io.BytesIO(wav_bytes(self.loud)),"rb") as audio:
            self.assertEqual((audio.getframerate(),audio.getnchannels(),audio.getsampwidth()),(16000,1,2))
            self.assertEqual(audio.readframes(320),self.loud)

class ConfigTests(unittest.TestCase):
    def test_defaults_valid_no_ready(self):
        cfg=defaults()
        validate(cfg)
        with self.assertRaises(ValueError): ready(cfg)

    def test_no_insecure_endpoint(self):
        for url in ("http://example.com","https://user:pass@example.com","not-a-url"):
            with self.assertRaises(ValueError): endpoint(url)

    def test_dpapi_roundtrip(self):
        from voiceinput.win32 import protect,unprotect
        value=protect("fake-test-key-only")
        self.assertNotIn("fake-test-key-only",value)
        self.assertEqual(unprotect(value),"fake-test-key-only")

    def test_config_roundtrip(self):
        with tempfile.TemporaryDirectory() as folder:
            store=ConfigStore(Path(folder)/"settings.json")
            cfg=defaults()
            cfg["profiles"]["讯飞"]["api_key"]="fake-test-key-only"
            store.save(cfg)
            self.assertNotIn("fake-test-key-only",store.path.read_text(encoding="utf-8"))
            self.assertEqual(store.load(),cfg)

class ProviderTests(unittest.TestCase):
    def test_dynamic_correction(self):
        result=XfResults()
        result.feed(dict(sn=0,ws=[dict(cw=[dict(w="错误")])]))
        result.feed(dict(sn=1,ws=[dict(cw=[dict(w="文字")])]))
        result.feed(dict(sn=2,pgs="rpl",rg=[0,1],ws=[dict(cw=[dict(w="正确文字")])]))
        self.assertEqual(result.text(),"正确文字")

    def test_rewrite_fallback(self):
        warnings=[]
        def fail(text): raise TimeoutError()
        self.assertEqual(polish_or_original("原文",fail,warnings.append),"原文")
        self.assertEqual(len(warnings),1)

    def test_empty_no_rewrite(self):
        fn=Mock()
        self.assertEqual(polish_or_original("",fn,Mock()),"")
        fn.assert_not_called()

    def test_custom_multipart(self):
        with patch("voiceinput.providers.post_json",return_value=({"text":"你好"},{})) as post:
            p=defaults()["profiles"]["自定义"]
            self.assertEqual(transcribe("自定义",p,b"\0"*640),"你好")
            self.assertEqual(post.call_args.kwargs["files"]["file"][2],"audio/wav")

    def test_volcano_status_check(self):
        p=defaults()["profiles"]["火山引擎"]
        with patch("voiceinput.providers.post_json",return_value=({"result":{"text":"洛阳"}},{"X-Api-Status-Code":"20000000"})):
            self.assertEqual(transcribe("火山引擎",p,b"\0"*640),"洛阳")
        with patch("voiceinput.providers.post_json",return_value=({}, {"X-Api-Status-Code":"45000000"})):
            with self.assertRaises(RuntimeError): transcribe("火山引擎",p,b"\0"*640)

class PipelineTests(unittest.TestCase):
    def run_session(self,output="sentence",offline=False,fail_rewrite=False,cancel=False):
        cfg=defaults()
        cfg.update(output=output,offline=offline)
        local=Mock()
        local.call.side_effect=lambda kind,val,config: "原文" if kind=="asr" else "整理后"
        events=[]
        session=Session(cfg,local,lambda name,data:events.append((name,data)))
        session.segments.put(b"\0"*640)
        session.segments.put(b"\0"*640)
        session.capture_done.set()
        if cancel: session.cancel()
        with patch("voiceinput.providers.transcribe",return_value="原文") as asr,patch("voiceinput.providers.rewrite",side_effect=TimeoutError() if fail_rewrite else lambda p,t:"整理后") as tidy:
            session._process()
        return events,asr,tidy,local

    def test_sentence(self):
        events,asr,tidy,_=self.run_session()
        self.assertEqual([v for k,v in events if k=="text"],["整理后","整理后"])
        self.assertEqual(tidy.call_count,2)

    def test_final_once(self):
        events,_,tidy,_=self.run_session(output="final")
        self.assertEqual([v for k,v in events if k=="text"],["整理后"])
        self.assertEqual(tidy.call_count,1)
        self.assertEqual(tidy.call_args.args[1],"原文原文")

    def test_offline_never_cloud(self):
        events,asr,tidy,local=self.run_session(offline=True)
        asr.assert_not_called()
        tidy.assert_not_called()
        self.assertEqual(local.call.call_count,4)

    def test_cancel_no_input(self):
        events,asr,_,_=self.run_session(cancel=True)
        asr.assert_not_called()
        self.assertFalse(any(k=="text" for k,v in events))

    def test_rewrite_failure_keeps_text(self):
        events,_,_,_=self.run_session(fail_rewrite=True)
        self.assertEqual([v for k,v in events if k=="text"],["原文","原文"])

if __name__=="__main__": unittest.main()
