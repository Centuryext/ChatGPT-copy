"""
Minimal Kokoro TTS service for Pipecat.

Kokoro is small, fast, and natural — good default for real-time phone audio.
Telephony wants 8kHz mono; Kokoro outputs 24kHz, so we resample down.

To swap voices: change TTS_VOICE (e.g. af_heart, af_bella, am_michael).
To swap engines entirely (e.g. XTTS-v2 for voice cloning), keep the same
run_tts() signature and yield TTSAudioRawFrame chunks.
"""
import numpy as np
from kokoro_onnx import Kokoro

from pipecat.frames.frames import TTSAudioRawFrame, TTSStartedFrame, TTSStoppedFrame
from pipecat.services.tts_service import TTSService

TELEPHONY_RATE = 8000
KOKORO_RATE = 24000


def _resample_to_8k(samples: np.ndarray) -> bytes:
    # simple linear decimation 24k -> 8k (factor 3); fine for phone audio
    if samples.dtype != np.float32:
        samples = samples.astype(np.float32)
    down = samples[::3]
    pcm16 = np.clip(down * 32767, -32768, 32767).astype("<i2")
    return pcm16.tobytes()


class KokoroTTSService(TTSService):
    def __init__(self, voice: str = "af_heart", **kwargs):
        super().__init__(sample_rate=TELEPHONY_RATE, **kwargs)
        self._voice = voice
        # Model files: download once (see runbook). Paths configurable via env if needed.
        self._kokoro = Kokoro("kokoro-v0_19.onnx", "voices.bin")

    async def run_tts(self, text: str):
        yield TTSStartedFrame()
        samples, _sr = self._kokoro.create(text, voice=self._voice, speed=1.0, lang="en-us")
        pcm8k = _resample_to_8k(np.asarray(samples))
        # chunk ~20ms frames (160 samples @ 8kHz, 2 bytes each = 320 bytes)
        chunk = 320
        for i in range(0, len(pcm8k), chunk):
            yield TTSAudioRawFrame(pcm8k[i:i + chunk], TELEPHONY_RATE, 1)
        yield TTSStoppedFrame()
