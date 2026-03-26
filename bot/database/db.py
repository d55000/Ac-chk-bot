"""
bot/database/db.py
~~~~~~~~~~~~~~~~~~
Asynchronous SQLite-backed persistence for the tiered RBAC system.

Tables
------
- **admins** – user IDs granted admin privileges by the Owner.
- **authorized** – user IDs allowed to upload files and trigger processing.

All public helpers are ``async`` and use ``aiosqlite`` so the event loop is
never blocked.
"""

import aiosqlite

from bot.core.config import DB_PATH
from bot.utils.logger import setup_logger

log = setup_logger("db")

# ── Schema DDL ──────────────────────────────────────────────────────────
_SCHEMA = """
CREATE TABLE IF NOT EXISTS admins (
    user_id  INTEGER PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS authorized (
    user_id  INTEGER PRIMARY KEY
);
"""


async def init_db() -> None:
    """Create the database tables if they do not already exist."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(_SCHEMA)
        await db.commit()
    log.info("Database initialised at %s", DB_PATH)


# ── Admin helpers ───────────────────────────────────────────────────────

async def add_admin(user_id: int) -> bool:
    """Insert *user_id* into the admins table.

    Returns ``True`` if the row was inserted, ``False`` if already present.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute(
                "INSERT INTO admins (user_id) VALUES (?)", (user_id,)
            )
            await db.commit()
            log.info("Admin added: %s", user_id)
            return True
        except aiosqlite.IntegrityError:
            return False


async def remove_admin(user_id: int) -> bool:
    """Remove *user_id* from the admins table.

    Returns ``True`` if a row was deleted.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "DELETE FROM admins WHERE user_id = ?", (user_id,)
        )
        await db.commit()
        return cursor.rowcount > 0


async def is_admin(user_id: int) -> bool:
    """Check whether *user_id* is an admin."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT 1 FROM admins WHERE user_id = ? LIMIT 1", (user_id,)
        )
        return await cursor.fetchone() is not None


async def get_all_admins() -> list[int]:
    """Return a list of all admin user IDs."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT user_id FROM admins")
        rows = await cursor.fetchall()
        return [r[0] for r in rows]


# ── Authorized-user helpers ─────────────────────────────────────────────

async def authorize_user(user_id: int) -> bool:
    """Grant *user_id* authorization to use file-processing features.

    Returns ``True`` on success, ``False`` if already authorized.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute(
                "INSERT INTO authorized (user_id) VALUES (?)", (user_id,)
            )
            await db.commit()
            log.info("User authorized: %s", user_id)
            return True
        except aiosqlite.IntegrityError:
            return False


async def unauthorize_user(user_id: int) -> bool:
    """Revoke *user_id*'s authorization.

    Returns ``True`` if a row was deleted.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "DELETE FROM authorized WHERE user_id = ?", (user_id,)
        )
        await db.commit()
        return cursor.rowcount > 0


async def is_authorized(user_id: int) -> bool:
    """Check whether *user_id* is authorized."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT 1 FROM authorized WHERE user_id = ? LIMIT 1", (user_id,)
        )
        return await cursor.fetchone() is not None


async def get_all_authorized() -> list[int]:
    """Return a list of all authorized user IDs."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT user_id FROM authorized")
        rows = await cursor.fetchall()
        return [r[0] for r in rows]


# ── Statistics ──────────────────────────────────────────────────────────

async def get_stats() -> dict:
    """Return a dictionary with counts of admins and authorized users."""
    async with aiosqlite.connect(DB_PATH) as db:
        admin_cur = await db.execute("SELECT COUNT(*) FROM admins")
        auth_cur = await db.execute("SELECT COUNT(*) FROM authorized")
        admin_count = (await admin_cur.fetchone())[0]
        auth_count = (await auth_cur.fetchone())[0]
    return {"admins": admin_count, "authorized": auth_count}
