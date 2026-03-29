"""Tests for the metadata enrichment module (P2-001)."""

import io
import xml.etree.ElementTree as ET

import piexif
import pytest
from PIL import Image

from src.analysis.schemas import MediaMetadataResult
from src.enrichment.embedder import MetadataEmbedder

METADATA = MediaMetadataResult(
    title="Sunset Beach",
    description="A vibrant sunset over a sandy beach with palm trees.",
    tags=["sunset", "beach", "tropical"],
    objects=["sun", "ocean", "palm trees"],
    scenes=["coastal sunset"],
    context="Nature photography of a Pacific coast sunset",
    mood="serene",
    people=[],
    people_count=0,
    orientation="landscape",
    colors=["orange", "purple", "blue"],
    location_hint="Pacific coast",
    quality_notes=None,
)

UNICODE_METADATA = MediaMetadataResult(
    title="Caf\u00e9 \u00e0 Paris",
    description="Un caf\u00e9 sur les Champs-\u00c9lys\u00e9es avec des cr\u00e8pes.",
    tags=["caf\u00e9", "paris", "fran\u00e7ais"],
    objects=["table", "coffee"],
    scenes=["street caf\u00e9"],
    context="European street photography",
    mood="romantic",
    people=["woman sitting at table"],
    people_count=1,
    orientation="landscape",
    colors=["brown", "cream"],
    location_hint="Paris, France",
    quality_notes=None,
)


def _make_jpeg(width=200, height=150) -> bytes:
    img = Image.new("RGB", (width, height), "red")
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def _make_png(width=200, height=150) -> bytes:
    img = Image.new("RGB", (width, height), "blue")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_webp(width=200, height=150) -> bytes:
    img = Image.new("RGB", (width, height), "green")
    buf = io.BytesIO()
    img.save(buf, format="WEBP")
    return buf.getvalue()


def _make_bmp(width=200, height=150) -> bytes:
    img = Image.new("RGB", (width, height), "yellow")
    buf = io.BytesIO()
    img.save(buf, format="BMP")
    return buf.getvalue()


def _make_gif(width=200, height=150) -> bytes:
    img = Image.new("RGB", (width, height), "cyan")
    buf = io.BytesIO()
    img.save(buf, format="GIF")
    return buf.getvalue()


@pytest.fixture
def embedder():
    return MetadataEmbedder()


class TestJPEG:
    def test_exif_embedded(self, embedder):
        result = embedder.embed(_make_jpeg(), "image/jpeg", METADATA, "test.jpg")
        assert result.embedded is True
        exif = piexif.load(result.enriched_bytes)
        desc = exif["0th"].get(piexif.ImageIFD.ImageDescription, b"")
        assert b"Sunset Beach" in desc

    def test_exif_user_comment(self, embedder):
        result = embedder.embed(_make_jpeg(), "image/jpeg", METADATA, "test.jpg")
        exif = piexif.load(result.enriched_bytes)
        raw_comment = exif["Exif"].get(piexif.ExifIFD.UserComment, b"")
        # Strip 8-byte charset prefix (ASCII\x00\x00\x00)
        comment_text = raw_comment[8:].decode("ascii", errors="replace")
        assert "Mood" in comment_text

    def test_round_trip(self, embedder):
        result = embedder.embed(_make_jpeg(), "image/jpeg", METADATA, "test.jpg")
        img = Image.open(io.BytesIO(result.enriched_bytes))
        assert img.size == (200, 150)

    def test_unicode(self, embedder):
        result = embedder.embed(_make_jpeg(), "image/jpeg", UNICODE_METADATA, "cafe.jpg")
        assert result.embedded is True
        img = Image.open(io.BytesIO(result.enriched_bytes))
        assert img.size == (200, 150)


