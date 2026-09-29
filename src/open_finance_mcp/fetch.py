"""HTTP access with a small on-disk cache and SEC fair-access rules.

SEC asks automated clients to send a User-Agent naming a contact
("Sample Company Name AdminContact@<sample company domain>.com") and to stay
under 10 requests/second; generic user agents get 403s. So the SEC agent is
required configuration, not a default, and SEC requests are spaced out.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
from pathlib import Path

import httpx

SEC_MIN_INTERVAL = 0.12  # seconds between SEC requests (< 10/s)


class ConfigError(RuntimeError):
    pass


class UpstreamError(RuntimeError):
    pass


def cache_dir() -> Path:
    base = os.environ.get("OPEN_FINANCE_MCP_CACHE") or os.path.join(
        os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache")), "open-finance-mcp"
    )
    return Path(base)


class Fetcher:
    def __init__(self, client: httpx.AsyncClient | None = None, cache: Path | None = None,
                 sec_user_agent: str | None = None):
        self._client = client or httpx.AsyncClient(timeout=30.0, follow_redirects=True)
        self._cache = cache if cache is not None else cache_dir()
        self._sec_ua = sec_user_agent if sec_user_agent is not None else os.environ.get("SEC_USER_AGENT")
        self._sec_lock = asyncio.Lock()
        self._sec_last = 0.0

    async def aclose(self) -> None:
        await self._client.aclose()

    def _cache_path(self, url: str) -> Path:
        return self._cache / (hashlib.sha256(url.encode()).hexdigest()[:32] + ".json")

    def _read_cache(self, url: str, ttl: float) -> object | None:
        path = self._cache_path(url)
        try:
            if time.time() - path.stat().st_mtime < ttl:
                return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        return None

    def _write_cache(self, url: str, payload: object) -> None:
        path = self._cache_path(url)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload), encoding="utf-8")
            os.replace(tmp, path)
        except OSError:
            pass  # the cache is an optimization; never fail a request over it

    async def sec_json(self, url: str, ttl: float) -> dict:
        if not self._sec_ua or "@" not in self._sec_ua:
            raise ConfigError(
                "SEC_USER_AGENT is not set. SEC requires a contact in the User-Agent, "
                'e.g. SEC_USER_AGENT="Your Name you@example.com".'
            )
        cached = self._read_cache(url, ttl)
        if cached is not None:
            return cached
        async with self._sec_lock:
            wait = SEC_MIN_INTERVAL - (time.monotonic() - self._sec_last)
            if wait > 0:
                await asyncio.sleep(wait)
            try:
                r = await self._client.get(url, headers={"User-Agent": self._sec_ua,
                                                         "Accept-Encoding": "gzip, deflate"})
            finally:
                self._sec_last = time.monotonic()
        if r.status_code == 404:
            raise UpstreamError(f"SEC returned 404 for {url}")
        if r.status_code != 200:
            raise UpstreamError(f"SEC returned HTTP {r.status_code} for {url}")
        payload = r.json()
        self._write_cache(url, payload)
        return payload

    async def get_json(self, url: str, ttl: float, headers: dict | None = None) -> dict:
        cached = self._read_cache(url, ttl)
        if cached is not None:
            return cached
        r = await self._client.get(url, headers=headers or {})
        if r.status_code != 200:
            raise UpstreamError(f"HTTP {r.status_code} for {url}")
        payload = r.json()
        self._write_cache(url, payload)
        return payload

    async def get_text(self, url: str, ttl: float) -> str:
        cached = self._read_cache(url, ttl)
        if isinstance(cached, str):
            return cached
        r = await self._client.get(url)
        if r.status_code != 200:
            raise UpstreamError(f"HTTP {r.status_code} for {url}")
        self._write_cache(url, r.text)
        return r.text
