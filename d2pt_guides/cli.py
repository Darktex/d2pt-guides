"""Command line interface: generate Dota 2 in-game guides from Dota2ProTracker."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from urllib.parse import quote

from .builder import BuilderOptions, GuideBuilder, _build_win_rate
from .constants import Constants
from .d2pt import POSITION_LABELS, POSITIONS, CloudflareBlocked, D2PTClient
from .steam import find_guide_dirs, install


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="d2pt-guides",
        description="Generate Dota 2 in-game hero guides from Dota2ProTracker's "
        "most played builds (7000+ MMR, last ~8 days).",
    )
    p.add_argument(
        "heroes",
        nargs="*",
        metavar="HERO",
        help="hero names, e.g. 'Sven' 'naga siren'. Use --all-heroes for everyone.",
    )
    p.add_argument("--all-heroes", action="store_true", help="generate for every hero")
    p.add_argument(
        "--positions",
        default="",
        help="comma-separated positions (1-5). Default: every position the hero "
        "actually plays (>= --min-matches recent matches on d2pt).",
    )
    p.add_argument(
        "--top-builds",
        type=int,
        default=1,
        help="guides per hero+position, one per d2pt build/facet (default 1)",
    )
    p.add_argument(
        "--min-matches",
        type=int,
        default=30,
        help="skip hero+position combos with fewer recent matches (default 30)",
    )
    p.add_argument("--out", default="output/guides", help="output directory")
    p.add_argument(
        "--install",
        action="store_true",
        help="also copy the guides into your Steam userdata guides folder "
        "(close Dota 2 first; guides load on next game start)",
    )
    p.add_argument(
        "--guides-dir",
        default="",
        help="explicit .../570/remote/guides directory (skips auto-detection)",
    )
    p.add_argument(
        "--replace",
        action="store_true",
        help="with --install: delete previously installed D2PT guides for the "
        "same heroes before installing",
    )
    p.add_argument(
        "--patch",
        default="",
        help="patch label for the guide, e.g. 7.40c (default: newest patch "
        "name from OpenDota)",
    )
    p.add_argument(
        "--no-late-staples",
        action="store_true",
        help="don't pin the 'Super Late & Turbo' category (BKB, Aghanim's "
        "Shard/Blessing, super-blink, Moon Shard) into every guide",
    )
    p.add_argument(
        "--situational-floor",
        type=float,
        default=0.15,
        help="min pick rate for an item to appear as situational (default 0.15)",
    )
    return p.parse_args(argv)


class Progress:
    """Per-hero progress: a live single-line bar on a terminal, plain
    '[i/N] hero' lines when piped or logged."""

    WIDTH = 24

    def __init__(self, total: int) -> None:
        self.total = max(total, 1)
        self.i = 0
        self.label = ""
        self.tty = sys.stderr.isatty()

    def step(self, label: str) -> None:
        self.i += 1
        self.label = label
        if self.tty:
            self._draw()
        else:
            print(f"[{self.i}/{self.total}] {label}", flush=True)

    def println(self, msg: str) -> None:
        """Print a normal output line without corrupting the bar."""
        self._clear()
        print(msg, flush=True)
        if self.tty:
            self._draw()

    def done(self) -> None:
        if self.tty and self.i:
            sys.stderr.write("\n")
            sys.stderr.flush()

    def _draw(self) -> None:
        filled = round(self.WIDTH * self.i / self.total)
        pct = round(100 * self.i / self.total)
        sys.stderr.write(
            f"\r[{'#' * filled}{'-' * (self.WIDTH - filled)}] "
            f"{self.i}/{self.total} ({pct:>3}%) {self.label[:20]:<20}"
        )
        sys.stderr.flush()

    def _clear(self) -> None:
        if self.tty:
            sys.stderr.write("\r" + " " * (self.WIDTH + 32) + "\r")
            sys.stderr.flush()


# Fixed epoch for stable filenames. The in-game client identifies a local
# guide by its file name, so regenerating under the same name updates the
# guide in place and anyone following it keeps following it. A fresh
# timestamp per run would make every update look like a brand-new guide.
STABLE_TS_BASE = 1_600_000_000


def stable_guide_id(hero_id: int, pos_num: int, build_idx: int) -> int:
    """Deterministic pseudo-timestamp, unique per hero+position+build slot."""
    return STABLE_TS_BASE + hero_id * 1_000 + pos_num * 100 + build_idx


def pick_positions(hero_row: dict, requested: list[str], min_matches: int) -> list[str]:
    if requested:
        return requested
    return [
        pos for pos in POSITIONS if (hero_row.get(f"{pos} matches") or 0) >= min_matches
    ]


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.heroes and not args.all_heroes:
        print("error: name at least one hero or pass --all-heroes", file=sys.stderr)
        return 2

    requested_positions = [
        f"pos {p.strip()}" for p in args.positions.split(",") if p.strip()
    ]
    for pos in requested_positions:
        if pos not in POSITIONS:
            print(f"error: bad position {pos!r} (use 1-5)", file=sys.stderr)
            return 2

    constants = Constants()
    client = D2PTClient()
    builder = GuideBuilder(
        constants,
        BuilderOptions(
            situational_floor=args.situational_floor,
            late_staples=not args.no_late_staples,
        ),
    )
    patch = args.patch or constants.latest_patch()

    try:
        roster = {row["hero_id"]: row for row in client.heroes_list()}
    except CloudflareBlocked as err:
        print(f"error: {err}", file=sys.stderr)
        return 1

    if args.all_heroes:
        hero_ids = sorted(roster)
    else:
        hero_ids = [constants.hero_id_by_name(name) for name in args.heroes]

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    base_ts = int(time.time())
    written: list[Path] = []
    heroes_written: set[str] = set()

    progress = Progress(len(hero_ids))
    for hero_id in hero_ids:
        row = roster.get(hero_id, {})
        display = constants.hero_display_name(hero_id)
        progress.step(display)
        positions = pick_positions(row, requested_positions, args.min_matches)
        if not positions:
            progress.println(
                f"{display}: no position with >= {args.min_matches} matches, skipping"
            )
            continue
        for pos in positions:
            try:
                builds = client.hero_builds(hero_id, pos)
            except CloudflareBlocked as err:
                print(f"error: {err}", file=sys.stderr)
                return 1
            builds = sorted(builds, key=lambda b: b.get("num_matches", 0), reverse=True)
            builds = [
                b for b in builds if b.get("num_matches", 0) >= args.min_matches
            ][: args.top_builds]
            if not builds:
                progress.println(f"{display} {pos}: no build with enough matches, skipping")
                continue
            for idx, build in enumerate(builds):
                url = f"https://dota2protracker.com/hero/{quote(display)}"
                guide = builder.build_guide(build, source_url=url, patch=patch)
                if len(builds) > 1:
                    guide.title += f" #{idx + 1}"
                pos_num = int(pos.split()[1])
                guide.timestamp = stable_guide_id(hero_id, pos_num, idx)
                guide.updated = base_ts
                path = out_dir / guide.filename()
                path.write_text(guide.render(), encoding="utf-8", newline="\n")
                written.append(path)
                heroes_written.add(guide.hero)
                progress.println(
                    f"wrote {path}  ({display} {POSITION_LABELS[pos]}, "
                    f"{build['num_matches']} matches, "
                    f"{round(_build_win_rate(build) * 100)}% WR)"
                )
    progress.done()

    if not written:
        print("nothing generated", file=sys.stderr)
        return 1

    if args.install:
        if args.guides_dir:
            guide_dirs = [Path(args.guides_dir)]
        else:
            guide_dirs = find_guide_dirs()
        if not guide_dirs:
            print(
                "error: no Steam userdata guides folder found; pass --guides-dir",
                file=sys.stderr,
            )
            return 1
        if len(guide_dirs) > 1 and not args.guides_dir:
            print(
                "multiple Steam accounts found, pass --guides-dir with one of:",
                file=sys.stderr,
            )
            for d in guide_dirs:
                print(f"  {d}", file=sys.stderr)
            return 1
        target = guide_dirs[0]
        if args.replace:
            removed = _remove_previous(target, heroes_written)
            if removed:
                print(f"removed {removed} previously installed D2PT guides")
        install(written, target)
        print(f"installed {len(written)} guides into {target}")
        print("Start Dota 2 (with the game previously closed) to load them.")
    return 0


def _remove_previous(guides_dir: Path, heroes: set[str]) -> int:
    removed = 0
    for f in guides_dir.glob("*.build"):
        try:
            head = f.read_text(encoding="utf-8", errors="replace")[:500]
        except OSError:
            continue
        if '"Title"\t\t"D2PT ' not in head:
            continue
        if any(f'"Hero"\t\t"{h}"' in head for h in heroes):
            f.unlink()
            removed += 1
    return removed


if __name__ == "__main__":
    sys.exit(main())
