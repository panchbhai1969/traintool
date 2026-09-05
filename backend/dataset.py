from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = ROOT.parent / "label_studio_best_pt_conf_0.25" / "tasks_with_predictions.json"


@dataclass(frozen=True)
class CropRecord:
    crop_id: str
    image_id: str
    image_url: str
    original_width: int
    original_height: int
    x: float
    y: float
    width: float
    height: float


class DatasetCatalog:
    def __init__(self, path: Path = DEFAULT_DATASET) -> None:
        self.path = path
        self.images: list[dict[str, Any]] = []
        self.crops: dict[str, CropRecord] = {}
        self._load()

    def _load(self) -> None:
        tasks = json.loads(self.path.read_text(encoding="utf-8"))
        for index, task in enumerate(tasks):
            image_id = str(task.get("meta", {}).get("source_image_id") or index)
            image_url = str(task["data"]["image"])
            crop_summaries: list[dict[str, Any]] = []
            results = [
                result
                for annotation in task.get("annotations", [])
                for result in annotation.get("result", [])
                if result.get("type") == "rectanglelabels"
            ]
            for box_index, result in enumerate(results):
                value = result["value"]
                crop_id = f"{image_id}:{result.get('id') or box_index}"
                record = CropRecord(
                    crop_id=crop_id,
                    image_id=image_id,
                    image_url=image_url,
                    original_width=int(result["original_width"]),
                    original_height=int(result["original_height"]),
                    x=float(value["x"]),
                    y=float(value["y"]),
                    width=float(value["width"]),
                    height=float(value["height"]),
                )
                self.crops[crop_id] = record
                crop_summaries.append(self.public_crop(record))
            self.images.append(
                {
                    "image_id": image_id,
                    "image_url": image_url,
                    "source_row": task.get("meta", {}).get("source_csv_row"),
                    "crop_count": len(crop_summaries),
                    "crops": crop_summaries,
                }
            )

    @staticmethod
    def public_crop(crop: CropRecord) -> dict[str, Any]:
        return {
            "crop_id": crop.crop_id,
            "original_width": crop.original_width,
            "original_height": crop.original_height,
            "box": {
                "x": crop.x,
                "y": crop.y,
                "width": crop.width,
                "height": crop.height,
            },
        }

    def payload(self) -> dict[str, Any]:
        return {
            "images": self.images,
            "image_count": len(self.images),
            "crop_count": len(self.crops),
        }

