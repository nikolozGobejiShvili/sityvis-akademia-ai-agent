"""Under-age manager-handoff live bugs (2026-06-22).

A real PARENT/camp transcript for an 8-year-old (under-age) surfaced two bugs
in the under-age manager-handoff contact collection:

  BUG 1 — „კი მომწერე" („yes, write to me", an agreement to the handoff) was
  mis-read: the parser stored the verb „მომწერე" as the parent's NAME and the
  bot replied „სახელი მივიღე…" instead of asking for the name + phone.

  BUG 2 — „მენეჯერის ნომერი მომწერე" („write me the MANAGER's number") was
  also mis-read as a name disclosure, so the under-age parent was wrongly
  re-asked for THEIR number instead of being given the manager's number. The
  dedicated manager-number interceptor never ran because the under-age handoff
  (which takes precedence) intercepted the „მენეჯერ" mention first.

Fixes (all in app/flows/parent_flow.py, in-memory only — NO Sheets / Calendar /
dispatch):
  A — name-reject stems for the comms-imperative verbs („მომწერ" /
      „გამომიგზავ" / „გამიგზავ") and the role word „მენეჯერ" so none is ever
      stored as a name.
  B — the under-age handoff serves an explicit manager-NUMBER request with the
      configured number (admin_config_service.get_manager_phone()).
  C — a leading affirmative + a „contact me" verb („კი მომწერე") is recognised
      as handoff agreement, so it asks for the name + phone.

All offline / mocked — no real OpenAI / Meta / Calendar / Sheets / network.
"""
from __future__ import annotations

import dataclasses
from types import SimpleNamespace

import pytest

import app.config as config_module
from app.flows import parent_flow
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.services import (
    admin_config_service,
    messenger_service,
    notification_service,
    openai_service,
)
from app.agent.tools import parent_tool_executor

_OFFER = (
    "ბანაკში მონაწილეობა შესაძლებელია 9–17 წლის ბავშვებისთვის. "
    "ამ ასაკისთვის ბანაკში ჩაწერას ვერ შემოგთავაზებთ. "
    "თუ გსურთ, მენეჯერთან დაგაკავშირებთ."
)


@pytest.fixture(autouse=True)
def _reset_state():
    from app.services import conversation_service
    parent_tool_executor.reset_state()
    conversation_service.conversations.clear()
    parent_flow.invalid_phone_retries.clear()
    yield
    parent_tool_executor.reset_state()
    conversation_service.conversations.clear()


@pytest.fixture
def engine_on(monkeypatch):
    swapped = dataclasses.replace(config_module.settings, USE_PARENT_LLM_ENGINE=True)
    monkeypatch.setattr(parent_flow, "settings", swapped)
    monkeypatch.setattr(messenger_service, "get_user_profile", lambda sid, plat: {})


def _ua_conv(sender_id, *, name="", phone="", child_age="8", last=_OFFER):
    """An under-age (default 8yo) PARENT conversation, last assistant turn = the
    manager-handoff offer (so the handoff context is armed)."""
    conv = Conversation(sender_id=sender_id, platform="instagram", segment="PARENT")
    conv.lead = Lead(sender_id=sender_id, platform="instagram", segment="PARENT")
    conv.lead.child_age = child_age
    if name:
        conv.lead.name = name
    if phone:
        conv.lead.phone = phone
    conv.history.append({"role": "assistant", "content": last})
    return conv


def _spy_dispatch(monkeypatch):
    calls = []
    monkeypatch.setattr(
        notification_service, "notify_manager_handoff",
        lambda lead, reason: calls.append((lead.name, lead.phone, reason)) or True,
    )
    return calls


def _boom(**kw):
    raise AssertionError("engine must NOT be consulted on a deterministic turn")


# ===========================================================================
# A — name rejection of comms-imperative verbs + the role word „მენეჯერ"
# ===========================================================================


@pytest.mark.parametrize("token", [
    "მომწერე", "მომწერეთ", "მენეჯერი", "მენეჯერის", "გამომიგზავნე", "გამიგზავნე",
])
def test_comms_verbs_and_manager_word_not_a_name(token):
    assert parent_flow._name_token_is_valid(token) is False


@pytest.mark.parametrize("name", ["ნინო", "ნიკოლოზი", "მარიამი", "გიორგი", "ანა"])
def test_real_names_still_valid(name):
    assert parent_flow._name_token_is_valid(name) is True


def test_manager_number_phrase_is_not_a_person_name():
    # The whole „მენეჯერის ნომერი მომწერე" run must not yield a stored name.
    assert parent_flow.is_valid_person_name("მენეჯერის ნომერი მომწერე") is False
    name, phone = parent_flow._parse_name_phone("მენეჯერის ნომერი მომწერე")
    assert name == ""
    assert phone == ""


