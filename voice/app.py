"""Voice API scaffold. Provider calls are kept in an isolated process by design."""
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
