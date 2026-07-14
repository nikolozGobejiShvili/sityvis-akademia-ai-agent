"""Shared pytest fixtures + safe defaults for the test suite.

P3-C PATCH 1: when `.env` flips ``USE_PARENT_LLM_ENGINE=true`` for a
live smoke test, the legacy P0/P1/P2 tests that drive
``conversation_service.process_message`` directly would route through
the new LLM engine and hit the live OpenAI API. That breaks them in a
way unrelated to what they're testing (state-machine + analyzer
behaviour).

This autouse fixture pins ``parent_flow.settings.USE_PARENT_LLM_ENGINE``
to ``False`` for every test by default. Tests that DO want the engine
on (``test_parent_llm_engine.py``) layer their own monkeypatch on top —
pytest's ``monkeypatch`` is LIFO, so the engine fixture wins inside its
own tests, and the autouse default wins everywhere else.

The autouse fixture replaces only the ``parent_flow.settings`` module
reference (which is what ``parent_flow.handle`` consults). The global
``app.config.settings`` instance is untouched, so other modules that
read it directly (e.g. ``app.main`` boot logging) continue to reflect
the real ``.env``.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

import app.config as config_module
from app.flows import adult_flow, parent_flow
from app.services import redis_state_service


@pytest.fixture
def camp_registration_open(monkeypatch):
    """Opt-in fixture for legacy/open-registration tests.

    The real test config is intentionally closed for Release Checkpoint #1.
    Tests that exercise historical registration, booking, or follow-up flows
    must request this fixture explicitly.
    """
    from app.services import admin_config_service

    monkeypatch.setattr(
        admin_config_service, "get_camp_registration_status", lambda: "open",
    )
    monkeypatch.setattr(
        admin_config_service, "is_camp_registration_open", lambda: True,
    )
    yield


_CAMP_REGISTRATION_DEFAULT_OPEN_EXCLUDED_FILES = {
    "test_admin_config.py",
    "test_camp_info_vs_registration_2026_06_20.py",
    "test_camp_registration_closed_2026_07_13.py",
    "test_camp_stream_and_price_asabove_2026_07_07.py",
    "test_closed_camp_live_qa_hotfix_2026_07_14.py",
    "test_comment_flow.py",
    "test_final_camp_public_policy_2026_07_14.py",
    "test_first_turn_intent_no_menu_2026_07_08.py",
    "test_legacy_sunday_school_and_duplicate_age_guard_2026_06_27.py",
    "test_live_camp_registration_link_2026_06_19.py",
    "test_source_of_truth_guard_2026_07_10.py",
}


@pytest.fixture(autouse=True)
def _default_camp_registration_open_for_legacy_tests(request, monkeypatch):
    """Default legacy tests to pre-closure registration behavior.

    Release Checkpoint #1 intentionally keeps the real test config closed.
    Most older tests predate that lifecycle state and assert historical open
    registration, booking, and sales flows. Keep the new closed-policy tests
    and config/source-of-truth guards on the real or explicitly patched state.
    """
    test_file = Path(str(request.node.fspath)).name
    if test_file in _CAMP_REGISTRATION_DEFAULT_OPEN_EXCLUDED_FILES:
        yield
        return

    from app.services import admin_config_service

    monkeypatch.setattr(
        admin_config_service,
        "get_camp_registration_status",
        lambda: "open",
    )
    monkeypatch.setattr(
        admin_config_service,
        "is_camp_registration_open",
        lambda: True,
    )
    yield


@pytest.fixture
def adult_events_june_2026_clock(monkeypatch):
    """Opt-in clock for legacy adult-event tests seeded with June 2026 dates."""
    from app.services import admin_config_service

    monkeypatch.setattr(
        admin_config_service,
        "_now_tbilisi",
        lambda: (
            datetime(2026, 6, 1, 12, 0, tzinfo=ZoneInfo("Asia/Tbilisi")),
            ZoneInfo("Asia/Tbilisi"),
        ),
    )
    yield


@pytest.fixture
def camp_streams_visible(monkeypatch):
    """Opt-in clock for legacy camp rich-DM tests that expect visible streams."""
    from app.services import admin_config_service

    monkeypatch.setattr(
        admin_config_service,
        "_now_tbilisi",
        lambda: (
            datetime(2026, 7, 13, 12, 0, tzinfo=ZoneInfo("Asia/Tbilisi")),
            ZoneInfo("Asia/Tbilisi"),
        ),
    )
    yield


@pytest.fixture(autouse=True)
def _force_adult_llm_engine_off(monkeypatch):
    """Default to USE_ADULT_LLM_ENGINE=False for every test.

    Mirrors the parent-engine pattern below. The ADULT LLM engine default
    is ON (live setting), but the legacy ADULT state-machine tests
    (PATCH 7 global intent guard, SHOW_EVENTS / ANSWER_QUESTIONS, etc.)
    drive ``adult_flow.handle`` directly and expect the deterministic
    state machine. Pinning the flag off keeps those tests behaviour-
    identical to pre-engine baseline. The engine-specific test file
    (``test_adult_llm_engine.py``) overrides with its own
    ``enable_adult_engine`` fixture which sits on top of the same
    monkeypatch stack.
    """
    swapped = dataclasses.replace(
        config_module.settings, USE_ADULT_LLM_ENGINE=False,
    )
    monkeypatch.setattr(adult_flow, "settings", swapped)
    yield


@pytest.fixture(autouse=True)
def _force_parent_llm_engine_off(monkeypatch):
    """Default to USE_PARENT_LLM_ENGINE=False for every test.

    Tests that need the engine ON (``test_parent_llm_engine.py``) use
    their own ``enable_engine`` fixture which overrides this on top of
    the same monkeypatch stack.

    Also pins ``USE_REASONING_LAYER=False`` (Reasoning Layer Phase 1,
    2026-06-23) so the gated deterministic analyzer is never consulted by
    default and behaviour stays byte-identical. The reasoning-layer test
    file enables it with its own fixture on top of this monkeypatch stack.
    """
    swapped = dataclasses.replace(
        config_module.settings,
        USE_PARENT_LLM_ENGINE=False,
        USE_REASONING_LAYER=False,
        USE_CONVERSATION_PLANNER=False,
        CONVERSATION_PLANNER_AUTHORITATIVE=False,
        CONVERSATION_TRACE_DEBUG=False,
        USE_SLIM_PROMPTS=False,
    )
    # Pin the config singleton too, so tests that rebuild settings from
    # `config_module.settings` (rather than the already-pinned module copies) do
    # NOT inherit whatever the operator set in `.env` (e.g. a live
    # CONVERSATION_PLANNER_AUTHORITATIVE=true). Test isolation only.
    monkeypatch.setattr(config_module, "settings", swapped)
    monkeypatch.setattr(parent_flow, "settings", swapped)
    # conversation_service holds its OWN `from app.config import settings`
    # binding (the original object built from the live `.env`, which has the
    # planner authoritative). The Phase-3 topic-routing / writeback logic reads
    # those flags, so pin its copy OFF too — otherwise every legacy
    # process_message test would inherit live planner routing. The engines
    # (parent/adult) read USE_SLIM_PROMPTS, so pin theirs as well. Tests that
    # exercise the planner/slim path override these with their own monkeypatch
    # on top of this (LIFO) stack.
    from app.services import conversation_service as _cs
    from app.agent.llm import parent_llm_engine as _ple
    from app.agent.llm import adult_llm_engine as _ale
    monkeypatch.setattr(_cs, "settings", swapped)
    monkeypatch.setattr(_ple, "settings", swapped)
    monkeypatch.setattr(_ale, "settings", swapped)
    # Client ❤️ emoji policy (2026-06-28) defaults ON for live; pin it OFF for
    # every test so the existing greeting/booking/thanks assertions stay
    # byte-identical. The emoji test file opts back in on top of this stack.
    monkeypatch.setattr(parent_flow, "_CLIENT_EMOJI_ENABLED", False, raising=False)
    yield


@pytest.fixture(autouse=True)
def _force_followup_production_cadence(monkeypatch):
    """Follow-up Test Mode Patch (2026-06-06) — default to production
    cadence for every test.

    The live ``.env`` keeps `FOLLOWUP_TEST_MODE=true` +
    `FOLLOWUP_FIRST_DELAY_SECONDS=120` so an operator can live-test the
    scheduler in two minutes. Without this fixture every legacy
    follow-up test that fires a 23-hour-elapsed conversation would
    suddenly trip the 120-second override and start sending. Tests
    that DO want the override (this patch's own test file) layer their
    own monkeypatch on top — pytest's monkeypatch is LIFO, so the
    explicit override wins inside those tests.
    """
    from app.services import followup_service as _followup_service
    swapped = dataclasses.replace(
        _followup_service.settings,
        FOLLOWUP_ENABLED=True,
        FOLLOWUP_TEST_MODE=False,
        FOLLOWUP_FIRST_DELAY_SECONDS=0,
    )
    monkeypatch.setattr(_followup_service, "settings", swapped)
    yield


@pytest.fixture(autouse=True)
def _force_redis_disabled(monkeypatch):
    """P3-B — default to Redis disabled for the WHOLE test suite.

    The user's `.env` may point REDIS_URL at a real local Redis
    instance (for live QA). If we let that bleed into pytest, tests
    pick up stale keys from prior runs — `processed_comment:*` causes
    the comment flow to short-circuit, `manager_notified:*` skips
    notifications, etc.

    Tests that DO want Redis active (`test_redis_persistence.py`)
    inject their own FakeRedis fixture which overrides this on top of
    the same monkeypatch stack; the lifo ordering means the local
    fixture wins inside those tests and the autouse default wins
    everywhere else.
    """
    monkeypatch.setattr(redis_state_service, "_client", None)
    monkeypatch.setattr(redis_state_service, "_connection_attempted", True)
    monkeypatch.setattr(redis_state_service, "_connection_ok", False)
    swapped = dataclasses.replace(
        redis_state_service.settings,
        REDIS_URL="",
        REDIS_ENABLED=False,
    )
    monkeypatch.setattr(redis_state_service, "settings", swapped)
    yield


@pytest.fixture(autouse=True)
def _block_real_smtp(monkeypatch):
    """Hard safety net: no test may ever open a REAL SMTP connection.

    `.env` carries live SMTP credentials, so any code path that reaches
    `notification_service._send_email` (e.g. the under-age manager-handoff
    dispatch, Live P0/P1 Hotfix 2026-06-15) would otherwise send a real
    email. This stubs `smtplib.SMTP` with an inert no-op context manager so
    the gate logic still runs but the network send never happens. Tests that
    install their own `smtplib.SMTP` fake (test_notification_service.py) win
    via pytest's LIFO monkeypatch ordering.
    """
    import smtplib

    class _InertSMTP:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self, *a, **k):
            return None

        def login(self, *a, **k):
            return None

        def send_message(self, *a, **k):
            return None

    monkeypatch.setattr(smtplib, "SMTP", _InertSMTP)
    yield


@pytest.fixture(autouse=True)
def _block_real_meta_http(monkeypatch):
    """Hard safety net: no test may make a REAL outbound Meta / WhatsApp
    HTTP call.

    Manager WhatsApp Notification Fix (2026-06-18): once the operator puts
    live WhatsApp Cloud API credentials in `.env`,
    `settings.is_whatsapp_configured()` becomes True, so
    `notification_service._send_manager_whatsapp` (and the
    `messenger_service.send_message` WhatsApp branch) would otherwise reach
    `httpx.post(graph.facebook.com)` for real on any unmocked booking /
    handoff path. This stubs the MODULE-LEVEL `httpx.post` / `httpx.get`
    (the only form our Meta/WhatsApp code uses) so the real network is
    never touched; every caller already wraps the call in try/except and
    degrades to a clean "not sent" result.

    It does NOT touch `httpx.Client(...)` instance methods, so SDKs that
    use a client instance internally (e.g. the OpenAI SDK) are unaffected.
    Tests that assert HTTP behaviour install their own `httpx.post` mock,
    which wins via pytest's LIFO monkeypatch ordering.
    """
    import httpx

    def _blocked(*args, **kwargs):
        raise RuntimeError(
            "[test] real outbound HTTP blocked by _block_real_meta_http",
        )

    monkeypatch.setattr(httpx, "post", _blocked)
    monkeypatch.setattr(httpx, "get", _blocked)
    yield


@pytest.fixture(autouse=True)
def _block_live_whatsapp(monkeypatch):
    """Pin ``ALLOW_LIVE_WHATSAPP=False`` for every test so the manager-WhatsApp
    live-send guard blocks the Meta POST at the source (belt-and-braces with
    ``_block_real_meta_http``). Even if a test installs its own ``httpx.post``,
    ``_send_manager_whatsapp`` returns a safe failure before reaching it unless
    the test explicitly re-enables the flag."""
    import dataclasses

    from app.services import notification_service

    monkeypatch.setattr(
        notification_service,
        "settings",
        dataclasses.replace(
            notification_service.settings, ALLOW_LIVE_WHATSAPP=False,
        ),
    )
    yield
