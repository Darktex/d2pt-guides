"""End-to-end builder tests against real d2pt API payloads (Sven pos 1,
captured 2026-06 and 2026-07 — the schema drifted between them: the newer
one has no top-level win_rate and no shortName on neutral items). Uses live
OpenDota constants (cached on disk after the first run)."""

import json
import re
from pathlib import Path

import pytest

from d2pt_guides.builder import (
    ABILITY_LEVELS,
    CAT_SUPER_LATE,
    SUPER_BLINKS,
    BuilderOptions,
    GuideBuilder,
    TALENT_LEVELS,
)
from d2pt_guides.constants import Constants
from d2pt_guides.guide import CAT_STARTING

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def constants():
    return Constants()


@pytest.fixture(
    scope="module",
    params=["builds_sven_pos1.json", "builds_sven_pos1_202607.json"],
)
def sven_guide(request, constants):
    build = json.loads((FIXTURES / request.param).read_text())[0]
    return GuideBuilder(constants).build_guide(
        build, source_url="https://dota2protracker.com/hero/Sven", patch="7.40c"
    )


def test_header_fields(sven_guide):
    assert sven_guide.hero == "sven"
    assert sven_guide.title.startswith("D2PT Sven Carry")
    # Win rate must come from num_wins/num_matches when the payload has no
    # top-level win_rate field.
    assert "· 0% WR" not in sven_guide.title
    assert sven_guide.role == "#DOTA_HeroGuide_Role_Core"
    assert "Dota2ProTracker" in sven_guide.overview


def test_item_categories(sven_guide):
    titles = [c.title for c in sven_guide.item_categories]
    assert titles[0] == CAT_STARTING
    assert any("Early Game" in t for t in titles)
    assert any("Situational" in t for t in titles)
    assert "Top Neutral Items" in titles
    for cat in sven_guide.item_categories:
        assert cat.items, f"empty category {cat.title}"
        for item in cat.items:
            assert item.startswith("item_"), item


def test_situational_items_have_stat_tooltips(sven_guide):
    situational = [
        c for c in sven_guide.item_categories if "Situational" in c.title
    ]
    assert situational
    for cat in situational:
        for item in cat.items:
            tip = sven_guide.item_tooltips[item]
            assert tip.startswith("SITUATIONAL")
            assert "WR" in tip and "min" in tip


def test_late_staples_always_present(sven_guide):
    """Endgame staples must appear somewhere in every guide, even when the
    d2pt data window has no purchases for them (Turbo / super-late games)."""
    everywhere = [i for c in sven_guide.item_categories for i in c.items]
    for staple in (
        "item_black_king_bar",
        "item_aghanims_shard",
        "item_ultimate_scepter_2",
        "item_moon_shard",
    ):
        assert staple in everywhere, staple
        assert everywhere.count(staple) == 1, f"{staple} duplicated"
    assert any(b in everywhere for b in SUPER_BLINKS.values())
    pinned = next(
        c for c in sven_guide.item_categories if c.title == CAT_SUPER_LATE
    )
    for item in pinned.items:
        assert sven_guide.item_tooltips[item].startswith("STAPLE")


def test_late_staples_can_be_disabled(constants):
    build = json.loads((FIXTURES / "builds_sven_pos1.json").read_text())[0]
    guide = GuideBuilder(constants, BuilderOptions(late_staples=False)).build_guide(
        build
    )
    assert all(c.title != CAT_SUPER_LATE for c in guide.item_categories)


def test_ability_order_levels(sven_guide):
    order = sven_guide.ability_order
    # Talent picked at every talent tier, as a special_bonus ability.
    for lvl in TALENT_LEVELS:
        assert order[lvl].startswith("special_bonus_"), (lvl, order.get(lvl))
    # All regular skill points assigned to Sven abilities.
    for lvl in ABILITY_LEVELS:
        assert order[lvl].startswith("sven_"), (lvl, order.get(lvl))
    # 4/4/4/3 point distribution for a standard hero kit.
    counts = {}
    for lvl in ABILITY_LEVELS:
        counts[order[lvl]] = counts.get(order[lvl], 0) + 1
    assert sorted(counts.values()) == [3, 4, 4, 4]
    assert counts["sven_gods_strength"] == 3  # ultimate capped at 3
    assert order[6] == "sven_gods_strength"


def test_talent_tooltips_mention_alternative(sven_guide):
    talent = sven_guide.ability_order[10]
    tip = sven_guide.ability_tooltips[talent]
    assert "Picked" in tip and "Alternative:" in tip


def test_render_matches_valve_kv_shape(sven_guide):
    text = sven_guide.render()
    assert text.startswith('"guidedata"\n{\n')
    assert '"GuideFormatVersion"\t\t"2"' in text
    assert '"Hero"\t\t"sven"' in text
    assert '"#DOTA_Item_Build_Starting_Items"' in text
    assert re.search(r'"item"\t\t"item_\w+"', text)
    assert re.search(r'"6"\t\t"sven_gods_strength"', text)
    # Balanced braces, quotes closed on every line.
    assert text.count("{") == text.count("}")
    assert sven_guide.filename().startswith("sven_") and sven_guide.filename().endswith(
        ".build"
    )


def test_real_guide_file_parses_with_same_conventions():
    """Sanity-check our format assumptions against a real in-game-editor file."""
    text = (FIXTURES / "naga_siren_1755780481.build").read_text()
    assert text.startswith('"guidedata"')
    assert '"GuideFormatVersion"\t\t"2"' in text
    assert text.count("{") == text.count("}")
