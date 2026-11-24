"""Group messaging: who answers, several speakers, memory fan-out, isolation."""

import json

import pytest
from sqlalchemy import select

from app.models import CharacterMemory, Conversation, Message
from app.services.chat_session_service import ChatSessionService
from app.services.conversation_service import AIResponseError
from app.services.group_conversation_service import GroupConversationService
from app.services.group_context_builder import label_messages
from app.services.speaker_selection import GroupMember, select_speaker
from app.services.telegram_user_service import TelegramUserService
from tests.telegram_harness import Harness, add_characters, callback_update, message_update
from tests.test_conversation_engine import ONE_MEMORY, ScriptedProvider

TRIO = [("Amy", "amy", 0, True), ("Bob", "bob", 1, True), ("Cy", "cy", 2, True)]
FOUR_CHARS = TRIO + [("Dee", "dee", 3, True)]


def member(name, slug=None):
    return GroupMember(id=name, slug=slug or name.lower(), name=name)


class PromptLog(ScriptedProvider):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.chat_prompts = []
        self.chat_messages = []

    async def generate_response(self, system_prompt, messages):
        reply = await super().generate_response(system_prompt, messages)
        low = system_prompt.lower()
        if "long-term memory extraction system" not in low and "long-term conversation memory manager" not in low:
            self.chat_prompts.append(system_prompt)
            self.chat_messages.append(messages)
        return reply


async def make_group(maker, slugs=("amy", "bob"), telegram_id=1001):
    async with maker() as s:
        user = await TelegramUserService(s).get_or_create(telegram_id, "Ada")
        user_id = user.id
        ctx = await ChatSessionService(s).create_group(user_id, list(slugs))
        return user_id, ctx.conversation_id


# ------------------------------------------------------ speaker selection


def test_addressed_character_speaks():
    amy, bob = member("Amy"), member("Bob")
    assert select_speaker("Bob, how are you?", [amy, bob]).member is bob
    assert select_speaker("Bob, how are you?", [amy, bob]).reason == "addressed"
    assert select_speaker("@amy hi", [amy, bob]).member is amy
    assert select_speaker("what do you think, Bob?", [amy, bob]).member is bob


def test_continuation_and_default():
    amy, bob = member("Amy"), member("Bob")
    choice = select_speaker("tell me more", [amy, bob], last_speaker_id="Bob")
    assert (choice.member, choice.reason) == (bob, "continuation")
    choice = select_speaker("hello all", [amy, bob])
    assert (choice.member, choice.reason) == (amy, "default")


def test_addressing_beats_continuation_and_unknown_last_speaker_is_ignored():
    amy, bob = member("Amy"), member("Bob")
    assert select_speaker("Amy, you?", [amy, bob], last_speaker_id="Bob").member is amy
    assert select_speaker("hi", [amy, bob], last_speaker_id="ghost").reason == "default"


def test_no_members_is_an_error():
    with pytest.raises(ValueError):
        select_speaker("hi", [])


def test_label_messages_roles_and_names():
    class M:
        def __init__(self, sender_type, content, cid=None):
            self.sender_type, self.content, self.sender_character_id = sender_type, content, cid

    out = label_messages(
        [M("user", "hi"), M("character", "yo", "a"), M("character", "hey", "b")],
        "a",
        {"a": "Amy", "b": "Bob"},
        "Ada",
    )
    assert out == [
        {"role": "user", "content": "Ada: hi"},
        {"role": "assistant", "content": "yo"},
        {"role": "user", "content": "Bob: hey"},
    ]


# ----------------------------------------------------------- the service


def test_group_reply_is_saved_for_the_speaker_and_prompt_lists_the_room(run_db):
    async def scenario(maker):
        await add_characters(maker, TRIO)
        user_id, conv_id = await make_group(maker)
        provider = PromptLog(chat_reply="Bob: Hello there")

        async with maker() as s:
            [reply] = await GroupConversationService(s, provider).send_message(conv_id, user_id, "Bob, hi!")

        assert reply.speaker.name == "Bob" and reply.reason == "addressed"
        assert reply.content == "Hello there"  # the model's own-name prefix is dropped
        async with maker() as s:
            rows = (await s.execute(select(Message).order_by(Message.created_at))).scalars().all()
        assert [r.sender_type for r in rows] == ["user", "character"]
        assert rows[1].sender_character_id == reply.speaker.id
        assert rows[1].content == "Hello there"
        assert "Amy" in provider.chat_prompts[-1] and "Bob" in provider.chat_prompts[-1]
        assert provider.chat_messages[-1][-1] == {"role": "user", "content": "Ada: Bob, hi!"}

    run_db(scenario)


