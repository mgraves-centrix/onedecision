"""Record the demo in a real, visible Google Chrome window, captured from the screen.

Usage: python tools/video/record_live.py [base_url] [--preview]

Playwright drives the installed Google Chrome in a window of its own, centered on
a display at 1x scaling (an external monitor), and ffmpeg captures that window
from the screen at 1920x1080, one screen pixel per video pixel: tab, address bar,
and page exactly as a person would see them. The pointer glides to each control
before it is clicked, and the approval token is typed key by key. The pointer is
drawn in the page, because synthetic input does not move the macOS cursor; the
real cursor is left out of the capture.

Long server calls (the model investigating, proposing a policy, replaying it) are
recorded but marked as cuts in var/video/timeline.json, so the video shows the
click and the result without minutes of loading. The phone beat is a headless
phone-sized stand-in, and the AgentCore beat is spliced in afterward by
record_terminal.py. --preview opens the window, checks the geometry, zoom, and
pointer, saves one captured frame to var/video/preview.png, and exits without
resetting the demo data.
"""

from __future__ import annotations

import json
import math
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import urllib.request

from playwright.sync_api import Page, sync_playwright

from paths import OUT, REPO

ARGS = [a for a in sys.argv[1:] if not a.startswith("--")]
PREVIEW = "--preview" in sys.argv
BASE = ARGS[0] if ARGS else "http://onedecision.localhost:8000"
TOKEN = os.environ.get("ONEDECISION_APPROVAL_TOKEN", "replace-me-local-demo-token")
DUR: dict[str, float] = json.loads((OUT / "durations.json").read_text())
RAW = OUT / "raw"
PHONE = {"width": 390, "height": 844}
LONG_MS = 300_000  # a model call on Bedrock can take minutes
WIN = (1920, 1080)  # the Chrome window, and so the video frame
ZOOM = 1.25  # Chrome's own page zoom, so the app reads at a normal size in 1080p
FPS = 30

SPOT_CSS = """html { scroll-behavior: smooth; }
.__spot { outline: 3px solid #5eead4 !important; outline-offset: 4px;
          box-shadow: 0 0 0 8px rgba(94, 234, 212, .16) !important; border-radius: 8px; }
.__ring { position: fixed; width: 34px; height: 34px; margin: -17px 0 0 -17px; border-radius: 50%;
          border: 2px solid #5eead4; pointer-events: none; z-index: 2147483646;
          animation: __ring .45s ease-out forwards; }
@keyframes __ring { from { transform: scale(.3); opacity: 1; } to { transform: scale(1.5); opacity: 0; } }
#__ptr { position: fixed; left: 0; top: 0; z-index: 2147483647; pointer-events: none;
         transform: translate(-100px, -100px); filter: drop-shadow(0 1px 1.5px rgba(0, 0, 0, .5)); }"""

POINTER_SVG = (
    '<svg width="22" height="30" viewBox="0 0 22 30"><path d="M2 2v22l5.6-5.3 3.7 8.6 3.9-1.7'
    '-3.7-8.4H19z" fill="#111" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/></svg>'
)


def init_script(pointer: bool) -> str:
    """Highlight and click-ripple styles for every page; the drawn pointer on desktop only."""
    return """
document.addEventListener('DOMContentLoaded', () => {
  const s = document.createElement('style');
  s.textContent = %s;
  document.head.appendChild(s);
  window.__ripple = (x, y) => {
    const r = document.createElement('div');
    r.className = '__ring';
    r.style.left = x + 'px';
    r.style.top = y + 'px';
    document.body.appendChild(r);
    setTimeout(() => r.remove(), 600);
  };
  if (!%s) return;
  const p = document.createElement('div');
  p.id = '__ptr';
  p.innerHTML = %s;
  document.body.appendChild(p);
  const place = (x, y) => { p.style.transform = `translate(${x - 2}px, ${y - 2}px)`; };
  // Keep the pointer where it was across page loads, as a real cursor would be.
  const saved = JSON.parse(sessionStorage.getItem('__ptr') || 'null');
  if (saved) place(saved[0], saved[1]);
  addEventListener('mousemove', e => {
    place(e.clientX, e.clientY);
    sessionStorage.setItem('__ptr', JSON.stringify([e.clientX, e.clientY]));
  }, true);
});
""" % (json.dumps(SPOT_CSS), "true" if pointer else "false", json.dumps(POINTER_SVG))


