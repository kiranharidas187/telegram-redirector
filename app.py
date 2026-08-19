"""
Web portal for the Telegram TTS reader — log in, pick channels, assign
voices, and listen, all from a browser. Binds to 127.0.0.1 only; there's no
portal-level login of its own, since the OS user account on this machine is
the trust boundary (this holds a live Telegram session).

Run it with: python app.py — then open http://127.0.0.1:8765

For headless/systemd use without a browser, telegram_tts_reader.py (driven
by .env) still works exactly as before; this app and that script share their
core logic via reader_core.py.
"""

import asyncio
import json
import sys
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from telethon import TelegramClient, events
from telethon.errors import SessionPasswordNeededError
from telethon.tl.types import Channel, Chat
from telethon.utils import get_peer_id

import config_store
import reader_core

STATIC_DIR = Path(__file__).resolve().parent / "static"

API_ID, API_HASH = reader_core.load_api_credentials()
client = TelegramClient("tts_reader_session", API_ID, API_HASH)

# Single-user local tool — plain module-level state, no session/cookie handling needed.
login_state = {"phone": None, "phone_code_hash": None, "needs_password": False}


@asynccontextmanager
async def lifespan(app: FastAPI):
    await client.connect()
    app.state.config = config_store.load()
    app.state.speech_settings = reader_core.SpeechSettings(
        rate=app.state.config["speech_rate"], volume=app.state.config["volume"]
    )
    app.state.message_queue = asyncio.Queue()
    app.state.channel_voices = {}
    app.state.channel_titles = {}
    app.state.listening = False
    app.state.activity_subscribers = []
    app.state.tts_task = asyncio.create_task(
        reader_core.tts_worker(app.state.message_queue, app.state.speech_settings)
    )
    try:
        yield
    finally:
        app.state.tts_task.cancel()
        await client.disconnect()


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def _broadcast_activity(event: dict) -> None:
    for queue in list(app.state.activity_subscribers):
        queue.put_nowait(event)


async def _message_handler(event) -> None:
    text = event.raw_text
    if not text:
        return  # skip pure-media posts with no caption

    text = reader_core.clean_text(text)
    if not text:
        return  # nothing left to say after stripping emojis/links

    title = app.state.channel_titles.get(event.chat_id, "Unknown channel")
    spoken_text = f"New message in {title}. {text}" if len(app.state.channel_titles) > 1 else text
    voice = app.state.channel_voices.get(event.chat_id)

    await app.state.message_queue.put((spoken_text, voice))
    _broadcast_activity(
        {
            "ts": datetime.now().strftime("%H:%M:%S"),
            "channel_id": event.chat_id,
            "channel_title": title,
            "text": text,
            "voice": voice,
        }
    )


async def _stop_listening() -> None:
    if app.state.listening:
        client.remove_event_handler(_message_handler)
        app.state.listening = False


async def _start_listening() -> None:
    await _stop_listening()

    enabled = [c for c in app.state.config["channels"] if c["enabled"] and not c["muted"]]
    if not enabled:
        raise ValueError("No channels are enabled — pick at least one to start listening.")

    channel_entries = [c["id"] for c in enabled]
    entities = await reader_core.resolve_channels(client, channel_entries)
    peer_ids = reader_core.peer_ids_for(entities)
    requested_voices = [None if c["voice"] == "auto" else c["voice"] for c in enabled]
    available = [v["id"] for v in reader_core.list_voices()]

    app.state.channel_voices = reader_core.build_voice_map(peer_ids, requested_voices, available)
    app.state.channel_titles = {pid: c["title"] for pid, c in zip(peer_ids, enabled, strict=True)}

    client.add_event_handler(_message_handler, events.NewMessage(chats=channel_entries))
    app.state.listening = True


# ---------------------------------------------------------------- frontend

@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


# -------------------------------------------------------------------- auth

class PhoneIn(BaseModel):
    phone: str


class CodeIn(BaseModel):
    code: str


class PasswordIn(BaseModel):
    password: str


@app.get("/api/auth/status")
async def auth_status() -> dict:
    if await client.is_user_authorized():
        me = await client.get_me()
        return {"status": "connected", "name": me.first_name or me.username or str(me.id)}
    if login_state["needs_password"]:
        return {"status": "awaiting_password"}
    if login_state["phone_code_hash"]:
        return {"status": "awaiting_code"}
    return {"status": "logged_out"}


