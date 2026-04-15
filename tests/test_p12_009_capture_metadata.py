"""P12-009 — Source Capture Metadata Preservation Hardening tests.

9 focused tests covering:
  1. Ingest extracts DateTimeOriginal -> source_capture_datetime_utc
  2. Ingest preserves source_capture_datetime_raw
  3. Ingest extracts GPS lat/lon as decimal degrees
  4. Re-analysis (_upsert_metadata) does NOT overwrite source capture fields
  5. JPEG enrichment preserves pre-existing DateTimeOriginal and GPS EXIF
  6. AI location_hint is NOT written to IPTC city
  7. AI location_hint is NOT written to XMP Iptc4xmpCore:Location
  8. PNG enrichment preserves existing XMP and merges AI fields without loss
  9. PNG enrichment fails closed when existing XMP is corrupt
"""

import io
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import piexif
import pytest
from PIL import Image
from PIL.PngImagePlugin import PngInfo

from src.analysis.schemas import MediaMetadataResult
from src.enrichment.embedder import MetadataEmbedder
from src.enrichment.field_mapping import build_iptc_data
from src.enrichment.xmp_builder import build_xmp_xml
from src.ingestion.metadata_extractor import extract_source_capture_metadata


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_jpeg_no_exif() -> bytes:
    img = Image.new("RGB", (100, 80), "red")
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def _inject_exif(jpeg_bytes: bytes, exif_dict: dict) -> bytes:
    """Inject a piexif EXIF dict into JPEG bytes via Pillow save."""
    img = Image.open(io.BytesIO(jpeg_bytes))
    exif_bytes = piexif.dump(exif_dict)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif_bytes)
    return buf.getvalue()


def _make_jpeg_with_datetime(dt_str: str = "2023:07:14 10:30:00", offset: str | None = None) -> bytes:
    """JPEG with DateTimeOriginal (and optional OffsetTimeOriginal) in EXIF."""
    exif_dict: dict = {
        "0th": {},
        "Exif": {
            piexif.ExifIFD.DateTimeOriginal: dt_str.encode("ascii"),
        },
        "GPS": {},
        "1st": {},
        "thumbnail": None,
    }
    if offset is not None:
        exif_dict["Exif"][piexif.ExifIFD.OffsetTimeOriginal] = offset.encode("ascii")
    return _inject_exif(_make_jpeg_no_exif(), exif_dict)


def _make_jpeg_with_gps(
    lat_deg: float = 48.8566,
    lon_deg: float = 2.3522,
    alt_m: float = 35.0,
) -> bytes:
    """JPEG with GPS coordinates in EXIF."""

    def _to_dms_rational(decimal: float):
        abs_val = abs(decimal)
        d = int(abs_val)
        m = int((abs_val - d) * 60)
        s = (abs_val - d - m / 60) * 3600
        return ((d, 1), (m, 1), (int(s * 100), 100))

    lat_ref = b"N" if lat_deg >= 0 else b"S"
    lon_ref = b"E" if lon_deg >= 0 else b"W"

    exif_dict = {
        "0th": {},
        "Exif": {},
        "GPS": {
            piexif.GPSIFD.GPSLatitudeRef: lat_ref,
            piexif.GPSIFD.GPSLatitude: _to_dms_rational(lat_deg),
            piexif.GPSIFD.GPSLongitudeRef: lon_ref,
            piexif.GPSIFD.GPSLongitude: _to_dms_rational(lon_deg),
            piexif.GPSIFD.GPSAltitudeRef: 0,
            piexif.GPSIFD.GPSAltitude: (int(alt_m * 10), 10),
        },
        "1st": {},
        "thumbnail": None,
    }
    return _inject_exif(_make_jpeg_no_exif(), exif_dict)


