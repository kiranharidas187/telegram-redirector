"""
Helper: prints the name and numeric ID of the 10 channels/groups your
Telegram account has most recently interacted with. Use this to find the
CHANNEL value for a private channel that has no public t.me/xxxx link.

Usage:
    python list_my_channels.py
"""

import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.tl.types import Channel, Chat

load_dotenv(Path(__file__).resolve().parent / ".env")

# Reuse the same .env values as telegram_tts_reader.py
API_ID = int(os.environ.get("API_ID", "0") or 0)
API_HASH = os.environ.get("API_HASH", "")

client = TelegramClient("tts_reader_session", API_ID, API_HASH)


async def main() -> None:
    if not API_ID or not API_HASH:
        raise SystemExit(
            "Set API_ID and API_HASH in .env first — get them from https://my.telegram.org/apps"
        )

    await client.start()
    print(f"{'ID':<16} {'Type':<50} Name")
    print("-" * 60)
    shown = 0
    async for dialog in client.iter_dialogs():
        entity = dialog.entity
        if isinstance(entity, Channel):
            kind = "Channel" if entity.broadcast else "Group"
        elif isinstance(entity, Chat):
            kind = "Group"
        else:
            continue

        print(f"{entity.id:<16} {kind:<10} {dialog.name}")
        shown += 1
        if shown >= 10:
            break


if __name__ == "__main__":
    asyncio.run(main())
