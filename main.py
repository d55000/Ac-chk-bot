"""
main.py
~~~~~~~
Entry point for the AC-CHK Telegram Bot.

Initialises the database, configures logging, and starts the Pyrogram
client.  Handler modules are explicitly imported so that their
``@app.on_message`` / ``@app.on_callback_query`` decorators register
on the client instance before ``app.start()`` is called.

**Important:** We use ``app.run()`` (not ``asyncio.run()``) because
Pyrogram's Dispatcher captures the event loop at ``Client.__init__()``
time.  ``asyncio.run()`` creates a *new* loop, leaving the handler-
registration tasks orphaned on the old loop so no commands ever fire.
"""

from pyrogram import idle

from bot.core.client import app
from bot.core.config import LOG_LEVEL, OWNER_ID
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

    # Fetch and display bot identity.
    me = await app.get_me()
    log.info("Bot started as @%s (ID: %s)", me.username, me.id)
    log.info("Bot is running. Press Ctrl+C to stop.")

    # Notify the owner that the bot has started.
    if OWNER_ID:
        try:
            await app.send_message(
                OWNER_ID,
                f"✅ **Bot started!**\n"
                f"🤖 **Username:** @{me.username}\n"
                f"🆔 **Bot ID:** `{me.id}`",
            )
        except Exception as exc:
            log.warning("Could not notify owner %s: %s", OWNER_ID, exc)

    # Block until a termination signal is received.
    await idle()

    await app.stop()
    log.info("Bot stopped.")


if __name__ == "__main__":
    try:
        app.run(main())
    except KeyboardInterrupt:
        log.info("Shutting down…")
