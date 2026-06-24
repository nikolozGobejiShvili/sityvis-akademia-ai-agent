"""FULL Live QA Patch — 2026-06-05 (Session 6 follow-up).

12 live-QA bugs from the gpt-4.1-mini transcript:

  Bug 1  CRITICAL — Admin Panel adult_events not read by live agent.
                    (a) section-level fallback when events[] missing,
                    (b) minimal Admin Panel events[] editor,
                    (c) adult flow shows admin event,
                    (d) debug logging.
  Bug 2  — „კულტურული საღამოები რა არის?" must be answered first.
  Bug 3  — Adult target question stays „სხვა ადამიანისთვის?".
  Bug 4  — Adult-to-PARENT known child age clarification (no re-ask).
  Bug 5  — Adult/cultural event 13-year floor; per-event override up.
  Bug 6  — Manager handoff wording („კავშირით" / bare „დაგაკავშირებთ.").
  Bug 7  — Sibling discount only on explicit 2+ children trigger.
  Bug 8  — Name extraction ignores „კაი" / „კარგი" / „კი" / „დიახ".
  Bug 9  — Reschedule replacement with safe ordering (new → cancel old).
  Bug 10 — Redundant confirmation echo („X საათზე ჩამწერეთ კონსულტაცია").
  Bug 11 — Calendar re-check phrase expansion.
  Bug 12 — Booking-question wording polish (re-asserted).
"""

from __future__ import annotations

import textwrap
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.agent.llm import adult_llm_engine
from app.agent.llm.adult_llm_engine import (
    _ADULT_FOLLOWUP_QUESTION_WHO,
    _maybe_capture_adult_target,
    _user_wants_parent_flow,
)
from app.agent.llm.parent_llm_engine import (
    _build_context_message,
    sanitise_response_wording,
)
from app.agent.tools import parent_tool_executor
from app.agent.tools.parent_tool_executor import (
    ParentToolExecutor,
    _BOOKING_VERIFICATION_PHRASES,
    _user_requested_verification,
)
from app.flows import parent_flow
from app.flows.parent_flow import (
    _parse_name_phone,
    _strip_unwarranted_sibling_discount,
)
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.services import admin_config_service


TBILISI = ZoneInfo("Asia/Tbilisi")


# =========================================================================
# Bug 1A — section-level fallback event
# =========================================================================


def _write_sections(tmp_path, yaml_text: str, monkeypatch):
    p = tmp_path / "sections.yaml"
    p.write_text(yaml_text, encoding="utf-8")
    monkeypatch.setattr(admin_config_service, "SECTIONS_PATH", p)
    return p


def test_1a_fallback_event_from_section_metadata(monkeypatch, tmp_path):
    _write_sections(
        tmp_path,
        textwrap.dedent(
            """\
            sections:
            - id: adult_events
              name: ზრდასრულთა ღონისძიებები
              type: adult_events
              status: active
              age_min: 13
              location: ბორის პაიჭაძის სტადიონი
              price_text: '200'
              price_gel: 200
              payment_terms: https://example.com/reserve
              description_short: maroon 5 კონცერტი
              streams:
              - name: 23 ივნისი
                dates_text: დასაწყისი 19:00 საათზე
                status: active
            """
        ),
        monkeypatch,
    )
    events = admin_config_service.get_adult_events()
    assert len(events) == 1
    fb = events[0]
    assert fb["title"] == "maroon 5 კონცერტი"
    assert fb["price_text"] == "200"
    assert fb["location"] == "ბორის პაიჭაძის სტადიონი"
    assert fb["date_text"] == "23 ივნისი — დასაწყისი 19:00 საათზე"
    assert fb["min_age"] == 13
    assert fb["active"] is True
    assert fb["reservation_url"] == "https://example.com/reserve"


def test_1a_fallback_event_visible_to_age_21(monkeypatch, tmp_path):
    _write_sections(
        tmp_path,
        textwrap.dedent(
            """\
            sections:
            - id: adult_events
              type: adult_events
              status: active
              age_min: 13
              description_short: maroon 5 კონცერტი
              price_text: '200'
            """
        ),
        monkeypatch,
    )
    events = admin_config_service.get_active_adult_events(user_age=21)
    assert len(events) == 1
    assert events[0]["title"] == "maroon 5 კონცერტი"


