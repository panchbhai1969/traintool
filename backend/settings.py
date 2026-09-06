from __future__ import annotations

import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_dotenv() -> None:
    """Load local settings without overriding the process environment."""
    for path in (ROOT.parent / ".env", ROOT / ".env"):
        if not path.exists():
            continue
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


load_dotenv()

OPENROUTER_API_KEY_KEY = "OPENROUTER_API_KEY"
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/")
DEFAULT_MODEL = os.getenv("OPENROUTER_MODEL", "qwen/qwen3-vl-235b-a22b-instruct")
ENHANCE_MODEL = os.getenv("ENHANCE_MODEL", "openai/gpt-image-2")
ENHANCE_PROMPT = os.getenv("ENHANCE_PROMPT", "enhance the image")
TOOTH_API_URL = os.getenv("TOOTH_API_URL", "https://internal9.logy.ai/runsync")
TOOTH_API_KEY = os.getenv("TOOTH_API_KEY")
APP_PASSWORD = os.getenv("TRAINTOOL") or None
DATA_DIR = ROOT / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
CROP_DIR = DATA_DIR / "crops"
