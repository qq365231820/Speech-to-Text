from array import array
from collections import deque
import math

SAMPLE_RATE = 16000
FRAME_SAMPLES = 320

class Segmenter:
    """Bounded 16 kHz / 16-bit mono energy detector, including pre-roll."""
    def __init__(self, threshold=350, silence_ms=800, max_seconds=15):
        self.threshold = threshold
        self.silence_frames = max(1, silence_ms // 20)
        self.limit = max_seconds * 50
        self.pre = deque(maxlen=10)
        self.frames = []
        self.quiet = 0
        self.voiced = 0

    def feed(self, frame):
        samples = array("h", frame)
        energy = math.sqrt(sum(v*v for v in samples) / max(1, len(samples)))
        loud = energy >= self.threshold
        if not self.frames:
            self.pre.append(frame)
            if not loud:
                return None
            self.frames = list(self.pre)
            self.pre.clear()
        else:
            self.frames.append(frame)
        self.voiced += int(loud)
        self.quiet = 0 if loud else self.quiet + 1
        if self.quiet >= self.silence_frames or len(self.frames) >= self.limit:
            return self.flush()
        return None

    def flush(self):
        data = b"".join(self.frames) if self.voiced >= 5 else None
        self.frames.clear()
        self.quiet = self.voiced = 0
        return data
