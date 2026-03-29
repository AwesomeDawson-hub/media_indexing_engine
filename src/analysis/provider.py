"""Vision provider interface for AI-powered image analysis."""

from typing import Protocol

from src.analysis.schemas import MediaMetadataResult


class VisionProvider(Protocol):
    """Abstract interface for vision AI providers.

    Implementations handle: prompt construction, API call, response parsing, validation.
    Future providers (OpenAI, Gemini) implement the same interface.
    """

    async def analyze_image(
        self, image_base64: str, media_type: str
    ) -> MediaMetadataResult:
        """Analyze an image and return structured metadata.

        Args:
            image_base64: Base64-encoded image data (already resized).
            media_type: MIME type of the encoded image (e.g., "image/jpeg").

        Returns:
            Validated MediaMetadataResult with all 13 fields.
        """
        ...
