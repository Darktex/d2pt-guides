"""Translate a Dota2ProTracker build payload into an in-game Guide.

Design notes
------------
d2pt has no explicit "situational" flag: the site's own UI treats items
bought in >=50% of matches as core and renders lower-pick-rate items as the
situational alternatives next to them. We mirror that: each game phase gets
a CORE category (>=50% pick rate, in average-purchase-time order) and a
SITUATIONAL category (sorted by pick rate). Pick rate, win rate and average
purchase minute go into the item tooltips so the variability data d2pt
shows is visible in-game.

Game phases follow the d2pt UI bucketing by average purchase minute:
early < 12 min, mid 12-35 min, late >= 35 min.

The skill order uses d2pt's most common first-10-skill-points sequence
(hero levels 1-9 and 11), talents by pick rate at 10/15/20/25, and the
remaining points (levels 12, 13, 14, 16, 18) are completed greedily:
finish the abilities the build was already prioritizing, ultimate points
at their level gates (12/18).
"""

from __future__ import annotations

from dataclasses import dataclass

from .constants import Constants
from .d2pt import POSITION_LABELS
from .guide import CAT_STARTING, ROLE_TOKENS, Guide, ItemCategory

# Hero levels that grant a regular skill point, current patches: talents
# occupy 10/15/20/25 and there is no point at 17/19/21-24.
ABILITY_LEVELS = [1, 2, 3, 4, 5, 6, 7, 8, 9, 11, 12, 13, 14, 16, 18]
TALENT_LEVELS = [10, 15, 20, 25]

EARLY_END = 12  # minutes, same bucketing as the d2pt UI
MID_END = 35

ROLE_FOR_POSITION = {
    "pos 1": ROLE_TOKENS["core"],
    "pos 2": ROLE_TOKENS["core"],
    "pos 3": ROLE_TOKENS["offlane"],
    "pos 4": ROLE_TOKENS["support"],
    "pos 5": ROLE_TOKENS["support"],
}


@dataclass
class BuilderOptions:
    core_threshold: float = 0.5  # pick rate for an item to count as core
    situational_floor: float = 0.15  # ignore items below this pick rate
    max_situational: int = 8  # per phase
    neutrals_per_tier: int = 2


def _pct(x: float) -> str:
    return f"{round(x * 100)}%"


