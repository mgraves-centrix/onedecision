"""Record the AgentCore beat on its own and splice it into the timeline.

Usage: python tools/video/record_terminal.py
The beat is a local page replaying captured `agentcore invoke` output (render it
first with render_terminal.py), with no server calls, so redoing it never needs a
new Bedrock take. Refuses to splice if the terminal window does not fit the
viewport, because then the typed command scrolls off the top.
"""

from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

from paths import OUT

DESK = {"width": 1600, "height": 900}
OUT_DIR = OUT / "raw" / "terminal"
PAGE = OUT / "terminal.html"


def main() -> None:
    if not PAGE.exists():
        sys.exit(f"{PAGE} is missing; run render_terminal.py first")
    dur = json.loads((OUT / "durations.json").read_text())["agentcore"]
    shutil.rmtree(OUT_DIR, ignore_errors=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(
            viewport=DESK, device_scale_factor=1,
            record_video_dir=str(OUT_DIR), record_video_size=DESK,
        )
        page = ctx.new_page()
        origin = time.monotonic()
        page.goto(PAGE.as_uri() + f"?d={dur}")
        start = time.monotonic() - origin
        # Hidden rows are opacity 0 but still laid out, so this is the final height.
        box = page.locator(".win").bounding_box()
        if box is None or box["y"] < 0 or box["y"] + box["height"] > DESK["height"]:
            ctx.close()
            browser.close()
            sys.exit(f"terminal window does not fit the {DESK['height']} px viewport: {box}; timeline.json untouched")
        time.sleep(dur)
        end = time.monotonic() - origin
        video = page.video.path()
        ctx.close()
        browser.close()

    timeline_path = OUT / "timeline.json"
    timeline = json.loads(timeline_path.read_text())
    timeline["segments"] = [s for s in timeline["segments"] if s["beat"] != "agentcore"] + [
        {"beat": "agentcore", "source": "terminal", "start": round(start, 3), "end": round(end, 3)}
    ]
    timeline["terminal"] = str(video)
    timeline_path.write_text(json.dumps(timeline, indent=2) + "\n")
    print(f"window {box['height']:.0f} px tall at y={box['y']:.0f}; "
          f"spliced agentcore {end - start:.1f} s from {Path(video).name}")


if __name__ == "__main__":
    main()
