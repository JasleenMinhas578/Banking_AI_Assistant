"""Speech in and out, both local and both optional.

    STT: faster-whisper (Whisper small, int8 on CPU). Returns the text and a confidence.
    TTS: Kokoro through kokoro-onnx. Returns 24 kHz WAV bytes.

Install with `uv sync --extra voice` and `make voice-models`. Without them the
gateway still works: the web app falls back to typing and to the browser's own
speech synthesis, and says so on screen.
"""

import io
import logging
import math
import re
import wave
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)
LOW_CONFIDENCE = 0.55  # below this, ask the caller to repeat rather than act on a guess


class SpeechToText:
    def __init__(self, model_size: str = "small") -> None:
        self.model: Any = None
        try:
            from faster_whisper import WhisperModel

            self.model = WhisperModel(model_size, device="cpu", compute_type="int8")
            log.info("Whisper %s loaded", model_size)
        except Exception as exc:  # not installed, or the model can't load
            log.warning("Speech-to-text unavailable: %s", exc)

    @property
    def available(self) -> bool:
        return self.model is not None

    def transcribe(self, audio_path: Path) -> tuple[str, float]:
        """Text and a 0..1 confidence (from Whisper's average log probability)."""
        segments, _info = self.model.transcribe(
            str(audio_path), language="en", beam_size=1, vad_filter=True
        )
        parts, logprobs = [], []
        for segment in segments:
            parts.append(segment.text.strip())
            logprobs.append(segment.avg_logprob)
        text = " ".join(p for p in parts if p)
        confidence = math.exp(sum(logprobs) / len(logprobs)) if logprobs else 0.0
        return text, min(1.0, confidence)


class TextToSpeech:
    def __init__(self, model_dir: Path, voice: str = "af_sarah") -> None:
        self.model: Any = None
        self.voice = voice
        try:
            from kokoro_onnx import Kokoro

            self.model = Kokoro(
                str(model_dir / "kokoro-v1.0.onnx"), str(model_dir / "voices-v1.0.bin")
            )
            log.info("Kokoro loaded")
        except Exception as exc:
            log.warning("Text-to-speech unavailable: %s", exc)

    @property
    def available(self) -> bool:
        return self.model is not None

    def speak(self, text: str) -> bytes:
        samples, rate = self.model.create(spoken(text), voice=self.voice, speed=1.0, lang="en-us")
        return to_wav(samples, rate)


def spoken(text: str) -> str:
    """Make replies read well aloud: '••••4821' becomes 'ending 4 8 2 1'."""
    return re.sub(r"••••(\d{4})", lambda m: "ending " + " ".join(m.group(1)), text)


def to_wav(samples: Any, rate: int) -> bytes:
    import numpy as np

    pcm = (np.clip(np.asarray(samples), -1.0, 1.0) * 32767).astype("<i2").tobytes()
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(pcm)
    return buffer.getvalue()
