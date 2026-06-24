"""Wording Fixes (2026-06-11).

BUG 1 — ban the awkward „შეშფოთება" (concern / anxiety — wrong, alarming
word for a parent's camp goal) and the hallucinated „თქვენი ინფორმაცია
უკვე მაქვს ასაკისა და შეშფოთების შესახებ…" preamble from user-facing
PARENT booking replies. Deterministic sanitizer; the prompt is NOT changed.

BUG 2 — answer a subscribed user's „where will the notification arrive?"
question instead of redirecting it as off-topic.

All deterministic; no network.
"""

from __future__ import annotations

import pytest

from app.agent.llm.parent_llm_engine import sanitise_response_wording as san


_LIVE_BUG = (
    "თქვენი ინფორმაცია უკვე მაქვს ასაკისა და შეშფოთების შესახებ. "
    "მომწერეთ თქვენი სახელი და 9-ნიშნა საკონტაქტო ნომერი, რომ "
    "კონსულტაცია ჩავნიშნოთ."
)
_PRIVACY = (
    "თქვენი ინფორმაცია გამოიყენება მხოლოდ კონსულტაციისთვის და "
    "საჯაროდ არ გამოქვეყნდება."
)


# ===========================================================================
# BUG 1 — ban „შეშფოთება" / „info already known about age & concern" preamble
# ===========================================================================


def test_b1_01_live_bug_preamble_stripped():
    out = san(_LIVE_BUG)
    assert "შეშფოთება" not in out
    assert "ინფორმაცია უკვე მაქვს" not in out
    assert "ასაკისა და" not in out
    # The clean contact request survives.
    assert "მომწერეთ თქვენი სახელი და 9-ნიშნა საკონტაქტო ნომერი" in out


def test_b1_02_no_info_already_known_preamble():
    out = san("თქვენი ინფორმაცია უკვე მაქვს ასაკისა და მიზნის შესახებ. მომწერეთ ნომერი.")
    assert "ინფორმაცია უკვე მაქვს ასაკისა და" not in out
    assert "მომწერეთ ნომერი" in out


def test_b1_03_missing_both_asks_simply():
    msg = "მომწერეთ თქვენი სახელი და 9-ნიშნა საკონტაქტო ნომერი, რომ კონსულტაცია ჩავნიშნოთ."
    assert san(msg) == msg  # already clean — untouched


def test_b1_04_name_known_phone_missing_preserved():
    msg = "სახელი უკვე მაქვს. მომწერეთ 9-ნიშნა საკონტაქტო ნომერი, რომ კონსულტაცია ჩავნიშნოთ."
    out = san(msg)
    assert "სახელი უკვე მაქვს" in out  # legitimate name-known wording kept
    assert "9-ნიშნა საკონტაქტო ნომერი" in out


def test_b1_05_phone_known_name_missing_preserved():
    msg = "ნომერი მივიღე. მომწერეთ თქვენი სახელი, რომ კონსულტაცია ჩავნიშნოთ."
    assert san(msg) == msg


def test_b1_06_lizi_phone_still_parses():
    from app.flows.parent_flow import _parse_name_phone
    name, phone = _parse_name_phone("ლიზი 595999733")
    assert name == "ლიზი"
    assert phone == "595999733"


def test_b1_07_privacy_notice_survives_sanitiser():
    """Task 2 regression — the privacy notice must pass through unchanged
    (it has no „უკვე მაქვს" / „შეშფოთებ", so the concern strip ignores it)."""
    assert san(_PRIVACY) == _PRIVACY


def test_b1_08_name_already_known_wording_not_stripped():
    """The „სახელი უკვე ვიცი" logic (Live Bug 3 from an earlier task) must
    survive — only the age/concern preamble is targeted."""
    msg = "სახელი უკვე ვიცი. მომწერეთ 9-ნიშნა საკონტაქტო ნომერი."
    assert san(msg) == msg


def test_b1_09_residual_concern_word_replaced():
    out = san("გასაგებია თქვენი შეშფოთება ეკრანის შესახებ.")
    assert "შეშფოთება" not in out
    assert "მოლოდინი" in out