class GuideBuilder:
    def __init__(self, constants: Constants, options: BuilderOptions | None = None):
        self.c = constants
        self.opt = options or BuilderOptions()

    def build_guide(self, build: dict, *, source_url: str = "", patch: str = "") -> Guide:
        bd = build["build_data"]
        hero_id = build["hero_id"]
        position = build["position"]
        hero_short = self.c.hero_short_name(hero_id)
        hero_display = self.c.hero_display_name(hero_id)
        pos_label = POSITION_LABELS.get(position, position)

        guide = Guide(
            hero=hero_short,
            title=self._title(hero_display, pos_label, build),
            role=ROLE_FOR_POSITION.get(position, ""),
            gameplay_version=patch,
        )

        self._notes: list[str] = []
        self._add_items(guide, bd)
        self._add_neutrals(guide, bd)
        self._add_abilities(guide, bd)
        guide.overview = self._overview(hero_display, pos_label, build, source_url)
        if self._notes:
            guide.overview += "\n\n" + "\n".join(self._notes)
        return guide

    # --- title / overview ---------------------------------------------------

    def _title(self, hero_display: str, pos_label: str, build: dict) -> str:
        wr = _pct(build.get("win_rate", 0))
        return f"D2PT {hero_display} {pos_label} · {wr} WR"

    def _overview(self, hero_display: str, pos_label: str, build: dict, source_url: str) -> str:
        lines = [
            f"{hero_display} — {pos_label} ({build['position']})",
            "Auto-generated from Dota2ProTracker: most played build in "
            "7000+ MMR pub games (last ~8 days).",
            f"{build.get('num_matches', '?')} matches · "
            f"{_pct(build.get('win_rate', 0))} win rate",
            "",
            "Item categories: CORE items are bought in >=50% of games and "
            "listed in typical purchase order. SITUATIONAL items are the "
            "lower-frequency alternatives — hover them for pick rate, win "
            "rate and average timing before committing.",
            "Talent tooltips compare both options' pick and win rates.",
        ]
        if source_url:
            lines += ["", f"Source: {source_url}"]
        if build.get("updated_at"):
            lines += [f"Data updated: {build['updated_at'][:10]}"]
        return "\n".join(lines)

    # --- items ---------------------------------------------------------------

    def _item_name(self, item_id: int) -> str | None:
        return self.c.item_internal_name(item_id)

    def _add_items(self, guide: Guide, bd: dict) -> None:
        # Starting items: the most common complete starting inventory.
        starting = self._starting_inventory(bd)
        if starting:
            guide.item_categories.append(ItemCategory(CAT_STARTING, starting))

        # Per-item pick rates for individual starting items -> tooltips.
        for entry in bd.get("starting_items", []):
            name = self._item_name(entry["raw_item_id"])
            if name and name in starting:
                guide.item_tooltips.setdefault(
                    name, f"In {_pct(entry['pr'])} of starting inventories."
                )

        pool = self._progression_pool(bd)
        phases = [
            (f"Early Game (0-{EARLY_END} min)", lambda m: m < EARLY_END),
            (f"Mid Game ({EARLY_END}-{MID_END} min)", lambda m: EARLY_END <= m < MID_END),
            (f"Late Game ({MID_END}+ min)", lambda m: m >= MID_END),
        ]
        for label, in_phase in phases:
            entries = [e for e in pool if in_phase(e["avg_minute"])]
            core = sorted(
                (e for e in entries if e["pr"] >= self.opt.core_threshold),
                key=lambda e: e["avg_minute"],
            )
            situational = sorted(
                (
                    e
                    for e in entries
                    if self.opt.situational_floor <= e["pr"] < self.opt.core_threshold
                ),
                key=lambda e: e["pr"],
                reverse=True,
            )[: self.opt.max_situational]

            if core:
                guide.item_categories.append(
                    ItemCategory(label, [e["name"] for e in core])
                )
            if situational:
                guide.item_categories.append(
                    ItemCategory(
                        label.split(" (")[0] + " — Situational",
                        [e["name"] for e in situational],
                    )
                )
            for e in core:
                guide.item_tooltips[e["name"]] = (
                    f"CORE · bought in {_pct(e['pr'])} of matches · "
                    f"{_pct(e['win_rate'])} WR · avg {e['avg_minute']:.0f} min."
                )
            for e in situational:
                guide.item_tooltips[e["name"]] = (
                    f"SITUATIONAL · bought in {_pct(e['pr'])} of matches · "
                    f"{_pct(e['win_rate'])} WR · avg {e['avg_minute']:.0f} min."
                )

    def _starting_inventory(self, bd: dict) -> list[str]:
        inventories = bd.get("starting_items_new") or []
        if inventories:
            ids, _stats = inventories[0]
            names = [self._item_name(i) for i in ids]
            return [n for n in names if n]
        # Fallback: individually popular starting items.
        names = [
            self._item_name(e["raw_item_id"])
            for e in bd.get("starting_items", [])
            if e.get("pr", 0) >= 0.4
        ]
        return [n for n in names if n]

    def _progression_pool(self, bd: dict) -> list[dict]:
        """Merge the item-progression lists, dedup by item id (keep the
        highest-count entry), and resolve internal names."""
        merged: dict[int, dict] = {}
        for key in ("anchor_items", "anchor_items2", "items_mid_late"):
            for e in bd.get(key) or []:
                iid = e["raw_item_id"]
                if iid not in merged or e.get("count", 0) > merged[iid].get("count", 0):
                    merged[iid] = e
        pool = []
        for iid, e in merged.items():
            name = self._item_name(iid)
            if not name or e.get("avg_minute") is None:
                continue
            pool.append(
                {
                    "name": name,
                    "pr": e.get("pr", 0),
                    "win_rate": e.get("win_rate", 0),
                    "avg_minute": e["avg_minute"],
                    "count": e.get("count", 0),
                }
            )
        return pool

    def _add_neutrals(self, guide: Guide, bd: dict) -> None:
        tiers = bd.get("neutral_stats") or {}
        items: list[str] = []
        for tier in sorted(tiers, key=lambda t: int(t)):
            ranked = sorted(
                tiers[tier].values(), key=lambda e: e.get("count", 0), reverse=True
            )
            for e in ranked[: self.opt.neutrals_per_tier]:
                name = f"item_{e['shortName']}"
                items.append(name)
                guide.item_tooltips[name] = (
                    f"Tier {int(tier) + 1} neutral · picked {_pct(e.get('pick_rate', 0))} "
                    f"· {_pct(e.get('win_rate', 0))} WR."
                )
        if items:
            guide.item_categories.append(ItemCategory("Top Neutral Items", items))

    # --- abilities -----------------------------------------------------------

    def _ability_names(self, bd: dict) -> dict[int, str]:
        names = {
            a["ability_id"]: a["name"]
            for a in bd.get("abilities", [])
            if a.get("name")
        }
        return names

    def _add_abilities(self, guide: Guide, bd: dict) -> None:
        orders = bd.get("abilities_new") or []
        if not orders:
            return
        names = self._ability_names(bd)

        def name_of(aid: int) -> str | None:
            return names.get(aid) or self.c.ability_internal_name(aid)

        prefix_ids, stats = orders[0]

        # Most common first 10 skill points = hero levels 1-9 and 11.
        levels_iter = iter(ABILITY_LEVELS)
        points: dict[int, int] = {}  # ability_id -> points spent
        first_seen: dict[int, int] = {}
        for aid in prefix_ids:
            level = next(levels_iter)
            n = name_of(aid)
            if n:
                guide.ability_order[level] = n
            points[aid] = points.get(aid, 0) + 1
            first_seen.setdefault(aid, level)

        # The ability taken with the 6th point (hero level 6) is the ultimate
        # for virtually every hero; it caps at 3 points, gated at 6/12/18.
        ult = prefix_ids[5] if len(prefix_ids) >= 6 else None
        if ult is not None and points.get(ult, 0) > 3:
            ult = None  # unusual kit; treat everything as a basic ability

        remaining_levels = [lv for lv in ABILITY_LEVELS if lv not in guide.ability_order]
        priority = sorted(points, key=lambda a: (-points[a], first_seen[a]))
        # Basics never skilled in the first 10 points still get the leftovers.
        for a in bd.get("abilities", []):
            aid = a.get("ability_id")
            if (
                aid is not None
                and aid not in points
                and not a.get("isTalent")
                and not a.get("isInnate")
            ):
                priority.append(aid)
                points.setdefault(aid, 0)
        for level in remaining_levels:
            aid = self._pick_next(points, priority, ult, level)
            if aid is None:
                continue
            n = name_of(aid)
            if n:
                guide.ability_order[level] = n
            points[aid] = points.get(aid, 0) + 1

        self._add_talents(guide, bd, name_of)

        # Note the runner-up skill order so the variability isn't lost.
        if len(orders) > 1:
            alt_ids, alt_stats = orders[1]
            alt_names = [self.c.ability_display_name(name_of(a) or "") for a in alt_ids]
            self._notes.append(
                f"Alternative skill order ({_pct(alt_stats.get('pr', 0))} of games, "
                f"{_pct(alt_stats.get('win_rate', 0))} WR): "
                + ", ".join(alt_names[:6])
                + "..."
            )

    def _pick_next(
        self,
        points: dict[int, int],
        priority: list[int],
        ult: int | None,
        level: int,
    ) -> int | None:
        # Take ultimate points at their level gates first (2nd at 12+, 3rd at 18+).
        if ult is not None:
            have = points.get(ult, 0)
            if (have == 1 and level >= 12) or (have == 2 and level >= 18):
                return ult
        for aid in priority:
            cap = 3 if aid == ult else 4
            if aid != ult and points.get(aid, 0) < cap:
                return aid
        return None

    def _add_talents(self, guide: Guide, bd: dict, name_of) -> None:
        for tier in bd.get("talents") or []:
            lvl = tier.get("lvl")
            if lvl not in TALENT_LEVELS:
                continue
            left, right = tier.get("left"), tier.get("right")
            if not left and not right:
                continue
            if left and right:
                chosen, other = (
                    (right, left) if tier.get("choice") == "rt" else (left, right)
                )
                if tier.get("choice") not in ("lt", "rt"):
                    chosen, other = (
                        (left, right)
                        if left.get("pick_rate", 0) >= right.get("pick_rate", 0)
                        else (right, left)
                    )
            else:
                chosen, other = (left or right), None
            guide.ability_order[lvl] = chosen["name"]
            tip = (
                f"Picked {_pct(chosen.get('pick_rate', 0))} · "
                f"{_pct(chosen.get('win_rate', 0))} WR."
            )
            if other:
                tip += (
                    f" Alternative: {other.get('displayName', '?')} "
                    f"({_pct(other.get('pick_rate', 0))} picked, "
                    f"{_pct(other.get('win_rate', 0))} WR)."
                )
            guide.ability_tooltips[chosen["name"]] = tip
