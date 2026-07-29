"""Claude setup-token backend — regression tests.

Ported from the Car_App Android project, where this approach is proven
in production. The three details that actually break in the field, and
which these tests pin down:

  1. Auth shape is chosen by TOKEN PREFIX, not by config. ``sk-ant-oat``
     (a ``claude setup-token``) must go out as ``Authorization: Bearer``
     plus the OAuth beta header; anything else as ``x-api-key``.

  2. The Claude Code billing attribution must be the FIRST LINE of the
     system prompt on EVERY call path. Without it a setup token reaches
     Haiku but answers 400 for Sonnet/Opus — so a test that only covers
     the plain-completion path would pass while the tool loop is broken.

  3. Tokens pasted from a clipboard carry invisible characters that make
     the auth header invalid and produce an unhelpful 401.

Plus the wire bridge: the engines are OpenAI-shaped and must keep working
untouched, so the adapter's output is fed through the ACTUAL accessors
from ``parent_llm_engine`` rather than a hand-written approximation.

Every HTTP call is mocked. No network, no credentials required.
"""

from __future__ import annotations

import dataclasses
import json
from typing import Any

import pytest

import app.config as config_module
from app.agent.llm import parent_llm_engine as engine
from app.services import anthropic_service, openai_service

SETUP_TOKEN = "sk-ant-oat01-TESTTOKENVALUE"
API_KEY = "sk-ant-api03-TESTKEYVALUE"

_TEXT_PAYLOAD: dict[str, Any] = {
    "id": "msg_1",
    "model": "claude-sonnet-4-6",
    "content": [{"type": "text", "text": "გამარჯობა"}],
    "stop_reason": "end_turn",
    "usage": {"input_tokens": 10, "output_tokens": 3},
}

_TOOL_PAYLOAD: dict[str, Any] = {
    "id": "msg_2",
    "model": "claude-sonnet-4-6",
    "content": [
        {"type": "text", "text": "ვინახავ"},
        {
            "type": "tool_use",
            "id": "toolu_01",
            "name": "save_lead_info",
            "input": {"field": "name", "value": "ნიკა"},
        },
    ],
    "stop_reason": "tool_use",
    "usage": {"input_tokens": 20, "output_tokens": 8},
}

_OPENAI_TOOLS = [{
    "type": "function",
    "function": {
        "name": "save_lead_info",
        "description": "Store a lead field.",
        "parameters": {
            "type": "object",
            "properties": {"field": {"type": "string"}},
            "required": ["field"],
        },
    },
}]


class _FakeResponse:
    def __init__(self, payload: Any, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self) -> Any:
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


def _configure(monkeypatch, **overrides) -> None:
    """Swap the settings singleton in BOTH service modules.

    ``Settings`` is a frozen dataclass, so ``dataclasses.replace`` is the
    canonical workaround used elsewhere in this suite. Both modules hold
    their own reference, so both must be patched or the provider switch
    and the credential lookup disagree.
    """
    swapped = dataclasses.replace(config_module.settings, **overrides)
    monkeypatch.setattr(openai_service, "settings", swapped)
    monkeypatch.setattr(anthropic_service, "settings", swapped)


def _capture(monkeypatch, payload: Any = None, status_code: int = 200) -> dict:
    """Intercept the outbound HTTP call and record what was sent."""
    captured: dict[str, Any] = {}

    def fake_post(url, headers=None, json=None, timeout=None):  # noqa: A002
        captured["url"] = url
        captured["headers"] = headers
        captured["body"] = json
        captured["timeout"] = timeout
        return _FakeResponse(
            _TEXT_PAYLOAD if payload is None else payload, status_code,
        )

    monkeypatch.setattr(anthropic_service.httpx, "post", fake_post)
    return captured


@pytest.fixture(autouse=True)
def _reset_misconfig_flag(monkeypatch):
    """The one-shot misconfiguration warning is module state — reset it
    so test order cannot mask the log-once assertion."""
    monkeypatch.setattr(openai_service, "_anthropic_misconfig_logged", False)


# =========================================================================
# 1 — Credential handling
# =========================================================================


