"""Data model for a Dota 2 in-game hero guide and its .build serialization.

The in-game guide format is Valve KeyValues (KV1) text with root key
"guidedata", stored as ``<hero>_<unix_timestamp>.build`` under
``Steam/userdata/<accountid32>/570/remote/guides/``.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

# Built-in localization tokens for item categories. Any other string is
# rendered literally as the category title in the shop UI.
CAT_STARTING = "#DOTA_Item_Build_Starting_Items"
CAT_EARLY = "#DOTA_Item_Build_Early_Game"
CAT_CORE = "#DOTA_Item_Build_Core_Items"
CAT_LUXURY = "#DOTA_Item_Build_Luxury"

ROLE_TOKENS = {
    "core": "#DOTA_HeroGuide_Role_Core",
    "offlane": "#DOTA_HeroGuide_Role_OffLane",
    "support": "#DOTA_HeroGuide_Role_Support",
    "initiator": "#DOTA_HeroGuide_Role_Initiator",
    "jungle": "#DOTA_HeroGuide_Role_Jungle",
    "roamer": "#DOTA_HeroGuide_Role_Roamer",
}


def _kv_escape(value: str) -> str:
    # KV1 quoted strings accept raw newlines; only double quotes and
    # backslashes need escaping.
    return value.replace("\\", "\\\\").replace('"', '\\"')


@dataclass
class ItemCategory:
    """One column in the guide's item panel."""

    title: str  # localization token (starts with '#') or literal display text
    items: list[str] = field(default_factory=list)  # internal names, e.g. item_magic_wand


@dataclass
class Guide:
    hero: str  # internal name minus 'npc_dota_hero_', e.g. 'naga_siren'
    title: str
    overview: str = ""
    role: str = ""  # one of ROLE_TOKENS values, or ""
    gameplay_version: str = ""
    item_categories: list[ItemCategory] = field(default_factory=list)
    # hero level -> ability internal name (talents are special_bonus_* names)
    ability_order: dict[int, str] = field(default_factory=dict)
    item_tooltips: dict[str, str] = field(default_factory=dict)
    ability_tooltips: dict[str, str] = field(default_factory=dict)
    timestamp: int = 0  # creation time; also used in the filename

    def filename(self) -> str:
        ts = self.timestamp or int(time.time())
        return f"{self.hero}_{ts}.build"

    def render(self) -> str:
        ts = self.timestamp or int(time.time())
        out: list[str] = []
        w = out.append

        def kv(indent: int, key: str, value: str) -> None:
            w("\t" * indent + f'"{_kv_escape(key)}"\t\t"{_kv_escape(value)}"')

        w('"guidedata"')
        w("{")
        kv(1, "Hero", self.hero)
        kv(1, "Title", self.title)
        if self.role:
            kv(1, "Role", self.role)
        kv(1, "GameplayVersion", self.gameplay_version)
        kv(1, "Overview", self.overview)
        kv(1, "GuideRevision", "1")
        kv(1, "AssociatedWorkshopItemID", "0x0000000000000000")
        kv(1, "OriginalCreatorID", "0x0000000000000000")
        kv(1, "GuideFormatVersion", "2")
        kv(1, "TimeUpdated", f"0x{ts:016X}")
        kv(1, "TimePublished", "0x0000000000000000")

        w('\t"ItemBuild"')
        w("\t{")
        w('\t\t"Items"')
        w("\t\t{")
        for cat in self.item_categories:
            w(f'\t\t\t"{_kv_escape(cat.title)}"')
            w("\t\t\t{")
            for item in cat.items:
                kv(4, "item", item)
            w("\t\t\t}")
        w("\t\t}")
        w('\t\t"ItemTooltips"')
        w("\t\t{")
        for item, tip in self.item_tooltips.items():
            kv(3, item, tip)
        w("\t\t}")
        w("\t}")

        w('\t"AbilityBuild"')
        w("\t{")
        w('\t\t"AbilityOrder"')
        w("\t\t{")
        for level in sorted(self.ability_order):
            kv(3, str(level), self.ability_order[level])
        w("\t\t}")
        w('\t\t"AbilityTooltips"')
        w("\t\t{")
        for ability, tip in self.ability_tooltips.items():
            kv(3, ability, tip)
        w("\t\t}")
        w("\t}")
        w("}")
        w("")
        return "\n".join(out)
