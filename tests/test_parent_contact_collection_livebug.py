"""Live Bugfix (2026-06-12) — PARENT contact-collection capture.

Covers the live contact-capture bugs:

  * BUG 1 — a bare valid 9-digit phone „595999733" during contact
    collection must be SAVED deterministically (not dropped by the
    stochastic LLM, never looping „მომწერეთ ნომერი"). „595999733 ეს არის
    ნომერი" already worked — both forms must now behave the same.
  * BUG 2 — a reversed „595999733 ლიზი" (phone-first then name) must save
    name + phone and ask for a date/time — it must NOT route to the
    booking/time path („ეს დრო ძალიან ახლოსაა…").

All deterministic; no OpenAI / network.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta

import pytest

from app import config as config_module
from app.flows import parent_flow
from app.flows.parent_flow import (
    TBILISI_TZ,
    _is_explicit_consultation_request,
    _maybe_handle_contact_collection,
    _maybe_request_full_contact_on_intent,
    _parse_name_phone,
    is_valid_person_name,
)
from app.models.conversation import Conversation
from app.models.lead import Lead


# -- helpers ---------------------------------------------------------------


def _conv(history=None, **kwargs) -> Conversation:
    conv = Conversation(
        sender_id=kwargs.pop("sender_id", "sender_contact"),
        platform=kwargs.pop("platform", "instagram"),
    )
    conv.segment = kwargs.pop("segment", "PARENT")
    conv.state = kwargs.pop("state", "ASK_NAME")
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


_CONTACT_ASK_TURN = {
    "role": "assistant",
    "content": "მომწერეთ თქვენი სახელი და 9-ნიშნა საკონტაქტო ნომერი, "
               "რომ კონსულტაცია ჩავნიშნოთ.",
}


def _future_weekday_iso(hour: int = 11) -> str:
    d = datetime.now(TBILISI_TZ) + timedelta(days=3)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d.replace(hour=hour, minute=0, second=0, microsecond=0).isoformat()


# ===========================================================================
# BUG 1 — bare phone capture
# ===========================================================================


def test_bug1_known_name_bare_phone_saves_and_asks_time():
    """Known name + bare „595999733" → saves phone, does NOT re-ask phone,
    asks for a time. No „სახელი უკვე ვიცი"."""
    conv = _conv(history=[_CONTACT_ASK_TURN])
    lead = _lead(conv, name="ნინო", child_age="14")

    reply = _maybe_handle_contact_collection(conv, "595999733")

    assert lead.phone == "595999733"
    assert reply is not None
    assert "ნომერი მივიღე" in reply
    assert "დრო" in reply  # asks for a time, not the phone again
    assert "უკვე ვიცი" not in reply


def test_bug1_no_name_bare_phone_saves_and_asks_name():
    """No name + bare „595999733" → saves phone, asks for the name."""
    conv = _conv(history=[_CONTACT_ASK_TURN])
    lead = _lead(conv, child_age="14")  # name unknown

    reply = _maybe_handle_contact_collection(conv, "595999733")

    assert lead.phone == "595999733"
    assert reply is not None
    assert "ნომერი მივიღე" in reply
    assert "სახელი" in reply  # asks for the name
    assert "უკვე ვიცი" not in reply


def test_bug1_phone_plus_text_still_saves():
    """„595999733 ეს არის ნომერი" → still saves the phone (parity with the
    bare form)."""
    conv = _conv(history=[_CONTACT_ASK_TURN])
    lead = _lead(conv, name="ნინო", child_age="14")

    reply = _maybe_handle_contact_collection(conv, "595999733 ეს არის ნომერი")

    assert lead.phone == "595999733"
    assert reply is not None
    assert "ნომერი მივიღე" in reply


def test_bug1_repeated_phone_does_not_loop():
    """Phone already on file + same phone repeated → does NOT loop on the
    phone request; moves forward (asks for time when name known)."""
    conv = _conv(history=[_CONTACT_ASK_TURN])
    lead = _lead(conv, name="ნინო", phone="595999733", child_age="14")

    reply = _maybe_handle_contact_collection(conv, "595999733")

    assert lead.phone == "595999733"
    assert reply is not None
    assert "ნომერი სწორად ვერ ამოვიკითხე" not in reply
    assert "დრო" in reply


