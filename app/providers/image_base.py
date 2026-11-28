from abc import ABC, abstractmethod


class ImageGenerationError(RuntimeError):
    """The image could not be made (provider down, timeout, bad answer)."""


class ImageGenerationRefused(ImageGenerationError):
    """The provider declined this request (its own content rules).

    Callers must NOT show the provider's wording to the user: the character
    answers in her own voice instead.
    """


def image_extension(data: bytes) -> str | None:
    """png/jpg/webp from the file's first bytes (never trust a provider)."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


class ImageProvider(ABC):
    name = "unknown"  # recorded in the cost ledger
    model: str | None = None

    @abstractmethod
    async def generate_image(self, prompt: str, character_ref: str | None = None) -> bytes:
        """Return the image as PNG/JPEG/WEBP bytes.

        character_ref is the provider's own id for the person to draw (the
        face and body live at the provider); the prompt only describes the
        scene.
        """