def _make_png_with_xmp(xmp_xml: str) -> bytes:
    img = Image.new("RGB", (100, 80), "blue")
    info = PngInfo()
    info.add_itxt("XML:com.adobe.xmp", xmp_xml)
    info.add_text("exif:ExifVersion", "0230")  # an unrelated chunk we must preserve
    buf = io.BytesIO()
    img.save(buf, format="PNG", pnginfo=info)
    return buf.getvalue()


_SAMPLE_XMP = """\
<?xpacket begin="\xef\xbb\xbf" id="W5M0MpCehiHzreSzNTczkc9d"?>
<x:xmpmeta xmlns:x="adobe:ns:meta/">
  <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
    <rdf:Description
      xmlns:dc="http://purl.org/dc/elements/1.1/"
      xmlns:custom="http://example.com/custom/">
      <dc:title>
        <rdf:Alt>
          <rdf:li xml:lang="x-default">Camera Original Title</rdf:li>
        </rdf:Alt>
      </dc:title>
      <custom:CameraModel>SomeCamera X10</custom:CameraModel>
    </rdf:Description>
  </rdf:RDF>
</x:xmpmeta>
<?xpacket end="w"?>"""

_AI_METADATA = MediaMetadataResult(
    title="AI Title",
    description="AI Description",
    tags=["tag1", "tag2"],
    objects=["cat"],
    scenes=["indoor"],
    context="AI context",
    mood="calm",
    people=[],
    people_count=0,
    orientation="landscape",
    colors=["blue"],
    location_hint="San Francisco",
    quality_notes=None,
)


# ---------------------------------------------------------------------------
# Tests 1–3: metadata_extractor unit tests
# ---------------------------------------------------------------------------

class TestIngestCaptureDatetime:
    def test_extracts_datetime_utc(self):
        """Test 1: DateTimeOriginal is correctly parsed into source_capture_datetime_utc."""
        jpeg = _make_jpeg_with_datetime("2023:07:14 10:30:00", offset="+02:00")
        result = extract_source_capture_metadata(jpeg, "image/jpeg")
        assert result.capture_datetime_utc is not None
        # With +02:00 offset, UTC should be 08:30:00
        assert result.capture_datetime_utc.hour == 8
        assert result.capture_datetime_utc.minute == 30
        assert result.capture_datetime_utc.tzinfo == timezone.utc

    def test_preserves_raw_datetime(self):
        """Test 2: The original EXIF datetime string is stored verbatim in capture_datetime_raw."""
        raw_dt = "2023:07:14 10:30:00"
        jpeg = _make_jpeg_with_datetime(raw_dt)
        result = extract_source_capture_metadata(jpeg, "image/jpeg")
        assert result.capture_datetime_raw == raw_dt

    def test_extracts_gps_decimal_degrees(self):
        """Test 3: GPS DMS coordinates are converted to decimal degrees."""
        jpeg = _make_jpeg_with_gps(lat_deg=48.8566, lon_deg=2.3522)
        result = extract_source_capture_metadata(jpeg, "image/jpeg")
        assert result.gps_latitude is not None
        assert result.gps_longitude is not None
        # Paris approximate coords — allow for DMS rounding error
        assert abs(result.gps_latitude - 48.8566) < 0.01
        assert abs(result.gps_longitude - 2.3522) < 0.01

    def test_non_image_mime_returns_empty(self):
        """Non-EXIF MIME types return all-None CaptureMetadata."""
        result = extract_source_capture_metadata(b"data", "image/png")
        assert result.capture_datetime_utc is None
        assert result.gps_latitude is None

    def test_corrupt_bytes_returns_empty(self):
        """Corrupted bytes are handled gracefully and return all-None."""
        result = extract_source_capture_metadata(b"\xff\xd8corrupt", "image/jpeg")
        assert result.capture_datetime_utc is None

    def test_no_offset_treats_as_utc(self):
        """When no OffsetTimeOriginal is present, datetime is treated as UTC."""
        jpeg = _make_jpeg_with_datetime("2023:07:14 10:30:00", offset=None)
        result = extract_source_capture_metadata(jpeg, "image/jpeg")
        assert result.capture_datetime_utc is not None
        assert result.capture_time_offset_minutes is None
        assert result.capture_datetime_utc.hour == 10
        assert result.capture_datetime_utc.tzinfo == timezone.utc


