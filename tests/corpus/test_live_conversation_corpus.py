"""Real-conversation REGRESSION CORPUS — built from live Messenger bugs that
are ALREADY FIXED. Each test is a deterministic, OFFLINE guard that the fix
stays fixed forever. A failure here = an unfixed regression to REPORT (not to
fix in this task).

Offline contract (NO external calls):
  * No OpenAI — `openai_service.chat_with_tools` is monkeypatched to RAISE
    wherever `parent_flow.handle` is driven (so reaching the LLM fails loudly).
  * No real Calendar — `parent_flow._book_selected_slot` /
    `calendar_service.check_slot_available` are stubbed.
  * No real Sheets / email / Meta — only the in-memory `Lead.to_sheet_row`
    serializer is exercised; `messenger_service.get_user_profile` is stubbed.

Assertions are on deterministic STATE / FIELDS / TOOL DECISIONS, plus the two
allowed wording checks: (a) a forbidden phrase must be ABSENT, (b) a
deterministic code-owned template marker that existing tests already assert
(„ნომერი მივიღე", „რამდენი წლისაა"). No free-LLM wording is asserted.

Pattern reused from tests/test_parent_contact_collection_livebug.py and
tests/test_parent_contact_booking_and_challenge_cleanup.py.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta

import pytest

from app import config as config_module
from app.agent.llm.parent_llm_engine import (
    maybe_capture_challenge_fallback,
    maybe_capture_child_age_fallback,
    sanitise_response_wording,
)
from app.agent.services.timestamps import extract_colloquial_hour
from app.agent.tools import parent_tool_executor
from app.flows import parent_flow
from app.flows.parent_flow import (
    TBILISI_TZ,
    _ensure_camp_age_question,
    _maybe_handle_contact_collection,
    _maybe_request_full_contact_on_intent,
    _parse_name_phone,
)
from app.flows.parent_turn_router import _parse_booking_datetime
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.services import calendar_service, messenger_service, openai_service


# -- offline helpers (mirroring the existing livebug + cleanup tests) -------


@pytest.fixture(autouse=True)
def _reset_executor_state():
    parent_tool_executor.reset_state()
    yield
    parent_tool_executor.reset_state()


# The bot's contact request carrying the brand markers that arm
# `_bot_recently_asked_for_contact` (see parent_flow._CONTACT_REQUEST_MARKERS).
_CONTACT_ASK_TURN = {
    "role": "assistant",
    "content": "მომწერეთ თქვენი სახელი და 9-ნიშნა საკონტაქტო ნომერი, "
               "რომ კონსულტაცია ჩავნიშნოთ.",
}


def _conv(history=None, **kwargs) -> Conversation:
    conv = Conversation(
        sender_id=kwargs.pop("sender_id", "corpus"),
        platform=kwargs.pop("platform", "instagram"),
    )
    conv.segment = kwargs.pop("segment", "PARENT")
    conv.state = kwargs.pop("state", "ASK_NAME")
    conv.last_activity = datetime.now(TBILISI_TZ).isoformat()
    if history is not None:
        conv.history = list(history)
    for key, value in kwargs.items():
        setattr(conv, key, value)
    return conv


def _lead(conv: Conversation, **kwargs) -> Lead:
    lead = Lead(sender_id=conv.sender_id, platform=conv.platform, segment="PARENT")
    for key, value in kwargs.items():
        setattr(lead, key, value)
    conv.lead = lead
    return lead


def _stale_iso(hour: int = 16, minute: int = 45) -> str:
    """A clearly past datetime (yesterday) — the live „16:45" shape."""
    d = datetime.now(TBILISI_TZ) - timedelta(days=1)
    return d.replace(hour=hour, minute=minute, second=0, microsecond=0).isoformat()


def _confirmed_pending(iso: str, **extra) -> dict:
    pending = {
        "requested_datetime_iso": iso,
        "requested_date_text": "ხვალ",
        "requested_time_text": "11:00",
        "user_confirmed_datetime": True,
        "source": "user_requested_exact_slot",
        "attempts": 0,
        "missing_fields": [],
    }
    pending.update(extra)
    return pending


