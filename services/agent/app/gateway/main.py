"""The gateway API and the web app, in one FastAPI process: `make serve`.

GET  /api/health                  what's up: bank, MCP, Ollama, voice
GET  /api/profiles                the demo customers
POST /api/calls                   start a call for a customer code
POST /api/calls/{id}/say          a typed turn
POST /api/calls/{id}/audio        a spoken turn (webm/wav), transcribed locally
POST /api/calls/{id}/pin          the keypad PIN, straight to the bank
POST /api/calls/{id}/code         the one-time code, straight to the bank
POST /api/calls/{id}/confirm      the caller's words at a confirmation
GET  /api/calls/{id}/transcript   the masked transcript
GET  /api/tts?text=               speech for a reply, as WAV
/                                 the web app (services/web)
"""

import asyncio
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx2
from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.chat import PROFILES
from app.config import settings
from app.gateway.calls import CallStore, Turn
from app.gateway.speech import LOW_CONFIDENCE, SpeechToText, TextToSpeech

WEB = Path(__file__).resolve().parents[3] / "web"
REPEAT = "Sorry, I didn't catch that. Could you say it again, or type it?"


@asynccontextmanager
async def lifespan(app: FastAPI) -> Any:
    app.state.http = httpx2.AsyncClient(base_url=settings.bank_api_url, timeout=15)
    app.state.calls = CallStore(settings, app.state.http)
    app.state.stt = SpeechToText(settings.whisper_model)
    app.state.tts = TextToSpeech(settings.voice_model_dir)
    yield
    await app.state.http.aclose()


app = FastAPI(title="Puffin Bank gateway", lifespan=lifespan)


class StartCall(BaseModel):
    customer_code: str


class Said(BaseModel):
    text: str = Field(min_length=1, max_length=500)


class Digits(BaseModel):
    digits: str = Field(default="", max_length=6)  # empty = cancel


def as_json(turn: Turn) -> dict[str, Any]:
    return {
        "kind": turn.kind,
        "text": turn.text,
        "ended": turn.ended,
        "handoff_reason": turn.handoff_reason,
        "demo_code": turn.demo_code,
        "trace": turn.trace,
        "heard": turn.heard,
    }


def call_or_404(request: Request, call_id: str) -> Any:
    try:
        return request.app.state.calls.get(call_id)
    except KeyError:
        raise HTTPException(404, "That call has ended or doesn't exist.") from None


@app.get("/api/health")
async def health(request: Request) -> dict[str, Any]:
    async def up(url: str) -> bool:
        try:
            async with httpx2.AsyncClient(timeout=2) as http:
                return (await http.get(url)).status_code < 500
        except Exception:
            return False

    bank, mcp, ollama = await asyncio.gather(
        up(f"{settings.bank_api_url}/health"),
        up(settings.mcp_url),
        up(f"{settings.ollama_base_url}/api/tags"),
    )
    return {
        "bank_api": bank,
        "mcp_server": mcp,
        "ollama": ollama,
        "policies": settings.policy_index_path.is_file(),
        "voice": {"stt": request.app.state.stt.available, "tts": request.app.state.tts.available},
    }


@app.get("/api/profiles")
async def profiles() -> list[dict[str, str]]:
    return [{"name": n, "customer_code": c, "pin": p, "story": s} for n, c, p, s in PROFILES]


@app.post("/api/calls")
async def start_call(body: StartCall, request: Request) -> dict[str, Any]:
    try:
        call = await request.app.state.calls.start(body.customer_code)
    except KeyError:
        raise HTTPException(404, "Unknown customer code.") from None
    except httpx2.HTTPError:
        raise HTTPException(503, "The bank API isn't answering. Is `make dev` running?") from None
    return {"call_id": call.call_id, "name": call.name, "greeting": call.transcript[0]["text"]}


@app.post("/api/calls/{call_id}/say")
async def say(call_id: str, body: Said, request: Request) -> dict[str, Any]:
    call = call_or_404(request, call_id)
    return as_json(await request.app.state.calls.say(call, body.text))


@app.post("/api/calls/{call_id}/audio")
async def audio(call_id: str, request: Request, file: UploadFile) -> dict[str, Any]:
    call = call_or_404(request, call_id)
    stt: SpeechToText = request.app.state.stt
    if not stt.available:
        raise HTTPException(503, "Speech-to-text isn't installed: run `uv sync --extra voice`.")
    suffix = Path(file.filename or "turn.webm").suffix or ".webm"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=True) as temp:
        temp.write(await file.read())
        temp.flush()
        text, confidence = await asyncio.to_thread(stt.transcribe, Path(temp.name))
    if not text or confidence < LOW_CONFIDENCE:
        return {
            "kind": "reply",
            "text": REPEAT,
            "ended": False,
            "heard": text,
            "confidence": confidence,
            "handoff_reason": None,
            "demo_code": None,
            "trace": None,
        }
    turn = await request.app.state.calls.say(call, text, heard=text)
    return as_json(turn) | {"confidence": confidence}


@app.post("/api/calls/{call_id}/pin")
async def pin(call_id: str, body: Digits, request: Request) -> dict[str, Any]:
    call = call_or_404(request, call_id)
    return as_json(await request.app.state.calls.pin(call, body.digits))


@app.post("/api/calls/{call_id}/code")
async def code(call_id: str, body: Digits, request: Request) -> dict[str, Any]:
    call = call_or_404(request, call_id)
    return as_json(await request.app.state.calls.code(call, body.digits))


@app.post("/api/calls/{call_id}/confirm")
async def confirm(call_id: str, body: Said, request: Request) -> dict[str, Any]:
    call = call_or_404(request, call_id)
    return as_json(await request.app.state.calls.confirm(call, body.text))


@app.get("/api/calls/{call_id}/transcript")
async def transcript(call_id: str, request: Request) -> list[dict[str, Any]]:
    return list(call_or_404(request, call_id).transcript)


@app.get("/api/tts")
async def tts(text: str, request: Request) -> Response:
    engine: TextToSpeech = request.app.state.tts
    if not engine.available:
        return JSONResponse({"detail": "Text-to-speech isn't installed."}, status_code=503)
    wav = await asyncio.to_thread(engine.speak, text[:600])
    return Response(wav, media_type="audio/wav")


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(WEB / "index.html")


if WEB.is_dir():
    app.mount("/", StaticFiles(directory=WEB), name="web")
