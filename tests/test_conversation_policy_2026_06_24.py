"""Consultant-quality conversation policy (Reasoning Layer Phase 3 Stage 3,
2026-06-24).

Refines answer/CTA/composition so the agent behaves like a thoughtful consultant
(source of truth: docs/source/sales_agent_prompt.md + the audience analysis):
open → ask child age → discover the pain point → value → price only when asked /
after engagement → CTA only at the right stage. Consent before any handoff /
subscription. Manager phone public-full; user phone masked.

All behaviour is reasoning-driven (planner intent + selected_state + composer +
validator) and gated on the AUTHORITATIVE planner — the existing suite (planner
off) is unaffected. The LLM is mocked offline.
"""
from __future__ import annotations

import dataclasses

import pytest

import app.config as config_module
from app.agent.llm import adult_llm_engine, parent_llm_engine
from app.flows import adult_flow, parent_flow
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.reasoning import conversation_planner as cp
from app.reasoning import response_policy as rp
from app.services import (
    admin_config_service, adult_subscription_service, conversation_service,
    notification_service, sheets_service,
)

_FLAGS = dict(
    USE_CONVERSATION_PLANNER=True,
    CONVERSATION_PLANNER_AUTHORITATIVE=True,
    USE_PARENT_LLM_ENGINE=True,
    USE_ADULT_LLM_ENGINE=True,
)
_PARENT_CANNED = "ბანაკის შესახებ დაგეხმარებით."
_ADULT_CANNED = "ზრდასრულთა ღონისძიებების სია."


def _fake_parent_engine(conversation, message):
    lead = conversation.lead
    try:
        parent_llm_engine.maybe_capture_child_age_fallback(
            lead, message, age_question_pending=True,
        )
    except Exception:
        pass
    return _PARENT_CANNED


@pytest.fixture
def live(monkeypatch):
    for mod in (
        conversation_service, parent_flow, adult_flow,
        parent_llm_engine, adult_llm_engine, config_module,
    ):
        monkeypatch.setattr(mod, "settings", dataclasses.replace(mod.settings, **_FLAGS))
    monkeypatch.setattr(parent_flow, "_run_llm_engine_safely", _fake_parent_engine)
    monkeypatch.setattr(adult_flow, "_run_adult_engine_safely", lambda c, l, m: _ADULT_CANNED)
    monkeypatch.setattr(notification_service, "notify_sunday_school_handoff", lambda lead: True)
    monkeypatch.setattr(sheets_service, "log_sunday_school_lead", lambda *a, **k: True)
    parent_flow._sunday_school_notified_senders.clear()
    conversation_service.conversations.clear()
    yield


def _conv(sender, segment="UNCLEAR", state="START", history=None, **lk):
    lead = Lead(sender_id=sender, platform="messenger", segment=segment)
    for k, v in lk.items():
        setattr(lead, k, v)
    conv = Conversation(
        sender_id=sender, platform="messenger", segment=segment, state=state,
        lead=lead, history=history if history is not None else [],
    )
    conversation_service.conversations[sender] = conv
    return conv


def _send(sender, text):
    return conversation_service.process_message(sender, text, "messenger")


def _manager_phone():
    return (admin_config_service.get_manager_phone() or "558 67 47 33").strip()


# ── #1/#2/#3 — camp info: value intro + ask age; no price/link/phone ──────────

def test_camp_info_no_price_no_link_no_phone_asks_age(live):
    conv = _conv("ci_1")
    resp = _send("ci_1", "გამარჯობა ბანაკი მაინტერესებს")
    assert "2150" not in resp                                  # no price
    assert "http" not in resp.lower() and "tinyurl" not in resp  # no link
    assert _manager_phone() not in resp                        # no manager phone
    assert "რამდენი წლისაა" in resp                            # asks child age
    assert len(resp) < 400                                     # concise


# ── #4 — explicit price → value-framed price ──────────────────────────────────

