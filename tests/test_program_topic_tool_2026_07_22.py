"""Capability #1 — topic-facts tool (get_program_topic). Flag USE_PROGRAM_TOPICS
converts the deterministic camp-topic interceptor into an LLM tool the model
reasons over. Flag OFF ⇒ byte-identical (interceptor answers, tool surface +
prompt unchanged)."""
from __future__ import annotations

import dataclasses

from app.config import Settings
import app.config as config_module
import app.agent.llm.parent_llm_engine as ple
from app.agent.tools import parent_tools as pt
from app.agent.tools.parent_tool_executor import ParentToolExecutor
from app.models.conversation import Conversation


def test_program_topics_flag_defaults_off():
    assert Settings().USE_PROGRAM_TOPICS is False


# -- Task 2: get_program_topic tool (schema, executor, wiring, prompt) -------


def _on(monkeypatch):
    swapped = dataclasses.replace(config_module.settings, USE_PROGRAM_TOPICS=True)
    monkeypatch.setattr(ple, "settings", swapped)


def _executor() -> ParentToolExecutor:
    conv = Conversation(sender_id="t", platform="messenger")
    return ParentToolExecutor(
        conversation=conv, lead=conv.lead, sender_id=conv.sender_id, platform=conv.platform,
    )


def test_topic_tool_out_of_parent_tools():
    names = [t["function"]["name"] for t in pt.PARENT_TOOLS]
    assert pt.TOOL_GET_PROGRAM_TOPIC not in names  # never in the always-on list


def test_topic_tool_in_allowed_names():
    assert pt.TOOL_GET_PROGRAM_TOPIC in pt.ALLOWED_TOOL_NAMES


def test_topic_tools_list_shape():
    names = [t["function"]["name"] for t in pt.TOPIC_TOOLS]
    assert names == [pt.TOOL_GET_PROGRAM_TOPIC]


def test_build_active_tools_flag_off_is_byte_identical_to_parent_tools():
    # The #1 risk: flag OFF must be indistinguishable from today.
    assert ple.build_active_tools(False, False, False) == list(pt.PARENT_TOOLS)


def test_build_active_tools_appends_only_when_flag_on():
    off = ple.build_active_tools(use_dynamic=False, use_learning=False, use_topics=False)
    on = ple.build_active_tools(use_dynamic=False, use_learning=False, use_topics=True)
    off_names = [t["function"]["name"] for t in off]
    on_names = [t["function"]["name"] for t in on]
    assert pt.TOOL_GET_PROGRAM_TOPIC not in off_names
    assert pt.TOOL_GET_PROGRAM_TOPIC in on_names


def test_build_active_tools_default_topics_off():
    # use_topics defaults to False so existing 2-arg callers are unaffected.
    default = ple.build_active_tools(False, False)
    assert default == list(pt.PARENT_TOOLS)


def test_executor_returns_topic_facts_from_backend():
    ex = _executor()
    res = ex._get_program_topic({"topic": "safety"})
    assert res["success"] is True
    assert res["topic"] == "safety"
    assert res["facts"]


def test_executor_medical_topic_uses_medical_answer():
    ex = _executor()
    res = ex._get_program_topic({"topic": "medical"})
    assert res["topic"] == "medical"
    # medical_answer() may be None in a stripped test fixture; either way the
    # contract (success flag matches whether facts is non-empty) must hold.
    assert res["success"] == bool(res["facts"])


def test_executor_unknown_topic_fails_safely():
    ex = _executor()
    res = ex._get_program_topic({"topic": "not_a_topic"})
    assert res["success"] is False


def test_executor_accepts_georgian_topic_names():
    # The prompt suffix lists topics in Georgian; the model may pass them
    # verbatim. The executor must resolve them (via the fuzzy matcher) rather
    # than fail — else the model invents (the whole point is facts-from-backend).
    ex = _executor()
    for georgian, expected_key in [
        ("უსაფრთხოება", "safety"),
        ("კვება", "food"),
        ("გაჯეტები", "gadgets"),
        ("მშობელთან კომუნიკაცია", "parent_communication"),
    ]:
        res = ex._get_program_topic({"topic": georgian})
        assert res["success"] is True, georgian
        assert res["topic"] == expected_key
        assert res["facts"]


def test_executor_accepts_georgian_medical_alias():
    ex = _executor()
    res = ex._get_program_topic({"topic": "სამედიცინო"})
    assert res["topic"] == "medical"
    assert res["success"] == bool(res["facts"])


def test_executor_non_string_topic_is_safe():
    # Malformed tool-call JSON could pass a non-string; must not raise.
    ex = _executor()
    for bad in (123, None, {"x": 1}):
        res = ex._get_program_topic({"topic": bad})
        assert res["success"] is False


