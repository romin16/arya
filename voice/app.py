"""Voice API scaffold. Provider calls are kept in an isolated process by design."""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

app = FastAPI(title="arya-voice")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/health")
async def health():
    return {"status": "healthy", "providers": {"elevenlabs": "not_configured", "sarvam": "not_configured", "groq": "not_configured"}}


@app.post("/speak")
async def speak(payload: dict):
    return JSONResponse({"success": False, "detail": "No speech provider is configured."}, status_code=503)


@app.post("/transcribe")
async def transcribe(audio: UploadFile = File(...)):
    return JSONResponse({"success": False, "text": "", "detail": "No speech provider is configured."}, status_code=503)


@app.post("/stop")
async def stop():
    return {"success": True}


def main() -> None:
    import uvicorn

    uvicorn.run(
        "voice.app:app",
        host=os.getenv("ARYA_VOICE_HOST", "127.0.0.1"),
        port=int(os.getenv("ARYA_VOICE_PORT", "5001")),
    )


if __name__ == "__main__":
    main()
