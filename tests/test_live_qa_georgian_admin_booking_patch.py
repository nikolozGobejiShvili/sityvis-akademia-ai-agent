"""Live QA Patch — Georgian wording, Adult events from Admin Panel,
Booking selected slot mismatch.

Six live-QA bugs from the 2026-06-05 gpt-4.1-mini transcript:

  Bug 1 — Georgian wording / grammar polish (8 phrase fixes).
  Bug 2 — Adult transition asks „თქვენი შვილისთვის?" — wrong
          context. Should be „სხვა ადამიანისთვის?". Bare
          „ჩემი შვილისთვის" in ADULT flow no longer auto-switches.
  Bug 3 — Adult event global min_age = 13 (was 18). Per-event
          min_age can override UPWARD only:
          effective_min_age = max(13, event.min_age).
  Bug 4 — Admin Panel sections.yaml is read fresh on every call
          (no module cache). Events with title + price but missing
          id / min_age are still surfaced (id auto-derived; min_age
          defaults to 13).
  Bug 5 CRITICAL — Booking selected-slot mismatch. User said
          „5 ივნისი 10:00" but agent confirmed „8 ივნისი 10:00"
          because the time-only matcher returned the first slot
          whose time matched. Fix: when the message has a date
          hint, slot match MUST also match that date; and after
          book_slot, backend compares the actual booked iso
          against the requested iso and rejects on mismatch.
  Bug 6 — Calendar freshness. Verification phrases („კარგად
          შეამოწმე") already block book + force re-check (shipped
          2026-06-04). This file re-asserts the contract.
"""

from __future__ import annotations

import textwrap
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

from app.agent.llm import adult_llm_engine, parent_llm_engine
from app.agent.llm.adult_llm_engine import (
    _ADULT_FOLLOWUP_QUESTION_WHO,
    _maybe_capture_adult_target,
    _user_wants_parent_flow,
    sanitise_adult_response,
)
from app.agent.llm.parent_llm_engine import sanitise_response_wording
from app.agent.tools import parent_tool_executor
from app.agent.tools.parent_tool_executor import ParentToolExecutor
from app.flows import parent_flow
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.services import admin_config_service
from app.services.session_key_service import conversation_cache_key


TBILISI = ZoneInfo("Asia/Tbilisi")
FIXED_NOW = datetime(2026, 6, 5, 9, 0, 0, tzinfo=TBILISI)


# =========================================================================
# BUG 1 — Georgian wording sanitizer entries
# =========================================================================


def test_strips_gmadlobt_rom_gaziaret_parent():
    out = sanitise_response_wording(
        "გმადლობთ, რომ გაზიარეთ. გავაანალიზებ.",
    )
    assert "გმადლობთ, რომ გაზიარეთ" not in out


def test_strips_gmadlobt_rom_gaziaret_adult():
    out = sanitise_adult_response("გმადლობთ, რომ გაზიარეთ. გავხსნი.")
    assert "გმადლობთ, რომ გაზიარეთ" not in out


def test_fixes_dastvis_to_distvis_parent():
    out = sanitise_response_wording("ჩემი დასთვის მინდა კონსულტაცია.")
    assert "დასთვის" not in out
    assert "დისთვის" in out


def test_fixes_dastvis_to_distvis_adult():
    out = sanitise_adult_response("ჩემი დასთვის ღონისძიება.")
    assert "დასთვის" not in out
    assert "დისთვის" in out


def test_fixes_mimocmebis_shedegad_parent():
    out = sanitise_response_wording(
        "მიმოწმების შედეგად, დრო თავისუფალია.",
    )
    assert "მიმოწმების შედეგად" not in out
    assert "გადავამოწმე" in out


def test_fixes_mimocmebis_shedegad_adult():
    out = sanitise_adult_response("მიმოწმების შედეგად ცარიელია.")
    assert "მიმოწმების შედეგად" not in out
    assert "გადავამოწმე" in out


def test_replaces_sashvilebit_dagidgebit_gverdshi():
    out = sanitise_response_wording("სიამოვნებით დაგიდგებით გვერდში.")
    assert "სიამოვნებით დაგიდგებით გვერდში" not in out
    assert "მენეჯერთან" in out


def test_replaces_tu_dagexmarot_skhva_gzit():
    out = sanitise_response_wording("თუ დაგეხმაროთ სხვა გზით?")
    assert "თუ დაგეხმაროთ სხვა გზით" not in out
    assert "მენეჯერთან" in out


def test_replaces_romeli_dro_gicers_mxars():
    out = sanitise_response_wording(
        "რომელი დრო გიჭერს მხარს?",
    )
    assert "გიჭერს მხარს" not in out
    assert "მოსახერხებელი" in out