def test_suffix_recovery_line_present_when_flag_on(monkeypatch):
    _on(monkeypatch)
    suffix = ple._topic_tool_prompt_suffix()
    assert "success=false" in suffix  # tells the model to answer normally on a miss
    assert "დღის განრიგი" not in suffix  # the dead topic (no backing key) is dropped


def test_executor_empty_topic_fails_safely():
    ex = _executor()
    res = ex._get_program_topic({"topic": ""})
    assert res == {"success": False, "topic": "", "facts": ""}


def test_executor_missing_args_fails_safely():
    ex = _executor()
    res = ex._get_program_topic({})
    assert res["success"] is False


def test_executor_dispatches_via_execute():
    ex = _executor()
    res = ex.execute(pt.TOOL_GET_PROGRAM_TOPIC, {"topic": "safety"})
    assert res["success"] is True
    assert res["topic"] == "safety"


def test_prompt_suffix_empty_when_flag_off(monkeypatch):
    swapped = dataclasses.replace(config_module.settings, USE_PROGRAM_TOPICS=False)
    monkeypatch.setattr(ple, "settings", swapped)
    assert ple._topic_tool_prompt_suffix() == ""


def test_prompt_suffix_empty_under_conftest_default():
    # No monkeypatch — proves the real default (conftest-pinned) is OFF.
    assert ple._topic_tool_prompt_suffix() == ""


def test_prompt_suffix_present_when_flag_on(monkeypatch):
    _on(monkeypatch)
    assert "get_program_topic" in ple._topic_tool_prompt_suffix()


# -- Task 3: interceptor bypass gate (flag-gated yield) ----------------------


def test_flag_off_interceptor_still_answers_topic():
    # Flag OFF (conftest default): the deterministic interceptor still returns a
    # canned topic block — byte-identical to today, engine not consulted.
    from app.flows import parent_flow
    conv = Conversation(sender_id="t", platform="messenger")
    out = parent_flow._maybe_handle_camp_topic_facts(conv, "უსაფრთხოება როგორ არის ბანაკში?")
    assert out and out.strip()


def test_flag_on_interceptor_yields(monkeypatch):
    # Flag ON + engine available: the interceptor YIELDS (returns None) so the
    # turn falls through to the LLM engine + the get_program_topic tool.
    from app.flows import parent_flow
    swapped = dataclasses.replace(
        config_module.settings, USE_PROGRAM_TOPICS=True, USE_PARENT_LLM_ENGINE=True,
    )
    monkeypatch.setattr(parent_flow, "settings", swapped)
    conv = Conversation(sender_id="t", platform="messenger")
    out = parent_flow._maybe_handle_camp_topic_facts(conv, "უსაფრთხოება როგორ არის ბანაკში?")
    assert out is None


def test_flag_on_but_engine_off_does_not_yield(monkeypatch):
    # Guard: the bypass requires BOTH flags. Topic flag on but engine OFF ⇒ the
    # interceptor still answers (no point yielding to an engine that won't run).
    from app.flows import parent_flow
    swapped = dataclasses.replace(
        config_module.settings, USE_PROGRAM_TOPICS=True, USE_PARENT_LLM_ENGINE=False,
    )
    monkeypatch.setattr(parent_flow, "settings", swapped)
    conv = Conversation(sender_id="t", platform="messenger")
    out = parent_flow._maybe_handle_camp_topic_facts(conv, "უსაფრთხოება როგორ არის ბანაკში?")
    assert out and out.strip()


def test_topic_tool_available_to_engine_when_flag_on():
    tools = ple.build_active_tools(use_dynamic=False, use_learning=False, use_topics=True)
    assert pt.TOOL_GET_PROGRAM_TOPIC in [t["function"]["name"] for t in tools]


def test_e2e_topic_question_reaches_engine_when_flag_on(monkeypatch):
    # End-to-end: both flags on → the deterministic topic interceptor yields and
    # a topic question reaches the LLM engine (replaced by a fake, no OpenAI
    # call). Registration reopened so no dead-season interceptor pre-empts it.
    from app.flows import parent_flow
    swapped = dataclasses.replace(
        config_module.settings, USE_PROGRAM_TOPICS=True, USE_PARENT_LLM_ENGINE=True,
    )
    monkeypatch.setattr(parent_flow, "settings", swapped)
    monkeypatch.setattr(ple, "run_parent_llm_turn", lambda *a, **k: "ENGINE_REPLY")
    monkeypatch.setattr(
        "app.services.admin_config_service.get_camp_registration_status",
        lambda: "open",
    )
    conv = Conversation(sender_id="t", platform="messenger")
    conv.history.append({"role": "assistant", "content": "_prior"})  # skip first-turn welcome
    out = parent_flow.handle(conv, "უსაფრთხოება როგორ არის ბანაკში?")
    assert out == "ENGINE_REPLY"
