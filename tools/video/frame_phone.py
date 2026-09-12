"""Put the phone screen recording into a phone, and cut it to its narration.

Usage: python tools/video/frame_phone.py <recording.mp4> [--start S] [--hold A B]

There is one phone, and it is the thing running the app, so nothing can film it
being held. What it can do is record its own screen, which is the honest
footage: a real iOS Safari on a real device, reaching the app over the LAN. This
wraps that recording in a drawn device body so it reads as a phone rather than a
bare vertical video, and cuts it to the length of the narration beat.

The screen is punched out of the body rather than laid over it, so the recording
keeps its own pixels and the body covers its square corners.

--hold slows one span, for the case this beat always has: a person scrolls to a
button and taps it in one motion, leaving the button on screen too briefly to
read. The span is real footage played slower, never a still or a duplicated
frame, and the beat still ends on the same frame it would have.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from paths import OUT

W, H = 1920, 1080
BG = "0x10131a"
SCREEN_H = 944                     # leaves a margin above and below in 1080
BEZEL = 13
BODY_R, SCREEN_R = 58, 46
BODY, EDGE, SHADOW = (28, 32, 41, 255), (58, 66, 82, 255), (0, 0, 0, 150)
BEAT = "phone"
HOLD_FACTOR = 1.85


def run(*args: str) -> str:
    return subprocess.run(args, check=True, capture_output=True, text=True).stdout


def probe(path: Path, entries: str) -> list[str]:
    out = run("ffprobe", "-v", "error", "-show_entries", entries,
              "-of", "default=nw=1:nk=1", str(path))
    return out.strip().splitlines()


def bezel(screen_w: int, screen_h: int) -> tuple[Path, int, int]:
    """Draw the body once, and report where its screen sits."""
    body_w, body_h = screen_w + BEZEL * 2, screen_h + BEZEL * 2
    bx0, by0 = W // 2 - body_w // 2, H // 2 - body_h // 2
    bx1, by1 = bx0 + body_w, by0 + body_h
    sx0, sy0 = bx0 + BEZEL, by0 + BEZEL
    sx1, sy1 = sx0 + screen_w, sy0 + screen_h

    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle(
        (bx0 - 2, by0 + 16, bx1 + 2, by1 + 26), BODY_R, fill=SHADOW
    )
    layer = shadow.filter(ImageFilter.GaussianBlur(26))

    body = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(body)
    d.rounded_rectangle((bx0, by0, bx1, by1), BODY_R, fill=BODY, outline=EDGE, width=2)
    # Side buttons, so the silhouette reads as a phone and not a rounded card.
    d.rounded_rectangle((bx0 - 3, by0 + 190, bx0 + 1, by0 + 252), 2, fill=EDGE)
    d.rounded_rectangle((bx0 - 3, by0 + 272, bx0 + 1, by0 + 334), 2, fill=EDGE)
    d.rounded_rectangle((bx1 - 1, by0 + 250, bx1 + 3, by0 + 352), 2, fill=EDGE)
    d.rounded_rectangle((sx0, sy0, sx1, sy1), SCREEN_R, fill=(0, 0, 0, 0))

    layer.alpha_composite(body)
    # Punch the screen through the shadow too, or the blur tints the recording.
    ImageDraw.Draw(layer).rounded_rectangle((sx0, sy0, sx1, sy1), SCREEN_R, fill=(0, 0, 0, 0))
    path = OUT / "phone-bezel.png"
    layer.save(path)
    return path, sx0, sy0


def spans(start: float, length: float, hold: tuple[float, float] | None) -> str:
    """The trim/setpts graph that fills exactly `length` seconds of output.

    Without a hold it is one straight cut. With one, the held span plays at
    HOLD_FACTOR and the cut simply runs further into the recording to make up
    the time, so the beat is still one continuous piece of real footage.
    """
    if hold is None:
        return f"[1:v]trim={start}:{start + length},setpts=PTS-STARTPTS[cut];"

    a, b = hold
    if not start <= a < b:
        sys.exit(f"--hold {a} {b} must start at or after --start {start}")
    before = a - start
    after = length - before - (b - a) * HOLD_FACTOR
    if after < 0:
        sys.exit(f"--hold span is too long to stretch inside a {length:.3f}s beat")
    return (
        f"[1:v]trim={start}:{a},setpts=PTS-STARTPTS[p1];"
        f"[1:v]trim={a}:{b},setpts={HOLD_FACTOR}*(PTS-STARTPTS)[p2];"
        f"[1:v]trim={b}:{b + after},setpts=PTS-STARTPTS[p3];"
        f"[p1][p2][p3]concat=n=3:v=1:a=0[cut];"
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("recording", type=Path)
    ap.add_argument("--start", type=float, required=True, help="seconds into the recording")
    ap.add_argument("--hold", type=float, nargs=2, metavar=("FROM", "TO"),
                    help="slow this span so a button stays readable")
    ap.add_argument("--out", type=Path, default=OUT / "phone-beat.mp4")
    args = ap.parse_args()

    if not args.recording.exists():
        sys.exit(f"{args.recording} not found")

    import json
    length = json.loads((OUT / "durations.json").read_text())[BEAT]
    width, height = (int(v) for v in probe(args.recording, "stream=width,height")[:2])
    screen_w = round(SCREEN_H * width / height / 2) * 2
    frame, sx, sy = bezel(screen_w, SCREEN_H)

    graph = spans(args.start, length, tuple(args.hold) if args.hold else None)
    run(
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "lavfi", "-t", f"{length:.3f}", "-i", f"color=c={BG}:s={W}x{H}:r=30",
        "-i", str(args.recording),
        "-i", str(frame),
        "-filter_complex",
        graph
        + f"[cut]fps=30,scale={screen_w}:{SCREEN_H}:flags=lanczos[scr];"
        + f"[0:v][scr]overlay={sx}:{sy}[a];"
        + "[a][2:v]overlay=0:0,format=yuv420p[v]",
        "-map", "[v]", "-t", f"{length:.3f}",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-movflags", "+faststart", str(args.out),
    )
    got = float(probe(args.out, "format=duration")[0])
    print(f"{args.out.name}: {got:.2f} s, screen {screen_w}x{SCREEN_H} at ({sx},{sy})")


if __name__ == "__main__":
    main()
