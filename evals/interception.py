"""Layer A — interception-rate instrument (Phase 1, Task 1).

FREE, deterministic, READ-ONLY diagnostic that measures what fraction of
PARENT turns are short-circuited by a deterministic ``_maybe_*`` interceptor
in ``app/flows/parent_flow.py`` BEFORE the LLM engine, vs. actually reaching
``app.agent.llm.parent_llm_engine.run_parent_llm_turn``. This is an
architectural-balance DIAGNOSTIC (how much of the agent's behaviour is
hand-written Python vs. LLM reasoning) — it is NOT an agent behaviour change.
Nothing in ``app/`` is touched by this module, and nothing outside the eval
harness / tests imports it.

Mechanism
---------
1. READ-ONLY guard reuse — every external side effect (Calendar / Sheets /
   manager notifications / outbound DM / SMTP / raw httpx) is stubbed via the
   SAME guard the rest of the harness uses: ``evals.safety.install_readonly``.
2. Trace-debug reuse — ``CONVERSATION_TRACE_DEBUG`` is switched on the same
   way ``evals.simulation`` already does it for its handler-identity scoring
   (same modules, same ``dataclasses.replace`` pattern), so
   ``app.reasoning.conversation_trace.history()`` is readable after the turn.
3. Engine spy (the RELIABLE signal) — ``parent_llm_engine.run_parent_llm_turn``
   is monkeypatched with a spy that records whether it was CALLED and returns
   a canned string (never touches OpenAI). A direct probe of the real code
   confirmed the CAVEAT the task brief warned about: most of the ~40
   ``_maybe_*`` pre-engine interceptors in ``parent_flow._handle_core`` return
   text WITHOUT ever calling ``conversation_trace.set(answered_by=...)``, so
   the trace is SILENT for them (`answered_by` / `handler` are both absent).
   Whether the spy was called is unambiguous: ``parent_flow._run_llm_engine_safely``
   does ``from app.agent.llm.parent_llm_engine import run_parent_llm_turn``
   freshly on every call, so patching the module attribute is picked up on
   every turn without needing to touch ``app/``.
4. Handler naming — when the spy was NOT called, the trace's ``answered_by``
   (falling back to ``handler``) names the deterministic path on the turns
   where the app happens to record one (e.g.
   ``response_policy.subscription_confirm``); otherwise the generic label
   ``"interceptor"`` is used (the CAVEAT case above).

Isolation
---------
``evals.safety.install_readonly`` and the trace-debug enabler both use raw
``setattr`` (not pytest's auto-restoring ``monkeypatch``), so leaving them
installed permanently would leak stubbed Calendar/Sheets/notification
functions — and a forced ``USE_PARENT_LLM_ENGINE=True`` /
``CONVERSATION_TRACE_DEBUG=True`` — into every OTHER test that runs later in
the same process. This module therefore snapshots every attribute it (and the
guard) is about to touch, drives exactly ONE turn, and restores everything in
a ``finally`` before returning — regardless of whether the guard was needed by
the current pytest context or not.
"""
from __future__ import annotations

import dataclasses
import importlib
from typing import Any

from evals import safety

_ENGINE_MODULE = "app.agent.llm.parent_llm_engine"
_ENGINE_ATTR = "run_parent_llm_turn"

# Review fix #1 (READ-ONLY, ANY segment): the PARENT engine is the reliable
# reached_llm signal, but a non-PARENT conversation routes to the ADULT engine,
# which would make a REAL OpenAI call. Spy BOTH so `answered_by` never sends a
# live request regardless of the conversation's segment. Only the PARENT spy
# increments engine_calls (the reached_llm signal is PARENT-scoped by design).
_ADULT_ENGINE_MODULE = "app.agent.llm.adult_llm_engine"
_ADULT_ENGINE_ATTR = "run_adult_llm_turn"

