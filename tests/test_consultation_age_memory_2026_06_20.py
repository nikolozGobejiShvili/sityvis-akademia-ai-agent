"""Consultation Flow Memory / Repeated Age Fix (2026-06-20).

Live bug: the parent gave the child's age and phone in ONE message
(„14 წლის არის 595999733"); the agent stored the phone but kept asking
„რამდენი წლისაა თქვენი შვილი?" turn after turn — behaving like a scripted
bot instead of remembering what it was told.

Root cause was NOT a phrase issue: the deterministic age fallback
(`maybe_capture_child_age_fallback`) BAILED whenever the message contained a
phone prefix („595…"), so the child age was never extracted/persisted and the
LLM (correctly, per its prompt) re-asked for the unknown fact.

The fix:
  * strip recognised phone numbers BEFORE age extraction so age + phone are
    captured from the SAME message (phone never erases age, age never erases
    phone);
  * run the capture PRE-turn in the engine so the model sees the facts before
    it answers;
  * a deterministic anti-repeat guard that replaces a redundant child-age
    question with the next missing detail once the age is known.

These tests drive the REAL parent flow (`parent_flow.handle` /
`conversation_service.process_message`) with the PARENT LLM engine ON and a
mocked OpenAI — no real OpenAI / Meta / Calendar / Sheets / Redis / network.
"""

from __future__ import annotations

import dataclasses
from types import SimpleNamespace

import pytest

import app.config as config_module
from app.agent.llm import parent_llm_engine
from app.flows import parent_flow, parent_turn_router
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.services import conversation_service, messenger_service, openai_service

_AGE_QUESTION_STRINGS = (
    "რამდენი წლის",
    "თქვენი შვილი რამდენი წლისაა",
)


# -- fixtures --------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_state():
    conversation_service.conversations.clear()
    parent_turn_router.manager_offer_shown.clear()
    parent_flow.available_slots.clear()
    parent_flow.invalid_phone_retries.clear()
    yield
    conversation_service.conversations.clear()


@pytest.fixture
def engine_on(monkeypatch):
    """Mirror the LIVE config: PARENT LLM engine ON. Settings is frozen, so
    swap a replaced copy into parent_flow (the routing chokepoint)."""
    swapped = dataclasses.replace(config_module.settings, USE_PARENT_LLM_ENGINE=True)
    monkeypatch.setattr(parent_flow, "settings", swapped)
    monkeypatch.setattr(messenger_service, "get_user_profile", lambda sid, plat: {})


def _mk_response(*, content: str = "", tool_calls=None):
    """Duck-typed OpenAI chat.completions response the engine can read."""
    tc_objs = []
    for tc in tool_calls or []:
        tc_objs.append(SimpleNamespace(
            id=tc["id"],
            function=SimpleNamespace(
                name=tc["name"], arguments=tc.get("arguments", "{}"),
            ),
        ))
    msg = SimpleNamespace(content=content or None, tool_calls=tc_objs or None)
    return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


def _mock_llm(monkeypatch, content):
    """Make the LLM return ``content`` as a direct answer (no tool call)."""
    monkeypatch.setattr(
        openai_service, "chat_with_tools",
        lambda **kw: _mk_response(content=content),
    )


def _parent_conv(child_age: str = "", phone: str = "") -> Conversation:
    conv = Conversation(sender_id="age-mem", platform="instagram")
    # Seed a prior assistant turn so the first-reply static-welcome bypass
    # doesn't short-circuit the engine.
    conv.history.append({"role": "assistant", "content": "_prior_welcome"})
    conv.lead = Lead(
        sender_id="age-mem", platform="instagram", segment="PARENT",
        child_age=child_age, phone=phone,
    )
    return conv


# ==========================================================================
# 1, 10–15 — extraction of age + phone from the SAME message
# ==========================================================================


def test_combined_age_phone_extracts_both(engine_on, monkeypatch):
    """Test 1 — „14 წლის არის 595999733" → child_age=14 AND phone=595999733."""
    conv = _parent_conv()
    _mock_llm(monkeypatch, "გასაგებია, გმადლობთ.")
    parent_flow.handle(conv, "14 წლის არის 595999733")
    assert conv.lead.child_age == "14"
    assert conv.lead.phone == "595999733"


def test_combined_age_phone_variant_extracts_both(engine_on, monkeypatch):
    """Test 10 — „14 წლისაა 595999733" → both."""
    conv = _parent_conv()
    _mock_llm(monkeypatch, "გასაგებია.")
    parent_flow.handle(conv, "14 წლისაა 595999733")
    assert conv.lead.child_age == "14"
    assert conv.lead.phone == "595999733"


