"""Booking Date Parse + Lead Field Separation Patch — 2026-06-04.

Two live bugs:

  BUG 1 — Relative date „ხვალ" parsed as past date.
          User: „მოვიფიქრე კონსულტაცია და ხვალ მინდა 11 საათზე"
          Agent: „წარსულ თარიღზე კონსულტაციას ვერ ჩავნიშნავთ…".
          Wrong. „ხვალ" must resolve to today_tbilisi + 1 day; the
          backend should pre-resolve and the past-date guard must
          only fire when the resolved datetime is genuinely in the
          past.

  BUG 2 — When the user first asks about ADULT events for a sister,
          then switches to camp (PARENT), the CRM challenge column
          shows the ADULT phrase „ზრდასრულთა საღამოები". Wrong.
          PARENT challenge and ADULT event_interest must stay
          segment-separated.

PART 1 — Georgian relative date parsing helper:
  * „ხვალ 11 საათზე" → today + 1 day at 11:00
  * „ხვალ მინდა 11 საათზე" → today + 1 day at 11:00
  * „ხვალ 11-ზე" → today + 1 day at 11:00
  * „ზეგ 14:00" → today + 2 days at 14:00
  * „დღეს 20:00" → today at 20:00
  * „გუშინ 11 საათზე" → today − 1 day at 11:00 (true past)
  * „ხვალ" with no time → today + 1 day at 00:00
  * Plain message with no relative-day stem → None

PART 2 — `_build_context_message` surfaces:
  * `today_iso_tbilisi=YYYY-MM-DD` (always)
  * `now_iso_tbilisi=YYYY-MM-DDTHH:MM±04:00` (always)
  * `resolved_relative_datetime_iso=...` (only when user message
    contains a relative-day phrase)

PART 3 — `ParentToolExecutor._normalise_datetime_iso_from_message`:
  * Overrides a wrong LLM-supplied ISO when user message contains
    „ხვალ" / „ზეგ" / „დღეს" / „გუშინ".
  * Preserves the LLM's time-of-day choice; overrides day only.
  * Safe no-op when the message has no relative-day stem.

PART 4 — Past-date guard does not over-trigger:
  * `check_consultation_slot` with a relative-date-derived
    datetime in the FUTURE (e.g. „ხვალ 11 საათზე") must NOT come
    back with `reason=past_datetime`.

PART 5 — Lead field separation:
  * `_save_lead_info` REFUSES to write adult event vocabulary into
    `lead.challenge`. The field stays untouched, the result lists
    `challenge` in `invalid_fields`.
  * `maybe_capture_challenge_fallback` skips adult event vocab.
  * Lead dataclass keeps `challenge` and `event_interest` strictly
    separate across `model_dump` / `from_dict`.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.agent.llm import parent_llm_engine
from app.agent.llm.parent_llm_engine import (
    _build_context_message,
    maybe_capture_challenge_fallback,
)
from app.agent.services.timestamps import (
    resolve_relative_datetime,
)
from app.agent.tools import parent_tool_executor
from app.agent.tools.parent_tool_executor import (
    ParentToolExecutor,
    _looks_like_adult_event_interest,
)
from app.models.conversation import Conversation
from app.models.lead import Lead


TBILISI = ZoneInfo("Asia/Tbilisi")

# A stable Tbilisi "now" used across all relative-date tests. The day
# of the week (Thursday) is irrelevant — we only assert offsets.
FIXED_NOW = datetime(2026, 12, 14, 9, 0, 0, tzinfo=TBILISI)


# =========================================================================
# PART 1 — Georgian relative date parsing
# =========================================================================


def test_resolve_xval_with_hour_in_georgian():
    out = resolve_relative_datetime("ხვალ 11 საათზე", now=FIXED_NOW)
    assert out is not None
    assert out.date() == (FIXED_NOW.date() + timedelta(days=1))
    assert (out.hour, out.minute) == (11, 0)


def test_resolve_xval_minda_form():
    out = resolve_relative_datetime("ხვალ მინდა 11 საათზე", now=FIXED_NOW)
    assert out is not None
    assert out.date() == (FIXED_NOW.date() + timedelta(days=1))
    assert (out.hour, out.minute) == (11, 0)


def test_resolve_xval_locative_suffix_form():
    out = resolve_relative_datetime("ხვალ 11-ზე", now=FIXED_NOW)
    assert out is not None
    assert out.date() == (FIXED_NOW.date() + timedelta(days=1))
    assert (out.hour, out.minute) == (11, 0)


def test_resolve_zeg_with_hhmm():
    out = resolve_relative_datetime("ზეგ 14:00", now=FIXED_NOW)
    assert out is not None
    assert out.date() == (FIXED_NOW.date() + timedelta(days=2))
    assert (out.hour, out.minute) == (14, 0)


def test_resolve_dghes_with_hour():
    out = resolve_relative_datetime("დღეს 20:00", now=FIXED_NOW)
    assert out is not None
    assert out.date() == FIXED_NOW.date()
    assert (out.hour, out.minute) == (20, 0)


def test_resolve_gushin_returns_past_date():
    out = resolve_relative_datetime("გუშინ 11 საათზე", now=FIXED_NOW)
    assert out is not None
    assert out.date() == (FIXED_NOW.date() - timedelta(days=1))
    assert (out.hour, out.minute) == (11, 0)
    assert out < FIXED_NOW


def test_resolve_xval_without_time_uses_midnight():
    out = resolve_relative_datetime("ხვალ", now=FIXED_NOW)
    assert out is not None
    assert out.date() == (FIXED_NOW.date() + timedelta(days=1))
    assert (out.hour, out.minute) == (0, 0)


def test_resolve_no_relative_word_returns_none():
    assert resolve_relative_datetime("11 საათზე", now=FIXED_NOW) is None
    assert resolve_relative_datetime("მინდა კონსულტაცია", now=FIXED_NOW) is None
    assert resolve_relative_datetime("", now=FIXED_NOW) is None


def test_resolve_uses_tbilisi_when_now_omitted():
    # Smoke-test the default-now path (uses now_tbilisi()).
    out = resolve_relative_datetime("ხვალ")
    assert out is not None
    assert out.tzinfo is not None
    # Tbilisi is UTC+4 — assert offset present.
    assert out.utcoffset().total_seconds() == 4 * 3600


# =========================================================================
# PART 2 — _build_context_message surfaces today + resolved
# =========================================================================


def test_context_message_always_includes_today_iso(monkeypatch):
    monkeypatch.setattr(
        parent_llm_engine, "now_tbilisi", lambda: FIXED_NOW,
    )
    conv = Conversation(sender_id="s1", platform="instagram")
    lead = Lead(sender_id="s1", platform="instagram", segment="PARENT")
    out = _build_context_message(conv, lead, user_message="გამარჯობა")
    assert "today_iso_tbilisi=2026-12-14" in out
    assert "now_iso_tbilisi=2026-12-14T09:00+04:00" in out
    # No relative-day phrase in the user message — no resolved key.
    assert "resolved_relative_datetime_iso=" not in out


def test_context_message_surfaces_resolved_xval(monkeypatch):
    monkeypatch.setattr(
        parent_llm_engine, "now_tbilisi", lambda: FIXED_NOW,
    )
    conv = Conversation(sender_id="s1", platform="instagram")
    lead = Lead(sender_id="s1", platform="instagram", segment="PARENT")
    out = _build_context_message(
        conv, lead, user_message="ხვალ მინდა 11 საათზე",
    )
    assert "today_iso_tbilisi=2026-12-14" in out
    assert "resolved_relative_datetime_iso=2026-12-15T11:00+04:00" in out


def test_context_message_no_user_message_skips_resolution(monkeypatch):
    monkeypatch.setattr(
        parent_llm_engine, "now_tbilisi", lambda: FIXED_NOW,
    )
    conv = Conversation(sender_id="s1", platform="instagram")
    lead = Lead(sender_id="s1", platform="instagram", segment="PARENT")
    out = _build_context_message(conv, lead)
    assert "today_iso_tbilisi=2026-12-14" in out
    assert "resolved_relative_datetime_iso=" not in out


# =========================================================================
# PART 3 — Executor normalisation overrides wrong LLM date
# =========================================================================


def _make_executor(user_message: str) -> ParentToolExecutor:
    conv = Conversation(sender_id="s1", platform="instagram")
    lead = Lead(sender_id="s1", platform="instagram", segment="PARENT")
    return ParentToolExecutor(
        conversation=conv,
        lead=lead,
        sender_id="s1",
        platform="instagram",
        user_message=user_message,
    )


def test_normalise_overrides_when_llm_used_past_date(monkeypatch):
    """Live bug: user said „ხვალ 11 საათზე", LLM passed yesterday's
    date. The normaliser must replace the day with the resolved one
    while preserving the LLM's time."""
    monkeypatch.setattr(
        parent_tool_executor, "now_tbilisi", lambda: FIXED_NOW,
    )
    # Also patch the timestamps module — `resolve_relative_datetime`
    # reads now_tbilisi() from its own module.
    from app.agent.services import timestamps as _ts
    monkeypatch.setattr(_ts, "now_tbilisi", lambda: FIXED_NOW)
    exe = _make_executor("ხვალ მინდა 11 საათზე")
    # LLM hallucinated yesterday at 11:00.
    wrong_iso = "2026-12-13T11:00:00+04:00"
    normalised = exe._normalise_datetime_iso_from_message(wrong_iso)
    parsed = datetime.fromisoformat(normalised)
    assert parsed.date() == FIXED_NOW.date() + timedelta(days=1)
    assert parsed.hour == 11
    assert parsed.minute == 0


