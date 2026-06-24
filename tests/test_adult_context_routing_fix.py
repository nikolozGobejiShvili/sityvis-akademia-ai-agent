"""ADULT Context Routing Fix — child_age vs adult/other-person age.

Covers the 2026-06-02 bug-fix triplet:

  PART 1 — ADULT transition follow-up never dead-ends. Broader pattern
           detection (acknowledgement + adult-event vocab + no question)
           appends the appropriate next-step question.

  PART 2 — `child_age` from a prior PARENT/camp turn is NOT used as
           the eligibility age for ADULT events unless the user
           explicitly says the event is for that child.

  PART 3 — Relative cues like „ჩემი დისთვის" / „ჩემი ძმისთვის" /
           „მეგობრისთვის" stay in the ADULT flow. The deterministic
           parent-switch guard NEVER fires on these alone.

  PART 4 — `lead.adult_target_relation` and `lead.adult_target_age`
           round-trip via dict / from_dict and feed back into the
           `_get_adult_events` eligibility filter.
"""

from __future__ import annotations

import textwrap

import pytest

from app.agent.llm import adult_llm_engine
from app.agent.llm.adult_llm_engine import (
    _ensure_adult_intro_followup,
    _looks_like_bare_intro,
    _maybe_capture_adult_target,
    _user_wants_parent_flow,
)
from app.agent.tools import adult_tool_executor
from app.agent.tools.adult_tool_executor import AdultToolExecutor
from app.agent.tools.adult_tools import (
    TOOL_GET_ADULT_EVENTS,
    TOOL_SAVE_ADULT_LEAD_INFO,
)
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.services import admin_config_service


# =========================================================================
# Fixtures
# =========================================================================


@pytest.fixture(autouse=True)
def reset_state():
    adult_tool_executor.reset_state()
    yield
    adult_tool_executor.reset_state()


