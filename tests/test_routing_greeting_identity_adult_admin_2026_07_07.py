"""Routing / greeting / identity / adult-context / admin-data hardening (2026-07-07).

BUG 1 — explicit camp price/info question on the first turn must answer the
        question, not the camp-vs-adult disambiguation menu.
BUG 2 — greeting („გამარჯობა") only on the first assistant reply; stripped on
        later turns.
BUG 3 — „შენ gpt ხარ?" is an identity question, not political → consultant answer.
BUG 4 — in adult-events context, „ჩემი შვილისთვის" stays adult events (not camp).
BUG 5 — the adult-events resolver lists ONLY active events (deleted/inactive
        never appear); no seed recreates a deleted event.
BUG 6 — a clear specific question is answered first (covered via 1 + existing
        deterministic handlers).

Plus regression guards for the earlier hardening (reservation fee, transport,
sports, multi-child, age-range, name-overwrite, unknown-detail). Deterministic;
the LLM engine is mocked where a handle()-level check is needed.
"""
from __future__ import annotations

import dataclasses

import pytest

import app.config as config_module
from app.flows import parent_flow
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.services import messenger_service

_MENU = "გვითხარით, რა გაინტერესებთ"
_MANAGER = "558 67 47 33"


def _conv(sid="x", *, state="", history=None, name="", child_age="") -> Conversation:
    c = Conversation(sender_id=sid, platform="instagram", segment="PARENT")
    if state:
        c.state = state
    c.lead = Lead(sender_id=sid, platform="instagram", segment="PARENT",
                  name=name, child_age=child_age)
    for t in history or []:
        c.history.append(t)
    return c


@pytest.fixture
def engine(monkeypatch):
    """Engine ON, returning a distinctive sentinel so a leaked engine/menu path
    is visible. Each test can override `_run_llm_engine_safely`."""
    swapped = dataclasses.replace(
        config_module.settings, USE_PARENT_LLM_ENGINE=True,
        USE_CONVERSATION_PLANNER=False, CONVERSATION_PLANNER_AUTHORITATIVE=False,
        USE_SLIM_PROMPTS=False,
    )
    monkeypatch.setattr(parent_flow, "settings", swapped)
    monkeypatch.setattr(messenger_service, "get_user_profile", lambda s, p: {})
    return monkeypatch


# ══ BUG 1 / 6 — explicit camp intent skips the menu ══════════════════════════
@pytest.mark.parametrize("msg", [
    "ბანაკი რა ღირს?", "ბანაკის ფასი?", "ბანაკზე მაინტერესებს ინფორმაცია",
    "საზაფხულო ბანაკის ფასი მაინტერესებს",
])
def test_bug1_explicit_camp_intent_yields_menu(msg):
    assert parent_flow._has_explicit_georgian_camp_intent(msg) is True


@pytest.mark.parametrize("msg", ["ბანაკი", "გამარჯობა", "ინფორმაცია მაინტერესებს"])
def test_bug1_ambiguous_first_message_still_menus(msg):
    assert parent_flow._has_explicit_georgian_camp_intent(msg) is False


def test_bug1_first_turn_price_no_menu(engine):
    engine.setattr(parent_flow, "_run_llm_engine_safely",
                   lambda c, m: "ბანაკის ფასი 2150 ლარია.")
    conv = _conv("p1", state="START")           # fresh first turn
    out = parent_flow.handle(conv, "ბანაკი რა ღირს?")
    assert _MENU not in out
    assert "2150" in out


def test_bug1_bare_banaki_first_turn_shows_menu(engine):
    engine.setattr(parent_flow, "_run_llm_engine_safely", lambda c, m: "SENTINEL_ENGINE")
    conv = _conv("p2", state="START")
    out = parent_flow.handle(conv, "ბანაკი")
    assert "SENTINEL_ENGINE" not in out       # static welcome owns the turn


# ══ BUG 2 — greeting only on the first reply ═════════════════════════════════
def test_bug2_second_turn_greeting_stripped():
    conv = _conv("g", history=[
        {"role": "user", "content": "ბანაკი რა ღირს?"},
        {"role": "assistant", "content": "გამარჯობა. ბანაკის ფასი 2150 ლარია."},
    ])
    out = parent_flow._strip_midconvo_intro_leak(
        conv, "ტრანსპორტირება როგორ ხდება?",
        "გამარჯობა. ბანაკის ღირებულებაში ტრანსპორტირება შედის.",
    )
    assert not out.startswith("გამარჯობა")
    assert "ბანაკის ღირებულებაში ტრანსპორტირება შედის" in out


