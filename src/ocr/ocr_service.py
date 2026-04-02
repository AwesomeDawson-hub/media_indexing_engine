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

        # Upscale small images — Tesseract accuracy drops below ~300dpi equivalent
        min_dim = min(img.width, img.height)
        if min_dim < 1000:
            scale = max(2, 1000 // min_dim)
            img = img.resize((img.width * scale, img.height * scale), Image.LANCZOS)

        # psm 11 = sparse text, finds text anywhere regardless of layout
        # Best for posters, collages, signage, screenshots with mixed regions
        config = "--psm 11 --oem 1"
        text: str = pytesseract.image_to_string(img, config=config)
        # Collapse runs of whitespace/newlines into single spaces — PSM 11
        # produces many single-word fragments on separate lines
        import re
        text = re.sub(r'[\r\n]+', ' ', text)
        text = re.sub(r'[ \t]{2,}', ' ', text)
        text = text.strip()

        if len(text) > _MAX_OCR_CHARS:
            text = text[:_MAX_OCR_CHARS]

        # Quality filter: real OCR text has a high proportion of word-like
        # tokens (>=3 chars, >=80% alphabetic). Garbled texture-noise output
        # floods with short mixed tokens like "1)", "ca1", "ge1", "w=", "|".
        # Discard if fewer than 40% of tokens look like real words.
        tokens = text.split()
        if tokens:
            word_like = sum(
                1 for t in tokens
                if len(t) >= 3 and sum(c.isalpha() for c in t) / len(t) >= 0.8
            )
            if word_like / len(tokens) < 0.20:
                logger.debug(
                    "OCR result discarded as noise (word ratio %.2f): %r",
                    word_like / len(tokens), text[:80],
                )
                return ""

        return text
    except Exception as exc:
        # Tesseract not found, image unreadable, etc. — always non-fatal
        logger.debug("OCR extraction failed (%s): %s", mime_type, exc)
        return ""
