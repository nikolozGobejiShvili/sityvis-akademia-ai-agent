"""Booked State Memory Response Polish — regression tests.

Covers the patch (2026-05-30):

  * `sanitise_response_wording` rewrites "მყარი ჯავშანი" →
    "კონსულტაცია ჩანიშნულია" and "ეკრანსიგან" → "ეკრანისგან".
  * `_strip_consultation_cta_if_booked` removes new-booking CTAs for
    already-booked parents and appends the help CTA.
  * `_maybe_memory_info_reply` deterministically answers memory-info
    questions ("ჩემზე რა ინფორმაცია გაქვს?") with a structured Georgian
    summary, omits unknown fields, never leaks internal IDs, and never
    suggests another booking when the lead is booked.
  * The engine path in `parent_flow.handle()` wires the short-circuit
    BEFORE the LLM and the stripper AFTER, so the response a booked
    parent sees never contains a duplicate-booking CTA.

External services are fully mocked.
"""

from __future__ import annotations

import dataclasses

import pytest

import app.config as config_module
from app.agent.llm import parent_llm_engine
from app.agent.tools import parent_tool_executor
from app.flows import parent_flow, parent_turn_router
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.services import conversation_service


@pytest.fixture(autouse=True)
def reset_module_state():
    conversation_service.conversations.clear()
    parent_turn_router.manager_offer_shown.clear()
    parent_flow.available_slots.clear()
    parent_flow.ask_name_retries.clear()
    parent_flow.invalid_phone_retries.clear()
    parent_flow.slots_shown_for_state.clear()
    parent_tool_executor.reset_state()
    yield
    conversation_service.conversations.clear()
    parent_turn_router.manager_offer_shown.clear()
    parent_flow.available_slots.clear()
    parent_flow.ask_name_retries.clear()
    parent_flow.invalid_phone_retries.clear()
    parent_flow.slots_shown_for_state.clear()
    parent_tool_executor.reset_state()


def _swap_engine_flag(monkeypatch, value: bool) -> None:
    swapped = dataclasses.replace(
        config_module.settings, USE_PARENT_LLM_ENGINE=value,
    )
    monkeypatch.setattr(parent_flow, "settings", swapped)


def _future_booked_iso() -> str:
    """Return an ISO datetime safely in the future relative to "now"
    in Asia/Tbilisi.

    Tests that simulate an already-booked parent need an ISO whose
    moment hasn't passed — otherwise the Expired Booking Memory Fix
    helper (parent_flow._expire_past_booking_if_needed) correctly
    demotes the lead to "not currently booked" before the booked-state
    stripper / memory-info formatter sees it.

    Using a fixed string like ``2026-05-29T15:00:00+04:00`` rots the
    moment the wall-clock crosses it; a dynamically-computed +30d
    keeps these tests green regardless of when they run.
    """
    from datetime import datetime, timedelta

    from app.flows.parent_flow import TBILISI_TZ
    return (
        datetime.now(tz=TBILISI_TZ).replace(microsecond=0) + timedelta(days=30)
    ).isoformat()


def _make_booked_conversation(
    *,
    sender_id: str = "user_booked",
    child_age: str = "12",
    challenge: str = "ეკრანისგან დისტანცია",
    booked: bool = True,
    booked_dt_iso: str | None = None,
    name: str = "ნინო",
    phone: str = "595999733",
    state: str = "DONE",
    bot_replied: bool = True,
) -> Conversation:
    if booked_dt_iso is None:
        booked_dt_iso = _future_booked_iso()
    conv = Conversation(sender_id=sender_id, platform="instagram")
    conv.segment = "PARENT"
    conv.state = state
    lead = Lead(sender_id=sender_id, platform="instagram", segment="PARENT")
    lead.name = name
    lead.phone = phone
    lead.child_age = child_age
    lead.challenge = challenge
    lead.calendly_booked = booked
    if booked:
        lead.booked_datetime_iso = booked_dt_iso
    conv.lead = lead
    if bot_replied:
        # Past the static-welcome trigger so the engine path is the
        # one being exercised.
        conv.history = [
            {"role": "user", "content": "გამარჯობა"},
            {"role": "assistant", "content": "PARENT_WELCOME"},
        ]
    return conv