def test_memory_is_stored_for_every_member_separately_and_not_for_outsiders(run_db):
    async def scenario(maker):
        await add_characters(maker, TRIO)
        user_id, conv_id = await make_group(maker, ("amy", "bob"))
        provider = ScriptedProvider(extraction_json=ONE_MEMORY)

        async with maker() as s:
            await GroupConversationService(s, provider).send_message(conv_id, user_id, "I love Interstellar")

        async with maker() as s:
            memories = (await s.execute(select(CharacterMemory))).scalars().all()
            from app.models import Character

            by_id = {c.id: c.slug for c in (await s.execute(select(Character))).scalars()}

        assert sorted(by_id[m.character_id] for m in memories) == ["amy", "bob"]  # not cy
        assert all(m.user_id == user_id and m.source_kind == "group" for m in memories)
        assert all(m.source_conversation_id == conv_id for m in memories)

    run_db(scenario)


def test_a_character_prompt_never_contains_another_characters_memory(run_db):
    async def scenario(maker):
        await add_characters(maker, TRIO)
        user_id, conv_id = await make_group(maker, ("amy", "bob"))
        from app.models import Character
        from app.services.character_memory_service import CharacterMemoryService

        async with maker() as s:
            bob = (await s.execute(select(Character).where(Character.slug == "bob"))).scalar_one()
            await CharacterMemoryService(s).add_memory(
                user_id=user_id, character_id=bob.id, category="personal",
                content="CANARY-BOB-SECRET", importance=10, confidence=1.0, memory_key="canary",
            )
            await s.commit()

        provider = PromptLog()
        async with maker() as s:
            [reply] = await GroupConversationService(s, provider).send_message(conv_id, user_id, "Amy, hello")
        assert reply.speaker.name == "Amy"
        assert "CANARY-BOB-SECRET" not in provider.chat_prompts[-1]

        async with maker() as s:
            await GroupConversationService(s, provider).send_message(conv_id, user_id, "Bob, hello")
        assert "CANARY-BOB-SECRET" in provider.chat_prompts[-1]  # Bob does know it

    run_db(scenario)


def test_deletion_request_applies_to_every_member(run_db):
    async def scenario(maker):
        await add_characters(maker, TRIO)
        user_id, conv_id = await make_group(maker, ("amy", "bob"))
        async with maker() as s:
            await GroupConversationService(s, ScriptedProvider(extraction_json=ONE_MEMORY)).send_message(
                conv_id, user_id, "I love Interstellar"
            )
        delete = json.dumps({"memories": [{
            "operation": "delete", "memory_key": "favorite_movie", "category": "interest",
            "content": "x", "importance": 5, "confidence": 0.99, "is_long_term": True,
        }]})
        async with maker() as s:
            await GroupConversationService(s, ScriptedProvider(extraction_json=delete)).send_message(
                conv_id, user_id, "forget my favorite movie"
            )
        async with maker() as s:
            assert (await s.execute(select(CharacterMemory))).scalars().all() == []

    run_db(scenario)


def test_provider_failure_keeps_the_user_message(run_db):
    async def scenario(maker):
        await add_characters(maker, TRIO)
        user_id, conv_id = await make_group(maker)
        async with maker() as s:
            with pytest.raises(AIResponseError):
                await GroupConversationService(s, ScriptedProvider(fail=["chat"])).send_message(
                    conv_id, user_id, "hello"
                )
        async with maker() as s:
            rows = (await s.execute(select(Message))).scalars().all()
        assert [r.sender_type for r in rows] == ["user"]

    run_db(scenario)


def test_another_user_and_direct_chats_and_inactive_members_are_refused(run_db):
    async def scenario(maker):
        await add_characters(maker, TRIO)
        user_id, conv_id = await make_group(maker)
        other_id, _ = await make_group(maker, ("amy", "cy"), telegram_id=2002)
        async with maker() as s:
            ctx = await ChatSessionService(s, ScriptedProvider()).open_character_chat(user_id, "amy")
            direct_id = ctx.conversation_id

        service = lambda s: GroupConversationService(s, ScriptedProvider())  # noqa: E731
        async with maker() as s:
            with pytest.raises(ValueError):
                await service(s).send_message(conv_id, other_id, "hi")
        async with maker() as s:
            with pytest.raises(ValueError):
                await service(s).send_message(direct_id, user_id, "hi")

        from app.models import Character

        async with maker() as s:
            bob = (await s.execute(select(Character).where(Character.slug == "bob"))).scalar_one()
            bob.is_active = False
            await s.commit()
        async with maker() as s:
            with pytest.raises(ValueError):
                await service(s).send_message(conv_id, user_id, "hi")
            assert (await s.execute(select(Message).where(Message.conversation_id == conv_id))).scalars().all() == []

    run_db(scenario)


