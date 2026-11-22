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

# Endgame pickups that stay relevant in every very long game (and in Turbo,
# where late game is reached almost every match). D2PT's data window is normal
# pubs, which often end before these are bought, so they are pinned into their
# own category even when the data has nothing for them.
CAT_SUPER_LATE = "Super Late & Turbo"
SUPER_BLINKS = {
    "str": "item_overwhelming_blink",
    "agi": "item_swift_blink",
    "int": "item_arcane_blink",
}

ROLE_FOR_POSITION = {
    "pos 1": ROLE_TOKENS["core"],
    "pos 2": ROLE_TOKENS["core"],
    "pos 3": ROLE_TOKENS["offlane"],
    "pos 4": ROLE_TOKENS["support"],
    "pos 5": ROLE_TOKENS["support"],
}


@dataclass
class BuilderOptions:
    core_threshold: float = 0.5  # strict: more than half of build matches
    situational_floor: float = 0.0  # include every observed situational item by default
    max_situational: int | None = None  # no truncation by default
    neutrals_per_tier: int = 2
    late_staples: bool = True  # pin the Super Late & Turbo category


def _pct(x: float) -> str:
    return f"{round(x * 100)}%"

def _pct1(x: float) -> str:
    return f"{x * 100:.1f}%"


def _build_win_rate(build: dict) -> float:
    # Newer payloads only carry num_wins/num_matches at the top level.
    if build.get("win_rate") is not None:
        return build["win_rate"]
    matches = build.get("num_matches") or 0
    return build.get("num_wins", 0) / matches if matches else 0.0


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
        self._add_items(guide, bd, hero_id)
        self._add_neutrals(guide, bd)
        self._add_abilities(guide, bd)
        guide.overview = self._overview(hero_display, pos_label, build, source_url)
        if self._notes:
            guide.overview += "\n\n" + "\n".join(self._notes)
        return guide

    # --- title / overview ---------------------------------------------------

    def _title(self, hero_display: str, pos_label: str, build: dict) -> str:
        wr = _pct(_build_win_rate(build))
        return f"D2PT {hero_display} {pos_label} · {wr} WR"

    def _overview(self, hero_display: str, pos_label: str, build: dict, source_url: str) -> str:
        lines = [
            f"{hero_display} — {pos_label} ({build['position']})",
            "Auto-generated from Dota2ProTracker: most played build in "
            "7000+ MMR pub games (last ~8 days).",
            f"{build.get('num_matches', '?')} matches · "
            f"{_pct(_build_win_rate(build))} win rate",
            "",
            "Item categories mirror D2PT: CORE items are bought in >50% of "
            "this build's matches and ordered by average purchase time. "
            "SITUATIONAL contains every other observed item; hover for pick "
            "rate, win rate, average timing and purchase count.",
            "The first recorded skill points use D2PT order data; later points "
            "are estimated from the available popular order variants.",
            "Talent tooltips compare both options' pick and win rates.",
            "The Super Late & Turbo category pins endgame staples (BKB, "
            "Shard, Blessing, super-blink, Moon Shard) that pub data often "
            "ends too early to show.",
        ]
        if source_url:
            lines += ["", f"Source: {source_url}"]
        if build.get("updated_at"):
            lines += [f"Data updated: {build['updated_at'][:10]}"]
        return "\n".join(lines)

    # --- items ---------------------------------------------------------------

    def _item_name(self, item_id: int) -> str | None:
        return self.c.item_internal_name(item_id)

    def _add_items(self, guide: Guide, bd: dict, hero_id: int) -> None:
        # Starting items are a separate D2PT section, based on the common
        # opening inventory rather than the core-item progression.
        starting = self._starting_inventory(bd)
        if starting:
            guide.item_categories.append(ItemCategory(CAT_STARTING, starting))

        for entry in bd.get("starting_items", []):
            name = self._item_name(entry["raw_item_id"])
            if name and name in starting:
                guide.item_tooltips.setdefault(
                    name, f"In {_pct(entry['pr'])} of starting inventories."
                )

        pool = self._progression_pool(bd)
        core = sorted(
            (entry for entry in pool if entry["kind"] == "core"),
            key=lambda entry: (entry["avg_minute"], -entry["pr"], entry["name"]),
        )
        situational = sorted(
            (
                entry for entry in pool
                if entry["kind"] == "situational"
                and entry["pr"] > 0
                and entry["pr"] >= self.opt.situational_floor
            ),
            key=lambda entry: (-entry["pr"], entry["avg_minute"], entry["name"]),
        )
        if self.opt.max_situational is not None:
            situational = situational[: self.opt.max_situational]

        if core:
            guide.item_categories.append(
                ItemCategory("Core Items", [entry["name"] for entry in core])
            )
        if situational:
            guide.item_categories.append(
                ItemCategory("Situational Items", [entry["name"] for entry in situational])
            )

        for entry in core:
            tip = (
                f"CORE · pick rate {_pct1(entry['pr'])} of all build matches · "
                f"{_pct(entry['win_rate'])} WR · avg {entry['avg_minute']:.1f} min"
            )
            if entry.get("count"):
                tip += f" · {int(entry['count'])} matches with purchase"
            guide.item_tooltips[entry["name"]] = tip + "."

        for entry in situational:
            tip = f"SITUATIONAL · {self._item_pick_rate_description(entry)}"
            tip += f" · {_pct(entry['win_rate'])} WR · avg {entry['avg_minute']:.1f} min"
            if entry.get("min_minute") is not None and entry.get("max_minute") is not None:
                tip += f" ({entry['min_minute']:.0f}-{entry['max_minute']:.0f} min)"
            if entry.get("count"):
                tip += f" · {int(entry['count'])} purchases"
            guide.item_tooltips[entry["name"]] = tip + "."

        self._ensure_boots(guide, pool)
        if self.opt.late_staples:
            self._add_late_staples(guide, pool, hero_id)

    @staticmethod
    def _item_pick_rate_description(entry: dict) -> str:
        """Describe pick rate without mixing different statistical samples."""
        sample_pr = entry.get("sample_pr")
        if sample_pr is None:
            return f"pick rate {_pct1(entry['pr'])} of all build matches"
        description = f"pick rate {_pct1(sample_pr)} in this item-build sample"
        all_match_pr = entry.get("all_match_pr")
        if all_match_pr is not None:
            description += f" · {_pct1(all_match_pr)} of all build matches"
        return description


    def _ensure_boots(self, guide: Guide, pool: list[dict]) -> None:
        """Surface a boots option when the observed build usually skips boots."""
        boots = self.c.boots_items()
        if {item for category in guide.item_categories for item in category.items} & boots:
            return

        def comparable_rate(entry: dict) -> float:
            all_match_pr = entry.get("all_match_pr")
            return all_match_pr if all_match_pr is not None else entry["pr"]

        ranked = sorted(
            (entry for entry in pool if entry["name"] in boots),
            key=comparable_rate,
            reverse=True,
        )[:2]
        items = []
        for entry in ranked:
            items.append(entry["name"])
            tip = (
                "BOOTS · this build usually skips boots — "
                f"{self._item_pick_rate_description(entry)} · "
                f"{_pct(entry['win_rate'])} WR, avg {entry['avg_minute']:.1f} min."
            )
            guide.item_tooltips[entry["name"]] = tip
        if not items:
            items = ["item_boots"]
            guide.item_tooltips["item_boots"] = (
                "BOOTS · no boots at all in d2pt's data for this build — "
                "players skip them; buy for the move speed if you want it."
            )
        after_starting = bool(
            guide.item_categories and guide.item_categories[0].title == CAT_STARTING
        )
        guide.item_categories.insert(
            1 if after_starting else 0,
            ItemCategory("Boots (usually skipped)", items),
        )


    def _add_late_staples(self, guide: Guide, pool: list[dict], hero_id: int) -> None:
        """Pin the endgame staples that D2PT's normal-pub data window often
        never reaches: BKB, Aghanim's Shard/Blessing, the hero's super-blink
        upgrade(s) and a Moon Shard to consume."""
        by_name = {entry["name"]: entry for entry in pool}

        wanted = {name for name in SUPER_BLINKS.values() if name in by_name}
        attr = self.c.hero_primary_attr(hero_id)
        if attr in SUPER_BLINKS:
            wanted.add(SUPER_BLINKS[attr])
        else:
            wanted.update((SUPER_BLINKS["str"], SUPER_BLINKS["agi"]))
        if self.c.hero_is_melee(hero_id):
            wanted.add(SUPER_BLINKS["str"])
        blinks = [name for name in SUPER_BLINKS.values() if name in wanted]

        usage = {
            "item_ultimate_scepter_2": "frees the Scepter inventory slot",
            "item_moon_shard": "consume it once slots run out",
        }
        present = {item for category in guide.item_categories for item in category.items}
        items = []
        for name in [
            "item_black_king_bar",
            "item_aghanims_shard",
            *blinks,
            "item_ultimate_scepter_2",
            "item_moon_shard",
        ]:
            if name in present:
                continue
            items.append(name)
            entry = by_name.get(name)
            if entry:
                tip = (
                    f"STAPLE · {self._item_pick_rate_description(entry)} · "
                    f"{_pct(entry['win_rate'])} WR · avg {entry['avg_minute']:.1f} min."
                )
            else:
                tip = (
                    "STAPLE · no recent d2pt data (pubs in the data window "
                    "rarely go this long) — standard super-late pickup."
                )
            if name in usage:
                tip += f" {usage[name].capitalize()}."
            guide.item_tooltips[name] = tip
        if items:
            guide.item_categories.append(ItemCategory(CAT_SUPER_LATE, items))


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
        """Combine all-match progression rates with item-build sample stats.

        anchor_items/anchor_items2/items_mid_late use all selected hero-position
        matches as their denominator. anchor_item_stats uses the selected
        item-build sample and reports pick_rate in percentage units.
        """
        all_match_by_id: dict[int, dict] = {}
        for key in ("anchor_items", "anchor_items2", "items_mid_late"):
            for entry in bd.get(key) or []:
                raw_iid = entry.get("raw_item_id")
                if raw_iid is None:
                    continue
                try:
                    iid = int(raw_iid)
                    raw_pr = float(entry.get("pr", 0) or 0)
                    count = float(entry.get("count", 0) or 0)
                except (TypeError, ValueError):
                    continue
                pr = raw_pr / 100.0 if raw_pr > 1.0 else raw_pr
                candidate = {
                    "pr": max(0.0, min(pr, 1.0)),
                    "count": count,
                    "entry": entry,
                }
                previous = all_match_by_id.get(iid)
                if previous is None or count > previous["count"]:
                    all_match_by_id[iid] = candidate

        core_by_id: dict[int, dict] = {}
        for iid, global_stats in all_match_by_id.items():
            pr = global_stats["pr"]
            if pr <= self.opt.core_threshold:
                continue
            entry = global_stats["entry"]
            name = self._item_name(iid)
            avg_minute = entry.get("avg_minute")
            if not name or avg_minute is None:
                continue
            try:
                win_rate = float(entry.get("win_rate", 0) or 0)
                avg_minute = float(avg_minute)
            except (TypeError, ValueError):
                continue
            if win_rate > 1.0:
                win_rate /= 100.0
            core_by_id[iid] = {
                "id": iid,
                "name": name,
                "kind": "core",
                "pr": pr,
                "win_rate": max(0.0, min(win_rate, 1.0)),
                "avg_minute": avg_minute,
                "count": entry.get("count", 0) or 0,
                "min_minute": None,
                "max_minute": None,
            }

        situational_by_id: dict[int, dict] = {}
        item_stats = bd.get("anchor_item_stats") or {}
        if isinstance(item_stats, dict):
            for raw_iid, entry in item_stats.items():
                if not isinstance(entry, dict):
                    continue
                try:
                    iid = int(raw_iid)
                    raw_pr = float(entry.get("pr", 0) or 0)
                    win_rate = float(entry.get("win_rate", 0) or 0)
                except (TypeError, ValueError):
                    continue
                if iid in core_by_id:
                    continue
                pr = raw_pr / 100.0  # anchor_item_stats.pr is in percentage units
                if pr <= 0:
                    continue
                name = self._item_name(iid)
                avg_minute = entry.get("avg_minute")
                if not name or avg_minute is None:
                    continue
                try:
                    avg_minute = float(avg_minute)
                except (TypeError, ValueError):
                    continue
                if win_rate > 1.0:
                    win_rate /= 100.0
                min_minute = entry.get("min_minute")
                max_minute = entry.get("max_minute")
                try:
                    min_minute = max(0.0, float(min_minute)) if min_minute is not None else None
                    max_minute = max(0.0, float(max_minute)) if max_minute is not None else None
                except (TypeError, ValueError):
                    min_minute = max_minute = None
                global_stats = all_match_by_id.get(iid)
                situational_by_id[iid] = {
                    "id": iid,
                    "name": name,
                    "kind": "situational",
                    "pr": max(0.0, min(pr, 1.0)),
                    "sample_pr": max(0.0, min(pr, 1.0)),
                    "all_match_pr": global_stats["pr"] if global_stats is not None else None,
                    "win_rate": max(0.0, min(win_rate, 1.0)),
                    "avg_minute": avg_minute,
                    "count": entry.get("purchases", entry.get("count", 0)) or 0,
                    "min_minute": min_minute,
                    "max_minute": max_minute,
                }

        if situational_by_id:
            return list(core_by_id.values()) + list(situational_by_id.values())

        # Compatibility fallback for older cached payloads without
        # anchor_item_stats. These arrays report all-match fractional rates.
        pool: list[dict] = []
        for iid, global_stats in all_match_by_id.items():
            entry = global_stats["entry"]
            name = self._item_name(iid)
            avg_minute = entry.get("avg_minute")
            if not name or avg_minute is None:
                continue
            try:
                avg_minute = float(avg_minute)
                win_rate = float(entry.get("win_rate", 0) or 0)
            except (TypeError, ValueError):
                continue
            if win_rate > 1.0:
                win_rate /= 100.0
            pool.append({
                "id": iid,
                "name": name,
                "kind": "core" if global_stats["pr"] > self.opt.core_threshold else "situational",
                "pr": global_stats["pr"],
                "sample_pr": None,
                "all_match_pr": global_stats["pr"],
                "win_rate": max(0.0, min(win_rate, 1.0)),
                "avg_minute": avg_minute,
                "count": entry.get("count", 0) or 0,
                "min_minute": max(0.0, float(entry["min_minute"])) if entry.get("min_minute") is not None else None,
                "max_minute": max(0.0, float(entry["max_minute"])) if entry.get("max_minute") is not None else None,
            })
        return pool


    def _add_neutrals(self, guide: Guide, bd: dict) -> None:
        # Tier dicts are keyed by item id; older payloads also carried a
        # shortName per entry, current ones don't.
        tiers = bd.get("neutral_stats") or {}
        items: list[str] = []
        for tier in sorted(tiers, key=lambda t: int(t)):
            ranked = sorted(
                tiers[tier].items(), key=lambda kv: kv[1].get("count", 0), reverse=True
            )
            for iid, e in ranked[: self.opt.neutrals_per_tier]:
                if e.get("shortName"):
                    name = f"item_{e['shortName']}"
                else:
                    name = self._item_name(int(iid))
                if not name:
                    continue
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
        # Preserve the most common order's point counts, but use all returned
        # D2PT variants to break ties and rank abilities absent from the top order.
        weighted_counts: dict[int, float] = {}
        weighted_first: dict[int, int] = {}
        talent_ids = {
            side.get("ability_id")
            for tier in bd.get("talents") or []
            for side in (tier.get("left"), tier.get("right"))
            if side and side.get("ability_id") is not None
        }
        ability_meta = {
            ability.get("ability_id"): ability
            for ability in bd.get("abilities", [])
            if ability.get("ability_id") is not None
        }
        for order_ids, order_stats in orders:
            weight = float((order_stats or {}).get("pr", 0) or 0)
            if weight <= 0:
                weight = 1.0
            for index, aid in enumerate(order_ids):
                ability_name = name_of(aid) or ""
                metadata = ability_meta.get(aid, {})
                if (
                    aid in talent_ids
                    or ability_name.startswith("special_bonus_")
                    or metadata.get("isTalent")
                    or metadata.get("isInnate")
                ):
                    continue
                weighted_counts[aid] = weighted_counts.get(aid, 0.0) + weight
                weighted_first.setdefault(aid, index)

        priority = sorted(
            points,
            key=lambda aid: (
                -points[aid],
                -weighted_counts.get(aid, 0.0),
                first_seen[aid],
            ),
        )
        alternative_priority = sorted(
            (aid for aid in weighted_counts if aid not in points),
            key=lambda aid: (-weighted_counts[aid], weighted_first[aid]),
        )
        priority.extend(alternative_priority)

        # Basics never skilled in any returned order still get the leftovers.
        for ability in bd.get("abilities", []):
            aid = ability.get("ability_id")
            if (
                aid is not None
                and aid not in points
                and aid not in priority
                and not ability.get("isTalent")
                and not ability.get("isInnate")
            ):
                priority.append(aid)
                points.setdefault(aid, 0)
        if remaining_levels:
            self._notes.append(
                "Skill points after hero level 11 are estimated from the weighted "
                "popular D2PT order variants; exact later level-by-level picks "
                "are not included in the API data."
            )
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