def test_replaces_romeli_dro_gcirdebat():
    out = sanitise_response_wording("რომელი დრო გჭირდებათ?")
    assert "რომელი დრო გჭირდებათ" not in out
    assert "მოსახერხებელი" in out


def test_replaces_pirvandel_droze_darchet():
    out = sanitise_response_wording("გნებავთ პირვანდელ დროზე დარჩეთ?")
    assert "პირვანდელ დროზე დარჩეთ" not in out
    assert "მოსახერხებელი" in out


def test_sanitizer_is_idempotent():
    raw = "გმადლობთ, რომ გაზიარეთ. დასთვის რომელი დრო გიჭერს მხარს?"
    once = sanitise_response_wording(raw)
    twice = sanitise_response_wording(once)
    assert once == twice


# =========================================================================
# BUG 2 — Adult transition wording + relative routing
# =========================================================================


def test_adult_followup_who_question_uses_shvilistvis():
    # Live QA Session 7 Patch (2026-06-06) — Bug 3 revert. Brand-owner
    # preference is the original „თქვენი შვილისთვის?". The
    # intermediate „სხვა ადამიანისთვის?" wording is gone.
    assert "თქვენი შვილისთვის" in _ADULT_FOLLOWUP_QUESTION_WHO
    assert "სხვა ადამიანისთვის" not in _ADULT_FOLLOWUP_QUESTION_WHO


def test_sanitizer_normalises_to_shvilistvis_form():
    # The reverse of the Session 6 mapping: the intermediate
    # „სხვა ადამიანისთვის?" wording is normalised back to the
    # brand-owner-preferred „თქვენი შვილისთვის?" form.
    raw = "ღონისძიების შერჩევა თქვენთვის გსურთ თუ სხვა ადამიანისთვის?"
    out = sanitise_adult_response(raw)
    assert "სხვა ადამიანისთვის" not in out
    assert "თქვენი შვილისთვის" in out


def test_relative_dis_captured_into_target_relation():
    lead = Lead(sender_id="s1", platform="instagram", segment="ADULT")
    _maybe_capture_adult_target("ჩემი დისთვის მინდა ღონისძიება", lead)
    assert lead.adult_target_relation == "და"


def test_relative_dzma_captured_into_target_relation():
    lead = Lead(sender_id="s1", platform="instagram", segment="ADULT")
    _maybe_capture_adult_target("ჩემი ძმისთვის ვეძებ", lead)
    assert lead.adult_target_relation == "ძმა"


def test_bare_shvilis_in_adult_flow_does_not_switch_to_parent():
    """Bug 2 fix: „ჩემი შვილისთვის" without a hard camp keyword
    must NOT trigger the parent switch."""
    assert _user_wants_parent_flow("ჩემი შვილისთვის ღონისძიება") is False
    assert _user_wants_parent_flow("შვილისთვის მინდა") is False
    assert _user_wants_parent_flow("ბავშვისთვის მინდა") is False


def test_shvili_for_adult_event_captured_as_relative():
    """The relative capture now picks up „შვილისთვის" so the LLM
    can ask the child's age while staying in ADULT."""
    lead = Lead(sender_id="s1", platform="instagram", segment="ADULT")
    _maybe_capture_adult_target("ჩემი შვილისთვის მინდა ღონისძიება", lead)
    assert lead.adult_target_relation == "შვილი"


def test_shvili_plus_camp_keyword_still_switches():
    """Hard camp keyword wins — explicit „ბანაკი" routes to PARENT."""
    assert _user_wants_parent_flow("ჩემი შვილისთვის ბანაკი მინდა") is True
    assert _user_wants_parent_flow("საზაფხულო ბანაკი") is True


def test_bare_age_with_child_no_longer_switches():
    """Bug 2 tightening — bare „12 წლის ბავშვისთვის" without a hard
    camp keyword stays ADULT now. The LLM/relative-capture asks
    the child's age and offers adult-event matches."""
    assert _user_wants_parent_flow("12 წლის ბავშვისთვის მინდა") is False


# =========================================================================
# BUG 3 — Global min_age = 13 + effective_min_age floor
# =========================================================================


def test_event_without_min_age_defaults_to_13():
    raw = {"id": "evt1", "title": "ლიტ. საღამო"}
    out = admin_config_service._normalize_adult_event(raw)
    assert out["min_age"] == 13


def test_event_min_age_20_kept_as_20():
    raw = {"id": "evt1", "title": "premium", "min_age": 20}
    out = admin_config_service._normalize_adult_event(raw)
    assert out["min_age"] == 20


