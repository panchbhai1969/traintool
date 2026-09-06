# Dental Finding Prompt Lab

A local prompt-engineering interface for comparing OpenRouter vision-model verdicts for stain, calculus, and caries across individual-tooth boxes.

## Setup

The backend must use the existing Python environment requested for this project:

```bash
../py3srv/bin/python -m pip install -r requirements.txt
```

The backend reads configuration from `../.env` first and an optional local `.env` second. Required key: `OPENROUTER_API_KEY`. The tooth detector defaults to `https://internal9.logy.ai/runsync`; override it with `TOOTH_API_URL` and optionally set `TOOTH_API_KEY` when the endpoint requires authentication.

## Development

```bash
../py3srv/bin/python -m uvicorn backend.app:app --reload
```

Open <http://localhost:8000>. Use **Upload image** to send one JPEG, PNG, or WebP image to the tooth detector. Detected tooth crops appear without being selected or evaluated automatically. Uploads are temporary browser-session additions and are not restored after a refresh.

Select **Stain**, **Calculus**, or **Caries** before running an evaluation. Their prompts are loaded from `stain.md`, `calculus.md`, and `caries.md`. Prompt edits are persisted to the selected file only when **Save prompt** is clicked.

The application APIs are `POST /api/images/upload` for raw image bytes, `POST /api/evaluate` for LLM evaluation, and `PUT /api/prompts/{finding}` for prompt updates. The URL-encoded upload filename is passed in the `X-Filename` header. Dataset content and prompt defaults are served at `/dataset.json`.

The **History** button shows session-only run summaries grouped by source image. Parallel crop costs are summed into one entry with the image ID and number of calls. History is intentionally cleared when the page is refreshed.

## Tests

```bash
../py3srv/bin/python -m pytest
```
