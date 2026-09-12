"""Render the architecture diagram and the interactive page from one model.

Usage: python tools/diagram/build_architecture.py

Reads docs/architecture.json and writes:
  docs/architecture.svg   the tiered diagram used in the README
  docs/architecture.html  the same model, where hovering a component shows what
                          it connects to and which way the data moves
  <out>/architecture-artifact.html  the page without its document wrapper, for
                          publishing (default: alongside the repository)

Keeping both outputs on one model is the point: the diagram cannot drift from
the page, and neither can drift from the tier list without editing the model.
docs/architecture.png is rendered from the SVG at 2x with headless Chrome.
"""

from __future__ import annotations

import html
import json
import os
import textwrap
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
DOCS = REPO / "docs"
MODEL = json.loads((DOCS / "architecture.json").read_text())
ARTIFACT_OUT = Path(os.environ.get("ONEDECISION_VIDEO_OUT") or REPO.parent / f"{REPO.name}-video")

# The product's own tokens (app/static/app.css), so the diagram and the app read
# as one system rather than two.
BG = "#10131a"
PANEL = "#171b24"
PANEL_2 = "#1e232e"
LINE = "#2a3140"
INK = "#e6e9ef"
DIM = "#9aa4b6"
FAINT = "#6b7488"
ACCENT = "#5eead4"

# --- static diagram ---------------------------------------------------------

WIDTH = 1440
MARGIN = 40
RAIL = 196  # the tier rail: name and one-line role
CHAR_W = 6.2  # 12px sans, measured off the rendered SVG
MONO_W = 6.6  # 11px mono
GUTTER = 18  # between cards
LANE_GAP = 74  # between tiers: room for two stacked arrow labels
HEAD = 132  # title block
FOOT = 86  # legend


def esc(text: str) -> str:
    return html.escape(text, quote=False)


def wrap_to(text: str, width: float, char_w: float = CHAR_W) -> list[str]:
    """SVG has no text wrapping, so wrap to what fits the card at this font size."""
    return textwrap.wrap(text, max(12, int((width - 30) / char_w))) or [""]


def card_geometry(node: dict) -> tuple[int, int]:
    """Where the function lines start, and how tall the card has to be."""
    top = 44 + 14 * len(node["meta_lines"]) + 12
    return top, top + 17 * len(node["lines"]) + 6


def layout() -> tuple[list[dict], int]:
    """Place every node: tiers stack, cards fill the width of their tier."""
    placed: list[dict] = []
    y = HEAD
    for tier in MODEL["tiers"]:
        nodes = tier["nodes"]
        span = WIDTH - 2 * MARGIN - RAIL
        width = (span - GUTTER * (len(nodes) - 1)) / len(nodes)
        prepared = []
        for node in nodes:
            lines: list[str] = []
            for fn in node["functions"]:
                lines.extend(wrap_to(fn, width))
            prepared.append({**node, "lines": lines, "meta_lines": wrap_to(node["meta"], width, MONO_W)})
        height = max(card_geometry(n)[1] for n in prepared)
        for i, node in enumerate(prepared):
            x = MARGIN + RAIL + i * (width + GUTTER)
            placed.append(
                {**node, "tier": tier["id"], "x": x, "y": y, "w": width, "h": height}
            )
        tier["y"], tier["h"] = y, height
        y += height + LANE_GAP
    return placed, y - LANE_GAP + FOOT


def steps_by_node(node_id: str) -> list[int]:
    return sorted(
        e["step"] for e in MODEL["edges"] if e.get("step") and e["from"] == node_id
    )


def in_gap(y: float, top: float, bottom: float) -> float:
    """Keep a label inside the band between two tiers, never on a card."""
    return max(min(top, bottom) + 13, min(y, max(top, bottom) - 5))


def connector(path: str, color: str, label: str = "", at: tuple[float, float] | None = None) -> str:
    """One orthogonal connector, with its label placed clear of every card."""
    text = (
        f'<text x="{at[0]:.0f}" y="{at[1]:.0f}" class="edge-label">{esc(label)}</text>'
        if label and at
        else ""
    )
    return (
        f'<path d="{path}" fill="none" stroke="{color}" stroke-width="1.6" '
        f'marker-end="url(#arrow-{color.lstrip("#")})" opacity="0.9"/>{text}'
    )


