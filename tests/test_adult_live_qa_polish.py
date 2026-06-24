"""ADULT Live QA Polish Patch — regression tests.

Covers the 4 live-bug fixes shipped on 2026-06-02:

  * Bug 1 — "თქვენთვისაა ღონისძიებები" sanitiser + correct phrasing
    in system_adult_v1.md.
  * Bug 2 — strict event-data grounding (no invented dates/prices,
    "ახლახან ზუსტდება" stripped, seed events marked inactive so they
    don't surface until the operator fills them).
  * Bug 3 — `lead.adult_age` separate from `lead.child_age`, saved
    via `save_adult_lead_info`, surfaced in engine context, reused
    so the engine never re-asks age, and transferred on PARENT→ADULT
    switch when child_age is outside the camp range.
  * Bug 4 — `_ensure_adult_intro_followup` appends a next question
    when the LLM produces just a bare confirmation.
  * Part 5 — privacy note rule for child-data triggers in PARENT
    system prompt.
"""

from __future__ import annotations

import textwrap

import pytest

from app.agent.llm import adult_llm_engine
from app.agent.llm.adult_llm_engine import (
    _ensure_adult_intro_followup,
    sanitise_adult_response,
)
from app.agent.tools import adult_tool_executor, parent_tool_executor
from app.agent.tools.adult_tool_executor import AdultToolExecutor
from app.agent.tools.adult_tools import (
    TOOL_GET_ADULT_EVENTS,
    TOOL_SAVE_ADULT_LEAD_INFO,
)
from app.agent.tools.parent_tool_executor import ParentToolExecutor
from app.agent.tools.parent_tools import TOOL_SWITCH_TO_ADULT_FLOW
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.services import admin_config_service


# =========================================================================
# Fixtures
# =========================================================================


@pytest.fixture(autouse=True)
def reset_state():
    adult_tool_executor.reset_state()
    parent_tool_executor.reset_state()
    yield
    adult_tool_executor.reset_state()
    parent_tool_executor.reset_state()


@pytest.fixture
def admin_yaml_with_full_event(monkeypatch, tmp_path):
    """One event fully populated, one with only title+min_age, one
    inactive — so we can probe each branch of the grounding rule."""
    yaml_text = textwrap.dedent(
        """\
        sections:
        - id: adult_events
          name: ზრდასრულთა ღონისძიებები
          type: adult_events
          status: active
          hashtags: [ღონისძიება]
          auto_dm_template_id: adult_events_comment_dm
          events:
          - id: full_event
            title: სრული ღონისძიება
            status: active
            min_age: 13
            date_text: 2026 წლის ივლისი
            location: თბილისი
            theme: ლიტერატურული შეხვედრა
            guest: გიორგი ხელაია
            format: დისკუსია
            price_text: 50 ლარი
            reservation_url: https://example.com/full
            seats_available: 20
          - id: bare_event
            title: მცირე ღონისძიება
            status: active
            min_age: 13
            date_text: ''
            location: ''
            theme: ''
            guest: ''
            format: ''
            price_text: ''
            reservation_url: ''
            seats_available: 0
          - id: hidden_event
            title: დამალული ღონისძიება
            status: inactive
            min_age: 13
            date_text: ''
        """,
    )
    sections_path = tmp_path / "sections.yaml"
    sections_path.write_text(yaml_text, encoding="utf-8")
    monkeypatch.setattr(admin_config_service, "SECTIONS_PATH", sections_path)
    return sections_path


def _make_adult_executor(lead: Lead | None = None) -> AdultToolExecutor:
    conv = Conversation(sender_id="s_polish", platform="instagram", segment="ADULT")
    if lead is None:
        lead = Lead(sender_id="s_polish", platform="instagram", segment="ADULT")
    conv.lead = lead
    return AdultToolExecutor(
        conversation=conv,
        lead=lead,
        sender_id="s_polish",
        platform="instagram",
    )


def _make_parent_executor(lead: Lead) -> ParentToolExecutor:
    conv = Conversation(sender_id="s_polish_p", platform="instagram", segment="PARENT")
    conv.lead = lead
    return ParentToolExecutor(
        conversation=conv,
        lead=lead,
        sender_id="s_polish_p",
        platform="instagram",
    )


# =========================================================================
# Phrasing — Bug 1
# =========================================================================


