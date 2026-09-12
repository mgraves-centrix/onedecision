# Draft demo video

These tools turn [docs/demo-script.md](../../docs/demo-script.md) into a draft video. The draft
shows the live app on Amazon Bedrock in a real Google Chrome window, captured from the screen,
voiced with Amazon Polly. Waits for model calls are cut, so the video shows each click and its
result. Before anything is assembled, every fact the narration states is checked against the
take's own database.

Everything generated goes to `../onedecision-video/`, beside the repository rather than
inside it, because the AgentCore packager ships every file in the tree, gitignored or not,
and a few takes are hundreds of megabytes. Override the location with
`ONEDECISION_VIDEO_OUT`. Run every command from the repository root.

## What you need

- macOS with Google Chrome installed.
- A display at 1x scaling with room for a 1920x1080 window, such as an external 1440p monitor.
  The window is captured one screen pixel per video pixel, so a Retina display doesn't work.
- Screen Recording permission for the terminal app you run these from, under System Settings >
  Privacy & Security > Screen Recording.
- `ffmpeg` (`brew install ffmpeg`).
- The AWS CLI signed in to a profile with Bedrock and Polly access:
  `aws sso login --profile onedecision`.
- The Python extra and Playwright's Chromium, which records the phone stand-in:

  ```bash
  .venv/bin/pip install -e ".[video]"
  .venv/bin/playwright install chromium
  ```

## Making a draft

1. **Voiceover.** Edit `narration.json` if the script changed, then run the command below. It
   writes one clip per beat plus `durations.json`, and the recording is paced to those
   durations.

   ```bash
   .venv/bin/python tools/video/synth.py            # voice Ruth, generative engine
   ```

2. **Take server.** Start a Bedrock-backed app with its own database, so a take never touches
   your local demo data. Keep it running in another terminal.

   It uses port 8000, the same as `make run`, so stop that first. The recorder opens the app
   as `onedecision.localhost:8000`. Chrome sends any `*.localhost` name to this machine, so no
   hosts-file change is needed, and the address bar shows a name instead of an IP address. To
   use another address, pass it to `record_live.py` as its first argument.

   ```bash
   AWS_PROFILE=onedecision ONEDECISION_MODEL_PROVIDER=bedrock ONEDECISION_DB_PATH=../onedecision-video/take.db \
     .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
   ```

3. **Preview.** This opens the Chrome window for a few seconds, checks its position, the 125%
   page zoom, and where the pointer lands, and saves one captured frame. Look at the frame.

   ```bash
   .venv/bin/python tools/video/record_live.py --preview   # writes ../onedecision-video/preview.png
   ```

4. **Take.** A take lasts about eight minutes on Bedrock. Chrome takes keyboard focus, so don't
   type and don't use that display until it finishes.

   ```bash
   .venv/bin/python tools/video/record_live.py
   ```

5. **AgentCore beat.** This replays captured `agentcore invoke` output in a terminal-style
   window. It makes no server calls, so redoing it never needs a new take.

   ```bash
   .venv/bin/python tools/video/render_terminal.py
   .venv/bin/python tools/video/record_terminal.py
   ```

6. **Check the take.** Every line must say PASS. The voiceover states these facts out loud,
   including that approving a decision activates nothing. If any line fails, re-record the take
   rather than assembling it.

   ```bash
   .venv/bin/python tools/video/check_take.py ../onedecision-video/take.db
   ```

7. **Assemble and look.** The contact sheet shows the start, middle, and end of every beat.
   Check it before sharing the draft.

   ```bash
   .venv/bin/python tools/video/assemble.py        # ../onedecision-video/onedecision-demo-draft.mp4
   .venv/bin/python tools/video/contact_sheet.py   # ../onedecision-video/contact-sheet.png
   ```

## What is real and what stands in

- **Desktop beats:** every desktop beat is the live app on Bedrock in Chrome. The pointer is
  drawn in the page, because automated input doesn't move the macOS cursor. The teal outline
  marks what the narration is talking about. A slow click keeps the camera on the waiting
  panel for `WATCH[beat]` seconds so the run is seen reporting its own steps; the rest of the
  wait, tens of seconds, still happens off camera.
- **Phone beat:** real footage. There is one phone and it is the thing running the app, so
  nothing can film it being held; it records its own screen instead, reaching the app over the
  LAN. `frame_phone.py` wraps that recording in a drawn device body and cuts it to the beat:

  ```bash
  .venv/bin/python tools/video/frame_phone.py <recording.mp4> --start 51.9 --hold 52.9 53.95
  ```

  `--hold` slows one span, for the case this beat always has: a person scrolls to a button and
  taps it in one motion, leaving the button on screen too briefly to read. It is real footage
  played slower, never a still or a duplicated frame. Then point `"phone"` in
  `../onedecision-video/timeline.json` at `phone-beat.mp4` with one segment covering the beat,
  and re-run `assemble.py`.
- **AgentCore beat:** it replays `agentcore-result.json`, the handler's result from a real
  `agentcore invoke "Investigate CASE-2001" --json`, without the CLI's session ID or local log
  path. To use a fresh capture, pass the new CLI output to `render_terminal.py`.
