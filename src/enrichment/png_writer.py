"""XMP embedding for PNG via Pillow iTXt chunk.

P12-009 / ARCH-004: XMP writes are non-destructive.  When an existing
XMP packet is present, the AI-produced fields are merged into it rather
than replacing the entire block.  If the merge cannot be completed safely
the function fails closed — preserving the original XMP unchanged.
"""

import io
import logging
import xml.etree.ElementTree as ET

from PIL import Image
from PIL.PngImagePlugin import PngInfo

from src.analysis.schemas import MediaMetadataResult
from src.enrichment.xmp_builder import build_xmp_xml

logger = logging.getLogger(__name__)

# Namespaces used in AI-generated XMP that we merge into existing packets
_NS = {
    "x": "adobe:ns:meta/",
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "dc": "http://purl.org/dc/elements/1.1/",
    "photoshop": "http://ns.adobe.com/photoshop/1.0/",
}
# Tags we write from AI — these are the only ones we replace / add in the merge
_AI_TAGS = {
    "{http://purl.org/dc/elements/1.1/}title",
    "{http://purl.org/dc/elements/1.1/}description",
    "{http://purl.org/dc/elements/1.1/}subject",
    "{http://ns.adobe.com/photoshop/1.0/}Headline",
}


def _try_merge_xmp(existing_xmp: str, metadata: MediaMetadataResult) -> str | None:
    """Merge AI metadata into existing XMP.

    Removes any existing AI-managed elements from the first rdf:Description,
    then appends the new AI elements extracted from build_xmp_xml(metadata).

    Returns the merged XMP string on success, or None if anything goes wrong
    (fail-closed — caller must preserve original XMP when None is returned).
    """
    try:
        # Register namespaces to get clean serialization
        for prefix, uri in _NS.items():
            ET.register_namespace(prefix, uri)

        # Parse the existing XMP packet, stripping the xpacket processing instructions
        # which ElementTree cannot handle
        inner = existing_xmp
        xpacket_begin = ""
        xpacket_end = ""
        if "<?xpacket" in inner:
            lines = inner.split("\n")
            body_lines = []
            for line in lines:
                if line.strip().startswith("<?xpacket"):
                    if 'begin=' in line:
                        xpacket_begin = line
                    elif 'end=' in line:
                        xpacket_end = line
                else:
                    body_lines.append(line)
            inner = "\n".join(body_lines)

        existing_root = ET.fromstring(inner.strip())

        # Find the first rdf:Description to merge into
        rdf_ns = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
        desc = existing_root.find(f".//{{{rdf_ns}}}RDF/{{{rdf_ns}}}Description")
        if desc is None:
            desc = existing_root.find(f".//{{{rdf_ns}}}Description")
        if desc is None:
            return None

        # Remove existing AI-controlled tags so we replace rather than duplicate
        for child in list(desc):
            if child.tag in _AI_TAGS:
                desc.remove(child)

        # Parse the new AI XMP to get the elements to add
        ai_xmp = build_xmp_xml(metadata)
        ai_lines = ai_xmp.split("\n")
        ai_body_lines = [
            ln for ln in ai_lines if not ln.strip().startswith("<?xpacket")
        ]
        ai_root = ET.fromstring("\n".join(ai_body_lines).strip())
        ai_desc = ai_root.find(f".//{{{rdf_ns}}}RDF/{{{rdf_ns}}}Description")
        if ai_desc is None:
            ai_desc = ai_root.find(f".//{{{rdf_ns}}}Description")

        if ai_desc is not None:
            for child in ai_desc:
                if child.tag in _AI_TAGS:
                    desc.append(child)

        merged_body = ET.tostring(existing_root, encoding="unicode", xml_declaration=False)

        if xpacket_begin and xpacket_end:
            return f"{xpacket_begin}\n{merged_body}\n{xpacket_end}"
        return merged_body

    except Exception as exc:
        logger.debug("XMP merge failed, preserving original: %s", exc)
        return None


def embed_png(file_bytes: bytes, metadata: MediaMetadataResult) -> bytes:
    """Embed XMP metadata into a PNG file via iTXt chunk.

    Non-destructive: if an existing XMP packet is present it is merged
    rather than replaced.  If the merge fails the original XMP is preserved
    unchanged and a debug log is emitted.
    """
    img = Image.open(io.BytesIO(file_bytes))

    png_info = PngInfo()

    # Determine the XMP to write
    existing_xmp: str | None = None
    if hasattr(img, "text") and img.text:
        existing_xmp = img.text.get("XML:com.adobe.xmp")

    if existing_xmp:
        merged = _try_merge_xmp(existing_xmp, metadata)
        if merged is not None:
            xmp_to_write = merged
        else:
            # Fail closed: preserve original, skip AI XMP
            logger.debug("embed_png: merge failed closed; preserving original XMP for %s", getattr(metadata, 'title', '?'))
            xmp_to_write = existing_xmp
    else:
        # No existing XMP — write AI XMP directly
        xmp_to_write = build_xmp_xml(metadata)

    # Copy non-XMP text chunks
    if hasattr(img, "text") and img.text:
        for key, value in img.text.items():
            if key != "XML:com.adobe.xmp":
                png_info.add_text(key, value)

    png_info.add_itxt("XML:com.adobe.xmp", xmp_to_write)

    buf = io.BytesIO()
    img.save(buf, format="PNG", pnginfo=png_info)
    return buf.getvalue()

