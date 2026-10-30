# ARYA V2 - Voice Pipeline Server
# Updated: /speak now returns audio bytes (stream=true) so browser plays it
#          Supports ElevenLabs and Sarvam Bulbul v3 with 16+ female voices
#          /stop endpoint kills in-progress playback
#          No external media player ever opens!

import asyncio
import json
import os
import io
import base64
from pathlib import Path
from dotenv import load_dotenv
import pyaudio
import wave
import requests
from elevenlabs.client import ElevenLabs
from sarvamai import SarvamAI
import keyboard
import time
import tempfile
import threading
from flask import Flask, request, jsonify, send_file, Response
from flask_cors import CORS

load_dotenv()


# ══════════════════════════════════════════════════════════════
# CONFIGURATION
# ══════════════════════════════════════════════════════════════
class Config:
    GROQ_API_KEY       = os.getenv("GROQ_API_KEY")
    ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
    SARVAM_AI_API_KEY  = os.getenv("SARVAM_AI_API_KEY")
    N8N_WEBHOOK_URL    = os.getenv("N8N_WEBHOOK_URL", "http://localhost:5678/webhook/arya")

    STT_PROVIDER       = os.getenv("STT_PROVIDER", "groq")
    OPENAI_API_KEY     = os.getenv("OPENAI_API_KEY", "")

    SAMPLE_RATE   = 16000
    CHANNELS      = 1
    CHUNK_SIZE    = 1024
    RECORD_SECONDS = 5

    ELEVENLABS_VOICE = os.getenv("ELEVENLABS_VOICE", "Hope")


# ══════════════════════════════════════════════════════════════
# VOICE IDs
# ══════════════════════════════════════════════════════════════
VOICE_IDS = {
    "Rachel":   "21m00Tcm4TlvDq8ikWAM",
    "Domi":     "AZnzlk1XvdvUeBnXmlld",
    "Bella":    "EXAVITQu4vr4xnSDxMaL",
    "Antoni":   "ErXwobaYiN019PkySvjV",
    "Elli":     "MF3mGyEYCl7XYWbV9V6O",
    "Josh":     "TxGEqnHWrfWFTfGW9XjX",
    "Arnold":   "VR6AewLTigWG4xSOukaG",
    "Adam":     "pNInz6obpgDQGcFmaJgB",
    "Sam":      "yoZ06aMxZJJ28mfd3POQ",
    "Hope":     "uYXf8XasLslADfZ2MB4u",   # User custom Hope voice
    "Lucy":     "lcMyyd2HUfFzxdCaC4Ta",
    "Charlotte":"XB0fDUnXU5powFXDhCwa",
    "Alice":    "Xb7hH8MSUJpSbSDYk0k2",
    "Matilda":  "XrExE9yKIg1WjnnlVkGX",
    "Freya":    "jsCqWAovK2LkecY7zXl4",
}


# ══════════════════════════════════════════════════════════════
# TTS ENGINE
# ══════════════════════════════════════════════════════════════
elevenlabs_client = ElevenLabs(api_key=Config.ELEVENLABS_API_KEY)
audio_pa = pyaudio.PyAudio()

# Global playback state so /stop can interrupt
_current_pygame_playing = False
_stop_requested = False


def get_voice_id() -> str:
    """Return voice ID from .env ELEVENLABS_VOICE_ID or name mapping."""
    vid = os.getenv("ELEVENLABS_VOICE_ID")
    if vid:
        return vid
    return VOICE_IDS.get(Config.ELEVENLABS_VOICE, VOICE_IDS["Bella"])


def generate_audio_bytes(text: str) -> bytes:
    """
    Call ElevenLabs and return raw MP3 bytes.
    Raises on error.
    """
    audio_gen = elevenlabs_client.text_to_speech.convert(
        voice_id=get_voice_id(),
        text=text,
        model_id="eleven_turbo_v2_5",   # free-tier compatible
    )
    return b"".join(audio_gen)