def test_bug1_too_long_phone_asks_for_valid():
    """Invalid too-long „555555555555555" in contact context → asks for a
    valid 9-digit phone, does NOT save a rescued window."""
    conv = _conv(history=[_CONTACT_ASK_TURN])
    lead = _lead(conv, name="ნინო", child_age="14")

    reply = _maybe_handle_contact_collection(conv, "555555555555555")

    assert reply is not None
    # Client wording (2026-07-03): asks for a contact number, never „9-ნიშნა".
    assert "საკონტაქტო ნომერი" in reply
    assert "9-ნიშნა" not in reply
    assert not (lead.phone or "")


def test_bug1_separated_phone_formats_save():
    """„595 999 733" / „595-999-733" parse to the clean phone."""
    for raw in ("595 999 733", "595-999-733"):
        conv = _conv(history=[_CONTACT_ASK_TURN])
        lead = _lead(conv, name="ნინო", child_age="14")
        reply = _maybe_handle_contact_collection(conv, raw)
        assert lead.phone == "595999733", raw
        assert reply is not None


def test_bug1_question_with_number_defers_to_engine():
    """A question that merely contains a number must NOT be hijacked."""
    conv = _conv(history=[_CONTACT_ASK_TURN])
    _lead(conv, name="ნინო", child_age="14")
    reply = _maybe_handle_contact_collection(conv, "595999733 როდის დარეკავთ?")
    assert reply is None


def test_bug1_existing_name_phone_parses_unchanged():
    """Regression: „ჯონი 595999733" / „ლიზი 595999733" still parse."""
    assert _parse_name_phone("ჯონი 595999733") == ("ჯონი", "595999733")
    assert _parse_name_phone("ლიზი 595999733") == ("ლიზი", "595999733")


# ===========================================================================
# BUG 2 — reversed phone + name, contact priority over booking/time
# ===========================================================================


@pytest.mark.parametrize("msg", [
    "595999733 ლიზი",
    "ლიზი 595999733",
    "595999733, ლიზი",
    "ლიზი, 595999733",
])
def test_bug2_name_phone_both_orders_save_no_booking(msg):
    """Reversed and normal „name phone" save both fields and ask for a
    date/time — never the booking/time rejection wording."""
    conv = _conv(history=[_CONTACT_ASK_TURN])
    lead = _lead(conv, child_age="14")  # name unknown until this message

    reply = _maybe_handle_contact_collection(conv, msg)

    assert lead.phone == "595999733", msg
    assert lead.name == "ლიზი", msg
    assert reply is not None
    assert "ლიზი" in reply
    assert "ძალიან ახლოს" not in reply
    assert "დაკავებული" not in reply
    assert "დრო" in reply  # asks preferred date/time


def test_bug2_contact_only_does_not_attempt_booking():
    """A contact-only message must not check slots / book a stale time —
    the deterministic handler answers it (no None fall-through to booking)."""
    conv = _conv(history=[_CONTACT_ASK_TURN])
    _lead(conv, child_age="14")
    reply = _maybe_handle_contact_collection(conv, "595999733 ლიზი")
    assert reply is not None
    assert "ძალიან ახლოს" not in reply


def test_bug2_contact_with_explicit_datetime_defers():
    """„ლიზი 595999733 16 ივნისი 10 საათზე" carries a datetime → the
    contact-only handler defers (lets the booking path parse the time)."""
    conv = _conv(history=[_CONTACT_ASK_TURN])
    _lead(conv, child_age="14")
    reply = _maybe_handle_contact_collection(
        conv, "ლიზი 595999733 16 ივნისი 10 საათზე",
    )
    assert reply is None  # defers — has an explicit booking datetime


def test_bug2_future_bookable_slot_defers_to_commit():
    """A genuinely future, bookable confirmed slot + bare phone → defers so
    the commit helper books that slot (not hijacked as contact-only)."""
    conv = _conv(history=[_CONTACT_ASK_TURN])
    _lead(conv, name="ნინო", child_age="14")
    conv.pending_booking = {
        "requested_datetime_iso": _future_weekday_iso(11),
        "user_confirmed_datetime": True,
        "missing_fields": [],
    }
    reply = _maybe_handle_contact_collection(conv, "595999733")
    assert reply is None  # future bookable slot — defer to commit/book


