"""Construct embedding text from metadata fields for vector indexing."""

import json

from src.analysis.schemas import MediaMetadataResult
from src.models import MediaMetadata


def _join_list(data: list[str]) -> str:
    return ", ".join(data) if data else ""


def build_embedding_text(metadata: MediaMetadataResult) -> str:
    """Build embedding text from a Pydantic metadata result (used during analysis flow)."""
    parts = [
        metadata.title,
        "",
        metadata.description,
        "",
    ]

    if metadata.tags:
        parts.append(f"Tags: {_join_list(metadata.tags)}")
    if metadata.objects:
        parts.append(f"Objects: {_join_list(metadata.objects)}")
    if metadata.scenes:
        parts.append(f"Scenes: {_join_list(metadata.scenes)}")
    parts.append(f"Context: {metadata.context}")
    parts.append(f"Mood: {metadata.mood}")
    if metadata.colors:
        parts.append(f"Colors: {_join_list(metadata.colors)}")
    if metadata.people:
        parts.append(f"People: {_join_list(metadata.people)} ({metadata.people_count} people)")
    elif metadata.people_count > 0:
        parts.append(f"People: {metadata.people_count} people")
    parts.append(f"Orientation: {metadata.orientation}")
    parts.append(f"Location: {metadata.location_hint or 'Unknown'}")

    return "\n".join(parts)


def build_embedding_text_from_db(meta: MediaMetadata) -> str:
    """Build embedding text from an ORM model (used during rebuild)."""
    tags = json.loads(meta.tags)
    objects = json.loads(meta.objects)
    scenes = json.loads(meta.scenes)
    people = json.loads(meta.people)
    colors = json.loads(meta.colors)

    parts = [
        meta.title,
        "",
        meta.description,
        "",
    ]

    if tags:
        parts.append(f"Tags: {_join_list(tags)}")
    if objects:
        parts.append(f"Objects: {_join_list(objects)}")
    if scenes:
        parts.append(f"Scenes: {_join_list(scenes)}")
    parts.append(f"Context: {meta.context}")
    parts.append(f"Mood: {meta.mood}")
    if colors:
        parts.append(f"Colors: {_join_list(colors)}")
    if people:
        parts.append(f"People: {_join_list(people)} ({meta.people_count} people)")
    elif meta.people_count > 0:
        parts.append(f"People: {meta.people_count} people")
    parts.append(f"Orientation: {meta.orientation}")
    parts.append(f"Location: {meta.location_hint or 'Unknown'}")

    return "\n".join(parts)
