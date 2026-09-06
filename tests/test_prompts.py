from pathlib import Path

import pytest

from backend import prompts


def test_prompt_store_loads_and_atomically_saves_fixed_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = {finding: tmp_path / f"{finding}.md" for finding in prompts.FINDINGS}
    for finding, path in paths.items():
        path.write_text(f"Original {finding}\n", encoding="utf-8")
    monkeypatch.setattr(prompts, "PROMPT_PATHS", paths)

    assert prompts.load_prompts()["stain"] == "Original stain"
    assert prompts.save_prompt("calculus", "  Updated calculus  ") == "Updated calculus"
    assert paths["calculus"].read_text(encoding="utf-8") == "Updated calculus\n"
    assert not (tmp_path / "calculus.md.tmp").exists()


def test_prompt_store_rejects_unknown_finding_and_blank_prompt() -> None:
    with pytest.raises(ValueError, match="Unsupported finding"):
        prompts.save_prompt("../other", "Prompt")
    with pytest.raises(ValueError, match="cannot be empty"):
        prompts.save_prompt("stain", "   ")
