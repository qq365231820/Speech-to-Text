import copy
import queue
import threading
import time
from .audio import Segmenter, SAMPLE_RATE, FRAME_SAMPLES
from . import providers

def polish_or_original(text, rewrite, warning):
    if not text:
        return ""
    try:
        return rewrite(text)
    except Exception:
        warning("文字整理失败，已使用原始识别文字")
        return text

class Session:
    def __init__(self, cfg, local, emit):
        self.cfg = copy.deepcopy(cfg)
        self.local, self.emit = local, emit
        self.stop_event = threading.Event()
        self.cancel_event = threading.Event()
        self.capture_done = threading.Event()
        self.frames = queue.Queue(maxsize=250)
        self.segments = queue.Queue(maxsize=8)
        self.stream = None
        self.started = time.monotonic()
        self.overrun = False

    def start(self):
        import sounddevice as sd
        def callback(data, frames, timing, status):
            if self.stop_event.is_set():
                return
            if status:
                self.overrun = True
                self.stop_event.set()
                return
            try:
                self.frames.put_nowait(bytes(data))
            except queue.Full:
                self.overrun = True
                self.stop_event.set()
        mic = self.cfg["microphone"]
        device = int(mic) if mic.strip().isdigit() else mic or None
        self.stream = sd.RawInputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16",
                                       blocksize=FRAME_SAMPLES, device=device, callback=callback)
        try:
            self.stream.start()
        except Exception:
            self.stream.close()
            raise
        self.processor = threading.Thread(target=self._process, daemon=True)
        self.capture = threading.Thread(target=self._capture, daemon=True)
        self.processor.start()
        self.capture.start()

    def stop(self):
        self.stop_event.set()

    def cancel(self):
        self.cancel_event.set()
        self.stop_event.set()

    def _enqueue(self, segment):
        if segment and not self.cancel_event.is_set():
            try:
                self.segments.put_nowait(segment)
            except queue.Full:
                self.overrun = True
                self.stop_event.set()
                self.emit("warning", "处理跟不上录音，已停止；末尾一段未处理，请重录")

    def _capture(self):
        segmenter = Segmenter(self.cfg["threshold"], self.cfg["silence_ms"], self.cfg["max_segment_s"])
        try:
            while not self.cancel_event.is_set():
                if time.monotonic()-self.started > self.cfg["max_record_s"]:
                    self.stop_event.set()
                if self.stop_event.is_set() and self.frames.empty():
                    break
                try:
                    frame = self.frames.get(timeout=0.05)
                except queue.Empty:
                    continue
                self._enqueue(segmenter.feed(frame))
            self._enqueue(segmenter.flush())
        finally:
            try:
                self.stream.stop()
            except Exception:
                self.emit("warning", "麦克风停止异常，请检查设备")
            finally:
                try:
                    self.stream.close()
                except Exception:
                    pass
                if self.overrun:
                    self.emit("warning", "音频缓冲异常，录音已停止；结果可能不完整")
                self.emit("status", "处理中…" if not self.cancel_event.is_set() else "已取消")
                self.capture_done.set()

    def _process(self):
        cfg = self.cfg
        name = cfg["provider"]
        p = cfg["profiles"][name]
        transcript = []
        rewrite = (lambda value: self.local.call("text", value, cfg)) if cfg["offline"] else (lambda value: providers.rewrite(p, value))
        warning = lambda value: self.emit("warning", value)
        try:
            while not self.cancel_event.is_set():
                try:
                    audio = self.segments.get(timeout=0.1)
                except queue.Empty:
                    if self.capture_done.is_set():
                        break
                    continue
                try:
                    text = self.local.call("asr", audio, cfg) if cfg["offline"] else providers.transcribe(name, p, audio)
                finally:
                    del audio
                if self.cancel_event.is_set():
                    break
                if cfg["output"] == "sentence":
                    value = polish_or_original(text, rewrite, warning)
                    if value and not self.cancel_event.is_set():
                        self.emit("text", value)
                elif text:
                    transcript.append(text)
            if cfg["output"] == "final" and transcript and not self.cancel_event.is_set():
                value = polish_or_original("".join(transcript), rewrite, warning)
                if not self.cancel_event.is_set():
                    self.emit("text", value)
        except Exception as exc:
            self.stop_event.set()
            if transcript and not self.cancel_event.is_set():
                self.emit("text", "".join(transcript))
            detail = str(exc) if isinstance(exc, (RuntimeError, ValueError)) else type(exc).__name__
            self.emit("warning", f"识别失败：{detail}。未识别音频不保存，请检查后重录")
        finally:
            self.stop_event.set()
            self.capture_done.wait(5)
            while True:
                try:
                    self.segments.get_nowait()
                except queue.Empty:
                    break
            self.emit("done", "")
