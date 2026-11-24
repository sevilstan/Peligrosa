"""The character card: age, place, job, life story and key traits."""

from types import SimpleNamespace

import pytest

from app.services.character_definition_loader import CharacterDefinitionLoader, CharacterProfile
from app.services.character_gallery_service import CharacterGalleryService, GalleryCharacter
from app.services.character_prompt_builder import CharacterPromptBuilder
from app.telegram.slides import build_caption, build_slide

BASE = """
name: Elena
slug: elena
description: Gizemli ve zeki.
personality:
  core_traits:
    - Esprili
"""


def load(tmp_path, extra=""):
    (tmp_path / "elena.yaml").write_text(BASE + extra, encoding="utf-8")
    return CharacterDefinitionLoader(tmp_path).load("elena")


# ---------------------------------------------------------------------- loader


def test_profile_is_optional(tmp_path):
    assert load(tmp_path).profile is None
    assert load(tmp_path, "profile:\n").profile is None
    assert load(tmp_path, "profile: {}\n").profile is None


def test_profile_fields_are_loaded_and_cleaned(tmp_path):
    profile = load(
        tmp_path,
        """
profile:
  age: 28
  city: "  İstanbul "
  occupation: Fotoğrafçı
  bio: >
    İzmir'de büyüdü.
    Sonra İstanbul'a taşındı.
  highlights:
    - Gizemli
    - Esprili
  future_field: ignored
""",
    ).profile

    assert profile == CharacterProfile(
        age=28,
        city="İstanbul",
        occupation="Fotoğrafçı",
        bio="İzmir'de büyüdü. Sonra İstanbul'a taşındı.",
        highlights=("Gizemli", "Esprili"),
    )


@pytest.mark.parametrize(
    "block",
    [
        "profile:\n  age: 17\n",  # every character is an adult
        "profile:\n  age: 0\n",
        "profile:\n  age: 121\n",
        "profile:\n  age: '28'\n",
        "profile:\n  age: 28.5\n",
        "profile:\n  age: true\n",
        "profile: text\n",
        "profile:\n  city: [a]\n",
        "profile:\n  city: " + "x" * 61 + "\n",
        "profile:\n  occupation: " + "x" * 61 + "\n",
        "profile:\n  bio: " + "x" * 601 + "\n",
        "profile:\n  highlights: Gizemli\n",
        "profile:\n  highlights: [a, b, c, d, e, f]\n",
        "profile:\n  highlights: ['']\n",
        "profile:\n  highlights: [1]\n",
        "profile:\n  highlights: ['" + "x" * 41 + "']\n",
    ],
)
def test_invalid_profile_is_an_error_not_a_silent_fallback(tmp_path, block):
    with pytest.raises(ValueError):
        load(tmp_path, block)


def test_age_boundaries_are_allowed(tmp_path):
    assert load(tmp_path, "profile:\n  age: 18\n").profile.age == 18
    assert load(tmp_path, "profile:\n  age: 120\n").profile.age == 120


# --------------------------------------------------------------------- gallery


def test_gallery_passes_the_profile_through_and_falls_back_without_yaml(run_db, tmp_path):
    async def scenario(maker):
        from app.models import Character

        (tmp_path / "amy.yaml").write_text(
            "name: Amy\nslug: amy\ndescription: d\nprofile:\n  age: 30\n  city: Ankara\n", encoding="utf-8"
        )
        async with maker() as s:
            s.add_all(
                [
                    Character(name="Amy", slug="amy", description="d", personality="p", system_prompt="s", is_active=True, sort_order=0),
                    Character(name="Bob", slug="bob", description="d", personality="p", system_prompt="s", is_active=True, sort_order=1),
                ]
            )
            await s.commit()

        async with maker() as s:
            service = CharacterGalleryService(s, CharacterDefinitionLoader(tmp_path))
            amy = (await service.get_page(0)).characters[0]
            bob = (await service.get_page(1)).characters[0]

        assert amy.profile == CharacterProfile(age=30, city="Ankara")
        assert bob.profile is None  # no YAML: the card stays as before

    run_db(scenario)


# ----------------------------------------------------------------------- card


def card(profile=None, name="Elena", description="Gizemli ve zeki."):
    return GalleryCharacter("elena", name, description, None, profile)


FULL = CharacterProfile(
    age=28,
    city="İstanbul",
    occupation="Fotoğrafçı",
    bio="İzmir'de büyüdü, İstanbul'a taşındı.".replace("'", " "),
    highlights=("Gizemli", "Esprili"),
)


def test_card_without_a_profile_looks_exactly_as_before():
    assert build_caption(card()) == "<b>Elena</b>\n\nGizemli ve zeki."
    assert build_caption(card(name="Elena", description="")) == "<b>Elena</b>"