# =========================================================================
# PART 1 — sanitiser rewrites
# =========================================================================


def test_sanitiser_replaces_mqari_javshani():
    """"მყარი ჯავშანი გაქვთ 29 მაისს, 15:00 საათზე" →
    "კონსულტაცია ჩანიშნულია 29 მაისს, 15:00 საათზე"."""
    out = parent_llm_engine.sanitise_response_wording(
        "მყარი ჯავშანი გაქვთ 29 მაისს, 15:00 საათზე.",
    )
    assert "მყარი ჯავშანი" not in out
    assert "კონსულტაცია ჩანიშნულია" in out


def test_sanitiser_replaces_standalone_mqari_javshani():
    out = parent_llm_engine.sanitise_response_wording(
        "მყარი ჯავშანი დასტურდება ხვალ.",
    )
    assert "მყარი ჯავშანი" not in out
    assert "კონსულტაცია" in out


def test_sanitiser_fixes_ekransigan_typo():
    out = parent_llm_engine.sanitise_response_wording(
        "თქვენი შვილი ეკრანსიგან დისტანციის მიღებაა.",
    )
    assert "ეკრანსიგან" not in out
    assert "ეკრანისგან დისტანცია" in out


def test_sanitiser_fixes_ekransigan_anywhere():
    out = parent_llm_engine.sanitise_response_wording("ეკრანსიგან.")
    assert "ეკრანსიგან" not in out
    assert "ეკრანისგან" in out


def test_sanitiser_idempotent_on_clean_text():
    text = "კონსულტაცია ჩანიშნულია 29 მაისს, 15:00 საათზე."
    assert parent_llm_engine.sanitise_response_wording(text) == text


def test_full_live_response_polished_end_to_end():
    """The exact wording from the live observation should come out
    polished after `sanitise_response_wording` runs."""
    bad = (
        "თქვენი შვილის ასაკი 12 წელი და ინტერესი ეკრანსიგან დისტანციის "
        "მიღებაა. მყარი ჯავშანი გაქვთ 29 მაისს, 15:00 საათზე."
    )
    out = parent_llm_engine.sanitise_response_wording(bad)
    assert "ეკრანსიგან" not in out
    assert "მყარი ჯავშანი" not in out
    assert "ეკრანისგან დისტანცია" in out
    assert "კონსულტაცია ჩანიშნულია 29 მაისს, 15:00 საათზე." in out


# =========================================================================
# PART 2 — booked-state CTA stripper
# =========================================================================


def test_stripper_removes_new_booking_cta_for_booked_lead():
    # Live QA Session 8 Patch (2026-06-07) — auto-append of help CTA
    # removed. The stripped response no longer carries the trailing
    # „თუ დამატებითი კითხვა გაქვთ…" filler — operators preferred a
    # clean short reply.
    conv = _make_booked_conversation()
    raw = (
        "თქვენი ჯავშანი 29 მაისს, 15:00.\n\n"
        "თუ გნებავთ, კონსულტაციაზე ჩაგწერთ."
    )
    out = parent_flow._strip_consultation_cta_if_booked(conv, raw)
    assert "კონსულტაციაზე ჩაგწერთ" not in out
    # No replacement help CTA is added.
    assert "თუ დამატებითი კითხვა გაქვთ" not in out


