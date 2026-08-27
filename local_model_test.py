"""Opt-in real model test. Synthetic local speech only; never sends network requests."""
import argparse
import audioop
import json
import multiprocessing
from pathlib import Path
import time
import wave
import sys
from voiceinput.config import defaults, ConfigStore
from voiceinput.offline import LocalBackend

ROOT=Path(__file__).resolve().parent
SAMPLE="今天下午三点在洛阳开会，请把会议记录整理好。"

def make_sample():
    import comtypes.client
    folder=ROOT/"test-artifacts"
    folder.mkdir(exist_ok=True)
    path=folder/"synthetic-mandarin.wav"
    voice=comtypes.client.CreateObject("SAPI.SpVoice")
    voices=voice.GetVoices()
    descriptions=[]
    selected=None
    for index in range(voices.Count):
        token=voices.Item(index)
        descriptions.append(token.GetDescription())
        languages=token.GetAttribute("Language").lower().split(";")
        if "804" in languages:
            selected=token
            break
    if selected is None:
        raise RuntimeError("No local Mandarin SAPI voice: "+str(descriptions))
    voice.Voice=selected
    stream=comtypes.client.CreateObject("SAPI.SpFileStream")
    stream.Open(str(path),3,False)
    try:
        voice.AudioOutputStream=stream
        voice.Speak(SAMPLE)
    finally:
        stream.Close()
    with wave.open(str(path),"rb") as source:
        pcm=source.readframes(source.getnframes())
        if source.getsampwidth()!=2:
            pcm=audioop.lin2lin(pcm,source.getsampwidth(),2)
        if source.getnchannels()==2:
            pcm=audioop.tomono(pcm,2,0.5,0.5)
        if source.getframerate()!=16000:
            pcm,_=audioop.ratecv(pcm,2,1,source.getframerate(),16000,None)
    return pcm,selected.GetDescription()

def child_memory(pid):
    import ctypes as c
    from ctypes import wintypes as w
    class Memory(c.Structure):
        _fields_=[("cb",w.DWORD),("faults",w.DWORD)]+[(name,c.c_size_t) for name in
            ("peak_ws","working_set","peak_paged","paged","peak_nonpaged","nonpaged","pagefile","peak_pagefile")]
    kernel=c.WinDLL("kernel32")
    kernel.OpenProcess.argtypes=[w.DWORD,w.BOOL,w.DWORD]
    kernel.OpenProcess.restype=w.HANDLE
    kernel.CloseHandle.argtypes=[w.HANDLE]
    psapi=c.WinDLL("psapi")
    psapi.GetProcessMemoryInfo.argtypes=[w.HANDLE,c.POINTER(Memory),w.DWORD]
    handle=kernel.OpenProcess(0x410,False,pid)
    info=Memory(cb=c.sizeof(Memory))
    try:
        if not handle or not psapi.GetProcessMemoryInfo(handle,c.byref(info),info.cb):
            return None
        return round(info.working_set/1024/1024,1)
    finally:
        if handle:kernel.CloseHandle(handle)

def main():
    if hasattr(sys.stdout,"reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser=argparse.ArgumentParser()
    parser.add_argument("--sample-only",action="store_true")
    parser.add_argument("--asr-only",action="store_true")
    parser.add_argument("--configure",action="store_true")
    parser.add_argument("--check-runtime",action="store_true")
    args=parser.parse_args()
    if args.check_runtime:
        import faster_whisper,llama_cpp
        print("faster-whisper",faster_whisper.__version__,"llama-cpp-python",llama_cpp.__version__,flush=True)
        import sounddevice as sd
        inputs=[d for d in sd.query_devices() if d["max_input_channels"]>0]
        print("Available audio inputs:",len(inputs),flush=True)
        try:
            sd.check_input_settings(channels=1,samplerate=16000,dtype="int16")
            print("Default microphone supports 16kHz mono PCM",flush=True)
        except Exception as exc:
            print("Default microphone configuration check:",type(exc).__name__,flush=True)
        return
    pcm,voice=make_sample()
    print(json.dumps(dict(voice=voice,sample=SAMPLE,audio_seconds=len(pcm)/32000),ensure_ascii=False),flush=True)
    if args.sample_only:return
    cfg=defaults()
    cfg.update(offline=True,offline_asr=str(ROOT/"models"/"faster-whisper-small"),
               offline_llm=str(ROOT/"models"/"qwen"/"qwen2.5-1.5b-instruct-q4_k_m.gguf"),
               offline_device="cpu")
    backend=LocalBackend()
    report=dict(sample=SAMPLE,voice=voice)
    try:
        start=time.monotonic()
        text=backend.call("asr",pcm,cfg)
        report.update(asr_text=text,asr_cold_seconds=round(time.monotonic()-start,2),asr_memory_mb=child_memory(backend.process.pid))
        print(json.dumps(report,ensure_ascii=False),flush=True)
        assert "洛阳" in text and "会议" in text,"Mandarin key-word check failed"
        start=time.monotonic()
        warm=backend.call("asr",pcm,cfg)
        report["asr_warm_seconds"]=round(time.monotonic()-start,2)
        assert warm==text,"Repeated ASR result changed"
        if not args.asr_only:
            start=time.monotonic()
            polished=backend.call("text",text,cfg)
            report.update(polished_text=polished,text_cold_seconds=round(time.monotonic()-start,2),combined_memory_mb=child_memory(backend.process.pid))
            assert "洛阳" in polished and "会议" in polished,"Polished text lost key facts"
            start=time.monotonic()
            dialect=backend.call("text","俺今儿下午三点去洛阳开会，你帮俺把那个会议记录弄好。",cfg)
            report.update(dialect_text= dialect,text_warm_seconds=round(time.monotonic()-start,2))
            assert "洛阳" in dialect and "会议" in dialect,"Dialect rewriting lost key facts"
            from voiceinput.engine import Session
            events=[]
            cfg["output"]="final"
            session=Session(cfg,backend,lambda name,value:events.append((name,value)))
            session.segments.put(pcm)
            session.capture_done.set()  # Synthetic segment instead of a live microphone.
            session._process()
            outputs=[value for name,value in events if name=="text"]
            report["pipeline_output"]=outputs
            report["pipeline_warnings"]=[value for name,value in events if name=="warning"]
            assert len(outputs)==1 and "洛阳" in outputs[0] and not report["pipeline_warnings"],"Full offline pipeline failed"
        backend.last_used=time.monotonic()-61
        backend.unload_idle(60)
        report["idle_unloaded"]=backend.process is None
        assert report["idle_unloaded"]
        if args.configure:
            store=ConfigStore()
            saved=store.load()
            # Keep the user's keys, hotkey and other preferences.
            for key in ("offline_asr","offline_llm","offline_device"):
                saved[key]=cfg[key]
            saved["offline"]=True
            store.save(saved)
            restored=store.load()
            assert restored["offline"] and restored["offline_asr"]==cfg["offline_asr"] and restored["offline_llm"]==cfg["offline_llm"]
            report["configured_offline"]=True
        path=ROOT/"test-artifacts"/("offline-asr-test.json" if args.asr_only else "offline-test.json")
        path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
        print(json.dumps(report,ensure_ascii=False,indent=2),flush=True)
    finally:
        backend.close()

if __name__=="__main__":
    multiprocessing.freeze_support()
    main()