def test_1a_fallback_event_min_age_floor(monkeypatch, tmp_path):
    _write_sections(
        tmp_path,
        textwrap.dedent(
            """\
            sections:
            - id: adult_events
              type: adult_events
              status: active
              age_min: 10
              description_short: test event
              price_text: '100'
            """
        ),
        monkeypatch,
    )
    events = admin_config_service.get_adult_events()
    assert events[0]["min_age"] == 13  # raised from 10 → 13


def test_1a_no_fallback_for_inactive_section(monkeypatch, tmp_path):
    _write_sections(
        tmp_path,
        textwrap.dedent(
            """\
            sections:
            - id: adult_events
              type: adult_events
              status: inactive
              description_short: hidden
              price_text: '100'
            """
        ),
        monkeypatch,
    )
    assert admin_config_service.get_adult_events() == []


def test_1a_no_fallback_when_events_list_present(monkeypatch, tmp_path):
    """If events[] has at least one valid entry, no fallback fires."""
    _write_sections(
        tmp_path,
        textwrap.dedent(
            """\
            sections:
            - id: adult_events
              type: adult_events
              status: active
              age_min: 13
              description_short: section-level filler
              price_text: '100'
              events:
              - id: real_one
                title: real event
                status: active
            """
        ),
        monkeypatch,
    )
    events = admin_config_service.get_adult_events()
    assert len(events) == 1
    assert events[0]["title"] == "real event"
    assert events[0]["id"] == "real_one"


# =========================================================================
# Bug 1B — Admin Panel events[] editor
# =========================================================================


def test_1b_save_adult_event_writes_to_events_list(monkeypatch, tmp_path):
    _write_sections(
        tmp_path,
        textwrap.dedent(
            """\
            sections:
            - id: adult_events
              name: ზრდასრულთა ღონისძიებები
              type: adult_events
              status: active
              age_min: 13
              hashtags: [ღონისძიება]
            """
        ),
        monkeypatch,
    )
    errors = admin_config_service.save_adult_event({
        "title": "Maroon 5 კონცერტი",
        "status": "active",
        "min_age": 13,
        "date_text": "23 ივნისი, 19:00",
        "location": "ბორის პაიჭაძის სტადიონი",
        "price_text": "200",
    })
    assert errors == []
    events = admin_config_service.get_adult_events()
    assert len(events) == 1
    assert events[0]["title"] == "Maroon 5 კონცერტი"
    assert events[0]["id"]  # auto-derived from title


def test_1b_section_metadata_preserved_after_event_save(monkeypatch, tmp_path):
    p = _write_sections(
        tmp_path,
        textwrap.dedent(
            """\
            sections:
            - id: adult_events
              name: ზრდასრულთა ღონისძიებები
              type: adult_events
              status: active
              age_min: 13
              hashtags: [ღონისძიება, საღამო]
              discovery_questions:
              - რომელი ღონისძიება გაინტერესებთ?
              description_short: pre-existing
              price_text: '300'
            """
        ),
        monkeypatch,
    )
    admin_config_service.save_adult_event({
        "title": "test event",
        "status": "active",
    })
    after = admin_config_service.get_section("adult_events")
    assert after["name"] == "ზრდასრულთა ღონისძიებები"
    assert after["hashtags"] == ["ღონისძიება", "საღამო"]
    assert after["discovery_questions"] == ["რომელი ღონისძიება გაინტერესებთ?"]
    assert after["description_short"] == "pre-existing"
    assert after["price_text"] == "300"


def test_1b_missing_min_age_defaults_to_13_on_save(monkeypatch, tmp_path):
    _write_sections(
        tmp_path,
        textwrap.dedent(
            """\
            sections:
            - id: adult_events
              type: adult_events
              status: active
              hashtags: []
            """
        ),
        monkeypatch,
    )
    errors = admin_config_service.save_adult_event({"title": "no age event"})
    assert errors == []
    events = admin_config_service.get_adult_events()
    assert events[0]["min_age"] == 13


def test_1b_delete_event_removes_it(monkeypatch, tmp_path):
    _write_sections(
        tmp_path,
        textwrap.dedent(
            """\
            sections:
            - id: adult_events
              type: adult_events
              status: active
              hashtags: []
            """
        ),
        monkeypatch,
    )
    admin_config_service.save_adult_event({
        "id": "e_keep",
        "title": "keep",
        "status": "active",
    })
    admin_config_service.save_adult_event({
        "id": "e_drop",
        "title": "drop",
        "status": "active",
    })
    assert len(admin_config_service.get_adult_events()) == 2
    ok = admin_config_service.delete_adult_event("e_drop")
    assert ok is True
    titles = [e["title"] for e in admin_config_service.get_adult_events()]
    assert titles == ["keep"]


