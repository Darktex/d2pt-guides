"""Minimal client for the Dota2ProTracker JSON API.

Endpoints are unauthenticated but the site sits behind Cloudflare bot
protection: requests from datacenter IPs get a 403 challenge page, while
requests from residential IPs with browser-like headers work. Run this
from your own machine (which is where your Steam folder lives anyway).

Data window: last ~8 days of 7000+ MMR pub games, per hero and position.
"""

from __future__ import annotations

import json
import time
import urllib.error
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen

BASE = "https://dota2protracker.com"

# A plain browser UA + Referer is what community d2pt scrapers use.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Referer": "https://dota2protracker.com/",
    "Accept": "application/json",
}

CACHE_DIR = Path.home() / ".cache" / "d2pt-guides"
CACHE_TTL = 30 * 60  # d2pt data updates continuously; be polite

POSITIONS = ["pos 1", "pos 2", "pos 3", "pos 4", "pos 5"]
POSITION_LABELS = {
    "pos 1": "Carry",
    "pos 2": "Mid",
    "pos 3": "Offlane",
    "pos 4": "Soft Support",
    "pos 5": "Hard Support",
}


class CloudflareBlocked(RuntimeError):
    pass


class D2PTClient:
    def __init__(self, cache_ttl: int = CACHE_TTL, delay: float = 1.0) -> None:
        self.cache_ttl = cache_ttl
        self.delay = delay  # seconds between uncached requests
        self._last_request = 0.0

    def _get(self, path: str, cache_name: str):
        cache_file = CACHE_DIR / "d2pt" / f"{cache_name}.json"
        if cache_file.exists() and time.time() - cache_file.stat().st_mtime < self.cache_ttl:
            return json.loads(cache_file.read_text(encoding="utf-8"))

        wait = self.delay - (time.time() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        req = Request(f"{BASE}{path}", headers=HEADERS)
        try:
            with urlopen(req, timeout=30) as resp:
                body = resp.read().decode("utf-8")
        except urllib.error.HTTPError as err:
            if err.code == 403:
                raise CloudflareBlocked(
                    "dota2protracker.com returned 403 (Cloudflare bot challenge). "
                    "This usually happens on datacenter/VPN IPs. Run this script "
                    "from a normal home connection, or retry later."
                ) from err
            raise
        finally:
            self._last_request = time.time()

        data = json.loads(body)
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(body, encoding="utf-8")
        return data

    def heroes_list(self) -> list[dict]:
        """Hero roster with per-position match counts and winrates."""
        return self._get("/api/heroes/list", "heroes_list")

    def hero_builds(self, hero_id: int, position: str) -> list[dict]:
        """MOST PLAYED BUILDS for a hero+position ('pos 1'..'pos 5' or 'all')."""
        pos_slug = position.replace(" ", "")
        return self._get(
            f"/api/hero/{hero_id}/builds?position={quote(position)}",
            f"builds_{hero_id}_{pos_slug}",
        )

    def pro_builds(self, hero_id: int) -> list[dict]:
        """Builds aggregated from tournament games (may be empty)."""
        return self._get(f"/api/hero/{hero_id}/pro-builds", f"pro_builds_{hero_id}")