@pytest.fixture
def admin_yaml_age13_event(monkeypatch, tmp_path):
    """One active event with min_age=13."""
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
          - id: cultural_evening
            title: კულტურული საღამო
            status: active
            min_age: 13
            date_text: 2026 წლის ივლისი
            location: თბილისი
            theme: ლიტერატურა
            guest: ''
            format: დისკუსია
            price_text: 50 ლარი
            reservation_url: https://example.com/cultural
            seats_available: 20
        """,
    )
    sections_path = tmp_path / "sections.yaml"
    sections_path.write_text(yaml_text, encoding="utf-8")
    monkeypatch.setattr(admin_config_service, "SECTIONS_PATH", sections_path)
    return sections_path


def _make_adult_executor(lead: Lead | None = None) -> AdultToolExecutor:
    conv = Conversation(sender_id="s_ctx", platform="instagram", segment="ADULT")
    if lead is None:
        lead = Lead(sender_id="s_ctx", platform="instagram", segment="ADULT")
    conv.lead = lead
    return AdultToolExecutor(
        conversation=conv,
        lead=lead,
        sender_id="s_ctx",
        platform="instagram",
    )


# =========================================================================
# PART 1 — ADULT transition follow-up never dead-ends
# =========================================================================


def test_intro_followup_broad_pattern_catches_near_miss_phrasing():
    """Live near-miss: bot said „გასაგებია, კულტურულ საღამოებზე
    უპასუხებთ" — the literal pattern list didn't catch it but the
    broader heuristic should."""
    lead = Lead(sender_id="s", platform="instagram", segment="ADULT")
    response = "გასაგებია, კულტურულ საღამოებზე უპასუხებთ."
    out = _ensure_adult_intro_followup(response, lead)
    assert "?" in out
    assert out != response


def test_intro_followup_uses_relative_question_when_relation_known():
    lead = Lead(
        sender_id="s", platform="instagram", segment="ADULT",
        adult_target_relation="და",
    )
    response = "გასაგებია, ზრდასრულთა ღონისძიებებზე დაგეხმარებით."
    out = _ensure_adult_intro_followup(response, lead)
    assert "თქვენი და რამდენი წლისაა" in out
    assert "?" in out


def test_intro_followup_offers_list_when_relative_age_known():
    lead = Lead(
        sender_id="s", platform="instagram", segment="ADULT",
        adult_target_relation="და",
        adult_target_age="14",
    )
    response = "გასაგებია, ზრდასრულთა ღონისძიებებზე დაგეხმარებით."
    out = _ensure_adult_intro_followup(response, lead)
    assert "გნებავთ" in out
    assert "?" in out


def test_intro_followup_offers_list_when_self_age_known():
    lead = Lead(
        sender_id="s", platform="instagram", segment="ADULT", adult_age="30",
    )
    response = "გასაგებია, ზრდასრულთა ღონისძიებებზე დაგეხმარებით."
    out = _ensure_adult_intro_followup(response, lead)
    assert "გნებავთ" in out
    assert "?" in out


def test_intro_followup_default_who_question_when_no_context():
    lead = Lead(sender_id="s", platform="instagram", segment="ADULT")
    response = "გასაგებია, ღონისძიებებზე დაგეხმარებით."
    out = _ensure_adult_intro_followup(response, lead)
    assert "ღონისძიების შერჩევა თქვენთვის გსურთ" in out
    assert "?" in out


def test_intro_followup_no_op_for_long_substantive_response():
    lead = Lead(sender_id="s", platform="instagram", segment="ADULT")
    response = (
        "გასაგებია, ზრდასრულთა ღონისძიებებზე დაგეხმარებით. "
        "ჩვენი მიმდინარე პროგრამა მოიცავს ლიტერატურულ შეხვედრებს, "
        "პოეზიის საღამოებსა, დისკუსიებსა და ფილოსოფიურ კლუბებს."
    )
    assert len(response) > 120
    out = _ensure_adult_intro_followup(response, lead)
    assert out == response


def test_intro_followup_no_op_when_response_has_question():
    lead = Lead(sender_id="s", platform="instagram", segment="ADULT")
    response = "გასაგებია. რომელ თემაზე გნებავთ მეტი ინფორმაცია?"
    out = _ensure_adult_intro_followup(response, lead)
    assert out == response


def test_looks_like_bare_intro_recognises_short_ack_with_topic():
    assert _looks_like_bare_intro("გასაგებია, ღონისძიებებზე ვიმუშავოთ.") is True
    assert _looks_like_bare_intro("კარგი, კულტურულ საღამოს მოვძებნი.") is True


def test_looks_like_bare_intro_rejects_long_or_question():
    long_text = "გასაგებია, ღონისძიებებზე დაგეხმარებით. " * 5
    assert _looks_like_bare_intro(long_text) is False
    assert _looks_like_bare_intro("გასაგებია, ღონისძიება? როდისაა?") is False


def test_looks_like_bare_intro_rejects_ack_without_topic():
    assert _looks_like_bare_intro("გასაგებია, მოგწერთ ცოტა ხანში.") is False


# =========================================================================
# PART 2 — child_age leakage guard
# =========================================================================


def test_child_age_does_not_filter_adult_events_by_default(
    admin_yaml_age13_event,
):
    """Live bug: PARENT captured child_age=12, user later asked for
    adult events. The LLM passed user_age=12 → executor must REFUSE
    to filter by it (no relative target on record, no adult_age,
    user did not say event is for that child)."""
    lead = Lead(
        sender_id="s", platform="instagram", segment="ADULT",
        child_age="12",
    )
    executor = _make_adult_executor(lead=lead)
    result = executor.execute(TOOL_GET_ADULT_EVENTS, {"user_age": 12})

    # Guard must zero out the filter — returns all events, not "none
    # available for age 12".
    assert result["success"] is True
    assert result["user_age"] is None
    ids = {e["id"] for e in result["events"]}
    assert "cultural_evening" in ids


def test_child_age_DOES_filter_when_child_explicitly_named_as_target(
    admin_yaml_age13_event,
):
    """When the user explicitly named the child as target (via
    `adult_target_relation`), the child's age IS a valid filter."""
    lead = Lead(
        sender_id="s", platform="instagram", segment="ADULT",
        child_age="12",
        adult_target_relation="შვილი",
        adult_target_age="12",
    )
    executor = _make_adult_executor(lead=lead)
    # Don't pass user_age explicitly — executor reads adult_target_age.
    result = executor.execute(TOOL_GET_ADULT_EVENTS, {})
    assert result["user_age"] == 12
    # min_age=13 event is hidden from a 12-year-old.
    ids = {e["id"] for e in result["events"]}
    assert "cultural_evening" not in ids


