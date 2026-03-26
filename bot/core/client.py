"""
bot/core/client.py
~~~~~~~~~~~~~~~~~~
Initialises the Pyrogram :class:`Client` using configuration values from
``bot.core.config``.  Other modules import the singleton ``app`` object.

Handlers are registered via instance-level decorators (``@app.on_message``)
in each handler module, which are explicitly imported in ``main.py``.
"""

from pyrogram import Client

from bot.core.config import API_ID, API_HASH, BOT_TOKEN

# The Pyrogram Client instance used by all handlers.
app = Client(
    name="ac_chk_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    workdir="data",            # Session file stored inside the data dir
)