def test_explicit_price_returns_price_with_value(live):
    conv = _conv("pr_1", segment="PARENT", state="IN_PROGRESS", child_age="14",
                 history=[{"role": "assistant", "content": "prev"}])
    resp = _send("pr_1", "ფასი რა ღირს?")
    assert "2150" in resp
    assert "http" not in resp.lower()                          # no link by default
    assert _manager_phone() not in resp                        # no manager phone by default
    assert "ღირებულება" in resp or "შედის" in resp             # value framing


# ── #3/#5/#6 — eligible child age → pain-point discovery ──────────────────────

def test_eligible_age_asks_pain_point_not_generic(live):
    conv = _conv("ea_1", segment="PARENT", state="IN_PROGRESS",
                 history=[{"role": "assistant", "content": "რამდენი წლისაა თქვენი შვილი?"}])
    resp = _send("ea_1", "14 წლის არის")
    assert "შეესაბამება" in resp                               # confirms fit
    assert "2150" not in resp                                  # no price
    assert "http" not in resp.lower()                          # no link
    assert "რა გაწუხებთ" in resp                               # pain-point question
    assert "რის შესახებ გსურთ ინფორმაცია" not in resp          # not the awkward wording


def test_eligible_age_unit_pain_point():
    out = rp.eligible_age_reply("14")
    assert "შეესაბამება" in out and "რა გაწუხებთ" in out
    assert "2150" not in out and "http" not in out.lower()


# ── #4 — consultation CTA: the MANAGER explains the details ───────────────────

def test_consultation_cta_manager_explains_unit():
    draft = "კარგი, კონსულტაციაზე ჩაგწერთ და დეტალურად აგიხსნით პროგრამას."
    out = rp.fix_consultation_cta(draft)
    assert "მენეჯერი" in out
    assert "დეტალურად აგიხსნით პროგრამას" not in out


def test_consultation_cta_idempotent_when_manager_present():
    draft = "კონსულტაციაზე ჩაგწერთ და მენეჯერი დეტალებს აგიხსნით."
    assert rp.fix_consultation_cta(draft) == draft


# ── #5 — Sunday School: no auto-handoff; offer consent ────────────────────────

def test_sunday_school_known_contact_offers_consent_no_handoff(live):
    _conv("ss_1", segment="PARENT", state="IN_PROGRESS",
          name="ჯონი", phone="595999733", child_age="7",
          history=[{"role": "assistant", "content": "prev"}])
    resp = _send("ss_1", "საკვირაო სკოლაზე მაინტერესებს როდის ემატება?")
    assert "გადავეცი მენეჯერს" not in resp                     # NO auto-handoff
    assert "მადლობა, ინფორმაცია გადავეცი" not in resp
    assert "მომწერეთ თქვენი სახელი" not in resp                # known contact not re-asked
    assert ("მენეჯერს გადავცემ" in resp) or ("დაგიკავშირდებათ" in resp)  # consent offer


def test_sunday_school_then_consent_dispatches(live):
    _conv("ss_2", segment="PARENT", state="IN_PROGRESS",
          name="ჯონი", phone="595999733", child_age="7",
          history=[{"role": "assistant", "content": "prev"}])
    _send("ss_2", "საკვირაო სკოლა მაინტერესებს როდის ემატება?")
    resp2 = _send("ss_2", "კი, გადაეცი")
    assert "გადავეცი მენეჯერს" in resp2                        # dispatched AFTER consent


# ── #6 — adult subscription confirmation: no adult age; known contact ─────────

def test_subscription_consent_uses_known_contact_no_age(live):
    conv = _conv("sub_1", segment="ADULT", state="IN_PROGRESS",
                 name="ჯონი", phone="595999733",
                 history=[{"role": "assistant", "content":
                           "ახალი ღონისძიება რომ დაემატება, შეგატყობინებთ. გსურთ?"}])
    conv.adult_subscription_status = "asked"
    resp = _send("sub_1", "კი მინდა")
    assert conv._turn_plan.user_current_intent == "subscription_request"
    assert "რამდენი წლის" not in resp                          # NO adult-age ask
    assert "ჯონი" in resp                                      # known name used
    assert "595***733" in resp and "595999733" not in resp      # masked phone, not full
    assert "ჩაგწეროთ სიაში?" in resp                           # asks confirmation


