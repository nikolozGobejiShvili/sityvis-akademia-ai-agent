"""LIVE-PATH camp registration link (2026-06-19).

Prior tests passed at the helper / routing level but the ACTUAL Messenger
final response (conversation_service.process_message → parent_flow.handle →
engine) still asked the child age / gave a general intro instead of the
registration link — because those tests STUBBED the engine and never asserted
the real final outgoing text.

These tests exercise the SAME final-response path used by Messenger
(`conversation_service.process_message`) with the PARENT LLM engine turned ON
(mirroring live) and a SPY proving the engine is NEVER consulted for a
registration-link request: a deterministic pre-engine interceptor returns the
configured Admin `registration_url` immediately. No real OpenAI / Meta /
Redis / network (conftest disables Redis + blocks outbound HTTP; the engine
spy records-only).
"""

from __future__ import annotations

import dataclasses

import pytest

import app.config as config_module
from app.flows import parent_flow
from app.services import admin_config_service, conversation_service, messenger_service


_ADMIN_URL = "https://tinyurl.com/36jcae8z"
_MENU = "გვითხარით, რა გაინტერესებთ"
_AGE_PHRASES = ("რამდენი წლის", "თქვენი შვილი რამდენი წლისაა")


@pytest.fixture(autouse=True)
def _reset():
    conversation_service.conversations.clear()
    yield
    conversation_service.conversations.clear()


@pytest.fixture
def engine_on(monkeypatch):
    """Mirror the LIVE config: PARENT LLM engine ON. The engine is replaced
    by a record-only spy — if the registration interceptor failed and the
    request reached the engine, `calls` would be non-empty AND the real link
    would be absent."""
    swapped = dataclasses.replace(config_module.settings, USE_PARENT_LLM_ENGINE=True)
    monkeypatch.setattr(parent_flow, "settings", swapped)
    calls: list = []

    def _spy(**kwargs):
        calls.append(kwargs)
        return "ENGINE_WAS_CALLED"  # sentinel — must NOT appear for reg requests

    monkeypatch.setattr(
        "app.agent.llm.parent_llm_engine.run_parent_llm_turn", _spy,
    )
    monkeypatch.setattr(messenger_service, "get_user_profile", lambda sid, plat: {})
    return calls


# =========================================================================
# 1–5 — fresh state, real final outgoing text contains the Admin link,
# no age question, no menu, engine never consulted.
# =========================================================================

_REGISTRATION_INPUTS = [
    "გამარჯობა, ბანაკზე როგორ დავრეგისტრირდე?",
    "ბანაკზე როგორ დავრეგისტრირდე?",
    "ბანაკის სარეგისტრაციო ლინკი მომწერე",
    "რეგისტრაციის ფორმა სად არის ბანაკზე?",
]


@pytest.mark.parametrize("msg", _REGISTRATION_INPUTS)
def test_live_registration_returns_admin_link(engine_on, msg):
    out = conversation_service.process_message("reg-live", msg, "instagram")
    assert _ADMIN_URL in out, f"registration link missing for {msg!r}: {out!r}"
    for age in _AGE_PHRASES:
        assert age not in out, f"asked age for {msg!r}: {out!r}"
    assert _MENU not in out, f"generic menu shown for {msg!r}"
    assert "ENGINE_WAS_CALLED" not in out
    assert engine_on == [], "engine must NOT be consulted — deterministic link answer"


# =========================================================================
# 6 — general camp interest still goes to the normal flow (engine consulted),
# NOT the registration interceptor.
# =========================================================================


def test_camp_interest_still_normal_flow(engine_on):
    out = conversation_service.process_message("interest", "ბანაკი მაინტერესებს", "instagram")
    assert _ADMIN_URL not in out          # registration interceptor did NOT fire
    assert len(engine_on) == 1            # general interest WAS routed to the engine


# =========================================================================
# 7 — bare greeting still shows the generic menu.
# =========================================================================


def test_bare_greeting_still_menu(engine_on):
    out = conversation_service.process_message("greet", "გამარჯობა", "instagram")
    assert _MENU in out
    assert _ADMIN_URL not in out
    assert engine_on == []                # greeting never reaches the engine


# =========================================================================
# 8 — missing Admin registration_url → safe fallback, NO invented link.
# =========================================================================


def test_missing_registration_url_safe_fallback(engine_on, monkeypatch):
    monkeypatch.setattr(
        admin_config_service, "get_camp_facts",
        lambda: {"name": "ბანაკი", "registration_url": ""},
    )
    out = conversation_service.process_message(
        "missing", "ბანაკზე როგორ დავრეგისტრირდე?", "instagram",
    )
    assert "http" not in out, f"a link was invented: {out!r}"
    # Safe fallback: manager contact / ask for name + phone.
    assert ("მენეჯერ" in out) or ("ნომერ" in out)
    for age in _AGE_PHRASES:
        assert age not in out
    assert _MENU not in out
    assert engine_on == []                # still deterministic, no engine call


# =========================================================================
# Helper-level guards (kept minimal — the live-path tests above are primary).
# =========================================================================


@pytest.mark.parametrize("msg", _REGISTRATION_INPUTS)
def test_is_camp_registration_link_request_true(msg):
    assert parent_flow._is_camp_registration_link_request(msg) is True


@pytest.mark.parametrize("msg", [
    "ბანაკი მაინტერესებს",                  # general interest, not a link request
    "გამარჯობა",                            # greeting
    "ღონისძიებაზე როგორ დავრეგისტრირდე",    # adult event, no camp keyword
    "ბანაკის კონსულტაციაზე ჩამწერეთ",       # consultation booking, not a form link
    "რეგისტრაცია მინდა",                     # no camp context
    # Adversarial-review fixes (substring false-positives):
    "ბანაკზე უკვე ჩაწერილი ვარ",            # „already enrolled" — ჩაწერილი ≠ ჩაწერა
    "ბანაკის ფორმატი რა არის",              # „format" — ფორმატი ≠ ფორმა
])
def test_is_camp_registration_link_request_false(msg):
    assert parent_flow._is_camp_registration_link_request(msg) is False
