import io
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image

from backend.app import DEFAULT_SCHEMA, app, catalog, uploaded_sources
from backend.tooth_extractor import ToothDetection


client = TestClient(app)


def test_default_schema_puts_reasoning_first() -> None:
    assert DEFAULT_SCHEMA["required"][0] == "reasoning"
    assert next(iter(DEFAULT_SCHEMA["properties"])) == "reasoning"
    assert set(DEFAULT_SCHEMA["properties"]) == {"reasoning", "stain_present"}


def test_page_and_static_catalog_are_served() -> None:
    assert client.get("/").status_code == 200
    response = client.get("/dataset.json")
    assert response.status_code == 200
    assert response.json()["image_count"] == 1090


def test_evaluate_rejects_unknown_server_side_crop() -> None:
    response = client.post(
        "/api/evaluate",
        json={
            "crop_ids": ["not-a-real-crop"],
            "prompt": "Evaluate",
            "schema": {"type": "object"},
            "model": "test/model",
        },
    )
    assert response.status_code == 400


def test_evaluate_streams_crop_events_without_extra_api_calls(monkeypatch) -> None:
    crop_id = next(iter(catalog.crops))

    async def fake_evaluate(_client, crop, **kwargs):
        await kwargs["emit"]({"type": "running", "crop_id": crop.crop_id})
        await kwargs["emit"](
            {
                "type": "completed",
                "crop_id": crop.crop_id,
                "result": {"stain_present": False},
            }
        )

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    with patch("backend.app.evaluate_one", fake_evaluate):
        response = client.post(
            "/api/evaluate",
            json={
                "crop_ids": [crop_id],
                "prompt": "Evaluate",
                "schema": {"type": "object"},
                "model": "test/model",
            },
        )
    assert response.status_code == 200
    assert '"type":"running"' in response.text
    assert '"type":"completed"' in response.text
    assert '"type":"batch_completed"' in response.text


def test_evaluate_rejects_invalid_json_schema() -> None:
    crop_id = next(iter(catalog.crops))
    response = client.post(
        "/api/evaluate",
        json={
            "crop_ids": [crop_id],
            "prompt": "Evaluate",
            "schema": {"type": "definitely-not-a-json-schema-type"},
            "model": "test/model",
        },
    )
    assert response.status_code == 422


def test_upload_registers_detected_teeth_from_raw_image(tmp_path, monkeypatch) -> None:
    buffer = io.BytesIO()
    Image.new("RGB", (120, 80), "white").save(buffer, format="JPEG")
    original = buffer.getvalue()
    received: list[bytes] = []

    async def fake_extract(contents: bytes):
        received.append(contents)
        return [ToothDetection(0.1, 0.2, 0.5, 0.6, 0.9)]

    monkeypatch.setattr("backend.app.extract_teeth", fake_extract)
    monkeypatch.setattr("backend.app.UPLOAD_DIR", tmp_path)
    response = client.post(
        "/api/images/upload",
        content=original,
        headers={"Content-Type": "image/jpeg", "X-Filename": "My Photo.jpg"},
    )
    assert response.status_code == 200
    image = response.json()["image"]
    assert received == [original]
    assert image["image_id"].startswith("upload-my-photo-")
    assert image["crop_count"] == 1
    assert image["crops"][0]["box"] == {"x": 20.0, "y": 10.0, "width": 40.0, "height": 40.0}
    assert client.get(image["image_url"]).content == original

    for crop in image["crops"]:
        catalog.crops.pop(crop["crop_id"], None)
    uploaded_sources.pop(image["image_id"], None)


def test_upload_rejects_non_image() -> None:
    response = client.post(
        "/api/images/upload",
        content=b"not an image",
        headers={"X-Filename": "bad.jpg"},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Upload is not a valid image"
