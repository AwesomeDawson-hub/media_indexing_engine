"""EXIF writing for AVIF via pillow-heif + piexif."""

import io

import piexif
from PIL import Image
from pillow_heif import register_heif_opener

from src.analysis.schemas import MediaMetadataResult
from src.enrichment.field_mapping import build_exif_dict

# Register AVIF/HEIF support with Pillow
register_heif_opener()


def embed_avif(file_bytes: bytes, metadata: MediaMetadataResult) -> bytes:
    """Embed EXIF metadata into an AVIF file."""
    img = Image.open(io.BytesIO(file_bytes))

    ai_exif = build_exif_dict(metadata)

    # Try to preserve existing EXIF
    existing_exif = img.info.get("exif", b"")
    if existing_exif:
        try:
            existing = piexif.load(existing_exif)
            for ifd in ("0th", "Exif"):
                if ifd in ai_exif:
                    for tag, value in ai_exif[ifd].items():
                        existing[ifd][tag] = value
            exif_bytes = piexif.dump(existing)
        except Exception:
            exif_bytes = piexif.dump(ai_exif)
    else:
        exif_bytes = piexif.dump(ai_exif)

    buf = io.BytesIO()
    img.save(buf, format="AVIF", exif=exif_bytes, quality=90)
    return buf.getvalue()
