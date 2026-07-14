# -*- coding: utf-8 -*-
"""Client hotfix (2026-07-03) — two narrow changes:

Change 1 — the approved deterministic Camp intro (byte-exact, replaces the old
           LLM-paraphrased intro) is returned on a clear camp-info / interest
           turn while the child age is unknown; the greeting variant is prefixed
           with „გამარჯობა 💙".
Change 2 — the bot accepts a contact number from ANY country (Georgian local,
           +995, +1, 0044, …) and never demands a „9-ნიშნა" number in
           user-facing wording.

Live mode: engine ON / planner OFF / slim OFF. The LLM engine is stubbed with a
sentinel so routing is visible without a real OpenAI call.
"""
from __future__ import annotations

import dataclasses
import re

import pytest

import app.config as config_module
from app.flows import parent_flow
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.services import admin_config_service, messenger_service

_OLD_INTRO_PHRASE = "სწავლობენ საკუთარი აზრებისა და ემოციების გამოხატვას"
_NEW_INTRO_FULL = (
    "სიტყვის აკადემიის ბანაკი არის 7-დღიანი გამოცდილება, სადაც ბავშვები არა "
    "მხოლოდ ისვენებენ, არამედ რამდენიმე დღით შორდებიან ციფრულ ხმაურს, ერთვებიან "
    "ცოცხალ დისკუსიებში, სწავლობენ ფიქრს, აზრის ჩამოყალიბებასა და რეალურ "
    "ურთიერთობას."
)
_AGE_Q = "რამდენი წლის არის თქვენი შვილი?"
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
    # Emoji policy is pinned OFF in conftest; the client greeting-emoji policy is
    # live in production, so enable it here to exercise the „გამარჯობა 💙" variant.
    monkeypatch.setattr(parent_flow, "_CLIENT_EMOJI_ENABLED", True, raising=False)


def _conv(sid, prior_bot=False, child_age=""):
    c = Conversation(sender_id=sid, platform="instagram", segment="PARENT")
    c.state = "START"
    if prior_bot:
        c.history.append({
            "role": "assistant",
            "content": "გვითხარით, რა გაინტერესებთ: ბანაკი / ღონისძიებები",
        })
    c.lead = Lead(sender_id=sid, platform="instagram", segment="PARENT", child_age=child_age)
    return c


def _turn(c, msg):
    c.history.append({"role": "user", "content": msg})
    out = parent_flow.handle(c, msg)
    c.history.append({"role": "assistant", "content": out})
    return out


# ── Change 1 — Camp intro ────────────────────────────────────────────────────
def test_camp_intro_plain_exact():
    out = _turn(_conv("i1"), "ბანაკზე ინფორმაცია მინდა")
    assert _NEW_INTRO_FULL in out
    assert _AGE_Q in out
    assert _OLD_INTRO_PHRASE not in out
    assert _SENTINEL not in out  # deterministic — LLM never consulted


def test_camp_intro_greeting_variant():
    out = _turn(_conv("i2"), "გამარჯობა, ბანაკზე ინფორმაცია მაინტერესებს")
    assert out.startswith("გამარჯობა 💙")
    assert _NEW_INTRO_FULL in out
    assert _AGE_Q in out
    assert _OLD_INTRO_PHRASE not in out
    assert out.count("💙") == 1
    assert "❤️" not in out


def test_camp_intro_interest_only():
    out = _turn(_conv("i3"), "ბანაკით ვარ დაინტერესებული")
    assert "ციფრულ ხმაურს" in out
    assert _OLD_INTRO_PHRASE not in out


def test_camp_price_returns_deterministic_full_block():
    out = _turn(_conv("i4", prior_bot=True), "ბანაკის ფასი რა არის?")
    assert "ციფრულ ხმაურს" not in out          # not the intro
    assert _SENTINEL not in out                 # deterministic price owner
    assert "2150" in out
    assert "TBC" in out

def test_camp_consultation_defers_not_intro():
    out = _turn(_conv("i5", prior_bot=True), "კონსულტაციაზე ჩამწერეთ ბანაკზე")
    assert "ციფრულ ხმაურს" not in out


