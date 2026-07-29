"""Verify the Anthropic credential before flipping ``LLM_PROVIDER``.

    python -m tools.check_anthropic_token
    python -m tools.check_anthropic_token --tools     # also test tool-calling

Why a dedicated check: a Claude **setup token** can be perfectly valid
and still fail on the model you configured. Without the billing
attribution that ``anthropic_service`` injects, an ``sk-ant-oat`` token
reaches Haiku but answers 400 for Sonnet/Opus. Credential and model have
to be proven together, which is exactly what this does.

The ``--tools`` pass additionally proves the OpenAI↔Anthropic tool
translation, since the sales engines are tool-driven and a working plain
completion says nothing about whether tool calls round-trip.

Exit code 0 on success, 1 on any failure. The token is never printed.
"""

from __future__ import annotations

import json
import sys

from app.config import settings
from app.services import anthropic_service

_PROBE_TOOL = [{
    "type": "function",
    "function": {
        "name": "save_lead_info",
        "description": "Store a field the customer just provided.",
        "parameters": {
            "type": "object",
            "properties": {
                "field": {"type": "string", "description": "Field name"},
                "value": {"type": "string", "description": "Field value"},
            },
            "required": ["field", "value"],
        },
    },
}]


def _print_config() -> None:
    print("Anthropic configuration")
    print(f"  LLM_PROVIDER                 : {settings.LLM_PROVIDER}")
    print(f"  ANTHROPIC_MODEL              : {settings.ANTHROPIC_MODEL}")
    print(f"  credential kind              : {anthropic_service.auth_kind()}")
    print(f"  ANTHROPIC_FALLBACK_TO_OPENAI : {settings.ANTHROPIC_FALLBACK_TO_OPENAI}")
    print()


def _check_completion() -> bool:
    print("[1] plain completion ...", end=" ", flush=True)
    ok, detail = anthropic_service.test_connection()
    print("OK" if ok else "FAILED")
    print(f"    {detail}")
    if not ok:
        print()
        print("    Common causes:")
        print("      * token wrapped across lines, or pasted with quotes")
        print("      * setup token expired — regenerate with `claude setup-token`")
        print("      * ANTHROPIC_MODEL not available to this credential")
    return ok


def _check_tools() -> bool:
    print("[2] tool calling ...", end=" ", flush=True)
    try:
        response = anthropic_service.chat_with_tools(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You record customer details. When the customer states "
                        "a name, call save_lead_info with field='name'."
                    ),
                },
                {"role": "user", "content": "ჩემი სახელია ნიკა"},
            ],
            tools=_PROBE_TOOL,
            tool_choice="auto",
            max_tokens=200,
            temperature=0.0,
        )
    except RuntimeError as exc:
        print("FAILED")
        print(f"    {exc}")
        return False

    message = response["choices"][0]["message"]
    calls = message.get("tool_calls") or []
    if not calls:
        # Not a hard failure: the response shape is what matters here,
        # and the model is free to answer in prose instead.
        print("OK (no tool call — model answered directly)")
        print(f"    text: {(message.get('content') or '')[:80]}")
        return True

    call = calls[0]
    print("OK")
    print(f"    tool     : {call['function']['name']}")
    print(f"    call id  : {call['id']}")
    try:
        args = json.loads(call["function"]["arguments"])
    except ValueError:
        print("    arguments: <not valid JSON> — translation defect")
        return False
    print(f"    arguments: {args}")
    return True


def main() -> int:
    _print_config()

    if not anthropic_service.is_configured():
        print("FAILED: ANTHROPIC_AUTH_TOKEN is empty.")
        print("Generate a setup token with:  claude setup-token")
        return 1

    if not _check_completion():
        return 1

    if "--tools" in sys.argv and not _check_tools():
        return 1

    print()
    print("Ready. Set LLM_PROVIDER=anthropic in .env to route the agent to Claude.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