def test_stripper_removes_long_form_cta_for_booked_lead():
    """The exact wording from the live observation: "თუ გინდათ,
    შემიძლია მენეჯერთან მოკლე კონსულტაციაზე ჩაგწეროთ." (first-person
    "I can sign you up").

    Live QA Session 8 Patch (2026-06-07): stripped clean — no help
    CTA filler appended.
    """
    conv = _make_booked_conversation()
    raw = "თუ გინდათ, შემიძლია მენეჯერთან მოკლე კონსულტაციაზე ჩაგწეროთ."
    out = parent_flow._strip_consultation_cta_if_booked(conv, raw)
    assert "კონსულტაციაზე ჩაგწეროთ" not in out
    assert "თუ დამატებითი კითხვა გაქვთ" not in out


def test_stripper_passes_through_unbooked_lead():
    """An unbooked parent must still be able to receive the
    consultation CTA — this stripper is opt-in via booked state."""
    conv = _make_booked_conversation(booked=False, booked_dt_iso="")
    raw = "თუ გნებავთ, კონსულტაციაზე ჩაგწერთ."
    out = parent_flow._strip_consultation_cta_if_booked(conv, raw)
    assert out == raw


def test_stripper_idempotent_when_no_cta_present():
    conv = _make_booked_conversation()
    raw = "კონსულტაცია ჩანიშნულია 29 მაისს, 15:00 საათზე."
    out = parent_flow._strip_consultation_cta_if_booked(conv, raw)
    assert out == raw


def test_stripper_removes_help_cta_along_with_new_booking_cta():
    # Live QA Session 8 Patch (2026-06-07) — the trailing „თუ
    # დამატებითი კითხვა გაქვთ…" filler is now also stripped from
    # booked-state responses. The stripper removes both the new-
    # booking CTA AND the help-CTA filler in one pass.
    conv = _make_booked_conversation()
    raw = (
        "კონსულტაცია ჩანიშნულია.\n\n"
        "თუ დამატებითი კითხვა გაქვთ, მომწერეთ და დაგეხმარებით.\n\n"
        "კონსულტაციაზე ჩაგწერთ."
    )
    out = parent_flow._strip_consultation_cta_if_booked(conv, raw)
    assert "თუ დამატებითი კითხვა გაქვთ" not in out
    assert "კონსულტაციაზე ჩაგწერთ" not in out
    assert "კონსულტაცია ჩანიშნულია" in out


def test_lead_is_booked_via_calendly_booked_flag():
    conv = _make_booked_conversation(booked=True, booked_dt_iso="")
    assert parent_flow._lead_is_booked(conv.lead) is True


def test_lead_is_booked_via_booked_datetime_iso():
    """Either signal is enough — `booked_datetime_iso` is the
    belt-and-braces signal when `calendly_booked` was cleared."""
    conv = _make_booked_conversation(booked=False)
    conv.lead.booked_datetime_iso = "2026-06-01T10:00:00+04:00"
    assert parent_flow._lead_is_booked(conv.lead) is True


def test_lead_is_not_booked_when_neither_signal_set():
    conv = _make_booked_conversation(booked=False, booked_dt_iso="")
    assert parent_flow._lead_is_booked(conv.lead) is False


# =========================================================================
# PART 3 — deterministic memory-info short-circuit
# =========================================================================


@pytest.mark.parametrize("trigger", [
    "ჩემზე რა ინფორმაცია გაქვს?",
    "რა ინფორმაცია გაქვს ჩემზე?",
    "რა გახსოვს ჩემზე?",
    "ჩემზე რა იცი?",
    "რა იცი ჩემზე?",
    "რა იცით ჩემზე?",
])
def test_memory_info_short_circuit_triggers_on_known_phrasings(trigger):
    conv = _make_booked_conversation()
    out = parent_flow._maybe_memory_info_reply(conv, trigger)
    assert out is not None
    assert "თქვენზე შენახული ინფორმაციაა" in out


def test_memory_info_short_circuit_returns_none_for_unrelated_question():
    conv = _make_booked_conversation()
    assert parent_flow._maybe_memory_info_reply(conv, "რა ღირს ბანაკი?") is None


