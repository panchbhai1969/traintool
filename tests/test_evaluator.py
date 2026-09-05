import json
from pathlib import Path

import pytest
from jsonschema.exceptions import ValidationError
from PIL import Image

from backend.dataset import CropRecord
from backend.evaluator import _prepare_crop, parse_and_validate


SCHEMA = {
    "type": "object",
    "required": ["stain_present"],
    "properties": {"stain_present": {"type": "boolean"}},
}


def test_parser_accepts_json_and_markdown_fence() -> None:
    expected = {"stain_present": True}
    assert parse_and_validate(json.dumps(expected), SCHEMA) == expected
    assert parse_and_validate("```json\n{\"stain_present\": true}\n```", SCHEMA) == expected
    assert parse_and_validate("```\n{\"stain_present\": true}\n```", SCHEMA) == expected


def test_parser_rejects_schema_mismatch() -> None:
    with pytest.raises(ValidationError):
        parse_and_validate('{"stain_present":"yes"}', SCHEMA)


def test_crop_padding_is_clipped_at_image_edge(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "source.png"
    Image.new("RGB", (100, 80), "white").save(source)
    monkeypatch.setattr("backend.evaluator.CROP_DIR", tmp_path / "crops")
    crop = CropRecord("image:crop", "image", "https://example.test/image", 100, 80, 0, 0, 20, 25)
    output, data_url = _prepare_crop(source, crop, .25, 896)
    assert output.exists()
    assert Image.open(output).size == (25, 25)
    assert data_url.startswith("data:image/jpeg;base64,")
