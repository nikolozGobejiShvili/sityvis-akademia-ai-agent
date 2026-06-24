"""Selected-State Contract — Reasoning Layer Phase 3 Stage 2.1 (2026-06-24).

The live trace proved that raw, polluted lead/history state was handed to the
LLM as if every field were equally relevant — so a stale ``child_age=7`` leaked
into the adult-self flow and the agent risked treating the user as 7 years old.

This module is the SCOPING contract: given the planner's `TurnPlan` and the
lead, it returns ONLY the state fields that are relevant to the current turn —
a small, explicit dict the response layer (slim-prompt context builder, trace,
validator) consumes instead of the whole `lead`. It is PURE + metadata-only:
NEVER mutates the lead, NEVER calls the LLM / Calendar / Sheets, NEVER raises.

Contract (driven by `plan.state_to_use` which the planner already computes, with
a few topic-level safety rules layered on top):
  * ``adult_event_for_self`` → adult_age only; child_age is EXCLUDED.
  * camp / consultation       → child_age only; adult_age is EXCLUDED.
  * ``state_recall``          → BOTH child_age and adult_age, kept separate.
  * the phone is ALWAYS masked (last 3 digits) — never the full number.

The returned dict's keys mirror the planner's stable ``S_*`` identifiers so the
trace block and the validator can reason about exactly what the engine saw.
"""
from __future__ import annotations

import re

from app.reasoning import conversation_planner as cp


def _mask(phone: str) -> str:
    """Mask to ``…<last 3>`` (e.g. 595999733 → 595***733-style by reusing the
    project's recall mask when available; here a simple last-3 reveal)."""
    digits = re.sub(r"\D", "", phone or "")
    if not digits:
        return ""
    if len(digits) <= 3:
        return "***"
    return digits[:3] + "***" + digits[-3:] if len(digits) >= 6 else "***" + digits[-3:]


def build_selected_state(plan, lead, conversation=None) -> dict:
    """Return the scoped, only-relevant state for the current turn.

    Reads ``plan.state_to_use`` / ``plan.state_to_ignore`` (planner authority)
    and applies the adult/child separation safety rules on top. Pure; never
    raises (returns ``{}`` on any error)."""
    try:
        return _build(plan, lead, conversation)
    except Exception:  # pragma: no cover — selected-state must never break a reply
        return {}


def _build(plan, lead, conversation) -> dict:
    use = list(getattr(plan, "state_to_use", []) or [])
    ignore = set(getattr(plan, "state_to_ignore", []) or [])
    topic = getattr(plan, "active_topic", "none")
    intent = getattr(plan, "user_current_intent", "unclear")

    name = (getattr(lead, "name", "") or "").strip() if lead else ""
    phone = (getattr(lead, "phone", "") or "").strip() if lead else ""
    child_age = (getattr(lead, "child_age", "") or "").strip() if lead else ""
    adult_age = (getattr(lead, "adult_age", "") or "").strip() if lead else ""
    target_rel = (getattr(lead, "adult_target_relation", "") or "").strip() if lead else ""
    target_age = (getattr(lead, "adult_target_age", "") or "").strip() if lead else ""
    booked = False
    booked_iso = ""
    if lead is not None:
        booked = bool(getattr(lead, "calendly_booked", False)) or bool(
            (getattr(lead, "booked_datetime_iso", "") or "").strip()
        )
        booked_iso = (getattr(lead, "booked_datetime_iso", "") or "").strip()

    out: dict = {}

    # Identity (name + masked phone) — relevant whenever the planner asked for it
    # or for any non-adult-discovery turn (so camp/consultation/recall keep it).
    if cp.S_NAME in use or (name and topic != "adult_event"):
        if name:
            out[cp.S_NAME] = name
    if cp.S_PHONE in use or (phone and topic != "adult_event"):
        if phone:
            out[cp.S_PHONE] = _mask(phone)

    # ── adult/child age separation (the core of the contract) ────────────────
    want_child = (cp.S_CHILD_AGE in use) and (cp.S_CHILD_AGE not in ignore)
    want_adult = (cp.S_ADULT_AGE in use) and (cp.S_ADULT_AGE not in ignore)

    # Safety overlays the planner's lists with hard topic rules:
    if intent == "state_recall":
        # recall shows BOTH, kept under distinct keys.
        want_child, want_adult = bool(child_age), bool(adult_age)
    elif topic == "adult_event" and intent in (
        "adult_event_for_self", "adult_event_discovery", "adult_age_correction",
    ):
        # self / discovery flow: NEVER the child's age (the live leak).
        want_child = False
        want_adult = bool(adult_age) or want_adult
    elif topic in ("camp", "consultation"):
        # camp/consultation: child age only; the user's own adult age is
        # irrelevant and must not bleed in.
        want_adult = False
        want_child = bool(child_age) or want_child

    if want_child and child_age:
        out[cp.S_CHILD_AGE] = child_age
    if want_adult and adult_age:
        out[cp.S_ADULT_AGE] = adult_age

    # Adult-event relative target (only on a for-child / both adult turn).
    if cp.S_ADULT_TARGET not in ignore and topic == "adult_event" and (
        target_rel or target_age
    ):
        if target_rel:
            out["adult_target_relation"] = target_rel
        if target_age:
            out["adult_target_age"] = target_age

    # Confirmed booking — recall + booking-recall only.
    if booked and (
        cp.S_CONFIRMED_BOOKING in use or getattr(plan, "should_use_confirmed_booking", False)
    ):
        out[cp.S_CONFIRMED_BOOKING] = booked_iso or "booked"

    return out


def format_selected_state(selected: dict) -> str:
    """Render the selected-state dict as a compact LLM system block."""
    if not selected:
        return "SELECTED STATE: (ცარიელია — შესაბამისი მონაცემი არ არის)"
    parts = [f"{k}={v}" for k, v in selected.items()]
    return "SELECTED STATE (მხოლოდ ეს მონაცემია რელევანტური): " + "; ".join(parts)


def format_planner_policy(plan) -> str:
    """Render the planner decision as a compact LLM policy block (slim prompt)."""
    if plan is None:
        return "PLANNER POLICY: (none)"
    forb = ", ".join(getattr(plan, "forbidden_response_patterns", []) or []) or "—"
    return (
        "PLANNER POLICY (უპირობოდ დაიცავი): "
        f"active_topic={getattr(plan, 'active_topic', 'none')}; "
        f"intent={getattr(plan, 'user_current_intent', 'unclear')}; "
        f"answer_policy={getattr(plan, 'answer_policy', '')}; "
        f"forbidden=[{forb}]"
    )
