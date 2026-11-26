"""Fakes shared by the picture tests."""

from app.providers.image_base import ImageGenerationError, ImageGenerationRefused, ImageProvider
from app.services.character_definition_loader import CharacterDefinition, CharacterProfile
from app.services.image_scene import SCENE_MARKER
from tests.test_conversation_engine import ScriptedProvider

PNG_HEAD = b"\x89PNG\r\n\x1a\n"


def definition(slug="test-char", name="Testa", age=25, image_id="xav-test-1234"):
    return CharacterDefinition(
        name=name,
        slug=slug,
        description="",
        personality={},
        system_prompt="",
        profile=CharacterProfile(age=age) if age else None,
        image_character_id=image_id,
    )


class FakeLoader:
    def __init__(self, *definitions):
        self.by_slug = {d.slug: d for d in definitions}

    def load(self, slug):
        return self.by_slug.get(slug)


class FakeImageProvider(ImageProvider):
    """Every call returns a different picture and is recorded."""

    def __init__(self):
        self.calls = []
        self.error = None  # set to an exception instance to fail

    async def generate_image(self, prompt, character_ref=None):
        self.calls.append((prompt, character_ref))
        if self.error:
            raise self.error
        return PNG_HEAD + f"picture-{len(self.calls)}".encode()


class RefusingImageProvider(FakeImageProvider):
    def __init__(self):
        super().__init__()
        self.error = ImageGenerationRefused("no")


class BrokenImageProvider(FakeImageProvider):
    def __init__(self):
        super().__init__()
        self.error = ImageGenerationError("down")


class SceneProvider(ScriptedProvider):
    """Chat AI that also answers the scene writer."""

    def __init__(self, scene_reply="setting=bedroom; pose=lying down; outfit=red dress", **kw):
        super().__init__(**kw)
        self.scene_reply = scene_reply
        self.scene_requests = []
        self.scene_fails = False

    async def generate_response(self, system_prompt, messages):
        if SCENE_MARKER in system_prompt.lower():
            self.scene_requests.append(messages)
            if self.scene_fails:
                raise RuntimeError("scene writer is down")
            return self.scene_reply
        return await super().generate_response(system_prompt, messages)
