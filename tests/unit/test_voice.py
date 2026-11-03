import base64
import json

import httpx
import pytest

from voice.app import VoiceProviders, app, configured_elevenlabs_voice, require_voice_extra
from voice.stt_filter import AudioMetrics, is_known_hallucination, load_stt_settings


def test_voice_server_names_missing_extra(monkeypatch):
    import voice.app as voice_app

    monkeypatch.setattr(
        voice_app.importlib.util,
        "find_spec",
        lambda name: None if name == "sarvamai" else object(),
    )
    with pytest.raises(RuntimeError, match=r"voice extra.*missing: sarvamai"):
        require_voice_extra()


def test_launcher_sync_installs_all_optional_service_extras():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    sync_script = (root / "scripts" / "sync.ps1").read_text(encoding="utf-8")
    launcher = (root / "deploy" / "start_all.ps1").read_text(encoding="utf-8")
    assert "--extra voice --extra device --extra observability" in sync_script
    assert "scripts\\sync.ps1" in launcher


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


def test_stt_hallucination_filter_requires_known_phrase_and_short_or_quiet_recording():
    settings = load_stt_settings()
    assert is_known_hallucination("Thanks for watching.", AudioMetrics(0.8, 0.04), settings)
    assert is_known_hallucination("you", AudioMetrics(4.0, 0.002), settings)
    assert not is_known_hallucination("you", AudioMetrics(4.0, 0.04), settings)
    assert not is_known_hallucination("real command", AudioMetrics(0.4, 0.001), settings)


@pytest.mark.asyncio
async def test_transcribe_returns_empty_for_mocked_short_clip_hallucination(
    monkeypatch, voice_api_client
):
    monkeypatch.setenv("GROQ_API_KEY", "test-groq-key")

    async def handler(request: httpx.Request):
        assert b"whisper-large-v3" in request.content
        return httpx.Response(200, json={"text": "Thank you."})

    provider_http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    app.state.providers = VoiceProviders(provider_http)
    monkeypatch.setattr("voice.app.measure_audio", lambda *args: AudioMetrics(0.5, 0.03))
    response = await voice_api_client.post(
        "/transcribe", files={"audio": ("quiet.webm", b"mock-audio", "audio/webm")}
    )
    await provider_http.aclose()

    assert response.status_code == 200
    assert response.json() == {"success": True, "text": ""}
