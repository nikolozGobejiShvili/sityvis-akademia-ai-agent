"""State Consistency + Age Extraction Fix (2026-06-11).

Generic, state-based behaviour — NO hardcoded users.

Live bug: a fresh PARENT/camp user wrote „ბავშვების საზაფხულო ბანაკი 9-17"
(where „9-17" is the camp's advertised age BAND, not the child's age).
The deterministic fallback `maybe_capture_child_age_fallback` read „9" out
of „9-17" and set child_age=„9", so the agent treated the age as known
and never asked the child's real age.

Test groups (per task):
  FIX 1 — age extraction rejects ranges / menu echoes / time-date (1–10)
  FIX 2 — new-user camp qualification guard (11–16)
  FIX 3 — stored-state transparency + re-qualification (17–20)
  Scalability / no hardcoding (21–24)
"""

from __future__ import annotations

import dataclasses
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

import app.config as config_module
from app.agent.llm import parent_llm_engine
from app.agent.llm.parent_llm_engine import (
    _bot_recently_asked_child_age,
    _contains_age_range,
    maybe_capture_child_age_fallback,
)
from app.agent.tools.parent_tool_executor import ParentToolExecutor
from app.agent.tools.parent_tools import TOOL_SAVE_LEAD_INFO
from app.flows import parent_flow
from app.models.conversation import Conversation
from app.models.lead import Lead


def _lead(sender_id: str = "fake_user_1", child_age: str = "") -> Lead:
    lead = Lead(sender_id=sender_id, platform="messenger", segment="PARENT")
    lead.child_age = child_age
    return lead


def _parent_conv(
    *,
    sender_id: str = "fake_user_1",
    child_age: str = "",
    adult_age: str = "",
    segment: str = "PARENT",
    state: str = "START",
    booked: bool = False,
    name: str = "",
    phone: str = "",
    seed_assistant: bool = True,
) -> Conversation:
    conv = Conversation(sender_id=sender_id, platform="messenger", segment=segment)
    conv.state = state
    lead = Lead(sender_id=sender_id, platform="messenger", segment="PARENT")
    lead.child_age = child_age
    if adult_age:
        lead.adult_age = adult_age
    lead.name = name
    lead.phone = phone
    lead.calendly_booked = booked
    conv.lead = lead
    if seed_assistant:
        # Skip the state=START static-welcome bypass (fires only on the
        # bot's very first reply) so we can exercise the engine path.
        conv.history.append({"role": "assistant", "content": "_prior_turn"})
    return conv


def _mk_response(*, content: str = ""):
    msg = SimpleNamespace(content=content or None, tool_calls=None)
    return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


def _enable_engine(monkeypatch):
    swapped = dataclasses.replace(
        config_module.settings, USE_PARENT_LLM_ENGINE=True,
    )
    monkeypatch.setattr(parent_flow, "settings", swapped)


def _handle_mocked_engine(monkeypatch, conv, message, engine_reply):
    _enable_engine(monkeypatch)
    monkeypatch.setattr(
        parent_flow, "_run_llm_engine_safely", lambda c, m: engine_reply,
    )
    monkeypatch.setattr(
        parent_flow, "_handle_impl",
        lambda c, m: pytest.fail("legacy fallback must not run"),
    )
    return parent_flow.handle(conv, message)


# ===========================================================================
# FIX 1 — age extraction rejects ranges / menu echoes / time-date
# ===========================================================================


def test_1_camp_menu_range_not_extracted():
    lead = _lead()
    maybe_capture_child_age_fallback(lead, "ბავშვების საზაფხულო ბანაკი 9-17")
    assert lead.child_age == ""


def test_2_range_9_17_weli_not_extracted():
    lead = _lead()
    maybe_capture_child_age_fallback(lead, "9-17 წელი")
    assert lead.child_age == ""


def test_3_range_for_children_not_extracted():
    lead = _lead()
    maybe_capture_child_age_fallback(lead, "9-17 წლის ბავშვებისთვის")
    assert lead.child_age == ""


