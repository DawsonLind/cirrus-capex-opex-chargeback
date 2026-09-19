"""Load Cursor Admin API key without ever printing or logging it."""

from __future__ import annotations

import json
import os
from pathlib import Path

DEFAULT_SECRETS_PATH = Path("/home/box/agent-data/box-secrets.json")


def load_api_key(secrets_path: str | Path | None = None) -> str:
    """Return API key from CURSOR_API_KEY env, else box-secrets.json card.

    Raises RuntimeError if no key is found. Never logs the key value.
    """
    env_key = os.environ.get("CURSOR_API_KEY", "").strip()
    if env_key:
        return env_key

    path = Path(secrets_path) if secrets_path else DEFAULT_SECRETS_PATH
    if not path.is_file():
        raise RuntimeError(
            "CURSOR_API_KEY not set and secrets file not found. "
            "Set CURSOR_API_KEY or provide box-secrets.json."
        )

    with path.open() as f:
        data = json.load(f)

    card = data.get("card") if isinstance(data, dict) else None
    if isinstance(card, dict):
        key = (card.get("CURSOR_API_KEY") or "").strip()
        if key:
            return key

    # Fallback: top-level key
    if isinstance(data, dict):
        key = (data.get("CURSOR_API_KEY") or "").strip()
        if key:
            return key

    raise RuntimeError(
        "CURSOR_API_KEY not found in environment or secrets file (card.CURSOR_API_KEY)."
    )