def test_labelled_summary(run_db):
    async def scenario(maker):
        await add_characters(maker, TRIO)
        user_id, conv_id = await make_group(maker)
        seen = []

        class Spy(PromptLog):
            async def generate_response(self, system_prompt, messages):
                if "long-term conversation memory manager" in system_prompt.lower():
                    seen.append(messages)
                return await super().generate_response(system_prompt, messages)

        spy = Spy(chat_reply="ok")
        for i in range(6):
            async with maker() as s:
                await GroupConversationService(s, spy).send_message(conv_id, user_id, f"Amy, n{i}")
        assert seen, "summary should have run"
        assert any("Amy: ok" in m["content"] for m in seen[0])

    run_db(scenario)


# --------------------------------------------------------------- bot flow


def test_bot_answers_in_a_group_with_the_speakers_name(run_db, tmp_path):
    async def scenario(maker):
        await add_characters(maker, TRIO)
        provider = ScriptedProvider(chat_reply="<b>hi</b> there")
        bot = Harness(maker, tmp_path, provider)
        await bot.send(message_update("/newgroup"))
        await bot.send(callback_update("gsel:0:amy"))
        await bot.send(callback_update("gsel:0:bob"))
        await bot.send(callback_update("gdone"))

        await bot.send(message_update("Bob, hello"))
        last = bot.session.named("SendMessage")[-1]
        assert last["text"] == "<b>Bob:</b> &lt;b&gt;hi&lt;/b&gt; there"
        assert last["parse_mode"] == "HTML"

        await bot.send(message_update("/history"))
        await bot.send(callback_update("hopen:" + "x"))  # unknown id must not crash the bot

    run_db(scenario)


# ---------------------------------------------------------------- director

from app.services.speaker_director import (  # noqa: E402
    DIRECTOR_MARKER,
    SILENCE,
    UNDECIDED,
    SpeakerDirector,
)


class DirectorProvider(PromptLog):
    def __init__(self, director_reply='{"speakers": ["amy", "bob"]}', director_fails=False, **kw):
        super().__init__(**kw)
        self.director_reply = director_reply
        self.director_fails = director_fails
        self.director_calls = 0
        self.director_prompt = ""
        self.director_input = ""

    async def generate_response(self, system_prompt, messages):
        if DIRECTOR_MARKER in system_prompt.lower():
            self.director_calls += 1
            self.director_prompt = system_prompt
            self.director_input = messages[0]["content"]
            if self.director_fails:
                raise RuntimeError("director is down")
            return self.director_reply
        return await super().generate_response(system_prompt, messages)


AMY, BOB = member("Amy"), member("Bob")


@pytest.mark.parametrize(
    "raw, expected",
    [
        ('{"speakers": ["bob"]}', [BOB]),
        ('{"speakers": ["bob", "amy"]}', [BOB, AMY]),
        ('```json\n{"speakers": ["amy"]}\n```', [AMY]),
        ('{"speakers": ["amy", "amy", "ghost", 7]}', [AMY]),
        ('{"speakers": [" bob "]}', [BOB]),
        ('{"speakers": []}', SILENCE),
        ('{"speakers": ["ghost"]}', UNDECIDED),
        ('{"speakers": "bob"}', UNDECIDED),
        ('{"speaker": "bob"}', UNDECIDED),
        ('["bob"]', UNDECIDED),
        ("bob", UNDECIDED),
        ("", UNDECIDED),
        (None, UNDECIDED),
    ],
)
def test_director_output_is_validated(raw, expected):
    result = SpeakerDirector._parse(raw, [AMY, BOB])
    assert result == expected if isinstance(expected, list) else result is expected


