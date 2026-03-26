# AC-CHK Bot

A **production-ready, modular Telegram Bot** built with [Pyrogram](https://docs.pyrogram.org/) for processing `.txt` combo files through pluggable checking modules. Features tiered Role-Based Access Control (RBAC), async task management with cancellation, and a dynamic inline-keyboard UI.

---

## ✨ Features

| Feature | Details |
|---|---|
| **Tiered RBAC** | Owner → Admin → Authorized User → Unauthorized (ignored) |
| **Modular Architecture** | Clean separation: core, database, handlers, utils |
| **Async I/O** | `aiofiles` + `aiosqlite` — zero blocking on the event loop |
| **Task Manager** | Up to 50 concurrent workers (`asyncio.Semaphore`), per-task cancellation |
| **Dynamic UI** | Inline keyboards for module selection, throttled status edits |
| **Containerised** | Slim Docker image with non-root user and persistent volume |

---

## 📂 Project Structure

```
project_root/
├── main.py                  # Entry point
├── .env.example             # Environment variable template
├── requirements.txt         # Python dependencies
├── Dockerfile               # Container definition
├── README.md                # This file
└── bot/
    ├── __init__.py
    ├── core/
    │   ├── __init__.py
    │   ├── config.py        # Loads .env variables
    │   └── client.py        # Pyrogram Client initialisation
    ├── database/
    │   ├── __init__.py
    │   └── db.py            # aiosqlite RBAC persistence
    ├── handlers/
    │   ├── __init__.py
    │   ├── admin.py         # /auth, /unauth, /addadmin, /stats, /cancel
    │   ├── basic.py         # /start, /help
    │   └── files.py         # Document upload & inline-keyboard logic
    └── utils/
        ├── __init__.py
        ├── logger.py        # Standard logging configuration
        └── task_manager.py  # Async task tracking & execution
```

---

## 🔐 Role-Based Access Control

| Role | How assigned | Capabilities |
|---|---|---|
| **Owner** | `OWNER_ID` in `.env` | All commands, add/remove admins |
| **Admin** | `/addadmin <id>` (Owner only) | `/auth`, `/unauth`, `/cancel`, `/stats` |
| **Authorized** | `/auth <id>` (Admin/Owner) | Upload `.txt` files, trigger processing |
| **Unauthorized** | Default | Completely ignored (except `/start` and `/help`) |

---

## 🛠️ Environment Setup

1. **Clone the repo:**
   ```bash
   git clone https://github.com/d55000/Ac-chk-bot.git
   cd Ac-chk-bot
   ```

2. **Create a `.env` file** from the template:
   ```bash
   cp .env.example .env
   ```

3. **Fill in your credentials:**
   - `API_ID` / `API_HASH` — from [my.telegram.org](https://my.telegram.org)
   - `BOT_TOKEN` — from [@BotFather](https://t.me/BotFather)
   - `OWNER_ID` — your Telegram numeric user ID

4. **Install dependencies** (for local development):
   ```bash
   pip install -r requirements.txt
   ```

5. **Run the bot:**
   ```bash
   python main.py
   ```

---

## 🐳 Docker Deployment

### Build the image

```bash
docker build -t ac-chk-bot .
```

### Run with a persistent volume

The SQLite database is stored inside `/app/data`. Mount a Docker volume to persist it across container restarts:

```bash
docker run -d \
  --name ac-chk-bot \
  --env-file .env \
  -v ac-chk-data:/app/data \
  --restart unless-stopped \
  ac-chk-bot
```

### View logs

```bash
docker logs -f ac-chk-bot
```

### Stop / Remove

```bash
docker stop ac-chk-bot
docker rm ac-chk-bot
```

---

## 📝 Commands Reference

| Command | Access | Description |
|---|---|---|
| `/start` | Everyone | Welcome message with current role |
| `/help` | Everyone | List available commands |
| `/auth <user_id>` | Admin / Owner | Authorize a user |
| `/unauth <user_id>` | Admin / Owner | Revoke user access |
| `/addadmin <user_id>` | Owner | Promote user to admin |
| `/removeadmin <user_id>` | Owner | Demote an admin |
| `/cancel <task_id>` | Admin / Owner | Cancel a running task |
| `/stats` | Admin / Owner | Show bot statistics |

---

## ⚙️ Configuration Variables

| Variable | Default | Description |
|---|---|---|
| `API_ID` | — | Telegram API ID |
| `API_HASH` | — | Telegram API Hash |
| `BOT_TOKEN` | — | Bot token from BotFather |
| `OWNER_ID` | — | Owner's numeric Telegram user ID |
| `LOG_LEVEL` | `INFO` | Python logging level |
| `MAX_WORKERS` | `50` | Max concurrent processing tasks |
| `STATUS_INTERVAL` | `5` | Seconds between status-message edits |

---

## 🧩 Adding a New Processing Module

1. Add an entry to the `MODULES` dict in `bot/handlers/files.py`:
   ```python
   MODULES["mod_newservice"] = "🆕 NewService"
   ```
2. Implement the checking logic inside the `_process_file` worker or create a dedicated module and call it from there.

---

## 📄 License

This project is provided as-is for educational purposes.
