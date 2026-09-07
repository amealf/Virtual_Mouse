from collections import deque
from threading import Lock
import time

import numpy as np


class AudioSnapDetector:
    """Detect short microphone transients used to confirm a visual finger snap."""

    def __init__(self, sample_rate: int = 16_000, block_size: int = 256) -> None:
        self.sample_rate = sample_rate
        self.block_size = block_size
        self._events: deque[float] = deque(maxlen=16)
        self._lock = Lock()
        self._stream = None
        self._noise_floor = 0.008
        self._last_event = -10.0
        self.error: str | None = None

    @property
    def available(self) -> bool:
        return self._stream is not None and self.error is None

    def start(self) -> bool:
        try:
            import sounddevice as sd

            self._stream = sd.InputStream(
                samplerate=self.sample_rate,
                channels=1,
                dtype="float32",
                blocksize=self.block_size,
                callback=self._callback,
            )
            self._stream.start()
            return True
        except Exception as exc:
            self.error = str(exc)
            self._stream = None
            return False

    def _callback(self, input_data, _frames, _time_info, status) -> None:
        if status:
            return
        samples = np.abs(input_data[:, 0])
        peak = float(np.max(samples))
        rms = float(np.sqrt(np.mean(np.square(samples))))
        now = time.monotonic()
        threshold = max(0.08, self._noise_floor * 7.0)
        if peak >= threshold and rms >= self._noise_floor * 2.5 and now - self._last_event >= 0.25:
            with self._lock:
                self._events.append(now)
            self._last_event = now
        if rms < self._noise_floor * 3.0:
            self._noise_floor = self._noise_floor * 0.98 + max(rms, 0.001) * 0.02

    def consume_near(self, timestamp: float, tolerance: float = 0.30) -> bool:
        with self._lock:
            while self._events and self._events[0] < timestamp - tolerance:
                self._events.popleft()
            for event_time in tuple(self._events):
                if abs(event_time - timestamp) <= tolerance:
                    self._events.remove(event_time)
                    return True
        return False

    def close(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
