#!/usr/bin/env python3
"""
Telegram Admin Bot — Asynchronous Data Processing Bot
======================================================

A fully asynchronous Telegram bot built with python-telegram-bot (v20+)
for administrative data processing. Supports file uploads, inline keyboard
module selection, concurrent task processing via asyncio.Semaphore,
throttled live status updates, and MarkdownV2-formatted result dispatching.

Usage:
    1. Copy ``.env.example`` to ``.env`` and fill in your bot token / admin IDs.
    2. ``pip install -r requirements.txt``
    3. ``python bot.py``
"""

from __future__ import annotations

import asyncio
import functools
import logging
import os
import sys
import tempfile
import time
from collections.abc import Callable, Coroutine
from logging.handlers import RotatingFileHandler
from typing import Any

import aiofiles
import aiohttp
from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.error import BadRequest, RetryAfter, TimedOut
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ---------------------------------------------------------------------------
# Environment & Configuration
# ---------------------------------------------------------------------------

load_dotenv()  # Load .env into os.environ

BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
if not BOT_TOKEN:
    sys.exit("ERROR: BOT_TOKEN is not set in the .env file.")

# Parse comma-separated admin IDs into a frozenset for O(1) lookups.
_raw_admin_ids = os.getenv("ADMIN_USER_IDS", "")
ADMIN_USER_IDS: frozenset[int] = frozenset(
    int(uid.strip()) for uid in _raw_admin_ids.split(",") if uid.strip().isdigit()
)
if not ADMIN_USER_IDS:
    sys.exit("ERROR: ADMIN_USER_IDS is empty or invalid in the .env file.")

# Concurrency & throttle settings
MAX_CONCURRENT_WORKERS: int = 50
STATUS_UPDATE_INTERVAL_SECS: float = 5.0
STATUS_UPDATE_INTERVAL_ITEMS: int = 50

# Temporary directory for downloaded files
TEMP_DIR: str = tempfile.mkdtemp(prefix="tgbot_")

# ---------------------------------------------------------------------------
# Logging — rotating file handler + console
# ---------------------------------------------------------------------------

logger = logging.getLogger("admin_bot")
logger.setLevel(logging.DEBUG)

# Rotating file handler: 5 MB max, keep 3 backups
_file_handler = RotatingFileHandler(
    "bot.log", maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
)
_file_handler.setLevel(logging.DEBUG)
_file_handler.setFormatter(
    logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s")
)

# Console handler
_console_handler = logging.StreamHandler(sys.stdout)
_console_handler.setLevel(logging.INFO)
_console_handler.setFormatter(
    logging.Formatter("%(asctime)s | %(levelname)-8s | %(message)s")
)

logger.addHandler(_file_handler)
logger.addHandler(_console_handler)

# ---------------------------------------------------------------------------
# Shared aiohttp session (created lazily, closed on shutdown)
# ---------------------------------------------------------------------------

_http_session: aiohttp.ClientSession | None = None


async def get_http_session() -> aiohttp.ClientSession:
    """Return (and lazily create) a global ``aiohttp.ClientSession``."""
    global _http_session  # noqa: PLW0603
    if _http_session is None or _http_session.closed:
        _http_session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30)
        )
    return _http_session


async def close_http_session() -> None:
    """Gracefully close the shared HTTP session."""
    global _http_session  # noqa: PLW0603
    if _http_session and not _http_session.closed:
        await _http_session.close()
        _http_session = None
        logger.info("aiohttp session closed.")

# ---------------------------------------------------------------------------
# Admin-only access decorator
# ---------------------------------------------------------------------------


def admin_only(func):
    """Decorator that silently drops updates from non-admin users."""

    @functools.wraps(func)
    async def wrapper(
        update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs
    ):
        user_id = update.effective_user.id if update.effective_user else None
        if user_id not in ADMIN_USER_IDS:
            logger.warning("Unauthorized access attempt from user_id=%s", user_id)
            return  # Silently ignore
        return await func(update, context, *args, **kwargs)

    return wrapper

# ---------------------------------------------------------------------------
# MarkdownV2 helpers
# ---------------------------------------------------------------------------

