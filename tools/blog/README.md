# Blog cover

`cover.html` renders the cover image for the Builder.aws posts at 1200x630. The
numbers in it are not typed: `replay.png` is a screenshot of the real replay grid,
taken from the app running against a finished take's database, so the cover shows
the same evidence a reader would see in the product.

To rebuild after a take, serve that take's database and re-shoot the element:

```bash
ONEDECISION_MODEL_PROVIDER=scripted ONEDECISION_DB_PATH=../onedecision-video/take.db \
  .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8099
```

Screenshot `.replay-grid` on the decision page at `device_scale_factor=2` into
`replay.png`, then render `cover.html` in a 1200x630 viewport, also at 2x. The
output is `docs/blog/cover.png`.
