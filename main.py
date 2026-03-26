"""
main.py
~~~~~~~
Entry point for the AC-CHK Telegram Bot.

Initialises the database, configures logging, and starts the Pyrogram
client.  Handler modules are explicitly imported so that their
``@app.on_message`` / ``@app.on_callback_query`` decorators register
on the client instance before ``app.start()`` is called.
"""

import asyncio

from pyrogram import idle

from bot.core.client import app
from bot.core.config import LOG_LEVEL
from bot.database.db import init_db
from bot.utils.logger import setup_logger

# ── Import handler modules to register their decorators on `app` ────────
import bot.handlers.basic   # noqa: F401  (/start, /help)
import bot.handlers.admin   # noqa: F401  (/auth, /unauth, /addadmin, …)
import bot.handlers.files   # noqa: F401  (document upload & callbacks)

log = setup_logger("main", level=LOG_LEVEL)


async def main() -> None:
    """Bootstrap the bot: init DB → start Pyrogram client."""
    log.info("Initialising database…")
    await init_db()

    log.info("Starting bot…")
    await app.start()
    log.info("Bot is running. Press Ctrl+C to stop.")

    # Block until a termination signal is received.
    await idle()

    await app.stop()
    log.info("Bot stopped.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Shutting down…")
