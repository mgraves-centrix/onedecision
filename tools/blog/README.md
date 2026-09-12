# Blog covers

One 1200x630 cover per Builder post, plus a series cover, rendered by
`build_covers.py` from the spec in `covers.json`.

```bash
.venv/bin/python tools/blog/build_covers.py     # writes docs/blog/cover*.png
```

The evidence on each cover is the product's own. `replay.png` and `refusal.png`
are screenshots of the running app, and the terminal blocks are real captured CLI
and runtime output. No figure on a cover was typed to look good, which is the
point: a cover that claims zero wrong actions should be showing the screen that
says so.

To re-shoot the screenshots after a new take, serve that take's database:

```bash
ONEDECISION_MODEL_PROVIDER=scripted ONEDECISION_DB_PATH=../onedecision-video/take.db \
  .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8099
```

Then screenshot `.replay-grid` on a decision page and `section.card.danger` on the
escalated case, both at `device_scale_factor=2`, into `replay.png` and
`refusal.png`.