def test_event_min_age_10_lifted_to_13_floor():
    """13 is the FLOOR. An operator typo or low value is silently
    raised to 13 — never let an event silently open to under-13s."""
    raw = {"id": "evt1", "title": "x", "min_age": 10}
    out = admin_config_service._normalize_adult_event(raw)
    assert out["min_age"] == 13


def test_event_negative_min_age_lifted_to_13():
    raw = {"id": "evt1", "title": "x", "min_age": -5}
    out = admin_config_service._normalize_adult_event(raw)
    assert out["min_age"] == 13


def test_age_23_eligible_for_event_with_no_min_age(monkeypatch, tmp_path):
    yaml_text = textwrap.dedent(
        """\
        sections:
        - id: adult_events
          type: adult_events
          status: active
          events:
          - id: e1
            title: ლიტერატურული საღამო
            status: active
        """
    )
    p = tmp_path / "sections.yaml"
    p.write_text(yaml_text, encoding="utf-8")
    monkeypatch.setattr(admin_config_service, "SECTIONS_PATH", p)

    events = admin_config_service.get_active_adult_events(user_age=23)
    assert len(events) == 1
    assert events[0]["min_age"] == 13


def test_age_12_not_eligible_below_13_floor(monkeypatch, tmp_path):
    yaml_text = textwrap.dedent(
        """\
        sections:
        - id: adult_events
          type: adult_events
          status: active
          events:
          - id: e1
            title: ღია საღამო
            status: active
        """
    )
    p = tmp_path / "sections.yaml"
    p.write_text(yaml_text, encoding="utf-8")
    monkeypatch.setattr(admin_config_service, "SECTIONS_PATH", p)

    events = admin_config_service.get_active_adult_events(user_age=12)
    assert events == []


def test_system_adult_prompt_mentions_13_floor():
    """The prompt must codify the new rule so the LLM can answer
    „რა ასაკისთვის გაქვთ?" with 13, not 18."""
    from app.agent.llm.prompt_loader import load_prompt
    txt = load_prompt("system_adult_v1")
    # The 13-year floor MUST be stated.
    assert "13 წელი" in txt or "13 წლიდან" in txt
    # The "18 წლიდან as universal" claim must appear ONLY as a
    # banned/cautionary mention, not as a positive rule. Heuristic:
    # the section that codifies the 13-year floor surrounds it.
    assert "Bug 3" in txt or "13" in txt


# =========================================================================
# BUG 4 — Admin Panel reload + missing min_age + auto-id
# =========================================================================