def test_b1_10_idempotent():
    once = san(_LIVE_BUG)
    assert san(once) == once


@pytest.mark.parametrize("msg", [
    # Adversarial-review regressions — these legitimate sentences contain
    # both „უკვე ვიცი" and „ასაკ" but lack the „ინფორმაცია" preamble anchor,
    # so they must be PRESERVED (the old regex over-stripped them to "").
    "სახელი უკვე ვიცი, რა არის ბავშვის ასაკი?",
    "ბავშვის ასაკი უკვე ვიცი, ხუთი წლის.",
    "სახელი უკვე მაქვს და ასაკიც ვიცი.",
])
def test_b1_11_legitimate_age_sentences_preserved(msg):
    assert san(msg) == msg


# ===========================================================================
# BUG 2 — answer „where will the notification arrive?" (not off-topic redirect)
# ===========================================================================

from app.models.conversation import Conversation
from app.models.lead import Lead


def test_b2_01_messenger_delivery_answer():
    from app.agent.llm.adult_llm_engine import (
        _maybe_handle_notification_delivery_question as h,
    )
    out = h("და სად მომივა შეტყობინება მესენჯერში?", "messenger")
    assert out is not None
    assert "Messenger" in out
    assert "ბილეთის ბმულს" in out


def test_b2_02_messenger_yes_confirm():
    from app.agent.llm.adult_llm_engine import (
        _maybe_handle_notification_delivery_question as h,
    )
    assert h("მესენჯერში მომივა?", "messenger") is not None


def test_b2_03_does_not_trigger_offtopic_redirect():
    from app.agent.llm.adult_llm_engine import (
        _maybe_handle_notification_delivery_question as h,
    )
    out = h("სად მივიღებ შეტყობინებას?", "messenger")
    assert out is not None
    assert "ამ კითხვაზე ვერ დაგეხმარებით" not in out


def test_b2_04_does_not_re_subscribe_and_skips_llm(monkeypatch):
    """Integration via run_adult_llm_turn: the delivery question is answered
    deterministically — the LLM is never reached and no subscribe is run."""
    from app.agent.llm import adult_llm_engine
    from app.services import adult_subscription_service, openai_service

    def _boom(*a, **k):
        raise AssertionError("LLM must not be reached for a delivery question")

    monkeypatch.setattr(openai_service, "chat_with_tools", _boom)

    sub = {"called": False}
    monkeypatch.setattr(
        adult_subscription_service, "subscribe",
        lambda **k: sub.__setitem__("called", True) or {"success": True},
    )

    conv = Conversation(sender_id="s_del", platform="messenger", segment="ADULT")
    conv.lead = Lead(sender_id="s_del", platform="messenger", segment="ADULT")
    conv.adult_subscription_status = "subscribed"
    out = adult_llm_engine.run_adult_llm_turn(
        user_message="და სად მომივა შეტყობინება მესენჯერში?",
        conversation=conv, lead=conv.lead, sender_id="s_del", platform="messenger",
    )
    assert "Messenger" in out
    assert "ამ კითხვაზე ვერ" not in out   # not off-topic
    assert sub["called"] is False          # not re-subscribed


def test_b2_05_platform_aware_instagram():
    from app.agent.llm.adult_llm_engine import (
        _maybe_handle_notification_delivery_question as h,
    )
    msg = "სად მომივა შეტყობინება?"
    assert "Instagram" in h(msg, "instagram")
    assert "Messenger" in h(msg, "messenger")


def test_b2_06_non_delivery_question_not_intercepted():
    from app.agent.llm.adult_llm_engine import (
        _maybe_handle_notification_delivery_question as h,
    )
    assert h("ბილეთის ფასი რა არის?", "messenger") is None
    assert h("კი გამომიგზავნეთ", "messenger") is None  # subscription consent, not delivery


def test_b2_07_whatsapp_platform_branch():
    """Adversarial-review regression: a WhatsApp user must NOT be told
    „Messenger-ში"."""
    from app.agent.llm.adult_llm_engine import (
        _maybe_handle_notification_delivery_question as h,
    )
    out = h("სად მომივა შეტყობინება?", "whatsapp")
    assert "WhatsApp" in out
    assert "Messenger" not in out