def test_everyone_the_director_names_answers_in_order_and_sees_earlier_replies(run_db):
    async def scenario(maker):
        await add_characters(maker, TRIO)
        user_id, conv_id = await make_group(maker)
        provider = DirectorProvider('{"speakers": ["bob", "amy"]}', chat_reply="hey")
        delivered = []

        async def on_reply(reply):
            delivered.append(reply.speaker.name)

        async with maker() as s:
            replies = await GroupConversationService(s, provider).send_message(
                conv_id, user_id, "what a day", on_reply=on_reply
            )

        assert [(r.speaker.name, r.reason) for r in replies] == [("Bob", "director"), ("Amy", "director")]
        assert delivered == ["Bob", "Amy"]
        assert provider.director_calls == 1
        assert "Ada: what a day" in provider.director_input and 'slug "amy"' in provider.director_prompt
        # Amy answers second, so she sees Bob's reply (labelled) in her messages.
        assert provider.chat_messages[-1][-1] == {"role": "user", "content": "Bob: hey"}
        async with maker() as s:
            rows = (await s.execute(select(Message).order_by(Message.created_at, Message.id))).scalars().all()
        assert [r.sender_type for r in rows] == ["user", "character", "character"]

    run_db(scenario)


def test_the_director_may_leave_some_characters_out(run_db):
    async def scenario(maker):
        await add_characters(maker, TRIO)
        user_id, conv_id = await make_group(maker)
        provider = DirectorProvider('{"speakers": ["bob"]}')
        async with maker() as s:
            replies = await GroupConversationService(s, provider).send_message(conv_id, user_id, "what a day")
        assert [r.speaker.name for r in replies] == ["Bob"]

    run_db(scenario)


def test_addressed_messages_do_not_call_the_director(run_db):
    async def scenario(maker):
        await add_characters(maker, TRIO)
        user_id, conv_id = await make_group(maker)
        provider = DirectorProvider()

        async with maker() as s:
            [reply] = await GroupConversationService(s, provider).send_message(conv_id, user_id, "Amy, hello")

        assert reply.speaker.name == "Amy" and provider.director_calls == 0

    run_db(scenario)


def test_silence_saves_the_user_message_but_no_character_reply(run_db):
    async def scenario(maker):
        await add_characters(maker, TRIO)
        user_id, conv_id = await make_group(maker)
        provider = DirectorProvider('{"speakers": []}')

        async with maker() as s:
            replies = await GroupConversationService(s, provider).send_message(conv_id, user_id, "ok thanks")

        assert replies == [] and provider.chat_prompts == []
        async with maker() as s:
            rows = (await s.execute(select(Message))).scalars().all()
        assert [r.sender_type for r in rows] == ["user"]

    run_db(scenario)


@pytest.mark.parametrize(
    "kwargs",
    [{"director_reply": '{"speakers": ["ghost"]}'}, {"director_reply": "nonsense"}, {"director_fails": True}],
)
def test_a_bad_director_means_everyone_answers(run_db, kwargs):
    async def scenario(maker):
        await add_characters(maker, TRIO)
        user_id, conv_id = await make_group(maker)
        provider = DirectorProvider(chat_reply="hey", **kwargs)

        async with maker() as s:
            replies = await GroupConversationService(s, provider).send_message(conv_id, user_id, "what a day")

        assert [(r.speaker.name, r.reason) for r in replies] == [("Amy", "everyone"), ("Bob", "everyone")]

    run_db(scenario)


def test_reply_cap_and_a_failing_later_character_keep_earlier_replies(run_db, monkeypatch):
    async def scenario(maker):
        await add_characters(maker, FOUR_CHARS)
        user_id, conv_id = await make_group(maker, ("amy", "bob", "cy", "dee"))

        import app.services.group_conversation_service as module

        monkeypatch.setattr(module, "MAX_REPLIES_PER_TURN", 2)
        async with maker() as s:
            replies = await GroupConversationService(s, PromptLog(chat_reply="hey")).send_message(
                conv_id, user_id, "what a day"
            )
        assert [r.speaker.name for r in replies] == ["Amy", "Bob"]

        monkeypatch.setattr(module, "MAX_REPLIES_PER_TURN", 4)

        class SecondFails(PromptLog):
            chats = 0

            async def generate_response(self, system_prompt, messages):
                low = system_prompt.lower()
                if "long-term" not in low and DIRECTOR_MARKER not in low:
                    SecondFails.chats += 1
                    if SecondFails.chats == 2:
                        raise RuntimeError("down")
                return await super().generate_response(system_prompt, messages)

        async with maker() as s:
            replies = await GroupConversationService(s, SecondFails(chat_reply="hey")).send_message(
                conv_id, user_id, "and now?"
            )
        assert [r.speaker.name for r in replies] == ["Amy"]  # Amy kept, the rest stopped

    run_db(scenario)


