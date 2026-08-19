"""
Telegram Channel TTS Reader
----------------------------
Listens for new messages posted in one or more Telegram channels and reads
them aloud in real time using text-to-speech. When listening to more than
one channel, each channel gets its own TTS voice and messages are prefixed
with the channel name, so you can tell them apart by ear.

This is the headless/CLI path (good for systemd, or running from a
terminal). For interactive setup — Telegram login, picking channels, and
assigning voices from a browser — run the web portal instead: `python app.py`.

Why this needs your personal account (not a bot):
Telegram's Bot API can only see messages in channels where a bot has been
added as admin. To listen to a channel you're merely subscribed to (like a
news channel), the script logs in as your own account using Telegram's
Client API (MTProto), via the Telethon library.

--------------------------------------------------------------------------
SETUP
--------------------------------------------------------------------------
1. Get API credentials (free, takes 2 minutes):
   - Go to https://my.telegram.org/apps
   - Log in with your phone number
   - Create an app (any name/platform is fine)
   - Copy the "api_id" and "api_hash" values into the CONFIG section below

2. Install dependencies:
   pip install -r requirements.txt

   On Linux, pyttsx3 also needs a speech engine installed:
   sudo apt install espeak

3. Copy .env.example to .env and fill in API_ID, API_HASH, and CHANNEL.

4. Run it:
   python telegram_tts_reader.py

   The very first run will ask for your phone number and the login code
   Telegram sends you (same as logging into Telegram Desktop/Web). After
   that, it saves a session file so you won't be asked again.

--------------------------------------------------------------------------
FINDING THE RIGHT VALUE FOR "CHANNEL"
--------------------------------------------------------------------------
- Public channel (has a t.me/xxxx link): use just "xxxx"
- Private channel you're already a member of: use its numeric ID.
  Run list_my_channels.py (included alongside this script) to print the
  IDs and names of every channel/group your account is in.
- To listen to more than one channel, list them separated by commas, e.g.
  CHANNEL=xxxx,-100123456789
--------------------------------------------------------------------------
"""

import asyncio
import os

from telethon import TelegramClient, events

import reader_core

API_ID, API_HASH = reader_core.load_api_credentials()
# CHANNEL accepts one value or a comma-separated list to listen to several channels at once
CHANNELS = reader_core.parse_channels(os.environ.get("CHANNEL", ""))
# Optional: comma-separated voice names/ids, positionally matched to CHANNEL.
# Leave an entry blank to auto-assign a voice for that channel instead.
_channel_voices_raw = [v.strip() for v in os.environ.get("CHANNEL_VOICES", "").split(",")]
ANNOUNCE_SENDER = os.environ.get("ANNOUNCE_SENDER", "false").strip().lower() == "true"

client = TelegramClient("tts_reader_session", API_ID, API_HASH)
message_queue: asyncio.Queue[tuple[str, str | None]] = asyncio.Queue()
speech_settings = reader_core.SpeechSettings(rate=int(os.environ.get("SPEECH_RATE", 175)))
# Filled in by resolve_channels() before the client starts listening
channel_voices: dict[int, str | None] = {}


async def resolve_channels() -> None:
    """Resolves CHANNELS to entities and builds channel_voices (only
    meaningful with more than one channel — with a single channel it's left
    empty so playback uses the system default voice, unchanged from before)."""
    try:
        entities = await reader_core.resolve_channels(client, CHANNELS)
    except reader_core.ChannelResolutionError as e:
        raise SystemExit(
            f"Could not resolve CHANNEL entry '{e}' — it's not in your account's "
            "dialogs. Double-check the value in .env (run list_my_channels.py to "
            "list valid channels/IDs)."
        ) from e

    if len(CHANNELS) > 1:
        peer_ids = reader_core.peer_ids_for(entities)
        available = [v["id"] for v in reader_core.list_voices()]
        channel_voices.update(
            reader_core.build_voice_map(peer_ids, _channel_voices_raw, available)
        )


@client.on(events.NewMessage(chats=CHANNELS))
async def handler(event) -> None:
    text = event.raw_text
    if not text:
        return  # skip pure-media posts with no caption

    text = reader_core.clean_text(text)
    if not text:
        return  # nothing left to say after stripping emojis/links

    if ANNOUNCE_SENDER or len(CHANNELS) > 1:
        chat = await event.get_chat()
        text = f"New message in {chat.title}. {text}"

    voice = channel_voices.get(event.chat_id)
    print(f"[New message] {text}")
    await message_queue.put((text, voice))


async def main() -> None:
    if not API_ID or not API_HASH or not CHANNELS:
        raise SystemExit(
            "Set API_ID, API_HASH, and CHANNEL in .env first (copy .env.example to .env) — "
            "get API_ID/API_HASH from https://my.telegram.org/apps"
        )

    asyncio.create_task(reader_core.tts_worker(message_queue, speech_settings))
    await client.start()
    await resolve_channels()
    print(f"Listening for new messages in {CHANNELS}... (Ctrl+C to stop)")
    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