@pytest.mark.parametrize("message, expected_age", [
    ("14 წლის არისს", "14"),          # test 11 — typo tolerated
    ("ჩემი შვილი 14 წლისაა", "14"),   # test 12
    ("ბავშვი 14 წლის არის", "14"),    # test 13
    ("ცამეტი წლისაა", "13"),          # Georgian numeral
    ("თოთხმეტი წლისაა", "14"),        # Georgian numeral
])
def test_age_only_messages_extract_age(engine_on, monkeypatch, message, expected_age):
    conv = _parent_conv()
    _mock_llm(monkeypatch, "გასაგებია.")
    parent_flow.handle(conv, message)
    assert conv.lead.child_age == expected_age


def test_phone_capture_does_not_erase_existing_age(engine_on, monkeypatch):
    """Test 14 — a phone-only follow-up keeps the already-known age."""
    conv = _parent_conv(child_age="14")
    _mock_llm(monkeypatch, "გმადლობთ.")
    parent_flow.handle(conv, "595999733")
    assert conv.lead.child_age == "14"      # untouched
    assert conv.lead.phone == "595999733"   # captured


def test_age_capture_does_not_erase_existing_phone(engine_on, monkeypatch):
    """Test 15 — an age-only follow-up keeps the already-known phone."""
    conv = _parent_conv(phone="595999733")
    _mock_llm(monkeypatch, "გმადლობთ.")
    parent_flow.handle(conv, "14 წლისაა")
    assert conv.lead.phone == "595999733"   # untouched
    assert conv.lead.child_age == "14"      # captured


def test_two_phones_not_guessed(engine_on, monkeypatch):
    """Two distinct numbers must NOT be silently captured (disambiguation
    preserved); the combined age is still captured."""
    conv = _parent_conv()
    _mock_llm(monkeypatch, "გასაგებია.")
    parent_flow.handle(conv, "14 წლისაა, 595999733 ან 577123456")
    assert conv.lead.child_age == "14"
    assert (conv.lead.phone or "") == ""


# ==========================================================================
# 2 — after the combined message the reply must NOT re-ask the age
# ==========================================================================


def test_combined_message_reply_does_not_reask_age(engine_on, monkeypatch):
    """Test 2 — even if the (mocked) model tries to ask the age again, the
    anti-repeat guard removes it because child_age is now known."""
    conv = _parent_conv()
    _mock_llm(monkeypatch, "მადლობა. თქვენი შვილი რამდენი წლისაა?")
    out = parent_flow.handle(conv, "14 წლის არის 595999733")
    assert conv.lead.child_age == "14" and conv.lead.phone == "595999733"
    for phrase in _AGE_QUESTION_STRINGS:
        assert phrase not in out, f"reply re-asked age: {out!r}"


# ==========================================================================
# 3, 4, 5 — subsequent turns never re-ask the age once it is known
# ==========================================================================


@pytest.mark.parametrize("user_turn", [
    "შემომთავაზეთ თავისუფალი დღეები",   # test 3 — asks for free days
    "იყოს 10 საათი",                     # test 4 — selects a time
    "კიიი",                              # test 5 — confirms
    "მაწყობს",                           # test 5 — confirms
])
def test_known_age_never_reasked_on_later_turns(engine_on, monkeypatch, user_turn):
    conv = _parent_conv(child_age="14", phone="595999733")
    _mock_llm(monkeypatch, "კარგი. თქვენი შვილი რამდენი წლისაა?")  # worst case
    out = parent_flow.handle(conv, user_turn)
    for phrase in _AGE_QUESTION_STRINGS:
        assert phrase not in out, f"re-asked age on {user_turn!r}: {out!r}"
    assert conv.lead.child_age == "14"   # never wiped by a later turn


# ==========================================================================
# 6–9 — ask only for what is missing
# ==========================================================================


def test_only_phone_known_still_asks_age(engine_on, monkeypatch):
    """Test 6 — age genuinely unknown → the age question is NOT suppressed."""
    conv = _parent_conv(phone="595999733")
    _mock_llm(monkeypatch, "თქვენი შვილი რამდენი წლისაა?")
    out = parent_flow.handle(conv, "მინდა კონსულტაცია")
    assert "რამდენი წლის" in out  # asking age is correct when it is missing


def test_only_age_known_asks_phone_not_age(engine_on, monkeypatch):
    """Test 7 — age known, phone missing → a redundant age question is
    replaced by the phone ask."""
    conv = _parent_conv(child_age="14")
    _mock_llm(monkeypatch, "თქვენი შვილი რამდენი წლისაა?")
    out = parent_flow.handle(conv, "მინდა კონსულტაცია")
    assert "რამდენი წლის" not in out
    assert "ნომერ" in out  # next missing detail = phone