SEGMENTS: list[dict] = []


class Recorder:
    """Tracks which stretches of one video belong to which beat."""

    def __init__(self, page: Page, source: str):
        self.page, self.source = page, source
        self.origin = time.monotonic()
        self.open: tuple[str, float] | None = None

    def now(self) -> float:
        return time.monotonic() - self.origin

    def show(self, beat: str) -> None:
        self.open = (beat, self.now())

    def cut(self) -> None:
        beat, start = self.open
        SEGMENTS.append(
            {"beat": beat, "source": self.source, "start": round(start, 3), "end": round(self.now(), 3)}
        )
        self.open = None

    def elapsed(self, beat: str) -> float:
        done = sum(s["end"] - s["start"] for s in SEGMENTS if s["beat"] == beat)
        if self.open and self.open[0] == beat:
            done += self.now() - self.open[1]
        return done

    def hold(self, beat: str, fraction: float) -> None:
        """Wait until this beat has been on screen for `fraction` of its narration."""
        target = DUR[beat] * fraction
        while self.elapsed(beat) < target:
            time.sleep(0.03)


class Pointer:
    """The drawn pointer. Real mouse events, moved in small eased steps."""

    def __init__(self, page: Page):
        self.page = page
        self.x, self.y = WIN[0] / ZOOM * 0.62, WIN[1] / ZOOM * 0.55

    def glide(self, x: float, y: float, dur: float = 0.55) -> None:
        n = max(10, int(dur * 60))
        x0, y0 = self.x, self.y
        for i in range(1, n + 1):
            t = i / n
            e = t * t * (3 - 2 * t)
            self.page.mouse.move(x0 + (x - x0) * e, y0 + (y - y0) * e)
            time.sleep(dur / n)
        self.x, self.y = x, y

    def to(self, selector: str, where: str = "center") -> tuple[float, float]:
        box = self.page.locator(selector).first.bounding_box()
        if where == "center":
            x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        else:  # rest beside content being read, not on top of it
            x, y = box["x"] + min(18, box["width"] / 2), box["y"] + min(26, box["height"] / 2)
        self.glide(x, y)
        return x, y


def spot(page: Page, selector: str, ptr: Pointer | None = None, where: str = "edge") -> None:
    page.evaluate("() => document.querySelectorAll('.__spot').forEach(e => e.classList.remove('__spot'))")
    page.locator(selector).first.evaluate(
        "el => { el.classList.add('__spot'); el.scrollIntoView({behavior: 'smooth', block: 'center'}); }"
    )
    time.sleep(0.6)
    if ptr:
        ptr.to(selector, where)


def press(page: Page, selector: str, ptr: Pointer | None) -> None:
    """Glide to a control and press it: a ripple where the pointer (or finger) lands."""
    if ptr:
        x, y = ptr.to(selector)
    else:
        box = page.locator(selector).first.bounding_box()
        x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    page.evaluate("([x, y]) => window.__ripple && window.__ripple(x, y)", [x, y])
    time.sleep(0.15)


def click_and_skip_wait(rec: Recorder, beat: str, selector: str, ptr: Pointer | None) -> None:
    """Click a control that starts a slow server call: show the click, skip the wait."""
    press(rec.page, selector, ptr)
    # Playwright's click() blocks until the navigation it starts commits, which is
    # the whole model call, so the cut would land after the wait. A DOM click
    # returns at once; expect_navigation does the waiting, off camera.
    with rec.page.expect_navigation(timeout=LONG_MS):
        rec.page.locator(selector).first.evaluate("el => el.click()")
        time.sleep(0.35)
        rec.cut()
    rec.show(beat)
    time.sleep(0.2)


def follow(page: Page, selector: str, ptr: Pointer) -> None:
    """A quick, on-camera navigation, such as a nav link or a case card."""
    press(page, selector, ptr)
    with page.expect_navigation(timeout=60_000):
        page.locator(selector).first.evaluate("el => el.click()")
    time.sleep(0.3)


def post(path: str) -> None:
    urllib.request.urlopen(urllib.request.Request(BASE + path, method="POST"), timeout=120)


def check_in(case_id: str) -> str:
    return f'.dock-list li:has(code:text-is("{case_id}")) button'


def case_card(case_id: str) -> str:
    return f'a.case:has(code:text-is("{case_id}"))'


def nav(href: str) -> str:
    return f'nav a[href="{href}"]'


