"""Build assistant context from current deterministic state only."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


SAFE_STATE_FIELDS = (
    "contract",
    "generated_at",
    "opportunity_contract",
    "inputs",
    "opportunities",
    "machines",
    "capabilities",
    "transitions",
    "boundaries",
)


def load_current_state(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    state = json.loads(path.read_text(encoding="utf-8"))
    safe = {key: state.get(key) for key in SAFE_STATE_FIELDS if key in state}
    return {
        "score": 1.0,
        "payload": {
            "source": "homeauto-world-state:current",
            "chunk": 0,
            "text": json.dumps(safe, sort_keys=True),
        },
    }


def filter_retrieval_chunks(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        chunk for chunk in chunks
        if "/coordination/" not in str(chunk.get("payload", {}).get("source", "")).replace("\\", "/")
    ]
