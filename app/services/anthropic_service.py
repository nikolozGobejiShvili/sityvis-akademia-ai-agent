"""Anthropic Claude backend with Claude Code **setup-token** support.

=========================================================================
Why this module exists (2026-07-29)
=========================================================================

``claude setup-token`` mints an OAuth token (``sk-ant-oat01-…``) that
bills against a Claude Pro/Max **subscription** instead of pay-per-token
API credits. This module lets the agent talk to the Anthropic Messages
API with either credential shape:

  * ``sk-ant-oat*``  → ``Authorization: Bearer`` + the OAuth beta header
  * ``sk-ant-api*``  → the classic ``x-api-key`` header

The caller never picks: :func:`_auth_headers` sniffs the prefix. Flipping
``ANTHROPIC_AUTH_TOKEN`` in ``.env`` between a setup token and an API key
needs no code change.

Three non-obvious details, all of them load-bearing — this approach was
proven in the Car_App Android project and ported here verbatim:

1. **Billing attribution lives in the SYSTEM PROMPT, not in a header.**
   Despite its ``x-anthropic-…`` name, :data:`_CC_BILLING_HEADER` is
   prepended as the first line of the ``system`` string. Without it an
   OAuth token only gets Haiku — Sonnet/Opus return 400. It must be
   applied on EVERY call path; miss one and exactly that path breaks.
   API keys are unaffected (the prefix is skipped for them).

2. **Tokens pasted from a clipboard carry invisible characters.**
   Zero-width marks and stray newlines corrupt the auth header and the
   API answers 401 with a message that says nothing about whitespace.
   :func:`sanitize_token` strips everything outside printable ASCII.

3. **The token is never logged** — not the value, not its length. Log
   lines carry the auth *kind* ("setup-token" / "api-key") only.

=========================================================================
Wire-format bridge
=========================================================================

The rest of this codebase speaks OpenAI chat-completions. Rather than
touch ``parent_llm_engine`` / ``adult_llm_engine`` (~6000 lines that read
responses through duck-typed accessors), this module translates in both
directions and hands back a **plain dict shaped like an OpenAI
response**. The engines' ``_first_choice`` / ``_choice_message`` /
``_tool_calls`` / ``_message_content`` helpers all accept dicts, so they
work unmodified.

  OpenAI ``messages``          → Anthropic ``system`` + ``messages``
  OpenAI ``tools`` (function)  → Anthropic ``tools`` (input_schema)
  Anthropic ``content`` blocks → OpenAI ``choices[0].message``

Anthropic is stricter than OpenAI about message shape, so the translator
also: hoists mid-conversation ``system`` turns into the top-level system
string, merges consecutive same-role turns, guarantees the first turn is
``user``, and drops empty blocks. Each rule is commented at its site.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


# ── Wire constants ──────────────────────────────────────────────────────

_API_URL = "https://api.anthropic.com/v1/messages"
_API_VERSION = "2023-06-01"
_TIMEOUT_SECONDS = 60.0

#: Setup tokens (``claude setup-token``) start with this prefix. Anything
#: else is treated as a classic API key.
_OAUTH_TOKEN_PREFIX = "sk-ant-oat"

#: Beta features requested for OAuth tokens. ``oauth-2025-04-20`` is what
#: makes the Bearer credential acceptable at all; prompt caching rides
#: along because it is free to ask for and cheap when it hits.
_OAUTH_BETA = "prompt-caching-2024-07-31,oauth-2025-04-20"

#: Prepended to the system prompt for OAuth tokens ONLY. See point (1) in
#: the module docstring — this is not an HTTP header despite the name.
_CC_BILLING_HEADER = (
    "x-anthropic-billing-header: cc_version=2.1.63.0a5; "
    "cc_entrypoint=cli; cch=00000;"
)

#: Anthropic requires the first message to be ``user``. This project's
#: histories can legitimately open with the bot's greeting, so a neutral
#: opener is inserted rather than discarding that turn.
_CONVERSATION_START_MARKER = "[conversation start]"


# ── Credentials ─────────────────────────────────────────────────────────


def sanitize_token(raw: str | None) -> str:
    """Strip everything outside printable ASCII, then trim.

    Clipboard round-trips (terminal → browser → ``.env``) routinely inject
    zero-width spaces, non-breaking spaces and trailing newlines. Any of
    them makes the Authorization header invalid and the API replies 401
    without hinting at the cause. See point (2) in the module docstring.
    """
    if not raw:
        return ""
    return "".join(ch for ch in raw if 32 <= ord(ch) <= 126).strip()


def is_setup_token(token: str | None) -> bool:
    """True when *token* is a ``claude setup-token`` OAuth credential."""
    return bool(token) and token.startswith(_OAUTH_TOKEN_PREFIX)


def auth_token() -> str:
    """The configured Anthropic credential, sanitized. ``""`` when unset."""
    return sanitize_token(getattr(settings, "ANTHROPIC_AUTH_TOKEN", ""))


def auth_kind(token: str | None = None) -> str:
    """Non-secret description of the active credential, safe to log."""
    resolved = auth_token() if token is None else token
    if not resolved:
        return "none"
    return "setup-token" if is_setup_token(resolved) else "api-key"


def is_configured() -> bool:
    """True when a usable Anthropic credential is present."""
    return bool(auth_token())


def _auth_headers(token: str) -> dict[str, str]:
    """Auth + version headers for *token*, branching on its shape."""
    headers = {
        "anthropic-version": _API_VERSION,
        "content-type": "application/json",
    }
    if is_setup_token(token):
        headers["authorization"] = f"Bearer {token}"
        headers["anthropic-beta"] = _OAUTH_BETA
    else:
        headers["x-api-key"] = token
    return headers


def _apply_billing_attribution(system_prompt: str, token: str) -> str:
    """Prepend the Claude Code billing attribution for OAuth tokens.

    Required server-side for a setup token to reach Sonnet/Opus — without
    it every model except Haiku answers 400. API keys pass through
    untouched.
    """
    if not is_setup_token(token):
        return system_prompt
    if not system_prompt:
        return _CC_BILLING_HEADER
    return f"{_CC_BILLING_HEADER}\n{system_prompt}"


# ── OpenAI → Anthropic: messages ────────────────────────────────────────


def _text_block(text: str) -> dict[str, Any]:
    return {"type": "text", "text": text}


def _content_to_text(content: Any) -> str:
    """Flatten an OpenAI ``content`` value to plain text.

    Handles the string form this codebase uses plus the multipart list
    form, so a caller that ever passes blocks does not silently lose text.
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict) and part.get("type") == "text":
                parts.append(str(part.get("text") or ""))
        return "".join(parts)
    return str(content)