def test_1b_multiple_events_supported(monkeypatch, tmp_path):
    _write_sections(
        tmp_path,
        textwrap.dedent(
            """\
            sections:
            - id: adult_events
              type: adult_events
              status: active
              hashtags: []
            """
        ),
        monkeypatch,
    )
    for title in ("first", "second", "third"):
        admin_config_service.save_adult_event(
            {"title": title, "status": "active"},
        )
    events = admin_config_service.get_active_adult_events(user_age=25)
    assert {e["title"] for e in events} == {"first", "second", "third"}


def test_1b_inactive_event_hidden(monkeypatch, tmp_path):
    _write_sections(
        tmp_path,
        textwrap.dedent(
            """\
            sections:
            - id: adult_events
              type: adult_events
              status: active
              hashtags: []
            """
        ),
        monkeypatch,
    )
    admin_config_service.save_adult_event(
        {"title": "active e", "status": "active"},
    )
    admin_config_service.save_adult_event(
        {"title": "hidden e", "status": "inactive"},
    )
    active = admin_config_service.get_active_adult_events(user_age=25)
    titles = [e["title"] for e in active]
    assert "active e" in titles
    assert "hidden e" not in titles


# =========================================================================
# Bug 2 — cultural evenings explanation prompt
# =========================================================================


def test_2_prompt_codifies_cultural_evenings_explanation():
    from app.agent.llm.prompt_loader import load_prompt
    txt = load_prompt("system_adult_v1")
    assert "კულტურული საღამოები რა არის" in txt
    assert "შეხვედრები/ღონისძიებები" in txt


# =========================================================================
# Bug 3 — adult target wording (re-assertion)
# =========================================================================


def test_3_followup_question_uses_shvilistvis():
    # Live QA Session 7 Patch (2026-06-06) — reverted to brand-owner-
    # preferred wording „თქვენი შვილისთვის?". Test renamed accordingly.
    assert "თქვენი შვილისთვის" in _ADULT_FOLLOWUP_QUESTION_WHO
    assert "სხვა ადამიანისთვის" not in _ADULT_FOLLOWUP_QUESTION_WHO


def test_3_bare_shvilistvis_does_not_switch_to_parent():
    assert _user_wants_parent_flow("ჩემი შვილისთვის მინდა") is False
    assert _user_wants_parent_flow("ბავშვისთვის მინდა") is False


def test_3_shvili_plus_camp_keyword_switches():
    assert _user_wants_parent_flow("ჩემი შვილისთვის ბანაკი") is True
    assert _user_wants_parent_flow("ბავშვის ბანაკი მინდა") is True
    assert _user_wants_parent_flow("საზაფხულო ბანაკი") is True


def test_3_shvili_captured_as_relative():
    lead = Lead(sender_id="s", platform="instagram", segment="ADULT")
    _maybe_capture_adult_target("ჩემი შვილისთვის მინდა", lead)
    assert lead.adult_target_relation == "შვილი"


# =========================================================================
# Bug 4 — adult-to-PARENT known child age clarification
# =========================================================================


def test_4_context_message_surfaces_adult_target_fields(monkeypatch):
    from app.agent.llm import parent_llm_engine
    fixed_now = datetime(2026, 6, 5, 9, 0, 0, tzinfo=TBILISI)
    monkeypatch.setattr(parent_llm_engine, "now_tbilisi", lambda: fixed_now)
    conv = Conversation(sender_id="s", platform="instagram")
    lead = Lead(
        sender_id="s", platform="instagram", segment="PARENT",
        adult_target_relation="შვილი",
        adult_target_age="21",
    )
    out = _build_context_message(conv, lead, user_message="ბანაკი")
    assert "adult_target_relation=შვილი" in out
    assert "adult_target_age=21" in out


def test_4_prompt_has_adult_to_parent_carryover_rule():
    from app.agent.llm.prompt_loader import load_prompt
    txt = load_prompt("system_parent_v2")
    assert "ADULT→PARENT გადასვლის წესი" in txt
    assert "adult_target_relation" in txt
    assert "adult_target_age" in txt