class TestPNG:
    def test_xmp_embedded(self, embedder):
        result = embedder.embed(_make_png(), "image/png", METADATA, "test.png")
        assert result.embedded is True
        img = Image.open(io.BytesIO(result.enriched_bytes))
        xmp_data = img.text.get("XML:com.adobe.xmp", "")
        assert "Sunset Beach" in xmp_data
        assert "dc:title" in xmp_data

    def test_xmp_keywords(self, embedder):
        result = embedder.embed(_make_png(), "image/png", METADATA, "test.png")
        img = Image.open(io.BytesIO(result.enriched_bytes))
        xmp_data = img.text.get("XML:com.adobe.xmp", "")
        assert "sunset" in xmp_data
        assert "dc:subject" in xmp_data

    def test_xmp_parseable(self, embedder):
        result = embedder.embed(_make_png(), "image/png", METADATA, "test.png")
        img = Image.open(io.BytesIO(result.enriched_bytes))
        xmp_data = img.text.get("XML:com.adobe.xmp", "")
        # Strip xpacket processing instructions for XML parsing
        xml_start = xmp_data.find("<x:xmpmeta")
        xml_end = xmp_data.find("</x:xmpmeta>") + len("</x:xmpmeta>")
        xml_body = xmp_data[xml_start:xml_end]
        ET.fromstring(xml_body)  # Should not raise

    def test_round_trip(self, embedder):
        result = embedder.embed(_make_png(), "image/png", METADATA, "test.png")
        img = Image.open(io.BytesIO(result.enriched_bytes))
        assert img.size == (200, 150)

    def test_unicode(self, embedder):
        result = embedder.embed(_make_png(), "image/png", UNICODE_METADATA, "cafe.png")
        assert result.embedded is True
        img = Image.open(io.BytesIO(result.enriched_bytes))
        xmp_data = img.text.get("XML:com.adobe.xmp", "")
        assert "Caf\u00e9" in xmp_data


class TestWebP:
    def test_exif_embedded(self, embedder):
        result = embedder.embed(_make_webp(), "image/webp", METADATA, "test.webp")
        assert result.embedded is True
        # Read back EXIF from WebP
        img = Image.open(io.BytesIO(result.enriched_bytes))
        exif_data = img.info.get("exif", b"")
        assert len(exif_data) > 0
        exif = piexif.load(exif_data)
        desc = exif["0th"].get(piexif.ImageIFD.ImageDescription, b"")
        assert b"Sunset Beach" in desc

    def test_round_trip(self, embedder):
        result = embedder.embed(_make_webp(), "image/webp", METADATA, "test.webp")
        img = Image.open(io.BytesIO(result.enriched_bytes))
        assert img.size == (200, 150)


class TestBMPGIF:
    def test_bmp_passthrough(self, embedder):
        original = _make_bmp()
        result = embedder.embed(original, "image/bmp", METADATA, "test.bmp")
        assert result.embedded is False
        assert result.enriched_bytes == original

    def test_gif_passthrough(self, embedder):
        original = _make_gif()
        result = embedder.embed(original, "image/gif", METADATA, "test.gif")
        assert result.embedded is False
        assert result.enriched_bytes == original


class TestConvertToPNG:
    def test_bmp_to_png(self, embedder):
        result = embedder.convert_to_png_with_metadata(_make_bmp(), METADATA, "photo.bmp")
        assert result.embedded is True
        assert result.output_mime_type == "image/png"
        assert result.output_filename == "photo.png"
        img = Image.open(io.BytesIO(result.enriched_bytes))
        assert img.format == "PNG"
        xmp = img.text.get("XML:com.adobe.xmp", "")
        assert "Sunset Beach" in xmp

    def test_gif_to_png(self, embedder):
        result = embedder.convert_to_png_with_metadata(_make_gif(), METADATA, "logo.gif")
        assert result.embedded is True
        assert result.output_filename == "logo.png"
        img = Image.open(io.BytesIO(result.enriched_bytes))
        assert img.format == "PNG"


class TestPreserveExistingEXIF:
    def test_jpeg_preserves_camera_data(self, embedder):
        """Existing EXIF (camera model) should not be overwritten."""
        # Create JPEG with existing EXIF
        img = Image.new("RGB", (200, 150), "red")
        existing_exif = {
            "0th": {piexif.ImageIFD.Make: b"Canon", piexif.ImageIFD.Model: b"EOS R5"},
            "Exif": {},
        }
        exif_bytes = piexif.dump(existing_exif)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", exif=exif_bytes)
        jpeg_with_camera = buf.getvalue()

        # Embed AI metadata
        result = embedder.embed(jpeg_with_camera, "image/jpeg", METADATA, "camera.jpg")
        assert result.embedded is True

        # Verify camera data preserved
        enriched_exif = piexif.load(result.enriched_bytes)
        assert enriched_exif["0th"].get(piexif.ImageIFD.Make) == b"Canon"
        assert enriched_exif["0th"].get(piexif.ImageIFD.Model) == b"EOS R5"
        # AND AI data present
        assert b"Sunset Beach" in enriched_exif["0th"].get(piexif.ImageIFD.ImageDescription, b"")