def test_normalise_keeps_matching_iso_untouched(monkeypatch):
    monkeypatch.setattr(
        parent_tool_executor, "now_tbilisi", lambda: FIXED_NOW,
    )
    # Also patch the timestamps module — `resolve_relative_datetime`
    # reads now_tbilisi() from its own module.
    from app.agent.services import timestamps as _ts
    monkeypatch.setattr(_ts, "now_tbilisi", lambda: FIXED_NOW)
    exe = _make_executor("ხვალ 11 საათზე")
    good_iso = "2026-12-15T11:00:00+04:00"
    normalised = exe._normalise_datetime_iso_from_message(good_iso)
    assert normalised == good_iso


def test_normalise_no_relative_word_keeps_iso(monkeypatch):
    monkeypatch.setattr(
        parent_tool_executor, "now_tbilisi", lambda: FIXED_NOW,
    )
    # Also patch the timestamps module — `resolve_relative_datetime`
    # reads now_tbilisi() from its own module.
    from app.agent.services import timestamps as _ts
    monkeypatch.setattr(_ts, "now_tbilisi", lambda: FIXED_NOW)
    exe = _make_executor("რა ფასი აქვს ბანაკს?")
    iso = "2026-07-15T12:00:00+04:00"
    assert exe._normalise_datetime_iso_from_message(iso) == iso