@pytest.mark.parametrize(
    "raw,expected",
    [
        (f"  {SETUP_TOKEN}  ", SETUP_TOKEN),           # surrounding spaces
        (f"{SETUP_TOKEN}\n", SETUP_TOKEN),             # trailing newline
        (f"​{SETUP_TOKEN}​", SETUP_TOKEN),   # zero-width spaces
        (f"{SETUP_TOKEN[:10]} {SETUP_TOKEN[10:]}", SETUP_TOKEN),  # nbsp
        ("", ""),
        (None, ""),
    ],
)
def test_sanitize_token_strips_invisible_characters(raw, expected):
    assert anthropic_service.sanitize_token(raw) == expected


def test_setup_token_detected_by_prefix():
    assert anthropic_service.is_setup_token(SETUP_TOKEN) is True
    assert anthropic_service.is_setup_token(API_KEY) is False
    assert anthropic_service.is_setup_token("") is False


def test_setup_token_uses_bearer_and_oauth_beta():
    headers = anthropic_service._auth_headers(SETUP_TOKEN)
    assert headers["authorization"] == f"Bearer {SETUP_TOKEN}"
    assert "oauth-2025-04-20" in headers["anthropic-beta"]
    assert "x-api-key" not in headers


def test_api_key_uses_x_api_key_header():
    headers = anthropic_service._auth_headers(API_KEY)
    assert headers["x-api-key"] == API_KEY
    assert "authorization" not in headers
    assert "anthropic-beta" not in headers


def test_auth_kind_never_exposes_the_token(monkeypatch):
    _configure(monkeypatch, ANTHROPIC_AUTH_TOKEN=SETUP_TOKEN)
    kind = anthropic_service.auth_kind()
    assert kind == "setup-token"
    assert SETUP_TOKEN not in kind

    _configure(monkeypatch, ANTHROPIC_AUTH_TOKEN=API_KEY)
    assert anthropic_service.auth_kind() == "api-key"

    _configure(monkeypatch, ANTHROPIC_AUTH_TOKEN="")
    assert anthropic_service.auth_kind() == "none"
    assert anthropic_service.is_configured() is False


# =========================================================================
# 2 — Billing attribution (the Sonnet/Opus unlock)
# =========================================================================


def test_billing_attribution_prepended_for_setup_token():
    out = anthropic_service._apply_billing_attribution("SYSTEM", SETUP_TOKEN)
    first_line = out.splitlines()[0]
    assert first_line.startswith("x-anthropic-billing-header:")
    assert "cc_entrypoint=cli" in first_line
    assert out.endswith("SYSTEM")


def test_billing_attribution_skipped_for_api_key():
    assert anthropic_service._apply_billing_attribution("SYSTEM", API_KEY) == "SYSTEM"


def test_billing_attribution_present_on_plain_completion(monkeypatch):
    _configure(monkeypatch, ANTHROPIC_AUTH_TOKEN=SETUP_TOKEN)
    captured = _capture(monkeypatch)

    anthropic_service.chat_completion(
        messages=[
            {"role": "system", "content": "SYSTEM"},
            {"role": "user", "content": "hi"},
        ],
        max_tokens=50,
        temperature=0.2,
    )

    assert captured["body"]["system"].startswith("x-anthropic-billing-header:")


def test_billing_attribution_present_on_tool_call(monkeypatch):
    """The path that would silently break if attribution were applied in
    only one place — the sales engines are entirely tool-driven."""
    _configure(monkeypatch, ANTHROPIC_AUTH_TOKEN=SETUP_TOKEN)
    captured = _capture(monkeypatch, _TOOL_PAYLOAD)

    anthropic_service.chat_with_tools(
        messages=[
            {"role": "system", "content": "SYSTEM"},
            {"role": "user", "content": "ჩემი სახელია ნიკა"},
        ],
        tools=_OPENAI_TOOLS,
    )

    assert captured["body"]["system"].startswith("x-anthropic-billing-header:")


def test_billing_attribution_present_on_test_connection(monkeypatch):
    _configure(monkeypatch, ANTHROPIC_AUTH_TOKEN=SETUP_TOKEN)
    captured = _capture(monkeypatch)

    ok, _ = anthropic_service.test_connection()

    assert ok is True
    assert captured["body"]["system"].startswith("x-anthropic-billing-header:")


def test_billing_attribution_added_even_with_no_system_messages(monkeypatch):
    _configure(monkeypatch, ANTHROPIC_AUTH_TOKEN=SETUP_TOKEN)
    captured = _capture(monkeypatch)

    anthropic_service.chat_completion(
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=10,
        temperature=0.0,
    )

    assert captured["body"]["system"].startswith("x-anthropic-billing-header:")