@pytest.mark.parametrize("message", [
    "9 დან 17 წლამდე",
    "9-დან 17 წლამდე",
    "9 დან 17",
])
def test_4_georgian_dan_range_not_extracted(message):
    lead = _lead()
    maybe_capture_child_age_fallback(lead, message)
    assert lead.child_age == ""


def test_5_explicit_14_extracted():
    lead = _lead()
    maybe_capture_child_age_fallback(lead, "14 წლის არის")
    assert lead.child_age == "14"


def test_6_explicit_9_extracted():
    lead = _lead()
    maybe_capture_child_age_fallback(lead, "9 წლისაა")
    assert lead.child_age == "9"


@pytest.mark.parametrize("message", ["12 საათზე", "20:00 საათზე", "18 სთ"])
def test_7_time_not_extracted_even_when_age_pending(message):
    lead = _lead()
    maybe_capture_child_age_fallback(lead, message, age_question_pending=True)
    assert lead.child_age == ""


@pytest.mark.parametrize("message", ["11 ივნისს", "15 ივნისი", "20:00"])
def test_8_date_not_extracted_even_when_age_pending(message):
    lead = _lead()
    maybe_capture_child_age_fallback(lead, message, age_question_pending=True)
    assert lead.child_age == ""


@pytest.mark.parametrize("message", [
    "შვილი 8-ზე მოვა",
    "ბავშვი 9-ზე",
    "შვილი 8ზე მოვა",
    "შვილს 10-ზე მოვიყვან",
])
def test_8b_colloquial_hour_suffix_not_extracted(message):
    """„N-ზე" / „Nზე" is a colloquial CLOCK time („at N o'clock"), never
    the child's age — even though the message has a child word. (Found by
    the adversarial review — same bug class as the „9-17" range leak.)"""
    lead = _lead()
    maybe_capture_child_age_fallback(lead, message)
    assert lead.child_age == ""


def test_8c_real_age_with_child_word_still_extracted():
    """Control: a genuine age in child context is still captured."""
    lead = _lead()
    maybe_capture_child_age_fallback(lead, "ჩემი შვილი 12 წლისაა")
    assert lead.child_age == "12"


def test_9_standalone_number_in_age_question_context():
    lead = _lead()
    maybe_capture_child_age_fallback(lead, "12", age_question_pending=True)
    assert lead.child_age == "12"


def test_10_standalone_number_outside_age_context_not_extracted():
    lead = _lead()
    maybe_capture_child_age_fallback(lead, "12", age_question_pending=False)
    assert lead.child_age == ""


def test_contains_age_range_helper():
    assert _contains_age_range("9-17")
    assert _contains_age_range("9 - 17")
    assert _contains_age_range("9–17")
    assert _contains_age_range("9 დან 17 წლამდე")
    assert not _contains_age_range("14 წლის")
    assert not _contains_age_range("ორი ბავშვი 11 და 14 წლის")  # „და" ≠ „დან"


def test_bot_recently_asked_child_age_detection():
    conv = Conversation(sender_id="fake_u", platform="messenger")
    conv.history = [{"role": "assistant", "content": "თქვენი შვილი რამდენი წლისაა?"}]
    assert _bot_recently_asked_child_age(conv) is True
    conv.history = [{"role": "assistant", "content": "ბანაკი მშვენიერია."}]
    assert _bot_recently_asked_child_age(conv) is False


def test_save_lead_info_rejects_age_range():
    conv = _parent_conv()
    executor = ParentToolExecutor(
        conversation=conv, lead=conv.lead,
        sender_id=conv.sender_id, platform=conv.platform,
    )
    result = executor.execute(TOOL_SAVE_LEAD_INFO, {"child_age": "9-17"})
    assert "child_age" in result.get("invalid_fields", [])
    assert conv.lead.child_age == ""


