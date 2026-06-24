"""Handoff/contact intent-priority + deterministic semantic name validation
(live-smoke blocker, 2026-06-23).

A live under-age transcript trapped the agent in manager-handoff contact
collection: action phrases („მე დავურეკავ მენჯერის ნომერი მომწერე") were
stored as the parent's NAME, explicit manager-phone requests were ignored (the
typo „მენჯერ" was missed), and an affirmation („კიმინდა") after a consultation
CTA revived the stale handoff state.

Fixes (all deterministic, NO LLM, all in app/flows/parent_flow.py):
  * manager-phone / self-call request OUTRANKS contact collection (typo „მენჯერ"
    tolerated; self-call „მე თვითონ დავურეკავ" recognised);
  * a SHARED semantic name validator (`_is_storable_person_name`) used by BOTH
    the consultation and manager-handoff paths rejects action phrases /
    affirmations and generalises beyond a fixed reject list;
  * topic-switch with no contact defers (no sticky-handoff trap).

PART C: the manager phone is fetched from `admin_config_service.get_manager_phone()`
— this file never hardcodes the literal number.

All offline / mocked — no real OpenAI / Meta / Calendar / Sheets / email.
"""
from __future__ import annotations

import dataclasses

import pytest

import app.config as config_module
from app.flows import parent_flow
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.services import (
    admin_config_service,
    messenger_service,
    notification_service,
)
from app.agent.tools import parent_tool_executor

_OFFER = (
    "ბანაკში მონაწილეობა შესაძლებელია 9–17 წლის ბავშვებისთვის. "
    "ამ ასაკისთვის ბანაკში ჩაწერას ვერ შემოგთავაზებთ. "
    "თუ გსურთ, მენეჯერთან დაგაკავშირებთ."
)
_HANDOFF_ASK = parent_flow._HANDOFF_ASK_NAME_AND_PHONE
# PART C — canonical helper, never a hardcoded literal.
EXPECTED_PHONE = (admin_config_service.get_manager_phone() or "").strip()


@pytest.fixture(autouse=True)
def _reset_state():
    from app.services import conversation_service
    parent_tool_executor.reset_state()
    conversation_service.conversations.clear()
    yield
    parent_tool_executor.reset_state()
    conversation_service.conversations.clear()


@pytest.fixture
def engine_on(monkeypatch):
    swapped = dataclasses.replace(config_module.settings, USE_PARENT_LLM_ENGINE=True)
    monkeypatch.setattr(parent_flow, "settings", swapped)
    monkeypatch.setattr(messenger_service, "get_user_profile", lambda sid, plat: {})


def _ua_conv(sender_id="ua", *, name="", phone="", child_age="7", last=_OFFER):
    conv = Conversation(sender_id=sender_id, platform="instagram", segment="PARENT")
    conv.lead = Lead(sender_id=sender_id, platform="instagram", segment="PARENT")
    conv.lead.child_age = child_age
    if name:
        conv.lead.name = name
    if phone:
        conv.lead.phone = phone
    conv.history.append({"role": "assistant", "content": last})
    return conv


def _no_dispatch(monkeypatch):
    """Spy that fails the test if a manager handoff/email is ever dispatched."""
    calls = []
    monkeypatch.setattr(
        notification_service, "notify_manager_handoff",
        lambda lead, reason: calls.append((lead.name, lead.phone, reason)) or True,
    )
    return calls


# =========================================================================
# PART B/H — manager phone outranks contact collection
# =========================================================================
def test_h1_self_call_underage_gets_manager_phone(monkeypatch):
    calls = _no_dispatch(monkeypatch)
    conv = _ua_conv()
    out = parent_flow._maybe_handle_underage_manager_handoff(
        conv, "კი დამაკავშირეთ მენჯერის ნომერი რომმომწეროთ მე თვითონ დავურეკავ",
    )
    assert out is not None
    assert EXPECTED_PHONE and EXPECTED_PHONE in out
    assert "შეგიძლიათ პირდაპირ დაუკავშირდეთ" in out
    assert conv.lead.name == ""          # no name collected/stored
    assert calls == []                   # no dispatch / no email
    assert "გადავეცი" not in out         # never claims handoff success


def test_h2_self_call_phrase_gets_phone_not_name(monkeypatch):
    _no_dispatch(monkeypatch)
    conv = _ua_conv()
    out = parent_flow._maybe_handle_underage_manager_handoff(
        conv, "მე დავურეკავ მენჯერის ნომერი მომწერე",
    )
    assert out is not None
    assert EXPECTED_PHONE in out
    assert conv.lead.name == ""
    assert "სახელი მივიღე" not in out


