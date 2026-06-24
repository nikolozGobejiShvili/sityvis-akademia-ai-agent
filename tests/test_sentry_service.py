"""Sentry / Error Monitoring tests.

Covers the safe-fallback shape required by the Basic Error
Monitoring Patch brief:

  * `app/services/sentry_service` is a pure wrapper. Every public
    function MUST be a no-op when SENTRY_DSN is empty OR
    `sentry-sdk` is not installed.
  * `capture_exception` MUST NOT raise even if the underlying
    `sentry_sdk.capture_exception` raises — monitoring must never
    take down the agent.
  * Config defaults are conservative: DSN empty, environment
    "production", sample rate 0.0.
  * Capture points (`conversation_service.process_message`,
    `parent_tool_executor.execute`, `followup_service` loop) call
    `capture_exception` with privacy-safe context only.
  * Stage in the follow-up Sentry context stays a STRING ("first_24h"
    / "second_3d" / "third_7d"); the brief explicitly forbids
    integer values.

No real Sentry DSN is required. No internet. No `sentry-sdk` install
is required — the suite stays green whether or not it's available.
"""

from __future__ import annotations

import dataclasses
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import app.config as config_module
from app.config import Settings
from app.services import (
    conversation_service,
    followup_service,
    sentry_service,
)


@pytest.fixture(autouse=True)
def _reset_sentry_state(monkeypatch):
    """Make sure each test starts with the wrapper "uninitialised" so
    init-path tests have a clean slate. Also clear the in-memory
    conversation registry so a stale entry from another test file
    (test_redis_persistence seeds a "nope" conversation that
    survives between modules) cannot leak into the follow-up
    capture-point integration tests."""
    monkeypatch.setattr(sentry_service, "_INITIALIZED", False)
    conversation_service.conversations.clear()
    yield
    monkeypatch.setattr(sentry_service, "_INITIALIZED", False)
    conversation_service.conversations.clear()


@pytest.fixture
def fake_sdk(monkeypatch):
    """Pretend `sentry-sdk` is installed and replace it with a
    recording mock. Returns the mock so individual tests can assert
    on the calls."""
    sdk = MagicMock()
    # `push_scope` is a context manager; mock the returned scope so
    # set_extra calls are recordable.
    scope = MagicMock()
    sdk.push_scope.return_value.__enter__.return_value = scope
    sdk.push_scope.return_value.__exit__.return_value = False
    monkeypatch.setattr(sentry_service, "sentry_sdk", sdk)
    monkeypatch.setattr(sentry_service, "_SDK_AVAILABLE", True)
    return SimpleNamespace(sdk=sdk, scope=scope)


@pytest.fixture
def disabled_sdk(monkeypatch):
    """Simulate `sentry-sdk` NOT installed."""
    monkeypatch.setattr(sentry_service, "sentry_sdk", None)
    monkeypatch.setattr(sentry_service, "_SDK_AVAILABLE", False)


# =========================================================================
# PART 1 — config defaults
# =========================================================================


def test_sentry_dsn_default_is_empty():
    s = Settings()
    assert s.SENTRY_DSN == ""


def test_sentry_environment_default_is_production():
    s = Settings()
    assert s.SENTRY_ENVIRONMENT == "production"


def test_sentry_traces_sample_rate_default_is_zero():
    s = Settings()
    assert s.SENTRY_TRACES_SAMPLE_RATE == 0.0


def test_parse_float_safe_invalid_returns_default():
    """A malformed SENTRY_TRACES_SAMPLE_RATE must not crash boot."""
    # Empty string → default
    assert config_module._parse_float_safe("DOES_NOT_EXIST", 0.0) == 0.0


# =========================================================================
# PART 2 — init_sentry
# =========================================================================


def test_init_sentry_noop_when_dsn_empty(fake_sdk):
    sentry_service.init_sentry(dsn="", environment="production")
    fake_sdk.sdk.init.assert_not_called()
    assert sentry_service._INITIALIZED is False


def test_init_sentry_noop_when_sdk_unavailable(disabled_sdk):
    sentry_service.init_sentry(dsn="https://example.ingest.sentry.io/1")
    # No crash, no init. Cannot assert on the missing SDK directly;
    # the flag is the canonical signal.
    assert sentry_service._INITIALIZED is False


