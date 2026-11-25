from abc import ABC, abstractmethod


class ImageGenerationError(RuntimeError):
    """The image could not be made (provider down, timeout, bad answer)."""


class ImageGenerationRefused(ImageGenerationError):
    """The provider declined this request (its own content rules).

    Callers must NOT show the provider's wording to the user: the character
    answers in her own voice instead.
    """


class ImageProvider(ABC):
    @abstractmethod
    async def generate_image(self, prompt: str) -> bytes:
        """Return the image as PNG/JPEG bytes."""