def test_h3_manager_number_typo_wants_phone(monkeypatch):
    _no_dispatch(monkeypatch)
    conv = _ua_conv()
    out = parent_flow._maybe_handle_underage_manager_handoff(
        conv, "მენჯერის ნომერი მინდა",
    )
    assert out is not None
    assert EXPECTED_PHONE in out
    assert "მომწერეთ" not in out or "შეგიძლიათ პირდაპირ" in out  # not contact-collection
    assert conv.lead.name == ""


def test_h4_action_phrase_never_stored_as_name():
    # The exact live phrase must never become lead.name (validator-level).
    assert not parent_flow._is_storable_person_name(
        "დავურეკავ მენჯერის", "მე დავურეკავ მენჯერის ნომერი მომწერე",
    )


def test_h5_action_phrase_never_in_manager_email(monkeypatch):
    calls = _no_dispatch(monkeypatch)
    conv = _ua_conv()
    parent_flow._maybe_handle_underage_manager_handoff(
        conv, "მე დავურეკავ მენჯერის ნომერი მომწერე",
    )
    # Disclosure path dispatches nothing → the phrase can never reach the email.
    assert calls == []
    assert conv.lead.name == ""


def test_h6_plain_connect_me_collects_contact(monkeypatch):
    _no_dispatch(monkeypatch)
    conv = _ua_conv()
    out = parent_flow._maybe_handle_underage_manager_handoff(conv, "კი დამაკავშირეთ")
    assert out == _HANDOFF_ASK            # asks for name + phone
    assert conv.lead.name == ""
    assert EXPECTED_PHONE not in out      # NOT a phone disclosure


def test_h7_connect_to_manager_collects_contact(monkeypatch):
    _no_dispatch(monkeypatch)
    conv = _ua_conv()
    out = parent_flow._maybe_handle_underage_manager_handoff(
        conv, "დამაკავშირეთ მენეჯერთან",
    )
    assert out == _HANDOFF_ASK
    assert conv.lead.name == ""


# =========================================================================
# PART G/H — pending-state cleanup (topic switch / affirmation not trapped)
# =========================================================================
def test_h9_topic_switch_after_decline_not_trapped():
    # last assistant turn = the decline ack (no manager) → handoff not re-armed.
    conv = _ua_conv(last="გასაგებია. თუ რამე შეიცვლება, მომწერეთ.")
    assert parent_flow._maybe_handle_underage_manager_handoff(
        conv, "ბანაკის ფასი რა არის?",
    ) is None


def test_h9b_topic_switch_without_question_mark_not_trapped():
    # Even mid-collection, a topic switch with no contact defers to the engine.
    conv = _ua_conv(last=parent_flow._HANDOFF_ASK_NAME_AND_PHONE)
    assert parent_flow._maybe_handle_underage_manager_handoff(
        conv, "ბანაკის ფასი",
    ) is None


def test_h10_affirmation_after_consultation_cta_not_revived():
    # Consultation CTA mentions the manager, but „კიმინდა" must NOT revive the
    # handoff nor be stored as a name.
    conv = _ua_conv(
        last="თუ გსურთ, კონსულტაციაზე ჩაგწერთ და მენეჯერი დეტალებს აგიხსნით.",
    )
    out = parent_flow._maybe_handle_underage_manager_handoff(conv, "კიმინდა")
    assert out is None
    assert conv.lead.name != "კიმინდა"
    assert conv.lead.name == ""


def test_affirmation_is_not_a_name():
    for aff in ("კიმინდა", "კი მინდა", "კი, მინდა", "კი", "მინდა"):
        assert parent_flow._is_affirmation_only(aff), aff
        assert not parent_flow._is_storable_person_name(aff, aff), aff


# =========================================================================
# PART E — held-out action phrases (NOT transcript-specific blocklist)
# =========================================================================
def test_e_heldout_xval_dagirekavt_not_a_name():
    assert not parent_flow._is_storable_person_name("ხვალ დაგირეკავთ", "ხვალ დაგირეკავთ")
    conv = _ua_conv(last=parent_flow._HANDOFF_ASK_NAME_AND_PHONE)
    out = parent_flow._maybe_handle_underage_manager_handoff(conv, "ხვალ დაგირეკავთ")
    assert conv.lead.name == ""
    assert out is None or "სახელი მივიღე" not in out


def test_e_heldout_mogvianebit_mogtsert_not_a_name():
    assert not parent_flow._is_storable_person_name(
        "მოგვიანებით მოგწერთ", "მოგვიანებით მოგწერთ",
    )
    conv = _ua_conv(last=parent_flow._HANDOFF_ASK_NAME_AND_PHONE)
    out = parent_flow._maybe_handle_underage_manager_handoff(conv, "მოგვიანებით მოგწერთ")
    assert conv.lead.name == ""
    assert out is None or "სახელი მივიღე" not in out