def test_init_sentry_with_dsn_calls_sdk_init(fake_sdk):
    sentry_service.init_sentry(
        dsn="https://abc@example.ingest.sentry.io/1",
        environment="qa",
        traces_sample_rate=0.5,
    )
    assert fake_sdk.sdk.init.called
    kwargs = fake_sdk.sdk.init.call_args.kwargs
    assert kwargs["dsn"] == "https://abc@example.ingest.sentry.io/1"
    assert kwargs["environment"] == "qa"
    assert kwargs["traces_sample_rate"] == 0.5
    # Privacy: PII must be hard-off.
    assert kwargs["send_default_pii"] is False
    assert kwargs["attach_stacktrace"] is True
    assert sentry_service._INITIALIZED is True


def test_init_sentry_clamps_out_of_range_sample_rate(fake_sdk):
    sentry_service.init_sentry(dsn="https://x@y/1", traces_sample_rate=2.5)
    rate = fake_sdk.sdk.init.call_args.kwargs["traces_sample_rate"]
    assert rate == 1.0


def test_init_sentry_clamps_negative_sample_rate(fake_sdk):
    sentry_service.init_sentry(dsn="https://x@y/1", traces_sample_rate=-1.0)
    rate = fake_sdk.sdk.init.call_args.kwargs["traces_sample_rate"]
    assert rate == 0.0


def test_init_sentry_second_call_is_idempotent(fake_sdk):
    sentry_service.init_sentry(dsn="https://x@y/1")
    sentry_service.init_sentry(dsn="https://x@y/1")
    assert fake_sdk.sdk.init.call_count == 1


def test_init_sentry_does_not_raise_when_sdk_init_fails(fake_sdk):
    """Network unreachable / bad DSN format / etc. must not bring
    down boot."""
    fake_sdk.sdk.init.side_effect = RuntimeError("boom")
    # Should not raise.
    sentry_service.init_sentry(dsn="https://x@y/1")
    assert sentry_service._INITIALIZED is False


# =========================================================================
# PART 3 — capture_exception
# =========================================================================


def test_capture_exception_noop_when_disabled(fake_sdk):
    # SDK available but init never ran.
    sentry_service.capture_exception(RuntimeError("nope"))
    fake_sdk.sdk.capture_exception.assert_not_called()


def test_capture_exception_noop_when_sdk_missing(disabled_sdk):
    # MUST NOT raise.
    sentry_service.capture_exception(RuntimeError("nope"))


def test_capture_exception_with_context_uses_push_scope(fake_sdk):
    sentry_service.init_sentry(dsn="https://x@y/1")
    fake_sdk.sdk.reset_mock()
    fake_sdk.scope.reset_mock()
    sentry_service.capture_exception(
        RuntimeError("kaboom"),
        context={"area": "conversation_service", "platform": "instagram"},
    )
    assert fake_sdk.sdk.push_scope.called
    assert fake_sdk.scope.set_extra.call_count == 2
    fake_sdk.sdk.capture_exception.assert_called_once()


def test_capture_exception_without_context_skips_push_scope(fake_sdk):
    sentry_service.init_sentry(dsn="https://x@y/1")
    fake_sdk.sdk.reset_mock()
    sentry_service.capture_exception(RuntimeError("kaboom"))
    fake_sdk.sdk.push_scope.assert_not_called()
    fake_sdk.sdk.capture_exception.assert_called_once()


def test_capture_exception_never_raises_when_sentry_internals_fail(fake_sdk):
    """Hard requirement: monitoring must never break runtime."""
    sentry_service.init_sentry(dsn="https://x@y/1")
    fake_sdk.sdk.capture_exception.side_effect = RuntimeError("sentry crashed")
    # MUST NOT raise.
    sentry_service.capture_exception(RuntimeError("user-visible"))


# =========================================================================
# PART 4 — capture_message + set_tag no-ops
# =========================================================================


def test_capture_message_noop_when_disabled(fake_sdk):
    sentry_service.capture_message("hello")
    fake_sdk.sdk.capture_message.assert_not_called()


def test_capture_message_noop_when_sdk_missing(disabled_sdk):
    sentry_service.capture_message("hello")  # must not raise


