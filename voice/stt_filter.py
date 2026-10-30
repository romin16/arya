"""Filter known short-clip Whisper hallucinations using configured audio thresholds."""
from __future__ import annotations

import array
import io
import math
import re
import subprocess
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class AudioMetrics:
    duration_seconds: float
    rms_fraction: float


def load_stt_settings(path: Path | None = None) -> dict[str, Any]:
    source = yaml.safe_load((path or ROOT / "config" / "voice.yaml").read_text(encoding="utf-8"))
    return source["stt"]


def _pcm_metrics(pcm: bytes, sample_rate: int) -> AudioMetrics | None:
    if len(pcm) < 2 or sample_rate <= 0:
        return None
    samples = array.array("h")
    samples.frombytes(pcm[: len(pcm) - len(pcm) % 2])
    if not samples:
        return None
    if __import__("sys").byteorder != "little":
        samples.byteswap()
    squares = sum(sample * sample for sample in samples)
    rms_fraction = math.sqrt(squares / len(samples)) / 32768.0
    return AudioMetrics(len(samples) / sample_rate, rms_fraction)


def _wav_metrics(data: bytes) -> AudioMetrics | None:
    try:
        with wave.open(io.BytesIO(data), "rb") as wav:
            if wav.getcomptype() != "NONE" or wav.getsampwidth() != 2:
                return None
            sample_rate = wav.getframerate()
            frames = wav.readframes(wav.getnframes())
            channels = wav.getnchannels()
        metrics = _pcm_metrics(frames, sample_rate)
        if metrics is None:
            return None
        # Duration should be based on frames rather than interleaved channel samples.
        duration = metrics.duration_seconds / max(channels, 1)
        return AudioMetrics(duration, metrics.rms_fraction)
    except (wave.Error, EOFError, OSError):
        return None


def measure_audio(data: bytes, content_type: str = "", ffmpeg_path: str = "ffmpeg") -> AudioMetrics | None:
    """Decode supported audio to mono 16 kHz PCM without blocking an async caller.

    Call this function via ``asyncio.to_thread``. FFmpeg handles WebM/Opus;
    the WAV reader is a fallback for PCM16 WAV when FFmpeg is not installed.
    """
    try:
        process = subprocess.run(
            [ffmpeg_path, "-v", "error", "-nostdin", "-i", "pipe:0", "-ac", "1", "-ar", "16000", "-f", "s16le", "pipe:1"],
            input=data,
            capture_output=True,
            timeout=10,
            check=False,
        )
        if process.returncode == 0:
            return _pcm_metrics(process.stdout, 16000)
    except (OSError, subprocess.TimeoutExpired):
        pass
    if "wav" in content_type.lower() or data[:4] == b"RIFF":
        return _wav_metrics(data)
    return None


def is_known_hallucination(text: str, metrics: AudioMetrics | None, settings: dict[str, Any]) -> bool:
    normalized = re.sub(r"[^\w\s']", "", text.casefold()).strip()
    phrases = {
        re.sub(r"[^\w\s']", "", str(phrase).casefold()).strip()
        for phrase in settings.get("hallucination_phrases", [])
    }
    if normalized not in phrases or metrics is None:
        return False
    is_short = metrics.duration_seconds <= float(settings.get("short_duration_seconds", 1.25))
    is_quiet = metrics.rms_fraction <= float(settings.get("quiet_rms_fraction", 0.008))
    return is_short or is_quiet
