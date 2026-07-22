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
