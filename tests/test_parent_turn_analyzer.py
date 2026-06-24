"""Unit tests for app.agent.llm.parent_turn_analyzer (Phase 3.9).

Coverage:
  * Module imports cleanly.
  * Built payload includes current_state, the user message, lead fields,
    and a knowledge summary block (price/location/dates/registration/phone).
  * Valid JSON returned by the fake LLM parses into a normalised dict.
  * Invalid JSON / non-mapping JSON returns None.
  * OpenAI exception returns None (hard fallback to scripted flow).
  * Disallowed primary_intent or suggested_backend_action returns None.
  * Markdown-fenced JSON is unwrapped correctly.
  * Low-confidence result is preserved (does NOT short-circuit to None).
  * Manager / age+dates / no_concern / price / location example messages
    flow through correctly when the fake LLM returns the expected JSON.
  * Flag off → analyze returns None and openai_service is never called.

No test hits live OpenAI — every test that enables the analyzer
monkeypatches the openai_service.analyze_parent_turn surface.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from app.agent.llm import parent_turn_analyzer as analyzer
from app.models.lead import Lead


# -- fixtures --------------------------------------------------------------


@pytest.fixture
def lead_with_name() -> Lead:
    return Lead(
        sender_id="t-1",
        platform="instagram",
        segment="PARENT",
        name="ანა ლომიძე",
        child_age="8",
    )


@pytest.fixture
def empty_lead() -> Lead:
    return Lead(sender_id="t-2", platform="instagram", segment="PARENT")


@pytest.fixture
def enable_analyzer(monkeypatch):
    """Force-enable the analyzer for a single test without mutating
    the frozen Settings dataclass."""
    monkeypatch.setattr(analyzer, "_analyzer_enabled", lambda: True)


def _fake_llm(monkeypatch, text: str):
    """Replace openai_service.analyze_parent_turn with a function returning ``text``."""
    monkeypatch.setattr(
        "app.services.openai_service.analyze_parent_turn",
        lambda **kwargs: text,
    )


def _fake_llm_raises(monkeypatch, exc: Exception):
    def _raise(**kwargs):
        raise exc
    monkeypatch.setattr("app.services.openai_service.analyze_parent_turn", _raise)


def _valid_json(**overrides: Any) -> str:
    base: dict[str, Any] = {
        "primary_intent": "answer_flow_question",
        "provided_fields": {
            "child_age": None, "phone": None, "name": None,
            "challenge": None, "deeper_concern": None, "desired_change": None,
        },
        "user_wants_human": False,
        "user_rejects_discovery": False,
        "fact_types_requested": [],
        "suggested_backend_action": "continue_flow",
        "confidence": 0.9,
        "reason_short": "user answered the script question",
    }
    base.update(overrides)
    return json.dumps(base, ensure_ascii=False)


# -- 1. module imports ----------------------------------------------------


def test_module_imports() -> None:
    assert hasattr(analyzer, "analyze_parent_turn")
    assert callable(analyzer.analyze_parent_turn)
    assert hasattr(analyzer, "ALLOWED_INTENTS")
    assert hasattr(analyzer, "ALLOWED_ACTIONS")
    assert hasattr(analyzer, "LOW_CONFIDENCE_THRESHOLD")
    assert analyzer.LOW_CONFIDENCE_THRESHOLD == 0.65


# -- 2. payload contents --------------------------------------------------


def test_payload_includes_current_state_and_user_message(lead_with_name: Lead) -> None:
    _, user_payload = analyzer.build_payload(
        current_state="ASK_AGE",
        user_message="მენეჯერი მინდა",
        lead=lead_with_name,
    )
    assert "CURRENT_STATE:\nASK_AGE" in user_payload
    assert '"მენეჯერი მინდა"' in user_payload


def test_payload_includes_lead_fields(lead_with_name: Lead) -> None:
    _, user_payload = analyzer.build_payload(
        current_state="ASK_CHALLENGE",
        user_message="ბევრს ზის ტელეფონზე",
        lead=lead_with_name,
    )
    assert "NAME: ანა ლომიძე" in user_payload
    assert "CHILD_AGE: 8" in user_payload
    for label in ("CHALLENGE:", "DEEPER_CONCERN:", "DESIRED_CHANGE:", "PHONE:"):
        assert label in user_payload, f"missing lead label {label!r}"


def test_payload_includes_knowledge_summary(empty_lead: Lead, monkeypatch) -> None:
    # Clock-robust (2026-06-23): freeze the camp-stream "now" before any stream
    # start so all three streams stay visible in the knowledge summary.
    import datetime as _dt
    from app.services import admin_config_service as _acs
    from app.agent.services.timestamps import TBILISI_TZ as _TZ
    monkeypatch.setattr(
        _acs, "_now_tbilisi",
        lambda: (_dt.datetime(2026, 6, 1, 12, 0, tzinfo=_TZ), _TZ),
    )
    _, user_payload = analyzer.build_payload(
        current_state="ASK_AGE",
        user_message="ფასი რა არის?",
        lead=empty_lead,
    )
    # Authoritative camp facts from camp_2026.yaml
    assert "price_gel=2150" in user_payload
    assert "ამბასადორი კაჭრეთი" in user_payload
    assert "23-29 ივნისი" in user_payload
    assert "5-11 ივლისი" in user_payload
    assert "14-20 ივლისი" in user_payload
    assert "tinyurl.com/36jcae8z" in user_payload
    assert "558 67 47 33" in user_payload


def test_payload_system_prompt_loaded(empty_lead: Lead) -> None:
    system_prompt, _ = analyzer.build_payload(
        current_state="ASK_AGE",
        user_message="hi",
        lead=empty_lead,
    )
    # parent_turn_analyzer.md ships with these exact strings.
    assert "primary_intent" in system_prompt
    assert "suggested_backend_action" in system_prompt
    assert "ask_manager" in system_prompt
    assert "answer_facts" in system_prompt


def test_payload_includes_recent_history(empty_lead: Lead) -> None:
    history = [
        {"role": "user", "content": "გამარჯობა"},
        {"role": "assistant", "content": "გვითხარით რა გაინტერესებთ"},
        {"role": "user", "content": "ბანაკი"},
    ]
    _, user_payload = analyzer.build_payload(
        current_state="ASK_AGE",
        user_message="8",
        lead=empty_lead,
        conversation_history=history,
    )
    assert "RECENT CONVERSATION" in user_payload
    assert "ბანაკი" in user_payload


# -- 3. happy path: valid JSON parses correctly ---------------------------


def test_valid_json_parses(enable_analyzer, monkeypatch, lead_with_name: Lead) -> None:
    _fake_llm(monkeypatch, _valid_json(
        primary_intent="ask_dates",
        suggested_backend_action="answer_facts",
        fact_types_requested=["dates"],
        confidence=0.92,
    ))
    result = analyzer.analyze_parent_turn(
        current_state="ASK_AGE",
        user_message="თარიღები რა არის?",
        lead=lead_with_name,
    )
    assert result is not None
    assert result["primary_intent"] == "ask_dates"
    assert result["suggested_backend_action"] == "answer_facts"
    assert result["fact_types_requested"] == ["dates"]
    assert result["confidence"] == pytest.approx(0.92)


def test_provided_fields_coerced(enable_analyzer, monkeypatch, lead_with_name: Lead) -> None:
    """LLM sometimes returns numbers instead of strings — coercion must handle that."""
    _fake_llm(monkeypatch, json.dumps({
        "primary_intent": "answer_flow_question",
        "provided_fields": {
            "child_age": 8,  # int, not str
            "phone": None,
            "name": None,
            "challenge": "",  # empty string → None
            "deeper_concern": None,
            "desired_change": None,
        },
        "user_wants_human": False,
        "user_rejects_discovery": False,
        "fact_types_requested": [],
        "suggested_backend_action": "continue_flow",
        "confidence": 0.9,
        "reason_short": "age provided",
    }, ensure_ascii=False))
    result = analyzer.analyze_parent_turn(
        current_state="ASK_AGE",
        user_message="8",
        lead=lead_with_name,
    )
    assert result is not None
    assert result["provided_fields"]["child_age"] == "8"
    assert result["provided_fields"]["challenge"] is None


def test_markdown_fenced_json_is_unwrapped(
    enable_analyzer, monkeypatch, lead_with_name: Lead,
) -> None:
    """Models sometimes ignore 'no fences' instruction. Be tolerant."""
    fenced = "```json\n" + _valid_json(primary_intent="ask_price",
                                       suggested_backend_action="answer_facts",
                                       fact_types_requested=["price"]) + "\n```"
    _fake_llm(monkeypatch, fenced)
    result = analyzer.analyze_parent_turn(
        current_state="ASK_AGE",
        user_message="ფასი?",
        lead=lead_with_name,
    )
    assert result is not None
    assert result["primary_intent"] == "ask_price"


def test_text_with_extra_prose_around_json(
    enable_analyzer, monkeypatch, lead_with_name: Lead,
) -> None:
    blob = "Here is the JSON: " + _valid_json(
        primary_intent="ask_location",
        suggested_backend_action="answer_facts",
        fact_types_requested=["location"],
    ) + " (end)"
    _fake_llm(monkeypatch, blob)
    result = analyzer.analyze_parent_turn(
        current_state="ASK_CHALLENGE",
        user_message="სად ტარდება?",
        lead=lead_with_name,
    )
    assert result is not None
    assert result["primary_intent"] == "ask_location"


# -- 4. failure modes return None -----------------------------------------


def test_invalid_json_returns_none(
    enable_analyzer, monkeypatch, lead_with_name: Lead,
) -> None:
    _fake_llm(monkeypatch, "not even close to JSON")
    result = analyzer.analyze_parent_turn(
        current_state="ASK_AGE",
        user_message="hi",
        lead=lead_with_name,
    )
    assert result is None


def test_malformed_json_returns_none(
    enable_analyzer, monkeypatch, lead_with_name: Lead,
) -> None:
    _fake_llm(monkeypatch, '{"primary_intent": "ask_price", malformed}')
    result = analyzer.analyze_parent_turn(
        current_state="ASK_AGE",
        user_message="hi",
        lead=lead_with_name,
    )
    assert result is None


def test_json_array_returns_none(
    enable_analyzer, monkeypatch, lead_with_name: Lead,
) -> None:
    """LLM returns [..] instead of {..} — schema requires mapping."""
    _fake_llm(monkeypatch, "[]")
    result = analyzer.analyze_parent_turn(
        current_state="ASK_AGE",
        user_message="hi",
        lead=lead_with_name,
    )
    assert result is None


def test_disallowed_intent_returns_none(
    enable_analyzer, monkeypatch, lead_with_name: Lead,
) -> None:
    _fake_llm(monkeypatch, _valid_json(primary_intent="some_made_up_intent"))
    result = analyzer.analyze_parent_turn(
        current_state="ASK_AGE",
        user_message="hi",
        lead=lead_with_name,
    )
    assert result is None


def test_disallowed_action_returns_none(
    enable_analyzer, monkeypatch, lead_with_name: Lead,
) -> None:
    _fake_llm(monkeypatch, _valid_json(suggested_backend_action="do_some_dangerous_thing"))
    result = analyzer.analyze_parent_turn(
        current_state="ASK_AGE",
        user_message="hi",
        lead=lead_with_name,
    )
    assert result is None


def test_openai_error_returns_none(
    enable_analyzer, monkeypatch, lead_with_name: Lead,
) -> None:
    _fake_llm_raises(monkeypatch, RuntimeError("simulated quota error"))
    result = analyzer.analyze_parent_turn(
        current_state="ASK_AGE",
        user_message="hi",
        lead=lead_with_name,
    )
    assert result is None


def test_empty_llm_output_returns_none(
    enable_analyzer, monkeypatch, lead_with_name: Lead,
) -> None:
    _fake_llm(monkeypatch, "")
    result = analyzer.analyze_parent_turn(
        current_state="ASK_AGE",
        user_message="hi",
        lead=lead_with_name,
    )
    assert result is None


# -- 5. low confidence preserved (not collapsed to None) ------------------


def test_low_confidence_returns_dict_not_none(
    enable_analyzer, monkeypatch, lead_with_name: Lead,
) -> None:
    """Spec rule 4: low confidence → backend asks a clarifying question.
    Analyzer must still return the dict so the backend can detect this and
    branch correctly — it must NOT collapse to a hard fallback (None)."""
    _fake_llm(monkeypatch, _valid_json(
        primary_intent="unclear",
        suggested_backend_action="ask_clarifying_question",
        confidence=0.3,
    ))
    result = analyzer.analyze_parent_turn(
        current_state="ASK_AGE",
        user_message="hmm",
        lead=lead_with_name,
    )
    assert result is not None
    assert result["confidence"] == pytest.approx(0.3)
    assert result["confidence"] < analyzer.LOW_CONFIDENCE_THRESHOLD


def test_confidence_clamped_to_unit_interval(
    enable_analyzer, monkeypatch, lead_with_name: Lead,
) -> None:
    _fake_llm(monkeypatch, _valid_json(confidence=99.0))
    result = analyzer.analyze_parent_turn(
        current_state="ASK_AGE",
        user_message="8",
        lead=lead_with_name,
    )
    assert result is not None
    assert result["confidence"] == 1.0


def test_confidence_non_numeric_defaults_to_zero(
    enable_analyzer, monkeypatch, lead_with_name: Lead,
) -> None:
    _fake_llm(monkeypatch, _valid_json(confidence="probably"))
    result = analyzer.analyze_parent_turn(
        current_state="ASK_AGE",
        user_message="8",
        lead=lead_with_name,
    )
    assert result is not None
    assert result["confidence"] == 0.0


# -- 6. example messages from the spec ------------------------------------


def test_ask_manager_example(enable_analyzer, monkeypatch, lead_with_name: Lead) -> None:
    _fake_llm(monkeypatch, _valid_json(
        primary_intent="ask_manager",
        suggested_backend_action="ask_phone_for_callback",
        user_wants_human=True,
        confidence=0.95,
        reason_short="user requests manager",
    ))
    result = analyzer.analyze_parent_turn(
        current_state="ASK_AGE",
        user_message="მირჩევნია პირდაპირ მენეჯერს ველაპარაკო",
        lead=lead_with_name,
    )
    assert result is not None
    assert result["primary_intent"] == "ask_manager"
    assert result["user_wants_human"] is True
    assert result["suggested_backend_action"] == "ask_phone_for_callback"


def test_age_plus_dates_example(
    enable_analyzer, monkeypatch, lead_with_name: Lead,
) -> None:
    """Multi-intent: age provided + dates requested."""
    _fake_llm(monkeypatch, json.dumps({
        "primary_intent": "ask_dates",
        "provided_fields": {
            "child_age": "8",
            "phone": None,
            "name": None,
            "challenge": None,
            "deeper_concern": None,
            "desired_change": None,
        },
        "user_wants_human": False,
        "user_rejects_discovery": False,
        "fact_types_requested": ["dates"],
        "suggested_backend_action": "answer_facts",
        "confidence": 0.88,
        "reason_short": "age plus dates question",
    }, ensure_ascii=False))
    result = analyzer.analyze_parent_turn(
        current_state="ASK_AGE",
        user_message="8 წლის არის ჩემი შვილი, თარიღები რა არის?",
        lead=lead_with_name,
    )
    assert result is not None
    assert result["primary_intent"] == "ask_dates"
    assert result["provided_fields"]["child_age"] == "8"
    assert "dates" in result["fact_types_requested"]


def test_no_concern_example(
    enable_analyzer, monkeypatch, lead_with_name: Lead,
) -> None:
    _fake_llm(monkeypatch, _valid_json(
        primary_intent="no_concern",
        suggested_backend_action="answer_facts",
        user_rejects_discovery=True,
        fact_types_requested=["dates"],
        confidence=0.9,
    ))
    result = analyzer.analyze_parent_turn(
        current_state="ASK_CHALLENGE",
        user_message="არაფერი არ აწუხებს, უბრალოდ თარიღები მაინტერესებს",
        lead=lead_with_name,
    )
    assert result is not None
    assert result["primary_intent"] == "no_concern"
    assert result["user_rejects_discovery"] is True


def test_ask_price_example(
    enable_analyzer, monkeypatch, lead_with_name: Lead,
) -> None:
    _fake_llm(monkeypatch, _valid_json(
        primary_intent="ask_price",
        suggested_backend_action="answer_facts",
        fact_types_requested=["price"],
        confidence=0.95,
    ))
    result = analyzer.analyze_parent_turn(
        current_state="ASK_CHALLENGE",
        user_message="ფასი მაინტერესებს",
        lead=lead_with_name,
    )
    assert result is not None
    assert result["primary_intent"] == "ask_price"
    assert "price" in result["fact_types_requested"]


def test_ask_location_example(
    enable_analyzer, monkeypatch, lead_with_name: Lead,
) -> None:
    _fake_llm(monkeypatch, _valid_json(
        primary_intent="ask_location",
        suggested_backend_action="answer_facts",
        fact_types_requested=["location"],
        confidence=0.91,
    ))
    result = analyzer.analyze_parent_turn(
        current_state="ASK_AGE",
        user_message="სად ტარდება ბანაკი?",
        lead=lead_with_name,
    )
    assert result is not None
    assert result["primary_intent"] == "ask_location"
    assert "location" in result["fact_types_requested"]


# -- 7. flag off — analyzer is a no-op, never calls OpenAI ---------------


def test_flag_off_returns_none_without_calling_openai(
    monkeypatch, lead_with_name: Lead,
) -> None:
    monkeypatch.setattr(analyzer, "_analyzer_enabled", lambda: False)

    called = {"n": 0}

    def _spy(**kwargs):
        called["n"] += 1
        return "should not be reached"

    monkeypatch.setattr("app.services.openai_service.analyze_parent_turn", _spy)
    result = analyzer.analyze_parent_turn(
        current_state="ASK_AGE",
        user_message="ფასი?",
        lead=lead_with_name,
    )
    assert result is None
    assert called["n"] == 0, "analyzer must NOT call openai when flag is off"


# -- 8. fact_types coerced + filtered to whitelist ------------------------


def test_unknown_fact_types_filtered(
    enable_analyzer, monkeypatch, lead_with_name: Lead,
) -> None:
    _fake_llm(monkeypatch, _valid_json(
        primary_intent="ask_price",
        suggested_backend_action="answer_facts",
        fact_types_requested=["price", "weather", "horoscope"],
    ))
    result = analyzer.analyze_parent_turn(
        current_state="ASK_AGE",
        user_message="ფასი?",
        lead=lead_with_name,
    )
    assert result is not None
    assert result["fact_types_requested"] == ["price"]


# -- 9. analyzer never mutates lead or conversation ------------------------


def test_analyzer_does_not_mutate_lead(
    enable_analyzer, monkeypatch, lead_with_name: Lead,
) -> None:
    """The analyzer module classifies; it must not touch the lead. (Field
    application is the backend's job — see parent_turn_router.)"""
    _fake_llm(monkeypatch, _valid_json(
        primary_intent="answer_flow_question",
        provided_fields={
            "child_age": "99",
            "phone": "+1234567890",
            "name": "OTHER",
            "challenge": None,
            "deeper_concern": None,
            "desired_change": None,
        },
        suggested_backend_action="continue_flow",
        confidence=0.9,
    ))
    original_name = lead_with_name.name
    original_age = lead_with_name.child_age
    analyzer.analyze_parent_turn(
        current_state="ASK_AGE",
        user_message="x",
        lead=lead_with_name,
    )
    assert lead_with_name.name == original_name
    assert lead_with_name.child_age == original_age
    assert lead_with_name.phone == ""


# -- 10. JSON extractor sanity unit tests ---------------------------------


def test_extractor_handles_plain_blob() -> None:
    assert analyzer._extract_json_blob('{"a": 1}') == '{"a": 1}'


def test_extractor_handles_fence() -> None:
    assert analyzer._extract_json_blob("```json\n{\"a\": 1}\n```") == '{"a": 1}'


def test_extractor_returns_none_for_garbage() -> None:
    assert analyzer._extract_json_blob("no json here") is None
    assert analyzer._extract_json_blob("") is None
