# Build spec: Dental extrinsic-stain VLM evaluation harness

## What this is

A local web tool for testing and iterating on LLM prompts that judge extrinsic
dental stain on individual tooth crops. This is a **prompt engineering lab**, not
a production clinical tool. The single most important thing it must do well is
let one person change a prompt and immediately see how that change affected the
verdict on every tooth in a batch.

Everything else is in service of that loop.

## Pipeline

```
Upload dental image(s)
      │
      ▼
POST to external tooth-extraction API  ──►  returns tooth crops + metadata
      │
      ▼
For each crop: call an LLM via OpenRouter with the current prompt
      │  (sequential OR parallel, user's choice)
      ▼
Render verdicts in a results grid, aligned with crop thumbnails
```

## Stack

- **Backend:** Python, FastAPI, `httpx` (async), `asyncio`
- **Frontend:** React + Vite + Tailwind
- **Storage:** SQLite via SQLAlchemy — runs, crops, results, prompt versions
- **Images:** stored on local disk under `data/uploads/` and `data/crops/`,
  served by the backend

Single `docker-compose.yml` to bring everything up. Backend and frontend both
hot-reload in dev.

## Hard requirements

### Secrets
The OpenRouter API key lives in `.env`, read server-side only. It must **never**
reach the browser. All OpenRouter calls are proxied through the backend. Same for
the tooth-extraction API credentials.

### Tooth extraction API
Treat this as a pluggable adapter behind an interface, because the endpoint
contract may change:

```python
class ToothExtractor(Protocol):
    async def extract(self, image_path: str) -> list[ToothCrop]: ...

@dataclass
class ToothCrop:
    crop_id: str
    image_path: str          # path to the saved crop file
    bbox: tuple[int,int,int,int]   # in source-image pixel coords
    tooth_number: str | None       # FDI notation if the API returns it
    meta: dict                     # anything else the API sends back
```

Ship one concrete implementation, `HttpToothExtractor`, configured by
`TOOTH_API_URL` and `TOOTH_API_KEY` in `.env`. Also ship a `MockToothExtractor`
that slices an image into a grid, so the UI is fully testable before the real API
is wired up.

### Crop handling
Two details that materially affect results — do not skip these:

1. **Pad every crop.** Default 25% padding on each side, exposed as a UI setting.
   Extrinsic stain is judged against immediately adjacent clean enamel, and
   cervical stain sits at the gingival margin. A tight crop throws that away.
2. **No per-crop color normalization.** Do any white-balance or exposure
   correction once on the source image, never per crop. Independent per-crop
   normalization destroys the color relationships that define a stain.

Preserve full crop resolution on disk. Downscale only when encoding for the LLM,
and make the max edge a UI setting (default 896).

### OpenRouter integration
- Model is user-selectable from a dropdown; fetch the live model list from
  OpenRouter's `/api/v1/models` and cache it. Default to a vision-capable model.
- Send images as base64 data URLs in the standard OpenAI-compatible content-parts
  format.
- Expose `temperature` (default 0) and `max_tokens` in the UI.
- Capture and display from every response: latency in ms, prompt/completion
  tokens, and computed cost.

### Structured output
The prompt must instruct the model to return **only** JSON, and the backend
validates it against a Pydantic schema:

```json
{
  "stain_present": true,
  "confidence": 0.0,
  "stain_type": "chromogenic | tobacco | chlorhexidine | food_beverage | uncertain | none",
  "surface": "cervical | occlusal_pits | interproximal | full_facial | other",
  "severity": "none | mild | moderate | heavy",
  "reasoning": "one or two sentences",
  "differential_considered": ["shadow", "calculus", "restoration_margin", "caries"]
}
```

If parsing fails, strip markdown fences and retry the parse once; if it still
fails, store the raw text and mark the result `PARSE_ERROR`. Never crash a batch
because one response was malformed. Make the schema editable in the UI as a JSON
Schema textarea — the whole point is experimentation, so the output shape must
not be hardcoded.

## Layout