def test_4_lead_keeps_adult_target_separate_from_child_age():
    lead = Lead(
        sender_id="s", platform="instagram", segment="PARENT",
        child_age="",
        adult_target_relation="შვილი",
        adult_target_age="21",
    )
    # Sanity — fields are independent.
    assert lead.child_age == ""
    assert lead.adult_target_age == "21"


# =========================================================================
# Bug 5 — 13+ floor + per-event override
# =========================================================================


def test_5_event_min_age_floor_applied():
    out = admin_config_service._normalize_adult_event(
        {"id": "x", "title": "t", "min_age": 10},
    )
    assert out["min_age"] == 13


def test_5_event_min_age_20_kept():
    out = admin_config_service._normalize_adult_event(
        {"id": "x", "title": "t", "min_age": 20},
    )
    assert out["min_age"] == 20


def test_5_missing_min_age_defaults_to_13():
    out = admin_config_service._normalize_adult_event(
        {"id": "x", "title": "t"},
    )
    assert out["min_age"] == 13


def test_5_age_12_below_floor(monkeypatch, tmp_path):
    _write_sections(
        tmp_path,
        textwrap.dedent(
            """\
            sections:
            - id: adult_events
              type: adult_events
              status: active
              events:
              - id: e
                title: t
                status: active
            """
        ),
        monkeypatch,
    )
    assert admin_config_service.get_active_adult_events(user_age=12) == []


def test_5_prompt_codifies_13_floor():
    from app.agent.llm.prompt_loader import load_prompt
    txt = load_prompt("system_adult_v1")
    assert "13 წელი" in txt


# =========================================================================
# Bug 6 — manager handoff wording sanitizer
# =========================================================================


def test_6_strips_menejertan_kavshirit():
    out = sanitise_response_wording(
        "მენეჯერთან კავშირით უფრო დაწვრილებით შეგიძლიათ გაიგოთ.",
    )
    assert "მენეჯერთან კავშირით" not in out
    assert "მენეჯერთან" in out


def test_6_bare_dagakavshirebt_gets_menejer_noun():
    out = sanitise_response_wording("თუ გსურთ, დაგაკავშირებთ.")
    assert "თუ გსურთ, დაგაკავშირებთ მენეჯერთან." in out


def test_6_handoff_wording_idempotent():
    raw = "თუ გსურთ, დაგაკავშირებთ."
    once = sanitise_response_wording(raw)
    twice = sanitise_response_wording(once)
    assert once == twice


# =========================================================================
# Bug 7 — sibling discount guard
# =========================================================================


def _conv_with_history(messages: list[str]) -> Conversation:
    conv = Conversation(sender_id="s", platform="instagram", segment="PARENT")
    for msg in messages:
        conv.history.append({"role": "user", "content": msg})
    return conv


def test_7_strips_discount_for_brother_inquiry():
    conv = _conv_with_history(
        ["ჩემი ძმისთვის მინდა, რომელიც არის 17 წლის"],
    )
    response = (
        "გასაგებია. დედმამიშვილებისთვის მოქმედებს 10%-იანი ფასდაკლება. "
        "ბანაკი 17 წლის მოზარდისთვის შესაფერისია."
    )
    out = _strip_unwarranted_sibling_discount(conv, "", response)
    assert "დედმამიშვილებისთვის" not in out
    assert "10%" not in out


def test_7_strips_discount_for_sister_inquiry():
    conv = _conv_with_history(["ჩემი დისთვის მინდა"])
    response = "დედმამიშვილებისთვის მოქმედებს 10%-იანი ფასდაკლება."
    out = _strip_unwarranted_sibling_discount(conv, "", response)
    assert "დედმამიშვილებისთვის" not in out


def test_7_strips_discount_for_single_child():
    conv = _conv_with_history(["ჩემი შვილისთვის, 14 წლის"])
    response = (
        "კარგია, ბანაკი შესაფერისია. "
        "დედმამიშვილებისთვის მოქმედებს 10%-იანი ფასდაკლება."
    )
    out = _strip_unwarranted_sibling_discount(conv, "", response)
    assert "დედმამიშვილებისთვის" not in out


def test_7_keeps_discount_for_two_children():
    conv = _conv_with_history(["ჩემი ორი შვილი მინდა ბანაკში"])
    response = "დედმამიშვილებისთვის მოქმედებს 10%-იანი ფასდაკლება."
    out = _strip_unwarranted_sibling_discount(conv, "", response)
    assert "დედმამიშვილებისთვის" in out