# =========================================================================
# 3 — OpenAI → Anthropic message translation
# =========================================================================


def test_system_turns_are_hoisted_in_order():
    """``parent_llm_engine`` appends a reasoning directive as a system
    turn right before the user message. Anthropic has no mid-conversation
    system role, so it must land in the top-level system string."""
    system, turns = anthropic_service.split_messages([
        {"role": "system", "content": "BASE"},
        {"role": "user", "content": "hello"},
        {"role": "system", "content": "DIRECTIVE"},
        {"role": "user", "content": "again"},
    ])

    assert system == "BASE\n\nDIRECTIVE"
    assert all(turn["role"] != "system" for turn in turns)


def test_tool_result_becomes_user_tool_result_block():
    _, turns = anthropic_service.split_messages([
        {"role": "user", "content": "hi"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "id": "toolu_01",
                "type": "function",
                "function": {
                    "name": "save_lead_info",
                    "arguments": '{"field": "name"}',
                },
            }],
        },
        {
            "role": "tool",
            "tool_call_id": "toolu_01",
            "name": "save_lead_info",
            "content": '{"success": true}',
        },
    ])

    assistant = turns[1]
    assert assistant["role"] == "assistant"
    assert assistant["content"][0]["type"] == "tool_use"
    assert assistant["content"][0]["input"] == {"field": "name"}

    result = turns[2]
    assert result["role"] == "user"
    assert result["content"][0]["type"] == "tool_result"
    assert result["content"][0]["tool_use_id"] == "toolu_01"


def test_malformed_tool_arguments_degrade_to_empty_object():
    _, turns = anthropic_service.split_messages([
        {"role": "user", "content": "hi"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "id": "toolu_01",
                "type": "function",
                "function": {"name": "t", "arguments": "{not json"},
            }],
        },
    ])
    assert turns[1]["content"][0]["input"] == {}


def test_consecutive_same_role_turns_are_merged():
    """Anthropic requires strictly alternating roles. A multi-tool round
    produces several tool_result user turns back to back."""
    _, turns = anthropic_service.split_messages([
        {"role": "user", "content": "hi"},
        {"role": "tool", "tool_call_id": "a", "content": "1"},
        {"role": "tool", "tool_call_id": "b", "content": "2"},
    ])

    roles = [turn["role"] for turn in turns]
    assert roles == ["user", "user"] or roles == ["user"]
    # Both results survive the merge regardless of how they grouped.
    blocks = [b for turn in turns for b in turn["content"]]
    ids = [b.get("tool_use_id") for b in blocks if b["type"] == "tool_result"]
    assert ids == ["a", "b"]


def test_history_opening_with_assistant_gets_a_user_opener():
    """This bot greets first, so a real history can start with an
    assistant turn — which Anthropic rejects."""
    _, turns = anthropic_service.split_messages([
        {"role": "system", "content": "S"},
        {"role": "assistant", "content": "გამარჯობა!"},
        {"role": "user", "content": "ფასი?"},
    ])

    assert turns[0]["role"] == "user"
    # The greeting is preserved, not discarded.
    assert any(
        block.get("text") == "გამარჯობა!"
        for turn in turns for block in turn["content"]
    )


def test_empty_and_blank_turns_are_dropped():
    _, turns = anthropic_service.split_messages([
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": ""},
        {"role": "assistant", "content": None},
        {"role": "user", "content": "   "},
    ])
    assert len(turns) == 1
    assert turns[0]["content"][0]["text"] == "hi"


def test_request_without_user_turns_is_rejected(monkeypatch):
    _configure(monkeypatch, ANTHROPIC_AUTH_TOKEN=SETUP_TOKEN)
    _capture(monkeypatch)

    with pytest.raises(RuntimeError, match="no user turns"):
        anthropic_service.chat_completion(
            messages=[{"role": "system", "content": "S"}],
            max_tokens=10,
            temperature=0.0,
        )


def test_temperature_is_clamped_to_anthropic_range(monkeypatch):
    _configure(monkeypatch, ANTHROPIC_AUTH_TOKEN=SETUP_TOKEN)
    captured = _capture(monkeypatch)

    anthropic_service.chat_completion(
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=10,
        temperature=1.8,
    )
    assert captured["body"]["temperature"] == 1.0


# =========================================================================
# 4 — Tool schema translation
# =========================================================================


