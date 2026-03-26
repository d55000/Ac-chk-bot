"""
main.py
~~~~~~~
Entry point for the AC-CHK Telegram Bot.

Initialises the database, configures logging, and starts the Pyrogram
client with the auto-discovered handler plugins.
"""

import asyncio

from bot.core.client import app
from bot.core.config import LOG_LEVEL
from bot.database.db import init_db
from bot.utils.logger import setup_logger

log = setup_logger("main", level=LOG_LEVEL)


async def main() -> None:
    """Bootstrap the bot: init DB → start Pyrogram client."""
    log.info("Initialising database…")
    await init_db()

    log.info("Starting bot…")
    await app.start()
    log.info("Bot is running. Press Ctrl+C to stop.")

    # Keep the process alive until interrupted.
    await asyncio.Event().wait()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Shutting down…")