# --- the screen, the window, and the capture -------------------------------------


def pick_display() -> tuple[tuple[int, int], tuple[int, int], tuple[int, int]]:
    """The first display at 1x scaling with room for the window.

    Returns the display's size in pixels, the window's top-left in the global
    coordinates Chrome uses, and the window's offset within the display, which is
    the capture's crop.
    """
    js = ('ObjC.import("AppKit"); const s = $.NSScreen.screens; const r = [];'
          "for (let i = 0; i < s.count; i++) { const n = s.objectAtIndex(i), f = n.frame, v = n.visibleFrame;"
          " r.push([f.origin.x, f.origin.y, f.size.width, f.size.height,"
          " v.origin.x, v.origin.y, v.size.width, v.size.height, n.backingScaleFactor]); }"
          " JSON.stringify(r)")
    out = subprocess.run(["osascript", "-l", "JavaScript", "-e", js], check=True, capture_output=True, text=True)
    screens = json.loads(out.stdout)
    main_height = screens[0][3]  # AppKit counts up from the main display's bottom edge
    for fx, fy, fw, fh, vx, vy, vw, vh, scale in screens:
        if scale == 1 and vw >= WIN[0] and vh >= WIN[1]:
            top = main_height - (fy + fh)  # the display's top edge, counting down
            visible_top = main_height - (vy + vh)  # below any menu bar
            win = (int(vx + (vw - WIN[0]) // 2), int(visible_top + (vh - WIN[1]) // 2))
            return (int(fw), int(fh)), win, (int(win[0] - fx), int(win[1] - top))
    sys.exit("recording needs a display at 1x scaling with room for a 1920x1080 window, such as an "
             "external 1440p monitor; see tools/video/README.md")


def capture_device(size: tuple[int, int]) -> str:
    listing = subprocess.run(
        ["ffmpeg", "-hide_banner", "-f", "avfoundation", "-list_devices", "true", "-i", ""],
        capture_output=True, text=True,
    ).stderr
    for index in re.findall(r"\[(\d+)\] Capture screen \d+", listing):
        probe = subprocess.run(
            ["ffmpeg", "-hide_banner", "-f", "avfoundation", "-capture_cursor", "0",
             "-i", f"{index}:none", "-frames:v", "1", "-f", "null", "-"],
            capture_output=True, text=True,
        ).stderr
        if f"{size[0]}x{size[1]}" in probe:
            return index
    sys.exit("no screen-capture device matches the chosen display; is Screen Recording allowed "
             "for this terminal in System Settings > Privacy & Security?")


def chrome_profile() -> str:
    """A throwaway Chrome profile whose default page zoom is ZOOM."""
    OUT.mkdir(parents=True, exist_ok=True)
    d = tempfile.mkdtemp(prefix="chrome-profile-", dir=OUT)
    os.mkdir(os.path.join(d, "Default"))
    level = math.log(ZOOM) / math.log(1.2)  # Chrome stores zoom as a power of 1.2
    prefs = {
        "partition": {"default_zoom_level": {"x": level}},
        # The approval token goes in a password field; keep Chrome from offering to save it.
        "credentials_enable_service": False,
        "profile": {"password_manager_enabled": False, "password_manager_leak_detection": False},
    }
    with open(os.path.join(d, "Default", "Preferences"), "w") as f:
        json.dump(prefs, f)
    return d


def start_capture(device: str, crop: tuple[int, int], out) -> subprocess.Popen:
    return subprocess.Popen(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "avfoundation", "-capture_cursor", "0",
         "-capture_mouse_clicks", "0", "-framerate", str(FPS), "-i", f"{device}:none",
         "-vf", f"crop={WIN[0]}:{WIN[1]}:{crop[0]}:{crop[1]},format=yuv420p",
         "-fps_mode", "cfr", "-r", str(FPS), "-c:v", "h264_videotoolbox", "-b:v", "20M", str(out)],
        stdin=subprocess.DEVNULL,
    )


def find_flash(video) -> float:
    """Seconds into the capture when the magenta sync frame first shows."""
    cx, cy = WIN[0] // 2, WIN[1] // 2
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(video), "-t", "60", "-vf", f"crop=4:4:{cx}:{cy},scale=1:1",
         "-fps_mode", "passthrough", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        check=True, capture_output=True,
    ).stdout
    for i in range(len(raw) // 3):
        r, g, b = raw[3 * i:3 * i + 3]
        if r > 200 and g < 90 and b > 200:
            return i / FPS
    sys.exit("sync flash not found in the capture; is the Chrome window where the capture expects it?")


def main() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    size, win, crop = pick_display()
    device = capture_device(size)
    profile = chrome_profile()
    screen_video = RAW / "screen" / "capture.mov"
    screen_video.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            profile, channel="chrome", headless=False, no_viewport=True,
            # Without these, Chrome shows the automation and --no-sandbox infobars.
            chromium_sandbox=True, ignore_default_args=["--enable-automation"],
            args=[f"--window-position={win[0]},{win[1]}", f"--window-size={WIN[0]},{WIN[1]}",
                  "--hide-crash-restore-bubble",
                  # A dark window frame to match the app; the app is dark either way.
                  "--force-dark-mode"],
        )
        ctx.add_init_script(init_script(pointer=True))
        ctx.set_default_navigation_timeout(LONG_MS)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.bring_to_front()
        ptr = Pointer(page)

        if PREVIEW:
            page.goto(BASE + "/")
            x, y = ptr.to(nav("/dashboard"))
            info = page.evaluate(
                "([x, y]) => ({dpr: devicePixelRatio, inner: [innerWidth, innerHeight],"
                " screen: [screenX, screenY, outerWidth, outerHeight],"
                " hit: !!document.elementFromPoint(x, y)?.closest('nav a[href=\"/dashboard\"]'),"
                " pointer: JSON.parse(sessionStorage.getItem('__ptr') || 'null')})",
                [x, y],
            )
            time.sleep(0.5)
            subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error", "-f", "avfoundation", "-capture_cursor", "0",
                 "-i", f"{device}:none", "-frames:v", "1",
                 "-vf", f"crop={WIN[0]}:{WIN[1]}:{crop[0]}:{crop[1]}", str(OUT / "preview.png")],
                check=True,
            )
            ctx.close()
            shutil.rmtree(profile, ignore_errors=True)
            print(f"device {device}; window at {win}; page {info}")
            print(f"pointer aimed at ({x:.0f}, {y:.0f}); var/video/preview.png written")
            return

        post("/demo/reset")  # off camera: the Dashboard at the end counts only this take
        cap = start_capture(device, crop, screen_video)
        time.sleep(1.5)  # let the capture settle before anything happens
        d = Recorder(page, "desktop")

        # Sync: one magenta frame, found later in the capture to line up the clocks.
        page.set_content("<body style='margin:0;height:100vh;background:#ff00ff'></body>")
        page.evaluate("() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))")
        flash_at = d.now()
        time.sleep(1.0)

        # 1 · the problem
        page.goto(BASE + "/")
        d.show("problem")
        ptr.glide(ptr.x, ptr.y, 0.2)  # bring the pointer into view
        d.hold("problem", 0.3)
        spot(page, ".policy-strip", ptr)
        d.hold("problem", 1.0)
        d.cut()

        # 2 · an exception arrives
        d.show("arrive")
        spot(page, check_in("CASE-2001"), ptr, "center")
        d.hold("arrive", 0.16)
        click_and_skip_wait(d, "arrive", check_in("CASE-2001"), ptr)
        exception_url = page.url
        spot(page, "table.evidence", ptr)
        d.hold("arrive", 0.5)
        spot(page, "table.evidence td.tool >> nth=1", ptr, "center")
        d.hold("arrive", 0.72)
        spot(page, "ul.boundaries", ptr)
        d.hold("arrive", 1.0)
        d.cut()

        # 3 · Dana decides from her phone (stand-in for real phone footage)
        phone_browser = p.chromium.launch()
        phone_ctx = phone_browser.new_context(
            viewport=PHONE, device_scale_factor=2, is_mobile=True, has_touch=True,
            record_video_dir=str(RAW / "phone"), record_video_size=PHONE,
        )
        phone_ctx.add_init_script(init_script(pointer=False))
        phone_ctx.set_default_navigation_timeout(LONG_MS)
        phone = phone_ctx.new_page()
        ph = Recorder(phone, "phone")
        phone.goto(exception_url)
        ph.show("phone")
        spot(phone, 'button:has-text("Approve and teach")')
        ph.hold("phone", 0.5)
        click_and_skip_wait(ph, "phone", 'button:has-text("Approve and teach")', None)
        # The confirmation sits just below the buttons; the proposed policy is a long
        # scroll away on a phone and would be caught mid-scroll.
        spot(phone, "p.decided")
        ph.hold("phone", 1.0)
        ph.cut()
        phone_video = phone.video.path()
        phone_ctx.close()
        phone_browser.close()

        # 4 · teach, then replay
        page.reload()
        d.show("teach")
        spot(page, "ul.conditions", ptr)
        d.hold("teach", 0.34)
        spot(page, "ul.actions-list", ptr)
        d.hold("teach", 0.62)
        spot(page, ".replay-grid", ptr)
        d.hold("teach", 1.0)
        d.cut()

        # 5 · explicit activation
        d.show("activate")
        spot(page, ".activation", ptr)
        d.hold("activate", 0.25)
        token = 'input[name="approval_token"]'
        press(page, token, ptr)
        page.locator(token).first.focus()
        page.keyboard.type(TOKEN, delay=55)
        click_and_skip_wait(d, "activate", 'button:has-text("Activate this policy version")', ptr)
        spot(page, ".policy-version.status-active header", ptr)
        d.hold("activate", 1.0)
        d.cut()

        # 6 · the next hundred
        d.show("next")
        follow(page, nav("/"), ptr)
        spot(page, check_in("CASE-2002"), ptr, "center")
        d.hold("next", 0.14)
        click_and_skip_wait(d, "next", check_in("CASE-2002"), ptr)
        spot(page, case_card("CASE-2002"), ptr, "center")
        d.hold("next", 0.3)
        follow(page, case_card("CASE-2002"), ptr)
        spot(page, "ol.timeline li.ev-action >> nth=0", ptr)
        d.hold("next", 0.68)
        spot(page, "ol.timeline li.ev-verification >> nth=0", ptr)
        d.hold("next", 1.0)
        d.cut()

        # 7 · the boundary holds
        d.show("boundary")
        follow(page, nav("/"), ptr)
        spot(page, check_in("CASE-2003"), ptr, "center")
        d.hold("boundary", 0.14)
        click_and_skip_wait(d, "boundary", check_in("CASE-2003"), ptr)
        spot(page, case_card("CASE-2003"), ptr, "center")
        d.hold("boundary", 0.26)
        follow(page, case_card("CASE-2003"), ptr)
        spot(page, "section.card.danger", ptr)
        d.hold("boundary", 1.0)
        d.cut()

        # 8 · AgentCore: spliced in afterward by record_terminal.py

        # 9 · the Dashboard
        d.show("dashboard")
        follow(page, nav("/dashboard"), ptr)
        spot(page, ".kpi-row", ptr)
        d.hold("dashboard", 0.3)
        spot(page, "ul.bars >> nth=0", ptr)
        d.hold("dashboard", 0.55)
        spot(page, "ul.bars >> nth=1", ptr)
        d.hold("dashboard", 0.75)
        spot(page, '.kpi:has(.label:text-is("Model tokens"))', ptr, "center")
        d.hold("dashboard", 1.0)
        d.cut()

        # 10 · the receipts, then the end card
        d.show("close")
        follow(page, nav("/policies"), ptr)
        spot(page, 'h2:has-text("Audit log") .pill', ptr, "center")
        d.hold("close", 0.55)
        d.cut()
        SEGMENTS.append({"beat": "close", "source": "endcard", "start": 0.0,
                         "end": round(max(0.5, DUR["close"] - d.elapsed("close")), 3)})

        cap.send_signal(signal.SIGINT)
        cap.wait(timeout=120)
        ctx.close()
    shutil.rmtree(profile, ignore_errors=True)

    offset = find_flash(screen_video) - flash_at
    for s in SEGMENTS:
        if s["source"] == "desktop":
            s["start"], s["end"] = round(s["start"] + offset, 3), round(s["end"] + offset, 3)
    (OUT / "timeline.json").write_text(json.dumps(
        {"desktop": str(screen_video), "phone": str(phone_video), "endcard": str(REPO / "docs" / "thumbnail.png"),
         "exception_url": exception_url, "sync_offset": round(offset, 3), "segments": SEGMENTS},
        indent=2,
    ) + "\n")
    shown = sum(s["end"] - s["start"] for s in SEGMENTS)
    print(f"recorded {len(SEGMENTS)} segments, {shown:.1f} s on screen; capture offset {offset:.3f} s; "
          "var/video/timeline.json written")


if __name__ == "__main__":
    main()
