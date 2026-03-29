"""Map MediaMetadataResult fields to EXIF/IPTC tags and UserComment text."""

import piexif

from src.analysis.schemas import MediaMetadataResult


def build_user_comment(metadata: MediaMetadataResult) -> str:
    """Build extended UserComment text for fields without standard EXIF/IPTC tags."""
    parts = [metadata.description]
    parts.append(f"\nContext: {metadata.context}")
    parts.append(f"Mood: {metadata.mood}")
    if metadata.scenes:
        parts.append(f"Scenes: {', '.join(metadata.scenes)}")
    if metadata.people:
        parts.append(f"People: {', '.join(metadata.people)} ({metadata.people_count})")
    elif metadata.people_count > 0:
        parts.append(f"People: {metadata.people_count}")
    if metadata.colors:
        parts.append(f"Colors: {', '.join(metadata.colors)}")
    return "\n".join(parts)


def build_exif_dict(metadata: MediaMetadataResult) -> dict:
    """Build a piexif-compatible EXIF dict from metadata fields.

    Only sets AI-specific fields — merge with existing EXIF to preserve camera data.
    """
    user_comment = build_user_comment(metadata)
    # EXIF UserComment: 8-byte charset prefix + encoded text
    # Use ASCII encoding (most compatible with viewers)
    user_comment_bytes = b"ASCII\x00\x00\x00" + user_comment.encode("ascii", errors="replace")

    exif_dict = {
        "0th": {
            piexif.ImageIFD.ImageDescription: metadata.title.encode("utf-8"),
        },
        "Exif": {
            piexif.ExifIFD.UserComment: user_comment_bytes,
        },
    }
    return exif_dict


def build_iptc_keywords(metadata: MediaMetadataResult) -> list[str]:
    """Build IPTC keywords list from tags + objects."""
    keywords = list(metadata.tags)
    for obj in metadata.objects:
        if obj.lower() not in [k.lower() for k in keywords]:
            keywords.append(obj)
    return keywords


def build_iptc_data(metadata: MediaMetadataResult) -> dict:
    """Build IPTC field dict for iptcinfo3.

    Keys are IPTC tag numbers: 2:105 (headline), 2:120 (caption),
    2:25 (keywords), 2:20 (supplemental categories), 2:90 (city), 2:40 (special instructions).
    """
    data = {
        "headline": metadata.title,
        "caption/abstract": metadata.description,
        "keywords": build_iptc_keywords(metadata),
    }
    if metadata.objects:
        data["supplemental category"] = metadata.objects
    if metadata.location_hint:
        data["city"] = metadata.location_hint
    if metadata.context:
        data["special instructions"] = metadata.context
    return data
