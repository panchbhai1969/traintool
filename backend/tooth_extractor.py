from __future__ import annotations

import base64
import math
from dataclasses import dataclass
from typing import Any

import httpx

from .settings import TOOTH_API_KEY, TOOTH_API_URL


class ToothExtractionError(RuntimeError):
    pass


@dataclass(frozen=True)
class ToothDetection:
    ymin: float
    xmin: float
    ymax: float
    xmax: float
    confidence: float

    def percentage_box(self) -> dict[str, float]:
        return {
            "x": self.xmin * 100,
            "y": self.ymin * 100,
            "width": (self.xmax - self.xmin) * 100,
            "height": (self.ymax - self.ymin) * 100,
        }


def _prediction_payload(body: dict[str, Any]) -> dict[str, Any]:
    if body.get("status") != "COMPLETED":
        raise ToothExtractionError(f"Tooth detector job did not complete: {body.get('status') or 'unknown status'}")
    output = body.get("output")
    if not isinstance(output, dict) or output.get("status") != 0:
        detail = output.get("error") if isinstance(output, dict) else None
        raise ToothExtractionError(f"Tooth detector failed{f': {detail}' if detail else ''}")
    groups = output.get("predictions")
    if not isinstance(groups, list) or not groups:
        raise ToothExtractionError("Tooth detector returned no prediction payload")
    group = next((item for item in groups if isinstance(item, dict) and item.get("image") == "image0"), groups[0])
    if not isinstance(group, dict):
        raise ToothExtractionError("Tooth detector returned an invalid prediction group")
    if group.get("error"):
        raise ToothExtractionError(str(group["error"]))
    prediction = group.get("prediction")
    if not isinstance(prediction, dict):
        raise ToothExtractionError("Tooth detector returned an invalid prediction object")
    return prediction


def parse_detections(body: dict[str, Any]) -> list[ToothDetection]:
    prediction = _prediction_payload(body)
    boxes = prediction.get("detection_boxes")
    scores = prediction.get("detection_scores")
    classes = prediction.get("detection_classes")
    if not all(isinstance(value, list) for value in (boxes, scores, classes)):
        raise ToothExtractionError("Tooth detector response is missing detection arrays")
    if len(boxes) != len(scores) or len(boxes) != len(classes):
        raise ToothExtractionError("Tooth detector returned mismatched detection arrays")

    detections: list[ToothDetection] = []
    for box, score, class_name in zip(boxes, scores, classes, strict=True):
        if str(class_name).lower() != "tooth":
            continue
        if not isinstance(box, list) or len(box) != 4:
            continue
        try:
            ymin, xmin, ymax, xmax = (float(value) for value in box)
            confidence = float(score)
        except (TypeError, ValueError):
            continue
        if not all(math.isfinite(value) for value in (ymin, xmin, ymax, xmax, confidence)):
            continue
        ymin, xmin, ymax, xmax = (min(1.0, max(0.0, value)) for value in (ymin, xmin, ymax, xmax))
        if ymax <= ymin or xmax <= xmin:
            continue
        detections.append(ToothDetection(ymin, xmin, ymax, xmax, confidence))
    return detections


async def extract_teeth(image_bytes: bytes, *, client: httpx.AsyncClient | None = None) -> list[ToothDetection]:
    headers = {"Content-Type": "application/json"}
    if TOOTH_API_KEY:
        headers["Authorization"] = f"Bearer {TOOTH_API_KEY}"
    payload = {
        "input": {
            "mode": "tooth",
            "image0_base64": base64.b64encode(image_bytes).decode("ascii"),
        }
    }

    owns_client = client is None
    active_client = client or httpx.AsyncClient(timeout=httpx.Timeout(120, connect=15))
    try:
        response = await active_client.post(TOOTH_API_URL, headers=headers, json=payload)
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict):
            raise ToothExtractionError("Tooth detector returned a non-object response")
        return parse_detections(body)
    except ToothExtractionError:
        raise
    except httpx.TimeoutException as error:
        raise ToothExtractionError("Tooth detector timed out") from error
    except httpx.HTTPStatusError as error:
        raise ToothExtractionError(f"Tooth detector returned HTTP {error.response.status_code}") from error
    except (httpx.HTTPError, ValueError) as error:
        raise ToothExtractionError(f"Could not call tooth detector: {error}") from error
    finally:
        if owns_client:
            await active_client.aclose()