def test_normalise_empty_iso_safe():
    exe = _make_executor("ხვალ 11 საათზე")
    assert exe._normalise_datetime_iso_from_message("") == ""


def test_normalise_empty_message_safe():
    exe = _make_executor("")
    iso = "2026-07-15T12:00:00+04:00"
    assert exe._normalise_datetime_iso_from_message(iso) == iso


# =========================================================================
# PART 4 — Past-date guard does not over-trigger for relative dates
# =========================================================================


def test_check_consultation_slot_xval_does_not_say_past(monkeypatch):
    """End-to-end: when the user says „ხვალ 11 საათზე" and the LLM
    even passes a stale ISO, the executor's normaliser repairs it and
    the slot-check returns reason=calendar_busy or available — NEVER
    past_datetime."""
    import app.services.calendar_service as calendar_service

    monkeypatch.setattr(
        parent_tool_executor, "now_tbilisi", lambda: FIXED_NOW,
    )
    # Also patch the timestamps module — `resolve_relative_datetime`
    # reads now_tbilisi() from its own module.
    from app.agent.services import timestamps as _ts
    monkeypatch.setattr(_ts, "now_tbilisi", lambda: FIXED_NOW)
    # Calendar treats every slot as free for this test so we focus on
    # the past-date guard contract, not the busy logic.
    monkeypatch.setattr(
        calendar_service, "check_slot_calendar_only", lambda dt: True,
    )
    # Skip the alt-slots fallback — irrelevant here.
    monkeypatch.setattr(
        calendar_service, "get_free_slots", lambda **kw: [],
    )

    exe = _make_executor("ხვალ მინდა 11 საათზე")
    wrong_iso = "2026-12-13T11:00:00+04:00"  # LLM thinks it's past
    result = exe._check_consultation_slot({"datetime_iso": wrong_iso})
    assert result.get("reason") != "past_datetime"
    # And the slot itself is in the future.
    out_iso = result.get("datetime_iso", "")
    assert out_iso  # populated
    parsed = datetime.fromisoformat(out_iso)
    assert parsed >= FIXED_NOW