def _tool_call_blocks(tool_calls: Any) -> list[dict[str, Any]]:
    """Convert OpenAI ``tool_calls`` into Anthropic ``tool_use`` blocks.

    ``function.arguments`` is a JSON *string* on the OpenAI wire (and in
    the dict the engines re-serialize between loop iterations), while
    Anthropic wants a decoded object. Undecodable arguments become ``{}``
    rather than raising — the engines already treat a malformed tool call
    as an empty-args call, and crashing the turn would be worse.
    """
    blocks: list[dict[str, Any]] = []
    for call in tool_calls or []:
        if not isinstance(call, dict):
            continue
        function = call.get("function") or {}
        raw_args = function.get("arguments")
        if isinstance(raw_args, dict):
            arguments = raw_args
        else:
            try:
                parsed = json.loads(raw_args or "{}")
            except (TypeError, ValueError):
                parsed = {}
            arguments = parsed if isinstance(parsed, dict) else {}
        blocks.append({
            "type": "tool_use",
            "id": str(call.get("id") or ""),
            "name": str(function.get("name") or ""),
            "input": arguments,
        })
    return blocks


def split_messages(
    messages: list[dict[str, Any]],
) -> tuple[str, list[dict[str, Any]]]:
    """Split OpenAI-format *messages* into (system text, Anthropic turns).

    Anthropic has no mid-conversation ``system`` role, so every system
    turn is hoisted into the top-level system string in original order,
    joined by blank lines. ``parent_llm_engine`` appends a reasoning
    directive as a system turn immediately before the user message —
    hoisting keeps that directive authoritative instead of dropping it.
    """
    system_parts: list[str] = []
    turns: list[dict[str, Any]] = []

    for message in messages or []:
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        content = message.get("content")

        if role == "system":
            text = _content_to_text(content).strip()
            if text:
                system_parts.append(text)
            continue

        if role == "tool":
            # An OpenAI tool result is its own message; Anthropic carries
            # it as a tool_result block inside a USER turn.
            turns.append({
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": str(message.get("tool_call_id") or ""),
                    "content": _content_to_text(content) or "{}",
                }],
            })
            continue

        if role == "assistant":
            blocks: list[dict[str, Any]] = []
            text = _content_to_text(content)
            if text.strip():
                blocks.append(_text_block(text))
            blocks.extend(_tool_call_blocks(message.get("tool_calls")))
            # An assistant turn with neither text nor tool calls carries
            # no information and Anthropic rejects an empty block list.
            if blocks:
                turns.append({"role": "assistant", "content": blocks})
            continue

        if role == "user":
            text = _content_to_text(content)
            if text.strip():
                turns.append({"role": "user", "content": [_text_block(text)]})
            continue

    return "\n\n".join(system_parts), _normalize_turns(turns)