# ---------------------------------------------------------------------------
# Test 4: Re-analysis does not overwrite source capture fields
# ---------------------------------------------------------------------------

class TestReanalysisSourceFieldImmutability:
    @pytest.mark.asyncio
    async def test_reanalysis_does_not_overwrite_capture_fields(self):
        """Test 4: _upsert_metadata only writes to MediaMetadata; MediaItem source fields unchanged."""
        from src.analysis.processor import _upsert_metadata
        from src.models import MediaItem, MediaMetadata
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
        from sqlalchemy.pool import StaticPool
        from src.database import Base
        from sqlalchemy import select

        engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        capture_dt = datetime(2023, 7, 14, 8, 30, 0, tzinfo=timezone.utc)

        from src.models import User
        async with session_factory() as db:
            user = User(id="u-001", email="test@test.com", display_name="Tester")
            db.add(user)
            await db.flush()

            item = MediaItem(
                user_id="u-001",
                content_hash="a" * 64,
                original_filename="test.jpg",
                file_size=1000,
                mime_type="image/jpeg",
                storage_path="u-001/aa/test.jpg",
                storage_mode="full",
                status="analyzed",
                source_capture_datetime_utc=capture_dt,
                source_capture_datetime_raw="2023:07:14 10:30:00",
                source_capture_time_offset_minutes=120,
                source_gps_latitude=48.8566,
                source_gps_longitude=2.3522,
                source_gps_altitude_meters=35.0,
            )
            db.add(item)
            await db.flush()
            item_id = item.id
            await db.commit()

        async with session_factory() as db:
            await _upsert_metadata(
                db,
                item_id,
                _AI_METADATA,
                provider="test-provider",
                model="test-model",
            )
            await db.commit()

        async with session_factory() as db:
            row = await db.execute(select(MediaItem).where(MediaItem.id == item_id))
            refreshed = row.scalar_one()

            # SQLite drops timezone info — compare as naive UTC
            stored_dt = refreshed.source_capture_datetime_utc
            assert stored_dt is not None
            stored_naive = stored_dt.replace(tzinfo=None) if stored_dt.tzinfo else stored_dt
            capture_naive = capture_dt.replace(tzinfo=None)
            assert stored_naive == capture_naive
            assert refreshed.source_capture_datetime_raw == "2023:07:14 10:30:00"
            assert refreshed.source_capture_time_offset_minutes == 120
            assert abs(refreshed.source_gps_latitude - 48.8566) < 0.0001
            assert abs(refreshed.source_gps_longitude - 2.3522) < 0.0001
            assert abs(refreshed.source_gps_altitude_meters - 35.0) < 0.0001

        await engine.dispose()


# ---------------------------------------------------------------------------
# Test 5: JPEG enrichment preserves pre-existing DateTimeOriginal and GPS
# ---------------------------------------------------------------------------