def test_memory_info_includes_child_age_when_known():
    conv = _make_booked_conversation(child_age="12")
    out = parent_flow._maybe_memory_info_reply(conv, "ჩემზე რა ინფორმაცია გაქვს?")
    assert "შვილის ასაკი" in out
    assert "12" in out


def test_memory_info_includes_challenge_when_known():
    conv = _make_booked_conversation(challenge="ეკრანისგან დისტანცია")
    out = parent_flow._maybe_memory_info_reply(conv, "ჩემზე რა ინფორმაცია გაქვს?")
    assert "მთავარი ინტერესი" in out
    assert "ეკრანისგან დისტანცია" in out


def test_memory_info_includes_booked_datetime_in_georgian_format():
    """Verifies Georgian rendering "DD <ქართული თვე>, HH:MM" for an
    active (future) booking. Uses a fixed 2030 date so the Expired
    Booking Memory Fix (parent_flow._expire_past_booking_if_needed)
    leaves the lead booked and the formatter has something to render.
    """
    conv = _make_booked_conversation(booked_dt_iso="2030-05-29T15:00:00+04:00")
    out = parent_flow._maybe_memory_info_reply(conv, "ჩემზე რა ინფორმაცია გაქვს?")
    assert "კონსულტაცია" in out
    assert "29 მაისი" in out
    assert "15:00" in out


def test_memory_info_omits_unknown_fields():
    conv = _make_booked_conversation(
        child_age="", challenge="", booked=True, booked_dt_iso="",
    )
    out = parent_flow._maybe_memory_info_reply(conv, "ჩემზე რა ინფორმაცია გაქვს?")
    assert "შვილის ასაკი" not in out
    assert "მთავარი ინტერესი" not in out
    # Booking line uses fallback "ჩანიშნულია" when datetime parse failed
    # but booked flag was true.
    assert "კონსულტაცია: ჩანიშნულია" in out


def test_memory_info_empty_state_uses_friendly_fallback():
    """Lead exists but has nothing on record yet — must not produce
    an empty summary. (PART B, 2026-06-23: name + masked phone are now
    part of the summary, so the empty-state case clears them too.)"""
    conv = _make_booked_conversation(
        name="", phone="", child_age="", challenge="", booked=False,
        booked_dt_iso="",
    )
    out = parent_flow._maybe_memory_info_reply(conv, "რა გახსოვს ჩემზე?")
    assert "ბევრი ინფორმაცია არ მაქვს" in out
    # Still pleasant and offers help — no booking CTA.
    assert "კონსულტაციაზე ჩაგწერთ" not in out


def test_memory_info_does_not_expose_sender_id():
    """Privacy rule: never leak internal IDs in the memory-info reply."""
    sid = "psid_1234567890"
    conv = _make_booked_conversation(sender_id=sid)
    out = parent_flow._maybe_memory_info_reply(conv, "ჩემზე რა ინფორმაცია გაქვს?")
    assert sid not in out


def test_memory_info_does_not_expose_phone_number():
    """The phone is intentionally omitted — we should not echo back
    sensitive contact info on an unauthenticated channel even to the
    apparent owner."""
    conv = _make_booked_conversation(phone="595999733")
    out = parent_flow._maybe_memory_info_reply(conv, "ჩემზე რა ინფორმაცია გაქვს?")
    assert "595999733" not in out


def test_memory_info_does_not_include_platform_id():
    conv = _make_booked_conversation()
    out = parent_flow._maybe_memory_info_reply(conv, "ჩემზე რა ინფორმაცია გაქვს?")
    assert "instagram" not in out.lower()
    assert "platform" not in out.lower()


def test_memory_info_booked_response_uses_help_cta_not_booking_cta():
    conv = _make_booked_conversation()
    out = parent_flow._maybe_memory_info_reply(conv, "ჩემზე რა ინფორმაცია გაქვს?")
    # Booked → no new-booking offer.
    assert "კონსულტაციაზე ჩაგწერთ" not in out
    assert "მყარი ჯავშანი" not in out
    # Closing CTA points to "edit or ask".
    assert "შეცვლა გსურთ" in out or "დამატებითი კითხვა" in out