def test_ki_momtsere_yields_no_name():
    name, phone = parent_flow._parse_name_phone("კი მომწერე")
    assert name == ""
    assert phone == ""


# ===========================================================================
# C — „კი მომწერე" is handoff agreement, not a name
# ===========================================================================


@pytest.mark.parametrize("msg", [
    "კი მომწერე", "დიახ დამირეკეთ", "კი დამიკავშირდით", "ჰო მომწერე",
])
def test_affirmative_plus_contact_verb_is_affirmative(msg):
    assert parent_flow._is_handoff_affirmative(msg.lower()) is True


@pytest.mark.parametrize("msg", ["კი", "დიახ", "კარგი"])
def test_bare_affirmative_still_affirmative(msg):
    assert parent_flow._is_handoff_affirmative(msg) is True


@pytest.mark.parametrize("msg", ["ნიკოლოზი", "595999733 ნიკოლოზი", "რა ღირს ბანაკი"])
def test_non_affirmative_messages(msg):
    assert parent_flow._is_handoff_affirmative(msg.lower()) is False


# ===========================================================================
# BUG 1 — „კი მომწერე" asks name + phone, does NOT claim a name was received
# ===========================================================================


def test_ki_momtsere_asks_name_and_phone_no_dispatch(monkeypatch):
    calls = _spy_dispatch(monkeypatch)
    conv = _ua_conv("ua-momt-1")
    out = parent_flow._maybe_handle_underage_manager_handoff(conv, "კი მომწერე")
    assert out is not None
    assert "სახელი" in out and "ნომერ" in out      # asks for BOTH
    assert "სახელი მივიღე" not in out               # never claims a name
    assert calls == []                              # nothing dispatched
    assert (conv.lead.name or "") == ""             # „მომწერე" not stored


# ===========================================================================
# BUG 2 — explicit manager-number request mid-handoff → discloses the number
# ===========================================================================


def test_manager_number_request_in_handoff_discloses_number(monkeypatch):
    calls = _spy_dispatch(monkeypatch)
    manager_number = admin_config_service.get_manager_phone()
    assert manager_number, "test prerequisite: a manager number must be configured"

    conv = _ua_conv("ua-mgr-1")
    out = parent_flow._maybe_handle_underage_manager_handoff(
        conv, "მენეჯერის ნომერი მომწერე",
    )
    assert out is not None
    assert manager_number in out                    # the manager number is given
    assert "სახელი მივიღე" not in out               # not re-asked as contact
    assert calls == []                              # disclosure, no dispatch
    assert (conv.lead.name or "") == ""             # nothing mis-captured


# ===========================================================================
# Regression — a real name + phone still dispatches with the right name
# ===========================================================================


def test_real_name_and_phone_still_dispatches(monkeypatch):
    calls = _spy_dispatch(monkeypatch)
    conv = _ua_conv("ua-ok-1")
    out = parent_flow._maybe_handle_underage_manager_handoff(
        conv, "ნიკოლოზი 595999733",
    )
    assert len(calls) == 1
    assert calls[0][0] == "ნიკოლოზი" and calls[0][1] == "595999733"
    assert "გადავეცი" in out


def test_real_name_only_still_asks_phone(monkeypatch):
    calls = _spy_dispatch(monkeypatch)
    conv = _ua_conv("ua-ok-2")
    out = parent_flow._maybe_handle_underage_manager_handoff(conv, "ნიკოლოზი")
    assert calls == []
    assert "ნომერ" in out
    assert conv.lead.name == "ნიკოლოზი"             # real name IS captured


# ===========================================================================
# End-to-end through parent_flow.handle (engine ON) — replays the transcript
# ===========================================================================


def test_transcript_end_to_end(engine_on, monkeypatch, camp_registration_open):
    """Replay the reported live transcript on the under-age path:
    „კი მომწერე" → asks name + phone (not „სახელი მივიღე");
    „მენეჯერის ნომერი მომწერე" → discloses the manager number.
    The deterministic handoff owns both turns; the LLM is never consulted."""
    monkeypatch.setattr(openai_service, "chat_with_tools", _boom)
    manager_number = admin_config_service.get_manager_phone()

    conv = _ua_conv("ua-e2e")

    out1 = parent_flow.handle(conv, "კი მომწერე")
    assert "სახელი" in out1 and "ნომერ" in out1
    assert "სახელი მივიღე" not in out1
    assert (conv.lead.name or "") == ""

    out2 = parent_flow.handle(conv, "მენეჯერის ნომერი მომწერე")
    assert manager_number in out2
    assert "სახელი მივიღე" not in out2
    assert (conv.lead.name or "") == ""
