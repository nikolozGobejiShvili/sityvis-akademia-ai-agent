"""OpenAI Model Compatibility Patch — regression tests.

Live error this patch resolves::

    openai.BadRequestError: Unsupported parameter: 'max_tokens' is not
    supported with this model. Use 'max_completion_tokens' instead.

GPT-5.x / GPT-5.4-mini / o1 / o3 / o4-mini reject ``max_tokens``;
older models (gpt-4.1-mini, gpt-4o) still use it. The service
helper ``_uses_max_completion_tokens`` selects the correct kwarg
shape per model. Tests verify:

  * gpt-4.1-mini → ``max_tokens`` (legacy).
  * gpt-5.4-mini → ``max_completion_tokens`` (new).
  * Both shapes NEVER appear in the same request.
  * Both ``_chat_completion`` and ``chat_with_tools`` honor the
    selection.
  * Tools and temperature pass through unchanged for both families.
  * Parent and Adult LLM engines can drive a GPT-5.x request through
    ``chat_with_tools`` without ``BadRequestError`` caused by
    ``max_tokens``.

All OpenAI client interactions are mocked. No network calls.
"""

from __future__ import annotations

import dataclasses
from types import SimpleNamespace
from typing import Any

import pytest

import app.config as config_module
from app.services import openai_service


def _swap_model(monkeypatch, model: str) -> None:
    """Replace ``openai_service.settings`` with a copy whose
    OPENAI_MODEL is the given value. Frozen Settings dataclass means
    we can't mutate in place — ``dataclasses.replace`` is the
    canonical workaround used elsewhere in the test suite.
    """
    swapped = dataclasses.replace(
        config_module.settings, OPENAI_MODEL=model,
    )
    monkeypatch.setattr(openai_service, "settings", swapped)


# =========================================================================
# 1 — Helper unit tests
# =========================================================================


@pytest.mark.parametrize(
    "model,expected",
    [
        ("gpt-4.1-mini", False),
        ("gpt-4o-mini", False),
        ("gpt-4o", False),
        ("gpt-4", False),
        ("gpt-3.5-turbo", False),
        ("", False),
        (None, False),
        ("gpt-5", True),
        ("gpt-5-mini", True),
        ("gpt-5.4-mini", True),
        ("gpt-5.4", True),
        ("o1", True),
        ("o1-mini", True),
        ("o3", True),
        ("o3-mini", True),
        ("o4-mini", True),
        # Case insensitivity.
        ("GPT-5.4-MINI", True),
        ("Gpt-4.1-Mini", False),
    ],
)
def test_uses_max_completion_tokens_matrix(model, expected):
    assert openai_service._uses_max_completion_tokens(model) is expected


def test_token_param_name_legacy():
    assert openai_service._token_param_name("gpt-4.1-mini") == "max_tokens"


def test_token_param_name_new_family():
    assert openai_service._token_param_name("gpt-5.4-mini") == "max_completion_tokens"


# =========================================================================
# 2 — Builder unit tests
# =========================================================================


def test_build_completion_kwargs_legacy_uses_max_tokens():
    kwargs = openai_service._build_completion_kwargs(
        model="gpt-4.1-mini",
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=300,
        temperature=0.7,
    )
    assert "max_tokens" in kwargs
    assert "max_completion_tokens" not in kwargs
    assert kwargs["max_tokens"] == 300
    assert kwargs["temperature"] == 0.7
    assert kwargs["model"] == "gpt-4.1-mini"


def test_build_completion_kwargs_new_family_uses_max_completion_tokens():
    kwargs = openai_service._build_completion_kwargs(
        model="gpt-5.4-mini",
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=300,
        temperature=0.7,
    )
    assert "max_completion_tokens" in kwargs
    assert "max_tokens" not in kwargs, (
        "MUST NOT send both — OpenAI returns 400 if both are present."
    )
    assert kwargs["max_completion_tokens"] == 300