# Mirrors the `patches` dict inside `evals/safety.py::install_readonly` — kept
# here ONLY so the snapshot/restore machinery below knows which attributes to
# put back after driving one turn. If `evals/safety.py` changes what it
# stubs, update this list to match (a residual stub left behind is harmless —
# it is the same read-only dry-run stub the rest of the harness already
# relies on — but keeping this in sync avoids any drift).
_SERVICE_PATCH_TARGETS: tuple[tuple[str, str], ...] = (
    ("app.services.messenger_service", "send_message"),
    ("app.services.messenger_service", "send_private_reply"),
    ("app.services.messenger_service", "get_user_profile"),
    ("app.services.calendar_service", "book_slot"),
    ("app.services.calendar_service", "create_event"),
    ("app.services.calendar_service", "cancel_calendar_event"),
    ("app.services.sheets_service", "create_lead"),
    ("app.services.sheets_service", "update_lead"),
    ("app.services.sheets_service", "save_lead"),
    ("app.services.sheets_service", "save_comment"),
    ("app.services.sheets_service", "log_sunday_school_lead"),
    ("app.services.sheets_service", "save_event_subscriber"),
    ("app.services.sheets_service", "mark_old_booking_rescheduled"),
    ("app.services.notification_service", "notify_manager"),
    ("app.services.notification_service", "send_manager_notification"),
    ("app.services.notification_service", "notify_manager_handoff"),
    ("app.services.notification_service", "notify_sunday_school_handoff"),
    ("app.services.notification_service", "_send_email"),
    ("app.services.notification_service", "_send_whatsapp"),
)

_REDIS_ATTRS: tuple[str, ...] = ("_client", "_connection_attempted", "_connection_ok")


def _resolve(module_name: str) -> Any | None:
    try:
        return importlib.import_module(module_name)
    except Exception:  # pragma: no cover - defensive
        return None


def _snapshot(pairs: list[tuple[str, str]]) -> list[tuple[Any, str, bool, Any]]:
    """Return ``[(module, attr, had_attr, old_value), ...]`` for later restore."""
    saved: list[tuple[Any, str, bool, Any]] = []
    for module_name, attr in pairs:
        mod = _resolve(module_name)
        if mod is None:
            continue
        had = hasattr(mod, attr)
        saved.append((mod, attr, had, getattr(mod, attr, None)))
    return saved


def _restore(saved: list[tuple[Any, str, bool, Any]]) -> None:
    for obj, attr, had, old in saved:
        try:
            if had:
                setattr(obj, attr, old)
            else:
                delattr(obj, attr)
        except Exception:  # pragma: no cover - restore must never raise
            pass


class _GuardedTurn:
    """Install the READ-ONLY guard + trace-debug + engine spy for ONE turn,
    record whether the engine was invoked, then restore every touched
    attribute so nothing leaks into other callers / later tests."""

    def __init__(self) -> None:
        self.engine_calls = 0
        self._saved: list[tuple[Any, str, bool, Any]] = []

    def __enter__(self) -> "_GuardedTurn":
        settings_targets = [
            (m, "settings") for m in tuple(safety._SETTINGS_MODULES) + ("app.config",)
        ]
        redis_targets = [
            ("app.services.redis_state_service", a) for a in _REDIS_ATTRS
        ]
        smtplib_targets = [("smtplib", "SMTP"), ("smtplib", "SMTP_SSL")]
        httpx_targets = [("httpx", "post"), ("httpx", "get")]
        engine_targets = [
            (_ENGINE_MODULE, _ENGINE_ATTR),
            (_ADULT_ENGINE_MODULE, _ADULT_ENGINE_ATTR),
        ]

        self._saved = _snapshot(
            settings_targets + redis_targets + list(_SERVICE_PATCH_TARGETS)
            + smtplib_targets + httpx_targets + engine_targets,
        )
        try:
            log = safety.SideEffectLog()
            safety.install_readonly(log, block_httpx=True)
            self._enable_trace_debug()
            self._install_engine_spy()
        except Exception:
            _restore(self._saved)
            raise
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        _restore(self._saved)
        return False

    def _enable_trace_debug(self) -> None:
        # Reuses the EXACT mechanism `evals/simulation.py::_enable_trace_debug`
        # already uses to make `conversation_trace` readable during a
        # harness-driven turn (same modules, same swap pattern).
        from app import config as cfg
        swapped = dataclasses.replace(cfg.settings, CONVERSATION_TRACE_DEBUG=True)
        for name in tuple(safety._SETTINGS_MODULES) + ("app.config",):
            mod = _resolve(name)
            if mod is not None and hasattr(mod, "settings"):
                setattr(mod, "settings", swapped)

    def _install_engine_spy(self) -> None:
        mod = _resolve(_ENGINE_MODULE)
        if mod is None:  # pragma: no cover - defensive
            return

        def _spy(*args: Any, **kwargs: Any) -> str:
            self.engine_calls += 1
            return "[eval interception spy] engine reached (no live OpenAI call)"

        setattr(mod, _ENGINE_ATTR, _spy)

        # Defense-in-depth (review fix #1): also neutralise the ADULT engine so a
        # non-PARENT conversation can never reach live OpenAI. Does NOT count
        # toward engine_calls — reached_llm is the PARENT-engine signal.
        adult_mod = _resolve(_ADULT_ENGINE_MODULE)
        if adult_mod is not None:
            def _adult_spy(*args: Any, **kwargs: Any) -> str:
                return "[eval interception spy] adult engine reached (no live OpenAI call)"
            setattr(adult_mod, _ADULT_ENGINE_ATTR, _adult_spy)


