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
- ``/setproxy``         — Upload a proxies.txt file (Admin / Owner).
- ``/clearproxy``       — Remove all loaded proxies (Admin / Owner).
- ``/proxystatus``      — Show current proxy and thread info (Admin / Owner).
- ``/setthreads <n>``   — Set concurrent thread count (Admin / Owner).
- ``/pull``             — Git pull to sync the deployed repo (Owner only).
"""

import asyncio
import os

from pyrogram import Client, filters
from pyrogram.types import Message

from bot.core.client import app
from bot.core.config import OWNER_ID, PROXY_FILE, TEMP_DIR
from bot.database import db
from bot.modules.proxy import proxy_manager
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

@app.on_message(filters.command("auth") & filters.private)
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

@app.on_message(filters.command("unauth") & filters.private)
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

@app.on_message(filters.command("addadmin") & filters.private)
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

@app.on_message(filters.command("removeadmin") & filters.private)
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

@app.on_message(filters.command("cancel") & filters.private)
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

@app.on_message(filters.command("stats") & filters.private)
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
        f"🧵 Threads: **{proxy_manager.threads}**\n"
        f"🌐 Proxies loaded: **{proxy_manager.count}**\n"
    )
    await message.reply_text(text)
    log.info("/stats requested by %s", message.from_user.id)


# ── /setproxy (upload proxies.txt) ─────────────────────────────────────

@app.on_message(filters.command("setproxy") & filters.private)
async def setproxy_handler(_client: Client, message: Message) -> None:
    """Load proxies from a replied-to .txt file or prompt user to reply."""
    if not await _is_admin_or_owner(message.from_user.id):
        return

    # Check if replying to a document.
    reply = message.reply_to_message
    if not reply or not reply.document:
        await message.reply_text(
            "⚠️ **Usage:** Reply to a `.txt` proxy file with `/setproxy`\n\n"
            "**Proxy format** (one per line):\n"
            "`host:port`\n"
            "`host:port:user:pass`"
        )
        return

    doc = reply.document
    if not doc.file_name or not doc.file_name.lower().endswith(".txt"):
        await message.reply_text("⚠️ Please reply to a `.txt` file.")
        return

    # Download and load.
    tmp_path = str(TEMP_DIR / f"proxy_{message.from_user.id}.txt")
    try:
        await reply.download(file_name=tmp_path)
        with open(tmp_path, "r", encoding="utf-8") as fh:
            text = fh.read()
        # Save to the persistent proxy file location.
        proxy_manager.save_to_file(text, PROXY_FILE)
        count = proxy_manager.load_from_text(text)
        await message.reply_text(
            f"✅ **Proxies loaded:** {count}\n"
            f"🧵 **Threads:** {proxy_manager.threads}"
        )
        log.info(
            "%d proxies loaded by user %s", count, message.from_user.id
        )
    except Exception:
        log.exception("Failed to load proxies")
        await message.reply_text("❌ Failed to load proxy file.")
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass


# ── /clearproxy ────────────────────────────────────────────────────────

@app.on_message(filters.command("clearproxy") & filters.private)
async def clearproxy_handler(_client: Client, message: Message) -> None:
    """Remove all loaded proxies."""
    if not await _is_admin_or_owner(message.from_user.id):
        return

    proxy_manager.clear()
    # Also remove the saved file.
    try:
        os.remove(PROXY_FILE)
    except OSError:
        pass
    await message.reply_text("✅ All proxies cleared. Running proxyless.")
    log.info("Proxies cleared by %s", message.from_user.id)


# ── /proxystatus ───────────────────────────────────────────────────────

@app.on_message(filters.command("proxystatus") & filters.private)
async def proxystatus_handler(_client: Client, message: Message) -> None:
    """Show current proxy and thread configuration."""
    if not await _is_admin_or_owner(message.from_user.id):
        return

    count = proxy_manager.count
    threads = proxy_manager.threads
    status = "Active ✅" if count > 0 else "None ❌"
    await message.reply_text(
        f"🌐 **Proxy Status**\n\n"
        f"📋 **Loaded:** {count} proxies\n"
        f"🔌 **Status:** {status}\n"
        f"🧵 **Threads:** {threads}"
    )


# ── /setthreads ────────────────────────────────────────────────────────

@app.on_message(filters.command("setthreads") & filters.private)
async def setthreads_handler(_client: Client, message: Message) -> None:
    """Set the number of concurrent threads for checking."""
    if not await _is_admin_or_owner(message.from_user.id):
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.reply_text(
            f"⚠️ Usage: `/setthreads <number>`\n"
            f"Current: **{proxy_manager.threads}** (range: 1–200)"
        )
        return

    try:
        n = int(parts[1].strip())
    except ValueError:
        await message.reply_text("⚠️ Please provide a valid number.")
        return

    if n < 1 or n > 200:
        await message.reply_text("⚠️ Thread count must be between 1 and 200.")
        return

    proxy_manager.threads = n
    await message.reply_text(f"✅ Threads set to **{proxy_manager.threads}**")
    log.info(
        "Threads set to %d by %s", proxy_manager.threads, message.from_user.id
    )


# ── /pull (Owner only) ────────────────────────────────────────────────

# Resolve the repository root (two levels up from bot/handlers/admin.py).
_REPO_DIR = str(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)
))))


@app.on_message(filters.command("pull") & filters.private)
async def pull_handler(_client: Client, message: Message) -> None:
    """Run ``git pull`` to sync the deployed repo with the remote. Owner only."""
    if message.from_user.id != OWNER_ID:
        return

    await message.reply_text("🔄 Running `git pull`…")

    try:
        proc = await asyncio.create_subprocess_exec(
            "git", "pull",
            cwd=_REPO_DIR,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=60)
        output = stdout.decode(errors="replace").strip() if stdout else "(no output)"
        code = proc.returncode

        if code == 0:
            await message.reply_text(
                f"✅ **Pull successful**\n```\n{output}\n```"
            )
        else:
            await message.reply_text(
                f"⚠️ **Pull exited with code {code}**\n```\n{output}\n```"
            )
        log.info("/pull by %s — exit %d: %s", message.from_user.id, code, output)
    except asyncio.TimeoutError:
        await message.reply_text("❌ `git pull` timed out after 60 s.")
        log.error("/pull by %s — timed out", message.from_user.id)
    except Exception as exc:
        await message.reply_text(f"❌ Failed to run `git pull`: `{exc}`")
        log.exception("/pull failed for %s", message.from_user.id)