def test_capture_message_calls_sdk_when_active(fake_sdk):
    sentry_service.init_sentry(dsn="https://x@y/1")
    sentry_service.capture_message("hi", level="warning")
    fake_sdk.sdk.capture_message.assert_called_once_with(
        "hi", level="warning",
    )


def test_set_tag_noop_when_disabled(fake_sdk):
    sentry_service.set_tag("env", "qa")
    fake_sdk.sdk.set_tag.assert_not_called()


def test_set_tag_noop_when_sdk_missing(disabled_sdk):
    sentry_service.set_tag("env", "qa")  # must not raise


def test_set_tag_calls_sdk_when_active(fake_sdk):
    sentry_service.init_sentry(dsn="https://x@y/1")
    sentry_service.set_tag("env", "qa")
    fake_sdk.sdk.set_tag.assert_called_once_with("env", "qa")


# =========================================================================
# PART 5 — mask_sender helper
# =========================================================================


def test_mask_sender_full_id_keeps_first_6():
    assert sentry_service.mask_sender("123456789012345") == "123456***"


def test_mask_sender_short_id_still_masks():
    assert sentry_service.mask_sender("abc") == "abc***"


def test_mask_sender_empty_returns_empty():
    assert sentry_service.mask_sender("") == ""
    assert sentry_service.mask_sender(None) == ""  # type: ignore[arg-type]


# =========================================================================
# PART 6 — Capture point integration
# =========================================================================


def test_conversation_service_exception_path_calls_capture(monkeypatch, fake_sdk):
    """When `_process_message_impl` raises, the wrapper MUST call
    `sentry_service.capture_exception` with privacy-safe context
    BEFORE re-raising."""
    sentry_service.init_sentry(dsn="https://x@y/1")

    def boom(*_a, **_k):
        raise RuntimeError("internal error")

    monkeypatch.setattr(conversation_service, "_process_message_impl", boom)
    captured: list[dict] = []

    def fake_capture(exc, context=None):
        captured.append({"exc_type": type(exc).__name__, "context": context})

    monkeypatch.setattr(sentry_service, "capture_exception", fake_capture)
    monkeypatch.setattr(conversation_service, "sentry_service", sentry_service)

    with pytest.raises(RuntimeError):
        conversation_service.process_message(
            sender_id="psid_1234567890",
            message_text="გამარჯობა",
            platform="instagram",
        )

    assert len(captured) == 1
    ctx = captured[0]["context"]
    assert ctx["area"] == "conversation_service"
    assert ctx["platform"] == "instagram"
    # Mask shape: first 6 chars + "***", no full sender id.
    assert ctx["sender"] == "psid_1***"
    assert "psid_1234567890" not in str(ctx)


def test_conversation_service_capture_does_not_leak_message_body(monkeypatch):
    """Privacy: the user's raw message must NEVER appear in the
    Sentry context."""
    sentry_service.init_sentry(dsn="https://x@y/1")
    monkeypatch.setattr(
        conversation_service, "_process_message_impl",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("x")),
    )
    captured: list[dict] = []

    def fake_capture(exc, context=None):
        captured.append({"context": context})

    monkeypatch.setattr(sentry_service, "capture_exception", fake_capture)
    monkeypatch.setattr(conversation_service, "sentry_service", sentry_service)

    secret = "MY_PHONE_IS_595999733"
    with pytest.raises(RuntimeError):
        conversation_service.process_message(
            sender_id="u1", message_text=secret, platform="instagram",
        )
    serialised = str(captured[0]["context"])
    assert secret not in serialised
    assert "595999733" not in serialised