def test_sanitiser_rewrites_broken_who_question_long():
    """Live QA Session 7 Patch (2026-06-06) — Bug 3 revert: the adult
    „who is this for?" question must end with „თქვენი შვილისთვის?"
    (brand-owner-preferred form). The intermediate „სხვა
    ადამიანისთვის" wording is no longer the target."""
    bad = (
        "გასაგებია. თქვენთვისაა ღონისძიებები თუ თქვენი შვილისთვის? "
        "მითხარით, რომ ზუსტად შემოგთავაზოთ."
    )
    out = sanitise_adult_response(bad)
    assert "თქვენთვისაა ღონისძიებები" not in out
    assert "ღონისძიების შერჩევა თქვენთვის გსურთ თუ თქვენი შვილისთვის" in out


def test_sanitiser_rewrites_broken_who_question_short_form():
    bad = "თქვენთვისაა ღონისძიებები?"
    out = sanitise_adult_response(bad)
    assert "თქვენთვისაა ღონისძიებები" not in out
    assert "ღონისძიების შერჩევა თქვენთვის გსურთ" in out


def test_adult_prompt_documents_correct_who_phrasing():
    """The system prompt must teach the LLM the correct fall-back
    wording — otherwise the sanitiser sees the broken phrase too
    often. Belt-and-braces."""
    from app.agent.llm.prompt_loader import load_prompt, reset_cache
    reset_cache()
    text = load_prompt("system_adult_v1")
    assert "ღონისძიების შერჩევა თქვენთვის გსურთ" in text


def test_adult_prompt_documents_self_and_child_age_phrasings():
    from app.agent.llm.prompt_loader import load_prompt, reset_cache
    reset_cache()
    text = load_prompt("system_adult_v1")
    assert "რამდენი წლის ბრძანდებით?" in text
    assert "თქვენი შვილი რამდენი წლისაა?" in text


# =========================================================================
# Event grounding — Bug 2
# =========================================================================


def test_sanitiser_strips_ahla_xan_zustdeba():
    bad = "ღონისძიება საინტერესოა. თარიღები და ფასები ახლახან ზუსტდება."
    out = sanitise_adult_response(bad)
    assert "ახლახან ზუსტდება" not in out
    assert "თარიღები და ფასები ახლახან ზუსტდება" not in out


def test_bare_event_returns_empty_fields_no_invention(
    admin_yaml_with_full_event,
):
    executor = _make_adult_executor()
    result = executor.execute(TOOL_GET_ADULT_EVENTS, {})
    by_id = {e["id"]: e for e in result["events"]}
    bare = by_id["bare_event"]
    assert bare["date_text"] == ""
    assert bare["location"] == ""
    assert bare["theme"] == ""
    assert bare["price_text"] == ""
    assert bare["has_reservation_url"] is False


def test_full_event_returns_configured_fields(admin_yaml_with_full_event):
    executor = _make_adult_executor()
    result = executor.execute(TOOL_GET_ADULT_EVENTS, {})
    by_id = {e["id"]: e for e in result["events"]}
    full = by_id["full_event"]
    assert full["date_text"] == "2026 წლის ივლისი"
    assert full["location"] == "თბილისი"
    assert full["theme"] == "ლიტერატურული შეხვედრა"
    assert full["guest"] == "გიორგი ხელაია"
    assert full["price_text"] == "50 ლარი"


def test_inactive_event_hidden(admin_yaml_with_full_event):
    executor = _make_adult_executor()
    result = executor.execute(TOOL_GET_ADULT_EVENTS, {})
    ids = {e["id"] for e in result["events"]}
    assert "hidden_event" not in ids


def test_live_seed_events_inactive_until_operator_populates():
    """The two seed events shipped in `data/admin_config/sections.yaml`
    (poetry_evening + book_club) MUST be `status: inactive` so they
    don't surface placeholders to live users. Operator activates them
    via Admin Panel once real dates/prices/etc. are filled.
    """
    events = admin_config_service.get_adult_events()
    by_id = {e["id"]: e for e in events}
    if "poetry_evening" in by_id:
        assert by_id["poetry_evening"]["active"] is False, (
            "Seed event poetry_evening must be inactive."
        )
    if "book_club" in by_id:
        assert by_id["book_club"]["active"] is False, (
            "Seed event book_club must be inactive."
        )


def test_adult_prompt_documents_strict_grounding_rule():
    from app.agent.llm.prompt_loader import load_prompt, reset_cache
    reset_cache()
    text = load_prompt("system_adult_v1")
    # The "do not invent" rule paragraph must mention the manager-handoff
    # wording for empty fields.
    assert "ამ დეტალს მენეჯერი დაგიზუსტებთ" in text
    # And the banned placeholder must be explicitly called out.
    assert "ახლახან ზუსტდება" in text


