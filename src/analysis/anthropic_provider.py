"""Anthropic Claude vision provider implementation (ADR-008)."""

import logging
import os

from anthropic import AsyncAnthropic, APIError, APITimeoutError, AuthenticationError

from src.analysis.schemas import MediaMetadataResult, parse_ai_response
from src.config import settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an image analysis assistant. Analyze the provided image and return a JSON object with exactly these fields:

{
  "title": "Short descriptive title (under 100 characters)",
  "description": "2-3 sentence natural language description of what the image shows",
  "tags": ["tag1", "tag2", ...],
  "objects": ["object1", "object2", ...],
  "scenes": ["scene1", "scene2", ...],
  "context": "Situational context — what is happening, what event or activity",
  "mood": "Emotional tone or atmosphere (e.g., cheerful, dramatic, serene)",
  "people": ["description1", ...],
  "people_count": 0,
  "orientation": "landscape|portrait|square",
  "colors": ["color1", "color2", ...],
  "location_hint": "Inferred location or null if not determinable",
  "quality_notes": "Notes on quality issues (blur, noise, exposure) or null if good"
}

Rules:
- Return ONLY the JSON object, no markdown fences, no explanation.
- Tags should be lowercase, single words or short phrases.
- people array contains descriptions only, never names or identifying information.
- orientation is based on image dimensions, not content.
- location_hint should be null if location cannot be reasonably inferred.
- quality_notes should be null if the image quality is acceptable."""


class AnalysisError(Exception):
    """Raised when AI analysis fails with a clear error message."""
    pass


class AnthropicVisionProvider:
    """Vision provider using Anthropic Claude via the official SDK."""

    def __init__(
        self,
        model: str | None = None,
        timeout: float | None = None,
    ) -> None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise AnalysisError(
                "ANTHROPIC_API_KEY environment variable is not set. "
                "Set it before running analysis."
            )

        self._client = AsyncAnthropic(api_key=api_key)
        self._model = model or settings.analysis.model
        self._timeout = timeout or settings.analysis.timeout_seconds

    async def analyze_image(
        self, image_base64: str, media_type: str
    ) -> MediaMetadataResult:
        """Send image to Claude and return validated structured metadata."""
        try:
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=1024,
                system=SYSTEM_PROMPT,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": media_type,
                                    "data": image_base64,
                                },
                            },
                            {
                                "type": "text",
                                "text": "Analyze this image and return the JSON metadata.",
                            },
                        ],
                    }
                ],
                timeout=self._timeout,
            )
        except AuthenticationError:
            raise AnalysisError("Anthropic API authentication failed. Check your ANTHROPIC_API_KEY.")
        except APITimeoutError:
            raise AnalysisError(f"Anthropic API request timed out after {self._timeout}s.")
        except APIError as e:
            raise AnalysisError(f"Anthropic API error: {e.message}")

        # Extract text content from response
        raw_text = response.content[0].text
        logger.debug("Claude raw response: %s", raw_text[:500])

        try:
            return parse_ai_response(raw_text)
        except Exception as e:
            raise AnalysisError(f"Failed to parse AI response: {e}")
