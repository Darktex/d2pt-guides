"""Locate the Steam userdata guides folder and install .build files.

Guides live at <steam>/userdata/<accountid32>/570/remote/guides/ and are
enumerated when the Dota 2 client starts — install with the game closed.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

STEAM_ROOTS = {
    "win32": [Path(r"C:\Program Files (x86)\Steam"), Path(r"C:\Program Files\Steam")],
    "linux": [
        Path.home() / ".local/share/Steam",
        Path.home() / ".steam/steam",
    ],
    "darwin": [Path.home() / "Library/Application Support/Steam"],
}


def find_guide_dirs() -> list[Path]:
    """All existing <userdata>/<account>/570/remote/guides dirs (created if
    the account has Dota installed but never made a guide)."""
    roots = STEAM_ROOTS.get(sys.platform, STEAM_ROOTS["linux"])
    dirs = []
    for root in roots:
        userdata = root / "userdata"
        if not userdata.is_dir():
            continue
        for account in sorted(userdata.iterdir()):
            if not account.name.isdigit() or account.name == "0":
                continue
            dota = account / "570"
            if dota.is_dir():
                dirs.append(dota / "remote" / "guides")
    # De-dup (e.g. ~/.steam/steam symlinks to ~/.local/share/Steam).
    seen: set[str] = set()
    unique = []
    for d in dirs:
        key = os.path.realpath(d)
        if key not in seen:
            seen.add(key)
            unique.append(d)
    return unique


def install(files: list[Path], guides_dir: Path) -> list[Path]:
    guides_dir.mkdir(parents=True, exist_ok=True)
    installed = []
    for f in files:
        dest = guides_dir / f.name
        dest.write_text(f.read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
        installed.append(dest)
    return installed
