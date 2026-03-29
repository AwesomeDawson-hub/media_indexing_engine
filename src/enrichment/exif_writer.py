"""EXIF + IPTC writing for JPEG and TIFF using piexif + iptcinfo3."""

import io
import tempfile
import os

import piexif
from PIL import Image
from iptcinfo3 import IPTCInfo

from src.analysis.schemas import MediaMetadataResult
from src.enrichment.field_mapping import build_exif_dict, build_iptc_data


def _merge_exif(existing_bytes: bytes, ai_exif: dict) -> bytes:
    """Merge AI EXIF fields into existing EXIF data, preserving camera info."""
    try:
        existing = piexif.load(existing_bytes)
    except Exception:
        existing = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}, "thumbnail": None}

    for ifd in ("0th", "Exif"):
        if ifd in ai_exif:
            for tag, value in ai_exif[ifd].items():
                existing[ifd][tag] = value

    return piexif.dump(existing)


def _apply_iptc(file_bytes: bytes, metadata: MediaMetadataResult, suffix: str) -> bytes:
    """Apply IPTC metadata using iptcinfo3 (requires temp file)."""
    iptc_data = build_iptc_data(metadata)

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name

    try:
        info = IPTCInfo(tmp_path)
        if iptc_data.get("headline"):
            info["headline"] = iptc_data["headline"]
        if iptc_data.get("caption/abstract"):
            info["caption/abstract"] = iptc_data["caption/abstract"]
        if iptc_data.get("keywords"):
            info["keywords"] = iptc_data["keywords"]
        if iptc_data.get("supplemental category"):
            info["supplemental category"] = iptc_data["supplemental category"]
        if iptc_data.get("city"):
            info["city"] = iptc_data["city"]
        if iptc_data.get("special instructions"):
            info["special instructions"] = iptc_data["special instructions"]
        info.save()

        with open(tmp_path, "rb") as f:
            return f.read()
    finally:
        for p in (tmp_path, tmp_path + "~"):
            try:
                os.unlink(p)
            except OSError:
                pass


def embed_jpeg(file_bytes: bytes, metadata: MediaMetadataResult) -> bytes:
    """Embed EXIF + IPTC metadata into a JPEG file."""
    # Use Pillow to load and re-save with merged EXIF (avoids piexif.insert file path issues)
    img = Image.open(io.BytesIO(file_bytes))

    ai_exif = build_exif_dict(metadata)
    exif_bytes = _merge_exif(file_bytes, ai_exif)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif_bytes, quality=95)
    jpeg_bytes = buf.getvalue()

    # Apply IPTC
    jpeg_bytes = _apply_iptc(jpeg_bytes, metadata, ".jpg")
    return jpeg_bytes


def embed_tiff(file_bytes: bytes, metadata: MediaMetadataResult) -> bytes:
    """Embed EXIF + IPTC metadata into a TIFF file."""
    img = Image.open(io.BytesIO(file_bytes))

    ai_exif = build_exif_dict(metadata)
    exif_bytes = _merge_exif(file_bytes, ai_exif)

    buf = io.BytesIO()
    img.save(buf, format="TIFF", exif=exif_bytes)
    tiff_bytes = buf.getvalue()

    tiff_bytes = _apply_iptc(tiff_bytes, metadata, ".tiff")
    return tiff_bytes
