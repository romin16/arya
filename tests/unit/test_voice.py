import base64
import json

import httpx
import pytest

from voice.app import VoiceProviders, app, configured_elevenlabs_voice


@pytest.fixture
async def voice_api_client():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://voice") as client:
        yield client


@pytest.mark.asyncio
async def test_speak_masks_email_and_phone_before_elevenlabs_request(monkeypatch, voice_api_client):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-eleven-key")
    raw_email = "person@example.com"
    raw_phone = "+91 98765 43210"
    captured = {}

    async def handler(request: httpx.Request):
        body = json.loads(request.content)
        captured["body"] = body
        captured["url"] = str(request.url)
        assert raw_email not in request.content.decode()
        assert raw_phone not in request.content.decode()
        assert "their email address" in body["text"]
        assert "the number ending in 10" in body["text"]
        return httpx.Response(200, content=b"fake-mp3")

    provider_http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    app.state.providers = VoiceProviders(provider_http)
    response = await voice_api_client.post(
        "/speak",
        json={
            "text": f"Contact me at {raw_email} or {raw_phone}",
            "provider": "elevenlabs",
            "voice_id": "test-voice-id",
        },
    )
    await provider_http.aclose()

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("audio/mpeg")
    assert response.content == b"fake-mp3"
    assert captured["url"].endswith("/test-voice-id/stream?output_format=mp3_44100_128")
    assert "eleven_turbo_v2_5" in captured["body"]["model_id"]


@pytest.mark.asyncio
async def test_sarvam_speak_uses_bulbul_v3_and_lowercase_speaker(monkeypatch, voice_api_client):
    monkeypatch.setenv("SARVAM_API_KEY", "test-sarvam-key")
    captured = {}

    async def handler(request: httpx.Request):
        captured["json"] = json.loads(request.content)
        captured["headers"] = request.headers
        return httpx.Response(200, json={"audios": [base64.b64encode(b"fake-wav").decode()]})

    provider_http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    app.state.providers = VoiceProviders(provider_http)
    response = await voice_api_client.post(
        "/speak", json={"text": "Hello", "provider": "sarvam", "voice": "Ishita"}
    )
    await provider_http.aclose()

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("audio/wav")
    assert response.content == b"fake-wav"
    assert captured["json"] == {
        "inputs": ["Hello"],
        "target_language_code": "en-IN",
        "model": "bulbul:v3",
        "speaker": "ishita",
    }
    assert captured["headers"]["api-subscription-key"] == "test-sarvam-key"


@pytest.mark.asyncio
async def test_transcribe_posts_audio_to_groq_whisper_large_v3(monkeypatch, voice_api_client):
    monkeypatch.setenv("GROQ_API_KEY", "test-groq-key")
    captured = {}

    async def handler(request: httpx.Request):
        captured["body"] = request.content
        captured["headers"] = request.headers
        return httpx.Response(200, json={"text": "recognized words"})

    provider_http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    app.state.providers = VoiceProviders(provider_http)
    response = await voice_api_client.post(
        "/transcribe", files={"audio": ("sample.webm", b"fake-audio", "audio/webm")}
    )
    await provider_http.aclose()

    assert response.status_code == 200
    assert response.json() == {"success": True, "text": "recognized words"}
    assert b"whisper-large-v3" in captured["body"]
    assert b"sample.webm" in captured["body"]
    assert captured["headers"]["authorization"] == "Bearer test-groq-key"


def test_configured_voice_id_uses_environment_or_legacy_name_mapping(monkeypatch):
    monkeypatch.delenv("ELEVENLABS_VOICE_ID", raising=False)
    monkeypatch.setenv("ELEVENLABS_VOICE", "Lucy")
    assert configured_elevenlabs_voice() == "lcMyyd2HUfFzxdCaC4Ta"
    monkeypatch.setenv("ELEVENLABS_VOICE_ID", "explicit-voice-id")
    assert configured_elevenlabs_voice() == "explicit-voice-id"
