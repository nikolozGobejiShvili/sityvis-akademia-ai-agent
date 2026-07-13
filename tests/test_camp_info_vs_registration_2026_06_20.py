"""URGENT live bug (2026-06-20) — a camp INFORMATION request must NOT return
the registration link.

User wrote „გამარჯობა ბანაკის შესახებ ინფორმაცია რომ მომწერო" and the agent
returned the registration link „https://tinyurl.com/36jcae8z". Root cause:
the registration-link interceptor matched the marker „ფორმა" as a RAW
substring, and „ფორმა" is a substring of „ინ-ფორმა-ცია" (information). So every
information request over-fired the link interceptor.

Fix: „ფორმა" is now matched with a Georgian word boundary (a standalone
„ფორმა"/„ფორმის" token), so it never fires inside „ინფორმაცია" or „ფორმატი"
(format). The same foot-gun is fixed in the conversation_service UNCLEAR
registration-clarification helper.

These tests run the SAME final-response path used by Messenger
(`conversation_service.process_message`) with the engine ON and a SPY that
proves the engine IS consulted for information requests (camp info) and is
NEVER consulted for registration requests (deterministic link). No real
OpenAI / Meta / Redis / network.
"""

from __future__ import annotations

import dataclasses

import pytest

import app.config as config_module
from app.flows import parent_flow
from app.services import admin_config_service, conversation_service, messenger_service


_ADMIN_URL = "https://tinyurl.com/36jcae8z"
_MENU = "გვითხარით, რა გაინტერესებთ"
_CLARIFY = "რომელი მიმართულების რეგისტრაციის ლინკი"


@pytest.fixture(autouse=True)
def _reset():
    conversation_service.conversations.clear()
    yield
    conversation_service.conversations.clear()

@pytest.fixture
def camp_registration_open(monkeypatch):
    monkeypatch.setattr(
        admin_config_service, "get_camp_registration_status", lambda: "open",
    )


@pytest.fixture
def engine_on(monkeypatch):
    """Mirror live: PARENT LLM engine ON, replaced by a record-only spy."""
    swapped = dataclasses.replace(config_module.settings, USE_PARENT_LLM_ENGINE=True)
    monkeypatch.setattr(parent_flow, "settings", swapped)
    calls: list = []

    def _spy(**kwargs):
        calls.append(kwargs)
        return "ENGINE_WAS_CALLED"

    monkeypatch.setattr("app.agent.llm.parent_llm_engine.run_parent_llm_turn", _spy)
    monkeypatch.setattr(messenger_service, "get_user_profile", lambda sid, plat: {})
    return calls


# =========================================================================
# INFORMATION requests must NOT return the registration link.
# =========================================================================

_INFO_INPUTS = [
    "გამარჯობა ბანაკის შესახებ ინფორმაცია რომ მომწერო",
    "ბანაკის შესახებ ინფორმაცია მინდა",
    "ბანაკზე ინფორმაცია მომწერეთ",
    "ინფორმაცია მომწერე ბანაკზე",
    "ბანაკი მაინტერესებს",
]


@pytest.mark.parametrize("msg", _INFO_INPUTS)
def test_info_request_is_not_registration_link(engine_on, msg):
    out = conversation_service.process_message("info", msg, "instagram")
    assert _ADMIN_URL not in out, f"info request wrongly returned the link: {msg!r}"
    # A camp INFO / interest request is now answered by the deterministic
    # approved intro (client hotfix 2026-07-03), never the registration link.
    assert "ციფრულ ხმაურს" in out, f"info request did not get the camp intro: {msg!r}"


# =========================================================================
# REGISTRATION requests still return the Admin link (deterministic).
# =========================================================================

_REG_INPUTS = [
    "ბანაკზე როგორ დავრეგისტრირდე?",
    "ბანაკის სარეგისტრაციო ლინკი მომწერე",
    "რეგისტრაციის ფორმა სად არის ბანაკზე?",
    "სარეგისტრაციო ფორმა მომწერეთ ბანაკზე",
    "ბანაკზე ჩაწერა მინდა",
]


@pytest.mark.parametrize("msg", _REG_INPUTS)
def test_registration_request_returns_admin_link(engine_on, camp_registration_open, msg):
    out = conversation_service.process_message("reg", msg, "instagram")
    assert _ADMIN_URL in out, f"registration link missing for: {msg!r}"
    assert _MENU not in out
    assert engine_on == [], f"registration must be deterministic (no engine): {msg!r}"


# =========================================================================
# Regressions.
# =========================================================================


def test_bare_greeting_still_menu(engine_on):
    out = conversation_service.process_message("greet", "გამარჯობა", "instagram")
    assert _MENU in out
    assert _ADMIN_URL not in out
    assert engine_on == []


def test_format_question_is_not_link(engine_on):
    out = conversation_service.process_message("fmt", "ბანაკის ფორმატი რა არის", "instagram")
    assert _ADMIN_URL not in out
    assert len(engine_on) == 1


def test_already_enrolled_is_not_link(engine_on):
    out = conversation_service.process_message("enr", "ბანაკზე უკვე ჩაწერილი ვარ", "instagram")
    assert _ADMIN_URL not in out


def test_adult_event_interest_no_camp_link(engine_on):
    out = conversation_service.process_message("adlt", "ღონისძიება მაინტერესებს", "instagram")
    assert _ADMIN_URL not in out
    assert conversation_service.conversations["adlt"].segment == "ADULT"


def test_bare_information_request_unclear_shows_menu_not_clarification(engine_on):
    """A FRESH, target-less „ინფორმაცია მომწერე" → UNCLEAR → generic menu,
    NOT the registration clarification (the conversation_service ფორმა
    foot-gun is fixed)."""
    out = conversation_service.process_message("amb-info", "ინფორმაცია მომწერე", "instagram")
    assert _CLARIFY not in out
    assert _ADMIN_URL not in out
    assert _MENU in out


def test_missing_registration_url_safe_fallback(engine_on, monkeypatch, camp_registration_open):
    monkeypatch.setattr(
        admin_config_service, "get_camp_facts",
        lambda: {"name": "ბანაკი", "registration_url": ""},
    )
    out = conversation_service.process_message(
        "missing", "ბანაკზე როგორ დავრეგისტრირდე?", "instagram",
    )
    assert "http" not in out          # no invented link
    assert ("მენეჯერ" in out) or ("ნომერ" in out)
    assert engine_on == []


# =========================================================================
# Helper-level guards.
# =========================================================================


@pytest.mark.parametrize("msg", _INFO_INPUTS + [
    "ბანაკის ფორმატი რა არის",
    "ბანაკზე უკვე ჩაწერილი ვარ",
])
def test_camp_registration_helper_false_for_info(msg):
    assert parent_flow._is_camp_registration_link_request(msg) is False


@pytest.mark.parametrize("msg", _REG_INPUTS + ["ბანაკის ფორმა მომწერეთ"])
def test_camp_registration_helper_true_for_registration(msg):
    assert parent_flow._is_camp_registration_link_request(msg) is True


@pytest.mark.parametrize("msg, expected", [
    ("ინფორმაცია მომწერე", False),          # information, not a form
    ("სარეგისტრაციო ფორმა მომწერეთ", True),  # standalone form token
    ("ლინკი მომწერე", True),
    ("ფორმატი რა არის", False),              # format ≠ form
])
def test_conversation_service_registration_helper(msg, expected):
    assert conversation_service._is_registration_link_request(msg) is expected