def test_book_consultation_xval_does_not_trigger_past_guard(monkeypatch):
    """The book path's `datetime_in_past` reason must NOT trigger for
    a relative-date-derived future datetime."""
    import app.flows.parent_flow as parent_flow
    import app.services.calendar_service as calendar_service

    monkeypatch.setattr(
        parent_tool_executor, "now_tbilisi", lambda: FIXED_NOW,
    )
    # Also patch the timestamps module — `resolve_relative_datetime`
    # reads now_tbilisi() from its own module.
    from app.agent.services import timestamps as _ts
    monkeypatch.setattr(_ts, "now_tbilisi", lambda: FIXED_NOW)
    monkeypatch.setattr(parent_flow, "TBILISI_TZ", TBILISI)
    # Approve the slot wholesale so we only check the past-guard
    # behaviour (not the booking write).
    monkeypatch.setattr(
        calendar_service, "check_slot_available", lambda dt: True,
    )
    monkeypatch.setattr(
        parent_flow, "_book_selected_slot",
        lambda *a, **kw: True,
    )

    conv = Conversation(sender_id="s1", platform="instagram")
    lead = Lead(
        sender_id="s1",
        platform="instagram",
        segment="PARENT",
        name="ნანა",
        phone="555111222",
        child_age="12",
    )
    exe = ParentToolExecutor(
        conversation=conv,
        lead=lead,
        sender_id="s1",
        platform="instagram",
        user_message="ხვალ მინდა 11 საათზე",
    )
    result = exe._book_consultation({
        "name": "ნანა",
        "phone": "555111222",
        "child_age": "12",
        "datetime_iso": "2026-12-13T11:00:00+04:00",  # stale LLM ISO
        "user_confirmed_datetime": True,
    })
    # Must NOT report `datetime_in_past` — relative-day normalisation
    # repaired the value before the past-time check.
    assert result.get("reason") != "datetime_in_past"