def test_memory_info_unbooked_response_uses_camp_help_cta():
    conv = _make_booked_conversation(booked=False, booked_dt_iso="")
    out = parent_flow._maybe_memory_info_reply(conv, "ჩემზე რა ინფორმაცია გაქვს?")
    assert "ბანაკთან დაკავშირებით კითხვა გაქვთ" in out
    assert "კონსულტაციაზე ჩაგწერთ" not in out


def test_memory_info_too_long_inbound_is_passed_through():
    """A long monologue that happens to contain a trigger stem is
    NOT short-circuited — discovery / objection turns should still
    reach the engine."""
    conv = _make_booked_conversation()
    long = "ჩემზე რა ინფორმაცია გაქვს — გავიგე ფასი მაგრამ ეჭვი მაქვს და მინდა ვიფიქრო ცოტა ხანი " * 3
    assert parent_flow._maybe_memory_info_reply(conv, long) is None


# =========================================================================
# PART 4 — engine path integration: short-circuit fires BEFORE LLM
# =========================================================================


def test_handle_memory_info_short_circuits_before_engine(monkeypatch):
    """When the inbound is a memory-info question, the engine must
    NEVER be called — we should not pay tokens just to summarise
    saved state."""
    _swap_engine_flag(monkeypatch, True)
    called = {"engine": 0}

    def fake_engine(*_a, **_k):
        called["engine"] += 1
        return "ENGINE_REPLY_SHOULD_NOT_FIRE"

    monkeypatch.setattr(parent_flow, "_run_llm_engine_safely", fake_engine)

    conv = _make_booked_conversation()
    response = parent_flow.handle(conv, "ჩემზე რა ინფორმაცია გაქვს?")
    assert called["engine"] == 0
    assert "თქვენზე შენახული ინფორმაციაა" in response
    assert "კონსულტაციაზე ჩაგწერთ" not in response
    assert "მყარი ჯავშანი" not in response


def test_handle_unrelated_question_still_reaches_engine(monkeypatch):
    _swap_engine_flag(monkeypatch, True)
    called = {"engine": 0}

    def fake_engine(*_a, **_k):
        called["engine"] += 1
        return "ENGINE_REPLY"

    monkeypatch.setattr(parent_flow, "_run_llm_engine_safely", fake_engine)

    conv = _make_booked_conversation()
    response = parent_flow.handle(conv, "რა ღირს ბანაკი?")
    assert called["engine"] == 1
    assert response == "ENGINE_REPLY"


def test_handle_engine_response_strips_booking_cta_for_booked_lead(monkeypatch):
    """If the engine STILL emits "კონსულტაციაზე ჩაგწერთ" for an
    already-booked parent (e.g. system prompt rule was not enough),
    the stripper catches it before the response goes out.

    Live QA Session 8 Patch (2026-06-07): the stripped response no
    longer carries the trailing help CTA filler.
    """
    _swap_engine_flag(monkeypatch, True)
    monkeypatch.setattr(
        parent_flow, "_run_llm_engine_safely",
        lambda conv, msg: "კონსულტაცია ჩანიშნულია.\n\nთუ გნებავთ, კონსულტაციაზე ჩაგწერთ.",
    )
    conv = _make_booked_conversation()
    response = parent_flow.handle(conv, "რა ხდება შემდეგ?")
    assert "კონსულტაციაზე ჩაგწერთ" not in response
    assert "თუ დამატებითი კითხვა გაქვთ" not in response
    assert "კონსულტაცია ჩანიშნულია" in response


