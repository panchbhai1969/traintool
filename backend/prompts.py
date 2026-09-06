from __future__ import annotations

from pathlib import Path

from .settings import ROOT


FINDINGS = ("stain", "calculus", "caries")
DEFAULT_FINDING = "stain"
PROMPT_PATHS: dict[str, Path] = {finding: ROOT / f"{finding}.md" for finding in FINDINGS}


def load_prompts() -> dict[str, str]:
    prompts: dict[str, str] = {}
    for finding, path in PROMPT_PATHS.items():
        try:
            prompts[finding] = path.read_text(encoding="utf-8").strip()
        except FileNotFoundError as error:
            raise RuntimeError(f"Missing prompt file: {path.name}") from error
    return prompts


def save_prompt(finding: str, prompt: str) -> str:
    path = PROMPT_PATHS.get(finding)
    if path is None:
        raise ValueError(f"Unsupported finding: {finding}")
    normalized = prompt.strip()
    if not normalized:
        raise ValueError("Prompt cannot be empty")
    temporary = path.with_suffix(".md.tmp")
    temporary.write_text(f"{normalized}\n", encoding="utf-8")
    temporary.replace(path)
    return normalized
