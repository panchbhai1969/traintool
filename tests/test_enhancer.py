import base64
import io
import json
from pathlib import Path

import httpx
import pytest
from PIL import Image

from backend.dataset import CropRecord
from backend.enhancer import EnhancementError, _result_data_url, enhance_crop_image


def _png_b64() -> str:
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), "white").save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def test_result_data_url_from_b64_json() -> None:
    b64 = _png_b64()
    assert _result_data_url({"data": [{"b64_json": b64, "media_type": "image/png"}]}) == f"data:image/png;base64,{b64}"


def test_result_data_url_defaults_media_type() -> None:
    b64 = _png_b64()
    assert _result_data_url({"data": [{"b64_json": b64}]}) == f"data:image/png;base64,{b64}"


def test_result_data_url_absent() -> None:
    assert _result_data_url({"data": []}) is None
    assert _result_data_url({}) is None


@pytest.mark.asyncio
async def test_enhance_crop_image_returns_model_image(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "source.png"
    Image.new("RGB", (100, 80), "white").save(source)
    monkeypatch.setattr("backend.evaluator.CROP_DIR", tmp_path / "crops")
    crop = CropRecord("image:crop", "image", "/api/uploads/image", 100, 80, 0, 0, 20, 25, source)
    b64 = _png_b64()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/images")
        assert request.headers["Authorization"] == "Bearer key"
        body = json.loads(request.content)
        assert "image" not in body
        url = body["input_references"][0]["image_url"]["url"]
        assert url.startswith("data:image/jpeg;base64,")
        return httpx.Response(
            200,
            json={"data": [{"b64_json": b64, "media_type": "image/png"}], "usage": {"cost": 0.0123, "total_tokens": 200}},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result, usage = await enhance_crop_image(client, crop, api_key="key", padding=0.25, max_edge=512)
    assert result == f"data:image/png;base64,{b64}"
    assert usage == {"cost": 0.0123, "total_tokens": 200}


@pytest.mark.asyncio
async def test_enhance_crop_image_raises_without_image(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "source.png"
    Image.new("RGB", (100, 80), "white").save(source)
    monkeypatch.setattr("backend.evaluator.CROP_DIR", tmp_path / "crops")
    crop = CropRecord("image:crop", "image", "/api/uploads/image", 100, 80, 0, 0, 20, 25, source)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(EnhancementError, match="no image"):
            await enhance_crop_image(client, crop, api_key="key", padding=0.25, max_edge=512)
