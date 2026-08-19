"""
Shared logic for reading Telegram messages aloud via TTS — used by both the
headless CLI script (telegram_tts_reader.py) and the web portal (app.py).
Nothing here reads CHANNEL/CHANNEL_VOICES from the environment: callers pass
in whatever channels/voices they've resolved for themselves (from .env or
config.json), so this module has no config format opinions of its own.
"""

import asyncio
import os
import re
from dataclasses import dataclass
from pathlib import Path

import pyttsx3
from dotenv import load_dotenv
from telethon.utils import get_peer_id

URL_PATTERN = re.compile(r"https?://\S+")
EMOJI_PATTERN = re.compile(
    "["
    "\U0001F1E0-\U0001F1FF"  # flags
    "\U0001F300-\U0001F5FF"  # symbols & pictographs
    "\U0001F600-\U0001F64F"  # emoticons
    "\U0001F680-\U0001F6FF"  # transport & map
    "\U0001F900-\U0001F9FF"  # supplemental symbols/pictographs
    "\U0001FA70-\U0001FAFF"  # symbols & pictographs extended-A
    "\U00002600-\U000026FF"  # misc symbols
    "\U00002700-\U000027BF"  # dingbats
    "\U0000FE0F"  # variation selector-16
    "\U0000200D"  # zero-width joiner
    "]+",
    flags=re.UNICODE,
)


class ChannelResolutionError(Exception):
    """Raised when a configured channel can't be resolved to a Telegram entity."""


def load_api_credentials() -> tuple[int, str]:
    """Loads API_ID/API_HASH from .env (relative to this file's directory)."""
    load_dotenv(Path(__file__).resolve().parent / ".env")
    api_id = int(os.environ.get("API_ID", "0") or 0)
    api_hash = os.environ.get("API_HASH", "")
    return api_id, api_hash


def parse_channel_entry(raw: str) -> int | str:
    # Telethon needs numeric IDs as int (not str) or it treats them as a username lookup
    raw = raw.strip()
    return int(raw) if raw.lstrip("-").isdigit() else raw


def parse_channels(raw: str) -> list[int | str]:
    """Splits a comma-separated CHANNEL value into individual entries."""
    return [parse_channel_entry(c) for c in raw.split(",") if c.strip()]


def clean_text(text: str) -> str:
    """Strips http(s) links and emojis so TTS doesn't try to read them aloud."""
    text = URL_PATTERN.sub("", text)
    text = EMOJI_PATTERN.sub("", text)
    return re.sub(r"\s+", " ", text).strip()


def list_voices() -> list[dict]:
    """Returns the system's installed TTS voices as {id, name} dicts."""
    engine = pyttsx3.init()
    return [{"id": v.id, "name": v.name} for v in engine.getProperty("voices")]


def build_voice_map(
    peer_ids: list[int], requested: list[str | None], available_voice_ids: list[str]
) -> dict[int, str | None]:
    """Maps each peer id to a voice id. requested[i] is an explicit voice id,
    or None/"" to auto-assign one from available_voice_ids by rotation."""
    voice_map: dict[int, str | None] = {}
    for i, peer_id in enumerate(peer_ids):
        req = requested[i] if i < len(requested) else None
        voice_map[peer_id] = req or available_voice_ids[i % len(available_voice_ids)]
    return voice_map


def speak(text: str, voice: str | None, rate: int, volume: float = 1.0) -> None:
    """Blocking TTS call — always run this in a worker thread, never
    directly on the asyncio event loop, or it will freeze message
    listening while it talks."""
    engine = pyttsx3.init()
    engine.setProperty("rate", rate)
    engine.setProperty("volume", volume)
    if voice:
        engine.setProperty("voice", voice)
    engine.say(text)
    engine.runAndWait()
    engine.stop()


@dataclass
class SpeechSettings:
    rate: int = 175
    volume: float = 1.0


async def tts_worker(
    queue: "asyncio.Queue[tuple[str, str | None]]", settings: SpeechSettings
) -> None:
    """Pulls queued messages one at a time and speaks them in order, so
    overlapping messages don't talk over each other. Reads settings fresh
    each time, so rate/volume changes apply to the next message without
    needing to restart this task."""
    loop = asyncio.get_running_loop()
    while True:
        text, voice = await queue.get()
        await loop.run_in_executor(None, speak, text, voice, settings.rate, settings.volume)
        queue.task_done()


def _matches_dialog(entry: int | str, entity) -> bool:
    if isinstance(entry, int):
        return abs(entry) == entity.id
    username = getattr(entity, "username", None)
    return username is not None and username.lower() == entry.lstrip("@").lower()


async def resolve_channels(client, channels: list[int | str]) -> list:
    """Resolves every entry in `channels` to its Telethon entity, warming
    the session's entity cache so both this call and the caller's own event
    handler can find it later.

    get_entity() on a bare numeric ID only checks the client's local cache —
    it never makes a network call for a raw int. A channel the account has
    never interacted with in this session won't be cached yet, so we fall
    back to iter_dialogs(), which fetches full entities (with access_hash)
    straight from the API regardless of cache state.

    Raises ChannelResolutionError naming the first entry that still can't be
    found (not a member, or a bad ID) after the dialog scan.
    """
    entities: list = [None] * len(channels)
    unresolved: list[tuple[int, int | str]] = []
    for i, ch in enumerate(channels):
        try:
            entities[i] = await client.get_entity(ch)
        except ValueError:
            unresolved.append((i, ch))

    if unresolved:
        dialog_entities = [d.entity async for d in client.iter_dialogs()]
        for i, ch in unresolved:
            match = next((e for e in dialog_entities if _matches_dialog(ch, e)), None)
            if match is None:
                raise ChannelResolutionError(str(ch))
            entities[i] = match

    return entities


def peer_ids_for(entities: list) -> list[int]:
    return [get_peer_id(e) for e in entities]