def test_a_failing_delivery_does_not_stop_the_other_characters(run_db):
    async def scenario(maker):
        await add_characters(maker, TRIO)
        user_id, conv_id = await make_group(maker)

        async def broken(reply):
            raise RuntimeError("telegram is down")

        async with maker() as s:
            replies = await GroupConversationService(s, PromptLog(chat_reply="hey")).send_message(
                conv_id, user_id, "what a day", on_reply=broken
            )
        assert len(replies) == 2

    run_db(scenario)


def test_bot_sends_each_characters_reply_as_its_own_message(run_db, tmp_path):
    async def scenario(maker):
        await add_characters(maker, TRIO)
        bot = Harness(maker, tmp_path, DirectorProvider(chat_reply="hey"))
        await bot.send(message_update("/newgroup"))
        await bot.send(callback_update("gsel:0:amy"))
        await bot.send(callback_update("gsel:0:bob"))
        await bot.send(callback_update("gdone"))
        before = len(bot.session.named("SendMessage"))

        await bot.send(message_update("what a day"))
        assert bot.texts()[before:] == ["<b>Amy:</b> hey", "<b>Bob:</b> hey"]

    run_db(scenario)


def test_bot_stays_quiet_when_the_director_chooses_silence(run_db, tmp_path):
    async def scenario(maker):
        await add_characters(maker, TRIO)
        bot = Harness(maker, tmp_path, DirectorProvider('{"speakers": []}'))
        await bot.send(message_update("/newgroup"))
        await bot.send(callback_update("gsel:0:amy"))
        await bot.send(callback_update("gsel:0:bob"))
        await bot.send(callback_update("gdone"))
        before = len(bot.session.named("SendMessage"))

        await bot.send(message_update("ok thanks"))
        assert len(bot.session.named("SendMessage")) == before

    run_db(scenario)


def test_instructions_tell_a_character_not_to_repeat_the_others():
    from app.services.group_context_builder import group_instructions

    text = group_instructions(AMY, [AMY, BOB], "Ada")
    assert "do not repeat their point" in text and "Bob" in text


# --------------------------------------------------- follow-ups (AI to AI)


class FollowupProvider(DirectorProvider):
    def __init__(self, followup_reply='{"from": "amy", "to": "bob"}', **kw):
        super().__init__(**kw)
        self.followup_reply = followup_reply
        self.followup_calls = 0

    async def generate_response(self, system_prompt, messages):
        if "side conversation" in system_prompt.lower():
            self.followup_calls += 1
            return self.followup_reply
        return await super().generate_response(system_prompt, messages)


@pytest.mark.parametrize(
    "raw, expected",
    [
        ('{"from": "amy", "to": "bob"}', (AMY, BOB)),
        ('```json\n{"from": "bob", "to": "amy"}\n```', (BOB, AMY)),
        ('{"from": null}', None),
        ('{"from": "amy", "to": "amy"}', None),
        ('{"from": "amy", "to": "ghost"}', None),
        ('{"from": "amy"}', None),
        ('{"from": 1, "to": 2}', None),
        ("[]", None),
        ("nonsense", None),
        (None, None),
    ],
)
def test_followup_output_is_validated(raw, expected):
    assert SpeakerDirector._parse_followup(raw, [AMY, BOB]) == expected


async def _talk(maker, provider, text="Amy, hello", **kwargs):
    from app.models import Character

    async with maker() as s:
        seeded = (await s.execute(select(Character.id).limit(1))).first() is not None
    if not seeded:
        await add_characters(maker, TRIO)
    user_id, conv_id = await make_group(maker)
    async with maker() as s:
        replies = await GroupConversationService(s, provider, **kwargs).send_message(conv_id, user_id, text)
    return user_id, conv_id, replies


def test_followup_is_a_question_and_an_answer_between_characters(run_db):
    async def scenario(maker):
        provider = FollowupProvider(chat_reply="hey")
        _, _, replies = await _talk(maker, provider, followup_chance=1.0)

        assert [(r.speaker.name, r.reason) for r in replies] == [
            ("Amy", "addressed"),
            ("Amy", "followup"),
            ("Bob", "followup"),
        ]
        assert provider.followup_calls == 1
        assert "RIGHT NOW" in provider.chat_prompts[-2] and "directly to Bob" in provider.chat_prompts[-2]
        assert "Amy just spoke to you" in provider.chat_prompts[-1]
        assert provider.chat_messages[-1][-1] == {"role": "user", "content": "Amy: hey"}

    run_db(scenario)


