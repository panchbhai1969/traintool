# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A local, single-user prompt-engineering lab for comparing OpenRouter vision-model
verdicts (`present` / `absent`) for **stain**, **calculus**, and **caries** on
individual tooth crops. You edit a prompt, run it against a batch of tooth boxes,
and watch verdicts stream back tile-by-tile.

`plan.md` is the original aspirational spec and describes far more than what
exists (SQLite, React/Vite/Tailwind, prompt versioning, caching, ground-truth
scoring, CSV/zip export, model dropdown from OpenRouter's `/models`). **None of
that is built.** Treat the code, `README.md`, and this file as ground truth, not
`plan.md`.

## Environment and commands

The project uses a shared external interpreter, not an in-repo venv. All commands
run through `../py3srv/bin/python`:

```bash
# install deps
../py3srv/bin/python -m pip install -r requirements.txt

# run the dev server (serves API + frontend at http://localhost:8000)
../py3srv/bin/python -m uvicorn backend.app:app --reload

# full test suite
../py3srv/bin/python -m pytest

# single test file / test
../py3srv/bin/python -m pytest tests/test_app.py
../py3srv/bin/python -m pytest tests/test_app.py::test_evaluate_streams_crop_events_without_extra_api_calls
```

There is no linter or formatter configured, and no pytest config file —
async tests carry explicit `@pytest.mark.asyncio` marks.

## Configuration

`backend/settings.py` runs a minimal dotenv loader at import time. It reads
`../.env` (the workspace-wide file, expected to exist) then `./.env`, using
`os.environ.setdefault` — **real environment variables always win**, and the
first file to define a key wins over the second.

- `OPENROUTER_API_KEY` — required for `/api/evaluate`; server-side only, never sent to the browser.
- `OPENROUTER_MODEL` (default `qwen/qwen3-vl-235b-a22b-instruct`), `OPENROUTER_BASE_URL`.
- `ENHANCE_MODEL` (default `openai/gpt-image-2`), `ENHANCE_PROMPT` (default `enhance the image`) — used by the per-crop Enhance button.
- `TOOTH_API_URL` (default `https://internal9.logy.ai/runsync`), `TOOTH_API_KEY` (optional).
- `TRAINTOOL` (optional) — when set, every request is gated behind HTTP Basic auth
  (any username, this value as the password), enforced by a middleware in `backend/app.py`.

## Architecture

Backend is FastAPI + `httpx`/`asyncio`. Frontend is a single hand-written
vanilla-JS module (`frontend/src/app.js`, ~500 lines, full re-render on every
`render()`), served by the catch-all route in `backend/app.py`. No build step, no
framework. The CORS allowance for `localhost:5173` is a leftover from the
abandoned Vite plan.

**No database. No persistence beyond prompt files and cached image bytes.**
All run state lives in module globals (`catalog`, `uploaded_sources` in
`backend/app.py`) and is lost on restart. Run history is browser-session-only and
cleared on refresh.

### Request flow

1. **Dataset load** — `GET /dataset.json` returns the crop catalog plus
   `defaults` (model, schema, finding, current prompt texts). The frontend fetches
   this once on load.
2. **Upload** — `POST /api/images/upload` takes raw image bytes (not multipart;
   filename comes URL-encoded in the `X-Filename` header). It validates the image
   with Pillow, calls the tooth detector, saves the source under `data/uploads/`,
   and registers one `CropRecord` per detected tooth. `GET /api/uploads/{id}`
   serves it back.
3. **Evaluate** — `POST /api/evaluate` validates crop IDs and the (editable) JSON
   Schema, then returns an **SSE stream** (`text/event-stream`). One `asyncio`
   task per crop, gated by an `asyncio.Semaphore` (`concurrency`, or 1 in
   `sequential` mode). Events: `queued` → `running` → `completed` / `parse_error`
   / `failed` / `rate_limited` / `cancelled`, ending with `batch_completed`. The
   handler polls `request.is_disconnected()` and cancels in-flight tasks when the
   client aborts.
4. **Prompt save** — `PUT /api/prompts/{finding}` writes the prompt back to
   `<finding>.md` at the repo root (atomic tmp-file replace). Only happens on an
   explicit "Save prompt" click.

### Key modules (`backend/`)

- **`dataset.py`** — `DatasetCatalog` loads `../label_studio_best_pt_conf_0.25/tasks_with_predictions.json`
  at construction (1090 images), turning Label Studio `rectanglelabels` results
  into `CropRecord`s. Boxes are stored as **percentages** of the source image.
  `register_upload` adds crops for uploaded images with a real `source_path`.
- **`tooth_extractor.py`** — adapter for the RunPod-style `/runsync` detector.
  Sends `{input: {mode: "tooth", image0_base64: ...}}`, expects
  `status == "COMPLETED"` with nested `output.predictions[].prediction.detection_*`
  arrays; keeps only `detection_classes == "tooth"`, clamps coords to `[0,1]`.
  All failures become `ToothExtractionError` (surfaced as HTTP 502).
- **`evaluator.py`** — the per-crop pipeline. `_source_image` resolves/downloads
  and caches the source (dataset crops fetch `image_url`; uploads use the local
  file). `_prepare_crop` applies **fractional padding** on each side, saves the
  full-res crop to `data/crops/`, then downscales a copy to `max_edge` and
  base64-encodes it as a `data:` URL. `build_system_prompt` appends fixed
  reasoning-then-verdict instructions and the schema. Calls OpenRouter
  `chat/completions` with up to 5 retries on HTTP 429 (exponential backoff +
  jitter). `parse_and_validate` strips markdown fences on a retry and validates
  against the schema with `jsonschema` Draft 2020-12.
  Note: `build_openrouter_payload` currently sends only `model` + `messages` —
  `temperature`, `seed`, and `max_tokens` are commented out.
- **`prompts.py`** — `FINDINGS = ("stain", "calculus", "caries")`; maps each to
  `<finding>.md` at repo root. `load_prompts` / `save_prompt` read/write those files.
- **`enhancer.py`** — `enhance_crop_image` cuts the full-resolution crop (via
  `_prepare_crop`) and POSTs it to OpenRouter's **`/images`** endpoint (not
  `/chat/completions` — `ENHANCE_MODEL` defaults to `openai/gpt-image-2`, an
  image-gen model) as `{model, prompt, input_references: [{type:"image_url",
  image_url:{url: dataURL}}]}` (the `input_references` field is required — an
  `image` field is silently ignored), and reads `data[0].b64_json` back. Returns
  `(image_data_url, usage)`. Backs `POST /api/crops/{crop_id}/enhance`, which also
  returns `model` + `latency_ms` + `usage` (cost/tokens) so the frontend can log
  each enhance call to the History panel. The enhanced image is returned inline
  (no disk storage); the frontend echoes it back in the `/api/evaluate` `enhanced`
  map, and `evaluate_one(..., enhanced_data_url=...)` sends it to the vision model
  in place of a freshly-cut crop.

### Prompt files

`stain.md`, `calculus.md`, `caries.md` at the repo root are **live application
data**, not documentation — they are the system prompts and are rewritten by
`PUT /api/prompts/{finding}`.

### Data directories (gitignored)

`data/uploads/` (source images + downloaded dataset images) and `data/crops/`
(full-resolution padded crops). Files are content/parameter-keyed by SHA-256 and
reused across runs.

## Domain constraints (from `plan.md`, still enforced in code)

- **Pad every crop** (default 25%) — stain is judged against adjacent clean
  enamel, so a tight crop loses the signal.
- **No per-crop color normalization** — it would destroy the color relationships
  that define a stain. Downscale only when encoding for the LLM; keep full-res on disk.
- Crops render on a **neutral gray** background in the UI; verdict color goes on
  the tile border, never as an overlay on the image.