def test_subscription_confirm_then_save(live, monkeypatch):
    saved = {}
    monkeypatch.setattr(
        adult_subscription_service, "subscribe",
        lambda **k: saved.update(k) or {"success": True, "status": "subscribed"},
    )
    conv = _conv("sub_2", segment="ADULT", state="IN_PROGRESS",
                 name="ჯონი", phone="595999733",
                 history=[{"role": "assistant", "content":
                           "ახალი ღონისძიება რომ დაემატება, შეგატყობინებთ. გსურთ?"}])
    conv.adult_subscription_status = "asked"
    _send("sub_2", "კი მინდა")                                 # → confirm step
    assert conv.adult_subscription_status == "confirm_pending"
    resp2 = _send("sub_2", "კი")                               # → save
    assert saved.get("name") == "ჯონი" and saved.get("phone") == "595999733"
    assert "ჩაგწერეთ" in resp2


# ── #7 — manager phone full; user phone masked ───────────────────────────────

def test_manager_phone_full_user_masked(live):
    conv = _conv("mp_1", segment="PARENT", state="IN_PROGRESS",
                 name="ჯონი", phone="595999733", child_age="14",
                 history=[{"role": "assistant", "content": "prev"}])
    r_mgr = _send("mp_1", "მენეჯერის ნომერი მომწერეთ და მე დავურეკავ")
    assert "558 67 47 33" in r_mgr                             # full, not masked
    r_recall = _send("mp_1", "ჩემზე რა ინფორმაცია გაქვს?")
    assert "595***733" in r_recall and "595999733" not in r_recall  # user masked


# ── #8 — camp registration (incl. typo) → link first, no consultation booking ─

@pytest.mark.parametrize("msg", [
    "გამარჯობა ბანაკზე დარეგისტრირება მინდა",
    "გამარჯობა ბანაკზე დარეგისტირება მინდა",   # live typo (extra „ი")
])
def test_camp_registration_link_first(live, msg):
    conv = _conv(f"reg_{abs(hash(msg))%9999}")
    resp = _send(conv.sender_id, msg)
    assert ("tinyurl" in resp) or ("http" in resp.lower()) or ("ბმულ" in resp)
    assert "რამდენი წლისაა" not in resp                        # no age question
    assert "სახელი და" not in resp                             # does not collect contact


# ── #9 — greeting after decline → neutral menu (no stale camp flow) ──────────

def test_greeting_after_decline_returns_menu(live):
    conv = _conv("gd_1", segment="PARENT", state="IN_PROGRESS", child_age="7",
                 history=[{"role": "assistant", "content": "prev"}])
    _send("gd_1", "არ მინდა მადლობა")                          # decline → close
    resp = _send("gd_1", "გამარჯობა")                          # greeting after close
    assert "რამდენი წლისაა" not in resp                        # no stale age question
    assert ("ბანაკი" in resp and "საკვირაო" in resp) or ("რით დაგეხმაროთ" in resp)


# ── #11/#13 — concise; decline does not create handoff/subscription state ─────

def test_collapse_repeated_thanks_unit():
    out = rp.collapse_repeated_thanks("მადლობა. კარგია. გმადლობთ ისევ.")
    assert out.count("მადლობ") + out.count("გმადლობ") == 1


def test_decline_does_not_create_subscription_or_target(live):
    conv = _conv("dc_1", segment="ADULT", state="IN_PROGRESS",
                 adult_target_relation="შვილი", adult_target_age="13",
                 history=[{"role": "assistant", "content": "ზრდასრულთა ღონისძიებები"}])
    resp = _send("dc_1", "არ მინდა მადლობა")
    assert "სიამოვნებით." not in resp                          # no robotic decline
    assert (conv.lead.adult_target_relation or "") == ""        # adult target cleared
    assert (conv.adult_subscription_status or "") != "subscribed"
