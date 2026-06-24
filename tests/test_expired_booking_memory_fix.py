"""Expired Booking Memory Fix — regression tests.

Covers:
  * Future booked_datetime_iso → active booking message allowed.
  * Past booked_datetime_iso → lead.calendly_booked flips to False,
    booked_datetime_iso cleared, memory-info reply does NOT mention
    the old date.
  * Memory-info reply with past booking → no "უკვე არის ჩანიშნული"
    wording; closes with the expired-memory line.
  * Memory-info reply with future booking → date still shown.
  * Memory-info reply with no booking at all → unchanged baseline
    behaviour.
  * Tbilisi-tz semantics: naive ISO strings are treated as local Tbilisi.
  * Malformed ISO → no crash, no mutation.
  * `_strip_consultation_cta_if_booked` ALSO refreshes expired memory
    so a fresh-booking CTA isn't scrubbed for a parent whose old
    booking is past.
  * Sanitiser: "მენეჯერთან გავარკვევთ" → "მენეჯერი დეტალებს დაგიზუსტებთ".
  * Sanitiser: past-date wording sanitiser remains intact.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.agent.llm import parent_llm_engine
from app.flows import parent_flow
from app.flows.parent_flow import (
    TBILISI_TZ,
    _expire_past_booking_if_needed,
    _lead_is_booked,
    _maybe_memory_info_reply,
    _strip_consultation_cta_if_booked,
)
from app.models.conversation import Conversation
from app.models.lead import Lead


def _now_tbilisi() -> datetime:
    return datetime.now(tz=TBILISI_TZ)


def _make_booked_conversation(booked_iso: str) -> Conversation:
    conv = Conversation(sender_id="exp-1", platform="instagram", segment="PARENT")
    lead = Lead(
        sender_id="exp-1",
        platform="instagram",
        segment="PARENT",
        name="ანა",
        phone="599123456",
        child_age="12",
        challenge="ეკრანისგან დისტანცია",
        calendly_booked=True,
        booked_datetime_iso=booked_iso,
        calendar_event_id="evt-xyz",
        status="Booked",
    )
    conv.lead = lead
    return conv


# =========================================================================
# 1 — Future booked_datetime_iso: active booking message allowed
# =========================================================================


def test_future_booking_not_expired():
    future = _now_tbilisi() + timedelta(days=7)
    lead = Lead(
        sender_id="s", platform="instagram", segment="PARENT",
        calendly_booked=True,
        booked_datetime_iso=future.isoformat(),
    )
    expired = _expire_past_booking_if_needed(lead)
    assert expired is False
    assert lead.calendly_booked is True
    assert lead.booked_datetime_iso == future.isoformat()
    assert _lead_is_booked(lead) is True


def test_future_booking_memory_reply_shows_date():
    future = _now_tbilisi() + timedelta(days=7)
    conv = _make_booked_conversation(future.isoformat())

    reply = _maybe_memory_info_reply(conv, "ჩემზე რა ინფორმაცია გაქვს?")
    assert reply is not None
    assert "კონსულტაცია" in reply
    # The future month/day should appear in the formatted date.
    assert str(future.day) in reply


# =========================================================================
# 2 — Past booked_datetime_iso: helper expires it
# =========================================================================


def test_past_booking_flips_calendly_booked_and_clears_iso():
    past = _now_tbilisi() - timedelta(days=5)
    lead = Lead(
        sender_id="s", platform="instagram", segment="PARENT",
        calendly_booked=True,
        booked_datetime_iso=past.isoformat(),
        calendar_event_id="evt-still-here",
        status="Booked",
    )
    expired = _expire_past_booking_if_needed(lead)
    assert expired is True
    assert lead.calendly_booked is False
    assert lead.booked_datetime_iso == ""
    # Intentional: do NOT clear calendar_event_id (existing
    # cancel/reschedule paths may need to look it up).
    assert lead.calendar_event_id == "evt-still-here"
    # Status preserved on the CRM record.
    assert lead.status == "Booked"
    # _lead_is_booked now returns False.
    assert _lead_is_booked(lead) is False


def test_past_booking_memory_reply_no_old_date_no_active_wording():
    past_iso = "2026-05-29T15:00:00"  # well before 2026-06-02
    conv = _make_booked_conversation(past_iso)

    reply = _maybe_memory_info_reply(conv, "ჩემზე რა ინფორმაცია გაქვს?")
    assert reply is not None

    # No old date echoed back.
    assert "29 მაისი" not in reply
    assert "15:00" not in reply

    # The patch spec's banned phrasings.
    assert "უკვე არის ჩანიშნული" not in reply
    assert "უკვე ჩანიშნულია" not in reply
    assert "გამოგიშლით" not in reply
    assert "კონსულტაცია ჩანიშნულია" not in reply

    # Spec-prescribed closing line is present.
    assert "კონსულტაციის აქტიური დრო ამ ეტაპზე არ ფიქსირდება" in reply
    # Door is open for new slots.
    assert "თავისუფალი დროები" in reply


def test_memory_reply_unbooked_with_no_data_uses_baseline():
    """When neither child_age nor challenge nor a booking are on file,
    the memory-info reply falls back to the friendly "nothing on
    record" line — unchanged from pre-patch behaviour.
    """
    conv = Conversation(sender_id="s", platform="instagram", segment="PARENT")
    conv.lead = Lead(sender_id="s", platform="instagram", segment="PARENT")
    reply = _maybe_memory_info_reply(conv, "ჩემზე რა ინფორმაცია გაქვს?")
    assert reply is not None
    assert "ბევრი ინფორმაცია არ მაქვს" in reply


# =========================================================================
# 3 — Tbilisi-tz semantics + parsing safety
# =========================================================================


def test_naive_iso_string_treated_as_tbilisi_local():
    """A naive ISO (no tz suffix) one minute in the future must NOT
    be expired."""
    soon = (_now_tbilisi() + timedelta(minutes=30)).replace(tzinfo=None)
    lead = Lead(
        sender_id="s", platform="instagram", segment="PARENT",
        calendly_booked=True,
        booked_datetime_iso=soon.isoformat(),
    )
    expired = _expire_past_booking_if_needed(lead)
    assert expired is False
    assert lead.calendly_booked is True


def test_tzaware_iso_string_normalised_correctly():
    """ISO with explicit Tbilisi offset still validates against current
    moment in Tbilisi."""
    future = (_now_tbilisi() + timedelta(days=1)).isoformat()
    lead = Lead(
        sender_id="s", platform="instagram", segment="PARENT",
        calendly_booked=True, booked_datetime_iso=future,
    )
    assert _expire_past_booking_if_needed(lead) is False


def test_malformed_iso_does_not_crash():
    lead = Lead(
        sender_id="s", platform="instagram", segment="PARENT",
        calendly_booked=True, booked_datetime_iso="not-a-real-iso",
    )
    expired = _expire_past_booking_if_needed(lead)
    assert expired is False
    # Lead is NOT mutated when parsing fails.
    assert lead.calendly_booked is True
    assert lead.booked_datetime_iso == "not-a-real-iso"


def test_helper_no_op_on_none_lead():
    assert _expire_past_booking_if_needed(None) is False


def test_helper_no_op_when_already_not_booked():
    lead = Lead(
        sender_id="s", platform="instagram", segment="PARENT",
        calendly_booked=False,
        booked_datetime_iso="2020-01-01T00:00:00",  # past but flag False
    )
    expired = _expire_past_booking_if_needed(lead)
    assert expired is False
    assert lead.calendly_booked is False


def test_helper_no_op_when_no_iso_stored():
    lead = Lead(
        sender_id="s", platform="instagram", segment="PARENT",
        calendly_booked=True,
        booked_datetime_iso="",
    )
    expired = _expire_past_booking_if_needed(lead)
    assert expired is False


# =========================================================================
# 4 — Booked-state CTA stripper also refreshes expired memory
# =========================================================================


def test_booked_cta_stripper_passes_through_when_expired():
    past_iso = "2026-05-29T15:00:00"
    conv = _make_booked_conversation(past_iso)

    # The LLM offered a fresh consultation CTA. For an expired lead,
    # this is LEGITIMATE wording — the stripper must NOT strip it.
    fresh_response = (
        "გასაგებია, ბანაკის შესახებ რას გაინტერესებთ?\n\n"
        "თუ გნებავთ, კონსულტაციაზე ჩაგწერთ."
    )
    out = _strip_consultation_cta_if_booked(conv, fresh_response)
    assert out == fresh_response
    # And the lead is now correctly not-booked.
    assert _lead_is_booked(conv.lead) is False


def test_booked_cta_stripper_still_strips_for_truly_booked_future_lead():
    """Regression — a future-booked lead must STILL get its new-booking
    CTA stripped. Without this, an LLM offer of a duplicate consultation
    would leak through.

    Live QA Session 8 Patch (2026-06-07): the help-CTA auto-append was
    removed. The stripped response is short and clean — no trailing
    „თუ დამატებითი კითხვა გაქვთ" filler.
    """
    future = _now_tbilisi() + timedelta(days=7)
    conv = _make_booked_conversation(future.isoformat())

    fresh_response = (
        "გასაგებია, თქვენი დეტალები მახსოვს.\n\n"
        "თუ გნებავთ, კონსულტაციაზე ჩაგწერთ."
    )
    out = _strip_consultation_cta_if_booked(conv, fresh_response)
    assert "თუ გნებავთ, კონსულტაციაზე ჩაგწერთ." not in out
    assert "თუ დამატებითი კითხვა გაქვთ" not in out
    assert "გასაგებია, თქვენი დეტალები მახსოვს" in out


# =========================================================================
# 5 — Sanitiser: sensitive-needs wording polish
# =========================================================================


def test_sanitiser_replaces_menejertan_gavarkvevt():
    bad = (
        "გასაგებია. ამ საკითხს მენეჯერთან გავარკვევთ. "
        "შემიძლია მენეჯერთან დაკავშირებაში დაგეხმაროთ."
    )
    out = parent_llm_engine.sanitise_response_wording(bad)
    assert "მენეჯერთან გავარკვევთ" not in out
    # The brand replacement is present.
    assert (
        "მენეჯერი დეტალებში დაგიზუსტებთ" in out
        or "მენეჯერი დეტალებს დაგიზუსტებთ" in out
    )


def test_sanitiser_idempotent_on_clean_sensitive_needs_response():
    clean = (
        "მადლობა, რომ დამიზუსტეთ. ასეთ შემთხვევაში ჯობს, დეტალები "
        "მენეჯერმა პირადად დაგიზუსტოთ, რადგან მნიშვნელოვანია ბავშვის "
        "საჭიროებები სწორად გავითვალისწინოთ. შემიძლია მენეჯერთან "
        "დაკავშირებაში დაგეხმაროთ."
    )
    out = parent_llm_engine.sanitise_response_wording(clean)
    # No banned phrase, no mutation of the brand stems.
    assert "მენეჯერთან გავარკვევთ" not in out
    # "მენეჯერ" stem still appears (declined into "მენეჯერმა" /
    # "მენეჯერთან" in the clean sample).
    assert "მენეჯერ" in out


# =========================================================================
# 6 — Past-date sanitiser (regression — must remain intact)
# =========================================================================


def test_sanitiser_still_rewrites_ukve_gasulia():
    bad = "ეს დრო უკვე გასულია."
    out = parent_llm_engine.sanitise_response_wording(bad)
    # The literal banned phrase is gone.
    assert "უკვე გასულია" not in out
    # The brand wording is the replacement.
    assert "წარსულ თარიღზე" in out or "წარსულია" in out


def test_sanitiser_does_not_introduce_am_dros_dajavshna_fallback():
    """The fake-booking guard's safe-fallback wording ("ამ დროის
    დაჯავშნა ვერ დავადასტურე") must NEVER be substituted by the
    sanitiser into a normal response. It is reserved for the
    fake-booking guard. The sanitiser table must not contain a rule
    that injects it.
    """
    sample = "თქვენი დრო თავისუფალია, დამიდასტურეთ და ჩავნიშნავ."
    out = parent_llm_engine.sanitise_response_wording(sample)
    assert "ამ დროის დაჯავშნა ვერ დავადასტურე" not in out