def test_adult_age_used_for_filtering_when_set(admin_yaml_age13_event):
    lead = Lead(
        sender_id="s", platform="instagram", segment="ADULT", adult_age="30",
    )
    executor = _make_adult_executor(lead=lead)
    result = executor.execute(TOOL_GET_ADULT_EVENTS, {})
    assert result["user_age"] == 30
    ids = {e["id"] for e in result["events"]}
    assert "cultural_evening" in ids


def test_target_age_takes_precedence_over_self_age(admin_yaml_age13_event):
    """When BOTH `adult_age` and `adult_target_age` are set, the
    target wins — the user is asking on behalf of the relative."""
    lead = Lead(
        sender_id="s", platform="instagram", segment="ADULT",
        adult_age="30",
        adult_target_relation="და",
        adult_target_age="14",
    )
    executor = _make_adult_executor(lead=lead)
    result = executor.execute(TOOL_GET_ADULT_EVENTS, {})
    assert result["user_age"] == 14


def test_get_adult_events_never_falls_back_to_child_age(
    admin_yaml_age13_event,
):
    """No `user_age`, no `adult_target_age`, no `adult_age` — even
    with `child_age` set, the executor returns the unfiltered list."""
    lead = Lead(
        sender_id="s", platform="instagram", segment="ADULT",
        child_age="12",
    )
    executor = _make_adult_executor(lead=lead)
    result = executor.execute(TOOL_GET_ADULT_EVENTS, {})
    assert result["user_age"] is None  # never derived from child_age


def test_child_age_and_adult_age_separation_preserved(admin_yaml_age13_event):
    """Sanity: setting one never touches the other."""
    lead = Lead(
        sender_id="s", platform="instagram", segment="ADULT",
        child_age="12", adult_age="30",
    )
    executor = _make_adult_executor(lead=lead)
    executor.execute(TOOL_SAVE_ADULT_LEAD_INFO, {"adult_age": "31"})
    assert executor.lead.child_age == "12"
    assert executor.lead.adult_age == "31"


# =========================================================================
# PART 3 — Relative intent stays in ADULT flow
# =========================================================================


def test_relative_dis_without_camp_keyword_does_not_switch_to_parent():
    assert _user_wants_parent_flow("კულტურული საღამო მინდა ჩემი დისთვის") is False


def test_relative_dis_with_camp_keyword_does_switch_to_parent():
    assert _user_wants_parent_flow("ჩემი დისთვის ბანაკი მინდა") is True


def test_relative_dzma_without_camp_keyword_stays_adult():
    assert _user_wants_parent_flow("ჩემი ძმისთვის კონცერტი მინდა") is False


def test_friend_relation_alone_stays_adult():
    assert _user_wants_parent_flow("მეგობრისთვის ღონისძიება მაინტერესებს") is False


def test_mother_father_relations_stay_adult():
    assert _user_wants_parent_flow("დედისთვის კულტურული საღამო") is False
    assert _user_wants_parent_flow("მამისთვის პოეტური საღამო") is False


def test_child_for_adult_event_does_not_switch_to_parent():
    """„ჩემი შვილისთვის კულტურული საღამო მინდა" — child relative
    but adult-event context → stays ADULT."""
    assert _user_wants_parent_flow(
        "ჩემი შვილისთვის კულტურული საღამო მინდა",
    ) is False


def test_child_for_camp_still_switches():
    assert _user_wants_parent_flow(
        "ჩემი შვილისთვის ბანაკი მინდა",
    ) is True


def test_bare_age_with_child_keyword_no_adult_signal_switches():
    """Live QA Patch (2026-06-05) — Bug 2 tightening: bare „12 წლის
    ბავშვისთვის" without a hard camp keyword no longer auto-switches
    to PARENT. The ADULT engine asks the relative's age and stays in
    the adult-event flow."""
    assert _user_wants_parent_flow("12 წლის ბავშვისთვის მინდა") is False