def _normalize_turns(turns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Make *turns* satisfy Anthropic's structural rules.

    Three constraints OpenAI does not impose:

      * roles must strictly alternate — consecutive same-role turns are
        merged by concatenating their block lists (this is what happens
        after a multi-tool round: several tool_result user turns in a row)
      * the first turn must be ``user`` — a neutral opener is inserted
        when the history starts with the bot's greeting
      * a trailing assistant turn is read as a prefill and must not end
        with whitespace
    """
    merged: list[dict[str, Any]] = []
    for turn in turns:
        if merged and merged[-1]["role"] == turn["role"]:
            merged[-1]["content"].extend(turn["content"])
        else:
            merged.append({"role": turn["role"], "content": list(turn["content"])})

    if merged and merged[0]["role"] != "user":
        merged.insert(0, {
            "role": "user",
            "content": [_text_block(_CONVERSATION_START_MARKER)],
        })

    if merged and merged[-1]["role"] == "assistant":
        for block in reversed(merged[-1]["content"]):
            if block.get("type") == "text":
                block["text"] = block["text"].rstrip()
                break

    return merged


# ── OpenAI → Anthropic: tools ───────────────────────────────────────────


def translate_tools(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Convert OpenAI function tools to Anthropic tool definitions."""
    translated: list[dict[str, Any]] = []
    for tool in tools or []:
        if not isinstance(tool, dict):
            continue
        function = tool.get("function") if tool.get("type") == "function" else tool
        if not isinstance(function, dict):
            continue
        name = function.get("name")
        if not name:
            continue
        translated.append({
            "name": str(name),
            "description": str(function.get("description") or ""),
            # Anthropic requires an object schema; an omitted/blank
            # ``parameters`` becomes an explicit no-argument schema.
            "input_schema": function.get("parameters")
            or {"type": "object", "properties": {}},
        })
    return translated


def _translate_tool_choice(tool_choice: Any) -> dict[str, Any] | None:
    """Map an OpenAI ``tool_choice`` to Anthropic's shape.

    Returns ``None`` when the default (auto) applies or the value is not
    recognised — sending nothing is always valid.
    """
    if isinstance(tool_choice, dict):
        name = (tool_choice.get("function") or {}).get("name")
        if name:
            return {"type": "tool", "name": str(name)}
        return None
    if tool_choice in {"required", "any"}:
        return {"type": "any"}
    if tool_choice == "none":
        return {"type": "none"}
    return None


# ── Anthropic → OpenAI: response ────────────────────────────────────────


def to_openai_response(payload: dict[str, Any]) -> dict[str, Any]:
    """Reshape an Anthropic Messages response into an OpenAI-style dict.

    The engines read responses through duck-typed accessors that already
    handle dicts, so this is all that is needed for them to run against
    Claude unmodified.
    """
    text_parts: list[str] = []
    tool_calls: list[dict[str, Any]] = []

    for block in payload.get("content") or []:
        if not isinstance(block, dict):
            continue
        kind = block.get("type")
        if kind == "text":
            text_parts.append(str(block.get("text") or ""))
        elif kind == "tool_use":
            tool_calls.append({
                "id": str(block.get("id") or ""),
                "type": "function",
                "function": {
                    "name": str(block.get("name") or ""),
                    # The engines pass this back through ``json.loads``,
                    # so it must be a string here, matching OpenAI.
                    "arguments": json.dumps(
                        block.get("input") or {}, ensure_ascii=False,
                    ),
                },
            })

    stop_reason = payload.get("stop_reason")
    message: dict[str, Any] = {
        "role": "assistant",
        "content": "".join(text_parts) or None,
    }
    if tool_calls:
        message["tool_calls"] = tool_calls

    usage = payload.get("usage") or {}
    return {
        "id": payload.get("id"),
        "model": payload.get("model"),
        "choices": [{
            "index": 0,
            "message": message,
            "finish_reason": "tool_calls" if tool_calls else "stop",
            "anthropic_stop_reason": stop_reason,
        }],
        "usage": {
            "prompt_tokens": usage.get("input_tokens", 0),
            "completion_tokens": usage.get("output_tokens", 0),
        },
    }


# ── Transport ───────────────────────────────────────────────────────────


def _extract_error(response: httpx.Response) -> str:
    """Pull Anthropic's ``error.message`` out of a failed response.

    Falls back to the status code. Never includes request headers, so the
    credential cannot leak into a log line or an exception message.
    """
    try:
        body = response.json()
        message = (body.get("error") or {}).get("message")
        if message:
            return str(message)
    except Exception:  # noqa: BLE001 — any parse failure degrades to status
        pass
    return f"HTTP {response.status_code}"


def _post(
    *,
    messages: list[dict[str, Any]],
    max_tokens: int,
    temperature: float,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: Any = None,
) -> dict[str, Any]:
    """Send one Messages request and return the decoded payload.

    Raises ``RuntimeError`` on any non-2xx or transport failure. Callers
    in :mod:`app.services.openai_service` catch it and either retry or
    fall back to OpenAI.
    """
    token = auth_token()
    if not token:
        raise RuntimeError("Anthropic credential not configured")

    system_prompt, turns = split_messages(messages)
    if not turns:
        raise RuntimeError("Anthropic request has no user turns")

    body: dict[str, Any] = {
        "model": settings.ANTHROPIC_MODEL,
        "max_tokens": max_tokens,
        "system": _apply_billing_attribution(system_prompt, token),
        "messages": turns,
        # Anthropic's range is 0..1; the OpenAI call sites use 0..0.7 but
        # clamp anyway so a future caller cannot 400 the request.
        "temperature": max(0.0, min(1.0, float(temperature))),
    }

    if tools:
        body["tools"] = translate_tools(tools)
        choice = _translate_tool_choice(tool_choice)
        if choice:
            body["tool_choice"] = choice

    try:
        response = httpx.post(
            _API_URL,
            headers=_auth_headers(token),
            json=body,
            timeout=_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as exc:
        raise RuntimeError(f"Anthropic request failed: {exc}") from exc

    if response.status_code < 200 or response.status_code >= 300:
        raise RuntimeError(f"Anthropic API error: {_extract_error(response)}")

    try:
        return response.json()
    except ValueError as exc:
        raise RuntimeError("Anthropic returned a non-JSON body") from exc


# ── Public surface (mirrors openai_service) ─────────────────────────────


def chat_completion(
    *,
    messages: list[dict[str, Any]],
    max_tokens: int,
    temperature: float,
) -> str:
    """Plain text completion. Mirrors ``openai_service._chat_completion``.

    No retry loop here: the OpenAI-side caller already retries three
    times around this call, and nesting retries would only delay its
    fallback.
    """
    payload = _post(
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
    )
    text_parts = [
        str(block.get("text") or "")
        for block in payload.get("content") or []
        if isinstance(block, dict) and block.get("type") == "text"
    ]
    return "".join(text_parts).strip()


def chat_with_tools(
    *,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    tool_choice: str = "auto",
    max_tokens: int = 500,
    temperature: float = 0.7,
) -> dict[str, Any]:
    """Tool-calling turn, returned in OpenAI response shape.

    Mirrors ``openai_service.chat_with_tools`` — same keyword arguments,
    and a return value the engines' accessors read identically.
    """
    payload = _post(
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
        tools=tools,
        tool_choice=tool_choice,
    )
    return to_openai_response(payload)


def test_connection() -> tuple[bool, str]:
    """Minimal live ping. Returns ``(ok, detail)``; never raises.

    The operator-facing equivalent of the reference project's "Test
    connection" button — it proves the credential AND the configured
    model together, which is the pair that actually fails (a setup token
    without billing attribution reaches Haiku but 400s on Sonnet).
    """
    if not is_configured():
        return False, "ANTHROPIC_AUTH_TOKEN is not set"
    try:
        text = chat_completion(
            messages=[
                {"role": "system", "content": "Respond with OK"},
                {"role": "user", "content": "test"},
            ],
            max_tokens=10,
            temperature=0.0,
        )
    except RuntimeError as exc:
        return False, str(exc)
    return True, f"{settings.ANTHROPIC_MODEL} responded: {text[:60]}"


# One-time boot line — mirrors the ``[openai]`` line in openai_service.
# Logs the credential KIND only; never the token, never its length.
logger.info(
    "[anthropic] provider=%s model=%s auth=%s",
    getattr(settings, "LLM_PROVIDER", "openai"),
    getattr(settings, "ANTHROPIC_MODEL", "<unset>"),
    auth_kind(),
)