def play_audio_locally(audio_bytes: bytes):
    """
    Play MP3/WAV bytes locally using pygame (for the voice server CLI mode).
    Respects _stop_requested flag so /stop can interrupt.
    """
    global _current_pygame_playing, _stop_requested
    _stop_requested = False

    # Write to temp file
    tmp = os.path.join(tempfile.gettempdir(), f"arya_{int(time.time())}.mp3")
    with open(tmp, "wb") as f:
        f.write(audio_bytes)

    try:
        import pygame
        pygame.mixer.init()
        pygame.mixer.music.load(tmp)
        pygame.mixer.music.play()
        _current_pygame_playing = True

        while pygame.mixer.music.get_busy():
            if _stop_requested:
                pygame.mixer.music.stop()
                break
            time.sleep(0.05)

        pygame.mixer.music.unload()
        _current_pygame_playing = False

    except ImportError:
        try:
            from playsound import playsound
            playsound(tmp)
        except Exception:
            pass
    finally:
        _current_pygame_playing = False
        try:
            time.sleep(0.2)
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass


def stop_playback():
    """Signal pygame to stop current playback."""
    global _stop_requested
    _stop_requested = True
    try:
        import pygame
        if pygame.mixer.get_init():
            pygame.mixer.music.stop()
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════
# FLASK APP
# ══════════════════════════════════════════════════════════════
flask_app = Flask(__name__)
CORS(flask_app)



def warmup_elevenlabs():
    """
    Pre-warm ElevenLabs voices on server start.
    First API call per voice takes 2-14s (cold start on ElevenLabs servers).
    Calling once at startup means all subsequent calls are fast (140-200ms).
    Runs in background threads — does not block server startup.
    """
    voices_to_warm = list(dict.fromkeys(filter(None, [
        os.getenv("ELEVENLABS_VOICE_ID", "uYXf8XasLslADfZ2MB4u"),  # Hope / primary
        "lcMyyd2HUfFzxdCaC4Ta",                                      # Lucy
        VOICE_IDS.get(Config.ELEVENLABS_VOICE, ""),                  # .env name
    ])))

    def _warm(vid):
        try:
            print(f"\r🔥 Warming up ElevenLabs voice {vid[:12]}…", end="", flush=True)
            gen = elevenlabs_client.text_to_speech.convert(
                voice_id=vid,
                text="Hi.",
                model_id="eleven_turbo_v2_5",
            )
            b"".join(gen)
            print(f"\r✅ ElevenLabs voice {vid[:12]} ready            ")
        except Exception as e:
            print(f"\r⚠️  Warmup failed {vid[:12]}: {e}")

    for vid in voices_to_warm:
        threading.Thread(target=_warm, args=(vid,), daemon=True).start()


