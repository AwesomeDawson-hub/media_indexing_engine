"""Tests for the OCR service (P4-006)."""

import io
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from src.ocr.ocr_service import extract_text


def _make_jpeg(text_color: str = "black") -> bytes:
    img = Image.new("RGB", (200, 50), "white")
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def _make_png() -> bytes:
    img = Image.new("RGB", (200, 50), "white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Unit tests — mock pytesseract so Tesseract binary is not required
# ---------------------------------------------------------------------------


def test_extract_text_returns_text_from_mock():
    """extract_text returns the string from pytesseract when available."""
    with patch("pytesseract.image_to_string", return_value="Hello World"):
        result = extract_text(_make_jpeg(), "image/jpeg")
    assert result == "Hello World"


def test_extract_text_strips_whitespace():
    """extract_text strips leading/trailing whitespace from OCR output."""
    with patch("pytesseract.image_to_string", return_value="  hello  "):
        result = extract_text(_make_jpeg(), "image/jpeg")
    assert result == "hello"


def test_extract_text_collapses_newlines():
    """Newlines and multi-space runs are collapsed to single spaces."""
    with patch("pytesseract.image_to_string", return_value="VISITING THE\nPolynesian\nCultural Center\n"):
        result = extract_text(_make_jpeg(), "image/jpeg")
    assert result == "VISITING THE Polynesian Cultural Center"


def test_extract_text_discards_garbled_noise():
    """Results where <20% of tokens look like real words (len>=3, >=80% alpha) return ''."""
    # Extreme noise: almost entirely digits, symbols, 1-2 char fragments
    garbled = "1g 1tt 11 aw f1 1 ba h1ts n0 n1 ot s1 y x gy HD wl fk s7 tm re v od oe tz fm"
    with patch("pytesseract.image_to_string", return_value=garbled):
        result = extract_text(_make_jpeg(), "image/jpeg")
    assert result == ""


def test_extract_text_keeps_clean_ocr():
    """Results with >=40% word-like tokens are kept."""
    clean = "POLYNESIAN CULTURAL CENTER OAHU TOP TOURIST ATTRACTION"
    with patch("pytesseract.image_to_string", return_value=clean):
        result = extract_text(_make_jpeg(), "image/jpeg")
    assert result == clean


def test_extract_text_unsupported_mime_returns_empty():
    """extract_text returns '' for non-image MIME types without calling OCR."""
    result = extract_text(b"fake-video-bytes", "video/mp4")
    assert result == ""


def test_extract_text_truncates_at_5000_chars():
    """extract_text caps output at 5000 characters."""
    long_text = "A" * 6000
    with patch("pytesseract.image_to_string", return_value=long_text):
        result = extract_text(_make_png(), "image/png")
    assert len(result) == 5000


def test_extract_text_returns_empty_on_tesseract_error():
    """extract_text returns '' when pytesseract raises an exception."""
    with patch("pytesseract.image_to_string", side_effect=RuntimeError("Tesseract not available")):
        result = extract_text(_make_jpeg(), "image/jpeg")
    assert result == ""


def test_extract_text_returns_empty_on_image_decode_error():
    """extract_text returns '' when image bytes cannot be decoded."""
    result = extract_text(b"not-an-image", "image/jpeg")
    assert result == ""


def test_extract_text_png_supported():
    """extract_text handles image/png MIME type."""
    with patch("pytesseract.image_to_string", return_value="PNG text"):
        result = extract_text(_make_png(), "image/png")
    assert result == "PNG text"


def test_extract_text_tiff_supported():
    """extract_text handles image/tiff MIME type."""
    img = Image.new("RGB", (100, 30), "white")
    buf = io.BytesIO()
    img.save(buf, format="TIFF")
    tiff_bytes = buf.getvalue()

    with patch("pytesseract.image_to_string", return_value="TIFF text"):
        result = extract_text(tiff_bytes, "image/tiff")
    assert result == "TIFF text"
