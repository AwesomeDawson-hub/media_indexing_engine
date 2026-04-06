"""Mock vision provider for testing. Returns canned metadata without API calls."""

from src.analysis.schemas import MediaMetadataResult


CANNED_METADATA = MediaMetadataResult(
    title="Test Image",
    description="A test image used for automated testing.",
    tags=["test", "automated", "sample"],
    objects=["placeholder"],
    scenes=["test environment"],
    context="Automated testing of the analysis pipeline",
    mood="neutral",
    people=[],
    people_count=0,
    orientation="landscape",
    colors=["gray", "white"],
    location_hint=None,
    quality_notes=None,
)


class MockVisionProvider:
    """Mock provider that returns deterministic canned metadata."""

    def __init__(self, fail_until_attempt: int = 0):
        """Args:
            fail_until_attempt: If > 0, raises on the first N calls (for retry testing).
        """
        self._fail_until_attempt = fail_until_attempt
        self._call_count = 0

    async def analyze_image(
        self, image_base64: str, media_type: str, hint: str | None = None
    ) -> MediaMetadataResult:
        self._call_count += 1
        if self._call_count <= self._fail_until_attempt:
            raise RuntimeError(f"Simulated failure (call {self._call_count})")
        return CANNED_METADATA