def test_build_completion_kwargs_passes_tools_and_tool_choice():
    tools = [{"type": "function", "function": {"name": "x"}}]
    kwargs = openai_service._build_completion_kwargs(
        model="gpt-5.4-mini",
        messages=[],
        max_tokens=100,
        temperature=0.0,
        tools=tools,
        tool_choice="auto",
    )
    assert kwargs["tools"] is tools
    assert kwargs["tool_choice"] == "auto"


def test_build_completion_kwargs_omits_temperature_when_none():
    kwargs = openai_service._build_completion_kwargs(
        model="gpt-4.1-mini",
        messages=[],
        max_tokens=50,
        temperature=None,
    )
    assert "temperature" not in kwargs


def test_build_completion_kwargs_omits_tools_when_none():
    kwargs = openai_service._build_completion_kwargs(
        model="gpt-4.1-mini",
        messages=[],
        max_tokens=50,
        temperature=0.7,
        tools=None,
        tool_choice=None,
    )
    assert "tools" not in kwargs
    assert "tool_choice" not in kwargs


# =========================================================================
# 3 — End-to-end: _chat_completion sends correct kwarg
# =========================================================================


class _FakeChoice:
    def __init__(self, content: str):
        self.message = SimpleNamespace(content=content)


class _FakeResponse:
    def __init__(self, content: str = "hello"):
        self.choices = [_FakeChoice(content)]


class _RecordingClient:
    """Mocks OpenAI() client object — records all create() kwargs so
    tests can assert which parameter shape was sent."""

    def __init__(self, content: str = "hello"):
        self.calls: list[dict[str, Any]] = []
        self._content = content
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=self._create),
        )

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        return _FakeResponse(self._content)


def test_chat_completion_sends_max_tokens_for_legacy(monkeypatch):
    client = _RecordingClient(content="ok")
    _swap_model(monkeypatch, "gpt-4.1-mini")
    monkeypatch.setattr(openai_service, "_client", lambda: client)

    result = openai_service._chat_completion(
        messages=[{"role": "user", "content": "test"}],
        max_tokens=200,
        temperature=0.5,
    )

    assert result == "ok"
    assert len(client.calls) == 1
    sent = client.calls[0]
    assert sent["max_tokens"] == 200
    assert "max_completion_tokens" not in sent


def test_chat_completion_sends_max_completion_tokens_for_new_family(
    monkeypatch,
):
    client = _RecordingClient(content="ok")
    _swap_model(monkeypatch, "gpt-5.4-mini")
    monkeypatch.setattr(openai_service, "_client", lambda: client)

    openai_service._chat_completion(
        messages=[{"role": "user", "content": "test"}],
        max_tokens=200,
        temperature=0.5,
    )

    sent = client.calls[0]
    assert sent["max_completion_tokens"] == 200
    assert "max_tokens" not in sent, (
        "Live bug returns 400 when both are present."
    )


# =========================================================================
# 4 — End-to-end: chat_with_tools sends correct kwarg
# =========================================================================


PARENT_TOOLS_SAMPLE = [
    {
        "type": "function",
        "function": {"name": "get_camp_info", "parameters": {"type": "object"}},
    },
]


def test_chat_with_tools_sends_max_tokens_for_legacy(monkeypatch):
    client = _RecordingClient(content="")
    _swap_model(monkeypatch, "gpt-4.1-mini")
    monkeypatch.setattr(openai_service, "_client", lambda: client)

    openai_service.chat_with_tools(
        messages=[{"role": "user", "content": "test"}],
        tools=PARENT_TOOLS_SAMPLE,
        tool_choice="auto",
        max_tokens=500,
        temperature=0.7,
    )

    sent = client.calls[0]
    assert sent["max_tokens"] == 500
    assert "max_completion_tokens" not in sent
    assert sent["tools"] is PARENT_TOOLS_SAMPLE
    assert sent["tool_choice"] == "auto"


