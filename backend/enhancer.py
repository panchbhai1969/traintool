from __future__ import annotations

import asyncio
import base64
import random
from pathlib import Path
from typing import Any

import httpx

from .dataset import CropRecord
from .evaluator import _prepare_crop, _source_image
from .settings import ENHANCE_MODEL, ENHANCE_PROMPT, OPENROUTER_BASE_URL


class EnhancementError(RuntimeError):
    pass


def _error_detail(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text[:400] or "(empty body)"
    if isinstance(body, dict) and body.get("error"):
        error = body["error"]
        return str(error.get("message") or error) if isinstance(error, dict) else str(error)
    return str(body)[:400]


def _result_data_url(body: dict[str, Any]) -> str | None:
    """Read the generated image from an OpenRouter /images response."""
    data = body.get("data")
    if not isinstance(data, list) or not data:
        return None
    item = data[0]
    if not isinstance(item, dict):
        return None
    b64 = item.get("b64_json")
    if isinstance(b64, str) and b64:
        media_type = item.get("media_type") or "image/png"
        return f"data:{media_type};base64,{b64}"
    url = item.get("url")
    if isinstance(url, str) and url.startswith("data:image/"):
        return url
    return None


async def enhance_crop_image(
    client: httpx.AsyncClient,
    crop: CropRecord,
    *,
    api_key: str,
    padding: float,
    max_edge: int,
) -> tuple[str, dict[str, Any]]:
    """Send the crop's existing pixels to the image model.

    Returns (image data URL, usage dict) where usage is OpenRouter's per-call
    ``usage`` block (cost, tokens) or ``{}`` if absent.
    """
    source_path = await _source_image(client, crop)
    # _prepare_crop writes the full-resolution crop to disk and returns a downscaled
    # data URL; the enhance model gets the full-resolution crop.
    crop_path, _downscaled = await asyncio.to_thread(_prepare_crop, source_path, crop, padding, max_edge)
    crop_bytes = await asyncio.to_thread(Path(crop_path).read_bytes)
    crop_data_url = "data:image/jpeg;base64," + base64.b64encode(crop_bytes).decode("ascii")

    payload = {
        "model": ENHANCE_MODEL,
        "prompt": ENHANCE_PROMPT,
        "input_references": [{"type": "image_url", "image_url": {"url": crop_data_url}}],
    }

    response: httpx.Response | None = None
    for attempt in range(5):
        response = await client.post(
            f"{OPENROUTER_BASE_URL}/images",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
        )
        if response.status_code != 429:
            break
        await asyncio.sleep(min(16.0, (2**attempt) + random.random()))
    assert response is not None

    if response.status_code >= 400:
        raise EnhancementError(
            f"Enhance model returned HTTP {response.status_code}: {_error_detail(response)}"
        )

    body = response.json()
    if isinstance(body, dict) and body.get("error"):
        error = body["error"]
        raise EnhancementError(f"Enhance model error: {error.get('message') if isinstance(error, dict) else error}")

    image = _result_data_url(body if isinstance(body, dict) else {})
    if image is None:
        raise EnhancementError(f"Enhance model returned no image: {str(body)[:300]}")
    usage = body.get("usage") if isinstance(body, dict) else None
    return image, usage if isinstance(usage, dict) else {}