@flask_app.route('/speak', methods=['POST'])
def speak_endpoint():
    """
    POST body: {"text": "...", "provider": "elevenlabs"|"sarvam", "voice": "...", "stream": true|false}
    """
    data = request.json or {}
    text = data.get('text', '').strip()
    provider = data.get('provider', 'elevenlabs').lower()
    voice = data.get('voice', 'ishita').lower()  # Sarvam names are strictly lowercase

    if not text:
        return jsonify({"success": False, "error": "text required"}), 400

    want_stream  = data.get('stream', True)   # default True for browser layout
    el_voice_id  = data.get('voice_id') or get_voice_id()  # UI dropdown or .env fallback

    # ── CASE 1: SARVAM AI PROVIDER ──
    if provider == 'sarvam':
        try:
            # 🔍 DEBUG PRINTS: Check what Python sees in environment variables
            env_with_ai = os.getenv('SARVAM_AI_API_KEY')
            env_without_ai = os.getenv('SARVAM_API_KEY')
            
            print(f"🔍 DEBUG: SARVAM_AI_API_KEY value -> {env_with_ai}")
            print(f"🔍 DEBUG: SARVAM_API_KEY value -> {env_without_ai}")

            # Fallback evaluation chain
            api_key = env_without_ai or env_with_ai
            
            if not api_key:
                print("❌ CRITICAL: No Sarvam API key found under either configuration key name!")
                return jsonify({"success": False, "error": "Sarvam API key missing from environment"}), 500
                
            # Initialize with verified key string
            client = SarvamAI(api_subscription_key=api_key)
            
            response = client.text_to_speech.convert(
                text=text,
                target_language_code="en-IN",
                model="bulbul:v3",
                speaker=voice
            )
            
            # Extract base64 encoded audio safely depending on payload format response structure
            try:
                audio_base64 = response.audios[0]
            except (AttributeError, TypeError):
                audio_base64 = response.get('audios')[0]
                
            audio_bytes = base64.b64decode(audio_base64)

            if want_stream:
                # Delivers unified audio response stream back to web UI layout components
                def generate_stream():
                    yield audio_bytes

                return Response(
                    generate_stream(),
                    mimetype='audio/wav',
                    headers={
                        'Cache-Control': 'no-cache',
                        'Access-Control-Allow-Origin': '*',
                        'X-Accel-Buffering': 'no',
                    }
                )
            else:
                # Fallback to direct local server line playback thread
                threading.Thread(
                    target=play_audio_locally,
                    args=(audio_bytes,),
                    daemon=True
                ).start()
                return jsonify({"success": True, "mode": "server-playback"})

        except Exception as e:
            print(f"❌ Sarvam AI error: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    # ── CASE 2: ELEVENLABS PROVIDER ──
    else:
        if want_stream:
            try:
                def generate_stream():
                    audio_gen = elevenlabs_client.text_to_speech.convert(
                        voice_id=el_voice_id,
                        text=text,
                        model_id="eleven_turbo_v2_5",
                    )
                    for chunk in audio_gen:
                        if chunk:
                            yield chunk

                return Response(
                    generate_stream(),
                    mimetype='audio/mpeg',
                    headers={
                        'Cache-Control': 'no-cache',
                        'Access-Control-Allow-Origin': '*',
                        'X-Accel-Buffering': 'no',
                    }
                )
            except Exception as e:
                print(f"❌ ElevenLabs error: {e}")
                return jsonify({"success": False, "error": str(e)}), 500
        else:
            try:
                audio_bytes = generate_audio_bytes(text)
            except Exception as e:
                print(f"❌ ElevenLabs error: {e}")
                return jsonify({"success": False, "error": str(e)}), 500
            threading.Thread(
                target=play_audio_locally,
                args=(audio_bytes,),
                daemon=True
            ).start()
            return jsonify({"success": True, "mode": "server-playback"})


@flask_app.route('/stop', methods=['POST'])
def stop_endpoint():
    stop_playback()
    return jsonify({"success": True, "message": "Playback stopped"})


@flask_app.route('/transcribe', methods=['POST'])
def transcribe_endpoint():
    if 'audio' not in request.files:
        return jsonify({"success": False, "error": "No audio file"}), 400

    audio_file = request.files['audio']
    suffix = '.webm' if 'webm' in (audio_file.content_type or '') else '.wav'
    tmp = os.path.join(tempfile.gettempdir(), f"cmd_{int(time.time())}{suffix}")
    audio_file.save(tmp)

    try:
        with open(tmp, 'rb') as f:
            response = requests.post(
                "https://api.groq.com/openai/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {Config.GROQ_API_KEY}"},
                files={"file": (os.path.basename(tmp), f, audio_file.content_type or 'audio/webm')},
                data={"model": "whisper-large-v3", "language": "en", "response_format": "json"},
                timeout=15
            )

        if response.status_code == 200:
            text = response.json().get("text", "").strip()
            print(f"💬 Transcribed: '{text}'")
            return jsonify({"success": True, "text": text})
        else:
            print(f"❌ Groq error {response.status_code}: {response.text}")
            return jsonify({"success": False, "error": f"Groq {response.status_code}"}), 500

    except Exception as e:
        print(f"❌ Transcribe error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass


@flask_app.route('/health', methods=['GET'])
def health():
    return jsonify({
        "status": "ok",
        "service": "arya-voice",
        "version": "2.2.0",
        "tts_providers": ["elevenlabs", "sarvam"],
        "stt": Config.STT_PROVIDER,
    })


# ══════════════════════════════════════════════════════════════
# CLI VOICE SERVER LOOP
# ══════════════════════════════════════════════════════════════
class ARYAVoiceCLI:
    def __init__(self):
        self.is_listening = False
        print("🎤 ARYA Voice CLI Starting...")
        print(f"📡 n8n Webhook: {Config.N8N_WEBHOOK_URL}")
        print(f"🎙️  STT: {Config.STT_PROVIDER.upper()}")

        if Config.STT_PROVIDER == "groq" and not Config.GROQ_API_KEY:
            print("❌ GROQ_API_KEY missing in .env")
            exit(1)

    def record_audio(self) -> str:
        print("\n🎤 Recording… (SPACE to stop, auto-stops in 5s)")
        frames = []
        stream = audio_pa.open(
            format=pyaudio.paInt16, channels=Config.CHANNELS,
            rate=Config.SAMPLE_RATE, input=True,
            frames_per_buffer=Config.CHUNK_SIZE
        )
        self.is_listening = True
        start = time.time()
        while self.is_listening:
            try:
                data = stream.read(Config.CHUNK_SIZE, exception_on_overflow=False)
                frames.append(data)
                if time.time() - start > Config.RECORD_SECONDS: break
                if keyboard.is_pressed('space'): break
            except Exception as e:
                print(f"❌ Record error: {e}"); break
        stream.stop_stream(); stream.close()
        self.is_listening = False

        tmp = "temp_recording.wav"
        wf = wave.open(tmp, 'wb')
        wf.setnchannels(Config.CHANNELS)
        wf.setsampwidth(audio_pa.get_sample_size(pyaudio.paInt16))
        wf.setframerate(Config.SAMPLE_RATE)
        wf.writeframes(b''.join(frames))
        wf.close()
        print("✅ Recorded")
        return tmp

    def transcribe(self, audio_file: str) -> str:
        print("🔄 Transcribing…")
        try:
            if Config.STT_PROVIDER == "groq":
                with open(audio_file, "rb") as f:
                    r = requests.post(
                        "https://api.groq.com/openai/v1/audio/transcriptions",
                        headers={"Authorization": f"Bearer {Config.GROQ_API_KEY}"},
                        files={"file": (audio_file, f, "audio/wav")},
                        data={"model": "whisper-large-v3", "language": "en", "response_format": "json"},
                        timeout=10
                    )
                return r.json().get("text", "") if r.status_code == 200 else ""
        except Exception as e:
            print(f"❌ Transcription error: {e}")
        return ""

    def send_to_n8n(self, user_input: str) -> str:
        print("📡 Sending to n8n…")
        try:
            r = requests.post(Config.N8N_WEBHOOK_URL,
                              json={"message": user_input, "user_id": "arya_test_user"},
                              timeout=30)
            if r.status_code == 200:
                result = r.json()
                if isinstance(result, list) and result:
                    return result[0].get("output", result[0].get("response", "No response"))
                return result.get("output", result.get("response", "No response"))
        except Exception as e:
            return f"Error: {e}"
        return "Something went wrong."

    def speak(self, text: str):
        print(f"🗣️  ARYA: {text}")
        try:
            audio_bytes = generate_audio_bytes(text)
            play_audio_locally(audio_bytes)
            print("✅ Done speaking")
        except Exception as e:
            print(f"❌ TTS error: {e}")

    def run(self):
        print("\n" + "="*52)
        print("🚀 ARYA V2 Voice CLI Running!")
        print("  ENTER → record   SPACE → stop   Ctrl+C → quit")
        print("="*52 + "\n")
        try:
            while True:
                input("Press ENTER to speak… ")
                af = self.record_audio()
                text = self.transcribe(af)
                if not text: continue
                print(f"💬 You: {text}")
                response = self.send_to_n8n(text)
                self.speak(response)
                if os.path.exists(af): os.remove(af)
                print("\n" + "─"*52 + "\n")
        except KeyboardInterrupt:
            print("\n👋 Shutting down…")
            audio_pa.terminate()


if __name__ == "__main__":
    flask_thread = threading.Thread(
        target=lambda: flask_app.run(
            host="0.0.0.0", port=5001,
            debug=False, use_reloader=False
        ),
        daemon=True
    )
    flask_thread.start()

    print("🔊 Voice HTTP server running on http://localhost:5001")
    print("   POST /speak   {\"text\": \"...\", \"provider\": \"sarvam\", \"voice\": \"ishita\"}")
    print()

    cli = ARYAVoiceCLI()
    cli.run()
