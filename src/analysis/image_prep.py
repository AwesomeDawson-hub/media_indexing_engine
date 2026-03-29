"""Image preparation for AI vision API submission.

Resizes large images and converts to JPEG base64 for the Anthropic API.
"""

import base64
import io

from PIL import Image

from src.config import settings


def prepare_image(
    file_bytes: bytes,
    mime_type: str,
    max_dimension: int | None = None,
) -> tuple[str, str]:
    """Resize image if needed, convert to JPEG, return (base64_str, media_type).

    Args:
        file_bytes: Raw image file bytes.
        mime_type: Original MIME type of the image.
        max_dimension: Max pixels on longest side. Defaults to config value.

    Returns:
        Tuple of (base64-encoded JPEG string, "image/jpeg").
    """
    if max_dimension is None:
        max_dimension = settings.analysis.max_image_dimension

    img = Image.open(io.BytesIO(file_bytes))

    # Handle transparency (RGBA/P → RGB) for JPEG conversion
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    elif img.mode != "RGB":
        img = img.convert("RGB")

    # Resize if longest side exceeds max_dimension
    width, height = img.size
    longest = max(width, height)
    if longest > max_dimension:
        scale = max_dimension / longest
        new_width = int(width * scale)
        new_height = int(height * scale)
        img = img.resize((new_width, new_height), Image.LANCZOS)

    # Encode to JPEG bytes
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=85)
    jpeg_bytes = buffer.getvalue()

    return base64.b64encode(jpeg_bytes).decode("ascii"), "image/jpeg"