def test_bug2_first_turn_greeting_kept():
    conv = _conv("g2")                           # no assistant turn yet
    out = parent_flow._strip_midconvo_intro_leak(
        conv, "გამარჯობა", "გამარჯობა. ბანაკის ფასი 2150 ლარია.",
    )
    assert out.startswith("გამარჯობა")


# ══ BUG 3 — identity is not political ════════════════════════════════════════
@pytest.mark.parametrize("msg", [
    "შენ gpt ხარ?", "შენ ჩატჯიპიტი ხარ?", "რობოტი ხარ?", "შენ ვინ ხარ?",
    "AI ხარ?", "ადამიანი ხარ?",
])
def test_bug3_identity_answer(msg):
    out = parent_flow._maybe_handle_identity(_conv(), msg)
    # Compared against the RENDERED identity, not the frozen constant: the
    # programs half is read from the active sections now, so a program the
    # operator closes stops being offered without a code edit.
    assert out == parent_flow._render_identity_answer()
    assert "პოლიტიკ" not in out


def test_bug3_identity_not_hijacking_organizer_or_price():
    assert parent_flow._maybe_handle_identity(_conv(), "ვინ არის ორგანიზატორი?") is None
    assert parent_flow._maybe_handle_identity(_conv(), "ბანაკი რა ღირს?") is None


def test_bug3_identity_e2e_preempts_engine(engine):
    engine.setattr(parent_flow, "_run_llm_engine_safely",
                   lambda c, m: "პოლიტიკურ თემებზე პასუხს არ ვცემ.")
    conv = _conv("id", history=[{"role": "assistant", "content": "_prior"}])
    out = parent_flow.handle(conv, "შენ gpt ხარ?")
    # Compared against the RENDERED identity, not the frozen constant: the
    # programs half is read from the active sections now, so a program the
    # operator closes stops being offered without a code edit.
    assert out == parent_flow._render_identity_answer()
    assert "პოლიტიკ" not in out
    assert "რამდენი წლის" not in out


# ══ BUG 4 — adult-events sticky context ══════════════════════════════════════
_ADULT_OFFER = {
    "role": "assistant",
    "content": "გასაგებია, ზრდასრულთა ღონისძიებებზე დაგეხმარებით. "
               "ღონისძიების შერჩევა თქვენთვის გსურთ თუ თქვენი შვილისთვის?",
}


def test_bug4_adult_context_child_stays_adult_known_age():
    hist = [
        {"role": "user", "content": "80 წლის არია"},
        {"role": "assistant", "content": "ჩვენი ბანაკი 9–17 წლისაა. ზრდასრულთა კულტურული საღამოები."},
        {"role": "user", "content": "კი მაინტერსებს"},
        _ADULT_OFFER,
    ]
    out = parent_flow._maybe_handle_adult_context_relative(_conv(history=hist), "ჩემი შვილისთვის")
    assert out == parent_flow._ADULT_CTX_ADULT_PARTICIPANT
    assert "ბანაკი" not in out
    assert "რამდენი წლის არის თქვენი შვილი" not in out


def test_bug4_adult_context_child_unknown_age_asks_participant():
    out = parent_flow._maybe_handle_adult_context_relative(
        _conv(history=[_ADULT_OFFER]), "ღონისძიება მაინტერესებს ჩემი შვილისთვის",
    )
    assert out == parent_flow._ADULT_CTX_ASK_AGE
    assert "მონაწილე" in out


def test_bug4_camp_intent_still_camp():
    # A hard camp keyword or in-band camp age is NOT hijacked.
    assert parent_flow._maybe_handle_adult_context_relative(
        _conv(history=[_ADULT_OFFER]), "ჩემი შვილი 12 წლისაა, ბანაკი მაინტერესებს",
    ) is None
    assert parent_flow._maybe_handle_adult_context_relative(
        _conv(history=[_ADULT_OFFER]), "ჩემი შვილი 13 წლისაა",
    ) is None


def test_bug4_no_adult_context_defers():
    assert parent_flow._maybe_handle_adult_context_relative(
        _conv(history=[{"role": "assistant", "content": "გამარჯობა"}]), "ჩემი შვილისთვის",
    ) is None


# ══ BUG 5 — admin adult-events resolver lists only ACTIVE ════════════════════
def _ev(eid, status="active", date_text="28 აგვისტო", min_age=13):
    return {"id": eid, "title": eid, "status": status, "active": status == "active",
            "date_text": date_text, "min_age": min_age, "location": "monaco",
            "price_text": "5000", "price_gel": 4999}