# =========================================================================
# PART H — real names / contact still captured (no over-rejection)
# =========================================================================
def test_h11_real_name_and_phone_still_dispatch(monkeypatch):
    calls = _no_dispatch(monkeypatch)
    conv = _ua_conv(last=parent_flow._HANDOFF_ASK_NAME_AND_PHONE)
    out = parent_flow._maybe_handle_underage_manager_handoff(conv, "ნიკოლოზი 595999733")
    assert conv.lead.name == "ნიკოლოზი"
    assert conv.lead.phone == "595999733"
    assert len(calls) == 1               # dispatched once with the REAL name
    assert calls[0][0] == "ნიკოლოზი"
    assert "გადავეცი" in out


def test_h13_georgian_name_storable():
    assert parent_flow._is_storable_person_name("ნიკა", "ნიკა 595999733")
    assert parent_flow._is_storable_person_name("nika", "nika 595999733")
    assert parent_flow._is_storable_person_name("ნიკოლოზი", "ნიკოლოზი")


def test_h12_latin_intent_word_not_storable():
    assert not parent_flow._is_storable_person_name("madloba", "madloba 595999733")


# =========================================================================
# PART C — canonical helper, not a hardcoded phone
# =========================================================================
def test_c_manager_phone_uses_canonical_helper(monkeypatch):
    # Change the helper → the disclosure must change accordingly (proves it is
    # NOT a hardcoded string).
    monkeypatch.setattr(admin_config_service, "get_manager_phone", lambda: "599 11 22 33")
    conv = _ua_conv()
    out = parent_flow._maybe_handle_underage_manager_handoff(conv, "მენჯერის ნომერი მინდა")
    assert "599 11 22 33" in out
    assert EXPECTED_PHONE not in out or EXPECTED_PHONE == "599 11 22 33"


def test_c_explicit_manager_request_still_works():
    conv = _ua_conv(child_age="12", last="გისმენთ")  # eligible, generic last turn
    out = parent_flow._maybe_handle_explicit_manager_request(
        conv, "მენეჯერის ნომერი მომწერე",
    )
    assert out is not None
    assert EXPECTED_PHONE in out


# =========================================================================
# integration through handle() with the engine ON
# =========================================================================
def test_integration_self_call_through_handle(engine_on, monkeypatch):
    calls = _no_dispatch(monkeypatch)
    tripped = {"engine": 0}
    monkeypatch.setattr(
        parent_flow, "_run_llm_engine_safely",
        lambda *a, **k: tripped.__setitem__("engine", tripped["engine"] + 1) or "ENGINE",
    )
    conv = _ua_conv()
    out = parent_flow.handle(conv, "მე დავურეკავ მენჯერის ნომერი მომწერე")
    assert EXPECTED_PHONE in out
    assert "სახელი მივიღე" not in out
    assert conv.lead.name == ""
    assert calls == []
    assert tripped["engine"] == 0        # never reached the LLM


# =========================================================================
# PART K — exact live-transcript handoff sub-sequence (scripted)
# =========================================================================
def test_exact_live_transcript_handoff_sequence(monkeypatch):
    """Walk the exact under-age handoff turns from the live smoke transcript.
    Each manager-phone request must disclose the number; no action phrase may
    ever be stored as the name; nothing is dispatched on a disclosure turn."""
    calls = _no_dispatch(monkeypatch)
    conv = _ua_conv()

    def _turn(user_msg):
        reply = parent_flow._maybe_handle_underage_manager_handoff(conv, user_msg)
        if reply is not None:
            conv.history.append({"role": "user", "content": user_msg})
            conv.history.append({"role": "assistant", "content": reply})
        return reply

    r1 = _turn("კი დამაკავშირეთ მენჯერის ნომერი რომმომწეროთ მე თვითონ დავურეკავ")
    assert r1 is not None and EXPECTED_PHONE in r1

    r2 = _turn("მე დავურეკავ მენჯერის ნომერი მომწერე")
    assert r2 is not None and EXPECTED_PHONE in r2
    assert "სახელი მივიღე" not in r2

    r3 = _turn("მენჯერის ნომერი მინდა")
    assert r3 is not None and EXPECTED_PHONE in r3
    assert "სახელი მივიღე" not in r3

    # Throughout, no action phrase was stored as the name and nothing dispatched.
    assert conv.lead.name == ""
    assert calls == []
    # The exact phrase never became the stored name.
    assert "დავურეკავ" not in (conv.lead.name or "")


# =========================================================================
# PART J — source-of-truth guard (not regressed)
# =========================================================================
def test_j_manager_phone_unified_on_helper():
    import inspect
    assert "get_manager_phone" in inspect.getsource(admin_config_service.get_camp_facts)


def test_j_parent_flow_zero_direct_camp_2026_reads():
    import inspect
    src = inspect.getsource(parent_flow)
    assert 'load_knowledge("camp_2026")' not in src
    assert "load_knowledge('camp_2026')" not in src
