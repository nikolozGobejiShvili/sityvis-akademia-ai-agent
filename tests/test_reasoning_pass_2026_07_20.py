"""Phase 2 — reasoning loop (analyze→ground→answer→reflect), USE_REASONING_PASS.

Flag OFF ⇒ engine path byte-identical. Every step fails safe. REFLECT is the
conservative money/fact reliability guard (judges only grounded fact-classes).
"""


# -- Task 1: USE_REASONING_PASS flag ---------------------------------------

def test_use_reasoning_pass_defaults_false():
    from app.config import Settings
    assert Settings().USE_REASONING_PASS is False


def test_use_reasoning_pass_parses_env(monkeypatch):
    monkeypatch.setenv("USE_REASONING_PASS", "true")
    from app.config import Settings
    assert Settings.from_env().USE_REASONING_PASS is True


def test_use_reasoning_pass_pinned_off_on_engine_module():
    # conftest autouse pin must reach the engine module's own settings copy
    from app.agent.llm import parent_llm_engine as ple
    assert ple.settings.USE_REASONING_PASS is False


# -- Task 2: analyze_for_engine + parent_reasoning.md prompt ---------------

import json

from app.agent.llm import parent_turn_analyzer as analyzer
from app.models.conversation import Conversation
from app.models.lead import Lead


def _reasoning_lead() -> Lead:
    return Lead(sender_id="s", platform="facebook", segment="PARENT")


def _reasoning_conversation() -> Conversation:
    return Conversation(sender_id="s", platform="facebook")


def _mock_reasoning_llm(monkeypatch, text: str):
    monkeypatch.setattr(
        "app.services.openai_service.analyze_parent_turn",
        lambda **kwargs: text,
    )


def _mock_reasoning_llm_raises(monkeypatch):
    def _raise(**kwargs):
        raise RuntimeError("boom")
    monkeypatch.setattr("app.services.openai_service.analyze_parent_turn", _raise)


def _valid_reasoning_json(**overrides) -> str:
    payload = {
        "user_goal": "check age eligibility",
        "sentiment": "neutral",
        "needed_facts": ["price", "age"],
        "missing_lead_fields": ["child_age"],
        "suggested_tool": "get_camp_info",
        "should_greet": False,
        "plan": "Look up price and age range, then answer.",
    }
    payload.update(overrides)
    return json.dumps(payload)


def test_analyze_for_engine_valid_json_returns_parsed_seven_field_dict(monkeypatch):
    _mock_reasoning_llm(monkeypatch, _valid_reasoning_json())

    result = analyzer.analyze_for_engine(
        user_message="რა ღირს ბანაკი 10 წლის ბავშვისთვის?",
        lead=_reasoning_lead(),
        conversation=_reasoning_conversation(),
        knowledge_keys=["camp_2026"],
        tool_names=["get_camp_info", "book_consultation"],
    )

    assert result is not None
    assert set(result.keys()) == {
        "user_goal", "sentiment", "needed_facts", "missing_lead_fields",
        "suggested_tool", "should_greet", "plan",
    }
    assert result["user_goal"] == "check age eligibility"
    assert result["sentiment"] == "neutral"
    assert result["needed_facts"] == ["price", "age"]
    assert result["missing_lead_fields"] == ["child_age"]
    assert result["suggested_tool"] == "get_camp_info"
    assert result["should_greet"] is False
    assert result["plan"] == "Look up price and age range, then answer."


def test_analyze_for_engine_malformed_json_returns_none(monkeypatch):
    _mock_reasoning_llm(monkeypatch, "this is not json at all {{{")

    result = analyzer.analyze_for_engine(
        user_message="გამარჯობა",
        lead=_reasoning_lead(),
        conversation=_reasoning_conversation(),
        knowledge_keys=["camp_2026"],
        tool_names=["get_camp_info"],
    )

    assert result is None


def test_analyze_for_engine_openai_raises_returns_none(monkeypatch):
    _mock_reasoning_llm_raises(monkeypatch)

    result = analyzer.analyze_for_engine(
        user_message="ფასი რა არის?",
        lead=_reasoning_lead(),
        conversation=_reasoning_conversation(),
        knowledge_keys=["camp_2026"],
        tool_names=["get_camp_info"],
    )

    assert result is None


def test_analyze_for_engine_coerces_unknown_fact_and_tool_values(monkeypatch):
    _mock_reasoning_llm(
        monkeypatch,
        _valid_reasoning_json(
            needed_facts=["price", "weather", "age"],
            suggested_tool="nonexistent",
        ),
    )

    result = analyzer.analyze_for_engine(
        user_message="ხვალ ამინდი როგორია?",
        lead=_reasoning_lead(),
        conversation=_reasoning_conversation(),
        knowledge_keys=["camp_2026"],
        tool_names=["get_camp_info", "book_consultation"],
    )

    assert result is not None
    # "weather" is not in the closed fact-type set — dropped.
    assert result["needed_facts"] == ["price", "age"]
    # "nonexistent" is not in the provided tool_names — coerced to None.
    assert result["suggested_tool"] is None
