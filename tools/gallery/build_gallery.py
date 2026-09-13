"""Render the Devpost gallery: real screens of the running app, 3:2.

Usage: python tools/gallery/build_gallery.py

Devpost wants JPG/PNG/GIF at 3:2, 5 MB each, 15 at most. Every shot here is the
product running against a real take's database, framed by scrolling the page the
way a person would rather than by cropping something out of a video.

Two servers are expected:
  8100  a database whose CASE-2001 is waiting on a decision (the card, the
        evidence, the buttons a person actually presses)
  8101  a finished take: an active policy, an auto-resolved case, a refusal,
        the dashboard and the audit log
"""

from __future__ import annotations

import pathlib
import subprocess
import sys

from playwright.sync_api import sync_playwright

OUT = pathlib.Path(__file__).resolve().parent.parent.parent / "docs" / "gallery"
VIEW = {"width": 1440, "height": 960}          # 3:2, rendered at 2x
BG = "0x10131a"

HERO, FULL = "http://127.0.0.1:8100", "http://127.0.0.1:8101"

# (file, base url, path, selector to bring to the top, pixels below the top)
SHOTS = [
    ("01-inbox",        HERO, "/",                          ".dock-list",              120),
    ("02-decision-card", HERO, "/exceptions/{hero}",         "section.card:has(h2)",     40),
    ("03-evidence",     HERO, "/exceptions/{hero}",          "table.evidence",           60),
    ("04-boundaries",   HERO, "/exceptions/{hero}",          "ul.boundaries",            60),
    ("05-the-decision", HERO, "/exceptions/{hero}",          ".actions",                260),
    ("06-candidate-policy", FULL, "/exceptions/{full1}",     "ul.conditions",            80),
    ("07-policy-diff",  FULL, "/exceptions/{full1}",         ".diff-table, table",       80),
    ("08-replay-gate",  FULL, "/exceptions/{full1}",         ".replay-grid",             80),
    ("09-auto-resolved", FULL, "/exceptions/{full2}",        "ol.timeline",             120),
    ("10-refusal",      FULL, "/exceptions/{full3}",         "section.card.danger",     100),
    ("11-policies",     FULL, "/policies",                   ".policy-version",          80),
    ("12-dashboard",    FULL, "/dashboard",                  ".kpi-row",                100),
    ("13-audit-log",    FULL, "/policies",                   'h2:has-text("Audit log")', 60),
]

IDS = {"hero": "exc_3b5cb74454f3", "full1": "exc_476d73beac4f",
       "full2": "exc_80c3ac2216ce", "full3": "exc_392d8e1e13da"}


def shoot(page, name: str, base: str, path: str, selector: str, offset: int) -> None:
    page.goto(base + path.format(**IDS), wait_until="load")
    page.wait_for_timeout(300)
    el = page.locator(selector).first
    if not el.count():
        print(f"  {name:22} SKIPPED, no {selector}")
        return
    # Put the subject a fixed distance below the top edge, so every frame is
    # composed the same way instead of wherever the browser happened to stop.
    el.evaluate(
        "(e, off) => window.scrollTo({top: e.getBoundingClientRect().top + window.scrollY - off})",
        offset,
    )
    page.wait_for_timeout(250)
    out = OUT / f"{name}.png"
    page.screenshot(path=str(out))
    print(f"  {name:22} {out.stat().st_size / 1024:5.0f} KB")


def pad(src: pathlib.Path, name: str) -> None:
    """Fit an existing image into the 3:2 frame on the app's own background."""
    out = OUT / f"{name}.png"
    w, h = VIEW["width"] * 2, VIEW["height"] * 2
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src),
         "-vf", f"scale={w}:{h}:force_original_aspect_ratio=decrease:flags=lanczos,"
                f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color={BG}",
         str(out)], check=True)
    print(f"  {name:22} {out.stat().st_size / 1024:5.0f} KB")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_context(viewport=VIEW, device_scale_factor=2).new_page()
        for name, base, path, selector, offset in SHOTS:
            shoot(page, name, base, path, selector, offset)
        browser.close()

    repo = pathlib.Path(__file__).resolve().parent.parent.parent
    pad(repo / "docs" / "architecture.png", "14-architecture")

    oversize = [f for f in OUT.glob("*.png") if f.stat().st_size > 5_000_000]
    if oversize:
        sys.exit("over Devpost's 5 MB limit: " + ", ".join(f.name for f in oversize))
    print(f"\n{len(list(OUT.glob('*.png')))} images in docs/gallery, all 3:2 and under 5 MB")


if __name__ == "__main__":
    main()