def build_svg() -> str:
    nodes, height = layout()
    at = {n["id"]: n for n in nodes}
    kinds = MODEL["kinds"]
    parts: list[str] = []

    colors = sorted({k["color"] for k in kinds.values()})
    markers = "".join(
        f'<marker id="arrow-{c.lstrip("#")}" viewBox="0 0 10 10" refX="9" refY="5" '
        f'markerWidth="6" markerHeight="6" orient="auto-start-reverse">'
        f'<path d="M 0 0 L 10 5 L 0 10 z" fill="{c}"/></marker>'
        for c in colors
    )

    parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{height}" '
        f'viewBox="0 0 {WIDTH} {height}" font-family="-apple-system, BlinkMacSystemFont, '
        f'\'Segoe UI\', Roboto, Helvetica, Arial, sans-serif">'
    )
    parts.append(f"<defs>{markers}</defs>")
    parts.append(f'<rect width="{WIDTH}" height="{height}" fill="{BG}"/>')
    parts.append(
        "<style>"
        f".t{{fill:{INK}}} .dim{{fill:{DIM}}} .faint{{fill:{FAINT}}} "
        ".mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace}"
        f".edge-label{{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:11px;fill:{DIM}}}"
        "</style>"
    )

    # Title block
    parts.append(
        f'<text x="{MARGIN}" y="56" class="t" font-size="30" font-weight="700">{esc(MODEL["title"])}</text>'
        f'<text x="{MARGIN}" y="84" class="dim" font-size="15">{esc(MODEL["subtitle"])}</text>'
        f'<text x="{MARGIN}" y="106" class="faint" font-size="12.5">{esc(MODEL["note"])}</text>'
    )

    # Tier rails and cards
    for tier in MODEL["tiers"]:
        ty, th = tier["y"], tier["h"]
        parts.append(
            f'<rect x="{MARGIN}" y="{ty}" width="3" height="{th}" fill="{ACCENT}" opacity="0.55" rx="1.5"/>'
            f'<text x="{MARGIN + 14}" y="{ty + 18}" class="t" font-size="12.5" font-weight="700" '
            f'letter-spacing="1.1">{esc(tier["name"].upper())}</text>'
        )
        for i, line in enumerate(textwrap.wrap(tier["role"], 26)):
            parts.append(
                f'<text x="{MARGIN + 14}" y="{ty + 40 + i * 15}" class="faint" font-size="12">{esc(line)}</text>'
            )

    for node in nodes:
        x, y, w, h = node["x"], node["y"], node["w"], node["h"]
        parts.append(
            f'<rect x="{x:.0f}" y="{y}" width="{w:.0f}" height="{h}" rx="10" fill="{PANEL}" '
            f'stroke="{LINE}"/>'
        )
        steps = steps_by_node(node["id"])
        title_x = x + 14
        if steps:
            badge = ",".join(str(s) for s in steps)
            parts.append(
                f'<rect x="{x + 13:.0f}" y="{y + 13}" width="{9 + 8 * len(badge)}" height="18" rx="9" '
                f'fill="{ACCENT}" opacity="0.15"/>'
                f'<text x="{x + 17 + 4 * len(badge):.0f}" y="{y + 26}" text-anchor="middle" '
                f'font-size="11" font-weight="700" fill="{ACCENT}" class="mono">{badge}</text>'
            )
            title_x = x + 26 + 8 * len(badge)
        parts.append(
            f'<text x="{title_x:.0f}" y="{y + 26}" class="t" font-size="14.5" font-weight="650">'
            f'{esc(node["name"])}</text>'
        )
        for i, line in enumerate(node["meta_lines"]):
            parts.append(
                f'<text x="{x + 14:.0f}" y="{y + 44 + i * 14}" class="faint mono" font-size="11">{esc(line)}</text>'
            )
        top = card_geometry(node)[0]
        for i, line in enumerate(node["lines"]):
            parts.append(
                f'<text x="{x + 14:.0f}" y="{y + top + i * 17}" class="dim" font-size="12">{esc(line)}</text>'
            )

    # The golden path: numbered on the cards, drawn between them. Same-tier steps are
    # short hops through an 18px gutter, too narrow for a label, so the numbers carry
    # the order there and only the cross-tier steps are labelled.
    tier_index = {t["id"]: i for i, t in enumerate(MODEL["tiers"])}
    gap_use: dict[tuple[int, int], int] = {}
    for edge in MODEL["edges"]:
        if not edge.get("step"):
            continue
        a, b = at[edge["from"]], at[edge["to"]]
        color = MODEL["kinds"][edge["kind"]]["color"]
        ta, tb = tier_index[a["tier"]], tier_index[b["tier"]]
        if ta == tb:
            forward = b["x"] > a["x"]
            x1 = a["x"] + a["w"] + 2 if forward else a["x"] - 2
            x2 = b["x"] - 5 if forward else b["x"] + b["w"] + 5
            parts.append(connector(f"M {x1:.0f} {a['y'] + a['h'] / 2:.0f} H {x2:.0f}", color))
            continue

        key = (min(ta, tb), max(ta, tb))
        lane = gap_use.get(key, 0)
        gap_use[key] = lane + 1
        down = tb > ta
        y1 = a["y"] + a["h"] if down else a["y"]
        y2 = b["y"] - 7 if down else b["y"] + b["h"] + 7
        bx = b["x"] + b["w"] / 2
        if abs(ta - tb) > 1:
            # Skips a tier: run down the channel beside the rail rather than through
            # the cards in between.
            channel = MARGIN + RAIL - 16
            turn = b["y"] - 26
            path = (
                f"M {a['x']:.0f} {a['y'] + a['h'] / 2:.0f} H {channel:.0f} "
                f"V {turn:.0f} H {bx:.0f} V {y2:.0f}"
            )
            ly = in_gap(a["y"] + a["h"] + 20, a["y"] + a["h"], a["y"] + a["h"] + LANE_GAP)
            parts.append(connector(path, color, edge["label"], (channel + 10, ly)))
            continue

        ax = a["x"] + a["w"] / 2 + lane * 30
        mid = (y1 + y2) / 2 + (lane * 24 - 12)
        path = f"M {ax:.0f} {y1:.0f} V {mid:.0f} H {bx + lane * 30:.0f} V {y2:.0f}"
        parts.append(
            connector(path, color, edge["label"], (bx + lane * 30 + 12, in_gap(mid - 6, y1, y2)))
        )

    # Legend
    ly = height - FOOT + 30
    parts.append(
        f'<text x="{MARGIN}" y="{ly}" class="faint" font-size="12">'
        f'Numbers follow one case through the system. Full connections, including audit and '
        f'persistence, are in docs/architecture.html.</text>'
    )
    lx = MARGIN
    for kind in ("control", "advisory", "read", "write", "gate", "escalate"):
        color = kinds[kind]["color"]
        parts.append(
            f'<line x1="{lx}" y1="{ly + 24}" x2="{lx + 22}" y2="{ly + 24}" stroke="{color}" stroke-width="2"/>'
            f'<text x="{lx + 30}" y="{ly + 28}" class="dim" font-size="12">{esc(kinds[kind]["label"])}</text>'
        )
        lx += 42 + 7.6 * len(kinds[kind]["label"])
    parts.append("</svg>")
    return "\n".join(parts)