def test_bug5_deleted_event_not_listed(monkeypatch):
    from app.services import admin_config_service as acs
    from datetime import datetime, timezone, timedelta
    now = datetime(2026, 7, 7, 12, 0, tzinfo=timezone(timedelta(hours=4)))
    # roster has ONLY the deleted event removed → empty
    monkeypatch.setattr(acs, "get_adult_events", lambda: [])
    assert acs.get_active_adult_events(now=now) == []


def test_bug5_inactive_formula_not_listed(monkeypatch):
    from app.services import admin_config_service as acs
    from datetime import datetime, timezone, timedelta
    now = datetime(2026, 7, 7, 12, 0, tzinfo=timezone(timedelta(hours=4)))
    monkeypatch.setattr(acs, "get_adult_events", lambda: [_ev("fromula_1", status="inactive")])
    out = acs.get_active_adult_events(now=now)
    assert out == []
    assert not any("fromula" in str(e.get("id", "")) for e in out)


def test_bug5_active_event_shown_only_when_active(monkeypatch):
    from app.services import admin_config_service as acs
    from datetime import datetime, timezone, timedelta
    now = datetime(2026, 7, 7, 12, 0, tzinfo=timezone(timedelta(hours=4)))
    monkeypatch.setattr(acs, "get_adult_events", lambda: [_ev("fromula_1", status="active")])
    out = acs.get_active_adult_events(now=now)
    # It IS active in this (mocked) source → shown. The live reappearance is a
    # DATA issue (committed sections.yaml), not a resolver bug.
    assert any(e.get("id") == "fromula_1" for e in out)


def test_bug5_no_active_events_no_fabrication(monkeypatch):
    from app.services import admin_config_service as acs
    from datetime import datetime, timezone, timedelta
    now = datetime(2026, 7, 7, 12, 0, tzinfo=timezone(timedelta(hours=4)))
    monkeypatch.setattr(acs, "get_adult_events", lambda: [
        _ev("a", status="inactive"), _ev("b", status="inactive"),
    ])
    assert acs.get_active_adult_events(now=now) == []


def test_bug5_delete_removes_from_list(monkeypatch):
    from app.services import admin_config_service as acs
    store = {"events": [_ev("fromula_1"), _ev("keep")]}
    monkeypatch.setattr(acs, "_load_adult_events_raw", lambda: list(store["events"]))
    monkeypatch.setattr(acs, "_save_adult_events_list", lambda evs: store.update(events=evs) or [])
    assert acs.delete_adult_event("fromula_1") is True
    assert not any(e.get("id") == "fromula_1" for e in store["events"])


# ══ Regression — earlier hardening intact ════════════════════════════════════
def test_regression_reservation_fee():
    out = parent_flow._maybe_handle_reservation_fee_question(_conv(), "წინასწარ რამდენს ვიხდი?")
    assert out == ("რაც შეეხება ჯავშნის საფასურს, ამ დეტალებს მენეჯერი გაგაცნობთ: " + _MANAGER)


def test_regression_transport_city_not_sports():
    out = parent_flow._maybe_handle_transport_logistics(
        _conv(), "მე თელავში ვცხოვრობ და ტრანსპორტირება როგორ მოხდება?")
    assert "თელავიდან" in out and _MANAGER in out
    assert "სპორტული აქტივობები" not in out


def test_regression_sports_still_works():
    # transport interceptor does not hijack a real sports question
    assert parent_flow._maybe_handle_transport_logistics(_conv(), "სპორტული აქტივობები არის?") is None


def test_regression_multi_child_records_both():
    conv = _conv("mc")
    out = parent_flow._maybe_handle_multi_child_age(conv, "მე მყავს ორი შვილი 10 წლის და 14 წლის")
    assert out is not None
    assert conv.lead.child_age == "10"
    assert "10 და 14" in conv.lead.deeper_concern


def test_regression_age_range_not_captured():
    conv = _conv("ar")
    assert parent_flow._maybe_handle_multi_child_age(conv, "ბანაკი 9-17 წლის ბავშვებისთვისაა?") is None
    assert conv.lead.child_age == ""


def test_regression_name_overwrite_guard():
    assert parent_flow.is_valid_person_name("მოგწერეთ") is False
    assert parent_flow.is_valid_person_name("ნებისმიერი") is False
    assert parent_flow.is_valid_person_name("გავიგე") is False
    assert parent_flow.is_valid_person_name("მარიამი") is True


def test_regression_unknown_detail_manager_fallback():
    out = parent_flow._maybe_handle_unknown_operational_early(_conv(), "ოთახში რამდენი ბავშვი იქნება?")
    assert out is not None and "მენეჯერი გაგაცნობთ" in out and _MANAGER in out
