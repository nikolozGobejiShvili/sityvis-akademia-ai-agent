"""Phase 4 (prompt & sanitizer hygiene) — flag defaults + from_env parsing.

Both flags default OFF (flag-off ⇒ byte-identical). This file grows across
Phase-4 tasks; Task 1 covers only the two flags.
"""
from __future__ import annotations

import dataclasses

from app import config
from app.config import Settings


def test_lean_prompt_flag_defaults_off():
    assert config.settings.USE_LEAN_PROMPT is False


def test_lean_sanitizer_flag_defaults_off():
    assert config.settings.USE_LEAN_SANITIZER is False


def test_from_env_parses_lean_prompt_true(monkeypatch):
    monkeypatch.setenv("USE_LEAN_PROMPT", "true")
    assert Settings.from_env().USE_LEAN_PROMPT is True


def test_from_env_parses_lean_sanitizer_true(monkeypatch):
    monkeypatch.setenv("USE_LEAN_SANITIZER", "true")
    assert Settings.from_env().USE_LEAN_SANITIZER is True


def test_from_env_defaults_off_when_unset(monkeypatch):
    monkeypatch.delenv("USE_LEAN_PROMPT", raising=False)
    monkeypatch.delenv("USE_LEAN_SANITIZER", raising=False)
    s = Settings.from_env()
    assert s.USE_LEAN_PROMPT is False and s.USE_LEAN_SANITIZER is False
