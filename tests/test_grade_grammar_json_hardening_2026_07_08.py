"""Deterministic tests for the hardened evals.judge.grade_grammar JSON parsing.

No live LLM — the Anthropic client is stubbed. Proves that a messy-but-valid
grader response (```json fences + trailing prose + a brace inside a quoted
Georgian fragment — exactly the long-price-reply shape that broke the old
find('{')/rfind('}') slice) now parses; that a transient bad response is retried
once; and that a genuinely unparseable response raises an EXPLICIT
GrammarGraderError (never a silent pass, never a false FAIL).
"""
from __future__ import annotations

import pytest

from evals import judge


class _FakeBlock:
    def __init__(self, text):
        self.text = text


class _FakeResp:
    def __init__(self, text):
        self.content = [_FakeBlock(text)]


def _install_fake_anthropic(monkeypatch, responses):
    """Stub anthropic.Anthropic so client.messages.create returns `responses`
    in order (last one repeats). Returns a call-counter list."""
    import anthropic

    calls: list[int] = []

    class _FakeMessages:
        def create(self, **kwargs):
            i = len(calls)
            calls.append(i)
            text = responses[i] if i < len(responses) else responses[-1]
            return _FakeResp(text)

    class _FakeClient:
        def __init__(self, *a, **k):
            self.messages = _FakeMessages()

    monkeypatch.setattr(anthropic, "Anthropic", _FakeClient)
    return calls


_ALL_SIX = (
    '{"id":"cases","pass":true,"errors":[]},'
    '{"id":"conjugation","pass":false,"errors":[{"fragment":"ფასი 2150 {ლარი}",'
    '"correction":"ფასი 2150 ლარია","rule":"უღლება"}]},'
    '{"id":"agreement","pass":true,"errors":[]},'
    '{"id":"spelling","pass":true,"errors":[]},'
    '{"id":"word_order","pass":true,"errors":[]},'
    '{"id":"mixed_script","pass":true,"errors":[]}'
)

# ```json fence + leading prose + trailing prose + a brace inside a fragment
_MESSY_VALID = (
    "Sure, here is the grammar assessment:\n"
    "```json\n"
    '{"results": [' + _ALL_SIX + "]}\n"
    "```\n"
    "Let me know if you need anything else."
)


def test_extract_json_object_handles_fences_prose_and_inner_braces():
    blob = judge._extract_json_object(_MESSY_VALID)
    assert blob is not None
    import json
    parsed = json.loads(blob)
    assert len(parsed["results"]) == 6
    # a brace inside a string value must NOT truncate the object
    assert "{ლარი}" in blob


def test_extract_json_object_none_when_no_object():
    assert judge._extract_json_object("no json here at all") is None
    assert judge._extract_json_object("{unbalanced ") is None


def test_grade_grammar_parses_messy_but_valid_output(monkeypatch):
    calls = _install_fake_anthropic(monkeypatch, [_MESSY_VALID])
    out = judge.grade_grammar("ფასი 2150 ლარია, გადანაწილება შესაძლებელია 6 თვემდე.")
    assert len(calls) == 1            # parsed on the first try — no retry needed
    assert len(out) == 6
    by = {o["id"]: o for o in out}
    assert by["cases"]["pass"] is True
    assert by["conjugation"]["pass"] is False
    assert by["conjugation"]["errors"][0]["fragment"] == "ფასი 2150 {ლარი}"
    # the report renderer must still consume it cleanly
    block = judge.render_grammar_issues("t0", "ფასი 2150 ლარია", out)
    assert "უღლება" in block


def test_grade_grammar_retries_once_then_succeeds(monkeypatch):
    garbage = "I cannot answer that. {this is not valid json,,,"
    calls = _install_fake_anthropic(monkeypatch, [garbage, _MESSY_VALID])
    out = judge.grade_grammar("გამარჯობა")
    assert len(calls) == 2            # retried exactly once, then succeeded
    assert len(out) == 6
    assert {o["id"] for o in out} == {c[0] for c in judge.GRAMMAR_CRITERIA}


def test_grade_grammar_raises_explicit_error_after_retry_fails(monkeypatch):
    garbage = "sorry, no json {broken,,,"
    calls = _install_fake_anthropic(monkeypatch, [garbage, garbage, garbage])
    with pytest.raises(judge.GrammarGraderError):
        judge.grade_grammar("გამარჯობა")
    assert len(calls) == 2            # initial + ONE retry, then give up (no infinite loop)


def test_grade_grammar_missing_criterion_defaults_to_pass_not_fail(monkeypatch):
    # grader omits some ids → those default to pass=True (lenient, unchanged
    # behaviour) — never a false FAIL from a partial payload.
    partial = '{"results": [{"id":"cases","pass":true,"errors":[]}]}'
    _install_fake_anthropic(monkeypatch, [partial])
    out = judge.grade_grammar("ტექსტი")
    by = {o["id"]: o for o in out}
    assert all(by[o]["pass"] is True for o in by)
    assert len(out) == 6