def test_camp_dates_defers_not_intro():
    out = _turn(_conv("i5b", prior_bot=True), "ბანაკი როდის ტარდება?")
    assert "ციფრულ ხმაურს" not in out


def test_camp_intro_not_shown_when_age_known():
    out = _turn(_conv("i6", prior_bot=True, child_age="12"), "ბანაკზე ინფორმაცია მინდა")
    assert "ციფრულ ხმაურს" not in out          # past the intro → engine


def test_bare_greeting_still_shows_menu():
    out = _turn(_conv("i7"), "გამარჯობა")
    assert "ციფრულ ხმაურს" not in out
    assert "გვითხარით, რა გაინტერესებთ" in out


# ── Change 2 — flexible phone parsing ────────────────────────────────────────
@pytest.mark.parametrize("msg,exp_name,exp_digits", [
    ("ნიკოლოზ 595999733", "ნიკოლოზ", "595999733"),
    ("ნიკოლოზ +995595999733", "ნიკოლოზ", "995595999733"),
    ("ნინო +995 595 999 733", "ნინო", "995595999733"),
    ("Nino +1 415 555 2671", "Nino", "14155552671"),
    ("ნინო +1 415 555 2671", "ნინო", "14155552671"),
    ("ნინო 0044 7700 900123", "ნინო", "00447700900123"),
])
def test_flexible_phone_parsing(msg, exp_name, exp_digits):
    name, phone = parent_flow._parse_name_phone(msg)
    assert name == exp_name
    assert phone  # something phone-like exists
    assert re.sub(r"\D", "", phone) == exp_digits


def test_no_phone_like_value_returns_no_phone():
    name, phone = parent_flow._parse_name_phone("ნინო")
    assert phone == ""


def test_empty_message_no_phone():
    assert parent_flow._parse_name_phone("") == ("", "")


def test_georgian_two_numbers_still_detected():
    # Existing „two Georgian numbers" detection is byte-identical.
    assert parent_flow._distinct_valid_phones("595999733 ან 595999734") == [
        "595999733", "595999734",
    ]


# ── Change 2 — contact wording ───────────────────────────────────────────────
def test_contact_constants_have_no_9nishna():
    for const in (
        parent_flow._CONTACT_REQUEST_NAME_AND_PHONE,
        parent_flow._CONTACT_REQUEST_PHONE_ONLY,
        parent_flow._HANDOFF_ASK_NAME_AND_PHONE,
        parent_flow._SUNDAY_SCHOOL_OFFER_TAIL,
        parent_flow._SUNDAY_SCHOOL_ASK_PHONE,
    ):
        assert "9-ნიშნა" not in const
        assert "საკონტაქტო ნომერი" in const


def test_wording_sanitizer_strips_9nishna_and_hint():
    s = "მომწერეთ თქვენი სახელი და 9-ნიშნა საკონტაქტო ნომერი (5/7/8-ით დაწყებული)."
    out = parent_flow._normalise_contact_number_wording(s)
    assert "9-ნიშნა" not in out
    assert "5/7/8" not in out
    assert "საკონტაქტო ნომერი" in out


def test_wording_sanitizer_no_false_rewrite():
    # „ნიშნავს" (means) must not be corrupted.
    assert parent_flow._normalise_contact_number_wording("რას ნიშნავს ეს?") == "რას ნიშნავს ეს?"


def test_full_contact_request_via_handle_no_9nishna():
    c = _conv("w1", prior_bot=True, child_age="14")  # eligible, no contact
    out = _turn(c, "კი მინდა კონსულტაცია")
    assert "9-ნიშნა" not in out
    assert "საკონტაქტო ნომერი" in out


def test_intl_phone_captured_in_live_contact_flow():
    c = _conv("p1", prior_bot=True, child_age="14")
    c.history.append({
        "role": "assistant",
        "content": parent_flow._CONTACT_REQUEST_NAME_AND_PHONE,
    })
    out = _turn(c, "ნიკოლოზ +1 415 555 2671")
    assert (c.lead.phone or "")  # international number captured
    assert "9-ნიშნა" not in out