def test_bare_age_with_child_keyword_AND_adult_signal_stays_adult():
    """„12 წლის ბავშვისთვის კულტურული საღამო" — adult-event signal
    blocks the switch even with a child-age cue."""
    assert _user_wants_parent_flow(
        "12 წლის ბავშვისთვის კულტურული საღამო",
    ) is False


def test_hard_camp_keyword_alone_switches():
    assert _user_wants_parent_flow("ბანაკის შესახებ მითხარი") is True
    assert _user_wants_parent_flow("საზაფხულო ბანაკი მაინტერესებს") is True


def test_pure_adult_inquiry_does_not_switch():
    assert _user_wants_parent_flow("რომელი ღონისძიება გაქვთ ივლისში?") is False


# =========================================================================
# PART 4 — adult_target_relation / adult_target_age fields
# =========================================================================


def test_lead_has_target_relation_and_target_age_fields():
    lead = Lead(sender_id="s", platform="instagram", segment="ADULT")
    assert hasattr(lead, "adult_target_relation")
    assert hasattr(lead, "adult_target_age")
    assert lead.adult_target_relation == ""
    assert lead.adult_target_age == ""


def test_lead_target_fields_round_trip_via_dict():
    lead = Lead(
        sender_id="s", platform="instagram", segment="ADULT",
        adult_target_relation="და",
        adult_target_age="14",
    )
    payload = lead.model_dump(mode="json")
    restored = Lead.from_dict(payload)
    assert restored.adult_target_relation == "და"
    assert restored.adult_target_age == "14"


def test_save_adult_lead_info_stores_target_fields(admin_yaml_age13_event):
    executor = _make_adult_executor()
    result = executor.execute(
        TOOL_SAVE_ADULT_LEAD_INFO,
        {"adult_target_relation": "და", "adult_target_age": "14"},
    )
    assert result["success"] is True
    assert "adult_target_relation" in result["saved_fields"]
    assert "adult_target_age" in result["saved_fields"]
    assert executor.lead.adult_target_relation == "და"
    assert executor.lead.adult_target_age == "14"
    # Strict separation: never writes to child_age or adult_age.
    assert executor.lead.child_age == ""
    assert executor.lead.adult_age == ""


def test_save_adult_lead_info_rejects_garbage_target_age(
    admin_yaml_age13_event,
):
    executor = _make_adult_executor()
    result = executor.execute(
        TOOL_SAVE_ADULT_LEAD_INFO,
        {"adult_target_age": "abc"},
    )
    assert "adult_target_age" in result.get("invalid_fields", [])
    assert executor.lead.adult_target_age == ""


def test_context_block_surfaces_target_fields():
    conv = Conversation(sender_id="s", platform="instagram", segment="ADULT")
    lead = Lead(
        sender_id="s", platform="instagram", segment="ADULT",
        adult_target_relation="და",
        adult_target_age="14",
    )
    conv.lead = lead
    block = adult_llm_engine._build_context_message(conv, lead)
    assert "adult_target_relation=და" in block
    assert "adult_target_age=14" in block


def test_context_block_dashes_when_target_fields_empty():
    conv = Conversation(sender_id="s", platform="instagram", segment="ADULT")
    lead = Lead(sender_id="s", platform="instagram", segment="ADULT")
    conv.lead = lead
    block = adult_llm_engine._build_context_message(conv, lead)
    assert "adult_target_relation=—" in block
    assert "adult_target_age=—" in block


# =========================================================================
# Deterministic relative-target capture (helper)
# =========================================================================


def test_capture_helper_extracts_relation_dis():
    lead = Lead(sender_id="s", platform="instagram", segment="ADULT")
    _maybe_capture_adult_target("კულტურული საღამო ჩემი დისთვის", lead)
    assert lead.adult_target_relation == "და"
    assert lead.adult_target_age == ""


def test_capture_helper_extracts_relation_and_age():
    lead = Lead(sender_id="s", platform="instagram", segment="ADULT")
    _maybe_capture_adult_target("ჩემი 14 წლის დისთვის მინდა საღამო", lead)
    assert lead.adult_target_relation == "და"
    assert lead.adult_target_age == "14"


