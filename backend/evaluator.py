from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import json
import random
import re
import time
from pathlib import Path
from typing import Any, Awaitable, Callable

import httpx
from jsonschema import Draft202012Validator
from PIL import Image

from .dataset import CropRecord
from .settings import CROP_DIR, OPENROUTER_BASE_URL, UPLOAD_DIR


Emit = Callable[[dict[str, Any]], Awaitable[None]]
_download_locks: dict[str, asyncio.Lock] = {}


def _file_key(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


async def _source_image(client: httpx.AsyncClient, crop: CropRecord) -> Path:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    path = UPLOAD_DIR / f"{_file_key(crop.image_url)}.image"
    lock = _download_locks.setdefault(crop.image_url, asyncio.Lock())
    async with lock:
        if path.exists():
            return path
        response = await client.get(crop.image_url, follow_redirects=True)
        response.raise_for_status()
        if len(response.content) > 30 * 1024 * 1024:
            raise ValueError("Source image exceeds the 30 MB limit")
        Image.open(io.BytesIO(response.content)).verify()
        temporary = path.with_suffix(".tmp")
        temporary.write_bytes(response.content)
        temporary.replace(path)
    return path


def _prepare_crop(source_path: Path, crop: CropRecord, padding: float, max_edge: int) -> tuple[Path, str]:
    CROP_DIR.mkdir(parents=True, exist_ok=True)
    with Image.open(source_path) as source:
        source.load()
        width, height = source.size
        x1 = crop.x * width / 100
        y1 = crop.y * height / 100
        box_width = crop.width * width / 100
        box_height = crop.height * height / 100
        left = max(0, round(x1 - box_width * padding))
        top = max(0, round(y1 - box_height * padding))
        right = min(width, round(x1 + box_width * (1 + padding)))
        bottom = min(height, round(y1 + box_height * (1 + padding)))
        if right <= left or bottom <= top:
            raise ValueError("Crop box has no area")
        full = source.crop((left, top, right, bottom)).convert("RGB")
        crop_path = CROP_DIR / f"{_file_key(f'{crop.crop_id}:{padding:.4f}')}.jpg"
        if not crop_path.exists():
            full.save(crop_path, format="JPEG", quality=96, subsampling=0)
        llm_image = full.copy()
        llm_image.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
        buffer = io.BytesIO()
        llm_image.save(buffer, format="JPEG", quality=92)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return crop_path, f"data:image/jpeg;base64,{encoded}"


def _extract_text(response: dict[str, Any]) -> str:
    content = response["choices"][0]["message"]["content"]
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(str(part.get("text", "")) for part in content if isinstance(part, dict))
    return str(content)


def parse_and_validate(raw: str, schema: dict[str, Any]) -> dict[str, Any]:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        cleaned = re.sub(r"^\s*```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```\s*$", "", cleaned)
        parsed = json.loads(cleaned)
    Draft202012Validator(schema).validate(parsed)
    return parsed


async def evaluate_one(
    client: httpx.AsyncClient,
    crop: CropRecord,
    *,
    api_key: str,
    model: str,
    prompt: str,
    schema: dict[str, Any],
    temperature: float,
    max_tokens: int,
    max_edge: int,
    padding: float,
    emit: Emit,
) -> None:
    await emit({"type": "running", "crop_id": crop.crop_id})
    started = time.perf_counter()
    try:
        source_path = await _source_image(client, crop)
        crop_path, data_url = await asyncio.to_thread(_prepare_crop, source_path, crop, padding, max_edge)
        schema_text = json.dumps(schema, separators=(",", ":"))
        messages = [
            {
                "role": "system",
                "content": f"{prompt}\n\nReturn only JSON matching this JSON Schema:\n{schema_text}",
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Evaluate this individual tooth crop."},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            },
        ]
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        response: httpx.Response | None = None
        for attempt in range(5):
            response = await client.post(
                f"{OPENROUTER_BASE_URL}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=payload,
            )
            if response.status_code != 429:
                break
            delay = min(16.0, (2**attempt) + random.random())
            await emit({"type": "rate_limited", "crop_id": crop.crop_id, "retry_in": round(delay, 2)})
            await asyncio.sleep(delay)
        assert response is not None
        response.raise_for_status()
        body = response.json()
        raw = _extract_text(body)
        usage = body.get("usage") or {}
        common = {
            "crop_id": crop.crop_id,
            "raw": raw,
            "latency_ms": round((time.perf_counter() - started) * 1000),
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
            "cost": usage.get("cost"),
            "crop_path": str(crop_path.relative_to(CROP_DIR.parent)),
        }
        try:
            parsed = parse_and_validate(raw, schema)
            await emit({"type": "completed", **common, "result": parsed})
        except Exception as error:
            await emit({"type": "parse_error", **common, "error": str(error)})
    except asyncio.CancelledError:
        await emit({"type": "cancelled", "crop_id": crop.crop_id})
        raise
    except Exception as error:
        await emit(
            {
                "type": "failed",
                "crop_id": crop.crop_id,
                "latency_ms": round((time.perf_counter() - started) * 1000),
                "error": str(error),
            }
        )
