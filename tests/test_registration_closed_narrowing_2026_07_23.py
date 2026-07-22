"""Registration-closed catch-all narrowing — USE_REGISTRATION_CLOSED_NARROWING
(Step 4 increment 1, 2026-07-23).

When camp registration is closed, ``_maybe_handle_final_camp_public_policy`` used
a catch-all default that returned the blanket „registration closed" answer for
ANY camp-context turn that fell through to ``current_details_limited`` — including
a price objection („ცოტა ძვირია") and „ბანაკის გარდა კიდევ რა პროგრამები გაქვთ?"
(eval OB3 / PI2), a wrong-answer-to-the-question bleed. With the flag ON, that
catch-all DEFERS (returns None) so the engine answers the real question; a genuine
registration action (category ``registration_closed``) still gets the closed
answer. OFF ⇒ byte-identical.
"""
from __future__ import annotations

import dataclasses

import pytest

import app.config as config_module
from app.flows import parent_flow
from app.models.conversation import Conversation

_OBJECTION = "მოვიფიქრებ, ცოტა ძვირია"
_OTHER_PROGRAMS = "ბანაკის გარდა კიდევ რა პროგრამები გაქვთ?"
_REGISTRATION = "ბანაკზე რეგისტრაცია მინდა"


@pytest.fixture
def reg_closed(monkeypatch):
    """Force closed registration deterministically (independent of shipped config)."""
    monkeypatch.setattr(parent_flow, "_is_camp_registration_open", lambda: False)


def _set_flag(monkeypatch, value):
    swapped = dataclasses.replace(
        config_module.settings, USE_REGISTRATION_CLOSED_NARROWING=value)
    monkeypatch.setattr(parent_flow, "settings", swapped)


def _ob3_conv():
    c = Conversation(sender_id="ob3", platform="instagram", segment="PARENT")
    c.state = "ASK_CHALLENGE"
    c.history = [{"role": "assistant", "content": "ბანაკის ღირებულებაა 2150 ლარი."}]
    return c


def _pi2_conv():
    c = Conversation(sender_id="pi2", platform="instagram", segment="PARENT")
    c.state = "START"
    return c


# ── flag OFF (default) — byte-identical: catch-all returns the closed answer ──

def test_flag_off_objection_gets_registration_closed(reg_closed, monkeypatch):
    _set_flag(monkeypatch, False)
    out = parent_flow._maybe_handle_final_camp_public_policy(_ob3_conv(), _OBJECTION)
    assert out is not None and "რეგისტრაცია" in out


def test_flag_off_other_programs_gets_registration_closed(reg_closed, monkeypatch):
    _set_flag(monkeypatch, False)
    out = parent_flow._maybe_handle_final_camp_public_policy(_pi2_conv(), _OTHER_PROGRAMS)
    assert out is not None and "რეგისტრაცია" in out


# ── flag ON — the catch-all (current_details_limited) DEFERS to the engine ──

def test_flag_on_objection_defers(reg_closed, monkeypatch):
    _set_flag(monkeypatch, True)
    # sanity: the category IS the catch-all we target
    assert parent_flow._final_camp_public_policy_category(_ob3_conv(), _OBJECTION) == \
        parent_flow._FINAL_CAMP_POLICY_CURRENT_DETAILS_LIMITED
    assert parent_flow._maybe_handle_final_camp_public_policy(_ob3_conv(), _OBJECTION) is None


def test_flag_on_other_programs_defers(reg_closed, monkeypatch):
    _set_flag(monkeypatch, True)
    assert parent_flow._maybe_handle_final_camp_public_policy(_pi2_conv(), _OTHER_PROGRAMS) is None


# ── flag ON — a genuine registration action STILL gets the closed answer ──

def test_flag_on_registration_action_still_closed(reg_closed, monkeypatch):
    _set_flag(monkeypatch, True)
    c = Conversation(sender_id="reg", platform="instagram", segment="PARENT")
    c.state = "START"
    # a genuine registration request is category `registration_closed`, NOT the
    # narrowed catch-all — the flag must not touch it.
    assert parent_flow._final_camp_public_policy_category(c, _REGISTRATION) == \
        parent_flow._FINAL_CAMP_POLICY_REGISTRATION_CLOSED
    out = parent_flow._maybe_handle_final_camp_public_policy(c, _REGISTRATION)
    assert out is not None and "რეგისტრაცია" in out