class TestJPEGEnrichmentPreservesExif:
    def test_enrich_preserves_datetime_original_and_gps(self):
        """Test 5: _merge_exif preserves DateTimeOriginal and GPS after AI merge."""
        from src.enrichment.exif_writer import _merge_exif
        from src.enrichment.field_mapping import build_exif_dict

        jpeg_base = _make_jpeg_with_datetime("2023:07:14 10:30:00")
        exif_existing = piexif.load(jpeg_base)
        exif_existing["GPS"] = {
            piexif.GPSIFD.GPSLatitudeRef: b"N",
            piexif.GPSIFD.GPSLatitude: ((48, 1), (51, 1), (2376, 100)),
            piexif.GPSIFD.GPSLongitudeRef: b"E",
            piexif.GPSIFD.GPSLongitude: ((2, 1), (21, 1), (792, 100)),
        }
        jpeg_bytes = _inject_exif(_make_jpeg_no_exif(), exif_existing)

        ai_exif_dict = build_exif_dict(_AI_METADATA)
        merged_exif_bytes = _merge_exif(jpeg_bytes, ai_exif_dict)
        exif_out = piexif.load(merged_exif_bytes)

        # DateTimeOriginal must survive the merge
        dt_raw = exif_out["Exif"].get(piexif.ExifIFD.DateTimeOriginal)
        assert dt_raw == b"2023:07:14 10:30:00", (
            "ARCH-004: DateTimeOriginal must not be overwritten by AI EXIF embed"
        )

        # GPS IFD must survive the merge
        assert piexif.GPSIFD.GPSLatitudeRef in exif_out["GPS"], (
            "ARCH-004: GPS data must not be overwritten by AI EXIF embed"
        )
        assert piexif.GPSIFD.GPSLatitude in exif_out["GPS"]


# ---------------------------------------------------------------------------
# Tests 6–7: location_hint isolation
# ---------------------------------------------------------------------------

class TestLocationHintIsolation:
    def test_location_hint_not_in_iptc_city(self):
        """Test 6: AI location_hint must NOT appear in the IPTC 'city' field."""
        data = build_iptc_data(_AI_METADATA)
        assert "city" not in data, (
            "ARCH-004 D4 violation: location_hint must not be written to IPTC city"
        )

    def test_location_hint_not_in_xmp_location(self):
        """Test 7: AI location_hint must NOT appear in XMP Iptc4xmpCore:Location."""
        xmp = build_xmp_xml(_AI_METADATA)
        assert "Iptc4xmpCore:Location" not in xmp, (
            "ARCH-004 D4 violation: location_hint must not be written to XMP Iptc4xmpCore:Location"
        )
        # Also check the namespace declaration is gone
        assert "Iptc4xmpCore" not in xmp


# ---------------------------------------------------------------------------
# Tests 8–9: PNG non-destructive XMP merge
# ---------------------------------------------------------------------------

class TestPNGXMPMerge:
    def test_existing_xmp_preserved_and_ai_merged(self):
        """Test 8: Embed into PNG with existing XMP preserves custom fields and adds AI fields."""
        png_bytes = _make_png_with_xmp(_SAMPLE_XMP)

        embedder = MetadataEmbedder()
        result = embedder.embed(png_bytes, "image/png", _AI_METADATA, "test.png")
        assert result.embedded is True

        enriched_img = Image.open(io.BytesIO(result.enriched_bytes))
        xmp_out = enriched_img.text.get("XML:com.adobe.xmp", "")
        assert xmp_out, "XMP chunk must be present after embed"

        # Custom camera field from original XMP must survive
        assert "SomeCamera X10" in xmp_out, (
            "Existing custom XMP field was discarded — non-destructive merge violated"
        )

        # AI title must be present
        assert "AI Title" in xmp_out, "AI title must appear in merged XMP"

        # Non-XMP text chunk must also survive
        assert enriched_img.text.get("exif:ExifVersion") == "0230"

    def test_corrupt_xmp_fails_closed(self):
        """Test 9: When existing XMP is unparseable, original XMP is preserved unchanged."""
        corrupt_xmp = "THIS IS NOT VALID XML <<<<"
        png_bytes = _make_png_with_xmp(corrupt_xmp)

        embedder = MetadataEmbedder()
        result = embedder.embed(png_bytes, "image/png", _AI_METADATA, "test.png")
        assert result.embedded is True  # embed should not raise

        enriched_img = Image.open(io.BytesIO(result.enriched_bytes))
        xmp_out = enriched_img.text.get("XML:com.adobe.xmp", "")

        # Must preserve the original corrupt XMP (fail closed — no AI injection)
        assert xmp_out == corrupt_xmp, (
            "Fail-closed violated: corrupt XMP should be preserved unchanged"
        )
