"""A (review fixes): V5 = stream-lifecycle no longer misroutes a parent-
communication question to stream dates; V4 = the topic suffix nudges the model
to surface reassuring safety/medical facts BEFORE offering the manager."""
import dataclasses

import app.config as config_module
import app.agent.llm.parent_llm_engine as ple
from app.flows.parent_flow import _is_camp_stream_lifecycle_question as is_stream_q


# -- V5 ---------------------------------------------------------------------
def test_v5_child_wellbeing_question_is_not_a_stream_question():
    # The V5 bug: „მიმდინარეობისას" matched the stream-„ongoing?" marker.
    assert is_stream_q("როგორ გავიგებ ბანაკის მიმდინარეობისას ჩემი შვილი კარგადაა თუ არა?") is False
    assert is_stream_q("ჩემი შვილი როგორ არის ბანაკში?") is False


def test_v5_real_stream_questions_still_fire():
    assert is_stream_q("ბანაკი უკვე დაიწყო?") is True
    assert is_stream_q("ბანაკის ნაკადი მიმდინარეობს?") is True
    assert is_stream_q("ბანაკის ნაკადები როდის არის?") is True


# -- V4 ---------------------------------------------------------------------
def test_v4_suffix_nudges_facts_before_manager(monkeypatch):
    swapped = dataclasses.replace(config_module.settings, USE_PROGRAM_TOPICS=True)
    monkeypatch.setattr(ple, "settings", swapped)
    suffix = ple._topic_tool_prompt_suffix()
    assert "სამედიცინო პერსონალი 24/7" in suffix        # surface the reassuring fact
    assert "პირდაპირ მენეჯერზე ნუ გადახვალ" in suffix   # don't jump straight to manager


def test_v4_suffix_still_empty_when_flag_off():
    assert ple._topic_tool_prompt_suffix() == ""         # flag-off byte-identity intact
