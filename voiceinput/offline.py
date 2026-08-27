"""Heavy libraries live only in a disposable child process; never download models."""
import multiprocessing as mp
from pathlib import Path
import threading
import time

def _worker(pipe, cfg):
    import os
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    asr = llm = None
    converter = None
    try:
        while True:
            kind, value = pipe.recv()
            try:
                if kind == "asr":
                    if asr is None:
                        from faster_whisper import WhisperModel
                        asr = WhisperModel(cfg["offline_asr"], device=cfg["offline_device"],
                            compute_type="int8" if cfg["offline_device"] == "cpu" else "float16",
                            cpu_threads=4, num_workers=1, local_files_only=True)
                    import numpy as np
                    samples = np.frombuffer(value, dtype=np.int16).astype(np.float32) / 32768.0
                    segments, _ = asr.transcribe(samples, language="zh", beam_size=1,
                        condition_on_previous_text=False, vad_filter=True)
                    result = "".join(segment.text for segment in segments).strip()
                    # Whisper can emit traditional characters even for mainland Mandarin.
                    # Normalize locally, including the raw-text fallback when rewriting fails.
                    if converter is None:
                        from opencc import OpenCC
                        converter = OpenCC("t2s")
                    result = converter.convert(result)
                else:
                    if not cfg["offline_llm"] or not Path(cfg["offline_llm"]).is_file():
                        raise ValueError("未配置本地 GGUF 文字整理模型")
                    if llm is None:
                        from llama_cpp import Llama
                        llm = Llama(model_path=cfg["offline_llm"], n_ctx=4096, n_threads=4,
                                    n_threads_batch=4, n_batch=128, n_ubatch=64,
                                    n_gpu_layers=0, verbose=False)
                    from .providers import PROMPT
                    output = llm.create_chat_completion(messages=[dict(role="system", content=PROMPT),
                        dict(role="user", content=value)], temperature=0.1, max_tokens=2048)
                    result = output["choices"][0]["message"]["content"].strip()
                    if not result or len(result) > max(500, len(value)*4):
                        raise ValueError("本地整理结果异常")
                pipe.send((True, result))
            except Exception as exc:
                # Do not pass model paths, transcript contents or raw exception messages to UI/logs.
                pipe.send((False, type(exc).__name__))
    except (EOFError, BrokenPipeError):
        pass
    finally:
        pipe.close()

class LocalBackend:
    def __init__(self):
        self.process = self.pipe = None
        self.key = None
        self.lock = threading.Lock()
        self.last_used = 0

    def _close(self):
        if self.process:
            self.process.terminate()
            self.process.join(2)
            if self.process.is_alive():
                self.process.kill()
                self.process.join(1)
            self.process.close()
            self.process = None
        if self.pipe:
            self.pipe.close()
            self.pipe = None

    def call(self, kind, value, cfg):
        with self.lock:
            key = (cfg["offline_asr"], cfg["offline_llm"], cfg["offline_device"])
            if self.process is None or not self.process.is_alive() or self.key != key:
                self._close()
                context = mp.get_context("spawn")
                self.pipe, child = context.Pipe()
                self.process = context.Process(target=_worker, args=(child, cfg), daemon=True)
                self.process.start()
                child.close()
                self.key = key
            try:
                self.pipe.send((kind, value))
                if not self.pipe.poll(180):
                    self._close()
                    raise TimeoutError("本地模型超过 180 秒未响应，已卸载")
                ok, result = self.pipe.recv()
                if not ok:
                    raise RuntimeError(f"本地模型失败（{result}），检查依赖、模型格式和设备")
                return result
            finally:
                self.last_used = time.monotonic()

    def unload_idle(self, seconds):
        if self.lock.acquire(blocking=False):
            try:
                if self.process and time.monotonic()-self.last_used > seconds:
                    self._close()
            finally:
                self.lock.release()

    def close(self):
        # Shutdown is allowed to interrupt an in-flight local inference.
        if self.process and self.process.is_alive():
            self.process.terminate()
        if self.lock.acquire(timeout=3):
            try:
                self._close()
            finally:
                self.lock.release()