def test_check_consultation_slot_gushin_still_treated_as_past(monkeypatch):
    """Defense check: „გუშინ" IS past — the past-date branch must
    still fire."""
    import app.services.calendar_service as calendar_service

    monkeypatch.setattr(
        parent_tool_executor, "now_tbilisi", lambda: FIXED_NOW,
    )
    # Also patch the timestamps module — `resolve_relative_datetime`
    # reads now_tbilisi() from its own module.
    from app.agent.services import timestamps as _ts
    monkeypatch.setattr(_ts, "now_tbilisi", lambda: FIXED_NOW)
    monkeypatch.setattr(
        calendar_service, "check_slot_calendar_only", lambda dt: True,
    )
    monkeypatch.setattr(
        calendar_service, "get_free_slots", lambda **kw: [],
    )

    exe = _make_executor("გუშინ 11 საათზე")
    # The LLM-supplied datetime here is the truth (yesterday), so the
    # business-hours / past check chain in `_check_consultation_slot`
    # rejects it. We only assert it ISN'T treated as "today".
    yesterday_iso = "2026-12-13T11:00:00+04:00"
    result = exe._check_consultation_slot({"datetime_iso": yesterday_iso})
    out_iso = result.get("datetime_iso", "")
    parsed = datetime.fromisoformat(out_iso)
    assert parsed.date() == FIXED_NOW.date() - timedelta(days=1)


# =========================================================================
# PART 5 — Lead Field Separation: PARENT challenge ≠ ADULT event_interest
# =========================================================================


def test_save_lead_info_refuses_adult_event_text():
    """The PARENT save_lead_info must REFUSE to store adult-event
    vocabulary in `lead.challenge`. The CRM column stays clean."""
    conv = Conversation(sender_id="s1", platform="instagram", segment="PARENT")
    lead = Lead(sender_id="s1", platform="instagram", segment="PARENT")
    exe = ParentToolExecutor(
        conversation=conv, lead=lead, sender_id="s1", platform="instagram",
    )
    result = exe._save_lead_info({"challenge": "ზრდასრულთა საღამოები"})
    assert result["success"] is True
    assert lead.challenge == ""  # NOT polluted
    assert "challenge" not in result.get("saved_fields", [])
    assert "challenge" in result.get("invalid_fields", [])


def test_save_lead_info_accepts_legitimate_parent_challenge():
    """A genuine PARENT challenge — e.g. „ახალი გარემო და
    განვითარება" — must still be stored."""
    conv = Conversation(sender_id="s1", platform="instagram", segment="PARENT")
    lead = Lead(sender_id="s1", platform="instagram", segment="PARENT")
    exe = ParentToolExecutor(
        conversation=conv, lead=lead, sender_id="s1", platform="instagram",
    )
    result = exe._save_lead_info({"challenge": "ახალი გარემო და განვითარება"})
    assert result["success"] is True
    assert lead.challenge == "ახალი გარემო და განვითარება"
    assert "challenge" in result.get("saved_fields", [])


def test_save_lead_info_refuses_adult_text_in_notes():
    conv = Conversation(sender_id="s1", platform="instagram", segment="PARENT")
    lead = Lead(sender_id="s1", platform="instagram", segment="PARENT")
    exe = ParentToolExecutor(
        conversation=conv, lead=lead, sender_id="s1", platform="instagram",
    )
    result = exe._save_lead_info({"notes": "კულტურული საღამო მაინტერესებს"})
    assert lead.challenge == ""
    assert "notes" in result.get("invalid_fields", [])


def test_save_lead_info_does_not_set_event_interest_field():
    """Defence in depth — even when a parent volunteers a challenge
    payload, event_interest must stay empty (ADULT executor owns it)."""
    conv = Conversation(sender_id="s1", platform="instagram", segment="PARENT")
    lead = Lead(
        sender_id="s1", platform="instagram", segment="PARENT",
        event_interest="ზრდასრულთა საღამოები",  # set earlier in ADULT
    )
    exe = ParentToolExecutor(
        conversation=conv, lead=lead, sender_id="s1", platform="instagram",
    )
    result = exe._save_lead_info({"challenge": "ეკრანისგან დისტანცია"})
    # ADULT event_interest preserved, PARENT challenge stored separately.
    assert lead.event_interest == "ზრდასრულთა საღამოები"
    assert lead.challenge == "ეკრანისგან დისტანცია"