def test_7_keeps_discount_on_user_question():
    conv = _conv_with_history([])
    response = "დედმამიშვილებისთვის მოქმედებს 10%-იანი ფასდაკლება."
    out = _strip_unwarranted_sibling_discount(
        conv, "ფასდაკლება გაქვთ?", response,
    )
    assert "დედმამიშვილებისთვის" in out


def test_7_keeps_discount_when_da_dzma_ertad():
    conv = _conv_with_history(["და-ძმა ერთად მოდიან"])
    response = "დედმამიშვილებისთვის მოქმედებს 10%-იანი ფასდაკლება."
    out = _strip_unwarranted_sibling_discount(conv, "", response)
    assert "დედმამიშვილებისთვის" in out


# =========================================================================
# Bug 8 — name extraction filler-word ignore
# =========================================================================


def test_8_kai_pridoni_extracts_pridoni():
    name, phone = _parse_name_phone("კაი ფრიდონი 595999733")
    assert phone == "595999733"
    assert name == "ფრიდონი"


def test_8_kargi_mariami_extracts_mariami():
    name, phone = _parse_name_phone("კარგი, მარიამი 598000000")
    assert phone == "598000000"
    assert name == "მარიამი"


def test_8_ki_nika_extracts_nika():
    name, phone = _parse_name_phone("კი ნიკა 597000000")
    assert phone == "597000000"
    assert name == "ნიკა"


def test_8_legacy_nikolozi_works():
    name, phone = _parse_name_phone("ნიკოლოზი 595999733")
    assert phone == "595999733"
    assert name == "ნიკოლოზი"


def test_8_phone_first_then_name():
    name, phone = _parse_name_phone("595999733 ფრიდონი")
    assert phone == "595999733"
    assert name == "ფრიდონი"


def test_8_only_filler_no_name():
    name, phone = _parse_name_phone("კი 595999733")
    assert phone == "595999733"
    assert name == ""


def test_8_dakhi_only_no_name():
    name, phone = _parse_name_phone("დიახ 595999733")
    assert phone == "595999733"
    assert name == ""


# =========================================================================
# Bug 9 — reschedule replacement with safe ordering
# =========================================================================


def _reschedule_executor(monkeypatch, *, lead: Lead, user_message: str = ""):
    import app.services.calendar_service as calendar_service
    monkeypatch.setattr(parent_flow, "TBILISI_TZ", TBILISI)
    monkeypatch.setattr(
        calendar_service, "check_slot_available", lambda dt: True,
    )
    conv = Conversation(sender_id="s_resch", platform="instagram")
    conv.state = "DONE"
    conv.lead = lead
    return ParentToolExecutor(
        conversation=conv, lead=lead, sender_id="s_resch",
        platform="instagram", user_message=user_message,
    )


def _booked_lead() -> Lead:
    return Lead(
        sender_id="s_resch", platform="instagram", segment="PARENT",
        name="ნიკოლოზი", phone="595999733", child_age="14",
        calendly_booked=True,
        booked_datetime_iso="2026-07-06T15:00:00+04:00",
        calendar_event_id="evt_old_123",
        status="Booked",
    )


def test_9_successful_reschedule_new_then_cancel_order(monkeypatch):
    """Verify: NEW Calendar event created BEFORE old is cancelled."""
    import app.services.calendar_service as calendar_service
    cancel_calls: list[str] = []
    monkeypatch.setattr(
        calendar_service, "cancel_calendar_event",
        lambda eid: cancel_calls.append(eid) or True,
    )

    booking_order: list[str] = []

    def fake_book(conv, lead, slot):
        booking_order.append("book")
        lead.calendly_booked = True
        lead.calendar_event_id = "evt_new_456"
        lead.booked_datetime_iso = slot["datetime_iso"]
        lead.status = "Booked"
        return True

    def cancel_wrap(eid):
        booking_order.append(f"cancel:{eid}")
        cancel_calls.append(eid)
        return True

    monkeypatch.setattr(parent_flow, "_book_selected_slot", fake_book)
    monkeypatch.setattr(
        calendar_service, "cancel_calendar_event", cancel_wrap,
    )
    monkeypatch.setattr(
        "app.services.sheets_service.update_lead",
        lambda sid, updates: True,
    )

    lead = _booked_lead()
    exe = _reschedule_executor(monkeypatch, lead=lead)
    result = exe._reschedule_booking(
        "evt_old_123",
        {
            "action": "reschedule",
            "new_datetime_iso": "2026-07-08T10:00:00+04:00",
        },
    )
    assert result["success"] is True
    assert result["action"] == "reschedule"
    assert result.get("old_cancel_failed") is False
    # ORDER guard: book must happen BEFORE cancel.
    assert booking_order == ["book", "cancel:evt_old_123"]
    assert lead.calendar_event_id == "evt_new_456"
    assert lead.booked_datetime_iso == "2026-07-08T10:00:00+04:00"