def _install_fake_booking(monkeypatch) -> dict:
    """Stub the Calendar write; flips ``called`` True if a booking is
    attempted (used to assert NO booking happened)."""
    state = {"called": False, "booked_iso": ""}

    def _fake_book_selected_slot(conversation, lead, slot):
        state["called"] = True
        state["booked_iso"] = slot.get("datetime_iso", "")
        lead.calendly_booked = True
        lead.booked_datetime_iso = slot.get("datetime_iso", "")
        lead.calendar_event_id = "evt_corpus"
        lead.status = "Booked"
        conversation.state = "DONE"
        return True

    monkeypatch.setattr(parent_flow, "_book_selected_slot", _fake_book_selected_slot)
    monkeypatch.setattr(calendar_service, "check_slot_available", lambda *_a, **_k: True)
    return state


def _engine_on(monkeypatch) -> None:
    swapped = dataclasses.replace(
        config_module.settings, USE_PARENT_LLM_ENGINE=True,
    )
    monkeypatch.setattr(parent_flow, "settings", swapped)


def _block_external(monkeypatch) -> None:
    def _boom(*_a, **_k):  # pragma: no cover - must never be reached
        raise AssertionError("OpenAI must not be called in the corpus")
    monkeypatch.setattr(openai_service, "chat_with_tools", _boom)
    monkeypatch.setattr(messenger_service, "get_user_profile", lambda sid, plat: {})


# ===========================================================================
# CONV 1 — contact + stale time: contact saved, NO booking at a past datetime
# (turn 1 „კი ჩამწერე" is represented by the contact-collection + stale-pending
#  state below; turn 2 „ჯონი 595999733" is processed through handle()).
# ===========================================================================
def test_conv01_contact_plus_stale_time_no_past_booking(monkeypatch):
    _engine_on(monkeypatch)
    _block_external(monkeypatch)
    booking = _install_fake_booking(monkeypatch)

    conv = _conv(history=[_CONTACT_ASK_TURN])
    lead = _lead(conv, child_age="12")
    conv.pending_booking = _confirmed_pending(_stale_iso())  # stale 16:45

    reply = parent_flow.handle(conv, "ჯონი 595999733")

    assert lead.name == "ჯონი"
    assert lead.phone == "595999733"
    assert booking["called"] is False          # no Calendar book attempted
    assert lead.calendly_booked is False        # not booked at the stale time
    assert "16:45" not in (reply or "")


# ===========================================================================
# CONV 2 — month as name: name not overwritten with „ივნის"; date+time parsed
# ===========================================================================
def test_conv02_month_not_captured_as_name():
    msg = "595999733 16 ივნის მინდა 10 საათზე"

    parsed_name, parsed_phone = _parse_name_phone(msg)
    assert parsed_phone == "595999733"
    assert "ივნის" not in parsed_name
    assert parsed_name == ""  # no garbage name extracted

    iso = _parse_booking_datetime(msg)
    assert iso is not None
    dt = datetime.fromisoformat(iso)
    assert (dt.month, dt.day) == (6, 16)        # June 16
    assert (dt.hour, dt.minute) == (10, 0)      # 10:00

    # A known name must NOT be overwritten by this compound message.
    conv = _conv(history=[_CONTACT_ASK_TURN])
    lead = _lead(conv, name="ჯონი", phone="595999733", child_age="12")
    _maybe_handle_contact_collection(conv, msg)
    assert lead.name == "ჯონი"                  # still ჯონი, never „ივნის"


# ===========================================================================
# CONV 3 — age range echo: „9-17" not read as the child's age; deterministic
# age-ask path is taken (code-owned template marker, not an LLM string).
# ===========================================================================
def test_conv03_age_range_echo_not_captured():
    lead = Lead(sender_id="corpus", platform="instagram", segment="PARENT")
    maybe_capture_child_age_fallback(
        lead, "ბავშვების საზაფხულო ბანაკი 9-17", age_question_pending=False,
    )
    captured = (lead.child_age or "").strip()
    assert captured == ""            # NOT „9", NOT „17", nothing captured
    assert captured not in {"9", "17"}

    # Deterministic age-ask path: _ensure_camp_age_question appends the
    # code-owned age question (template marker, never an LLM free string).
    conv = _conv(state="START")
    conv.lead = lead
    out = _ensure_camp_age_question(
        conv, "ბავშვების საზაფხულო ბანაკი 9-17", "ბანაკი შესანიშნავი არჩევანია.",
    )
    assert "რამდენი წლისაა" in out


