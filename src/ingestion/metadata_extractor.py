"""Extract source-truth capture metadata from file EXIF at ingest time.

P12-009 / ARCH-004: These fields are set once at ingest from the file's own
EXIF and are never overwritten by re-analysis or AI write-back.
"""

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import piexif

logger = logging.getLogger(__name__)

# EXIF DateTimeOriginal format: "YYYY:MM:DD HH:MM:SS"
_EXIF_DT_FORMAT = "%Y:%m:%d %H:%M:%S"
# OffsetTimeOriginal pattern: "+05:30" or "-08:00"
_OFFSET_RE = re.compile(r"^([+-])(\d{2}):(\d{2})$")

# MIME types we attempt EXIF extraction on
_EXIF_MIME_TYPES = frozenset(
    ["image/jpeg", "image/tiff", "image/jpg"]
)


@dataclass
class CaptureMetadata:
    """Source-truth capture metadata extracted from file EXIF."""

    capture_datetime_utc: datetime | None = None
    capture_datetime_raw: str | None = None
    capture_time_offset_minutes: int | None = None
    gps_latitude: float | None = None
    gps_longitude: float | None = None
    gps_altitude_meters: float | None = None


def _rational_to_float(rational: tuple) -> float:
    """Convert a piexif rational (numerator, denominator) to float."""
    num, den = rational
    if den == 0:
        return 0.0
    return num / den


def _dms_to_decimal(dms: tuple, ref: bytes) -> float:
    """Convert DMS rational tuple and ref byte to decimal degrees."""
    deg = _rational_to_float(dms[0])
    min_ = _rational_to_float(dms[1])
    sec = _rational_to_float(dms[2])
    decimal = deg + min_ / 60.0 + sec / 3600.0
    direction = ref.decode("ascii", errors="ignore").strip().upper()
    if direction in ("S", "W"):
        decimal = -decimal
    return decimal


def _parse_offset_minutes(offset_str: str) -> int | None:
    """Parse "+05:30" / "-08:00" to total signed offset in minutes."""
    m = _OFFSET_RE.match(offset_str.strip())
    if not m:
        return None
    sign = 1 if m.group(1) == "+" else -1
    hours = int(m.group(2))
    minutes = int(m.group(3))
    return sign * (hours * 60 + minutes)


def extract_source_capture_metadata(
    file_bytes: bytes, mime_type: str
) -> CaptureMetadata:
    """Extract capture datetime and GPS from file EXIF.

    Returns a CaptureMetadata with all fields None when the file has no
    relevant EXIF or EXIF extraction fails.  This function is non-fatal —
    it catches all exceptions internally so that upload/ingest pipelines
    are never interrupted by metadata extraction failures.
    """
    if mime_type not in _EXIF_MIME_TYPES:
        return CaptureMetadata()

    try:
        exif_data = piexif.load(file_bytes)
    except Exception as exc:
        logger.debug("piexif.load failed (mime=%s): %s", mime_type, exc)
        return CaptureMetadata()

    result = CaptureMetadata()

    # --- Capture datetime -------------------------------------------------
    try:
        exif_ifd = exif_data.get("Exif") or {}
        raw_dt_bytes = exif_ifd.get(piexif.ExifIFD.DateTimeOriginal)
        if raw_dt_bytes:
            raw_dt_str = raw_dt_bytes.decode("ascii", errors="ignore").strip()
            result.capture_datetime_raw = raw_dt_str

            # Try to parse offset so we can normalise to UTC
            raw_offset_bytes = exif_ifd.get(piexif.ExifIFD.OffsetTimeOriginal)
            if raw_offset_bytes:
                offset_str = raw_offset_bytes.decode("ascii", errors="ignore").strip()
                offset_minutes = _parse_offset_minutes(offset_str)
                if offset_minutes is not None:
                    result.capture_time_offset_minutes = offset_minutes
                    naive_dt = datetime.strptime(raw_dt_str, _EXIF_DT_FORMAT)
                    tz_offset = timezone(timedelta(minutes=offset_minutes))
                    aware_dt = naive_dt.replace(tzinfo=tz_offset)
                    result.capture_datetime_utc = aware_dt.astimezone(timezone.utc)
                else:
                    # Malformed offset string — treat raw datetime as UTC
                    naive_dt = datetime.strptime(raw_dt_str, _EXIF_DT_FORMAT)
                    result.capture_datetime_utc = naive_dt.replace(tzinfo=timezone.utc)
            else:
                # No UTC offset available — store raw datetime as if UTC per EXIF convention
                naive_dt = datetime.strptime(raw_dt_str, _EXIF_DT_FORMAT)
                result.capture_datetime_utc = naive_dt.replace(tzinfo=timezone.utc)
    except Exception as exc:
        logger.debug("Capture datetime extraction failed: %s", exc)

    # --- GPS coordinates --------------------------------------------------
    try:
        gps_ifd = exif_data.get("GPS") or {}
        lat_dms = gps_ifd.get(piexif.GPSIFD.GPSLatitude)
        lat_ref = gps_ifd.get(piexif.GPSIFD.GPSLatitudeRef)
        lon_dms = gps_ifd.get(piexif.GPSIFD.GPSLongitude)
        lon_ref = gps_ifd.get(piexif.GPSIFD.GPSLongitudeRef)

        if lat_dms and lat_ref and lon_dms and lon_ref:
            result.gps_latitude = _dms_to_decimal(lat_dms, lat_ref)
            result.gps_longitude = _dms_to_decimal(lon_dms, lon_ref)

        alt_rational = gps_ifd.get(piexif.GPSIFD.GPSAltitude)
        alt_ref = gps_ifd.get(piexif.GPSIFD.GPSAltitudeRef)
        if alt_rational is not None:
            alt_meters = _rational_to_float(alt_rational)
            # GPSAltitudeRef: 0 = above sea level, 1 = below sea level
            if alt_ref == 1:
                alt_meters = -alt_meters
            result.gps_altitude_meters = alt_meters
    except Exception as exc:
        logger.debug("GPS extraction failed: %s", exc)

    return result
