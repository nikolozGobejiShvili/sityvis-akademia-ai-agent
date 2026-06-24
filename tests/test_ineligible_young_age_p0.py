"""P0 Stabilization (2026-06-09) — ineligible-young deterministic message.

Targets the flaky CRITICAL scenario SC-06 ("Ineligible Age — 8 წლის").
Root cause: the existing `_strip_consultation_cta_if_ineligible` only
appended the manager-handoff line WHEN a booking CTA was present, so a
CTA-free-but-vague LLM reply for a sub-minimum-age child could omit the
explicit age boundary and/or the manager offer — intermittently failing
the assertion ("9" or "ასაკი") AND "მენეჯერ".

`_ensure_ineligible_young_age_message` closes the gap deterministically:
on the turn the parent discloses an age below `age_min`, the response is
replaced with a fixed message that always states the eligible range,
declines the booking, and offers the manager. Scope: age < age_min only.
Over-age (18+) and eligible (9–17) paths are untouched.
"""

from __future__ import annotations

import dataclasses
from types import SimpleNamespace
from typing import Any

import pytest

import app.config as config_module
from app.flows import parent_flow
from app.models.conversation import Conversation
from app.models.lead import Lead


# ---------------------------------------------------------------------------
# helpers / fixtures
# ---------------------------------------------------------------------------


def _conv_with_age(age: str, sender: str = "p0_user") -> Conversation:
    conv = Conversation(sender_id=sender, platform="instagram")
    conv.lead = Lead(
        sender_id=sender, platform="instagram", segment="PARENT",
        child_age=age,
    )
    return conv


def _swap_engine_flag(monkeypatch, value: bool) -> None:
    swapped = dataclasses.replace(
        config_module.settings, USE_PARENT_LLM_ENGINE=value,
    )
    monkeypatch.setattr(parent_flow, "settings", swapped)


def _mk_response(content: str) -> Any:
    """Minimal duck-typed OpenAI chat.completions response."""
    message = SimpleNamespace(content=content, tool_calls=[])
    choice = SimpleNamespace(message=message, finish_reason="stop")
    return SimpleNamespace(choices=[choice])


# The exact SC-06 failure mode: an ineligible reply that is polite but
# omits the manager offer (and the boundary), so the LLM-only path would
# fail the CRITICAL assertion.
_VAGUE_INELIGIBLE_REPLY = (
    "ბოდიში, მაგრამ ეს ბანაკი ამ შემთხვევაში არ მოერგება."
)


# ---------------------------------------------------------------------------
# 1. helper unit tests — under-min age guarantees the canonical message
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("age", ["8", "7", "6", "5", "3"])
def test_under_min_age_returns_canonical_message(age):
    conv = _conv_with_age(age)
    out = parent_flow._ensure_ineligible_young_age_message(
        conv, f"{age} წლის", _VAGUE_INELIGIBLE_REPLY,
    )
    # Must state the eligible range, decline, and offer the manager.
    assert "9" in out
    assert "17" in out
    assert "ასაკი" in out          # SC-06 any-of: "9" OR "ასაკი"
    assert "მენეჯერ" in out         # SC-06: MANAGER_OFFERED
    assert "ვერ შემოგთავაზებთ" in out  # clear cannot-offer wording
    # Forbidden booking-confirmation tokens must NOT appear.
    assert "ჩავნიშნ" not in out
    assert "კონსულტაციაზე ჩაგწერთ" not in out


def test_sc06_assertion_shape_satisfied():
    """Mirror the CRITICAL SC-06 assertion exactly:
    ("9" OR "ასაკი") AND ("მენეჯერ"), no forbidden tokens."""
    conv = _conv_with_age("8")
    out = parent_flow._ensure_ineligible_young_age_message(
        conv, "8 წლის", _VAGUE_INELIGIBLE_REPLY,
    )
    assert ("9" in out) or ("ასაკი" in out)
    assert "მენეჯერ" in out
    assert "კონსულტაციაზე ჩაგწერთ" not in out
    assert "ჩავნიშნ" not in out


# ---------------------------------------------------------------------------
# 2. eligible ages are never touched
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("age", ["9", "10", "14", "16", "17"])
def test_eligible_age_passthrough(age):
    conv = _conv_with_age(age)
    original = "ბანაკის ფასი 2150 ლარია. რა გაინტერესებთ?"
    out = parent_flow._ensure_ineligible_young_age_message(
        conv, f"{age} წლის", original,
    )
    assert out == original


def test_boundary_age_9_is_eligible_passthrough():
    """Exactly age_min (9) is eligible — must pass through untouched."""
    conv = _conv_with_age("9")
    original = "კარგი, 9 წელი ერგება ბანაკის ასაკობრივ ჩარჩოს."
    out = parent_flow._ensure_ineligible_young_age_message(
        conv, "9 წლის", original,
    )
    assert out == original


def test_boundary_age_17_is_eligible_passthrough():
    conv = _conv_with_age("17")
    original = "17 წელი ერგება ბანაკს. რა გაინტერესებთ?"
    out = parent_flow._ensure_ineligible_young_age_message(
        conv, "17 წლის", original,
    )
    assert out == original


