from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app import app, catalog


client = TestClient(app)


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
