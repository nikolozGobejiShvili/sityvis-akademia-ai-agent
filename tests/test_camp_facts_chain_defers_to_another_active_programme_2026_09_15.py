"""With TWO camps active, naming one and then asking a bare follow-up leaked
the OTHER camp's hardcoded facts (measured 2026-09-15, in memory only, while
answering the operator's question about running two camps together).

    „ზამთრის ბანაკი"           -> winter camp overview                 (right)
    „ფასი რა არის?"            -> „ბანაკის ფასი არის 2150 ლარი…"        (wrong —
                                    that is the SUMMER camp's hardcoded price)

`_maybe_handle_camp_facts_chain` (exact-detail / repeat-price / camp-topic
facts) answers for the summer camp whenever it is active, with no check for
whether the conversation actually names it. Its own docstring says a turn
naming another programme "never arrives here" because `_is_dynamic_program_turn`
sends it to the engine first — true for the turn that DOES the naming, false
for every later turn that does not, because that gate reads only the CURRENT
message. `_maybe_handle_out_of_range_age` and `_maybe_handle_camp_status`
already carry the fix for exactly this shape of bug (2026-09-11/12); this
chain never got it.

Restoring the same symmetry here: one guard at the top of the chain, reusing
`_msg_names_other_program` / `_conversation_names_other_program` exactly as
those two already do. Only fires when the summer camp is ACTIVE alongside
another active programme — the summer-camp-alone and camp-off cases (Paris/
winter camp exclusively active) are unaffected, since `camp_off` already
silences the whole chain there.

Georgian strings are built from code points so no letter can drift.
"""
from __future__ import annotations

import dataclasses

import pytest

import app.config as config_module
from app.flows import parent_flow
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.services import admin_config_service as acs


def _ka(text: str) -> str:
    for ch in text:
        assert ord(ch) < 128 or 0x10D0 <= ord(ch) <= 0x10FF, repr(text)
    return text


CAMP = _ka("ბანაკი")
SUMMER_NAME = _ka("საზაფხულო " + CAMP)
WINTER_NAME = _ka("ზამთრის " + CAMP)
PRICE_Q = _ka("ფასი რა არის?")
FOOD_Q = _ka(
    "რამდენად კვება"
    " ირიბა დღეში?")  # how many meals a day


def _summer(status: str) -> dict:
    return {"id": "summer_camp", "type": "camp", "status": status,
            "name": SUMMER_NAME, "hashtags": [CAMP], "age_min": 9, "age_max": 17,
            "registration_status": "open" if status == "active" else "closed"}


def _winter(status: str = "active") -> dict:
    return {"id": "winter_camp", "type": "camp", "status": status,
            "name": WINTER_NAME, "hashtags": [CAMP], "age_min": 8, "age_max": 16,
            "registration_status": "open"}


@pytest.fixture
def panel(monkeypatch):
    def _install(sections, camp_status="active"):
        sections = list(sections)
        monkeypatch.setattr(acs, "load_sections",
                            lambda: [dict(s) for s in sections])
        monkeypatch.setattr(acs, "get_active_sections",
                            lambda: [dict(s) for s in sections
                                     if s.get("status") == "active"])
        monkeypatch.setattr(acs, "get_section",
                            lambda pid: next((dict(s) for s in sections
                                              if s["id"] == pid), None))
        monkeypatch.setattr(acs, "get_camp_status", lambda: camp_status)
        monkeypatch.setattr(acs, "is_camp_registration_open",
                            lambda: camp_status == "active")
        monkeypatch.setattr(acs, "get_camp_age_bounds", lambda: (9, 17))
        monkeypatch.setattr(acs, "get_manager_phone", lambda: "558 67 47 33")
        monkeypatch.setattr(acs, "render_template", lambda *a, **k: "")
        monkeypatch.setattr(parent_flow, "settings", dataclasses.replace(
            config_module.settings, USE_DYNAMIC_PROGRAMS=True))
    return _install


def _conv(*user_turns: str) -> Conversation:
    conv = Conversation(sender_id="two-camps", platform="messenger", segment="PARENT")
    conv.lead = Lead(sender_id="two-camps", platform="messenger", segment="PARENT")
    history = []
    for text in user_turns:
        history.append({"role": "user", "content": text})
        history.append({"role": "assistant", "content": "ok"})
    conv.history = history
    return conv


# ── the leak, reproduced ────────────────────────────────────────────────────

def test_a_price_question_after_naming_winter_camp_does_not_leak_summer_price(panel):
    panel([_summer("active"), _winter("active")])
    conv = _conv(WINTER_NAME)
    out = parent_flow._maybe_handle_camp_facts_chain(conv, PRICE_Q, camp_off=False)
    assert out is None, (
        "the chain must defer to the engine (which has the winter camp's own "
        f"facts), not answer for the summer camp; got: {out!r}"
    )


def test_an_exact_detail_question_after_naming_winter_camp_does_not_leak(panel):
    panel([_summer("active"), _winter("active")])
    conv = _conv(WINTER_NAME)
    out = parent_flow._maybe_handle_camp_facts_chain(conv, FOOD_Q, camp_off=False)
    assert out is None


def test_naming_the_summer_camp_itself_still_gets_its_own_answer(panel):
    """The guard must not silence the summer camp in its own conversation."""
    panel([_summer("active"), _winter("active")])
    conv = _conv(SUMMER_NAME)
    out = parent_flow._maybe_handle_camp_facts_chain(conv, PRICE_Q, camp_off=False)
    assert out is not None
    assert "2150" in out


def test_the_summer_camp_alone_is_unaffected(panel):
    """No second camp in the panel: nothing to defer to, byte-identical."""
    panel([_summer("active")])
    conv = _conv(PRICE_Q)
    out = parent_flow._maybe_handle_camp_facts_chain(conv, PRICE_Q, camp_off=False)
    assert out is not None
    assert "2150" in out


def test_camp_off_is_still_the_first_gate(panel):
    """When the summer camp itself is off, the chain is already silenced by
    `camp_off` — the new guard must not change that."""
    panel([_summer("ended"), _winter("active")], camp_status="ended")
    conv = _conv(WINTER_NAME)
    assert parent_flow._maybe_handle_camp_facts_chain(
        conv, PRICE_Q, camp_off=True) is None
