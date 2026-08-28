"""JSON extraction helpers for LLM responses."""

from __future__ import annotations

import json
import re
from typing import Any


class JSONExtractionError(ValueError):
    """Raised when no valid JSON object can be extracted from model output."""


def strip_markdown_code_fence(text: str) -> str:
    """Remove common markdown code fences around JSON."""
    text = text.strip()

    full_fence_pattern = r"^```(?:json|JSON)?\s*(.*?)\s*```$"
    match = re.match(full_fence_pattern, text, flags=re.DOTALL)

    if match:
        return match.group(1).strip()

    # Handle opening fence without closing fence.
    if text.startswith("```json"):
        return text[len("```json"):].strip()

    if text.startswith("```JSON"):
        return text[len("```JSON"):].strip()

    if text.startswith("```"):
        return text[len("```"):].strip()

    return text

def find_first_json_object(text: str) -> str:
    """Extract the first balanced JSON object from arbitrary text."""
    text = strip_markdown_code_fence(text)

    start = text.find("{")
    if start == -1:
        raise JSONExtractionError("No opening '{' found in model output.")

    depth = 0
    in_string = False
    escape = False

    for index in range(start, len(text)):
        char = text[index]

        if escape:
            escape = False
            continue

        if char == "\\":
            escape = True
            continue

        if char == '"':
            in_string = not in_string
            continue

        if in_string:
            continue

        if char == "{":
            depth += 1

        elif char == "}":
            depth -= 1

            if depth == 0:
                return text[start : index + 1]

    raise JSONExtractionError("No balanced JSON object found in model output.")


def parse_json_object(raw_text: str) -> dict[str, Any]:
    """Parse a JSON object from raw model output."""
    try:
        json_text = find_first_json_object(raw_text)
        payload = json.loads(json_text)
    except Exception as exc:
        preview = raw_text[:1500]
        raise JSONExtractionError(
            f"Could not parse JSON object. Error={exc}. Output preview={preview}"
        ) from exc

    if not isinstance(payload, dict):
        raise JSONExtractionError(
            f"Expected JSON object, got {type(payload).__name__}."
        )

    return payload


def try_parse_json_object(
    raw_text: str,
) -> tuple[dict[str, Any] | None, str | None]:
    """Return parsed JSON or an error message."""
    try:
        return parse_json_object(raw_text), None
    except Exception as exc:
        return None, str(exc)


def compact_json_schema_hint(schema: dict[str, Any]) -> str:
    """Format a schema/example dict for prompt inclusion."""
    return json.dumps(schema, ensure_ascii=False, indent=2)