def test_chat_with_tools_sends_max_completion_tokens_for_new_family(
    monkeypatch,
):
    client = _RecordingClient(content="")
    _swap_model(monkeypatch, "gpt-5.4-mini")
    monkeypatch.setattr(openai_service, "_client", lambda: client)

    openai_service.chat_with_tools(
        messages=[{"role": "user", "content": "test"}],
        tools=PARENT_TOOLS_SAMPLE,
        tool_choice="auto",
        max_tokens=500,
        temperature=0.7,
    )

    sent = client.calls[0]
    assert sent["max_completion_tokens"] == 500
    assert "max_tokens" not in sent
    # Tools must still pass through unchanged for the new model family.
    assert sent["tools"] is PARENT_TOOLS_SAMPLE
    assert sent["tool_choice"] == "auto"


# =========================================================================
# 5 — Engine integration: Parent + Adult engines drive the new family
# =========================================================================


def test_parent_engine_does_not_send_max_tokens_under_new_model(monkeypatch):
    """Parent LLM engine builds messages and calls chat_with_tools.
    With model=gpt-5.4-mini, the resulting OpenAI request MUST NOT
    contain ``max_tokens`` — the live BadRequest fix."""
    from app.agent.llm import parent_llm_engine
    from app.models.conversation import Conversation
    from app.models.lead import Lead

    client = _RecordingClient(content="ok-no-tools")
    _swap_model(monkeypatch, "gpt-5.4-mini")
    monkeypatch.setattr(openai_service, "_client", lambda: client)

    conv = Conversation(sender_id="s_compat_p", platform="instagram", segment="PARENT")
    lead = Lead(sender_id="s_compat_p", platform="instagram", segment="PARENT")
    conv.lead = lead

    parent_llm_engine.run_parent_llm_turn(
        user_message="ფასი მაინტერესებს",
        conversation=conv,
        lead=lead,
        sender_id=conv.sender_id,
        platform="instagram",
    )

    # Engine made at least one chat.completions call.
    assert client.calls, "engine should have made at least one OpenAI call"
    for sent in client.calls:
        assert "max_completion_tokens" in sent
        assert "max_tokens" not in sent


def test_adult_engine_does_not_send_max_tokens_under_new_model(monkeypatch):
    """Adult LLM engine path: same invariant for the new model family."""
    from app.agent.llm import adult_llm_engine
    from app.models.conversation import Conversation
    from app.models.lead import Lead

    client = _RecordingClient(content="ok-no-tools")
    _swap_model(monkeypatch, "gpt-5.4-mini")
    monkeypatch.setattr(openai_service, "_client", lambda: client)

    conv = Conversation(sender_id="s_compat_a", platform="instagram", segment="ADULT")
    lead = Lead(sender_id="s_compat_a", platform="instagram", segment="ADULT")
    conv.lead = lead

    adult_llm_engine.run_adult_llm_turn(
        user_message="ღონისძიება მაინტერესებს ჩემთვის",
        conversation=conv,
        lead=lead,
        sender_id=conv.sender_id,
        platform="instagram",
    )

    assert client.calls, "adult engine should have made at least one OpenAI call"
    for sent in client.calls:
        assert "max_completion_tokens" in sent
        assert "max_tokens" not in sent


# =========================================================================
# 6 — Regression: existing OpenAI-service behaviour unchanged for current
# production model.
# =========================================================================


def test_chat_completion_existing_legacy_path_byte_compatible(monkeypatch):
    """Sanity — under the production model (gpt-4.1-mini), kwargs sent
    to OpenAI match the pre-patch shape exactly: model + messages +
    max_tokens + temperature, no extra keys.
    """
    client = _RecordingClient(content="hello")
    _swap_model(monkeypatch, "gpt-4.1-mini")
    monkeypatch.setattr(openai_service, "_client", lambda: client)

    openai_service._chat_completion(
        messages=[{"role": "user", "content": "ping"}],
        max_tokens=50,
        temperature=0.0,
    )

    sent = client.calls[0]
    assert set(sent.keys()) == {"model", "messages", "max_tokens", "temperature"}
    assert sent["model"] == "gpt-4.1-mini"
    assert sent["max_tokens"] == 50
    assert sent["temperature"] == 0.0
