import json
from pathlib import Path

import pytest
from jsonschema.exceptions import ValidationError
from PIL import Image

from backend.dataset import CropRecord
from backend.evaluator import _prepare_crop, _source_image, build_openrouter_payload, build_system_prompt, parse_and_validate


SCHEMA = {
    "type": "object",
    "required": ["verdict"],
    "properties": {"verdict": {"type": "string", "enum": ["present", "absent"]}},
}


def test_parser_accepts_json_and_markdown_fence() -> None:
    expected = {"verdict": "present"}
    assert parse_and_validate(json.dumps(expected), SCHEMA) == expected
    assert parse_and_validate('```json\n{"verdict":"present"}\n```', SCHEMA) == expected
    assert parse_and_validate('```\n{"verdict":"present"}\n```', SCHEMA) == expected


def test_parser_rejects_schema_mismatch() -> None:
    with pytest.raises(ValidationError):
        parse_and_validate('{"verdict":"uncertain"}', SCHEMA)


def test_system_prompt_requests_explanation_before_verdict() -> None:
    prompt = build_system_prompt("Evaluate", {"type": "object"}, "caries")
    assert prompt.index("explanation first") < prompt.index("present-or-absent verdict")
    assert "adjacent enamel" in prompt
    assert "image-quality limitations" in prompt
    assert "for caries" in prompt
    assert prompt.endswith('{"type":"object"}')


def test_openrouter_payload_leaves_sampling_parameters_to_provider() -> None:
    payload = build_openrouter_payload("test/model", [{"role": "user", "content": "test"}], 100)
    assert "temperature" not in payload
    assert "seed" not in payload


def test_crop_padding_is_clipped_at_image_edge(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "source.png"
    Image.new("RGB", (100, 80), "white").save(source)
    monkeypatch.setattr("backend.evaluator.CROP_DIR", tmp_path / "crops")
    crop = CropRecord("image:crop", "image", "https://example.test/image", 100, 80, 0, 0, 20, 25)
    output, data_url = _prepare_crop(source, crop, .25, 896)
    assert output.exists()
    assert Image.open(output).size == (25, 25)
    assert data_url.startswith("data:image/jpeg;base64,")


@pytest.mark.asyncio
async def test_uploaded_crop_uses_local_source_without_http(tmp_path: Path) -> None:
    source = tmp_path / "upload.jpg"
    Image.new("RGB", (100, 80), "white").save(source)
    crop = CropRecord("image:crop", "image", "/api/uploads/image", 100, 80, 0, 0, 20, 25, source)

    class NoDownloadClient:
        async def get(self, *_args, **_kwargs):
            raise AssertionError("Uploaded image should not be downloaded")

    assert await _source_image(NoDownloadClient(), crop) == source
