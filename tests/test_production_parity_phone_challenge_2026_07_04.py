# -*- coding: utf-8 -*-
"""Production parity hotfix (2026-07-04) — two live Railway cases still broken in
HEAD after the 2026-07-03 four-bug fix.

Bug A — International phone with a non-995 „+" country code (+43 / +49 / …) was
        truncated to a spurious embedded 9-digit Georgian window and the „+"
        leaked into the name (Sheet showed name="ნიკოლოზ +", phone="595999733").
        Root cause: PHONE_CANDIDATE_PATTERN keeps the „+" INSIDE the token only
        for „+995…"; for other codes the „+" sits in the raw text just before the
        match, so the compound-rescue skip guard was bypassed. Fix: also check the
        character preceding the match, require a letter in a name token, and prefer
        the full `_distinct_valid_phones` number in the save path.

Bug B — A volunteered Camp challenge combined with a price/payment/info question in
        ONE message („ეკრანთან დროის შემცირება და ახალი მეგობრები, ფასი რა არის
        ბანაკის?") was not stored: a deterministic interceptor answered and the
        engine's challenge fallback never ran. Fix: capture at handle() level when
        the message carries a clear Camp goal signal, not only when the bot asked
        the goal question. The self-guarding fallback still drops pure questions.

Live mode: engine ON / planner OFF / slim OFF; the LLM engine is stubbed with a
sentinel so routing is visible without a real OpenAI call.
"""
from __future__ import annotations

import dataclasses
import re

import pytest

import app.config as config_module
from app.agent.tools.parent_tool_executor import ParentToolExecutor
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
    monkeypatch.setattr(parent_flow, "_run_llm_engine_safely", lambda c, m: _SENTINEL)
    monkeypatch.setattr(messenger_service, "get_user_profile", lambda sid, plat: {})
    monkeypatch.setattr(admin_config_service, "get_camp_status", lambda: "active")


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s or "")


def _conv(sid, child_age=""):
    c = Conversation(sender_id=sid, platform="instagram", segment="PARENT")
    c.state = "START"
    c.lead = Lead(sender_id=sid, platform="instagram", segment="PARENT", child_age=child_age)
    return c


def _turn(c, msg):
    c.history.append({"role": "user", "content": msg})
    out = parent_flow.handle(c, msg)
    c.history.append({"role": "assistant", "content": out})
    return out


# ── Bug A — international phone parsing ───────────────────────────────────────
@pytest.mark.parametrize("msg,exp_name,exp_digits", [
    ("ნიკოლოზ +43595999733", "ნიკოლოზ", "43595999733"),      # 1 — Austria
    ("ნიკოლოზ  +43595999733", "ნიკოლოზ", "43595999733"),     # 2 — double space
    ("ნიკოლოზ +491579999733", "ნიკოლოზ", "491579999733"),    # 3 — Germany
    ("ნიკოლოზ +995595999733", "ნიკოლოზ", "995595999733"),    # 4 — Georgia +995
    ("ნინო +1 415 555 2671", "ნინო", "14155552671"),          # 5 — US +1
    ("ნინო 0044 7700 900123", "ნინო", "00447700900123"),      # 6 — UK 0044
    ("ნიკოლოზ 595999733", "ნიკოლოზ", "595999733"),            # 7 — GE local
])
def test_bugA_parse_name_phone_preserves_country_code(msg, exp_name, exp_digits):
    name, phone = parent_flow._parse_name_phone(msg)
    assert name == exp_name, "name=%r" % name
    assert _digits(phone) == exp_digits, "phone=%r" % phone
    # 6 — name safety: never a lone „+" or any „+" leaked into the name.
    assert "+" not in name
    assert not any(ch.isdigit() for ch in name)


@pytest.mark.parametrize("user_msg,exp_name,exp_digits", [
    ("ნიკოლოზ  +43595999733", "ნიკოლოზ", "43595999733"),
    ("ნიკოლოზ +491579999733", "ნიკოლოზ", "491579999733"),
    ("ნიკოლოზ +995595999733", "ნიკოლოზ", "995595999733"),
    ("ნიკოლოზ 595999733", "ნიკოლოზ", "595999733"),
])
def test_bugA_save_lead_info_preserves_country_code(user_msg, exp_name, exp_digits):
    # Simulate the LLM splitting the contact into a stray-„+" name + truncated phone.
    c = _conv("a")
    ex = ParentToolExecutor(
        conversation=c, lead=c.lead, sender_id="a", platform="instagram",
        user_message=user_msg,
    )
    ex._save_lead_info({"name": "ნიკოლოზ +", "phone": "595999733"})
    assert c.lead.name == exp_name
    assert _digits(c.lead.phone) == exp_digits
    assert "+" not in c.lead.name


def test_bugA_name_token_rejects_lone_plus():
    # A lone „+" is never a valid name token.
    assert parent_flow._name_token_is_valid("+") is False
    assert parent_flow.is_valid_person_name("ნიკოლოზ +") is True  # still valid via the real token
    # …but the parsed name never contains it:
    name, _ = parent_flow._parse_name_phone("ნიკოლოზ +43595999733")
    assert name == "ნიკოლოზ"