def test_9_new_booking_failure_preserves_old(monkeypatch):
    """If new booking fails, old MUST remain active and cancel NEVER fires."""
    import app.services.calendar_service as calendar_service
    cancel_calls: list[str] = []
    monkeypatch.setattr(
        calendar_service, "cancel_calendar_event",
        lambda eid: cancel_calls.append(eid) or True,
    )
    monkeypatch.setattr(
        parent_flow, "_book_selected_slot", lambda c, l, s: False,
    )

    lead = _booked_lead()
    exe = _reschedule_executor(monkeypatch, lead=lead)
    result = exe._reschedule_booking(
        "evt_old_123",
        {
            "action": "reschedule",
            "new_datetime_iso": "2026-07-08T10:00:00+04:00",
        },
    )
    assert result["success"] is False
    assert result["reason"] == "calendar_error"
    assert result.get("old_booking_preserved") is True
    # Old Calendar event was never cancelled.
    assert cancel_calls == []
    # Lead state restored.
    assert lead.calendly_booked is True
    assert lead.calendar_event_id == "evt_old_123"
    assert lead.booked_datetime_iso == "2026-07-06T15:00:00+04:00"
    assert lead.status == "Booked"


def test_9_old_cancel_failure_keeps_new_marks_handoff(monkeypatch):
    """If new succeeds but old cancel fails, new stays, handoff flagged."""
    import app.services.calendar_service as calendar_service

    def fake_book(conv, lead, slot):
        lead.calendly_booked = True
        lead.calendar_event_id = "evt_new_456"
        lead.booked_datetime_iso = slot["datetime_iso"]
        lead.status = "Booked"
        return True

    monkeypatch.setattr(parent_flow, "_book_selected_slot", fake_book)
    monkeypatch.setattr(
        calendar_service, "cancel_calendar_event",
        lambda eid: False,  # cancel fails
    )
    monkeypatch.setattr(
        "app.services.sheets_service.update_lead",
        lambda sid, updates: True,
    )

    captured: list[tuple] = []
    monkeypatch.setattr(
        parent_tool_executor.sentry_service,
        "capture_exception",
        lambda exc, context=None: captured.append((exc, context)),
    )

    lead = _booked_lead()
    exe = _reschedule_executor(monkeypatch, lead=lead)
    result = exe._reschedule_booking(
        "evt_old_123",
        {
            "action": "reschedule",
            "new_datetime_iso": "2026-07-08T10:00:00+04:00",
        },
    )
    assert result["success"] is True
    assert result.get("old_cancel_failed") is True
    assert result.get("manager_handoff_required") is True
    # Lead has the NEW booking.
    assert lead.calendar_event_id == "evt_new_456"
    # Sentry captured the failure.
    assert len(captured) == 1
    _, ctx = captured[0]
    assert ctx["area"] == "booking_reschedule"
    assert ctx["reason"] == "old_cancel_failed_new_booking_active"


def test_9_new_booking_empty_event_id_preserves_old(monkeypatch):
    """`_book_selected_slot` returns True but populates no event_id —
    treat as failure and restore old state."""
    import app.services.calendar_service as calendar_service

    def silent_fail(conv, lead, slot):
        # half-write success state but no event_id
        lead.calendly_booked = True
        lead.calendar_event_id = ""
        lead.booked_datetime_iso = slot["datetime_iso"]
        lead.status = "Booked"
        return True

    cancel_calls: list[str] = []
    monkeypatch.setattr(parent_flow, "_book_selected_slot", silent_fail)
    monkeypatch.setattr(
        calendar_service, "cancel_calendar_event",
        lambda eid: cancel_calls.append(eid) or True,
    )

    lead = _booked_lead()
    exe = _reschedule_executor(monkeypatch, lead=lead)
    result = exe._reschedule_booking(
        "evt_old_123",
        {
            "action": "reschedule",
            "new_datetime_iso": "2026-07-08T10:00:00+04:00",
        },
    )
    assert result["success"] is False
    assert result.get("old_booking_preserved") is True
    assert cancel_calls == []
    # Old state restored fully.
    assert lead.calendar_event_id == "evt_old_123"
    assert lead.booked_datetime_iso == "2026-07-06T15:00:00+04:00"


