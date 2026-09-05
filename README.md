# Dental Stain Prompt Lab

A local prompt-engineering interface for comparing OpenRouter vision-model verdicts across precomputed individual-tooth boxes.

## Setup

The backend must use the existing Python environment requested for this project:

```bash
../py3srv/bin/python -m pip install -r requirements.txt
```

The backend reads OpenRouter configuration from `../.env` first and an optional local `.env` second. Required key: `OPENROUTER_API_KEY`.

## Development

```bash
../py3srv/bin/python -m uvicorn backend.app:app --reload
```

Open <http://localhost:8000>. There is one application API, `POST /api/evaluate`; dataset content is served as a static page resource at `/dataset.json`.

## Tests

```bash
../py3srv/bin/python -m pytest
```
