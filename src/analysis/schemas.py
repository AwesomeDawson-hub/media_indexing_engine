"""Structured metadata result schema and AI response parser (ADR-005)."""

import json
import re

from pydantic import BaseModel, field_validator


class MediaMetadataResult(BaseModel):
    """Validated metadata result matching the 13-field ADR-005 schema."""

    title: str
    description: str
    tags: list[str]
    objects: list[str]
    scenes: list[str]
    context: str
    mood: str
    people: list[str]
    people_count: int
    orientation: str
    colors: list[str]
    location_hint: str | None = None
    quality_notes: str | None = None

    @field_validator("people_count")
    @classmethod
    def people_count_non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError("people_count must be non-negative")
        return v

    @field_validator("orientation")
    @classmethod
    def orientation_valid(cls, v: str) -> str:
        allowed = {"landscape", "portrait", "square"}
        if v not in allowed:
            raise ValueError(f"orientation must be one of {allowed}, got '{v}'")
        return v

    @field_validator("tags", "objects", "scenes", "colors")
    @classmethod
    def non_empty_list(cls, v: list[str]) -> list[str]:
        if len(v) == 0:
            raise ValueError("list must not be empty")
        return v


def parse_ai_response(raw_text: str) -> MediaMetadataResult:
    """Extract and validate structured metadata from an AI response.

    Handles:
    - Raw JSON
    - JSON wrapped in markdown fences (```json ... ```)
    - JSON with surrounding text
    """
    # Strip markdown fences if present
    cleaned = raw_text.strip()
    fence_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", cleaned, re.DOTALL)
    if fence_match:
        cleaned = fence_match.group(1).strip()

    # Find the JSON object in the text
    brace_start = cleaned.find("{")
    brace_end = cleaned.rfind("}")
    if brace_start == -1 or brace_end == -1:
        raise ValueError("No JSON object found in AI response")

    json_str = cleaned[brace_start : brace_end + 1]

    data = json.loads(json_str)
    return MediaMetadataResult.model_validate(data)