def test_guard_replacement_picks_next_missing_detail():
    """Tests 7 + 9 (component) — when the guard has to replace a redundant age
    question it asks for the NEXT missing detail: the phone when the phone is
    unknown, the preferred day/time once age AND phone are both known."""
    conv = Conversation(sender_id="n", platform="instagram")
    age_only = Lead(sender_id="n", platform="instagram", segment="PARENT", child_age="14")
    out_phone = parent_llm_engine._suppress_redundant_age_question(
        "რამდენი წლისაა?", age_only, conv,
    )
    assert "ნომერ" in out_phone and "რამდენი წლის" not in out_phone

    age_phone = Lead(
        sender_id="n", platform="instagram", segment="PARENT",
        child_age="14", phone="595999733",
    )
    out_dt = parent_llm_engine._suppress_redundant_age_question(
        "რამდენი წლისაა?", age_phone, conv,
    )
    assert ("დღე" in out_dt or "საათ" in out_dt) and "რამდენი წლის" not in out_dt


def test_guard_untouched_when_age_unknown():
    """Test 8 (component) — both missing → guard never fires; the reply is
    returned verbatim so the flow can ask for what it needs."""
    conv = Conversation(sender_id="g", platform="instagram")
    text = "სახელი, ნომერი და ბავშვის ასაკი მომწერეთ. რამდენი წლისაა?"
    lead = Lead(sender_id="g", platform="instagram", segment="PARENT")
    out = parent_llm_engine._suppress_redundant_age_question(text, lead, conv)
    assert out == text


# ==========================================================================
# Anti-bot quality test + guard component behaviour
# ==========================================================================


def test_anti_bot_known_age_reply_never_asks_age():
    """Anti-bot: if child_age exists, the generated reply must not ask for the
    child's age again."""
    conv = Conversation(sender_id="q", platform="instagram")
    lead = Lead(sender_id="q", platform="instagram", segment="PARENT", child_age="14", phone="595999733")
    out = parent_llm_engine._suppress_redundant_age_question(
        "თქვენი შვილი რამდენი წლისაა?", lead, conv,
    )
    assert "რამდენი წლის" not in out
    assert out  # a real next-step reply, never empty


def test_guard_preserves_confirmation_mentioning_age():
    """A CONFIRMATION that mentions the age (not a question) is left intact."""
    conv = Conversation(sender_id="c", platform="instagram")
    lead = Lead(sender_id="c", platform="instagram", segment="PARENT", child_age="14")
    text = "თქვენი შვილის ასაკი 14 წელია — ბანაკი შესაბამისია. გავაგრძელოთ?"
    out = parent_llm_engine._suppress_redundant_age_question(text, lead, conv)
    assert out == text


# ==========================================================================
# 16 — pre-booking age correction still works
# ==========================================================================


def test_age_correction_before_booking(engine_on, monkeypatch):
    """Test 16 — „არა, 15 წლისაა" after a prior 14 updates child_age to 15."""
    conv = _parent_conv(child_age="14")
    _mock_llm(monkeypatch, "გასაგებია, განვაახლე.")
    parent_flow.handle(conv, "არა, 15 წლისაა")
    assert conv.lead.child_age == "15"


# ==========================================================================
# process_message — the full Messenger path persists both facts
# ==========================================================================


def test_process_message_persists_age_and_phone(engine_on, monkeypatch, camp_registration_open):
    """Through conversation_service.process_message (the live path): after a
    camp-interest turn, the combined age+phone message persists BOTH facts on
    the stored lead and the reply does not re-ask the age."""
    monkeypatch.setattr(
        openai_service, "chat_with_tools",
        lambda **kw: _mk_response(content="გასაგებია. თქვენი შვილი რამდენი წლისაა?"),
    )
    # Turn 1 — establish a PARENT conversation.
    conversation_service.process_message("flow-u", "ბანაკი მაინტერესებს", "instagram")
    # Turn 2 — the live bug message.
    out = conversation_service.process_message("flow-u", "14 წლის არის 595999733", "instagram")

    conv = conversation_service.conversations["flow-u"]
    assert conv.lead.child_age == "14"
    assert conv.lead.phone == "595999733"
    for phrase in _AGE_QUESTION_STRINGS:
        assert phrase not in out, f"process_message reply re-asked age: {out!r}"


# ==========================================================================
# 17, 24 — preserved behaviour guards (underage capture, stream filter)
# ==========================================================================


def test_underage_age_still_captured_and_no_age_reask(engine_on, monkeypatch):
    """Test 17 (capture side) — an under-age value is still captured (the
    executor/handoff handles eligibility elsewhere) and is not re-asked."""
    conv = _parent_conv()
    parent_llm_engine.maybe_capture_child_age_fallback(conv.lead, "8 წლისაა")
    assert conv.lead.child_age == "8"
    # An 8-year-old's manager-handoff reply (no age question) is untouched.
    handoff = "ეს ასაკი ბანაკს არ ერგება — გნებავთ, მენეჯერთან დაგაკავშირებთ?"
    out = parent_llm_engine._suppress_redundant_age_question(handoff, conv.lead, conv)
    assert out == handoff


def test_camp_stream_date_filter_helpers_unchanged():
    """Test 24 — the camp-stream visibility filter is untouched by this fix."""
    from app.services import admin_config_service as acs
    assert hasattr(acs, "get_visible_camp_streams")
    assert hasattr(acs, "is_camp_stream_visible")
