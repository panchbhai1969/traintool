import base64
import json

import httpx
import pytest

from backend.tooth_extractor import ToothExtractionError, extract_teeth, parse_detections


def response_body():
    return {
        "status": "COMPLETED",
        "output": {
            "status": 0,
            "predictions": [
                {
                    "image": "image0",
                    "prediction": {
                        "detection_boxes": [[0.1, 0.2, 0.5, 0.6], [0.2, 0.3, 0.4, 0.5]],
                        "detection_scores": [0.91, 0.72],
                        "detection_classes": ["tooth", "caries"],
                    },
                }
            ],
        },
    }


def test_parse_detections_uses_detection_keys_and_filters_non_teeth() -> None:
    detections = parse_detections(response_body())
    assert len(detections) == 1
    assert detections[0].percentage_box() == {"x": 20.0, "y": 10.0, "width": 40.0, "height": 40.0}
    assert detections[0].confidence == 0.91


def test_parse_detections_rejects_old_or_missing_keys() -> None:
    body = response_body()
    body["output"]["predictions"][0]["prediction"] = {"boxes": []}
    with pytest.raises(ToothExtractionError, match="missing detection arrays"):
        parse_detections(body)


@pytest.mark.asyncio
async def test_extract_teeth_sends_exact_bytes_as_base64(monkeypatch) -> None:
    original = b"exact original image bytes"

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["input"]["mode"] == "tooth"
        assert base64.b64decode(payload["input"]["image0_base64"]) == original
        return httpx.Response(200, json=response_body())

    monkeypatch.setattr("backend.tooth_extractor.TOOTH_API_URL", "https://detector.test/runsync")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        detections = await extract_teeth(original, client=client)
    assert len(detections) == 1
