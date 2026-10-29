"""Run with:  python -m uvicorn app:app --reload   then open http://127.0.0.1:8000

Optional: set ADMIN_TOKEN to require a token for uploading or clearing the
exception list (strongly recommended once the app is online):
    PowerShell:  $env:ADMIN_TOKEN = "choose-a-long-secret"
"""
import json
import os
import threading
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from converter import convert, convert_srt, looks_like_srt, parse_exceptions

BASE = Path(__file__).parent
STORE = BASE / "exceptions.json"          # saved list, survives restarts
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")

app = FastAPI(title="Punjabi to Roman")
_lock = threading.Lock()


def _load() -> dict:
    try:
        return json.loads(STORE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save(data: dict) -> None:
    tmp = STORE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, STORE)                # atomic: never leaves a half-written file


custom: dict = _load()


def _check_token(token: str) -> None:
    if ADMIN_TOKEN and token != ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="Wrong or missing admin token.")


class ConvertRequest(BaseModel):
    text: str = Field(max_length=2000000)
    long_vowels: bool = False
    capitalize: bool = True


class SrtRequest(BaseModel):
    content: str = Field(max_length=2_000_000)    # the .srt file's text
    long_vowels: bool = False
    capitalize: bool = True


class ExceptionsUpload(BaseModel):
    content: str = Field(max_length=1_100_000)    # the file's text
    mode: Literal["merge", "replace"] = "merge"


@app.post("/api/transliterate")
def transliterate(req: ConvertRequest):
    with _lock:
        snapshot = dict(custom)
    options = dict(long_vowels=req.long_vowels, exceptions=snapshot, capitalize=req.capitalize)
    # Subtitle text pasted into the box keeps its numbers and timestamps
    if looks_like_srt(req.text):
        return {"roman": convert_srt(req.text, **options), "srt": True}
    return {"roman": convert(req.text, **options), "srt": False}


@app.post("/api/srt")
def srt(req: SrtRequest):
    with _lock:
        snapshot = dict(custom)
    result = convert_srt(req.content, long_vowels=req.long_vowels,
                         exceptions=snapshot, capitalize=req.capitalize)
    return {"srt": result}


@app.get("/api/exceptions")
def exceptions_info():
    return {"count": len(custom), "token_required": bool(ADMIN_TOKEN)}


@app.post("/api/exceptions")
def exceptions_upload(req: ExceptionsUpload, x_admin_token: str = Header(default="")):
    _check_token(x_admin_token)
    try:
        incoming = parse_exceptions(req.content)
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err))
    with _lock:
        if req.mode == "replace":
            custom.clear()
        custom.update(incoming)
        _save(custom)
        total = len(custom)
    return {"added": len(incoming), "count": total}


@app.delete("/api/exceptions")
def exceptions_clear(x_admin_token: str = Header(default="")):
    _check_token(x_admin_token)
    with _lock:
        custom.clear()
        _save(custom)
    return {"count": 0}


@app.get("/api/exceptions/download")
def exceptions_download():
    with _lock:
        body = dict(custom)
    return Response(
        content=json.dumps(body, ensure_ascii=False, indent=2),
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="exceptions.json"'},
    )


@app.get("/")
def index():
    return FileResponse(BASE / "index.html")
