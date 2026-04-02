"""OCR service: extract text from images using Tesseract via pytesseract."""

from __future__ import annotations

import io
import logging

from PIL import Image

logger = logging.getLogger(__name__)

# Maximum characters to store from OCR output (prevent runaway text storage)
_MAX_OCR_CHARS = 5000

_SUPPORTED_MIME_TYPES = {
    "image/jpeg",
    "image/png",
    "image/tiff",
    "image/webp",
    "image/avif",
    "image/bmp",
    "image/gif",
}


def extract_text(file_bytes: bytes, mime_type: str) -> str:
    """Extract text from an image using Tesseract OCR.

    Returns the extracted text string, or an empty string if:
    - The MIME type is not a supported image format
    - Tesseract is not installed on the system
    - OCR produces no output
    - Any other error occurs (non-fatal)
    """
    if mime_type not in _SUPPORTED_MIME_TYPES:
        return ""

    try:
        import pytesseract
    except ImportError:
        logger.debug("pytesseract not installed — OCR skipped")
        return ""

    try:
        img = Image.open(io.BytesIO(file_bytes))
        # Convert palette / RGBA to RGB for Tesseract compatibility
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")

        text: str = pytesseract.image_to_string(img)
        text = text.strip()

        if len(text) > _MAX_OCR_CHARS:
            text = text[:_MAX_OCR_CHARS]

        return text
    except Exception as exc:
        # Tesseract not found, image unreadable, etc. — always non-fatal
        logger.debug("OCR extraction failed (%s): %s", mime_type, exc)
        return ""
