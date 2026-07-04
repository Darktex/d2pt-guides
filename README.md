# d2pt-guides

Generate **Dota 2 in-game hero guides** from [Dota2ProTracker](https://dota2protracker.com)'s
most played builds — so you get D2PT's data inside the game instead of alt-tabbing
to a browser mid-match.

For each hero + position it pulls the most played build (7000+ MMR pub games,
last ~8 days) and writes a native `.build` guide file that Dota 2 loads like any
other guide:

- **Item build** split into Starting / Early / Mid / Late game categories, in
  typical purchase order.
- **Situational items captured**, just like on the site: D2PT treats items bought
  in ≥50% of matches as core and lower-frequency picks as situational. Each phase
  gets a separate *Situational* category, and **every item's tooltip shows its
  pick rate, win rate and average purchase minute** so you can judge the branch
  in-game.
- **Skill order** from the most common first-10-points sequence, completed to
  level 18, with the runner-up skill order noted in the guide overview.
- **Talents** chosen by pick rate — the tooltip shows both options' pick/win
  rates so you can deviate when the situation calls for it.
- **Top neutral items per tier**, with pick/win rates.

See [`examples/sven_carry_example.build`](examples/sven_carry_example.build) for
what the output looks like.

## Install

Python 3.10+, no dependencies:

```sh
pip install .
# or just run from the checkout:
python -m d2pt_guides --help
```

## Usage

```sh
# One hero, every position they actually play on d2pt:
d2pt-guides Sven

# Specific positions (1=carry ... 5=hard support):
d2pt-guides "Naga Siren" --positions 1,5

# Everyone (~2 min due to polite 1 req/s rate limiting):
d2pt-guides --all-heroes

# Generate AND install into your Steam guides folder
# (close Dota 2 first; also removes stale D2PT guides for those heroes):
d2pt-guides --all-heroes --install --replace
```

Guides are written to `output/guides/` by default. With `--install` they are
copied to `Steam/userdata/<account>/570/remote/guides/` (auto-detected on
Windows / Linux / macOS; pass `--guides-dir` if you have multiple accounts).
**Start Dota 2 after installing** — guides are enumerated at client start, and
appear in the in-game guide selector next to workshop guides.

Other useful flags:

| flag | meaning |
|---|---|
| `--top-builds N` | up to N guides per hero+position (one per D2PT build/facet) |
| `--min-matches N` | skip hero/position combos with few recent matches (default 30) |
| `--situational-floor 0.15` | min pick rate for an item to show as situational |
| `--patch 7.40c` | patch label stamped on the guide |

## How it works

- Build data comes from D2PT's JSON API (`/api/hero/<id>/builds?position=pos N`,
  `/api/heroes/list`). Responses are cached for 30 minutes under
  `~/.cache/d2pt-guides/`.
- Hero/item/ability id ↔ name mappings come from OpenDota's constants API
  (cached for a week).
- The `.build` output matches the format the in-game guide editor saves
  (KeyValues, `GuideFormatVersion 2`): item categories with custom display
  names, `AbilityOrder` keyed by hero level with talents as `special_bonus_*`
  abilities at 10/15/20/25, and per-item/per-ability tooltips.

## Caveats

- **Run it from a normal home connection.** dota2protracker.com sits behind
  Cloudflare bot protection; datacenter/VPN IPs typically get a 403. From
  residential IPs a plain request works. The script rate-limits itself to
  ~1 request/second — please keep it that way.
- This is a fan tool for **personal use**: it fetches the same data your browser
  does when you open d2pt and turns it into local guide files. All build data is
  Dota2ProTracker's work — if you find it useful, support them.
- D2PT's numbers move with the meta; regenerate with `--install --replace`
  every few days (data window is ~8 days).
- Close Dota 2 before installing; the client picks up new guide files on start.

## Development

```sh
pip install pytest
pytest
```

Tests run against a captured D2PT API payload in `tests/fixtures/` plus a real
guide file saved by the in-game editor, so no D2PT access is needed.
