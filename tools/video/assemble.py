"""Cut the recorded waits, fit each beat to its narration, and join the draft video.

Usage: python tools/video/assemble.py
Reads narration.json, and from var/video: durations.json, timeline.json, and
audio/*.wav. Writes var/video/onedecision-demo-draft.mp4 (1920x1080, H.264 + AAC).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from paths import HERE, OUT

WORK = OUT / "work"
MP4 = OUT / "onedecision-demo-draft.mp4"
BG = "0x10131a"
SCALE = {
    "desktop": "scale=1920:1080:flags=lanczos",
    # The AgentCore beat, recorded on its own by record_terminal.py.
    "terminal": "scale=1920:1080:flags=lanczos",
    # The phone beat is real screen-recording footage, already composited into a
    # device frame on the app's background by tools/video/frame_phone.py.
    "phone": "scale=1920:1080:flags=lanczos",
}


def run(*args: str) -> str:
    return subprocess.run(args, check=True, capture_output=True, text=True).stdout


def opens_on_the_sync_flash(path: Path) -> bool:
    """Is the first frame the magenta the recorder uses to line up the clocks?

    The flash sits immediately before the first beat in the capture, so a start
    time a few milliseconds early ships it. It is unmistakable: a whole frame of
    #ff00ff, which nothing in the app comes near.
    """
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-frames:v", "1",
         "-vf", "scale=1:1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        check=True, capture_output=True,
    ).stdout
    if len(raw) < 3:
        return False
    r, g, b = raw[0], raw[1], raw[2]
    return r > 180 and g < 80 and b > 180


def duration(path: Path) -> float:
    return float(run("ffprobe", "-v", "error", "-show_entries", "format=duration",
                     "-of", "default=nw=1:nk=1", str(path)).strip())


def main() -> None:
    WORK.mkdir(parents=True, exist_ok=True)
    order = [b["id"] for b in json.loads((HERE / "narration.json").read_text())]
    dur = json.loads((OUT / "durations.json").read_text())
    timeline = json.loads((OUT / "timeline.json").read_text())
    beat_files = []

    for n, beat in enumerate(order):
        # Recorders append segments in the order they belong on screen; a beat can mix
        # sources (the close runs live, then holds on the end card), so keep that order.
        segments = [s for s in timeline["segments"] if s["beat"] == beat]
        parts = []
        for k, seg in enumerate(segments):
            part = WORK / f"{n:02d}-{beat}-{k}.mp4"
            src = timeline[seg["source"]]
            if src.endswith(".png"):
                # A still, held for the segment's length on the app's background color.
                source_args = ["-loop", "1", "-framerate", "30",
                               "-t", f"{seg['end'] - seg['start']:.3f}", "-i", src]
                vf = ("scale=1920:1080:force_original_aspect_ratio=decrease:flags=lanczos,"
                      f"pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color={BG}")
            else:
                source_args = ["-i", src, "-ss", f"{seg['start']:.3f}", "-to", f"{seg['end']:.3f}"]
                vf = SCALE[seg["source"]]
            run("ffmpeg", "-y", "-loglevel", "error", *source_args,
                "-vf", f"{vf},fps=30,format=yuv420p",
                "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "18", str(part))
            parts.append(part)

        listing = WORK / f"{n:02d}-{beat}.txt"
        listing.write_text("".join(f"file '{p}'\n" for p in parts))
        joined = WORK / f"{n:02d}-{beat}-joined.mp4"
        run("ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(listing),
            "-c", "copy", str(joined))

        target = dur[beat]
        shortfall = max(0.0, target - duration(joined))
        beat_file = WORK / f"{n:02d}-{beat}-final.mp4"
        run("ffmpeg", "-y", "-loglevel", "error",
            "-i", str(joined), "-i", str(OUT / "audio" / f"{beat}.wav"),
            "-vf", f"tpad=stop_mode=clone:stop_duration={shortfall:.3f}",
            "-t", f"{target:.3f}", "-map", "0:v", "-map", "1:a",
            "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", str(beat_file))
        beat_files.append(beat_file)
        print(f"{beat:<10} {target:6.2f} s  ({len(parts)} part(s), froze {shortfall:.2f} s)")

    listing = WORK / "all.txt"
    listing.write_text("".join(f"file '{p}'\n" for p in beat_files))
    run("ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(listing),
        "-c", "copy", "-movflags", "+faststart", str(MP4))
    print(f"wrote {MP4.name}: {duration(MP4):.1f} s, {MP4.stat().st_size / 1e6:.1f} MB")
    if opens_on_the_sync_flash(MP4):
        sys.exit("the video opens on the magenta sync flash; push the first beat's "
                 "start later in timeline.json and assemble again")


if __name__ == "__main__":
    main()