# --- interactive page -------------------------------------------------------

PAGE_STYLE = f"""
:root {{
  --bg: {BG}; --panel: {PANEL}; --panel-2: {PANEL_2}; --line: {LINE};
  --ink: {INK}; --dim: {DIM}; --faint: {FAINT}; --accent: {ACCENT};
  --sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  --mono: ui-monospace, SFMono-Regular, "SF Mono", Menlo, monospace;
}}
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: var(--bg); color: var(--ink); font-family: var(--sans);
        font-size: 14px; line-height: 1.5; -webkit-font-smoothing: antialiased; }}
.wrap {{ max-width: 1440px; margin: 0 auto; padding: 28px 24px 64px; }}
header h1 {{ margin: 0; font-size: clamp(24px, 3.4vw, 34px); letter-spacing: -0.4px; text-wrap: balance; }}
header p {{ margin: 8px 0 0; color: var(--dim); max-width: 68ch; }}
header .note {{ color: var(--faint); font-size: 12.5px; }}
.hint {{ display: flex; align-items: center; gap: 10px; margin: 18px 0 6px; color: var(--faint);
         font-size: 12.5px; font-family: var(--mono); }}
.hint .dot {{ width: 7px; height: 7px; border-radius: 50%; background: var(--accent); flex: none;
              animation: pulse 2.4s ease-in-out infinite; }}
@keyframes pulse {{ 0%, 100% {{ opacity: .35; }} 50% {{ opacity: 1; }} }}

.board {{ position: relative; }}
.edges {{ position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; z-index: 2; }}
.tier {{ display: grid; grid-template-columns: 168px 1fr; gap: 18px; align-items: start;
         padding: 18px 0; border-top: 1px solid var(--line); }}
.tier:first-of-type {{ border-top: 0; }}
.rail {{ position: sticky; top: 12px; }}
.rail h2 {{ margin: 0 0 6px; font-size: 12.5px; letter-spacing: 1.4px; text-transform: uppercase;
            color: var(--ink); }}
.rail p {{ margin: 0; color: var(--faint); font-size: 12px; }}
.rail .bar {{ width: 26px; height: 3px; border-radius: 2px; background: var(--accent); opacity: .55;
              margin-bottom: 10px; }}
.cards {{ display: grid; gap: 14px; grid-template-columns: repeat(auto-fit, minmax(min(210px, 100%), 1fr)); }}
.node {{ position: relative; z-index: 3; text-align: left; display: flex; flex-direction: column; gap: 6px;
         background: var(--panel); border: 1px solid var(--line); border-radius: 10px; padding: 13px 14px;
         color: inherit; font: inherit; cursor: pointer;
         transition: opacity .18s ease, border-color .18s ease, background .18s ease, transform .18s ease; }}
.node:focus-visible {{ outline: 2px solid var(--accent); outline-offset: 3px; }}
.node .top {{ display: flex; align-items: center; gap: 8px; }}
.node .step {{ font-family: var(--mono); font-size: 11px; font-weight: 700; color: var(--accent);
               background: rgba(94, 234, 212, .14); border-radius: 9px; padding: 1px 7px; }}
.node h3 {{ margin: 0; font-size: 14.5px; font-weight: 650; }}
.node .meta {{ font-family: var(--mono); font-size: 11px; color: var(--faint); }}
.node ul {{ margin: 2px 0 0; padding-left: 15px; color: var(--dim); font-size: 12.5px; }}
.node li + li {{ margin-top: 3px; }}

.board.active .node {{ opacity: .26; }}
.board.active .node.is-linked {{ opacity: 1; border-color: color-mix(in srgb, var(--accent) 45%, var(--line)); }}
.board.active .node.is-source {{ opacity: 1; border-color: var(--accent); background: var(--panel-2);
                                 transform: translateY(-1px); }}
.board.active .tier {{ border-color: var(--line); }}

.panel {{ position: sticky; bottom: 12px; margin-top: 22px; border: 1px solid var(--line);
          border-radius: 10px; background: var(--panel); padding: 16px 18px; min-height: 128px;
          box-shadow: 0 12px 32px rgba(0, 0, 0, .45); }}
.panel .empty {{ color: var(--faint); }}
.panel h3 {{ margin: 0 0 2px; font-size: 16px; }}
.panel .where {{ font-family: var(--mono); font-size: 11.5px; color: var(--faint); }}
.links {{ display: grid; gap: 10px; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); margin-top: 14px; }}
.links h4 {{ margin: 0 0 6px; font-size: 11.5px; letter-spacing: 1.2px; text-transform: uppercase;
             color: var(--faint); }}
.links li {{ list-style: none; display: flex; gap: 8px; align-items: baseline; padding: 3px 0;
             font-size: 12.5px; color: var(--dim); }}
.links ul {{ margin: 0; padding: 0; }}
.links .dirn {{ font-family: var(--mono); font-size: 11px; flex: none; }}
.links .who {{ color: var(--ink); }}

.legend {{ display: flex; flex-wrap: wrap; gap: 14px 20px; margin-top: 20px; color: var(--dim);
           font-size: 12px; }}
.legend span {{ display: inline-flex; align-items: center; gap: 7px; }}
.legend i {{ width: 22px; height: 2px; border-radius: 2px; display: inline-block; }}

.link {{ fill: none; stroke-width: 1.7; opacity: 0; transition: opacity .18s ease; }}
.board.active .link.is-live {{ opacity: .95; stroke-dasharray: 7 7; animation: flow 1.1s linear infinite; }}
@keyframes flow {{ to {{ stroke-dashoffset: -28; }} }}
@media (prefers-reduced-motion: reduce) {{
  .board.active .link.is-live {{ animation: none; stroke-dasharray: none; }}
  .hint .dot {{ animation: none; opacity: .8; }}
}}
@media (max-width: 760px) {{
  .tier {{ grid-template-columns: 1fr; }}
  .rail {{ position: static; }}
  .edges {{ display: none; }}
}}
"""

