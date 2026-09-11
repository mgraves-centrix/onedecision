"""Render a terminal-style screen from real `agentcore invoke --json` output.

Usage: python tools/video/render_terminal.py [agentcore-output.json]
Defaults to agentcore-result.json: the handler's result from a real
`agentcore invoke "Investigate CASE-2001" --json`, kept without the CLI's session
ID and local log path. Shows the exact command that was run and the fields the
narration discusses, verbatim, with a line saying the response is trimmed.
Writes var/video/terminal.html for record_terminal.py.
"""

from __future__ import annotations

import html
import json
import sys
from pathlib import Path

from paths import HERE, OUT

COMMAND = 'agentcore invoke "Investigate CASE-2001" --json'


def find_result(obj):
    """The handler's result sits somewhere inside the CLI's JSON envelope."""
    if isinstance(obj, dict):
        if "case_id" in obj and "outcome" in obj:
            return obj
        for value in obj.values():
            found = find_result(value)
            if found:
                return found
    elif isinstance(obj, list):
        for value in obj:
            found = find_result(value)
            if found:
                return found
    elif isinstance(obj, str):
        try:
            return find_result(json.loads(obj))
        except ValueError:
            return None
    return None


def main() -> None:
    source = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "agentcore-result.json"
    result = find_result(json.loads(source.read_text()))
    if result is None:
        raise SystemExit("no handler result found in the AgentCore output")
    card = result.get("decision_card") or {}
    excerpt = {
        "case_id": result.get("case_id"),
        "outcome": result.get("outcome"),
        "status": result.get("status"),
        "model_provider": result.get("model_provider"),
        "tool_calls": [c.get("name") if isinstance(c, dict) else c for c in result.get("tool_calls") or []],
        "decision_card": {
            "headline": card.get("headline"),
            "recommended_action": card.get("recommended_action"),
        },
    }
    lines = json.dumps(excerpt, indent=2).splitlines()
    body = "\n".join(f'<div class="ln">{html.escape(line)}</div>' for line in lines)
    page = f"""<!doctype html><html><head><meta charset="utf-8"><title>AgentCore invoke</title>
<style>
  html, body {{ margin: 0; height: 100%; background: #10131a; }}
  body {{ display: grid; place-items: center; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }}
  .win {{ width: 1360px; background: #0b0e14; border: 1px solid #2a3140; border-radius: 12px;
          box-shadow: 0 30px 80px rgba(0,0,0,.45); overflow: hidden; }}
  .bar {{ display: flex; align-items: center; gap: 8px; padding: 12px 16px; background: #171b24;
          border-bottom: 1px solid #2a3140; color: #9aa4b6; font-size: 14px; }}
  .dot {{ width: 12px; height: 12px; border-radius: 50%; background: #3b4256; }}
  .bar span {{ margin-left: 10px; }}
  .term {{ padding: 22px 26px 26px; font-size: 19px; line-height: 1.5; color: #e6e9ef; white-space: pre-wrap; }}
  /* Only the rows keep their whitespace; the newlines between them would otherwise
     render as blank lines and push the window past the viewport. */
  #out {{ white-space: normal; }}
  .ln {{ white-space: pre-wrap; }}
  .prompt {{ color: #5eead4; }}
  .ln, .note {{ opacity: 0; transition: opacity .25s; }}
  .ln.on, .note.on {{ opacity: 1; }}
  .note {{ color: #6b7488; margin-top: 10px; }}
  .caret {{ display: inline-block; width: 10px; background: #e6e9ef; animation: blink 1s steps(1) infinite; }}
  @keyframes blink {{ 50% {{ opacity: 0; }} }}
</style></head><body>
<div class="win">
  <div class="bar"><i class="dot"></i><i class="dot"></i><i class="dot"></i><span>onedecision · Amazon Bedrock AgentCore Runtime · us-west-2</span></div>
  <div class="term"><span class="prompt">$ </span><span id="cmd"></span><span class="caret" id="caret">&nbsp;</span>
<div id="out">{body}<div class="note">&#35; response trimmed to the fields discussed</div></div></div>
</div>
<script>
  const total = parseFloat(new URLSearchParams(location.search).get('d') || '12');
  const cmd = {json.dumps(COMMAND)};
  const el = document.getElementById('cmd');
  let i = 0;
  const typeMs = 45;
  const typer = setInterval(() => {{
    el.textContent = cmd.slice(0, ++i);
    if (i >= cmd.length) {{
      clearInterval(typer);
      document.getElementById('caret').remove();
      const rows = [...document.querySelectorAll('.ln, .note')];
      const spread = Math.max(1500, (total * 1000) * 0.45);
      rows.forEach((r, k) => setTimeout(() => r.classList.add('on'), 600 + (spread / rows.length) * k));
    }}
  }}, typeMs);
</script>
</body></html>"""
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "terminal.html").write_text(page)
    print(f"terminal.html written: {excerpt['case_id']} {excerpt['outcome']} via {excerpt['model_provider']}, "
          f"{len(excerpt['tool_calls'])} tool calls")


if __name__ == "__main__":
    main()