def test_followup_is_off_by_default_and_respects_the_chance(run_db):
    async def scenario(maker):
        provider = FollowupProvider(chat_reply="hey")
        _, _, replies = await _talk(maker, provider)  # default chance 0
        assert len(replies) == 1 and provider.followup_calls == 0

    run_db(scenario)


def test_followup_chance_gates_the_check(run_db):
    async def scenario_chance(maker):
        provider = FollowupProvider(chat_reply="hey")
        _, _, replies = await _talk(maker, provider, followup_chance=0.25, rng=lambda: 0.5)
        assert len(replies) == 1 and provider.followup_calls == 0  # 0.5 >= 0.25

        provider = FollowupProvider(chat_reply="hey")
        _, _, replies = await _talk(maker, provider, text="Bob, hi", followup_chance=0.25, rng=lambda: 0.1)
        assert provider.followup_calls == 1

    run_db(scenario_chance)


def test_no_followup_when_the_director_says_no_or_fails(run_db):
    async def scenario(maker):
        for reply in ('{"from": null}', "nonsense", '{"from": "amy", "to": "amy"}'):
            provider = FollowupProvider(followup_reply=reply, chat_reply="hey")
            _, _, replies = await _talk(maker, provider, followup_chance=1.0)
            assert [r.reason for r in replies] == ["addressed"]

    run_db(scenario)


def test_followup_respects_the_total_reply_cap(run_db, monkeypatch):
    async def scenario(maker):
        import app.services.group_conversation_service as module

        monkeypatch.setattr(module, "MAX_TOTAL_REPLIES_PER_TURN", 2)
        provider = FollowupProvider(chat_reply="hey")
        _, _, replies = await _talk(maker, provider, followup_chance=1.0)
        # 1 reply + a 2-message exchange would be 3 > 2: no follow-up, no extra call.
        assert len(replies) == 1 and provider.followup_calls == 0

    run_db(scenario)


def test_a_failing_followup_keeps_the_real_replies(run_db):
    async def scenario(maker):
        class Fails(FollowupProvider):
            chats = 0

            async def generate_response(self, system_prompt, messages):
                low = system_prompt.lower()
                if "long-term" not in low and DIRECTOR_MARKER not in low:
                    Fails.chats += 1
                    if Fails.chats == 2:  # Amy's reply works, the follow-up fails
                        raise RuntimeError("down")
                return await super().generate_response(system_prompt, messages)

        _, _, replies = await _talk(maker, Fails(chat_reply="hey"), followup_chance=1.0)
        assert [r.reason for r in replies] == ["addressed"]

    run_db(scenario)


def test_followup_messages_are_delivered_and_saved(run_db):
    async def scenario(maker):
        provider = FollowupProvider(chat_reply="hey")
        await add_characters(maker, TRIO)
        user_id, conv_id = await make_group(maker)
        delivered = []

        async def on_reply(reply):
            delivered.append((reply.speaker.name, reply.reason))

        async with maker() as s:
            await GroupConversationService(s, provider, followup_chance=1.0).send_message(
                conv_id, user_id, "Amy, hello", on_reply=on_reply
            )
        assert delivered == [("Amy", "addressed"), ("Amy", "followup"), ("Bob", "followup")]
        async with maker() as s:
            rows = (await s.execute(select(Message).order_by(Message.created_at, Message.id))).scalars().all()
        assert [r.sender_type for r in rows] == ["user", "character", "character", "character"]

    run_db(scenario)


def test_telegram_flow_enables_followups(run_db, tmp_path, monkeypatch):
    import app.telegram.handlers as handlers

    monkeypatch.setattr(handlers, "FOLLOWUP_CHANCE", 1.0)

    async def scenario(maker):
        await add_characters(maker, TRIO)
        bot = Harness(maker, tmp_path, FollowupProvider(chat_reply="hey"))
        await bot.send(message_update("/newgroup"))
        await bot.send(callback_update("gsel:0:amy"))
        await bot.send(callback_update("gsel:0:bob"))
        await bot.send(callback_update("gdone"))
        before = len(bot.session.named("SendMessage"))

        await bot.send(message_update("Amy, hello"))
        assert bot.texts()[before:] == ["<b>Amy:</b> hey", "<b>Amy:</b> hey", "<b>Bob:</b> hey"]

    run_db(scenario)