# Characters that must be escaped in MarkdownV2 text
_MD2_ESCAPE_CHARS = r"_*[]()~`>#+-=|{}.!\\"


def _escape_md2(text: str) -> str:
    """Escape special characters for Telegram MarkdownV2."""
    result: list[str] = []
    for ch in text:
        if ch in _MD2_ESCAPE_CHARS:
            result.append("\\")
        result.append(ch)
    return "".join(result)

# ---------------------------------------------------------------------------
# Processing modules (async replacements for CR.py / Hd.py logic)
# ---------------------------------------------------------------------------


async def _process_module_a(line: str, session: aiohttp.ClientSession) -> dict[str, Any]:
    """
    Module A — Generic processing stub.

    In production this would perform the real API flow (e.g. Crunchyroll).
    Returns a dict with ``success`` (bool) and optional ``data`` payload.
    """
    parts = line.strip().split(":", 1)
    if len(parts) != 2:
        return {"success": False, "error": "Invalid format"}

    email, password = parts

    try:
        # Example: non-blocking HTTP request to a placeholder endpoint
        async with session.post(
            "https://httpbin.org/post",
            json={"email": email},
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            if resp.status == 200:
                return {
                    "success": True,
                    "data": {
                        "email": email,
                        "password": password,
                        "plan": "Premium",
                        "country": "US",
                        "expiry": "N/A",
                    },
                }
            return {"success": False, "error": f"HTTP {resp.status}"}
    except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
        logger.error("Module A request failed for %s: %s", email, exc)
        return {"success": False, "error": str(exc)}


async def _process_module_b(line: str, session: aiohttp.ClientSession) -> dict[str, Any]:
    """
    Module B — Generic processing stub.

    In production this would perform the real API flow (e.g. Hidive).
    Returns a dict with ``success`` (bool) and optional ``data`` payload.
    """
    parts = line.strip().split(":", 1)
    if len(parts) != 2:
        return {"success": False, "error": "Invalid format"}

    email, password = parts

    try:
        async with session.post(
            "https://httpbin.org/post",
            json={"id": email},
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            if resp.status == 200:
                return {
                    "success": True,
                    "data": {
                        "email": email,
                        "password": password,
                        "type": "STANDARD",
                        "renewing": "YES",
                        "country": "US",
                    },
                }
            return {"success": False, "error": f"HTTP {resp.status}"}
    except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
        logger.error("Module B request failed for %s: %s", email, exc)
        return {"success": False, "error": str(exc)}


# Map callback data → processing function
# Type alias for module processing functions
ProcessFn = Callable[[str, aiohttp.ClientSession], Coroutine[Any, Any, dict[str, Any]]]

# Map callback data → (display_name, processing_function)
MODULE_MAP: dict[str, tuple[str, ProcessFn]] = {
    "module_a": ("Module A", _process_module_a),
    "module_b": ("Module B", _process_module_b),
}

# ---------------------------------------------------------------------------
# Result formatter (MarkdownV2 with box-drawing characters)
# ---------------------------------------------------------------------------


def _format_hit_md2(module_name: str, data: dict[str, str]) -> str:
    """Build a MarkdownV2-safe hit block using box-drawing characters."""
    lines = [
        f"╒══════════「✨ {module_name} ✨」",
        "",
    ]
    for key, value in data.items():
        lines.append(f"│ *{key}*: {value}")
    lines.append("")
    lines.append("╘══════════════════════")

    # Escape the whole block for MarkdownV2
    return _escape_md2("\n".join(lines))

# ---------------------------------------------------------------------------
# Core processing loop with semaphore-based concurrency
# ---------------------------------------------------------------------------


async def _run_processing(
    lines: list[str],
    module_key: str,
    chat_id: int,
    status_message_id: int,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """
    Process *lines* using the selected module with bounded concurrency.

    A single "status" message (identified by *status_message_id*) is edited
    periodically to show live progress without flooding Telegram.
    """
    module_name, process_fn = MODULE_MAP[module_key]
    session = await get_http_session()

    # Shared mutable counters (single event-loop ⇒ no lock needed)
    stats: dict[str, int] = {"processed": 0, "success": 0, "errors": 0}
    total = len(lines)
    last_edit_time: float = 0.0

    semaphore = asyncio.Semaphore(MAX_CONCURRENT_WORKERS)

    async def _update_status(*, force: bool = False) -> None:
        """Edit the status message if enough time/items have elapsed."""
        nonlocal last_edit_time

        now = time.monotonic()
        items_since = stats["processed"] % STATUS_UPDATE_INTERVAL_ITEMS

        should_update = (
            force
            or (now - last_edit_time >= STATUS_UPDATE_INTERVAL_SECS)
            or (items_since == 0 and stats["processed"] > 0)
        )
        if not should_update:
            return

        text = (
            f"⏳ *{_escape_md2(module_name)}* — Processing\\.\\.\\.\n\n"
            f"📊 Total: {_escape_md2(str(total))}\n"
            f"✅ Processed: {_escape_md2(str(stats['processed']))}\n"
            f"🎯 Success: {_escape_md2(str(stats['success']))}\n"
            f"❌ Errors: {_escape_md2(str(stats['errors']))}"
        )
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=status_message_id,
                text=text,
                parse_mode=ParseMode.MARKDOWN_V2,
            )
            last_edit_time = time.monotonic()
        except (RetryAfter, BadRequest, TimedOut):
            # Suppress expected rate-limiting and message-not-modified errors
            logger.debug("Status edit skipped (rate-limited or unchanged).")

    async def _worker(line: str) -> None:
        """Process a single line under the semaphore."""
        async with semaphore:
            result = await process_fn(line, session)

        stats["processed"] += 1

        if result.get("success"):
            stats["success"] += 1
            # Dispatch formatted hit message
            data_block = result.get("data", {})
            hit_text = _format_hit_md2(module_name, data_block)
            try:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=hit_text,
                    parse_mode=ParseMode.MARKDOWN_V2,
                )
            except Exception as send_err:
                logger.error("Failed to send hit message: %s", send_err)
        else:
            stats["errors"] += 1
            logger.debug(
                "Line failed: %s — %s",
                line.strip()[:30],
                result.get("error", "unknown"),
            )

        await _update_status()

    # Fire all workers (semaphore limits actual concurrency to 50)
    tasks = [asyncio.create_task(_worker(line)) for line in lines]
    await asyncio.gather(*tasks, return_exceptions=True)

    # Final status update
    await _update_status(force=True)

    done_text = (
        f"✅ *{_escape_md2(module_name)}* — Done\\!\n\n"
        f"📊 Total: {_escape_md2(str(total))}\n"
        f"🎯 Success: {_escape_md2(str(stats['success']))}\n"
        f"❌ Errors: {_escape_md2(str(stats['errors']))}"
    )
    try:
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=status_message_id,
            text=done_text,
            parse_mode=ParseMode.MARKDOWN_V2,
        )
    except (RetryAfter, BadRequest, TimedOut):
        logger.debug("Could not edit final status message.", exc_info=True)

    logger.info(
        "Processing complete for %s — %d/%d success.",
        module_name,
        stats["success"],
        total,
    )

