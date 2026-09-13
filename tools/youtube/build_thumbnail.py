"""Render the YouTube thumbnail: 1280x720, under YouTube's 2 MB limit.

Usage: python tools/youtube/build_thumbnail.py
"""
from __future__ import annotations
import pathlib
from playwright.sync_api import sync_playwright

HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE.parent.parent / "docs" / "youtube" / "thumbnail.png"

def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_context(viewport={"width": 1280, "height": 720}, device_scale_factor=1).new_page()
        pg.goto((HERE / "thumbnail.html").as_uri(), wait_until="networkidle")
        pg.wait_for_timeout(700)
        pg.screenshot(path=str(OUT))
        b.close()
    size = OUT.stat().st_size
    assert size < 2_000_000, f"thumbnail is {size} bytes, over YouTube's 2 MB limit"
    print(f"wrote docs/youtube/thumbnail.png: 1280x720, {size / 1024:.0f} KB")

if __name__ == "__main__":
    main()