PAGE_SCRIPT = """
const MODEL = __DATA__;
const byId = {};
MODEL.tiers.forEach(t => t.nodes.forEach(n => { byId[n.id] = { ...n, tier: t }; }));
const board = document.querySelector('.board');
const svg = document.querySelector('.edges');
const panel = document.querySelector('.panel');
const cards = new Map([...document.querySelectorAll('.node')].map(el => [el.dataset.id, el]));
const paths = new Map();
let pinned = null;

for (const [i, edge] of MODEL.edges.entries()) {
  const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  path.setAttribute('class', 'link');
  path.setAttribute('stroke', MODEL.kinds[edge.kind].color);
  path.setAttribute('marker-end', 'url(#head-' + edge.kind + ')');
  svg.appendChild(path);
  paths.set(i, path);
}

function anchors(a, b) {
  const board_box = board.getBoundingClientRect();
  const p = cards.get(a).getBoundingClientRect();
  const q = cards.get(b).getBoundingClientRect();
  const rel = box => ({ x: box.left - board_box.left, y: box.top - board_box.top, w: box.width, h: box.height });
  const s = rel(p), t = rel(q);
  const sameRow = Math.abs(s.y - t.y) < 8;
  if (sameRow) {
    const forward = t.x > s.x;
    return {
      x1: forward ? s.x + s.w : s.x, y1: s.y + s.h / 2,
      x2: forward ? t.x : t.x + t.w, y2: t.y + t.h / 2, bend: 'h',
    };
  }
  const down = t.y > s.y;
  return {
    x1: s.x + s.w / 2, y1: down ? s.y + s.h : s.y,
    x2: t.x + t.w / 2, y2: down ? t.y : t.y + t.h, bend: 'v',
  };
}

function drawEdges() {
  const box = board.getBoundingClientRect();
  svg.setAttribute('viewBox', `0 0 ${box.width} ${box.height}`);
  MODEL.edges.forEach((edge, i) => {
    const { x1, y1, x2, y2, bend } = anchors(edge.from, edge.to);
    const d = bend === 'h'
      ? `M ${x1} ${y1} C ${(x1 + x2) / 2} ${y1}, ${(x1 + x2) / 2} ${y2}, ${x2} ${y2}`
      : `M ${x1} ${y1} C ${x1} ${(y1 + y2) / 2}, ${x2} ${(y1 + y2) / 2}, ${x2} ${y2}`;
    paths.get(i).setAttribute('d', d);
  });
}

function describe(id) {
  const node = byId[id];
  const out = MODEL.edges.filter(e => e.from === id);
  const into = MODEL.edges.filter(e => e.to === id);
  const list = (edges, dir) => edges.map(e => {
    const other = byId[dir === 'out' ? e.to : e.from];
    const arrow = dir === 'out' ? '&rarr;' : '&larr;';
    return `<li><span class="dirn" style="color:${MODEL.kinds[e.kind].color}">${arrow}</span>
      <span><span class="who">${other.name}</span> — ${e.label}</span></li>`;
  }).join('') || '<li>Nothing</li>';
  panel.innerHTML = `
    <h3>${node.name}</h3>
    <div class="where">${node.tier.name} · ${node.meta}</div>
    <div class="links">
      <div><h4>Sends</h4><ul>${list(out, 'out')}</ul></div>
      <div><h4>Receives</h4><ul>${list(into, 'in')}</ul></div>
    </div>`;
}

function show(id) {
  board.classList.add('active');
  cards.forEach((el, key) => {
    el.classList.toggle('is-source', key === id);
    el.classList.remove('is-linked');
  });
  MODEL.edges.forEach((edge, i) => {
    const live = edge.from === id || edge.to === id;
    paths.get(i).classList.toggle('is-live', live);
    if (live) {
      // The dash animation always runs source to target, so direction reads off the page.
      paths.get(i).style.animationDirection = edge.from === id ? 'normal' : 'normal';
      cards.get(edge.from === id ? edge.to : edge.from).classList.add('is-linked');
    }
  });
  describe(id);
}

function clear() {
  if (pinned) return;
  board.classList.remove('active');
  cards.forEach(el => el.classList.remove('is-source', 'is-linked'));
  paths.forEach(p => p.classList.remove('is-live'));
  panel.innerHTML = '<p class="empty">Hover a component to see what it connects to, and which way the data moves. Click to keep it.</p>';
}

cards.forEach((el, id) => {
  el.addEventListener('mouseenter', () => { if (!pinned) show(id); });
  el.addEventListener('focus', () => { if (!pinned) show(id); });
  el.addEventListener('mouseleave', clear);
  el.addEventListener('blur', clear);
  el.addEventListener('click', () => {
    pinned = pinned === id ? null : id;
    if (pinned) { show(id); } else { clear(); }
  });
});
document.addEventListener('keydown', e => { if (e.key === 'Escape') { pinned = null; clear(); } });

const redraw = () => requestAnimationFrame(drawEdges);
window.addEventListener('resize', redraw);
if (document.fonts && document.fonts.ready) document.fonts.ready.then(redraw);
drawEdges();
clear();
"""