def test_parent_tool_executor_exception_calls_capture(monkeypatch):
    """When a tool raises inside the executor's try block, the
    capture is dispatched with tool name only — no args (which could
    contain phone / name)."""
    sentry_service.init_sentry(dsn="https://x@y/1")
    from app.agent.tools import parent_tool_executor as pte
    from app.models.conversation import Conversation
    from app.models.lead import Lead

    captured: list[dict] = []

    def fake_capture(exc, context=None):
        captured.append({"exc_type": type(exc).__name__, "context": context})

    monkeypatch.setattr(sentry_service, "capture_exception", fake_capture)
    monkeypatch.setattr(pte, "sentry_service", sentry_service)

    # Make _get_camp_info raise on the executor's first dispatch
    # path. The executor catches it in the existing except block we
    # just augmented.
    def boom(self, args):
        raise RuntimeError("camp facts broken")

    monkeypatch.setattr(pte.ParentToolExecutor, "_get_camp_info", boom)
    conv = Conversation(sender_id="u1", platform="instagram")
    lead = Lead(sender_id="u1", platform="instagram", segment="PARENT")
    conv.lead = lead
    executor = pte.ParentToolExecutor(
        conversation=conv, lead=lead, sender_id="u1", platform="instagram",
    )

    result = executor.execute("get_camp_info", {"topic": "price"})
    # Existing contract preserved: failure surfaces as
    # success=false / reason=tool_error.
    assert result == {"success": False, "reason": "tool_error", "tool": "get_camp_info"}
    assert len(captured) == 1
    ctx = captured[0]["context"]
    assert ctx == {"area": "parent_tool_executor", "tool": "get_camp_info"}
    # No phone / args leaked.
    assert "args" not in ctx


def test_followup_service_exception_calls_capture_with_string_stage(monkeypatch):
    """When `_maybe_send_followup_for_conversation` raises for a
    conversation, the loop catches it and calls capture_exception
    with `stage` as a STRING (never an integer)."""
    sentry_service.init_sentry(dsn="https://x@y/1")
    from app.models.conversation import Conversation
    from app.models.lead import Lead

    captured: list[dict] = []

    def fake_capture(exc, context=None):
        captured.append({"context": context})

    monkeypatch.setattr(sentry_service, "capture_exception", fake_capture)
    monkeypatch.setattr(followup_service, "sentry_service", sentry_service)

    # Force the per-conversation worker to raise.
    def boom(_conv, _now):
        raise RuntimeError("inner")

    monkeypatch.setattr(
        followup_service, "_maybe_send_followup_for_conversation", boom,
    )

    conv = Conversation(sender_id="psid_abcdef12345", platform="instagram")
    conv.segment = "PARENT"
    conv.followup_stage = "first_24h"
    lead = Lead(sender_id="psid_abcdef12345", platform="instagram", segment="PARENT")
    conv.lead = lead
    conversation_service.conversations[conv.sender_id] = conv

    try:
        followup_service.check_and_send_followups()
    finally:
        conversation_service.conversations.clear()

    assert len(captured) == 1
    ctx = captured[0]["context"]
    assert ctx["area"] == "followup_service"
    # Hard requirement: stage is a STRING matching followup_strategy.yaml.
    assert ctx["stage"] == "first_24h"
    assert isinstance(ctx["stage"], str)
    assert ctx["platform"] == "instagram"
    # Masked sender, not the full PSID.
    assert ctx["sender"] == "psid_a***"
    assert "psid_abcdef12345" not in str(ctx)


def test_followup_service_stage_context_is_never_integer(monkeypatch):
    """Defensive: even with an unusual stage value, the Sentry
    context preserves the existing string architecture — never
    coerces to int."""
    sentry_service.init_sentry(dsn="https://x@y/1")
    from app.models.conversation import Conversation
    from app.models.lead import Lead

    captured: list[dict] = []
    monkeypatch.setattr(
        sentry_service, "capture_exception",
        lambda exc, context=None: captured.append({"ctx": context}),
    )
    monkeypatch.setattr(followup_service, "sentry_service", sentry_service)
    monkeypatch.setattr(
        followup_service, "_maybe_send_followup_for_conversation",
        lambda _c, _n: (_ for _ in ()).throw(RuntimeError("x")),
    )
    conv = Conversation(sender_id="u1", platform="instagram")
    conv.segment = "PARENT"
    conv.followup_stage = "second_3d"
    conv.lead = Lead(sender_id="u1", platform="instagram", segment="PARENT")
    conversation_service.conversations[conv.sender_id] = conv

    try:
        followup_service.check_and_send_followups()
    finally:
        conversation_service.conversations.clear()

    assert captured[0]["ctx"]["stage"] == "second_3d"
    # The brief explicitly forbids 0/1/2/3.
    assert captured[0]["ctx"]["stage"] not in {0, 1, 2, 3}
