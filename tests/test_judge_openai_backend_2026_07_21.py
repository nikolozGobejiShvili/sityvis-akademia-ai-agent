"""evals.judge OpenAI backend + backend-selection (2026-07-21, validation-loop fix).

The Anthropic judge key is down; the operator has a live OpenAI key, so the eval
judge now DEFAULTS to an OpenAI backend (gpt-5.4-mini — stronger than and distinct
from the agent's gpt-4.1-mini, limiting self-judging bias). These deterministic
tests (no live LLM) prove:
  * the token-param router picks max_completion_tokens for gpt-5.x / o-series and
    max_tokens for the legacy families,
  * `_judge_completion` OpenAI path returns the message content and sends the
    right token param + temperature + system/user roles,
  * the anthropic backend is still reachable (concatenates content blocks),
  * `judge_available` reflects the selected backend's SDK + key,
  * `judge()` parses the OpenAI JSON output through the shared chokepoint.
"""
from __future__ import annotations

import pytest

from evals import judge


# ---- token-param routing ----------------------------------------------------

@pytest.mark.parametrize("model,expect_mct", [
    ("gpt-5.4-mini", True),
    ("gpt-5-mini", True),
    ("o1-preview", True),
    ("o3-mini", True),
    ("gpt-4.1-mini", False),
    ("gpt-4o", False),
    ("claude-sonnet-4-6", False),
])
def test_openai_token_param_routing(model, expect_mct):
    assert judge._openai_uses_completion_tokens(model) is expect_mct


# ---- OpenAI completion path -------------------------------------------------

class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeChoice:
    def __init__(self, content):
        self.message = _FakeMessage(content)


class _FakeCompletion:
    def __init__(self, content):
        self.choices = [_FakeChoice(content)]


def _install_fake_openai(monkeypatch, content, capture):
    import openai

    class _FakeCompletions:
        def create(self, **kwargs):
            capture.append(kwargs)
            return _FakeCompletion(content)

    class _FakeChat:
        def __init__(self):
            self.completions = _FakeCompletions()

    class _FakeOpenAI:
        def __init__(self, *a, **k):
            self.chat = _FakeChat()

    monkeypatch.setattr(openai, "OpenAI", _FakeOpenAI)


def test_judge_completion_openai_returns_content_and_uses_completion_tokens(monkeypatch):
    monkeypatch.setattr(judge, "_JUDGE_BACKEND", "openai")
    monkeypatch.setattr(judge, "_JUDGE_MODEL", "gpt-5.4-mini")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    cap: list[dict] = []
    _install_fake_openai(monkeypatch, '  [{"index":0,"pass":true,"reason":"ok"}]  ', cap)

    out = judge._judge_completion("SYS", "USER", max_tokens=321, temperature=0)

    assert out == '[{"index":0,"pass":true,"reason":"ok"}]'          # stripped
    assert cap and cap[0]["model"] == "gpt-5.4-mini"
    assert cap[0]["max_completion_tokens"] == 321
    assert "max_tokens" not in cap[0]
    assert cap[0]["temperature"] == 0
    assert [m["role"] for m in cap[0]["messages"]] == ["system", "user"]


def test_judge_completion_openai_legacy_model_uses_max_tokens(monkeypatch):
    monkeypatch.setattr(judge, "_JUDGE_BACKEND", "openai")
    monkeypatch.setattr(judge, "_JUDGE_MODEL", "gpt-4.1-mini")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    cap: list[dict] = []
    _install_fake_openai(monkeypatch, "[]", cap)

    judge._judge_completion("SYS", "USER", max_tokens=99)

    assert cap[0]["max_tokens"] == 99
    assert "max_completion_tokens" not in cap[0]


# ---- Anthropic completion path still reachable ------------------------------

def test_judge_completion_anthropic_concatenates_blocks(monkeypatch):
    import anthropic

    class _Block:
        def __init__(self, text):
            self.text = text

    class _Resp:
        content = [_Block('[{"index":0,'), _Block('"pass":true,"reason":"ok"}]')]

    class _Messages:
        def create(self, **kwargs):
            return _Resp()

    class _Client:
        def __init__(self, *a, **k):
            self.messages = _Messages()

    monkeypatch.setattr(judge, "_JUDGE_BACKEND", "anthropic")
    monkeypatch.setattr(anthropic, "Anthropic", _Client)

    out = judge._judge_completion("SYS", "USER", max_tokens=100)
    assert out == '[{"index":0,"pass":true,"reason":"ok"}]'


# ---- availability -----------------------------------------------------------

def test_judge_available_openai_with_key(monkeypatch):
    monkeypatch.setattr(judge, "_JUDGE_BACKEND", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    ok, why = judge.judge_available()
    assert ok and why == ""


def test_judge_available_openai_missing_key(monkeypatch):
    monkeypatch.setattr(judge, "_JUDGE_BACKEND", "openai")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(judge, "_openai_api_key", lambda: "")   # block .env fallback
    ok, why = judge.judge_available()
    assert not ok and "OPENAI_API_KEY" in why


# ---- judge() end-to-end parse via the shared chokepoint ---------------------

def test_judge_parses_openai_json(monkeypatch):
    monkeypatch.setattr(
        judge, "_judge_completion",
        lambda system, user, *, max_tokens, temperature=0.0:
            '[{"index":0,"pass":true,"reason":"good"},'
            '{"index":1,"pass":false,"reason":"bad"}]',
    )
    out = judge.judge("ctx", ["c0", "c1"])
    assert out[0] == ("c0", True, "good")
    assert out[1] == ("c1", False, "bad")