def page_body() -> str:
    kinds = MODEL["kinds"]
    heads = "".join(
        f'<marker id="head-{k}" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5.5" '
        f'markerHeight="5.5" orient="auto-start-reverse">'
        f'<path d="M 0 0 L 10 5 L 0 10 z" fill="{v["color"]}"/></marker>'
        for k, v in kinds.items()
    )
    tiers = []
    for tier in MODEL["tiers"]:
        cards = []
        for node in tier["nodes"]:
            steps = steps_by_node(node["id"])
            badge = (
                f'<span class="step">{",".join(str(s) for s in steps)}</span>' if steps else ""
            )
            items = "".join(f"<li>{esc(f)}</li>" for f in node["functions"])
            cards.append(
                f'<button class="node" type="button" data-id="{node["id"]}">'
                f'<span class="top">{badge}<h3>{esc(node["name"])}</h3></span>'
                f'<span class="meta">{esc(node["meta"])}</span>'
                f"<ul>{items}</ul></button>"
            )
        tiers.append(
            f'<section class="tier"><div class="rail"><div class="bar"></div>'
            f'<h2>{esc(tier["name"])}</h2><p>{esc(tier["role"])}</p></div>'
            f'<div class="cards">{"".join(cards)}</div></section>'
        )
    legend = "".join(
        f'<span><i style="background:{v["color"]}"></i>{esc(v["label"])}</span>' for v in kinds.values()
    )
    script = PAGE_SCRIPT.replace("__DATA__", json.dumps(MODEL))
    return f"""<title>OneDecision architecture</title>
<style>{PAGE_STYLE}</style>
<div class="wrap">
  <header>
    <h1>{esc(MODEL["title"])}</h1>
    <p>{esc(MODEL["subtitle"])}</p>
    <p class="note">{esc(MODEL["note"])}</p>
  </header>
  <div class="hint"><span class="dot"></span>Hover a component: its connections light up and the data animates in the direction it flows. Click to keep it, Escape to release.</div>
  <div class="board">
    <svg class="edges" aria-hidden="true"><defs>{heads}</defs></svg>
    {"".join(tiers)}
  </div>
  <div class="panel"></div>
  <div class="legend">{legend}</div>
</div>
<script>{script}</script>
"""


def main() -> None:
    (DOCS / "architecture.svg").write_text(build_svg() + "\n")
    body = page_body()
    (DOCS / "architecture.html").write_text(
        '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"{body}</html>\n"
    )
    ARTIFACT_OUT.mkdir(parents=True, exist_ok=True)
    (ARTIFACT_OUT / "architecture-artifact.html").write_text(body)
    nodes = sum(len(t["nodes"]) for t in MODEL["tiers"])
    print(
        f"wrote docs/architecture.svg, docs/architecture.html, and "
        f"{ARTIFACT_OUT.name}/architecture-artifact.html: "
        f"{len(MODEL['tiers'])} tiers, {nodes} components, {len(MODEL['edges'])} connections"
    )


if __name__ == "__main__":
    main()