def _drive_turn(conversation: Any, message: str) -> tuple[str, dict | None, int]:
    """Register ``conversation`` (if not already) and drive ONE turn through
    the real ``conversation_service.process_message`` → ``parent_flow.handle``
    path under the guard above. Returns (reply, trace_block, engine_calls)."""
    from app.reasoning import conversation_trace as trace
    from app.services import conversation_service

    # Review fix #2 (state hygiene): snapshot the conversations-dict slot so the
    # fake eval conversation never leaks into the global in-memory store (a
    # latent test-order hazard vs tests that assert the store is empty).
    sid = conversation.sender_id
    _had = sid in conversation_service.conversations
    _prev = conversation_service.conversations.get(sid)
    conversation_service.conversations[sid] = conversation

    try:
        with _GuardedTurn() as guard:
            trace.reset_history()
            reply = conversation_service.process_message(
                conversation.sender_id, message, conversation.platform,
            )
            history = trace.history()
            block = history[-1] if history else None
            engine_calls = guard.engine_calls
    finally:
        if _had:
            conversation_service.conversations[sid] = _prev
        else:
            conversation_service.conversations.pop(sid, None)

    return reply, block, engine_calls


def answered_by(conversation: Any, message: str) -> dict:
    """Drive ONE turn through the real conversation flow and report WHICH
    handler answered it.

    Returns ``{"handler": <name|"engine">, "reached_llm": bool}``. See the
    module docstring for the exact detection mechanism (engine-invocation spy
    is the reliable signal; the trace's `answered_by`/`handler` refines the
    interceptor's name when the app happens to have recorded one).
    """
    _reply, block, engine_calls = _drive_turn(conversation, message)

    if engine_calls > 0:
        return {"handler": "engine", "reached_llm": True}

    handler_name = None
    if block:
        handler_name = block.get("handler") or block.get("answered_by")
    return {"handler": handler_name or "interceptor", "reached_llm": False}


def answered_by_message(message: str) -> dict:
    """Convenience wrapper: build a FRESH PARENT conversation and drive ONE
    turn through it via `answered_by`."""
    from evals.harness import Harness

    h = Harness(safety.SideEffectLog(), llm_enabled=False, judge_enabled=False)
    conv = h.seed(segment="PARENT", state="START")
    return answered_by(conv, message)


def interception_rate(samples: list[dict]) -> dict:
    """Aggregate `answered_by` / `answered_by_message` samples.

    Returns ``{"intercepted": n, "reached_llm": m, "pct_reached_llm": float,
    "by_handler": {name: count}}``. Never raises; malformed/empty input is
    treated as zero samples.
    """
    try:
        sample_list = list(samples or [])
    except Exception:  # pragma: no cover - defensive
        sample_list = []

    reached_llm = 0
    intercepted = 0
    by_handler: dict[str, int] = {}
    for sample in sample_list:
        try:
            is_llm = bool(sample.get("reached_llm"))
            handler = sample.get("handler") or ("engine" if is_llm else "interceptor")
        except Exception:  # pragma: no cover - skip a malformed sample
            continue
        if is_llm:
            reached_llm += 1
        else:
            intercepted += 1
        by_handler[handler] = by_handler.get(handler, 0) + 1

    total = intercepted + reached_llm
    pct_reached_llm = (reached_llm / total) if total else 0.0
    return {
        "intercepted": intercepted,
        "reached_llm": reached_llm,
        "pct_reached_llm": pct_reached_llm,
        "by_handler": by_handler,
    }
