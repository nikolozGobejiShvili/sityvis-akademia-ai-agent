"""Transport / logistics question must be answered as transport, never sports.

Live bug: „მე თელავში ვცხოვრობ და ტრანსპორტირება როგორ მოხდება?" got the sports/
activity answer. Root cause: the sports camp-topic keyword „სპორტ" is a SUBSTRING
of „ტრან·სპორტ·ირება", so every transport question matched the sports topic.

Fix: a deterministic transport/logistics interceptor (runs before the operational
/ camp-topic handlers) that answers with the KNOWN fact (transport is included in
the camp price) + a manager defer for the unknown exact regional pickup/route,
and corrects a „სპორტი რა შუაშია?" challenge after a wrong sports reply. A real
sports question still gets the sports answer. Deterministic — no LLM call.
"""
from __future__ import annotations

import dataclasses

import pytest

import app.config as config_module
from app.flows import parent_flow
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.services import messenger_service

_SPORTS = "სპორტული აქტივობები"
_SPORTS_ANSWER = (
    "დიახ, პროგრამაში გათვალისწინებულია სპორტული აქტივობები და ჯანსაღი "
    "ცხოვრების წესთან დაკავშირებული გამოცდილებები."
)
_MANAGER = "558 67 47 33"
_INCLUDED = "ბანაკის ღირებულებაში ტრანსპორტირება შედის"


def _conv(sid="tr", *, history=None) -> Conversation:
    c = Conversation(sender_id=sid, platform="instagram", segment="PARENT")
    c.lead = Lead(sender_id=sid, platform="instagram", segment="PARENT")
    for t in history or []:
        c.history.append(t)
    return c


def _tr(message, *, history=None):
    return parent_flow._maybe_handle_transport_logistics(_conv(history=history), message)


# ── required 1 — city transport question → Telavi-specific, NOT sports ────────
def test_city_transport_question_transport_not_sports():
    out = _tr("მე თელავში ვცხოვრობ და ტრანსპორტირება როგორ მოხდება?")
    assert out is not None
    assert _INCLUDED in out
    assert "თელავიდან" in out
    assert _MANAGER in out
    assert _SPORTS not in out


# ── required 2 — repeating the same transport question → still transport ──────
def test_repeated_transport_question_still_transport():
    q = "მე თელავში ვცხოვრობ და ტრანსპორტირება როგორ მოხდება?"
    first = _tr(q)
    second = _tr(q, history=[
        {"role": "user", "content": q},
        {"role": "assistant", "content": first},
    ])
    assert second == first
    assert _SPORTS not in second


# ── required 3 — "სპორტი რა შუაშია?" after wrong sports → correction ─────────
def test_sports_challenge_after_wrong_answer_corrects_to_transport():
    hist = [
        {"role": "user", "content": "მე თელავში ვცხოვრობ და ტრანსპორტირება როგორ მოხდება?"},
        {"role": "assistant", "content": _SPORTS_ANSWER},
    ]
    out = _tr("სპორტი რა შუაშია?", history=hist)
    assert out is not None
    assert out.startswith("მართალი ხართ, ტრანსპორტირებაზე მეკითხებოდით.")
    assert _INCLUDED in out
    assert "თელავიდან" in out
    assert _MANAGER in out
    # It must NOT repeat the sports answer.
    assert _SPORTS not in out


def test_sports_challenge_without_transport_context_defers():
    # A bare „სპორტი რა შუაშია?" with no transport context is NOT hijacked
    # (nothing to correct) → None (normal flow).
    assert _tr("სპორტი რა შუაშია?") is None


# ── required 4 — generic transport question ──────────────────────────────────
def test_generic_transport_question():
    out = _tr("ტრანსპორტირება როგორ მოხდება?")
    assert out == (
        "ბანაკის ღირებულებაში ტრანსპორტირება შედის. "
        "ტრანსპორტირების ზუსტ დეტალებს მენეჯერი გაგაცნობთ: " + _MANAGER
    )
    assert _SPORTS not in out


