./# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A personal tool that logs into the user's own Telegram account (via Telethon, MTProto Client API — not a bot) and reads new posts aloud from one or more channels using local TTS (`pyttsx3`), in real time via an event handler. Two ways to run it, sharing the same core logic (`reader_core.py`):

- **`app.py`** — a local web portal (FastAPI + vanilla JS, no build step) for Telegram login, picking channels, assigning voices, and watching a live activity feed from a browser. This is the primary/day-to-day path. Binds to `127.0.0.1` only, no portal-level auth (the OS account is the trust boundary). Config (channels, per-channel voice/mute/forward flag, global forward targets, speech rate, volume) lives in `config.json`, a plain gitignored JSON file — no database. Optionally reposts each incoming message (as a new message, not a native Telegram forward) to one or more configured forward targets — see the "Message forwarding" architecture note below.
- **`telegram_tts_reader.py`** — the original headless CLI script, config from `.env`. Kept for systemd/no-browser use; unaffected by portal changes.

`list_my_channels.py` is a standalone helper to look up channel usernames/IDs from the terminal. No database, no test/build tooling beyond `ruff` — treat this as a small app, not a package with a real deploy pipeline.

## Credentials

`API_ID`/`API_HASH` (from `.env`, `python-dotenv`, loaded relative to the script's own directory — not cwd) are required by all three entry points. `telegram_tts_reader.py` and `list_my_channels.py` also read `CHANNEL`/`CHANNEL_VOICES`/`SPEECH_RATE`/`ANNOUNCE_SENDER` from `.env`; `app.py` ignores those and reads channels/voices/tuning from `config.json` instead (set via the browser). `.env.example` and `config.json.example` are the committed templates; `.env` and `config.json` themselves are gitignored and must never be committed.

First run (either entry point) creates `tts_reader_session.session`, a live logged-in Telegram session file. Treat it like a password — never commit it or expose its contents (also gitignored).

## Running

`python app.py` → http://127.0.0.1:8765 for the portal. `python telegram_tts_reader.py` for the headless path. The included `telegram-tts-reader.service` is a Linux systemd **user** unit wrapping the headless script for persistent deployment (documented in README) — it has placeholder paths/username that need manual edits before use on a Linux host.

## Linting

`ruff check .` (config in `ruff.toml`). Run it after edits to catch issues.

## Architecture notes

- **Shared core (`reader_core.py`)**: `clean_text`, `speak`, `tts_worker`, `resolve_channels`, and voice-assignment logic used by both entry points. Config-format-agnostic — callers resolve their own channel list/voice choices (from `.env` or `config.json`) and pass them in.
- **`speak()`** runs TTS playback via `loop.run_in_executor` fed by an `asyncio.Queue`, specifically so audio playback doesn't block the asyncio event loop and so bursts of messages play sequentially without overlapping. Preserve this pattern if touching message handling — a naive synchronous call to `pyttsx3` here would stall event processing (or, in the portal, the whole web server).
- **`resolve_channels()`**: `get_entity()` on a bare numeric ID only checks Telethon's local cache — it never hits the network for a raw int. A channel the account hasn't interacted with in this session won't be cached, so this falls back to scanning `client.iter_dialogs()` (which fetches full entities from the API regardless of cache state) for any entry that fails the fast path. Keep this fallback if touching channel resolution — dropping it reintroduces a `ValueError` crash (or, worse, a silently-never-resolves handler) for channels the account hasn't recently interacted with.
- **Portal listener lifecycle (`app.py`)**: Telethon's `events.NewMessage` handler is registered dynamically via `add_event_handler`/`remove_event_handler` (not the `@client.on` decorator) so the channel list can change at runtime without restarting the process. Changing which channels are enabled requires an explicit stop+re-add (the "Restart to apply" flow in the UI) — there's no live mutation of an already-registered filter.
- **Portal frontend (`static/`)**: intentionally vanilla HTML/CSS/JS, no bundler/npm — served directly by FastAPI's `StaticFiles`. Keep it that way; this is meant to stay a small, dependency-light local tool.
- **Message forwarding (`app.py`'s `_forward_message`)**: reuses `resolve_channels()` (not a second resolver) to resolve each enabled forward target, with a lazy success cache (`app.state.forward_entity_cache`) evicted only on a Telethon `RPCError` — no TTL, no background refresh. Unlike the source-channel list, forward-target edits and the per-channel `forward` toggle are read fresh from `app.state.config` on every message and don't touch the `NewMessage(chats=...)` filter, so they take effect immediately with no "Restart to apply" needed. Forwarding reposts via `client.send_message(target, message=event.message)` (copies text/media as a fresh message, no "Forwarded from" tag) — errors are caught per-target (`FloodWaitError`, `RPCError`, generic `Exception`) so one bad destination never blocks others or crashes the handler.
