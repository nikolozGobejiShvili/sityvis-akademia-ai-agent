# -*- coding: utf-8 -*-
"""Client local-smoke hotfix (2026-07-03) — four narrow deterministic fixes.

Bug 1 — a SIMPLE camp-price answer must not tack on a premature scheduling /
        date-time / name-contact question („რა დროს გადახედოთ კონსულტაციას?").
        It is price + inclusions + the soft consultation OFFER only; booking
        starts after explicit consent.
Bug 2 — in booking slot-selection context ONLY, a bare colloquial hour 1–9 maps
        to the afternoon/evening offer (8 საათზე → 20:00), so „3 ივლის 8 საათზე
        იყოს" matches the offered 20:00 slot, never a rejected 08:00. Explicit
        „დილ…" (morning) stays literal. Global time parsing is untouched.
Bug 3 — an international contact („ნიკოლოზ +995595999733") is stored with the
        country code preserved and a clean name, even when the LLM splits the
        contact into name="ნიკოლოზ +" / phone="595999733" before the save tool.
Bug 4 — the parent's camp goal / challenge answer is stored on the lead even
        when a deterministic camp-topic interceptor answers the turn (a goal
        answer overlaps camp-topic triggers გაჯეტ / ეკრან / მეგობრ).

Live mode: engine ON / planner OFF / slim OFF (the engine is stubbed with a
sentinel where a real turn would run, so routing is visible without OpenAI).
"""
from __future__ import annotations

import dataclasses

import pytest

import app.config as config_module
from app.agent.tools.parent_tool_executor import (
    ParentToolExecutor,
    _last_slots_by_sender,
)
from app.flows import parent_flow
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.services import admin_config_service, messenger_service

_SENTINEL = "[[ENGINE]]"


@pytest.fixture(autouse=True)
def _live(monkeypatch):
    swapped = dataclasses.replace(
        config_module.settings,
        USE_PARENT_LLM_ENGINE=True,
        USE_CONVERSATION_PLANNER=False,
        CONVERSATION_PLANNER_AUTHORITATIVE=False,
        USE_SLIM_PROMPTS=False,
    )
    monkeypatch.setattr(parent_flow, "settings", swapped)
    # Stub the LLM engine so routing is visible and no real OpenAI call is made.
    monkeypatch.setattr(parent_flow, "_run_llm_engine_safely", lambda c, m: _SENTINEL)
    monkeypatch.setattr(messenger_service, "get_user_profile", lambda sid, plat: {})
    monkeypatch.setattr(admin_config_service, "get_camp_status", lambda: "active")


def _conv(sid, child_age=""):
    c = Conversation(sender_id=sid, platform="instagram", segment="PARENT")
    c.state = "START"
    c.lead = Lead(sender_id=sid, platform="instagram", segment="PARENT", child_age=child_age)
    return c


# ── Bug 1 — price answer never carries a premature scheduling question ─────────
_PRICE_MSG = "ფასი რა არის ბანაკის?"
_PRICE_ANSWER = (
    "ფასი არის 2150 ლარი, რაც მოიცავს ტრანსპორტს, განთავსებას, კვებას და "
    "სრულ პროგრამას.\n\n"
    "თუ გსურთ, კონსულტაციაზე ჩაგწერთ, სადაც დეტალებს მენეჯერი გაგაცნობთ."
)


def test_bug1_strips_trailing_scheduling_question():
    resp = _PRICE_ANSWER + "\n\nრა დროს გადახედოთ კონსულტაციას?"
    out = parent_flow._strip_premature_scheduling_from_price_answer(_PRICE_MSG, resp)
    assert "რა დროს" not in out
    assert "გადახედ" not in out
    assert "2150" in out                                    # price preserved
    assert "კონსულტაციაზე ჩაგწერთ" in out                  # soft offer preserved


def test_bug1_strips_inline_name_contact_prompt():
    resp = (
        "ფასი არის 2150 ლარი, რაც მოიცავს ტრანსპორტს, განთავსებას, კვებას და "
        "სრულ პროგრამას. მომწერეთ თქვენი სახელი და საკონტაქტო ნომერი."
    )
    out = parent_flow._strip_premature_scheduling_from_price_answer(_PRICE_MSG, resp)
    assert "საკონტაქტო ნომერ" not in out
    assert "2150" in out


def test_bug1_clean_price_answer_untouched():
    out = parent_flow._strip_premature_scheduling_from_price_answer(_PRICE_MSG, _PRICE_ANSWER)
    assert out == _PRICE_ANSWER


def test_bug1_payment_question_not_gutted():
    # A PAYMENT question keeps its wording — the stripper is a no-op there.
    resp = "გადახდის გადანაწილება შესაძლებელია. რა დროს გადავიხადოთ?"
    out = parent_flow._strip_premature_scheduling_from_price_answer(
        "გადახდა როგორ ხდება?", resp,
    )
    assert out == resp


def test_bug1_non_price_message_untouched():
    resp = "ბანაკი ტარდება კაჭრეთში. რა დროს გადახედოთ კონსულტაციას?"
    out = parent_flow._strip_premature_scheduling_from_price_answer(
        "ბანაკი სად ტარდება?", resp,
    )
    assert out == resp


def test_bug1_price_still_defers_to_engine():
    # The first camp-price ask still reaches the engine (not made deterministic).
    c = _conv("b1e", child_age="13")
    c.history.append({"role": "assistant", "content": "გამარჯობა"})
    c.history.append({"role": "user", "content": _PRICE_MSG})
    out = parent_flow.handle(c, _PRICE_MSG)
    assert _SENTINEL in out


