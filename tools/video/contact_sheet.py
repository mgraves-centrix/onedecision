"""Grab frames from the start, middle, and end of every beat and tile them.

Usage: python tools/video/contact_sheet.py
Writes var/video/contact-sheet.png, one row per beat in narration order, for a
quick visual pass before a draft is shared.
"""

from __future__ import annotations

import json
import subprocess

from paths import HERE, OUT

WORK = OUT / "work" / "sheet"
SHEET = OUT / "contact-sheet.png"
MP4 = OUT / "onedecision-demo-draft.mp4"


def main() -> None:
    order = [b["id"] for b in json.loads((HERE / "narration.json").read_text())]
    dur = json.loads((OUT / "durations.json").read_text())
    WORK.mkdir(parents=True, exist_ok=True)

    frames = []
    t0 = 0.0
    for beat in order:
        d = dur[beat]
        for k, at in enumerate((t0 + 0.8, t0 + d / 2, t0 + d - 0.5)):
            f = WORK / f"{beat}-{k}.png"
            subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{at:.2f}", "-i", str(MP4), "-frames:v", "1",
                 # Homebrew's ffmpeg has no drawtext; rows follow narration.json order instead.
                 "-vf", "scale=640:-2", str(f)],
                check=True,
            )
            frames.append(f)
        t0 += d

    inputs = [a for f in frames for a in ("-i", str(f))]
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", *inputs,
         "-filter_complex", "".join(f"[{i}:v]" for i in range(len(frames)))
         + f"xstack=inputs={len(frames)}:grid=3x{len(order)}:fill=black[v]",
         "-map", "[v]", str(SHEET)],
        check=True,
    )
    print(f"wrote {SHEET.name}: {len(frames)} frames, {len(order)} beats")


if __name__ == "__main__":
    main()