# =========================================================================
# Bug 10 — redundant confirmation echo sanitizer
# =========================================================================


def test_10_strips_satze_chamceret_konsultacia():
    raw = (
        "10 ივნისი, 10:00 თავისუფალია. "
        "10 საათზე ჩამწერეთ კონსულტაცია, თუ ეს დრო გაწყობთ, დამიდასტურეთ."
    )
    out = sanitise_response_wording(raw)
    assert "საათზე ჩამწერეთ კონსულტაცია" not in out
    assert "თუ ეს დრო გაწყობთ, დამიდასტურეთ" not in out


def test_10_strips_damidasturet_after_explicit_command():
    """Context-aware: when the user said „ჩამწერეთ" the redundant
    confirmation gets stripped by the parent_flow post-process."""
    from app.flows.parent_flow import (
        _strip_redundant_confirmation_after_command,
    )
    user_msg = "10 ივნისს 10 საათზე ჩამწერეთ"
    response = "10 ივნისი, 10:00. თუ ეს დრო გაწყობთ, დამიდასტურეთ."
    out = _strip_redundant_confirmation_after_command(user_msg, response)
    assert "თუ ეს დრო გაწყობთ, დამიდასტურეთ" not in out


def test_10_keeps_damidasturet_in_discovery_path():
    """Without an explicit command, the confirmation phrase is the
    natural prompt the user expects — KEEP it."""
    from app.flows.parent_flow import (
        _strip_redundant_confirmation_after_command,
    )
    user_msg = "10:00 თავისუფალია?"
    response = "29 მაისს, 15:00 თავისუფალია. თუ ეს დრო გაწყობთ, დამიდასტურეთ."
    out = _strip_redundant_confirmation_after_command(user_msg, response)
    assert "თუ ეს დრო გაწყობთ, დამიდასტურეთ" in out


# =========================================================================
# Bug 11 — Calendar re-check phrase expansion
# =========================================================================


def test_11_sheamotsme_kalendari_triggers_verification():
    assert _user_requested_verification("შეამოწმე კალენდარი?") is True


def test_11_kalendarshi_gadaamotsme_triggers():
    assert _user_requested_verification("კალენდარში გადაამოწმე") is True


def test_11_kalendarshi_naxe_triggers():
    assert _user_requested_verification("კალენდარში ნახე") is True


def test_11_ar_aris_tavisuplali_triggers():
    assert _user_requested_verification(
        "არ არის თავისუფალი, კარგად შეამოწმე",
    ) is True


def test_11_namdvilad_tavisuplaia_triggers():
    assert _user_requested_verification("თავისუფალია ნამდვილად?") is True


def test_11_verification_phrase_blocks_book(monkeypatch):
    import app.services.calendar_service as calendar_service
    monkeypatch.setattr(parent_flow, "TBILISI_TZ", TBILISI)
    monkeypatch.setattr(
        calendar_service, "check_slot_available", lambda dt: True,
    )
    conv = Conversation(sender_id="s_v", platform="instagram")
    lead = Lead(
        sender_id="s_v", platform="instagram", segment="PARENT",
        name="ნანა", phone="595111222", child_age="12",
    )
    exe = ParentToolExecutor(
        conversation=conv, lead=lead, sender_id="s_v",
        platform="instagram",
        user_message="შეამოწმე კალენდარი?",
    )
    result = exe._book_consultation({
        "name": "ნანა", "phone": "595111222", "child_age": "12",
        "datetime_iso": "2026-07-15T10:00:00+04:00",
        "user_confirmed_datetime": True,
    })
    assert result["success"] is False
    assert result["reason"] == "verification_requested"


# =========================================================================
# Bug 12 — booking question wording polish (re-asserted)
# =========================================================================


def test_12_gicers_mxars_rewritten():
    out = sanitise_response_wording("რომელი დრო გიჭერს მხარს?")
    assert "გიჭერს მხარს" not in out
    assert "მოსახერხებელი" in out


def test_12_gtsirdebat_rewritten():
    out = sanitise_response_wording("რომელი დრო გჭირდებათ?")
    assert "გჭირდებათ" not in out or "მოსახერხებელი" in out
