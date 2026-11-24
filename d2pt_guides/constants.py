"""Dota 2 constants (heroes, items, abilities) fetched from OpenDota.

Cached on disk so repeated runs don't refetch. Only stdlib is used.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from urllib.request import Request, urlopen

OPENDOTA = "https://api.opendota.com/api/constants"
VALVE_FEED = "https://www.dota2.com/datafeed"
CACHE_DIR = Path.home() / ".cache" / "d2pt-guides"
CACHE_TTL = 7 * 24 * 3600  # constants change at most once per patch

USER_AGENT = "d2pt-guides (github.com/Darktex/d2pt-guides)"


def fetch_json(url: str, cache_name: str | None = None, ttl: int = CACHE_TTL) -> dict:
    cache_file = CACHE_DIR / f"{cache_name}.json" if cache_name else None
    if cache_file and cache_file.exists():
        age = time.time() - cache_file.stat().st_mtime
        if age < ttl:
            return json.loads(cache_file.read_text(encoding="utf-8"))
    req = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if cache_file:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(data), encoding="utf-8")
    return data


def removed_items_in_notes(notes: dict) -> set[int]:
    """Item ids a Valve patch-notes payload marks as removed from the game."""
    removed = set()
    for it in notes.get("items") or []:
        texts = [n.get("note", "") for n in it.get("ability_notes") or []]
        if any("removed from the game" in t.lower() for t in texts):
            removed.add(int(it["ability_id"]))
    return removed


class Constants:
    """Lookup tables between display names, internal names and ids."""

    def __init__(self) -> None:
        # A new patch adds items and abilities, so constants cached under the
        # previous patch are thrown away instead of waiting out the TTL.
        patch = self.latest_patch()
        marker = CACHE_DIR / "constants_patch.txt"
        try:
            cached_patch = marker.read_text(encoding="utf-8").strip()
        except OSError:
            cached_patch = ""
        ttl = 0 if patch and patch != cached_patch else CACHE_TTL

        self._heroes = fetch_json(f"{OPENDOTA}/heroes", "heroes", ttl)
        self._items = fetch_json(f"{OPENDOTA}/items", "items", ttl)
        self._item_ids = fetch_json(f"{OPENDOTA}/item_ids", "item_ids", ttl)
        self._abilities = fetch_json(f"{OPENDOTA}/abilities", "abilities", ttl)
        self._ability_ids = fetch_json(f"{OPENDOTA}/ability_ids", "ability_ids", ttl)
        if patch and patch != cached_patch:
            marker.write_text(patch, encoding="utf-8")

    # --- heroes -----------------------------------------------------------
    def hero_by_id(self, hero_id: int) -> dict:
        return self._heroes[str(hero_id)]

    def hero_short_name(self, hero_id: int) -> str:
        """'npc_dota_hero_naga_siren' -> 'naga_siren'."""
        return self.hero_by_id(hero_id)["name"].removeprefix("npc_dota_hero_")

    def hero_display_name(self, hero_id: int) -> str:
        return self.hero_by_id(hero_id)["localized_name"]

    def all_heroes(self) -> dict[int, dict]:
        return {int(k): v for k, v in self._heroes.items()}

    def hero_id_by_name(self, name: str) -> int:
        """Accepts display name ('Naga Siren'), short name ('naga_siren') or
        npc name, case-insensitively."""
        needle = name.strip().lower().replace("-", " ")
        for hid, h in self._heroes.items():
            candidates = {
                h["localized_name"].lower(),
                h["name"].lower(),
                h["name"].removeprefix("npc_dota_hero_").lower(),
                h["name"].removeprefix("npc_dota_hero_").replace("_", " ").lower(),
            }
            if needle in candidates:
                return int(hid)
        raise KeyError(f"unknown hero: {name!r}")

    def hero_primary_attr(self, hero_id: int) -> str:
        """'str' | 'agi' | 'int' | 'all' (universal)."""
        return self.hero_by_id(hero_id).get("primary_attr", "all")

    def boots_items(self) -> set[str]:
        """'item_boots' plus every item built from it, transitively
        ('item_power_treads', 'item_guardian_greaves', ...)."""
        if not hasattr(self, "_boots"):
            family = {"boots"}
            changed = True
            while changed:
                changed = False
                for short, it in self._items.items():
                    if short not in family and any(
                        c in family for c in it.get("components") or []
                    ):
                        family.add(short)
                        changed = True
            self._boots = {f"item_{s}" for s in family}
        return self._boots

    def hero_is_melee(self, hero_id: int) -> bool:
        return self.hero_by_id(hero_id).get("attack_type") == "Melee"

    def latest_patch(self) -> str:
        """Name of the newest gameplay patch ('7.41e'), '' if unavailable.

        Valve's patch-notes feed knows letter patches; OpenDota's list only
        tracks majors ('7.41'), so it is just the fallback."""
        if not hasattr(self, "_patch"):
            self._patch = self._fetch_latest_patch()
        return self._patch

    def _fetch_latest_patch(self) -> str:
        try:
            notes = fetch_json(
                f"{VALVE_FEED}/patchnoteslist?language=english",
                "patchnoteslist",
                ttl=24 * 3600,
            )
            patches = notes.get("patches") or []
            if patches:
                return patches[-1].get("patch_name", "")
        except Exception:
            pass
        try:
            patches = fetch_json(f"{OPENDOTA}/patch", "patch", ttl=24 * 3600)
            return patches[-1].get("name", "") if patches else ""
        except Exception:
            return ""

    # --- items ------------------------------------------------------------
    def item_internal_name(self, item_id: int) -> str | None:
        """36 -> 'item_magic_wand'. Returns None for unknown ids and for
        items the newest patch removed from the game."""
        short = self._item_ids.get(str(item_id))
        name = f"item_{short}" if short else self._valve_item_names().get(item_id)
        if name and item_id in self.removed_item_ids():
            return None
        return name

    def _valve_item_names(self) -> dict[int, str]:
        """Valve's own item list, which is current on patch day; used for ids
        OpenDota doesn't know yet."""
        if not hasattr(self, "_valve_items"):
            self._valve_items = {}
            try:
                data = fetch_json(
                    f"{VALVE_FEED}/itemlist?language=english",
                    "valve_itemlist",
                    ttl=24 * 3600,
                )
                for it in data["result"]["data"]["itemabilities"]:
                    self._valve_items[int(it["id"])] = it["name"]
            except Exception:
                pass
        return self._valve_items

    def removed_item_ids(self) -> set[int]:
        """Items the newest patch removed (7.42: Javelin, Helm of the
        Overlord, Khanda). D2PT's data window can still contain games from
        before the patch, so these must not end up in a guide."""
        if not hasattr(self, "_removed"):
            self._removed = set()
            patch = self.latest_patch()
            # A hotfix ('7.42a') doesn't repeat its major patch's removals.
            versions = {patch, patch.rstrip("abcdefghijklmnopqrstuvwxyz")} - {""}
            for version in sorted(versions):
                try:
                    notes = fetch_json(
                        f"{VALVE_FEED}/patchnotes?version={version}&language=english",
                        f"patchnotes_{version}",
                        ttl=24 * 3600,
                    )
                except Exception:
                    continue
                self._removed |= removed_items_in_notes(notes)
        return self._removed

    def item_display_name(self, internal: str) -> str:
        short = internal.removeprefix("item_")
        entry = self._items.get(short)
        return entry.get("dname", internal) if entry else internal

    def item_cost(self, internal: str) -> int:
        short = internal.removeprefix("item_")
        entry = self._items.get(short) or {}
        return entry.get("cost") or 0

    # --- abilities ---------------------------------------------------------
    def ability_internal_name(self, ability_id: int) -> str | None:
        """5003 -> 'naga_siren_mirror_image' (or 'special_bonus_*' for talents)."""
        return self._ability_ids.get(str(ability_id))

    def ability_display_name(self, internal: str) -> str:
        entry = self._abilities.get(internal)
        return entry.get("dname", internal) if entry else internal
