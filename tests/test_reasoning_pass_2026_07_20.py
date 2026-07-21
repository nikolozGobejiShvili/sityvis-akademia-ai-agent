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


def test_analyze_for_engine_should_greet_string_false_is_false(monkeypatch):
    # review Minor: a malformed string "false" must NOT truthy-coerce to True.
    _mock_reasoning_llm(monkeypatch, _valid_reasoning_json(should_greet="false"))
    result = analyzer.analyze_for_engine(
        user_message="გამარჯობა", lead=_reasoning_lead(),
        conversation=_reasoning_conversation(),
        knowledge_keys=["camp_2026"], tool_names=["get_camp_info"],
    )
    assert result is not None and result["should_greet"] is False


# -- Task 3: GROUND — per-class preselect (source-correct) -----------------

def test_reasoning_ground_selects_only_requested_classes(monkeypatch):
    from app.agent.llm import parent_llm_engine as ple
    from app.services import admin_config_service as acs
    monkeypatch.setattr(acs, "get_camp_facts", lambda: {
        "price_gel": 2150, "price_text": "2150", "location": "ამბასადორი კაჭრეთი",
        "age_min": 9, "age_max": 17, "registration_url": "https://reg.example",
    })
    monkeypatch.setattr(acs, "get_manager_phone", lambda: "558 67 47 33")
    g = ple._reasoning_ground(["price", "phone"])
    assert g["price"] == "2150"
    assert g["phone"] == "558 67 47 33"        # from get_manager_phone, not camp phone
    assert "location" not in g                 # not requested → not grounded


def test_reasoning_ground_age_and_registration(monkeypatch):
    from app.agent.llm import parent_llm_engine as ple
    from app.services import admin_config_service as acs
    monkeypatch.setattr(acs, "get_camp_facts", lambda: {
        "age_min": 9, "age_max": 17, "registration_url": "https://reg.example"})
    monkeypatch.setattr(acs, "get_manager_phone", lambda: "558 67 47 33")
    g = ple._reasoning_ground(["age", "registration"])
    assert g["age"] == "9-17" and g["registration"] == "https://reg.example"


def test_reasoning_ground_unsourceable_class_omitted(monkeypatch):
    from app.agent.llm import parent_llm_engine as ple
    from app.services import admin_config_service as acs
    monkeypatch.setattr(acs, "get_camp_facts", lambda: {"price_text": "2150"})
    monkeypatch.setattr(acs, "get_manager_phone", lambda: "558 67 47 33")
    # location requested but not in facts → omitted (not empty-stringed)
    g = ple._reasoning_ground(["location"])
    assert g == {}


def test_reasoning_ground_empty_and_error_safe(monkeypatch):
    from app.agent.llm import parent_llm_engine as ple
    from app.services import admin_config_service as acs
    assert ple._reasoning_ground([]) == {}
    assert ple._reasoning_ground(None) == {}
    monkeypatch.setattr(acs, "get_camp_facts", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    assert ple._reasoning_ground(["price"]) == {}   # never raises


def test_reasoning_ground_text_formats_present_keys():
    from app.agent.llm import parent_llm_engine as ple
    txt = ple._reasoning_ground_text({"price": "2150", "phone": "558 67 47 33"})
    assert "ფასი: 2150" in txt and "მენეჯერი: 558 67 47 33" in txt
    assert ple._reasoning_ground_text({}) == ""


# -- Task 4: REFLECT — verify only grounded classes, conservative fallback --

def test_reflect_passes_grounded_answer():
    from app.agent.llm import parent_llm_engine as ple
    ans = "ბანაკის ფასია 2150 ლარი."
    assert ple._reasoning_reflect(ans, {"price": "2150"}) == (ans, False)


def test_reflect_replaces_contradicted_price():
    from app.agent.llm import parent_llm_engine as ple
    out, replaced = ple._reasoning_reflect("ფასია 9999 ლარი.", {"price": "2150"})
    assert replaced is True and "9999" not in out


def test_reflect_does_not_judge_ungrounded_class():
    from app.agent.llm import parent_llm_engine as ple
    # a price token in the answer, but price was NOT grounded → pass
    ans = "ფორმულა1-ის ფასია 5000 ლარი."
    assert ple._reasoning_reflect(ans, {"phone": "558 67 47 33"}) == (ans, False)


def test_reflect_passes_when_grounded_price_present_among_others():
    from app.agent.llm import parent_llm_engine as ple
    # correct price IS present → do not flag even if another number appears
    ans = "ფასია 2150 ლარი, ფასდაკლებით 1900 ლარი."
    assert ple._reasoning_reflect(ans, {"price": "2150"}) == (ans, False)


def test_reflect_replaces_wrong_manager_phone():
    from app.agent.llm import parent_llm_engine as ple
    out, replaced = ple._reasoning_reflect("დარეკეთ 599 11 22 33.", {"phone": "558 67 47 33"})
    assert replaced is True


def test_reflect_never_raises():
    from app.agent.llm import parent_llm_engine as ple
    assert ple._reasoning_reflect(None, None) == (None, False)
    assert ple._reasoning_reflect("x", None) == ("x", False)
