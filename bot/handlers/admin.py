"""
bot/handlers/admin.py
~~~~~~~~~~~~~~~~~~~~~
Administrative commands for the tiered RBAC system:

- ``/auth <id>``        — Authorize a user (Admin / Owner).
- ``/unauth <id>``      — Revoke a user's access (Admin / Owner).
- ``/addadmin <id>``    — Promote a user to admin (Owner only).
- ``/removeadmin <id>`` — Demote an admin (Owner only).
- ``/cancel <task_id>`` — Cancel a running task (Admin / Owner).
- ``/stats``            — Show bot statistics (Admin / Owner).
"""

from pyrogram import Client, filters
from pyrogram.types import Message

from bot.core.config import OWNER_ID
from bot.database import db
from bot.utils.logger import setup_logger
from bot.utils.task_manager import task_manager

log = setup_logger("handlers.admin")


# ── Access-control helpers ──────────────────────────────────────────────

async def _is_admin_or_owner(user_id: int) -> bool:
    """Return ``True`` if the user is either the Owner or an admin."""
    return user_id == OWNER_ID or await db.is_admin(user_id)


def _parse_user_id(message: Message) -> int | None:
    """Extract a numeric user ID from the first command argument.

    Returns ``None`` and sends an error reply if the argument is missing
    or not a valid integer.
    """
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        return None
    try:
        return int(parts[1].strip())
    except ValueError:
        return None


# ── /auth ───────────────────────────────────────────────────────────────

@Client.on_message(filters.command("auth") & filters.private)
async def auth_handler(_client: Client, message: Message) -> None:
    """Authorize a user so they can upload and process files."""
    if not await _is_admin_or_owner(message.from_user.id):
        return  # Silently ignore unauthorized callers.

    target = _parse_user_id(message)
    if target is None:
        await message.reply_text("⚠️ Usage: `/auth <user_id>`")
        return

    if await db.authorize_user(target):
        await message.reply_text(f"✅ User `{target}` has been **authorized**.")
        log.info("User %s authorized by %s", target, message.from_user.id)
    else:
        await message.reply_text(f"ℹ️ User `{target}` is already authorized.")


# ── /unauth ─────────────────────────────────────────────────────────────

@Client.on_message(filters.command("unauth") & filters.private)
async def unauth_handler(_client: Client, message: Message) -> None:
    """Revoke a user's authorization."""
    if not await _is_admin_or_owner(message.from_user.id):
        return

    target = _parse_user_id(message)
    if target is None:
        await message.reply_text("⚠️ Usage: `/unauth <user_id>`")
        return

    if await db.unauthorize_user(target):
        await message.reply_text(
            f"🚫 User `{target}` has been **unauthorized**."
        )
        log.info("User %s unauthorized by %s", target, message.from_user.id)
    else:
        await message.reply_text(f"ℹ️ User `{target}` was not authorized.")


# ── /addadmin (Owner only) ──────────────────────────────────────────────

@Client.on_message(filters.command("addadmin") & filters.private)
async def addadmin_handler(_client: Client, message: Message) -> None:
    """Promote a user to admin. Owner only."""
    if message.from_user.id != OWNER_ID:
        return

    target = _parse_user_id(message)
    if target is None:
        await message.reply_text("⚠️ Usage: `/addadmin <user_id>`")
        return

    if await db.add_admin(target):
        # Admins are implicitly authorized as well.
        await db.authorize_user(target)
        await message.reply_text(
            f"🛡️ User `{target}` is now an **admin**."
        )
        log.info("Admin added: %s by owner %s", target, message.from_user.id)
    else:
        await message.reply_text(f"ℹ️ User `{target}` is already an admin.")


# ── /removeadmin (Owner only) ──────────────────────────────────────────

@Client.on_message(filters.command("removeadmin") & filters.private)
async def removeadmin_handler(_client: Client, message: Message) -> None:
    """Demote an admin. Owner only."""
    if message.from_user.id != OWNER_ID:
        return

    target = _parse_user_id(message)
    if target is None:
        await message.reply_text("⚠️ Usage: `/removeadmin <user_id>`")
        return

    if await db.remove_admin(target):
        await message.reply_text(
            f"✅ User `{target}` has been **demoted** from admin."
        )
        log.info(
            "Admin removed: %s by owner %s", target, message.from_user.id
        )
    else:
        await message.reply_text(f"ℹ️ User `{target}` is not an admin.")


# ── /cancel ─────────────────────────────────────────────────────────────

@Client.on_message(filters.command("cancel") & filters.private)
async def cancel_handler(_client: Client, message: Message) -> None:
    """Cancel a running task by its task_id."""
    if not await _is_admin_or_owner(message.from_user.id):
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.reply_text("⚠️ Usage: `/cancel <task_id>`")
        return

    task_id = parts[1].strip()
    if await task_manager.cancel(task_id):
        await message.reply_text(
            f"🛑 Task `{task_id}` has been **cancelled**."
        )
        log.info(
            "Task %s cancelled by %s", task_id, message.from_user.id
        )
    else:
        await message.reply_text(
            f"❌ Task `{task_id}` not found or already finished."
        )


# ── /stats ──────────────────────────────────────────────────────────────

@Client.on_message(filters.command("stats") & filters.private)
async def stats_handler(_client: Client, message: Message) -> None:
    """Show bot statistics: user counts and active tasks."""
    if not await _is_admin_or_owner(message.from_user.id):
        return

    db_stats = await db.get_stats()
    active = task_manager.active_count

    text = (
        "📊 **Bot Statistics**\n\n"
        f"👑 Owner: `{OWNER_ID}`\n"
        f"🛡️ Admins: **{db_stats['admins']}**\n"
        f"✅ Authorized users: **{db_stats['authorized']}**\n"
        f"⚙️ Active tasks: **{active}**\n"
    )
    await message.reply_text(text)
    log.info("/stats requested by %s", message.from_user.id)