def test_handle_engine_response_preserves_booking_cta_for_unbooked_lead(monkeypatch):
    _swap_engine_flag(monkeypatch, True)
    monkeypatch.setattr(
        parent_flow, "_run_llm_engine_safely",
        lambda conv, msg: "ეს გასაგებია. თუ გნებავთ, კონსულტაციაზე ჩაგწერთ.",
    )
    conv = _make_booked_conversation(booked=False, booked_dt_iso="")
    response = parent_flow.handle(conv, "კიდევ რას აკეთებენ ბავშვები?")
    # Unbooked → normal CTA preserved.
    assert "კონსულტაციაზე ჩაგწერთ" in response


def test_handle_greeting_does_not_restart_for_booked_user(monkeypatch):
    """Booked parent saying 'გამარჯობა' must not hit the static
    welcome menu. The conversation already has history past START,
    so `_maybe_static_welcome` returns None and the engine path
    runs — and any booking CTA the engine emits will be stripped."""
    _swap_engine_flag(monkeypatch, True)

    def fake_engine(*_a, **_k):
        # Pretend the engine produces a continuation rather than a
        # menu re-prompt.
        return "კონსულტაცია ჩანიშნულია. თუ რომელიმე დეტალის შეცვლა გსურთ, მომწერეთ."

    monkeypatch.setattr(parent_flow, "_run_llm_engine_safely", fake_engine)

    conv = _make_booked_conversation()
    response = parent_flow.handle(conv, "გამარჯობა")
    assert "PARENT_WELCOME" not in response
    assert "ბავშვების საზაფხულო ბანაკი" not in response  # static menu phrasing
    assert "კონსულტაცია ჩანიშნულია" in response


# =========================================================================
# PART 5 — memory-info short-circuit avoids external side effects
# =========================================================================


def test_memory_info_short_circuit_calls_no_external_services(monkeypatch):
    """Pure read — must not call LLM, Calendar, Sheets, email, or
    Meta send. Block every downstream side effect with a tripwire."""
    _swap_engine_flag(monkeypatch, True)

    tripped: list[str] = []

    def trip(name):
        def _inner(*_a, **_k):
            tripped.append(name)
            return None
        return _inner

    monkeypatch.setattr(parent_flow, "_run_llm_engine_safely", trip("engine"))
    from app.services import (
        calendar_service,
        messenger_service,
        notification_service,
        openai_service,
        sheets_service,
    )
    monkeypatch.setattr(openai_service, "chat_with_tools", trip("openai"))
    monkeypatch.setattr(calendar_service, "book_slot", trip("calendar"))
    monkeypatch.setattr(sheets_service, "create_lead", trip("sheets.create"))
    monkeypatch.setattr(sheets_service, "update_lead", trip("sheets.update"))
    monkeypatch.setattr(
        notification_service, "notify_manager", trip("notify"),
    )
    monkeypatch.setattr(messenger_service, "send_message", trip("send"))

    conv = _make_booked_conversation()
    response = parent_flow.handle(conv, "ჩემზე რა ინფორმაცია გაქვს?")
    assert "თქვენზე შენახული ინფორმაციაა" in response
    assert tripped == []  # nothing external called


# =========================================================================
# PART 6 — Georgian datetime formatter
# =========================================================================


def test_format_booked_datetime_short_georgian_valid():
    out = parent_flow._format_booked_datetime_short_georgian(
        "2026-05-29T15:00:00+04:00",
    )
    assert out == "29 მაისი, 15:00"


def test_format_booked_datetime_short_georgian_zulu():
    out = parent_flow._format_booked_datetime_short_georgian(
        "2026-06-01T10:00:00Z",
    )
    # Either Tbilisi-converted or raw UTC — the formatter does not
    # convert tz here, just renders. The day must still come out.
    assert "1" in out and ("ივნისი" in out)


def test_format_booked_datetime_short_georgian_bad_input():
    assert parent_flow._format_booked_datetime_short_georgian("") == ""
    assert parent_flow._format_booked_datetime_short_georgian("not-a-date") == ""
    assert parent_flow._format_booked_datetime_short_georgian(None) == ""  # type: ignore[arg-type]
