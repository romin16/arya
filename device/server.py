"""Authenticated local device API scaffold; GUI actions must use SerialDesktopQueue."""
import hmac
import os
from fastapi import FastAPI, Header, HTTPException
from device.queue import SerialDesktopQueue

app = FastAPI(title="arya-device")
queue = SerialDesktopQueue()


def require_token(authorization: str | None):
    expected = os.getenv("DEVICE_TOKEN", "")
    actual = authorization.removeprefix("Bearer ") if authorization else ""
    if not expected or not hmac.compare_digest(actual, expected):
        raise HTTPException(401, "Unauthorized")


@app.get("/health")
async def health(authorization: str | None = Header(default=None)):
    require_token(authorization)
    return {"status": "healthy", "spotify_playing": None}


@app.post("/panic")
async def panic(authorization: str | None = Header(default=None)):
    require_token(authorization)
    queue.panic()
    return {"cancelled": True}