def test_save_lead_info_accepts_single_age():
    conv = _parent_conv()
    executor = ParentToolExecutor(
        conversation=conv, lead=conv.lead,
        sender_id=conv.sender_id, platform=conv.platform,
    )
    result = executor.execute(TOOL_SAVE_LEAD_INFO, {"child_age": "14"})
    assert "child_age" in result.get("saved_fields", [])
    assert conv.lead.child_age == "14"


def test_adult_age_is_not_used_as_child_age():
    """An adult age never silently becomes the child age."""
    lead = _lead()
    lead.adult_age = "30"
    maybe_capture_child_age_fallback(lead, "30 წლის ვარ")  # > 20 → rejected
    assert lead.child_age == ""


# ===========================================================================
# FIX 2 — new-user camp qualification guard
# ===========================================================================


def test_camp_guard_appends_age_question_when_missing():
    conv = _parent_conv(child_age="")
    out = parent_flow._ensure_camp_age_question(
        conv, "ბავშვების საზაფხულო ბანაკი 9-17",
        "სიტყვის აკადემიის ბანაკი 9-17 წლის ბავშვებისთვისაა.",
    )
    assert "თქვენი შვილი რამდენი წლისაა?" in out


def test_camp_guard_noop_when_age_known():
    conv = _parent_conv(child_age="12")
    reply = "ბანაკის ფასი 2150 ლარია."
    out = parent_flow._ensure_camp_age_question(conv, "ფასი?", reply)
    assert out == reply


def test_camp_guard_noop_when_reply_already_asks():
    conv = _parent_conv(child_age="")
    reply = "გასაგებია. თქვენი შვილი რამდენი წლისაა?"
    out = parent_flow._ensure_camp_age_question(conv, "ბანაკი", reply)
    assert out == reply


def test_camp_guard_noop_for_adult_segment():
    conv = _parent_conv(child_age="", segment="ADULT")
    reply = "კულტურული საღამოები შემოგთავაზებთ."
    out = parent_flow._ensure_camp_age_question(conv, "ღონისძიება", reply)
    assert out == reply


def test_camp_guard_noop_on_manager_handoff():
    conv = _parent_conv(child_age="")
    reply = "თუ გსურთ, დაგაკავშირებთ მენეჯერთან."
    out = parent_flow._ensure_camp_age_question(conv, "მენეჯერი", reply)
    assert out == reply


def test_11_e2e_new_user_range_message_asks_age(monkeypatch):
    """Full path: „ბავშვების საზაფხულო ბანაკი 9-17" → real engine runs,
    the fallback does NOT capture „9" from the range, and the camp guard
    asks the child's age."""
    _enable_engine(monkeypatch)
    from app.services import messenger_service, openai_service
    monkeypatch.setattr(
        messenger_service, "get_user_profile", lambda sid, plat: {},
    )
    info = "სიტყვის აკადემიის ბანაკი 9-17 წლის ბავშვებისთვისაა."
    monkeypatch.setattr(
        openai_service, "chat_with_tools",
        lambda **kw: _mk_response(content=info),
    )
    conv = _parent_conv(child_age="", segment="PARENT")
    out = parent_flow.handle(conv, "ბავშვების საზაფხულო ბანაკი 9-17")
    assert conv.lead.child_age == ""  # FIX 1 — range not read as age
    assert "რამდენი წლისაა" in out    # FIX 2 — age asked


def test_12_new_user_camp_interest_asks_age(monkeypatch):
    conv = _parent_conv(child_age="", segment="PARENT")
    out = _handle_mocked_engine(
        monkeypatch, conv, "საზაფხულო ბანაკი მაინტერესებს",
        "სიამოვნებით დაგეხმარებით ბანაკის შესახებ.",
    )
    # Deterministic approved intro (client hotfix 2026-07-03) asks the child age
    # with „რამდენი წლის არის თქვენი შვილი?"; match either age-question phrasing.
    assert "რამდენი წლის" in out