def test_capture_helper_recognises_friend_mother_father():
    lead = Lead(sender_id="s", platform="instagram", segment="ADULT")
    _maybe_capture_adult_target("მეგობრისთვის ღონისძიება მინდა", lead)
    assert lead.adult_target_relation == "მეგობარი"

    lead2 = Lead(sender_id="s2", platform="instagram", segment="ADULT")
    _maybe_capture_adult_target("დედისთვის გავიქცე ღონისძიებაზე", lead2)
    assert lead2.adult_target_relation == "დედა"

    lead3 = Lead(sender_id="s3", platform="instagram", segment="ADULT")
    _maybe_capture_adult_target("მამისთვის ბილეთი", lead3)
    assert lead3.adult_target_relation == "მამა"


def test_capture_helper_no_overwrite_existing_relation():
    lead = Lead(
        sender_id="s", platform="instagram", segment="ADULT",
        adult_target_relation="ძმა",
        adult_target_age="20",
    )
    _maybe_capture_adult_target("ჩემი დისთვის ღონისძიება", lead)
    assert lead.adult_target_relation == "ძმა"
    assert lead.adult_target_age == "20"


def test_capture_helper_does_not_touch_child_age_or_adult_age():
    lead = Lead(
        sender_id="s", platform="instagram", segment="ADULT",
        child_age="12", adult_age="30",
    )
    _maybe_capture_adult_target("ჩემი 14 წლის დისთვის", lead)
    assert lead.child_age == "12"
    assert lead.adult_age == "30"
    assert lead.adult_target_age == "14"


def test_capture_helper_skips_unrelated_messages():
    lead = Lead(sender_id="s", platform="instagram", segment="ADULT")
    _maybe_capture_adult_target("რა კულტურული საღამოები გაქვთ?", lead)
    assert lead.adult_target_relation == ""
    assert lead.adult_target_age == ""


# =========================================================================
# End-to-end: full filtering path with relative target
# =========================================================================


def test_relative_age_14_filters_correctly_end_to_end(admin_yaml_age13_event):
    """„ჩემი 14 წლის დისთვის" → capture → filter at age 14 → min_age 13
    event is shown."""
    lead = Lead(sender_id="s", platform="instagram", segment="ADULT")
    _maybe_capture_adult_target("კულტურული საღამო ჩემი 14 წლის დისთვის", lead)
    executor = _make_adult_executor(lead=lead)
    result = executor.execute(TOOL_GET_ADULT_EVENTS, {})
    assert result["user_age"] == 14
    ids = {e["id"] for e in result["events"]}
    assert "cultural_evening" in ids


# =========================================================================
# Prompt + policy documentation evidence
# =========================================================================


def test_adult_prompt_documents_relative_routing():
    from app.agent.llm.prompt_loader import load_prompt, reset_cache
    reset_cache()
    text = load_prompt("system_adult_v1")
    # Relative phrasings must be called out as ADULT, not PARENT.
    assert "ჩემი დისთვის" in text
    assert "ჩემი ძმისთვის" in text or "ძმისთვის" in text
    # Hard-camp-only switch rule.
    assert "მხოლოდ" in text


def test_adult_prompt_documents_target_age_field():
    from app.agent.llm.prompt_loader import load_prompt, reset_cache
    reset_cache()
    text = load_prompt("system_adult_v1")
    assert "adult_target_age" in text
    assert "adult_target_relation" in text


def _read_adult_policy() -> str:
    """Read adult_sales_policy.md from the repo regardless of cwd."""
    import pathlib
    repo_root = pathlib.Path(__file__).resolve().parents[1]
    return (
        repo_root / "app" / "agent" / "policies" / "adult_sales_policy.md"
    ).read_text(encoding="utf-8")


def test_adult_policy_documents_child_age_leakage_rule():
    text = _read_adult_policy()
    assert "child_age leakage" in text or "leakage" in text


def test_adult_policy_documents_relative_target_rule():
    text = _read_adult_policy()
    assert "ჩემი დისთვის" in text or "Relative target" in text