def test_openai_function_tools_become_anthropic_tools():
    translated = anthropic_service.translate_tools(_OPENAI_TOOLS)
    assert translated == [{
        "name": "save_lead_info",
        "description": "Store a lead field.",
        "input_schema": {
            "type": "object",
            "properties": {"field": {"type": "string"}},
            "required": ["field"],
        },
    }]


def test_tool_without_parameters_gets_an_empty_object_schema():
    translated = anthropic_service.translate_tools([
        {"type": "function", "function": {"name": "ping"}},
    ])
    assert translated[0]["input_schema"] == {"type": "object", "properties": {}}


# =========================================================================
# 5 — Anthropic → OpenAI response bridge
# =========================================================================


def test_response_is_readable_by_the_real_engine_accessors():
    """The whole no-engine-changes claim rests on this: the adapter's
    output is parsed with the ACTUAL helpers from parent_llm_engine."""
    response = anthropic_service.to_openai_response(_TOOL_PAYLOAD)

    choice = engine._first_choice(response)
    assert choice is not None

    message = engine._choice_message(choice)
    assert engine._message_content(message) == "ვინახავ"

    calls = engine._tool_calls(message)
    assert len(calls) == 1
    assert engine._tool_name(calls[0]) == "save_lead_info"
    assert engine._tool_call_id(calls[0]) == "toolu_01"
    assert engine._parse_tool_args(engine._tool_args(calls[0])) == {
        "field": "name", "value": "ნიკა",
    }


def test_tool_arguments_are_a_json_string_like_openai():
    response = anthropic_service.to_openai_response(_TOOL_PAYLOAD)
    arguments = response["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"]
    assert isinstance(arguments, str)
    assert json.loads(arguments) == {"field": "name", "value": "ნიკა"}


def test_text_only_response_has_no_tool_calls():
    response = anthropic_service.to_openai_response(_TEXT_PAYLOAD)
    message = engine._choice_message(engine._first_choice(response))
    assert engine._tool_calls(message) == []
    assert engine._message_content(message) == "გამარჯობა"


def test_assistant_tool_call_round_trips_back_into_a_request():
    """The engine re-serializes the assistant turn and re-sends it on the
    next loop iteration — that dict must translate back to a tool_use
    block or the second iteration loses the tool call."""
    response = anthropic_service.to_openai_response(_TOOL_PAYLOAD)
    message = engine._choice_message(engine._first_choice(response))
    replayed = engine._assistant_message_for_tool_calls(message)

    _, turns = anthropic_service.split_messages([
        {"role": "user", "content": "ჩემი სახელია ნიკა"},
        replayed,
        {"role": "tool", "tool_call_id": "toolu_01", "content": "{}"},
    ])

    tool_use = [b for b in turns[1]["content"] if b["type"] == "tool_use"]
    assert tool_use[0]["id"] == "toolu_01"
    assert tool_use[0]["input"] == {"field": "name", "value": "ნიკა"}


# =========================================================================
# 6 — Provider switch inside openai_service
# =========================================================================


def test_default_provider_never_touches_anthropic(monkeypatch):
    """Default config must behave exactly as before this patch."""
    _configure(
        monkeypatch, LLM_PROVIDER="openai", ANTHROPIC_AUTH_TOKEN=SETUP_TOKEN,
    )

    def explode(**_kwargs):
        raise AssertionError("Anthropic must not be called under LLM_PROVIDER=openai")

    monkeypatch.setattr(anthropic_service, "chat_completion", explode)
    monkeypatch.setattr(openai_service, "_openai_chat_completion", lambda **_k: "from-openai")

    assert openai_service._chat_completion(
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=10,
        temperature=0.0,
    ) == "from-openai"


def test_anthropic_provider_routes_completions_to_claude(monkeypatch):
    _configure(
        monkeypatch, LLM_PROVIDER="anthropic", ANTHROPIC_AUTH_TOKEN=SETUP_TOKEN,
    )
    _capture(monkeypatch)
    monkeypatch.setattr(
        openai_service, "_openai_chat_completion",
        lambda **_k: pytest.fail("OpenAI must not be called"),
    )

    assert openai_service._chat_completion(
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=10,
        temperature=0.0,
    ) == "გამარჯობა"


