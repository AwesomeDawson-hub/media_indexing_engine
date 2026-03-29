"""Metadata embedder: routes by MIME type to format-specific writers."""

import io
import logging
from dataclasses import dataclass

from PIL import Image

from src.analysis.schemas import MediaMetadataResult

logger = logging.getLogger(__name__)


@dataclass
class EnrichmentResult:
    enriched_bytes: bytes
    embedded: bool
    output_mime_type: str
    output_filename: str


class MetadataEmbedder:
    """Stateless embedder: takes bytes + metadata, returns enriched bytes."""

    def embed(
        self,
        file_bytes: bytes,
        mime_type: str,
        metadata: MediaMetadataResult,
        original_filename: str = "image",
    ) -> EnrichmentResult:
        """Embed metadata into an image file based on its MIME type."""
        try:
            if mime_type == "image/jpeg":
                from src.enrichment.exif_writer import embed_jpeg
                enriched = embed_jpeg(file_bytes, metadata)
                return EnrichmentResult(enriched, True, mime_type, original_filename)

            elif mime_type == "image/tiff":
                from src.enrichment.exif_writer import embed_tiff
                enriched = embed_tiff(file_bytes, metadata)
                return EnrichmentResult(enriched, True, mime_type, original_filename)

            elif mime_type == "image/webp":
                from src.enrichment.webp_writer import embed_webp
                enriched = embed_webp(file_bytes, metadata)
                return EnrichmentResult(enriched, True, mime_type, original_filename)

            elif mime_type == "image/avif":
                from src.enrichment.avif_writer import embed_avif
                enriched = embed_avif(file_bytes, metadata)
                return EnrichmentResult(enriched, True, mime_type, original_filename)

            elif mime_type == "image/png":
                from src.enrichment.png_writer import embed_png
                enriched = embed_png(file_bytes, metadata)
                return EnrichmentResult(enriched, True, mime_type, original_filename)

            else:
                # BMP, GIF, or unknown — return original unchanged
                return EnrichmentResult(file_bytes, False, mime_type, original_filename)

        except Exception as e:
            logger.warning("Metadata embedding failed for %s (%s): %s", original_filename, mime_type, e)
            # Fallback: return original file unchanged
            return EnrichmentResult(file_bytes, False, mime_type, original_filename)

    def convert_to_png_with_metadata(
        self,
        file_bytes: bytes,
        metadata: MediaMetadataResult,
        original_filename: str = "image",
    ) -> EnrichmentResult:
        """Convert any image to PNG and embed XMP metadata."""
        from src.enrichment.png_writer import embed_png

        # Convert to PNG via Pillow
        img = Image.open(io.BytesIO(file_bytes))
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGBA")
        elif img.mode != "RGB":
            img = img.convert("RGB")

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        png_bytes = buf.getvalue()

        # Embed XMP
        enriched = embed_png(png_bytes, metadata)

        # Generate new filename
        base = original_filename.rsplit(".", 1)[0] if "." in original_filename else original_filename
        new_filename = f"{base}.png"

        return EnrichmentResult(enriched, True, "image/png", new_filename)
