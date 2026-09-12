"""Render one 1200x630 cover per Builder post.

Usage: python tools/blog/build_covers.py

The evidence on each cover is the product's own: `tokens.png`, `replay.png` and
`refusal.png` are screenshots taken from the app running against a finished
take's database, and the terminal block is real captured CLI and runtime output.
Nothing on a cover is a number someone typed to look good. See README.md for how
to re-shoot the screenshots after a new take.
"""

from __future__ import annotations

import html
import json
import pathlib
import sys

from playwright.sync_api import sync_playwright

HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE.parent.parent / "docs" / "blog"
W, H = 1200, 630

CSS = """
:root {
  --bg: #10131a; --panel: #171b24; --line: #2a3140;
  --ink: #e6e9ef; --dim: #9aa4b6; --faint: #6b7488;
  --accent: #5eead4; --good: #4ade80;
  --mono: "IBM Plex Mono", ui-monospace, Menlo, monospace;
  --sans: "IBM Plex Sans", ui-sans-serif, system-ui, sans-serif;
}
* { box-sizing: border-box; margin: 0; }
html, body { width: 1200px; height: 630px; }
body { background: var(--bg); color: var(--ink); font-family: var(--sans);
       display: flex; flex-direction: column; padding: 56px 60px 0;
       position: relative; overflow: hidden; }
.wash { position: absolute; inset: -40% 35% 40% -20%; pointer-events: none;
        background: radial-gradient(closest-side, rgba(94,234,212,.11), transparent 70%); }
.topline { display: flex; align-items: baseline; justify-content: space-between;
           gap: 24px; position: relative; }
.eyebrow { font-family: var(--mono); font-size: 15px; font-weight: 500;
           letter-spacing: .15em; text-transform: uppercase; color: var(--accent); }
.repo { font-family: var(--mono); font-size: 14px; color: var(--faint); }

.body { display: flex; gap: 52px; align-items: flex-start; position: relative;
        margin-bottom: 30px; }   /* a floor, so a tall hero never crowds the copy */
.copy { min-width: 0; }
h1 { margin-top: 30px; font-size: 54px; font-weight: 600; line-height: 1.08;
     letter-spacing: -.028em; max-width: 22ch; }
h1 .quiet { color: var(--dim); font-weight: 500; }
.sub { margin-top: 22px; max-width: 50ch; font-size: 19px; line-height: 1.45; color: var(--dim); }


.proof { margin-top: auto; padding-bottom: 46px; position: relative; }
.proof-label { display: flex; align-items: baseline; gap: 12px; margin-bottom: 13px;
               font-family: var(--mono); font-size: 13.5px; color: var(--faint); }
.proof-label b { color: var(--good); font-weight: 500; }
.proof img { display: block; width: 100%; border: 1px solid var(--line); border-radius: 9px; }

pre { background: var(--panel); border: 1px solid var(--line); border-radius: 9px;
      padding: 18px 22px; font-family: var(--mono); font-size: 14px; line-height: 1.62;
      color: var(--dim); overflow: hidden; white-space: pre; }
pre .cmd { color: var(--ink); }
"""


def page(spec: dict) -> str:
    layout = spec["layout"]
    caption = (
        f'<div class="proof-label"><span>{html.escape(spec["caption"])}</span>'
        f'<b>{html.escape(spec["flag"])}</b></div>'
    )

    if layout == "terminal":
        lines = "\n".join(
            f'<span class="cmd">{html.escape(l)}</span>' if l.startswith("$") else html.escape(l)
            for l in spec["terminal"]
        )
        proof = f'<div class="proof">{caption}<pre>{lines}</pre></div>'
        aside = ""
    else:
        proof = f'<div class="proof">{caption}<img src="{spec["hero"]}" alt=""></div>'
        aside = ""

    return f"""<!doctype html><meta charset="utf-8">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:wght@400;500;600;700&display=swap">
<style>{CSS}</style>
<div class="wash"></div>
<div class="topline">
  <p class="eyebrow">{html.escape(spec["eyebrow"])}</p>
  <p class="repo">github.com/mgraves-centrix/onedecision</p>
</div>
<div class="body">
  <div class="copy">
    <h1>{html.escape(spec["title"])}<br><span class="quiet">{spec["title_quiet"]}</span></h1>
    <p class="sub">{html.escape(spec["sub"])}</p>
  </div>
  {aside}
</div>
{proof}
"""


def main() -> None:
    specs = json.loads((HERE / "covers.json").read_text())
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": W, "height": H}, device_scale_factor=2)
        pg = ctx.new_page()
        for name, spec in specs.items():
            src = HERE / f"_{name}.html"
            src.write_text(page(spec))
            pg.goto(src.as_uri(), wait_until="networkidle")
            pg.wait_for_timeout(700)          # let the webfonts land
            out = OUT / (f"cover.png" if name == "series" else f"cover-{name}.png")
            pg.screenshot(path=str(out))
            src.unlink()
            print(f"{out.name:<28} {out.stat().st_size / 1024:5.0f} KB")
        browser.close()


if __name__ == "__main__":
    main()
