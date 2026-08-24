#!/usr/bin/env python3
"""Convert Radio Mobile runtime assets (rmwcore) into GUI resource PNGs.

Idempotent: safe to re-run after the rmwcore tree is updated. Outputs land in
``src/signal_gui/resources/rm/`` so packaged builds ship without rmwcore.

Usage: python scripts/convert_rm_icons.py [path/to/rmwcore]
"""

from __future__ import annotations

import os
import shutil
import sys

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "src", "signal_gui", "resources", "rm")


def find_rmwcore(explicit: str | None) -> str | None:
    if explicit and os.path.isdir(explicit):
        return explicit
    root = os.path.abspath(os.path.join(OUT, "..", "..", "..", "..", ".."))
    cand = os.path.join(root, "rmwcore")
    return cand if os.path.isdir(cand) else None


def convert(src: str, dst: str, height: int | None = None) -> None:
    im = Image.open(src)
    im = im.convert("RGBA")
    if height and im.height != height:
        w = max(1, round(im.width * height / im.height))
        im = im.resize((w, height), Image.LANCZOS)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    im.save(dst, "PNG")
    print(f"  {os.path.relpath(src)} -> {os.path.relpath(dst)} ({im.size[0]}x{im.size[1]})")


def copy(src: str, dst: str) -> None:
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copyfile(src, dst)
    print(f"  {os.path.relpath(src)} -> {os.path.relpath(dst)} (copied)")


def main() -> int:
    core = find_rmwcore(sys.argv[1] if len(sys.argv) > 1 else None)
    if not core:
        print("rmwcore not found; nothing to do")
        return 1
    print(f"Source: {core}")
    # Coverage dot markers (mobile units).
    for color in ("r", "g", "y"):
        src = os.path.join(core, f"dot_{color}.png")
        if os.path.exists(src):
            convert(src, os.path.join(OUT, f"dot_{color}.png"), height=24)
    # Antenna site pin.
    ant = os.path.join(core, "icon", "001_ant.ico")
    if os.path.exists(ant):
        convert(ant, os.path.join(OUT, "antenna_pin.png"), height=48)
    elif os.path.exists(os.path.join(core, "antenna.png")):
        convert(os.path.join(core, "antenna.png"),
                os.path.join(OUT, "antenna_pin.png"), height=48)
    # Bundled default elevation/signal palette for packaged builds.
    dat = os.path.join(core, "colors.dat")
    if os.path.exists(dat):
        copy(dat, os.path.join(OUT, "colors.dat"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
