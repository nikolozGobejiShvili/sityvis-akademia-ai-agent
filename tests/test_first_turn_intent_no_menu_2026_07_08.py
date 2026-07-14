"""First-turn intent → no-menu tests (2026-07-08).

Bug: `_maybe_static_welcome` showed the two-option camp/adult disambiguation menu
on the bot's FIRST reply for ANY first message lacking an explicit camp-intent
marker — so a clear first-turn PRICE / ADULT-events / camp-INFO question got the
menu instead of a real answer. The fix adds specific-intent YIELDS (return None)
so the real handler answers, while a BARE greeting / BARE topic word / vague
opener STILL shows the menu.

Two layers of tests:
  * DIRECT `_maybe_static_welcome` — pure, deterministic, no LLM (the fix itself).
  * FULL-FLOW `parent_flow.handle` (legacy path, LLM seam mocked) — confirms the
    reply is not the menu and the price answer surfaces end-to-end.
"""
from __future__ import annotations

import pytest

from app.flows import parent_flow
from app.models.conversation import Conversation

# A distinctive substring of the two-option PARENT_WELCOME disambiguation menu.
MENU_MARKER = "ზრდასრულთა კულტურული საღამოები"


def _fresh() -> Conversation:
    """A fresh PARENT conversation: state=START, no assistant reply yet."""
    c = Conversation(sender_id="ft-test", platform="instagram")
    c.segment = "PARENT"
    assert c.state == "START"          # precondition the static welcome needs
    return c


# ── DIRECT: _maybe_static_welcome yields for a clear specific intent ──────────
@pytest.mark.parametrize("msg", [
    "ბანაკის შესახებ მინდოდა კითხვა",                    # camp-INFO (past-tense want)
    "ზრდასრულებისთვის კულტურული ღონისძიებები თუ გაქვთ?",  # adult events
    "ფასი მაინტერესებს",                                  # price (no camp keyword)
    "რა ღირს ბანაკი და გადანაწილება?",                    # camp price
])
def test_clear_first_turn_intent_yields_not_menu(msg):
    assert parent_flow._maybe_static_welcome(_fresh(), msg) is None


# ── DIRECT COUNTERS: bare greeting / bare topic / vague opener STILL menu ─────
@pytest.mark.parametrize("msg", [
    "გამარჯობა",              # bare greeting
    "ბანაკი",                 # bare topic word (no question / marker)
    "გამარჯობა, როგორ ხართ?",  # vague, non-intent opener
])
def test_bare_or_vague_first_turn_still_shows_menu(msg):
    out = parent_flow._maybe_static_welcome(_fresh(), msg)
    assert out is not None
    assert MENU_MARKER in out


# ── DIRECT: the narrow adult-events helper is conservative ───────────────────
def test_adult_events_helper_requires_adult_and_event_marker():
    f = parent_flow._first_turn_adult_events_intent
    assert f("ზრდასრულებისთვის კულტურული ღონისძიება") is True
    assert f("ზრდასრულთა საღამო მაინტერესებს") is True
    # adult word alone (no event/culture) → NOT an adult-events opener
    assert f("ზრდასრული ვარ, ბანაკი მაინტერესებს") is False
    # event/culture word without the adult marker → NOT (stays ambiguous → menu)
    assert f("კულტურული ღონისძიება მაინტერესებს") is False


# ── DIRECT: the broadened camp-INFO markers cover the missed phrasings ────────
def test_camp_info_marker_extension_yields_but_bare_keyword_menus():
    y = parent_flow._has_explicit_georgian_camp_intent
    assert y("ბანაკის შესახებ მინდოდა კითხვა") is True   # שესახებ + მინდოდა
    assert y("ბანაკზე მაქვს კითხვა") is True              # კითხვა
    assert y("ბანაკის შესახებ") is True                   # შესახებ
    # a bare camp keyword with NO marker must STILL be ambiguous (→ menu)
    assert y("ბანაკი") is False
    # the new markers require a camp keyword (no camp word → not camp intent)
    assert y("შესახებ მაქვს კითხვა") is False


# ── FULL-FLOW (legacy path, engine OFF via conftest; LLM seams mocked) ────────
def _mock_llm(monkeypatch, start_intent):
    """Pin the LLM seams so the full flow is deterministic + makes no live call."""
    from app.services import messenger_service, openai_service
    monkeypatch.setattr(openai_service, "detect_start_intent", lambda m: start_intent)
    monkeypatch.setattr(
        openai_service, "chat_with_tools",
        lambda **k: pytest.fail("engine/LLM must not run for a first-turn intent"))
    monkeypatch.setattr(messenger_service, "get_user_profile", lambda *a, **k: {})
    # Guard the GREETING-branch composer too (only hit if a message reaches it).
    monkeypatch.setattr(
        parent_flow, "_compose_or_fallback",
        lambda **k: "ბანაკის შესახებ მოკლე ინფორმაცია.")


def test_fullflow_price_first_turn_answers_price_not_menu(monkeypatch):
    _mock_llm(monkeypatch, "PRICE")
    out = parent_flow.handle(_fresh(), "ფასი მაინტერესებს")
    assert MENU_MARKER not in out
    assert "2150" in out


def test_fullflow_camp_info_first_turn_not_menu(monkeypatch):
    _mock_llm(monkeypatch, "INFO")
    out = parent_flow.handle(_fresh(), "ბანაკის შესახებ მინდოდა კითხვა")
    assert MENU_MARKER not in out


def test_fullflow_adult_events_first_turn_not_menu(monkeypatch):
    _mock_llm(monkeypatch, "INFO")
    out = parent_flow.handle(_fresh(), "ზრდასრულებისთვის კულტურული ღონისძიებები თუ გაქვთ?")
    assert MENU_MARKER not in out


def test_fullflow_bare_greeting_still_menu(monkeypatch):
    _mock_llm(monkeypatch, "GREETING")
    out = parent_flow.handle(_fresh(), "გამარჯობა")
    assert MENU_MARKER in out


def test_fullflow_bare_topic_word_uses_final_camp_policy(monkeypatch):
    _mock_llm(monkeypatch, "GREETING")
    out = parent_flow.handle(_fresh(), "ბანაკი")
    assert out == parent_flow._camp_registration_closed_answer()
    assert MENU_MARKER not in out
