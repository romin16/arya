"""Async HTTP voice API for browser speech and transcription."""
from __future__ import annotations

import asyncio
import base64
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from voice.pii_mask import mask_for_tts
from voice.stt_filter import is_known_hallucination, load_stt_settings, measure_audio

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
STT_SETTINGS = load_stt_settings()
logger = logging.getLogger("arya.voice")
ELEVENLABS_VOICES = {
    "Rachel": "21m00Tcm4TlvDq8ikWAM",
    "Domi": "AZnzlk1XvdvUeBnXmlld",
    "Bella": "EXAVITQu4vr4xnSDxMaL",
    "Antoni": "ErXwobaYiN019PkySvjV",
    "Elli": "MF3mGyEYCl7XYWbV9V6O",
    "Josh": "TxGEqnHWrfWFTfGW9XjX",
    "Arnold": "VR6AewLTigWG4xSOukaG",
    "Adam": "pNInz6obpgDQGcFmaJgB",
    "Sam": "yoZ06aMxZJJ28mfd3POQ",
    "Hope": "uYXf8XasLslADfZ2MB4u",
    "Lucy": "lcMyyd2HUfFzxdCaC4Ta",
    "Charlotte": "XB0fDUnXU5powFXDhCwa",
    "Alice": "Xb7hH8MSUJpSbSDYk0k2",
    "Matilda": "XrExE9yKIg1WjnnlVkGX",
    "Freya": "jsCqWAovK2LkecY7zXl4",
}


class SpeakRequest(BaseModel):
    text: str
    stream: bool = True
    provider: str = "elevenlabs"
    voice: str = "ishita"
    voice_id: str | None = None


class VoiceProviders:
    """Asynchronous provider calls; injectable HTTP transport keeps tests offline."""

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self.client = client or httpx.AsyncClient(timeout=httpx.Timeout(60, connect=10))
        self.owns_client = client is None

    async def close(self) -> None:
        if self.owns_client:
            await self.client.aclose()

    async def elevenlabs(self, text: str, voice_id: str) -> bytes:
        key = os.getenv("ELEVENLABS_API_KEY", "")
        if not key:
            raise RuntimeError("ELEVENLABS_API_KEY is not configured")
        response = await self.client.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream",
            params={"output_format": "mp3_44100_128"},
            headers={"xi-api-key": key, "Accept": "audio/mpeg"},
            json={"text": text, "model_id": "eleven_turbo_v2_5"},
        )
        response.raise_for_status()
        return response.content

    async def sarvam(self, text: str, speaker: str) -> bytes:
        key = os.getenv("SARVAM_API_KEY") or os.getenv("SARVAM_AI_API_KEY", "")
        if not key:
            raise RuntimeError("SARVAM_API_KEY or SARVAM_AI_API_KEY is not configured")
        response = await self.client.post(
            "https://api.sarvam.ai/text-to-speech",
            headers={"api-subscription-key": key, "Accept": "application/json"},
            json={
                "inputs": [text],
                "target_language_code": "en-IN",
                "model": "bulbul:v3",
                "speaker": speaker.lower(),
            },
        )
        response.raise_for_status()
        audio = response.json()["audios"][0]
        return base64.b64decode(audio)

    async def groq_transcribe(self, filename: str, content_type: str, data: bytes) -> str:
        key = os.getenv("GROQ_API_KEY", "")
        if not key:
            raise RuntimeError("GROQ_API_KEY is not configured")
        response = await self.client.post(
            "https://api.groq.com/openai/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {key}"},
            files={"file": (filename, data, content_type)},
            data={"model": "whisper-large-v3", "language": "en", "response_format": "json"},
        )
        response.raise_for_status()
        return str(response.json().get("text", "")).strip()


def configured_elevenlabs_voice() -> str:
    voice_id = os.getenv("ELEVENLABS_VOICE_ID")
    if voice_id:
        return voice_id
    name = os.getenv("ELEVENLABS_VOICE", "Hope")
    return ELEVENLABS_VOICES.get(name, ELEVENLABS_VOICES["Hope"])