# ── Bug 2 — booking slot-selection bare 1–9 → afternoon/evening ───────────────
def _offer(sid):
    _last_slots_by_sender[sid] = [
        {"datetime_iso": "2026-07-03T20:00:00+04:00", "display": "3 ივლისი, 20:00", "slot_id": "s1"},
        {"datetime_iso": "2026-07-04T10:00:00+04:00", "display": "4 ივლისი, 10:00", "slot_id": "s2"},
    ]


def test_bug2_bare_8_maps_to_20_00_and_matches_offer():
    _offer("b2a")
    m = parent_flow._user_explicit_slot_choice("b2a", "3 ივლის 8 საათზე იყოს")
    assert m is not None
    assert m["datetime_iso"].startswith("2026-07-03T20:00")


def test_bug2_explicit_morning_stays_literal():
    _offer("b2b")
    # 08:00 is not offered → no match (proves 8 was NOT PM-normalised here).
    m = parent_flow._user_explicit_slot_choice("b2b", "დილით 8 საათზე")
    assert m is None


def test_bug2_two_digit_hour_stays_literal():
    _offer("b2c")
    m = parent_flow._user_explicit_slot_choice("b2c", "4 ივლის 10 საათზე")
    assert m is not None
    assert m["datetime_iso"].startswith("2026-07-04T10:00")


def test_bug2_explicit_hhmm_literal():
    _offer("b2d")
    m = parent_flow._user_explicit_slot_choice("b2d", "10:00 იყოს")
    assert m is not None
    assert m["datetime_iso"].startswith("2026-07-04T10:00")


def test_bug2_global_colloquial_parser_unchanged():
    # extract_colloquial_hour is the single source of truth and already mapped
    # 8 → 20:00 — this fix must not have altered it.
    from app.agent.services.timestamps import extract_colloquial_hour
    assert extract_colloquial_hour("8 საათზე") == (20, 0)
    assert extract_colloquial_hour("დილის 8 საათზე") == (8, 0)
    assert extract_colloquial_hour("10 საათზე") == (10, 0)


# ── Bug 3 — international phone preserved + clean name in the save path ────────
@pytest.mark.parametrize("user_msg,llm_name,llm_phone,exp_name,exp_phone", [
    ("ნიკოლოზ +995595999733", "ნიკოლოზ +", "595999733", "ნიკოლოზ", "+995595999733"),
    ("ნინო +995 595 999 733", "ნინო +", "595999733", "ნინო", "+995595999733"),
    ("Nino +1 415 555 2671", "Nino +", "4155552671", "Nino", "+14155552671"),
    ("ნინო 0044 7700 900123", "ნინო", "00447700900123", "ნინო", "00447700900123"),
    ("ჯონი 595999733", "ჯონი", "595999733", "ჯონი", "595999733"),
])
def test_bug3_save_lead_info_preserves_country_code(
    user_msg, llm_name, llm_phone, exp_name, exp_phone,
):
    c = _conv("b3")
    ex = ParentToolExecutor(
        conversation=c, lead=c.lead, sender_id="b3", platform="instagram",
        user_message=user_msg,
    )
    ex._save_lead_info({"name": llm_name, "phone": llm_phone})
    assert c.lead.name == exp_name
    assert c.lead.phone == exp_phone


def test_bug3_resave_without_phone_in_message_unchanged():
    # A re-save on a turn whose message has NO phone must not be overridden.
    c = _conv("b3b")
    ex = ParentToolExecutor(
        conversation=c, lead=c.lead, sender_id="b3b", platform="instagram",
        user_message="დიახ",
    )
    ex._save_lead_info({"name": "მარიამი", "phone": "595111222"})
    assert c.lead.name == "მარიამი"
    assert c.lead.phone == "595111222"


# ── Bug 4 — camp goal / challenge captured even when an interceptor answers ────
@pytest.mark.parametrize("answer", [
    "გაჯეტთან დროის შემცირება და ახალი მეგობრები",
    "ეკრანთან დროის შემცირება და ახალი მეგობრები",
    "გაჯეტებისგან განტვირთვა",
    "თავდაჯერება",
    "თვითგამოხატვა",
    "ახალი მეგობრები",
])
def test_bug4_goal_answer_stored_on_lead(answer):
    c = _conv("b4-%s" % hash(answer))
    c.history.append({
        "role": "assistant",
        "content": "რას ელოდებით ბანაკისგან — ეკრანისგან დისტანცია, ახალი გარემო თუ კომუნიკაცია?",
    })
    c.history.append({"role": "user", "content": answer})
    parent_flow.handle(c, answer)
    assert (c.lead.challenge or "").strip(), "challenge not captured for %r" % answer


def test_bug4_gadget_question_without_goal_ask_not_stored():
    # No goal question was asked → a gadget QUESTION must NOT be stored.
    c = _conv("b4neg1")
    c.history.append({"role": "assistant", "content": "გვითხარით, რა გაინტერესებთ"})
    c.history.append({"role": "user", "content": "გაჯეტებს იყენებენ ბანაკზე?"})
    parent_flow.handle(c, "გაჯეტებს იყენებენ ბანაკზე?")
    assert not (c.lead.challenge or "").strip()


def test_bug4_consent_reply_to_goal_not_stored():
    # Goal asked but the reply is a booking consent (no challenge stem) → skip.
    c = _conv("b4neg2")
    c.history.append({
        "role": "assistant",
        "content": "რისი მიღება გსურთ თქვენი შვილისთვის ამ ზაფხულს?",
    })
    c.history.append({"role": "user", "content": "კი ჩამწერეთ"})
    parent_flow.handle(c, "კი ჩამწერეთ")
    assert not (c.lead.challenge or "").strip()