# =========================================================================
# Age memory — Bug 3
# =========================================================================


def test_lead_has_dedicated_adult_age_field():
    lead = Lead(sender_id="s", platform="instagram", segment="ADULT")
    assert hasattr(lead, "adult_age")
    assert lead.adult_age == ""
    # Strict separation invariant.
    assert lead.child_age == ""


def test_lead_adult_age_round_trips_via_dict():
    lead = Lead(
        sender_id="s", platform="instagram", segment="ADULT", adult_age="30",
    )
    payload = lead.model_dump(mode="json")
    restored = Lead.from_dict(payload)
    assert restored.adult_age == "30"
    assert restored.child_age == ""


def test_save_adult_lead_info_stores_adult_age(admin_yaml_with_full_event):
    executor = _make_adult_executor()
    result = executor.execute(
        TOOL_SAVE_ADULT_LEAD_INFO, {"adult_age": "30"},
    )
    assert result["success"] is True
    assert "adult_age" in result["saved_fields"]
    assert executor.lead.adult_age == "30"
    # Strict separation: NEVER writes to child_age.
    assert executor.lead.child_age == ""


def test_save_adult_lead_info_rejects_garbage_adult_age(
    admin_yaml_with_full_event,
):
    executor = _make_adult_executor()
    result = executor.execute(
        TOOL_SAVE_ADULT_LEAD_INFO, {"adult_age": "not-a-number"},
    )
    assert "adult_age" in result.get("invalid_fields", [])
    assert executor.lead.adult_age == ""


def test_get_adult_events_uses_stored_adult_age_when_llm_omits_it(
    admin_yaml_with_full_event,
):
    """If the LLM forgets to pass `user_age`, the executor must read
    `lead.adult_age` so filtering still works."""
    lead = Lead(
        sender_id="s", platform="instagram", segment="ADULT",
        adult_age="13",
    )
    executor = _make_adult_executor(lead=lead)
    result = executor.execute(TOOL_GET_ADULT_EVENTS, {})
    # User age 13 should see all `min_age: 13` events.
    ids = {e["id"] for e in result["events"]}
    assert ids == {"full_event", "bare_event"}
    assert result["user_age"] == 13


def test_context_block_surfaces_adult_age():
    conv = Conversation(sender_id="s", platform="instagram", segment="ADULT")
    lead = Lead(
        sender_id="s", platform="instagram", segment="ADULT", adult_age="30",
    )
    conv.lead = lead
    block = adult_llm_engine._build_context_message(conv, lead)
    assert "adult_age=30" in block


def test_context_block_marks_missing_adult_age_with_dash():
    conv = Conversation(sender_id="s", platform="instagram", segment="ADULT")
    lead = Lead(sender_id="s", platform="instagram", segment="ADULT")
    conv.lead = lead
    block = adult_llm_engine._build_context_message(conv, lead)
    assert "adult_age=—" in block


# =========================================================================
# PARENT→ADULT switch transfers age — Bug 3
# =========================================================================


def test_switch_to_adult_flow_transfers_age_outside_camp_range():
    """child_age=25 is outside the camp range [9, 17]. The switch
    helper must transfer it to lead.adult_age AND clear lead.child_age
    so the PARENT flow never reads a 25-year-old as a child later.
    """
    lead = Lead(
        sender_id="s", platform="instagram", segment="PARENT",
        child_age="25",
    )
    executor = _make_parent_executor(lead)
    result = executor.execute(TOOL_SWITCH_TO_ADULT_FLOW, {})

    assert result["success"] is True
    assert lead.adult_age == "25"
    assert lead.child_age == ""
    assert result.get("transferred_adult_age") == "25"


def test_switch_to_adult_flow_keeps_in_range_child_age():
    """child_age=12 is inside the camp range — the parent may have a
    12-year-old AND a separate interest in adult events. The two
    fields stay independent: NO transfer.
    """
    lead = Lead(
        sender_id="s", platform="instagram", segment="PARENT",
        child_age="12",
    )
    executor = _make_parent_executor(lead)
    result = executor.execute(TOOL_SWITCH_TO_ADULT_FLOW, {})

    assert result["success"] is True
    assert lead.adult_age == ""
    assert lead.child_age == "12"
    assert result.get("transferred_adult_age") in (None, "")


