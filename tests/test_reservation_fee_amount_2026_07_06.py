"""Reservation / advance-payment FEE amount → manager defer (widening, 2026-07-06).

Live bug: the narrow „ჯავშ + რამდენ" detector missed advance-payment AMOUNT
questions phrased with „წინასწარ" (and the typo „წიანსწარ", and stretched text
like „ვიხდიიი"/„გააავიიგეეეე"), so the agent kept repeating the generic
payment-METHOD answer or gave the full camp price.

Required: any advance/reservation FEE AMOUNT question → the approved manager
defer „რაც შეეხება ჯავშნის საფასურს, ამ დეტალებს მენეჯერი გაგაცნობთ: 558 67 47 33".
The generic payment-METHOD answer stays only for method questions
(„როგორ ხდება გადახდა?" / „სრულად ვიხდი თუ ნაწილობრივ?").

Deterministic — the widened detector + a repeat-clarification path; no LLM call.
"""
from __future__ import annotations

import dataclasses

import pytest

import app.config as config_module
from app.flows import parent_flow
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.services import messenger_service

_DEFER = "რაც შეეხება ჯავშნის საფასურს, ამ დეტალებს მენეჯერი გაგაცნობთ: 558 67 47 33"
_GENERIC_PAYMENT = (
    "ბანაკის ჯავშნის საფასურის გადახდა ხდება წინასწარ, ხოლო სრული თანხის — "
    "ხელშეკრულებით გათვალისწინებულ დროში. თუ გსურთ, კონსულტაციაზე ჩაგწერთ."
)
_METHOD_FRAGMENT = "ჯავშნის საფასურის გადახდა ხდება წინასწარ"


def _conv(sid="fee", *, history=None) -> Conversation:
    c = Conversation(sender_id=sid, platform="instagram", segment="PARENT")
    c.lead = Lead(sender_id=sid, platform="instagram", segment="PARENT")
    for t in history or []:
        c.history.append(t)
    return c


def _fee(message, *, history=None):
    return parent_flow._maybe_handle_reservation_fee_question(
        _conv(history=history), message,
    )


# ── required tests 1–6 — amount questions → manager fallback ──────────────────
@pytest.mark.parametrize("msg", [
    "ჯავშნის საფასური რამდენია?",           # 1
    "რამდენს ვიხდი წინასწარ?",               # 2
    "წინასწარ რამდენს ვიხდი?",               # 3
    "რამდენს ვიხდი წიანსწარ?",               # 4 (typo)
    "რამდენი უნდა გადავიხადო წინასწარ?",
    "რამდენს ვიხდი ჯავშნისთვის?",
])
def test_amount_question_defers_to_manager(msg):
    assert _fee(msg) == _DEFER


# ── required tests 5–6 — frustration / stretched, after the generic answer ────
@pytest.mark.parametrize("msg", [
    "გავიგე, წინასწარ რამდენს ვიხდი?",                 # 5
    "გააავიიგეეეეე წინასწარ რამდენს ვიხდიიი???",       # 6 (stretched)
    "მადლობა, მაგრამ რამდენს ვიხდი წინასწარ?",
    "რამდენს ვიხდი?",                                   # bare, after generic answer
])
def test_repeat_amount_after_generic_answer_defers(msg):
    out = _fee(msg, history=[{"role": "assistant", "content": _GENERIC_PAYMENT}])
    assert out == _DEFER


def test_stretched_and_typo_defer_even_without_history():
    # 6 also fires on the base detector (has წინასწარ + amount), no history needed.
    assert _fee("გააავიიგეეეეე წინასწარ რამდენს ვიხდიიი???") == _DEFER
    # 4 typo normalises "წიანსწარ" → "წინასწარ".
    assert _fee("რამდენს ვიხდი წიანსწარ?") == _DEFER


# ── required test 7 — payment-METHOD question stays generic ───────────────────
@pytest.mark.parametrize("msg", [
    "როგორ ხდება გადახდა?",
    "როდის უნდა გადავიხადო?",
    "სრულად ვიხდი თუ ნაწილობრივ?",
])
def test_payment_method_question_not_hijacked(msg):
    assert _fee(msg) is None


# ── required test 8 — "თანხას სრულად ვიხდი?" generic, then amount → fallback ──
def test_sum_fully_question_generic_then_amount_defers():
    # The method question itself is generic (None) …
    assert _fee("თანხას სრულად ვიხდი?") is None
    # … but a follow-up advance-payment amount question defers.
    assert _fee(
        "რამდენს ვიხდი წინასწარ?",
        history=[{"role": "assistant", "content": _GENERIC_PAYMENT}],
    ) == _DEFER


# ── regression — camp / room questions not hijacked ──────────────────────────
def test_consultation_and_room_not_hijacked():
    assert _fee("რამდენი ღირს კონსულტაცია?") is None      # no advance cue
    assert _fee("ოთახში რამდენი ბავშვი იქნება?") is None   # room → operational defer


def test_normaliser_units():
    n = parent_flow._normalise_fee_text
    assert n("ვიხდიიი") == "ვიხდი"
    assert "წინასწარ" in n("წიანსწარ რამდენს")
    assert n("გააავიიგეეეეე") == "გავიგე"


# ── required tests 9–10 — end-to-end: generic answer NOT repeated ─────────────
@pytest.fixture
def engine_on(monkeypatch):
    swapped = dataclasses.replace(
        config_module.settings,
        USE_PARENT_LLM_ENGINE=True,
        USE_CONVERSATION_PLANNER=False,
        CONVERSATION_PLANNER_AUTHORITATIVE=False,
        USE_SLIM_PROMPTS=False,
    )
    monkeypatch.setattr(parent_flow, "settings", swapped)
    monkeypatch.setattr(messenger_service, "get_user_profile", lambda sid, plat: {})
    # If the reservation handler fails to preempt, the "engine" would answer with
    # the generic payment-method text — so a leak is detectable.
    monkeypatch.setattr(
        parent_flow, "_run_llm_engine_safely", lambda c, m: _GENERIC_PAYMENT,
    )
    return swapped


def test_e2e_amount_question_returns_manager_defer_not_generic(engine_on):
    conv = _conv("e2e", history=[
        {"role": "user", "content": "თანხას სრულად ვიხდი?"},
        {"role": "assistant", "content": _GENERIC_PAYMENT},
    ])
    out = parent_flow.handle(conv, "რამდენს ვიხდი წინასწარ?")
    # required 10 — the generic method answer must NOT be repeated …
    assert _METHOD_FRAGMENT not in out
    # required 9 — the manager fee defer is returned instead.
    assert out == _DEFER


def test_e2e_method_question_not_turned_into_defer(engine_on):
    conv = _conv("e2e2")
    out = parent_flow.handle(conv, "როგორ ხდება გადახდა?")
    # A pure method question is NOT hijacked into the fee defer.
    assert out != _DEFER