def test_anthropic_provider_routes_tool_calls_to_claude(monkeypatch):
    _configure(
        monkeypatch, LLM_PROVIDER="anthropic", ANTHROPIC_AUTH_TOKEN=SETUP_TOKEN,
    )
    _capture(monkeypatch, _TOOL_PAYLOAD)

    response = openai_service.chat_with_tools(
        messages=[{"role": "user", "content": "ჩემი სახელია ნიკა"}],
        tools=_OPENAI_TOOLS,
    )

    message = engine._choice_message(engine._first_choice(response))
    assert engine._tool_name(engine._tool_calls(message)[0]) == "save_lead_info"


def test_missing_token_falls_back_to_openai(monkeypatch):
    """LLM_PROVIDER=anthropic with no credential is a config mistake —
    it must not take live traffic down."""
    _configure(monkeypatch, LLM_PROVIDER="anthropic", ANTHROPIC_AUTH_TOKEN="")
    monkeypatch.setattr(openai_service, "_openai_chat_completion", lambda **_k: "from-openai")

    assert openai_service._chat_completion(
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=10,
        temperature=0.0,
    ) == "from-openai"
    assert openai_service._anthropic_misconfig_logged is True


# =========================================================================
# 7 — Failure handling
# =========================================================================


def test_api_error_message_is_surfaced_without_the_token(monkeypatch):
    _configure(monkeypatch, ANTHROPIC_AUTH_TOKEN=SETUP_TOKEN)
    _capture(
        monkeypatch,
        {"error": {"type": "invalid_request_error", "message": "model not found"}},
        status_code=400,
    )

    with pytest.raises(RuntimeError) as excinfo:
        anthropic_service.chat_completion(
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=10,
            temperature=0.0,
        )

    assert "model not found" in str(excinfo.value)
    assert SETUP_TOKEN not in str(excinfo.value)


def test_anthropic_failure_falls_back_to_openai(monkeypatch):
    _configure(
        monkeypatch,
        LLM_PROVIDER="anthropic",
        ANTHROPIC_AUTH_TOKEN=SETUP_TOKEN,
        ANTHROPIC_FALLBACK_TO_OPENAI=True,
    )
    monkeypatch.setattr(openai_service, "sleep", lambda _s: None)
    monkeypatch.setattr(
        anthropic_service, "chat_completion",
        lambda **_k: (_ for _ in ()).throw(RuntimeError("quota exceeded")),
    )
    monkeypatch.setattr(openai_service, "_openai_chat_completion", lambda **_k: "from-openai")

    assert openai_service._chat_completion(
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=10,
        temperature=0.0,
    ) == "from-openai"


def test_fallback_disabled_surfaces_the_anthropic_error(monkeypatch):
    _configure(
        monkeypatch,
        LLM_PROVIDER="anthropic",
        ANTHROPIC_AUTH_TOKEN=SETUP_TOKEN,
        ANTHROPIC_FALLBACK_TO_OPENAI=False,
    )
    monkeypatch.setattr(openai_service, "sleep", lambda _s: None)
    monkeypatch.setattr(
        anthropic_service, "chat_completion",
        lambda **_k: (_ for _ in ()).throw(RuntimeError("quota exceeded")),
    )
    monkeypatch.setattr(
        openai_service, "_openai_chat_completion",
        lambda **_k: pytest.fail("OpenAI must not be called when fallback is off"),
    )

    with pytest.raises(RuntimeError, match="quota exceeded"):
        openai_service._chat_completion(
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=10,
            temperature=0.0,
        )


def test_tool_call_failure_falls_back_to_openai(monkeypatch):
    _configure(
        monkeypatch,
        LLM_PROVIDER="anthropic",
        ANTHROPIC_AUTH_TOKEN=SETUP_TOKEN,
        ANTHROPIC_FALLBACK_TO_OPENAI=True,
    )
    monkeypatch.setattr(
        anthropic_service, "chat_with_tools",
        lambda **_k: (_ for _ in ()).throw(RuntimeError("overloaded")),
    )
    sentinel = object()
    monkeypatch.setattr(
        openai_service, "_client",
        lambda: type("C", (), {
            "chat": type("Ch", (), {
                "completions": type("Co", (), {
                    "create": staticmethod(lambda **_k: sentinel),
                })(),
            })(),
        })(),
    )

    assert openai_service.chat_with_tools(
        messages=[{"role": "user", "content": "hi"}],
        tools=_OPENAI_TOOLS,
    ) is sentinel