def test_13_new_user_price_question_returns_full_block(monkeypatch):
    conv = _parent_conv(child_age="", segment="PARENT")
    out = _handle_mocked_engine(
        monkeypatch, conv, "ფასი მაინტერესებს",
        "ბანაკის ფასი 2150 ლარია.",
    )
    assert "2150" in out
    assert "TBC" in out
    assert "რამდენი წლისაა" not in out

def test_14_known_age_same_camp_message_does_not_reask(monkeypatch):
    conv = _parent_conv(child_age="12", segment="PARENT")
    out = _handle_mocked_engine(
        monkeypatch, conv, "საზაფხულო ბანაკი მაინტერესებს",
        "ბანაკი მშვენიერია, 9-17 წლის ბავშვებისთვისაა.",
    )
    assert "რამდენი წლისაა" not in out


def test_15_adult_age_only_still_asks_child_age(monkeypatch):
    conv = _parent_conv(child_age="", adult_age="30", segment="PARENT")
    out = _handle_mocked_engine(
        monkeypatch, conv, "საზაფხულო ბანაკი მაინტერესებს",
        "სიამოვნებით დაგეხმარებით ბანაკის შესახებ.",
    )
    # Deterministic approved intro (client hotfix 2026-07-03) asks the child age;
    # match either age-question phrasing.
    assert "რამდენი წლის" in out
    assert conv.lead.child_age == ""        # adult_age NOT used as child_age
    assert conv.lead.adult_age == "30"


def test_16_dirty_mixed_state_reuses_child_age(monkeypatch):
    conv = _parent_conv(
        child_age="14", adult_age="30", segment="PARENT",
        state="DONE", booked=True,
    )
    out = _handle_mocked_engine(
        monkeypatch, conv, "ბანაკის შესახებ კიდევ მაქვს კითხვა",
        "რა თქმა უნდა, რას დააზუსტებთ ბანაკზე?",
    )
    assert conv.lead.child_age == "14"
    assert conv.lead.adult_age == "30"
    assert "რამდენი წლისაა" not in out


# ===========================================================================
# FIX 3 — stored-state transparency + re-qualification
# ===========================================================================


def test_17_resume_greeting_acknowledges_stored_age():
    conv = _parent_conv(child_age="14", segment="PARENT", state="DONE")
    out = parent_flow.handle(conv, "გამარჯობა")
    assert "14 წლისაა" in out
    assert "ისევ ინტერესდებით" in out


def test_18_confirm_after_ack_continues_without_reasking(monkeypatch):
    conv = _parent_conv(child_age="14", segment="PARENT", state="DONE")
    out = _handle_mocked_engine(
        monkeypatch, conv, "კი", "კარგი, გავაგრძელოთ ბანაკით.",
    )
    assert conv.lead.child_age == "14"
    assert "რამდენი წლისაა" not in out


def test_19_requalify_different_child_resets_and_asks():
    conv = _parent_conv(child_age="14", segment="PARENT", state="DONE")
    out = parent_flow.handle(conv, "არა, სხვა შვილზე ვწერ")
    assert conv.lead.child_age == ""
    assert "რამდენი წლისაა" in out


def test_19b_requalify_with_new_age_in_same_message(monkeypatch):
    conv = _parent_conv(child_age="14", segment="PARENT", state="DONE")
    out = _handle_mocked_engine(
        monkeypatch, conv, "სხვა ბავშვისთვის, 10 წლის",
        "გასაგებია, 10 წლის ბავშვისთვის ბანაკი იდეალურია.",
    )
    assert conv.lead.child_age == "10"


def test_20_requalify_preserves_name_and_phone():
    conv = _parent_conv(
        child_age="14", name="ნინო", phone="595999733", state="DONE",
    )
    parent_flow._maybe_requalify_child(conv, "სხვა შვილზე ვწერ")
    assert conv.lead.child_age == ""
    assert conv.lead.name == "ნინო"
    assert conv.lead.phone == "595999733"


