"""Operator-editable approved-answers store + deterministic matcher (Phase 5,
Task 4 — bounded learning loop). Operators edit
``data/admin_config/approved_answers.yaml`` to steer answers with NO code
change; a later task's LLM tool reads through `find_approved_answer`.

Mirrors two existing house patterns:
  * `app/reasoning/camp_topic_facts.py` `_count` / `_score` /
    `detect_camp_topic` — lowercase the message, count trigger-substring
    hits, best_score > 0 gate, strictly-greater tie-break (earliest wins).
  * `app/services/admin_config_service.py` `_safe_load_yaml` — tolerant
    fresh read on every call (NO module cache), safe default on any error.

Additive & flag-independent: this module is a pure data layer. It is wired
into NO live path here — a later task adds the tool. `load_answers()` and
`find_approved_answer()` never raise.
"""
from __future__ import annotations

import logging
from typing import Any

import yaml

from app.services.admin_config_service import ADMIN_CONFIG_DIR

logger = logging.getLogger(__name__)

ANSWERS_PATH = ADMIN_CONFIG_DIR / "approved_answers.yaml"

# A trigger shorter than this never contributes a match on its own.
_MIN_TRIGGER_LEN = 3


def load_answers() -> list[dict[str, Any]]:
    """Return the `answers` list from approved_answers.yaml, read fresh on
    every call (no module cache — mirrors admin_config_service._safe_load_yaml
    Bug-4 contract, so an operator edit is visible on the very next call).

    Missing file / malformed YAML / wrong shape / non-dict rows all resolve
    to `[]`. Never raises.
    """
    try:
        if not ANSWERS_PATH.exists():
            logger.info("[approved_answers] %s not present — using empty list", ANSWERS_PATH.name)
            return []
        with ANSWERS_PATH.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        if not isinstance(data, dict):
            return []
        answers = data.get("answers")
        if not isinstance(answers, list):
            return []
        return [dict(a) for a in answers if isinstance(a, dict)]
    except yaml.YAMLError as exc:
        logger.warning(
            "[approved_answers] %s YAML parse failed — using empty list: %s",
            ANSWERS_PATH.name, exc,
        )
        return []
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("[approved_answers] load_answers failed: %s", exc)
        return []


def _count(low: str, triggers: Any) -> int:
    """Count triggers (lowercased) present as substrings of `low`. Mirrors
    `camp_topic_facts._count`, plus a minimum-length guard: a trigger shorter
    than `_MIN_TRIGGER_LEN` never contributes a hit."""
    if not isinstance(triggers, (list, tuple)):
        return 0
    hits = 0
    for t in triggers:
        if not t:
            continue
        t_str = str(t).strip().lower()
        if len(t_str) < _MIN_TRIGGER_LEN:
            continue
        if t_str in low:
            hits += 1
    return hits


def find_approved_answer(message: str, segment: str) -> dict[str, Any] | None:
    """Return the highest-scoring approved answer `{id, answer}` for
    `message`, or None.

    Among `active` answers whose `segment` matches the passed `segment` OR is
    `"any"`, scores by counting trigger-substring hits (mirrors
    `camp_topic_facts._score`); a trigger shorter than 3 chars never
    contributes a hit. The winning score must be >= 1. Strictly-greater
    tie-break so the earliest-listed answer wins ties. Never raises.
    """
    try:
        low = (message or "").lower().strip()
        if not low:
            return None
        seg = str(segment or "").strip()

        best: dict[str, Any] | None = None
        best_score = 0
        for entry in load_answers():
            if not isinstance(entry, dict):
                continue
            if str(entry.get("status") or "active") != "active":
                continue
            entry_segment = str(entry.get("segment") or "")
            if entry_segment != "any" and entry_segment != seg:
                continue

            score = _count(low, entry.get("triggers"))
            if score <= best_score:
                continue

            answer_text = entry.get("answer")
            answer_id = entry.get("id")
            if not answer_text or not answer_id:
                continue

            best_score = score
            best = {"id": answer_id, "answer": answer_text}

        return best if best_score > 0 else None
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("[approved_answers] find_approved_answer failed: %s", exc)
        return None