def test_connection_check_reports_failure_without_raising(monkeypatch):
    _configure(monkeypatch, ANTHROPIC_AUTH_TOKEN=SETUP_TOKEN)
    _capture(
        monkeypatch,
        {"error": {"message": "invalid x-api-key"}},
        status_code=401,
    )

    ok, detail = anthropic_service.test_connection()
    assert ok is False
    assert "invalid x-api-key" in detail


# =========================================================================
# 8 — Boot requirements
# =========================================================================
#
# Live Railway crash-loop (2026-07-29): the operator removed
# OPENAI_API_KEY from the dashboard after adding the Claude variables and
# the container died at import time, before any LLM call:
#
#   app.config.ConfigurationError:
#       Missing required variables in .env: OPENAI_API_KEY
#
# The LLM credential requirement must follow LLM_PROVIDER.

_BOOT_VARS = {
    "GOOGLE_SHEET_ID": "sheet",
    "GOOGLE_CALENDAR_ID": "cal",
    "META_PAGE_ID": "page",
    "INSTAGRAM_ACCOUNT_ID": "ig",
    "MESSENGER_PAGE_ACCESS_TOKEN": "tok",
    "MESSENGER_VERIFY_TOKEN": "verify",
}


def _env_only(monkeypatch, **values) -> None:
    """Point ``_env`` at exactly *values* — no .env, no process leakage."""
    monkeypatch.setattr(config_module, "ENV_VALUES", {})
    for name in (
        *_BOOT_VARS,
        "OPENAI_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_API_KEY",
        "LLM_PROVIDER",
        "ANTHROPIC_FALLBACK_TO_OPENAI",
    ):
        monkeypatch.delenv(name, raising=False)
    for name, value in values.items():
        monkeypatch.setenv(name, value)


def test_openai_provider_still_requires_the_openai_key(monkeypatch):
    _env_only(monkeypatch, **_BOOT_VARS)
    with pytest.raises(config_module.ConfigurationError, match="OPENAI_API_KEY"):
        config_module.Settings.from_env()


def test_anthropic_provider_boots_without_an_openai_key(monkeypatch):
    """The exact configuration that crash-looped on Railway."""
    _env_only(
        monkeypatch,
        **_BOOT_VARS,
        LLM_PROVIDER="anthropic",
        ANTHROPIC_AUTH_TOKEN=SETUP_TOKEN,
    )
    resolved = config_module.Settings.from_env()
    assert resolved.LLM_PROVIDER == "anthropic"
    assert resolved.OPENAI_API_KEY == ""


def test_anthropic_api_key_alias_satisfies_the_requirement(monkeypatch):
    _env_only(
        monkeypatch,
        **_BOOT_VARS,
        LLM_PROVIDER="anthropic",
        ANTHROPIC_API_KEY=SETUP_TOKEN,
    )
    assert config_module.Settings.from_env().ANTHROPIC_AUTH_TOKEN == SETUP_TOKEN


def test_anthropic_provider_without_any_credential_fails_loudly(monkeypatch):
    _env_only(monkeypatch, **_BOOT_VARS, LLM_PROVIDER="anthropic")
    with pytest.raises(config_module.ConfigurationError) as excinfo:
        config_module.Settings.from_env()
    message = str(excinfo.value)
    assert "ANTHROPIC_AUTH_TOKEN or ANTHROPIC_API_KEY" in message
    assert "LLM_PROVIDER=anthropic" in message


def test_fallback_auto_disables_when_there_is_no_openai_key(monkeypatch):
    """Leaving the fallback nominally ON without a key would mean every
    retry fails — report the truth instead."""
    _env_only(
        monkeypatch,
        **_BOOT_VARS,
        LLM_PROVIDER="anthropic",
        ANTHROPIC_AUTH_TOKEN=SETUP_TOKEN,
        ANTHROPIC_FALLBACK_TO_OPENAI="true",
    )
    assert config_module.Settings.from_env().ANTHROPIC_FALLBACK_TO_OPENAI is False


def test_fallback_stays_on_when_both_credentials_are_present(monkeypatch):
    _env_only(
        monkeypatch,
        **_BOOT_VARS,
        LLM_PROVIDER="anthropic",
        ANTHROPIC_AUTH_TOKEN=SETUP_TOKEN,
        OPENAI_API_KEY="sk-openai",
    )
    assert config_module.Settings.from_env().ANTHROPIC_FALLBACK_TO_OPENAI is True