def test_ack_does_not_fire_mid_flow_pending_booking():
    conv = _parent_conv(child_age="14", segment="PARENT", state="DONE")
    conv.pending_booking = {"requested_datetime_iso": "2030-06-15T15:00:00+04:00"}
    assert parent_flow._maybe_acknowledge_stored_state(conv, "გამარჯობა") is None


def test_ack_does_not_fire_for_booked_user():
    conv = _parent_conv(child_age="14", segment="PARENT", state="DONE", booked=True)
    assert parent_flow._maybe_acknowledge_stored_state(conv, "გამარჯობა") is None


# ===========================================================================
# Scalability / no hardcoding
# ===========================================================================


@pytest.mark.parametrize("sender_id", [
    "fake_111", "fake_222", "another_fake_user", "psid_abc_999",
])
def test_23_same_input_same_state_same_behavior(sender_id):
    """Behaviour depends on state, not on which (fake) user it is."""
    lead_a = _lead(sender_id=sender_id)
    maybe_capture_child_age_fallback(lead_a, "ბავშვების საზაფხულო ბანაკი 9-17")
    assert lead_a.child_age == ""  # same for every sender id

    lead_b = _lead(sender_id=sender_id)
    maybe_capture_child_age_fallback(lead_b, "14 წლის")
    assert lead_b.child_age == "14"


def test_24_same_input_different_state_different_behavior():
    # Same bare „12" — captured ONLY when an age question is pending.
    pending = _lead()
    maybe_capture_child_age_fallback(pending, "12", age_question_pending=True)
    assert pending.child_age == "12"

    not_pending = _lead()
    maybe_capture_child_age_fallback(not_pending, "12", age_question_pending=False)
    assert not_pending.child_age == ""

    # Same camp reply — age asked only when child_age is unknown.
    unknown = _parent_conv(child_age="")
    known = _parent_conv(child_age="12")
    reply = "ბანაკი მშვენიერია."
    assert "რამდენი წლისაა" in parent_flow._ensure_camp_age_question(
        unknown, "ბანაკი", reply,
    )
    assert parent_flow._ensure_camp_age_question(known, "ბანაკი", reply) == reply


def test_21_no_hardcoded_real_sender_ids_in_changed_sources():
    """No long numeric LITERAL (a real Facebook PSID is 15–16 digits)
    hardcoded into the changed application logic. Tokenises the source so
    phone-format examples inside docstrings/comments are ignored — only
    actual numeric code literals are inspected."""
    import io
    import tokenize

    root = Path(__file__).resolve().parent.parent / "app"
    targets = [
        root / "flows" / "parent_flow.py",
        root / "agent" / "llm" / "parent_llm_engine.py",
        root / "agent" / "tools" / "parent_tool_executor.py",
    ]
    for path in targets:
        src = path.read_text(encoding="utf-8")
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type != tokenize.NUMBER:
                continue
            digits = tok.string.replace("_", "")
            assert not (digits.isdigit() and len(digits) >= 12), (
                f"hardcoded long numeric literal {tok.string!r} in {path.name}"
            )


def test_22_helpers_work_for_arbitrary_fake_sender_ids():
    for sid in ("u_aaa", "u_bbb", "u_ccc"):
        conv = _parent_conv(sender_id=sid, child_age="", segment="PARENT")
        out = parent_flow._ensure_camp_age_question(
            conv, "ბანაკი", "ბანაკი მშვენიერია.",
        )
        assert "რამდენი წლისაა" in out


# ===========================================================================
# FIX 4 — state versioning safe load (defaults, no crash)
# ===========================================================================


def test_fix4_stale_snapshot_loads_with_defaults():
    """An old/partial Redis payload (missing newer fields) loads cleanly
    with safe defaults — no crash."""
    stale = {"sender_id": "fake_u", "platform": "messenger"}
    conv = Conversation.from_dict(stale)
    assert conv.sender_id == "fake_u"
    assert conv.adult_subscription_status == ""
    assert conv.followup_stage == ""
    assert conv.pending_booking is None