# ===========================================================================
# Integration — handle() routes a bare phone to the deterministic handler
# (engine flag on; OpenAI must NOT be called).
# ===========================================================================


def test_integration_handle_bare_phone_engine_path(monkeypatch):
    swapped = dataclasses.replace(
        config_module.settings, USE_PARENT_LLM_ENGINE=True,
    )
    monkeypatch.setattr(parent_flow, "settings", swapped)

    def _boom(*_a, **_k):  # pragma: no cover - must never be reached
        raise AssertionError("OpenAI must not be called for a bare phone")

    from app.services import openai_service
    monkeypatch.setattr(openai_service, "chat_with_tools", _boom)

    conv = _conv(history=[_CONTACT_ASK_TURN])
    _lead(conv, name="ნინო", child_age="14")
    conv.last_activity = datetime.now(TBILISI_TZ).isoformat()

    reply = parent_flow.handle(conv, "595999733")

    assert conv.lead.phone == "595999733"
    assert "ნომერი მივიღე" in reply
    assert "უკვე ვიცი" not in reply


# ===========================================================================
# BUG 3 — ban „I already know YOUR age / name / info" during contact collection
# ===========================================================================

from app.agent.llm.parent_llm_engine import sanitise_response_wording as _san

_PRIVACY = (
    "თქვენი ინფორმაცია გამოიყენება მხოლოდ კონსულტაციისთვის და "
    "საჯაროდ არ გამოქვეყნდება."
)


def test_bug3_age_announcing_preamble_stripped():
    """„თქვენი ასაკი უკვე ვიცი, 15 წლისაა." (15 = CHILD's age) must be
    stripped; the contact request survives."""
    msg = (
        "თქვენი ასაკი უკვე ვიცი, 15 წლისაა. მომწერეთ თქვენი სახელი და "
        "9-ნიშნა საკონტაქტო ნომერი, რომ კონსულტაცია ჩავნიშნოთ."
    )
    out = _san(msg)
    assert "თქვენი ასაკი უკვე ვიცი" not in out
    assert "15 წლისაა" not in out
    assert "მომწერეთ თქვენი სახელი და 9-ნიშნა საკონტაქტო ნომერი" in out


def test_bug3_name_announcing_preamble_stripped():
    """„თქვენი სახელი უკვე ვიცი. …" must be stripped."""
    msg = (
        "თქვენი სახელი უკვე ვიცი. მომწერეთ თქვენი 9-ნიშნა საკონტაქტო "
        "ნომერი, რომ კონსულტაცია ჩავნიშნოთ."
    )
    out = _san(msg)
    assert "თქვენი სახელი უკვე ვიცი" not in out
    assert "9-ნიშნა საკონტაქტო" in out


def test_bug3_info_announcing_preamble_stripped():
    msg = "თქვენი ინფორმაცია უკვე მაქვს. მომწერეთ 9-ნიშნა საკონტაქტო ნომერი."
    out = _san(msg)
    assert "თქვენი ინფორმაცია უკვე მაქვს" not in out
    assert "9-ნიშნა საკონტაქტო ნომერი" in out


def test_bug3_privacy_notice_survives():
    """Task 2 regression — the privacy notice has no „უკვე ვიცი/მაქვს" so it
    must pass through untouched."""
    assert _san(_PRIVACY) == _PRIVACY


def test_bug3_booking_confirmation_intact():
    msg = (
        "კონსულტაცია 16 ივნისს, 11:00 საათზე ჩაგინიშნეთ. მენეჯერი "
        "დაგიკავშირდებათ."
    )
    assert _san(msg) == msg


@pytest.mark.parametrize("msg", [
    # No „თქვენი" → legitimate, must be preserved.
    "სახელი უკვე ვიცი, რა არის ბავშვის ასაკი?",
    "ბავშვის ასაკი უკვე ვიცი, ხუთი წლის.",
    "სახელი უკვე მაქვს. მომწერეთ 9-ნიშნა საკონტაქტო ნომერი.",
])
def test_bug3_legitimate_no_thqveni_preserved(msg):
    assert _san(msg) == msg


