"""
bot/handlers/basic.py
~~~~~~~~~~~~~~~~~~~~~
Handles ``/start`` and ``/help`` commands.

These commands are available to **all** users (including unauthorized ones)
so they can learn about the bot before requesting access.
"""

from pyrogram import Client, filters
from pyrogram.types import Message

from bot.core.config import OWNER_ID
from bot.database.db import is_admin, is_authorized
from bot.utils.logger import setup_logger

log = setup_logger("handlers.basic")

_START_TEXT = (
    "👋 **Welcome to AC-CHK Bot!**\n\n"
    "This bot processes `.txt` combo files through various checking modules.\n\n"
    "**Your access level:** {role}\n\n"
    "Use /help to see available commands."
)

_HELP_TEXT = (
    "📖 **Available Commands**\n\n"
    "**Everyone:**\n"
    "  /start — Show welcome message\n"
    "  /help  — This help text\n\n"
    "**Authorized Users:**\n"
    "  Upload a `.txt` file to begin processing\n\n"
    "**Admins:**\n"
    "  /auth `<user_id>` — Authorize a user\n"
    "  /unauth `<user_id>` — Revoke a user's access\n"
    "  /cancel `<task_id>` — Cancel a running task\n"
    "  /stats — Show bot statistics\n\n"
    "**Owner only:**\n"
    "  /addadmin `<user_id>` — Promote a user to admin\n"
    "  /removeadmin `<user_id>` — Demote an admin\n"
)


async def _resolve_role(user_id: int) -> str:
    """Return a human-readable role string for the given *user_id*."""
    if user_id == OWNER_ID:
        return "👑 Owner"
    if await is_admin(user_id):
        return "🛡️ Admin"
    if await is_authorized(user_id):
        return "✅ Authorized"
    return "🚫 Unauthorized"


@Client.on_message(filters.command("start") & filters.private)
async def start_handler(_client: Client, message: Message) -> None:
    """Respond to ``/start`` with a greeting and current role."""
    role = await _resolve_role(message.from_user.id)
    await message.reply_text(_START_TEXT.format(role=role))
    log.info("/start from %s (role=%s)", message.from_user.id, role)


@Client.on_message(filters.command("help") & filters.private)
async def help_handler(_client: Client, message: Message) -> None:
    """Respond to ``/help`` with the list of commands."""
    await message.reply_text(_HELP_TEXT)
    log.info("/help from %s", message.from_user.id)