def test_card_shows_name_age_place_job_description_life_and_traits():
    assert build_caption(card(FULL)) == (
        "<b>Elena</b>, 28\n\n"
        "📍 İstanbul  💼 Fotoğrafçı\n\n"
        "Gizemli ve zeki.\n\n"
        "<i>İzmir de büyüdü, İstanbul a taşındı.</i>\n\n"
        "✨ Gizemli · Esprili"
    )


def test_card_leaves_out_what_is_missing():
    assert build_caption(card(CharacterProfile(age=25))) == "<b>Elena</b>, 25\n\nGizemli ve zeki."
    assert build_caption(card(CharacterProfile(city="Ankara"))) == "<b>Elena</b>\n\n📍 Ankara\n\nGizemli ve zeki."
    assert build_caption(card(CharacterProfile(highlights=("Sakin",)), description="")) == "<b>Elena</b>\n\n✨ Sakin"


def test_card_escapes_html_everywhere():
    profile = CharacterProfile(age=20, city="A&B", occupation="<i>x</i>", bio="a < b", highlights=("<b>",))
    caption = build_caption(card(profile, name="E<l>", description="d & d"))
    assert "&lt;l&gt;" in caption and "A&amp;B" in caption and "&lt;i&gt;x&lt;/i&gt;" in caption
    assert "a &lt; b" in caption and "&lt;b&gt;" in caption and "d &amp; d" in caption
    assert "<l>" not in caption and "<i>x</i>" not in caption


def test_card_always_fits_a_photo_caption_even_with_everything_at_its_limit():
    nasty = CharacterProfile(
        age=120,
        city="&" * 60,
        occupation="<" * 60,
        bio=" ".join(["&<>"] * 150)[:600],
        highlights=tuple("&" * 40 for _ in range(5)),
    )
    caption = build_caption(card(nasty, name="N" * 100, description="&<>" * 400))
    assert len(caption) <= 1024
    assert caption.startswith("<b>") and "</b>, 120" in caption  # name and age always stay
    assert caption.count("<i>") == caption.count("</i>")  # trimming never cuts a tag in half
    assert caption.count("<b>") == caption.count("</b>")


def test_a_normal_card_is_not_trimmed():
    profile = CharacterProfile(age=30, bio="x " * 200, highlights=("a",))
    caption = build_caption(card(profile, description="d " * 100))
    assert len(caption) <= 1024 and "x x x x" in caption and "d d d d" in caption and "✨ a" in caption


def test_when_space_runs_out_the_life_story_goes_first_then_the_description():
    heavy = CharacterProfile(age=30, city="&" * 60, occupation="&" * 60, bio="story " * 80, highlights=tuple("&" * 40 for _ in range(2)))
    caption = build_caption(card(heavy, description="description " * 25))
    assert len(caption) <= 1024
    assert "<i>" not in caption and "story" not in caption  # the life story went first
    assert "📍" in caption  # the place and job line outlives the long texts


def test_slide_uses_the_card_and_keeps_the_picture_lookup(tmp_path):
    from app.telegram.avatars import AvatarProvider

    slide = build_slide(card(FULL), None, AvatarProvider(tmp_path))
    assert slide.caption == build_caption(card(FULL)) and slide.avatar is None


# ---------------------------------------------------------------------- prompt


def make_character(profile):
    return SimpleNamespace(name="Elena", description="d", personality="p", system_prompt="s", profile=profile)


def test_the_character_knows_the_facts_on_her_card():
    prompt = CharacterPromptBuilder().build(make_character(FULL))
    assert "Age: 28" in prompt and "City: İstanbul" in prompt and "Occupation: Fotoğrafçı" in prompt
    assert "Life story: İzmir de büyüdü, İstanbul a taşındı." in prompt
    assert "Key traits: Gizemli, Esprili" in prompt
    assert prompt.index("Age: 28") < prompt.index("PERSONALITY")  # part of her identity
    assert prompt.index("Key traits:") < prompt.index("PERSONALITY")


def test_no_profile_means_the_prompt_is_unchanged():
    without = CharacterPromptBuilder().build(make_character(None))
    legacy = CharacterPromptBuilder().build(SimpleNamespace(name="Elena", description="d", personality="p", system_prompt="s"))
    assert without == legacy and "Age:" not in without and "Life story" not in without
    only_city = CharacterPromptBuilder().build(make_character(CharacterProfile(city="X")))
    assert "Age:" not in only_city and "Key traits" not in only_city


def test_a_long_description_is_shortened_not_dropped():
    caption = build_caption(card(None, description="&" * 300))
    assert len(caption) <= 1024 and "&amp;&amp;" in caption  # some of it is still there