def test_challenge_fallback_skips_adult_event_text():
    lead = Lead(sender_id="s1", platform="instagram", segment="PARENT")
    maybe_capture_challenge_fallback(
        lead, "ზრდასრულთა საღამოები მაინტერესებს",
    )
    assert lead.challenge == ""


def test_challenge_fallback_skips_kulturuli_saghamo():
    lead = Lead(sender_id="s1", platform="instagram", segment="PARENT")
    maybe_capture_challenge_fallback(
        lead, "კულტურული საღამო მინდა მე და დის თვის",
    )
    assert lead.challenge == ""


def test_challenge_fallback_accepts_camp_phrase():
    """Regression — a real camp challenge phrase must still be
    captured by the fallback."""
    lead = Lead(sender_id="s1", platform="instagram", segment="PARENT")
    maybe_capture_challenge_fallback(
        lead, "ეკრანისგან დისტანცია მჭირდება ჩემი ბავშვისთვის",
    )
    assert lead.challenge != ""
    assert "ეკრან" in lead.challenge


def test_looks_like_adult_event_interest_helper():
    assert _looks_like_adult_event_interest("ზრდასრულთა საღამოები") is True
    assert _looks_like_adult_event_interest("კულტურული საღამო") is True
    assert _looks_like_adult_event_interest("პოეზიის საღამო") is True
    assert _looks_like_adult_event_interest("ღონისძიება მაინტერესებს") is True
    assert _looks_like_adult_event_interest("ბილეთი მინდა") is True
    assert _looks_like_adult_event_interest("ეკრანისგან დისტანცია") is False
    assert _looks_like_adult_event_interest("ახალი გარემო") is False
    assert _looks_like_adult_event_interest("") is False


def test_lead_dict_roundtrip_preserves_field_separation():
    """Lead.to_dict/from_dict round-trip — both fields stay separate."""
    lead = Lead(
        sender_id="s1",
        platform="instagram",
        segment="PARENT",
        challenge="ეკრანისგან დისტანცია",
        event_interest="ზრდასრულთა საღამოები",
    )
    payload = lead.model_dump(mode="json")
    assert payload["challenge"] == "ეკრანისგან დისტანცია"
    assert payload["event_interest"] == "ზრდასრულთა საღამოები"
    restored = Lead.from_dict(payload)
    assert restored.challenge == "ეკრანისგან დისტანცია"
    assert restored.event_interest == "ზრდასრულთა საღამოები"


def test_segment_switch_preserves_existing_challenge_and_event_interest():
    """When PARENT → ADULT → PARENT switches happen, lead.challenge
    and lead.event_interest stay independent. switch_to_adult_flow
    does not touch lead.challenge; switch_to_parent_flow does not
    clear lead.event_interest."""
    from app.agent.tools.adult_tool_executor import AdultToolExecutor

    conv = Conversation(sender_id="s1", platform="instagram", segment="PARENT")
    lead = Lead(
        sender_id="s1",
        platform="instagram",
        segment="PARENT",
        challenge="ეკრანისგან დისტანცია",  # PARENT challenge already set
    )
    # PARENT → ADULT.
    p_exe = ParentToolExecutor(
        conversation=conv, lead=lead, sender_id="s1", platform="instagram",
    )
    p_exe._switch_to_adult_flow({})
    assert lead.challenge == "ეკრანისგან დისტანცია"
    # ADULT executor saves an adult event interest.
    a_exe = AdultToolExecutor(
        conversation=conv, lead=lead, sender_id="s1", platform="instagram",
    )
    a_exe._save_adult_lead_info({"event_interest": "ზრდასრულთა საღამოები"})
    assert lead.event_interest == "ზრდასრულთა საღამოები"
    assert lead.challenge == "ეკრანისგან დისტანცია"  # untouched
    # ADULT → PARENT.
    a_exe._switch_to_parent_flow({})
    # Both preserved.
    assert lead.event_interest == "ზრდასრულთა საღამოები"
    assert lead.challenge == "ეკრანისგან დისტანცია"