async def _warm_configured_voice(providers: VoiceProviders) -> None:
    if not os.getenv("ELEVENLABS_API_KEY"):
        logger.info("ElevenLabs warm-up skipped: provider key is not configured")
        return
    try:
        await providers.elevenlabs("Hi.", configured_elevenlabs_voice())
        logger.info("Configured ElevenLabs voice warm-up completed")
    except Exception:
        logger.warning("Configured ElevenLabs voice warm-up failed", exc_info=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    providers = VoiceProviders()
    app.state.providers = providers
    warmup = asyncio.create_task(_warm_configured_voice(providers))
    try:
        yield
    finally:
        warmup.cancel()
        await asyncio.gather(warmup, return_exceptions=True)
        await providers.close()


app = FastAPI(title="arya-voice", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def _providers() -> VoiceProviders:
    return getattr(app.state, "providers", None) or VoiceProviders()


@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "service": "arya-voice",
        "tts_providers": ["elevenlabs", "sarvam"],
        "stt": "groq",
    }


@app.post("/speak")
async def speak(payload: SpeakRequest):
    text = payload.text.strip()
    if not text:
        return JSONResponse({"success": False, "error": "text required"}, status_code=400)
    provider_name = payload.provider.strip().lower()
    safe_text = mask_for_tts(text)
    providers = _providers()
    try:
        if provider_name == "elevenlabs":
            voice_id = payload.voice_id or configured_elevenlabs_voice()
            audio_bytes = await providers.elevenlabs(safe_text, voice_id)
            media_type = "audio/mpeg"
        elif provider_name == "sarvam":
            audio_bytes = await providers.sarvam(safe_text, payload.voice.lower())
            media_type = "audio/wav"
        else:
            return JSONResponse({"success": False, "error": "unsupported provider"}, status_code=400)
    except httpx.HTTPStatusError as exc:
        logger.warning("Voice provider returned HTTP %s", exc.response.status_code)
        return JSONResponse({"success": False, "error": "voice provider request failed"}, status_code=502)
    except Exception:
        logger.exception("Voice synthesis failed")
        return JSONResponse({"success": False, "error": "voice synthesis failed"}, status_code=502)

    async def audio_chunks() -> AsyncIterator[bytes]:
        for offset in range(0, len(audio_bytes), 16_384):
            yield audio_bytes[offset:offset + 16_384]

    return StreamingResponse(
        audio_chunks(),
        media_type=media_type,
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no-cache"},
    )


@app.post("/transcribe")
async def transcribe(audio: UploadFile = File(...)):
    content = await audio.read()
    if not content:
        return JSONResponse({"success": False, "text": "", "error": "empty audio file"}, status_code=400)
    try:
        text = await _providers().groq_transcribe(
            audio.filename or "audio.wav", audio.content_type or "audio/wav", content
        )
        metrics = await asyncio.to_thread(
            measure_audio,
            content,
            audio.content_type or "audio/wav",
            str(STT_SETTINGS.get("ffmpeg_path", "ffmpeg")),
        )
        if is_known_hallucination(text, metrics, STT_SETTINGS):
            text = ""
        return {"success": True, "text": text}
    except httpx.HTTPStatusError as exc:
        logger.warning("Groq returned HTTP %s", exc.response.status_code)
        return JSONResponse({"success": False, "text": "", "error": "transcription request failed"}, status_code=502)
    except Exception:
        logger.exception("Transcription failed")
        return JSONResponse({"success": False, "text": "", "error": "transcription failed"}, status_code=502)


@app.post("/stop")
async def stop():
    return {"success": True, "message": "Playback stopped"}


def main() -> None:
    import uvicorn

    uvicorn.run(
        "voice.app:app",
        host=os.getenv("ARYA_VOICE_HOST", "127.0.0.1"),
        port=int(os.getenv("ARYA_VOICE_PORT", "5001")),
    )


if __name__ == "__main__":
    main()
