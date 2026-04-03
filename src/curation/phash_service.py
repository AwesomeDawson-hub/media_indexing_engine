"""Perceptual hashing service for near-duplicate image detection.

Algorithm: 64-bit DCT perceptual hash (pHash) via the `imagehash` library.
Stored as 16 lowercase hex characters.  Two images are considered near-
duplicates when their Hamming distance is ≤ PHASH_THRESHOLD (10 bits).

Image normalisation pipeline (applied before hashing):
  1. Open via PIL from raw bytes.
  2. Apply EXIF orientation transpose so rotated originals hash consistently.
  3. Composite transparent images onto a white background (removes alpha channel).
  4. Convert to greyscale (L mode).
  5. Resize to 32×32 using LANCZOS — imagehash uses this internally for pHash.
  6. Compute 64-bit pHash; serialise to 16 lowercase hex chars.

Supported MIME types: JPEG, PNG, WebP, TIFF, BMP, AVIF.
GIF is explicitly excluded — the hash would be computed from the first frame
only, which misleads similarity scoring.  upload flow continues normally; the
perceptual_hash column is left NULL.
"""
from __future__ import annotations

import io
import logging
from datetime import datetime, timezone

import imagehash
from PIL import Image, ImageOps

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Public constants
# ---------------------------------------------------------------------------

PHASH_VERSION = "phash64-v1"

# Hamming distance ≤ this value → images are considered near-duplicates.
# 10 bits out of 64 ≈ 84 % similarity, tuned to catch crops / brightness
# shifts while avoiding false positives between distinct subjects.
PHASH_THRESHOLD = 10

# MIME types for which we generate a perceptual hash.
SUPPORTED_MIME_TYPES: frozenset[str] = frozenset(
    {
        "image/jpeg",
        "image/png",
        "image/webp",
        "image/tiff",
        "image/bmp",
        "image/avif",
    }
)


# ---------------------------------------------------------------------------
# Core helpers
# ---------------------------------------------------------------------------


def _normalise_image(img: Image.Image) -> Image.Image:
    """Return a normalised greyscale PIL image ready for pHash computation.

    Steps:
      1. EXIF transpose (in-place rotation/flip correction).
      2. Alpha composite onto white if image has transparency.
      3. Convert to greyscale.
    """
    # Step 1: correct EXIF orientation
    img = ImageOps.exif_transpose(img) or img

    # Step 2: flatten alpha channel onto white background
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        background = Image.new("RGB", img.size, (255, 255, 255))
        if img.mode == "P":
            img = img.convert("RGBA")
        background.paste(img, mask=img.split()[-1] if img.mode in ("RGBA", "LA") else None)
        img = background
    elif img.mode != "RGB":
        img = img.convert("RGB")

    # Step 3: convert to greyscale for pHash
    img = img.convert("L")
    return img


def compute_phash(file_bytes: bytes, mime_type: str) -> str | None:
    """Compute the perceptual hash of an image given its raw bytes.

    Returns a 16-character lowercase hex string, or None when:
      - The MIME type is not in SUPPORTED_MIME_TYPES (e.g. GIF).
      - PIL cannot decode the image (corrupted / unsupported sub-format).
      - Any unexpected error occurs (logged at WARNING level).

    Callers must handle None gracefully — it is not an error condition.
    """
    if mime_type not in SUPPORTED_MIME_TYPES:
        return None

    try:
        img = Image.open(io.BytesIO(file_bytes))
        img = _normalise_image(img)
        ph = imagehash.phash(img, hash_size=8)  # 8×8 = 64 bits
        return str(ph)  # imagehash __str__ returns lowercase hex, 16 chars
    except Exception as exc:  # noqa: BLE001
        logger.warning("pHash computation failed (mime=%s): %s", mime_type, exc)
        return None


def hamming_distance(h1: str, h2: str) -> int:
    """Return the Hamming distance (differing bits) between two 16-char hex hashes.

    Both values must be 16 lowercase hex characters as returned by
    `compute_phash`.  Raises ValueError for malformed inputs.
    """
    if len(h1) != 16 or len(h2) != 16:
        raise ValueError(
            f"pHash strings must be exactly 16 hex characters; "
            f"got len={len(h1)} and len={len(h2)}"
        )
    xor = int(h1, 16) ^ int(h2, 16)
    return bin(xor).count("1")


def find_similar(
    candidates: list[tuple[str, str]],
    anchor_hash: str,
    threshold: int = PHASH_THRESHOLD,
) -> list[tuple[str, int]]:
    """Return items from *candidates* whose pHash is within *threshold* bits of *anchor_hash*.

    Arguments:
        candidates: list of (media_item_id, perceptual_hash) pairs.  Items
                    with a NULL / empty hash are silently skipped.
        anchor_hash: 16-char hex hash for the item being queried.
        threshold:  maximum Hamming distance to consider near-duplicate.

    Returns:
        List of (media_item_id, hamming_distance) sorted by distance ascending.
        The anchor item should be excluded from *candidates* by the caller.
    """
    results: list[tuple[str, int]] = []
    for item_id, candidate_hash in candidates:
        if not candidate_hash:
            continue
        try:
            dist = hamming_distance(anchor_hash, candidate_hash)
        except ValueError:
            continue
        if dist <= threshold:
            results.append((item_id, dist))
    results.sort(key=lambda t: t[1])
    return results


def phash_timestamp() -> datetime:
    """Return current UTC timestamp for use in phash_computed_at."""
    return datetime.now(timezone.utc)