# ── required 5 — pickup-location question ─────────────────────────────────────
def test_pickup_location_question():
    out = _tr("ტრანსპორტი საიდან გადის?")
    assert out == (
        "ბანაკის ღირებულებაში ტრანსპორტირება შედის. "
        "რაც შეეხება ტრანსპორტის გასვლის ზუსტ ადგილს და დროს, "
        "ამ დეტალებს მენეჯერი გაგაცნობთ: " + _MANAGER
    )


# ── required 6 — real sports question still gets the sports answer ───────────
def test_transport_interceptor_ignores_real_sports_question():
    assert _tr("სპორტული აქტივობები არის?") is None
    assert _tr("ვარჯიში იქნება?") is None


def test_sports_answer_still_available_end_to_end(monkeypatch):
    swapped = dataclasses.replace(
        config_module.settings, USE_PARENT_LLM_ENGINE=True,
        USE_CONVERSATION_PLANNER=False, CONVERSATION_PLANNER_AUTHORITATIVE=False,
        USE_SLIM_PROMPTS=False,
    )
    monkeypatch.setattr(parent_flow, "settings", swapped)
    monkeypatch.setattr(messenger_service, "get_user_profile", lambda s, p: {})
    # a prior assistant turn so the static welcome doesn't own the turn.
    conv = _conv("sp", history=[{"role": "assistant", "content": "_prior"}])
    out = parent_flow.handle(conv, "სპორტული აქტივობები არის?")
    assert _SPORTS in out


# ── required 7 — existing unknown-detail (room) fallback intact ──────────────
def test_room_detail_fallback_intact():
    out = parent_flow._maybe_handle_unknown_operational_early(
        _conv(), "ოთახში რამდენი ბავშვი იქნება?",
    )
    assert out is not None and "მენეჯერი გაგაცნობთ" in out and _MANAGER in out
    # transport handler must NOT hijack the room question.
    assert _tr("ოთახში რამდენი ბავშვი იქნება?") is None


# ── required 8 — existing reservation-fee fix intact ─────────────────────────
def test_reservation_fee_fallback_intact():
    out = parent_flow._maybe_handle_reservation_fee_question(
        _conv(), "რამდენს ვიხდი წინასწარ?",
    )
    assert out == (
        "რაც შეეხება ჯავშნის საფასურს, ამ დეტალებს მენეჯერი გაგაცნობთ: " + _MANAGER
    )
    # transport handler must NOT hijack the fee question.
    assert _tr("რამდენს ვიხდი წინასწარ?") is None


# ── end-to-end — transport preempts the sports answer ────────────────────────
@pytest.fixture
def engine_sports(monkeypatch):
    swapped = dataclasses.replace(
        config_module.settings, USE_PARENT_LLM_ENGINE=True,
        USE_CONVERSATION_PLANNER=False, CONVERSATION_PLANNER_AUTHORITATIVE=False,
        USE_SLIM_PROMPTS=False,
    )
    monkeypatch.setattr(parent_flow, "settings", swapped)
    monkeypatch.setattr(messenger_service, "get_user_profile", lambda s, p: {})
    # If the transport interceptor fails to preempt, this "engine" leaks sports.
    monkeypatch.setattr(parent_flow, "_run_llm_engine_safely", lambda c, m: _SPORTS_ANSWER)
    return swapped


@pytest.mark.parametrize("msg", [
    "მე თელავში ვცხოვრობ და ტრანსპორტირება როგორ მოხდება?",
    "ტრანსპორტირება როგორ მოხდება?",
    "ტრანსპორტი საიდან გადის?",
])
def test_e2e_transport_never_sports(engine_sports, msg):
    out = parent_flow.handle(_conv(), msg)
    assert _INCLUDED in out
    assert _MANAGER in out
    assert _SPORTS not in out


def test_e2e_correction_never_repeats_sports(engine_sports):
    hist = [
        {"role": "user", "content": "მე თელავში ვცხოვრობ და ტრანსპორტირება როგორ მოხდება?"},
        {"role": "assistant", "content": _SPORTS_ANSWER},
    ]
    out = parent_flow.handle(_conv("corr", history=hist), "სპორტი რა შუაშია?")
    assert out.startswith("მართალი ხართ, ტრანსპორტირებაზე მეკითხებოდით.")
    assert "თელავიდან" in out
    assert _SPORTS not in out
