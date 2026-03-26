"""
bot/modules/proxy.py
~~~~~~~~~~~~~~~~~~~~
Thread-safe proxy loader and round-robin selector.

Proxies are loaded from a text file with lines in the format:
    host:port           (no auth)
    host:port:user:pass (with auth)

The loaded list is converted to ``requests``-compatible proxy dicts::

    {"http": "http://user:pass@host:port", "https": "http://user:pass@host:port"}
"""

from __future__ import annotations

import os
import threading
from typing import Optional

from bot.core.config import DEFAULT_THREADS, PROXY_FILE
from bot.utils.logger import setup_logger

log = setup_logger("mod.proxy")


class ProxyManager:
    """Thread-safe proxy list with round-robin selection and a
    configurable thread count."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._proxies: list[dict[str, str]] = []
        self._index = 0
        self._threads = DEFAULT_THREADS

    # ── Proxy management ───────────────────────────────────────────────

    def load_from_file(self, path: Optional[str] = None) -> int:
        """Load proxies from *path* (defaults to ``PROXY_FILE``).

        Returns the number of proxies loaded.
        """
        path = path or PROXY_FILE
        proxies: list[dict[str, str]] = []
        if not os.path.exists(path):
            log.info("Proxy file %s not found – running proxyless", path)
            with self._lock:
                self._proxies = []
                self._index = 0
            return 0
        try:
            with open(path, "r", encoding="utf-8") as fh:
                for raw in fh:
                    line = raw.strip()
                    if not line:
                        continue
                    parts = line.split(":")
                    if len(parts) == 4:
                        host, port, user, pw = parts
                        url = f"http://{user}:{pw}@{host}:{port}"
                    elif len(parts) == 2:
                        url = f"http://{line}"
                    else:
                        url = f"http://{line}"
                    proxies.append({"http": url, "https": url})
        except Exception:
            log.exception("Failed to read proxy file %s", path)
        with self._lock:
            self._proxies = proxies
            self._index = 0
        log.info("Loaded %d proxies from %s", len(proxies), path)
        return len(proxies)

    def load_from_text(self, text: str) -> int:
        """Parse proxy lines from a raw text string.

        Returns the number of proxies loaded.
        """
        proxies: list[dict[str, str]] = []
        for raw in text.splitlines():
            line = raw.strip()
            if not line:
                continue
            parts = line.split(":")
            if len(parts) == 4:
                host, port, user, pw = parts
                url = f"http://{user}:{pw}@{host}:{port}"
            elif len(parts) == 2:
                url = f"http://{line}"
            else:
                url = f"http://{line}"
            proxies.append({"http": url, "https": url})
        with self._lock:
            self._proxies = proxies
            self._index = 0
        log.info("Loaded %d proxies from text", len(proxies))
        return len(proxies)

    def save_to_file(self, text: str, path: Optional[str] = None) -> None:
        """Persist raw proxy text to *path* (defaults to ``PROXY_FILE``)."""
        path = path or PROXY_FILE
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        log.info("Saved proxy text to %s", path)

    def clear(self) -> None:
        """Remove all loaded proxies."""
        with self._lock:
            self._proxies.clear()
            self._index = 0
        log.info("Proxies cleared")

    def next(self) -> Optional[dict[str, str]]:
        """Return the next proxy dict in round-robin, or ``None``."""
        with self._lock:
            if not self._proxies:
                return None
            proxy = self._proxies[self._index % len(self._proxies)]
            self._index += 1
            return proxy

    @property
    def count(self) -> int:
        with self._lock:
            return len(self._proxies)

    # ── Thread count management ────────────────────────────────────────

    @property
    def threads(self) -> int:
        with self._lock:
            return self._threads

    @threads.setter
    def threads(self, value: int) -> None:
        value = max(1, min(value, 200))
        with self._lock:
            self._threads = value
        log.info("Thread count set to %d", value)


# Module-level singleton.
proxy_manager = ProxyManager()
