"""Capability #1 — topic-facts tool (get_program_topic). Flag USE_PROGRAM_TOPICS
converts the deterministic camp-topic interceptor into an LLM tool the model
reasons over. Flag OFF ⇒ byte-identical (interceptor answers, tool surface +
prompt unchanged)."""
from app.config import Settings


def test_program_topics_flag_defaults_off():
    assert Settings().USE_PROGRAM_TOPICS is False
