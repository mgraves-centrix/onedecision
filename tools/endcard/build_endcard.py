"""Render the video's closing card to docs/thumbnail.png.

Usage: python tools/endcard/build_endcard.py

The card was a PNG with no source, so a one-word change meant redrawing it. It
is HTML now. 1500x1000, the size the assembly expects.
"""

from __future__ import annotations

import pathlib

from playwright.sync_api import sync_playwright

HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE.parent.parent / "docs" / "thumbnail.png"
SIZE = {"width": 1500, "height": 1000}


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_context(viewport=SIZE, device_scale_factor=1).new_page()
        page.goto((HERE / "endcard.html").as_uri(), wait_until="networkidle")
        page.wait_for_timeout(700)          # let the webfonts land
        page.screenshot(path=str(OUT))
        browser.close()
    print(f"wrote {OUT.relative_to(HERE.parent.parent)}: "
          f"{SIZE['width']}x{SIZE['height']}, {OUT.stat().st_size / 1024:.0f} KB")


if __name__ == "__main__":
    main()