# ---------------------------------------------------------------------------
# Telegram Handlers
# ---------------------------------------------------------------------------


@admin_only
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start — greet admin and explain usage."""
    await update.message.reply_text(
        "👋 *Welcome, Admin\\!*\n\n"
        "Upload a `.txt` file containing data rows "
        "\\(one per line, `email:password` format\\) "
        "and I will process them for you\\.",
        parse_mode=ParseMode.MARKDOWN_V2,
    )


@admin_only
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help — list available commands."""
    await update.message.reply_text(
        "📖 *Commands*\n\n"
        "/start — Show welcome message\n"
        "/help  — This help text\n\n"
        "Simply upload a `.txt` file to begin processing\\.",
        parse_mode=ParseMode.MARKDOWN_V2,
    )


@admin_only
async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle uploaded .txt documents — download and present module selection."""
    document = update.message.document

    # Validate file type
    if not document.file_name or not document.file_name.lower().endswith(".txt"):
        await update.message.reply_text("⚠️ Please upload a `.txt` file only.")
        return

    # Download file to a secure temp directory
    tg_file = await document.get_file()
    safe_name = os.path.basename(document.file_name)
    local_path = os.path.join(TEMP_DIR, f"{update.effective_user.id}_{safe_name}")
    await tg_file.download_to_drive(local_path)
    logger.info("File downloaded: %s (%d bytes)", local_path, document.file_size or 0)

    # Read lines asynchronously with utf-8 encoding
    async with aiofiles.open(local_path, "r", encoding="utf-8") as fh:
        raw = await fh.read()
    lines = [ln for ln in raw.splitlines() if ln.strip()]

    if not lines:
        await update.message.reply_text("⚠️ The uploaded file is empty.")
        return

    # Store lines in user_data so the callback handler can retrieve them
    context.user_data["pending_lines"] = lines
    context.user_data["pending_file"] = local_path

    # Present module selection via inline keyboard
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🅰️ Module A", callback_data="module_a"),
                InlineKeyboardButton("🅱️ Module B", callback_data="module_b"),
            ]
        ]
    )
    await update.message.reply_text(
        f"📂 Received *{_escape_md2(document.file_name)}* "
        f"with {_escape_md2(str(len(lines)))} lines\\.\n\n"
        "Select a processing module:",
        reply_markup=keyboard,
        parse_mode=ParseMode.MARKDOWN_V2,
    )


@admin_only
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle inline-keyboard button presses for module selection."""
    query = update.callback_query
    await query.answer()  # Acknowledge the callback

    module_key = query.data
    if module_key not in MODULE_MAP:
        await query.edit_message_text("❌ Unknown module selected.")
        return

    lines: list[str] | None = context.user_data.get("pending_lines")
    if not lines:
        await query.edit_message_text("⚠️ No pending file. Please upload a `.txt` file first.")
        return

    module_name, _ = MODULE_MAP[module_key]

    # Remove the inline keyboard and confirm selection
    await query.edit_message_text(
        f"🚀 Starting *{_escape_md2(module_name)}* "
        f"with {_escape_md2(str(len(lines)))} entries\\.\\.\\.",
        parse_mode=ParseMode.MARKDOWN_V2,
    )

    # Send initial status message (this will be edited with live updates)
    status_msg = await context.bot.send_message(
        chat_id=query.message.chat_id,
        text=f"⏳ *{_escape_md2(module_name)}* — Initializing\\.\\.\\.",
        parse_mode=ParseMode.MARKDOWN_V2,
    )

    # Clear pending data so re-presses don't re-trigger
    context.user_data.pop("pending_lines", None)

    # Run the processing loop in the background so the bot stays responsive.
    # Using context.application.create_task() ensures proper exception handling
    # and task tracking by the python-telegram-bot framework.
    context.application.create_task(
        _run_processing(
            lines=lines,
            module_key=module_key,
            chat_id=query.message.chat_id,
            status_message_id=status_msg.message_id,
            context=context,
        ),
        update=update,
    )

# ---------------------------------------------------------------------------
# Graceful Shutdown
# ---------------------------------------------------------------------------


async def _shutdown(application: Application) -> None:
    """Clean up resources on shutdown."""
    logger.info("Shutting down — closing HTTP session…")
    await close_http_session()
    logger.info("Shutdown complete.")

# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Build and run the Telegram bot application."""
    logger.info("Starting Admin Bot…")
    logger.info("Authorized admins: %s", ADMIN_USER_IDS)
    logger.info("Max concurrent workers: %d", MAX_CONCURRENT_WORKERS)

    # Build application with post-shutdown hook
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_shutdown(_shutdown)
        .build()
    )

    # Register handlers
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(
        MessageHandler(filters.Document.ALL, handle_document)
    )
    app.add_handler(CallbackQueryHandler(handle_callback))

    # python-telegram-bot handles SIGINT/SIGTERM internally for graceful shutdown.

    # Start polling (blocks until stopped)
    app.run_polling(
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES,
    )


if __name__ == "__main__":
    main()