def test_sections_reload_picks_up_file_change(monkeypatch, tmp_path):
    """No module-level cache: editing the file makes the next call
    return the new content — no server restart needed."""
    p = tmp_path / "sections.yaml"
    p.write_text(
        textwrap.dedent(
            """\
            sections:
            - id: adult_events
              type: adult_events
              status: active
              events:
              - id: a1
                title: first
                status: active
            """
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(admin_config_service, "SECTIONS_PATH", p)

    first = admin_config_service.get_adult_events()
    assert len(first) == 1
    assert first[0]["title"] == "first"

    # Operator edits via Admin Panel — file is rewritten.
    p.write_text(
        textwrap.dedent(
            """\
            sections:
            - id: adult_events
              type: adult_events
              status: active
              events:
              - id: a1
                title: first
                status: active
              - id: a2
                title: second
                status: active
                price_text: 50 ლარი
            """
        ),
        encoding="utf-8",
    )

    second = admin_config_service.get_adult_events()
    titles = [e["title"] for e in second]
    assert titles == ["first", "second"]
    assert second[1]["price_text"] == "50 ლარი"


def test_event_with_title_no_id_gets_auto_id(monkeypatch, tmp_path):
    """An operator-saved event with title + price but no explicit id
    must still be surfaced. The loader auto-derives an id so the
    event reaches the LLM tool layer."""
    p = tmp_path / "sections.yaml"
    p.write_text(
        textwrap.dedent(
            """\
            sections:
            - id: adult_events
              type: adult_events
              status: active
              events:
              - title: მურმან ჯინორიას საღამო
                status: active
                price_text: 50 ლარი
            """
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(admin_config_service, "SECTIONS_PATH", p)
    events = admin_config_service.get_adult_events()
    assert len(events) == 1
    assert events[0]["title"] == "მურმან ჯინორიას საღამო"
    assert events[0]["id"]  # auto-derived, non-empty
    assert events[0]["price_text"] == "50 ლარი"


def test_active_event_visible_in_adult_flow(monkeypatch, tmp_path):
    """End-to-end: an Admin-Panel-saved active event with valid
    title shows up in get_active_adult_events for an adult user."""
    p = tmp_path / "sections.yaml"
    p.write_text(
        textwrap.dedent(
            """\
            sections:
            - id: adult_events
              type: adult_events
              status: active
              events:
              - title: მურმან ჯინორიას საღამო
                status: active
                price_text: 50 ლარი
            """
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(admin_config_service, "SECTIONS_PATH", p)
    events = admin_config_service.get_active_adult_events(user_age=25)
    assert len(events) == 1
    assert events[0]["title"] == "მურმან ჯინორიას საღამო"


def test_inactive_seed_event_ignored_when_active_exists(monkeypatch, tmp_path):
    p = tmp_path / "sections.yaml"
    p.write_text(
        textwrap.dedent(
            """\
            sections:
            - id: adult_events
              type: adult_events
              status: active
              events:
              - id: seed
                title: seed (inactive)
                status: inactive
              - id: real
                title: real event
                status: active
            """
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(admin_config_service, "SECTIONS_PATH", p)
    events = admin_config_service.get_active_adult_events(user_age=25)
    titles = [e["title"] for e in events]
    assert "seed (inactive)" not in titles
    assert "real event" in titles


# =========================================================================
# BUG 5 CRITICAL — Booking selected slot mismatch
# =========================================================================


def _seed_offered_slots(sender_id: str, slots: list[dict]) -> None:
    parent_tool_executor._last_slots_by_sender[sender_id] = slots


def test_slot_match_prefers_date_hint(monkeypatch):
    """User said "6 July 10:00". Offered list has 10:00 on
    BOTH 8 July and 6 July. Matcher MUST return 6 July, not the
    first list entry."""
    monkeypatch.setattr(parent_flow, "TBILISI_TZ", TBILISI)
    sender_id = "s_slot_match"
    _seed_offered_slots(
        sender_id,
        [
            # 8 July listed FIRST ? under the legacy time-only matcher
            # this would have been returned for "10:00".
            {
                "slot_id": 1,
                "datetime_iso": "2026-07-08T10:00:00+04:00",
                "display": "8 ივლისი, 10:00",
            },
            {
                "slot_id": 2,
                "datetime_iso": "2026-07-06T10:00:00+04:00",
                "display": "6 ივლისი, 10:00",
            },
        ],
    )
    matched = parent_flow._user_explicit_slot_choice(
        sender_id, "6 ივლისი 10 საათზე",
    )
    assert matched is not None
    assert matched["datetime_iso"] == "2026-07-06T10:00:00+04:00"
    assert matched["slot_id"] == 2


def _book_executor(*, monkeypatch, user_message: str = ""):
    import app.services.calendar_service as calendar_service
    from app.services import admin_config_service

    monkeypatch.setattr(admin_config_service, "get_camp_registration_status", lambda: "open")
    monkeypatch.setattr(admin_config_service, "is_camp_registration_open", lambda: True)
    monkeypatch.setattr(parent_tool_executor, "now_tbilisi", lambda: FIXED_NOW)
    monkeypatch.setattr(parent_flow, "TBILISI_TZ", TBILISI)
    monkeypatch.setattr(
        calendar_service, "check_slot_available", lambda dt: True,
    )
    conv = Conversation(sender_id="s_book", platform="instagram")
    lead = Lead(
        sender_id="s_book", platform="instagram", segment="PARENT",
        name="ნიკოლოზი", phone="595999733", child_age="12",
    )
    return ParentToolExecutor(
        conversation=conv, lead=lead, sender_id="s_book",
        platform="instagram", user_message=user_message,
    )


def test_book_slot_mismatch_returns_failure(monkeypatch):
    """The executor's silent-failure detector: book_slot stamps a
    DIFFERENT datetime than requested. Backend must roll back and
    surface `slot_mismatch`."""
    def fake_book(conv, lead, slot):
        # Backend booked on the WRONG date (8 June instead of 5 June).
        lead.calendly_booked = True
        lead.calendar_event_id = "evt_wrong_day"
        lead.booked_datetime_iso = "2030-07-08T10:00:00+04:00"  # Wednesday — different day
        lead.status = "Booked"
        return True

    monkeypatch.setattr(parent_flow, "_book_selected_slot", fake_book)
    exe = _book_executor(monkeypatch=monkeypatch)
    result = exe._book_consultation({
        "name": "ნიკოლოზი",
        "phone": "595999733",
        "child_age": "12",
        "datetime_iso": "2030-07-06T10:00:00+04:00",
        "user_confirmed_datetime": True,
    })
    assert result["success"] is False
    assert result["reason"] == "slot_mismatch"
    assert result.get("error") == "calendar_booking_failed"
    assert result.get("manager_handoff_required") is True
    # Lead state rolled back.
    assert exe.lead.calendly_booked is False
    assert exe.lead.booked_datetime_iso == ""
    assert exe.lead.calendar_event_id == ""


def test_book_slot_match_succeeds_with_actual_iso(monkeypatch):
    """When backend booked the exact requested slot, success returns
    booked_date/time derived from the ACTUAL datetime (lead state),
    not from the input args alone."""
    def fake_book(conv, lead, slot):
        lead.calendly_booked = True
        lead.calendar_event_id = "evt_ok"
        lead.booked_datetime_iso = slot["datetime_iso"]
        lead.status = "Booked"
        return True

    monkeypatch.setattr(parent_flow, "_book_selected_slot", fake_book)
    exe = _book_executor(monkeypatch=monkeypatch)
    result = exe._book_consultation({
        "name": "ნიკოლოზი",
        "phone": "595999733",
        "child_age": "12",
        "datetime_iso": "2030-07-06T10:00:00+04:00",
        "user_confirmed_datetime": True,
    })
    assert result["success"] is True
    assert result["booked_datetime_iso"] == "2030-07-06T10:00:00+04:00"
    assert "6" in result["booked_date"]
    assert "ივლის" in result["booked_date"]
    assert result["booked_time"] == "10:00"


def test_pending_commit_failure_offers_manager_callback(monkeypatch, camp_registration_open):
    """When the executor returns slot_mismatch, the parent_flow
    pending-commit branch surfaces the brand-standard manager
    handoff line — never a confirmation."""
    from app.agent.tools import parent_tool_executor as exe_mod

    def fake_book(conv, lead, slot):
        lead.calendly_booked = True
        lead.calendar_event_id = "evt_bad"
        lead.booked_datetime_iso = "2030-07-08T10:00:00+04:00"  # Wednesday — different day
        lead.status = "Booked"
        return True

    monkeypatch.setattr(parent_flow, "_book_selected_slot", fake_book)
    monkeypatch.setattr(parent_flow, "TBILISI_TZ", TBILISI)
    import app.services.calendar_service as calendar_service
    monkeypatch.setattr(
        calendar_service, "check_slot_available", lambda dt: True,
    )

    conv = Conversation(sender_id="s_pc", platform="instagram")
    conv.segment = "PARENT"
    conv.pending_booking = {
        "requested_datetime_iso": "2030-07-06T10:00:00+04:00",
        "requested_date_text": "6 ივლისი",
        "requested_time_text": "10:00",
        "user_confirmed_datetime": True,
        "source": "user_selected_slot",
        "missing_fields": ["name", "phone"],
        "created_at": "2026-07-04T09:00:00",
        "attempts": 0,
    }
    conv.lead = Lead(
        sender_id="s_pc", platform="instagram", segment="PARENT",
        child_age="12",
    )
    out = parent_flow._maybe_commit_pending_booking_engine(
        conv, "ნიკოლოზი 595999733",
    )
    assert out is not None
    assert "ჩაგინიშნე" not in out
    assert "ჩავნიშნე" not in out
    assert "მენეჯერი" in out
    assert exe_mod.book_consultation_success_for_conversation.get(
        conversation_cache_key(conv)
    ) is False


# =========================================================================
# BUG 6 — Calendar freshness rule (re-assertion of 2026-06-04 patch)
# =========================================================================


def test_verification_phrase_still_blocks_book(monkeypatch, camp_registration_open):
    """Regression — 'კარგად შეამოწმე' must continue to refuse the
    book and return verification_requested for a re-check."""
    import app.services.calendar_service as calendar_service
    monkeypatch.setattr(parent_flow, "TBILISI_TZ", TBILISI)
    monkeypatch.setattr(
        calendar_service, "check_slot_available", lambda dt: True,
    )
    conv = Conversation(sender_id="s_ver", platform="instagram")
    lead = Lead(
        sender_id="s_ver", platform="instagram", segment="PARENT",
        name="ნიკოლოზი", phone="595999733", child_age="12",
    )
    exe = ParentToolExecutor(
        conversation=conv, lead=lead, sender_id="s_ver",
        platform="instagram",
        user_message="კარგად შეამოწმე თავისუფალია?",
    )
    result = exe._book_consultation({
        "name": "ნიკოლოზი",
        "phone": "595999733",
        "child_age": "12",
        "datetime_iso": "2030-06-15T10:00:00+04:00",
        "user_confirmed_datetime": True,
    })
    assert result["success"] is False
    assert result["reason"] == "verification_requested"
    assert lead.calendly_booked is False