```
┌──────────────────────┬──────────────────────────────────────────┐
│                      │  [Upload]  Model ▾  Concurrency ──●── 8  │
│  PROMPT EDITOR       │  [Run all] [Run selected] [Stop]         │
│                      ├──────────────────────────────────────────┤
│  ┌────────────────┐  │  ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐    │
│  │ system prompt  │  │  │ crop │ │ crop │ │ crop │ │ crop │    │
│  │                │  │  │  ✓   │ │  ✗   │ │  ⟳   │ │  !   │    │
│  │                │  │  │ 0.92 │ │ 0.11 │ │      │ │ err  │    │
│  └────────────────┘  │  └──────┘ └──────┘ └──────┘ └──────┘    │
│  ┌────────────────┐  │  ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐    │
│  │ output schema  │  │  │      │ │      │ │      │ │      │    │
│  └────────────────┘  │  └──────┘ └──────┘ └──────┘ └──────┘    │
│                      │                                          │
│  Version: v7  ▾      │  ── detail panel (on crop click) ──────  │
│  [Save version]      │  full crop · raw JSON · reasoning ·      │
│  [Diff vs v6]        │  latency · tokens · cost · [ground truth]│
└──────────────────────┴──────────────────────────────────────────┘
```

Left panel is resizable and stays fixed while the results grid scrolls.

## Execution control

- **Mode toggle:** sequential or parallel.
- **Concurrency slider:** 1–32, default 8. Enforce with an `asyncio.Semaphore`.
- **Stream results as they land.** Use SSE or a WebSocket so each tile flips from
  spinner to verdict the moment its call returns. Do not wait for the whole batch.
- **Per-crop retry** on failure, and a "retry failed only" button.
- **Stop button** that cancels in-flight tasks cleanly.
- **Rate-limit handling:** exponential backoff with jitter on 429, and surface a
  clear banner rather than silently stalling.

## Prompt versioning — the core feature

Every run is stored against an immutable snapshot of `(prompt_text,
schema, model, temperature, crop_settings)`.

Required:
- **Save version** with an optional note.
- **Version dropdown** to load any past version back into the editor.
- **Diff view** between any two versions, text diff on the prompt.
- **Comparison table**: pick two versions, see per-crop verdicts side by side,
  with changed rows highlighted. This is what tells the user whether a prompt
  edit helped or just moved errors around.

### Caching
Key results on `hash(prompt + schema + model + temperature + crop_file_hash)`.
On re-run, skip anything already cached and show a "cached" badge, with a
"force re-run" override. Without this, iterating on a 200-crop batch gets
expensive fast.

## Ground truth and scoring

Add a ground-truth column the user can set per crop directly in the detail panel
(present / absent / unsure), persisted independently of any run. Once even a
partial ground truth exists, show for each run: accuracy, precision, recall, F1,
and a confusion matrix. Highlight false positives and false negatives in the grid
with distinct colors.

Without this, prompt iteration is vibes. With it, it's measurement.

## Export

- Results to CSV and JSON, including the prompt version used.
- Full run bundle as a zip: crops, results, prompt snapshot, metrics.

## Visual design

Dark neutral UI. Crops must be displayed on a neutral gray background — never
white, never a colored surface — because surrounding color shifts perceived tooth
shade, which is the exact thing being judged. No color-tinted overlays on the
crop image itself; put verdict color on the tile border, outside the image area.

Keep the interface quiet. The images are the content.

## Build order

1. FastAPI skeleton, SQLite models, `.env` config, docker-compose
2. Upload endpoint + `MockToothExtractor` + crop storage with padding
3. OpenRouter proxy with structured-output parsing and error states
4. React shell: prompt editor left, results grid right
5. Sequential run with SSE streaming
6. Parallel run with semaphore, stop, retry
7. Prompt versioning, diff, comparison table
8. Caching layer
9. Ground truth + metrics
10. Export
11. Swap in `HttpToothExtractor` against the real API

Get 1–6 working end to end before starting 7.

## Non-goals

Not a clinical tool. No patient identifiers stored. No auth or multi-user
support — this runs locally for one person. No model fine-tuning.