# ---------------------------------------------------------------------------
# 3. over-age (18+) path is NOT changed by this helper
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("age", ["18", "25", "40"])
def test_over_max_age_passthrough(age):
    """Over-17 (e.g. 18) is handled by the adult-switch / over-17 wording
    elsewhere — this young-only guarantee must leave it untouched."""
    conv = _conv_with_age(age)
    original = (
        "18 წელი ბანაკის ასაკს სცდება. ზრდასრულთა ღონისძიებები გვაქვს."
    )
    out = parent_flow._ensure_ineligible_young_age_message(
        conv, f"{age} წლის", original,
    )
    assert out == original


# ---------------------------------------------------------------------------
# 4. unknown age + over-fire prevention
# ---------------------------------------------------------------------------


def test_unknown_age_passthrough():
    conv = _conv_with_age("")
    original = "გვითხარით, რამდენი წლისაა თქვენი შვილი?"
    out = parent_flow._ensure_ineligible_young_age_message(
        conv, "გამარჯობა", original,
    )
    assert out == original


def test_no_overfire_on_later_turn_without_age_disclosure():
    """An ineligible-young lead whose CURRENT message does not re-disclose
    the age (e.g. a thank-you turn) must NOT have its response replaced —
    otherwise every subsequent turn would repeat the boundary message."""
    conv = _conv_with_age("8")
    original = "მადლობა თქვენ. თუ კიდევ დაგჭირდებათ ინფორმაცია, მომწერეთ."
    out = parent_flow._ensure_ineligible_young_age_message(
        conv, "მადლობა", original,
    )
    assert out == original


def test_no_overfire_on_time_message():
    """A time like '16 საათზე' must not be read as an under-min age and
    must not overwrite the response (16 is not < 9 anyway, and the lead's
    own age governs the gate)."""
    conv = _conv_with_age("8")
    # Current message carries a time, not the age '8' → no replacement.
    original = "ეს დრო დაკავებულია. სხვა დროს შემოგთავაზებთ."
    out = parent_flow._ensure_ineligible_young_age_message(
        conv, "16 საათზე", original,
    )
    assert out == original


def test_fires_again_if_age_restated():
    """If the parent re-states the under-min age on a later turn, the
    guarantee correctly re-fires (re-confirming ineligibility)."""
    conv = _conv_with_age("8")
    out = parent_flow._ensure_ineligible_young_age_message(
        conv, "ჰო, 8 წლისაა", "კარგი.",
    )
    assert "მენეჯერ" in out
    assert "ვერ შემოგთავაზებთ" in out


# ---------------------------------------------------------------------------
# 5. end-to-end through parent_flow.handle (engine mocked to the SC-06
#    failure mode)
# ---------------------------------------------------------------------------


def test_end_to_end_under9_engine_vague_reply_gets_canonical(monkeypatch):
    """Engine returns the vague ineligible reply (no manager offer); the
    post-engine guarantee must rewrite it to the full SC-06-passing
    message. This is the exact live failure mode."""
    from app.services import messenger_service, openai_service

    _swap_engine_flag(monkeypatch, True)
    monkeypatch.setattr(
        messenger_service, "get_user_profile", lambda sid, plat: {},
    )
    monkeypatch.setattr(
        openai_service, "chat_with_tools",
        lambda **kwargs: _mk_response(_VAGUE_INELIGIBLE_REPLY),
    )

    conv = _conv_with_age("8", sender="p0_e2e")
    # Pre-seed an assistant turn so the static-welcome bypass does not
    # short-circuit the engine path (mirrors fresh_conversation seeding).
    conv.history.append({"role": "assistant", "content": "_prior"})

    out = parent_flow.handle(conv, "8 წლის")

    assert ("9" in out) or ("ასაკი" in out)
    assert "მენეჯერ" in out
    assert "კონსულტაციაზე ჩაგწერთ" not in out
    assert "ჩავნიშნ" not in out
    # The lead age is captured deterministically regardless of LLM.
    assert conv.lead.child_age.strip().startswith("8")


def test_end_to_end_eligible_14_not_overwritten(monkeypatch):
    """A 14-year-old (eligible) must keep the engine's response — the
    guarantee must not fire."""
    from app.services import messenger_service, openai_service

    _swap_engine_flag(monkeypatch, True)
    monkeypatch.setattr(
        messenger_service, "get_user_profile", lambda sid, plat: {},
    )
    eligible_reply = "14 წელი ერგება ბანაკს. ფასი 2150 ლარია."
    monkeypatch.setattr(
        openai_service, "chat_with_tools",
        lambda **kwargs: _mk_response(eligible_reply),
    )

    conv = _conv_with_age("14", sender="p0_e2e_ok")
    conv.history.append({"role": "assistant", "content": "_prior"})

    out = parent_flow.handle(conv, "14 წლის")
    # Canonical ineligible text must NOT appear for an eligible child.
    assert "ვერ შემოგთავაზებთ" not in out
