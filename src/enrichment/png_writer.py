"""XMP embedding for PNG via Pillow iTXt chunk."""

import io

from PIL import Image
from PIL.PngImagePlugin import PngInfo

from src.analysis.schemas import MediaMetadataResult
from src.enrichment.xmp_builder import build_xmp_xml


def embed_png(file_bytes: bytes, metadata: MediaMetadataResult) -> bytes:
    """Embed XMP metadata into a PNG file via iTXt chunk."""
    img = Image.open(io.BytesIO(file_bytes))

    xmp_xml = build_xmp_xml(metadata)

    # Build PngInfo with the XMP chunk
    png_info = PngInfo()

    # Preserve existing text chunks
    if hasattr(img, "text") and img.text:
        for key, value in img.text.items():
            if key != "XML:com.adobe.xmp":  # Don't duplicate XMP
                png_info.add_text(key, value)

    # Add XMP as iTXt chunk (the standard Adobe keyword)
    png_info.add_itxt("XML:com.adobe.xmp", xmp_xml)

    buf = io.BytesIO()
    img.save(buf, format="PNG", pnginfo=png_info)
    return buf.getvalue()
