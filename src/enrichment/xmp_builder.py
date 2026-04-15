"""Build standards-compliant XMP XML from metadata fields for PNG embedding."""

from xml.sax.saxutils import escape

from src.analysis.schemas import MediaMetadataResult


def _escape(text: str) -> str:
    """XML-escape text content."""
    return escape(text)


def build_xmp_xml(metadata: MediaMetadataResult) -> str:
    """Construct XMP XML with Dublin Core, IPTC Core, and Photoshop namespaces."""
    # Combine tags + objects as keywords (dc:subject)
    keywords = list(metadata.tags)
    for obj in metadata.objects:
        if obj.lower() not in [k.lower() for k in keywords]:
            keywords.append(obj)

    keyword_items = "\n".join(
        f"          <rdf:li>{_escape(kw)}</rdf:li>" for kw in keywords
    )

    xmp = f"""<?xpacket begin="\xef\xbb\xbf" id="W5M0MpCehiHzreSzNTczkc9d"?>
<x:xmpmeta xmlns:x="adobe:ns:meta/">
  <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
    <rdf:Description
      xmlns:dc="http://purl.org/dc/elements/1.1/"
      xmlns:photoshop="http://ns.adobe.com/photoshop/1.0/">
      <dc:title>
        <rdf:Alt>
          <rdf:li xml:lang="x-default">{_escape(metadata.title)}</rdf:li>
        </rdf:Alt>
      </dc:title>
      <dc:description>
        <rdf:Alt>
          <rdf:li xml:lang="x-default">{_escape(metadata.description)}</rdf:li>
        </rdf:Alt>
      </dc:description>
      <dc:subject>
        <rdf:Bag>
{keyword_items}
        </rdf:Bag>
      </dc:subject>
      <photoshop:Headline>{_escape(metadata.title)}</photoshop:Headline>
    </rdf:Description>
  </rdf:RDF>
</x:xmpmeta>
<?xpacket end="w"?>"""

    return xmp