@app.post("/api/auth/send-code")
async def send_code(body: PhoneIn) -> dict:
    sent = await client.send_code_request(body.phone)
    login_state["phone"] = body.phone
    login_state["phone_code_hash"] = sent.phone_code_hash
    login_state["needs_password"] = False
    return {"status": "awaiting_code"}


@app.post("/api/auth/verify-code")
async def verify_code(body: CodeIn) -> dict:
    if not login_state["phone_code_hash"]:
        raise HTTPException(400, "Enter a phone number first.")
    try:
        await client.sign_in(
            phone=login_state["phone"],
            code=body.code,
            phone_code_hash=login_state["phone_code_hash"],
        )
    except SessionPasswordNeededError:
        login_state["needs_password"] = True
        return {"status": "awaiting_password"}
    me = await client.get_me()
    return {"status": "connected", "name": me.first_name or me.username or str(me.id)}


@app.post("/api/auth/verify-password")
async def verify_password(body: PasswordIn) -> dict:
    await client.sign_in(password=body.password)
    login_state["needs_password"] = False
    me = await client.get_me()
    return {"status": "connected", "name": me.first_name or me.username or str(me.id)}


@app.post("/api/auth/logout")
async def logout() -> dict:
    await _stop_listening()
    await client.log_out()
    login_state.update(phone=None, phone_code_hash=None, needs_password=False)
    return {"status": "logged_out"}


# ----------------------------------------------------------------- dialogs

@app.get("/api/dialogs")
async def dialogs() -> list[dict]:
    if not await client.is_user_authorized():
        raise HTTPException(401, "Not logged in.")

    results = []
    async for dialog in client.iter_dialogs():
        entity = dialog.entity
        if isinstance(entity, Channel):
            kind = "channel" if entity.broadcast else "group"
        elif isinstance(entity, Chat):
            kind = "group"
        else:
            continue
        results.append(
            {
                "id": get_peer_id(entity),
                "title": dialog.name,
                "username": getattr(entity, "username", None),
                "kind": kind,
            }
        )
    return results


# ------------------------------------------------------------------ config

class ConfigIn(BaseModel):
    channels: list[dict]
    speech_rate: int
    volume: float


@app.get("/api/config")
async def get_config() -> dict:
    return app.state.config


@app.put("/api/config")
async def put_config(body: ConfigIn) -> dict:
    config = body.model_dump()
    config_store.save(config)
    app.state.config = config
    app.state.speech_settings.rate = config["speech_rate"]
    app.state.speech_settings.volume = config["volume"]
    return config


# ------------------------------------------------------------------ voices

class PreviewIn(BaseModel):
    voice: str | None = None
    text: str = "This is a preview of this voice."


@app.get("/api/voices")
async def voices() -> list[dict]:
    return reader_core.list_voices()


@app.post("/api/voices/preview")
async def preview_voice(body: PreviewIn) -> dict:
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(
        None,
        reader_core.speak,
        body.text,
        body.voice,
        app.state.speech_settings.rate,
        app.state.speech_settings.volume,
    )
    return {"ok": True}


# ---------------------------------------------------------------- listener

@app.post("/api/listener/start")
async def listener_start() -> dict:
    if not await client.is_user_authorized():
        raise HTTPException(401, "Not logged in.")
    try:
        await _start_listening()
    except reader_core.ChannelResolutionError as e:
        raise HTTPException(400, f"Could not resolve channel '{e}'.") from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {"listening": True}


@app.post("/api/listener/stop")
async def listener_stop() -> dict:
    await _stop_listening()
    return {"listening": False}


@app.get("/api/listener/status")
async def listener_status() -> dict:
    return {"listening": app.state.listening}


# ----------------------------------------------------------------- activity

@app.get("/api/activity/stream")
async def activity_stream(request: Request) -> StreamingResponse:
    queue: asyncio.Queue = asyncio.Queue()
    app.state.activity_subscribers.append(queue)

    async def event_gen():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=15)
                except TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                yield f"data: {json.dumps(item)}\n\n"
        finally:
            app.state.activity_subscribers.remove(queue)

    return StreamingResponse(event_gen(), media_type="text/event-stream")


if __name__ == "__main__":
    if not API_ID or not API_HASH:
        sys.exit(
            "Set API_ID and API_HASH in .env first (copy .env.example to .env) — "
            "get them from https://my.telegram.org/apps"
        )

    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8765)