def test_bugA_distinct_valid_phones_intl_unchanged():
    # +995 Georgian two-number detection stays byte-identical.
    assert parent_flow._distinct_valid_phones("595999733 ან 595999734") == [
        "595999733", "595999734",
    ]


# ── Bug B — challenge captured from a multi-intent (challenge + price) message ─
@pytest.mark.parametrize("msg,must_contain", [
    ("ეკრანთან დროის შემცირება და ახალი მეგობრები, ფასი რა არის ბანაკის?", ["ეკრან", "მეგობრ"]),
    ("გაჯეტთან დროის შემცირება და ახალი მეგობრები, ფასი რა არის ბანაკის?", ["გაჯეტ", "მეგობრ"]),
    ("ახალი მეგობრები და თავდაჯერება მაინტერესებს, რა ღირს?", ["მეგობრ", "თავდაჯერ"]),
    ("თვითგამოხატვა და ეკრანთან დროის შემცირება, როგორ ხდება გადახდა?", ["თვითგამოხატ", "ეკრან"]),
])
def test_bugB_volunteered_challenge_stored(msg, must_contain):
    c = _conv("b-%d" % hash(msg), child_age="14")
    c.history.append({
        "role": "assistant",
        "content": "გვითხარით, რა გაინტერესებთ: ბანაკი / ღონისძიებები",
    })
    _turn(c, msg)
    stored = (c.lead.challenge or "").strip()
    assert stored, "challenge not stored for %r" % msg
    assert stored != "არ არის მითითებული"
    # A tacked-on price/payment question must be dropped, goal wording kept.
    assert "ფასი" not in stored and "ღირ" not in stored and "გადახდა" not in stored
    for frag in must_contain:
        assert frag in stored, "%r missing from %r" % (frag, stored)


@pytest.mark.parametrize("msg", [
    "ფასი რა არის ბანაკის?",
    "როგორ ხდება გადახდა?",
    "როდის იწყება?",
    "სად არის ბანაკი?",
])
def test_bugB_generic_question_not_stored_as_challenge(msg):
    c = _conv("bn-%d" % hash(msg), child_age="14")
    c.history.append({
        "role": "assistant",
        "content": "გვითხარით, რა გაინტერესებთ: ბანაკი / ღონისძიებები",
    })
    _turn(c, msg)
    assert not (c.lead.challenge or "").strip(), "wrongly stored: %r" % c.lead.challenge


def test_bugB_does_not_overwrite_existing_challenge():
    c = _conv("bo", child_age="14")
    c.lead.challenge = "ეკრანთან დროის შემცირება"
    c.history.append({"role": "assistant", "content": "გვითხარით, რა გაინტერესებთ"})
    _turn(c, "ფასი რა არის ბანაკის?")
    assert c.lead.challenge == "ეკრანთან დროის შემცირება"


def test_bugB_signal_detector_precision():
    assert parent_flow._message_has_camp_goal_signal("ეკრანთან დროის შემცირება, ფასი?") is True
    assert parent_flow._message_has_camp_goal_signal("ფასი რა არის ბანაკის?") is False
    assert parent_flow._message_has_camp_goal_signal("როგორ ხდება გადახდა?") is False


# ── Combined end-to-end booking flow (both bugs on the same lead) ─────────────
def test_full_booking_flow_phone_and_challenge(camp_registration_open):
    c = _conv("flow")
    # 1 — camp info → intro + age question (deterministic)
    out1 = _turn(c, "ბანაკზე ინფორმაცია მინდა")
    assert "რამდენი წლის" in out1
    # 2 — age
    _turn(c, "14 წლის")
    assert (c.lead.child_age or "") == "14"
    # 3 — challenge + price in one message → challenge captured, price may answer
    _turn(c, "ეკრანთან დროის შემცირება და ახალი მეგობრები, ფასი რა არის ბანაკის?")
    assert "ეკრანთან დროის შემცირება და ახალი მეგობრები" in (c.lead.challenge or "")
    # 4 — consultation intent, then the bot asks for contact
    _turn(c, "კონსულტაციაზე ჩამწერეთ")
    c.history.append({
        "role": "assistant",
        "content": parent_flow._CONTACT_REQUEST_NAME_AND_PHONE,
    })
    # 5 — international contact → full number + clean name
    _turn(c, "ნიკოლოზ +43595999733")
    assert c.lead.name == "ნიკოლოზ", "name=%r" % c.lead.name
    assert _digits(c.lead.phone) == "43595999733", "phone=%r" % c.lead.phone
    assert "+" not in c.lead.name
    # Final CRM/Sheet payload parity:
    assert c.lead.name == "ნიკოლოზ"
    assert c.lead.phone.replace(" ", "") == "+43595999733"
    assert "ეკრანთან დროის შემცირება და ახალი მეგობრები" in (c.lead.challenge or "")