# ===========================================================================
# CONV 4 — challenge pollution: lead.challenge AND the serialized Sheet-row
# payload are both clean of the tacked-on factual question.
# ===========================================================================
def test_conv04_challenge_and_sheet_row_clean():
    lead = Lead(sender_id="corpus", platform="instagram", segment="PARENT")
    maybe_capture_challenge_fallback(
        lead,
        "ეკრანისგან დისტანცია, მეგობრები და ასევე მაინტერესებს როდის ტარდება?",
    )

    # Goals kept.
    assert "ეკრან" in lead.challenge
    assert "მეგობრ" in lead.challenge
    # Factual question stripped from the stored field.
    assert "როდის ტარდება" not in lead.challenge

    # The SERIALIZED Sheet-row payload (in-memory only) is also clean.
    row = lead.to_sheet_row("")
    serialized = " ".join(str(cell) for cell in row)
    assert "როდის ტარდება" not in serialized


# ===========================================================================
# CONV 5 — standalone phone (recent regression): captured, no re-ask loop.
# ===========================================================================
def test_conv05_standalone_phone_no_loop():
    conv = _conv(history=[_CONTACT_ASK_TURN])     # brand markers arm the capture
    lead = _lead(conv, name="ნინო", child_age="14")  # name already known

    reply = _maybe_handle_contact_collection(conv, "595999733")

    assert lead.phone == "595999733"
    assert reply is not None
    assert "ნომერი მივიღე" in reply               # deterministic ack template
    # No second „ask for phone" decision on a valid phone.
    assert "ნომერი სწორად ვერ ამოვიკითხე" not in reply
    assert "9-ნიშნა" not in reply


# ===========================================================================
# CONV 6 — reversed name+phone: both captured, NO booking attempt.
# ===========================================================================
def test_conv06_reversed_name_phone_no_booking(monkeypatch):
    booking = _install_fake_booking(monkeypatch)
    conv = _conv(history=[_CONTACT_ASK_TURN])
    lead = _lead(conv, child_age="14")            # name unknown until this turn

    reply = _maybe_handle_contact_collection(conv, "595999733 ლიზი")

    assert lead.name == "ლიზი"
    assert lead.phone == "595999733"
    assert booking["called"] is False             # no booking attempted
    assert _parse_booking_datetime("595999733 ლიზი") is None  # no datetime present
    assert "ძალიან ახლოს" not in (reply or "")    # never the booking/time wording


# ===========================================================================
# CONV 7 — age-announce ban: the response must NOT contain „თქვენი ასაკი"
# (forbidden-phrase assertion only).
# ===========================================================================
def test_conv07_age_announce_forbidden_phrase_absent(monkeypatch):
    _engine_on(monkeypatch)
    _block_external(monkeypatch)

    conv = _conv(history=[_CONTACT_ASK_TURN])
    _lead(conv, child_age="15")                   # CHILD's age known = 15

    reply = parent_flow.handle(conv, "კი მინდა")
    assert "თქვენი ასაკი" not in (reply or "")

    # Regression guard for the deterministic sanitizer that owns the ban:
    # an LLM-style age-announcing preamble is stripped.
    san = sanitise_response_wording(
        "თქვენი ასაკი უკვე ვიცი, 15 წლისაა. მომწერეთ ნომერი.",
    )
    assert "თქვენი ასაკი" not in san


# ===========================================================================
# CONV 8 — colloquial PM time: „7 საათზე" → 19:00.
# ===========================================================================
def test_conv08_colloquial_pm_time():
    result = extract_colloquial_hour("7 საათზე")
    assert result is not None
    assert result[0] == 19


# ===========================================================================
# CONV 9 — single age still works: „9 წლის" → child_age 9.
# ===========================================================================
def test_conv09_single_age_captured():
    lead = Lead(sender_id="corpus", platform="instagram", segment="PARENT")
    maybe_capture_child_age_fallback(lead, "9 წლის", age_question_pending=False)
    assert (lead.child_age or "").strip() == "9"