def test_switch_to_adult_flow_no_child_age_yields_no_transfer():
    lead = Lead(
        sender_id="s", platform="instagram", segment="PARENT",
        child_age="",
    )
    executor = _make_parent_executor(lead)
    result = executor.execute(TOOL_SWITCH_TO_ADULT_FLOW, {})

    assert result["success"] is True
    assert lead.adult_age == ""
    assert lead.child_age == ""


# =========================================================================
# Transition follow-up — Bug 4
# =========================================================================


def test_intro_followup_appends_question_when_bare_confirmation():
    lead = Lead(sender_id="s", platform="instagram", segment="ADULT")
    response = "გასაგებია, ზრდასრულთა ღონისძიებებზე დაგეხმარებით."
    out = _ensure_adult_intro_followup(response, lead)
    assert "?" in out
    assert "ღონისძიების შერჩევა თქვენთვის გსურთ" in out


def test_intro_followup_offers_event_list_when_age_known():
    lead = Lead(
        sender_id="s", platform="instagram", segment="ADULT", adult_age="30",
    )
    response = "გასაგებია, ზრდასრულთა ღონისძიებებზე დაგეხმარებით."
    out = _ensure_adult_intro_followup(response, lead)
    assert "გნებავთ" in out or "ღონისძიებები" in out
    assert "?" in out


def test_intro_followup_passthrough_when_response_already_has_question():
    """If the LLM produced a real reply with a question, the guard
    must NOT touch it."""
    lead = Lead(sender_id="s", platform="instagram", segment="ADULT")
    response = (
        "გასაგებია, ზრდასრულთა ღონისძიებებზე დაგეხმარებით. "
        "რომელი თემა გაინტერესებთ?"
    )
    out = _ensure_adult_intro_followup(response, lead)
    assert out == response


def test_intro_followup_passthrough_for_long_responses():
    """A long response (>120 chars) is already substantive — guard
    must NOT append."""
    lead = Lead(sender_id="s", platform="instagram", segment="ADULT")
    response = (
        "გასაგებია, ზრდასრულთა ღონისძიებებზე დაგეხმარებით. "
        "ჩვენი მიმდინარე პროგრამა მოიცავს ლიტერატურულ შეხვედრებს, "
        "პოეზიის საღამოებსა და დისკუსიებს."
    )
    out = _ensure_adult_intro_followup(response, lead)
    assert out == response


def test_intro_followup_no_match_means_passthrough():
    """Generic response without the bare-intro pattern — guard
    must NOT touch."""
    lead = Lead(sender_id="s", platform="instagram", segment="ADULT")
    response = "გასაგებია, მოგწერთ მალე."
    out = _ensure_adult_intro_followup(response, lead)
    assert out == response


# =========================================================================
# Privacy note — Part 5
# =========================================================================


def test_parent_prompt_documents_privacy_note():
    from app.agent.llm.prompt_loader import load_prompt, reset_cache
    reset_cache()
    text = load_prompt("system_parent_v2")
    # The privacy-note rule section must exist with the literal phrase.
    assert "თქვენი ინფორმაცია გამოიყენება მხოლოდ კონსულტაციისთვის" in text
    # And the "რატო გჭირდება ასაკი?" handler.
    assert "რატო გჭირდება ასაკი" in text or "რად გჭირდებათ" in text


def test_parent_prompt_privacy_note_has_trigger_list():
    """The prompt must list the FOUR triggers and EXCLUDE adult-self
    contexts, off-topic redirects, every-turn use, recent-repeat."""
    from app.agent.llm.prompt_loader import load_prompt, reset_cache
    reset_cache()
    text = load_prompt("system_parent_v2")
    # Trigger evidence.
    assert "ბავშვის ასაკი" in text
    assert "ბავშვის გამოწვევას" in text or "ბავშვის გამოწვევა" in text
    # Recent-repeat suppression evidence.
    assert "ბოლო 3 ბრუნვაში" in text or "ბოლო 3" in text


def test_adult_prompt_does_not_include_child_privacy_note():
    """The ADULT prompt must NOT carry the child-data privacy note —
    that's a PARENT-flow concept. An adult buying an event ticket for
    themselves doesn't need the child-data reassurance.
    """
    from app.agent.llm.prompt_loader import load_prompt, reset_cache
    reset_cache()
    text = load_prompt("system_adult_v1")
    # The child-data privacy note phrase must NOT appear in the ADULT
    # system prompt.
    assert "თქვენი ინფორმაცია გამოიყენება მხოლოდ კონსულტაციისთვის" not in text