def test_bug3_deterministic_contact_reply_has_no_banned_wording():
    """The deterministic contact-collection replies (BUG 1) never carry a
    banned announcing preamble."""
    conv = _conv(history=[_CONTACT_ASK_TURN])
    _lead(conv, child_age="15")  # child age known, name/phone missing

    reply = _maybe_handle_contact_collection(conv, "595999733")
    assert reply is not None
    for banned in (
        "თქვენი ასაკი უკვე ვიცი",
        "თქვენი სახელი უკვე ვიცი",
        "თქვენი ინფორმაცია უკვე მაქვს",
        "შეშფოთება",
    ):
        assert banned not in reply


# ===========================================================================
# BUG 4 — explicit consultation request → complete contact request
# ===========================================================================


def test_bug4_intent_no_name_asks_name_and_phone():
    """Eligible age, no name/phone + „კი მინდა" → asks for name AND phone."""
    conv = _conv()
    _lead(conv, child_age="14")  # eligible, no contact
    reply = _maybe_request_full_contact_on_intent(conv, "კი მინდა")
    assert reply is not None
    assert "სახელი" in reply
    assert "საკონტაქტო ნომერი" in reply
    assert "9-ნიშნა" not in reply
    assert "უკვე ვიცი" not in reply


def test_bug4_intent_name_known_phone_missing_asks_phone_only():
    """Eligible age, name validly known, phone missing + „კი მინდა" → asks
    phone only, without „სახელი უკვე ვიცი"."""
    conv = _conv()
    _lead(conv, name="ნინო", child_age="14")  # name known, phone missing
    reply = _maybe_request_full_contact_on_intent(conv, "კი მინდა")
    assert reply is not None
    assert "საკონტაქტო ნომერი" in reply
    assert "9-ნიშნა" not in reply
    assert "სახელი უკვე ვიცი" not in reply
    assert "თქვენი სახელი უკვე ვიცი" not in reply


def test_bug4_intent_contact_complete_defers():
    """Name + phone already known → defer (engine proceeds to slots)."""
    conv = _conv()
    _lead(conv, name="ნინო", phone="595999733", child_age="14")
    assert _maybe_request_full_contact_on_intent(conv, "კი მინდა") is None


def test_bug4_intent_unknown_age_defers():
    """Unknown child age → defer so the qualification flow asks the age."""
    conv = _conv()
    _lead(conv)  # age unknown
    assert _maybe_request_full_contact_on_intent(conv, "კი მინდა") is None


def test_bug4_intent_ineligible_age_defers():
    """Ineligible age → defer (ineligible-age guards own that turn)."""
    conv = _conv()
    _lead(conv, child_age="6")  # below camp minimum
    assert _maybe_request_full_contact_on_intent(conv, "კი მინდა") is None


def test_bug4_enrol_stem_no_name_asks_name_and_phone():
    conv = _conv()
    _lead(conv, child_age="14")
    reply = _maybe_request_full_contact_on_intent(conv, "ჩამწერეთ კონსულტაციაზე")
    assert reply is not None
    assert "სახელი" in reply and "საკონტაქტო ნომერი" in reply
    assert "9-ნიშნა" not in reply


def test_bug4_soft_browsing_message_not_treated_as_request():
    """„კი მინდა ვიცოდე ფასი" is browsing, not an enrol request."""
    assert _is_explicit_consultation_request("კი მინდა ვიცოდე ფასი") is False
    conv = _conv()
    _lead(conv, child_age="14")
    assert _maybe_request_full_contact_on_intent(
        conv, "კი მინდა ვიცოდე ფასი",
    ) is None


def test_bug4_bare_ki_is_not_explicit_request():
    """A bare „კი" must not be treated as an enrol request (it can confirm
    an offered slot)."""
    assert _is_explicit_consultation_request("კი") is False
    assert _is_explicit_consultation_request("დიახ") is False


def test_bug4_future_slot_pending_defers_to_booking():
    """„კი მინდა" with a future bookable slot pending → defer to the
    booking-confirmation path (no contact re-ask)."""
    conv = _conv()
    _lead(conv, name="ნინო", child_age="14")  # phone missing but slot pending
    conv.pending_booking = {
        "requested_datetime_iso": _future_weekday_iso(11),
        "user_confirmed_datetime": True,
        "missing_fields": ["phone"],
    }
    assert _maybe_request_full_contact_on_intent(conv, "კი მინდა") is None
