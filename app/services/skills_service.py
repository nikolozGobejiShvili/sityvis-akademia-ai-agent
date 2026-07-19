"""Skills registry (Phase 3, USE_SKILLS).

Reads operator/author-editable capability packs from ``app/agent/skills/*.md``
(YAML frontmatter + Markdown body), fresh each call, and selects the most
relevant active pack(s) for a turn. Read-only: the operator is the sole writer
of the pack files. Every public function is tolerant and NEVER raises.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# app/services/skills_service.py -> parents[1] == app/ ; skills live in app/agent/skills
SKILLS_DIR: Path = Path(__file__).resolve().parents[1] / "agent" / "skills"
DEFAULT_SKILL_LIMIT: int = 2


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse_skill_md(text: str) -> tuple[dict, str]:
    """Split a SKILL.md into (frontmatter dict, body).

    Line-based (fixes critique M1 — no fragile ``lstrip("-")``): the first
    non-blank line must be exactly ``---``; the frontmatter is every line up to
    the next ``---`` line; the body is the remainder. Tolerant: not a string →
    ({}, ""); no opening fence or no closing fence → ({}, original text);
    frontmatter that isn't a mapping → ({}, body). Never raises. A body may
    legitimately start with a markdown ``---`` rule or a ``-`` bullet — those
    are preserved.
    """
    try:
        if not isinstance(text, str):
            return {}, ""
        lines = text.splitlines(keepends=True)
        i = 0
        while i < len(lines) and lines[i].strip() == "":
            i += 1
        if i >= len(lines) or lines[i].strip() != "---":
            return {}, text
        close = -1
        for j in range(i + 1, len(lines)):
            if lines[j].strip() == "---":
                close = j
                break
        if close == -1:
            return {}, text
        fm_block = "".join(lines[i + 1:close])
        body = "".join(lines[close + 1:]).lstrip("\n")
        meta = yaml.safe_load(fm_block)
        if not isinstance(meta, dict):
            return {}, body
        return meta, body
    except Exception:  # pragma: no cover - defensive
        return {}, text if isinstance(text, str) else ""


def load_skills() -> list[dict]:
    """Return every ``app/agent/skills/*.md`` (except README.md) as a normalized
    dict {id, name, segment, status, priority, triggers, body}. Fresh read every
    call (operator edits take effect without a restart). Tolerant → [] on any
    error; a single malformed file is skipped, not fatal. Never raises.
    """
    try:
        skills: list[dict] = []
        if not SKILLS_DIR.is_dir():
            return []
        for path in sorted(SKILLS_DIR.glob("*.md")):
            if path.name.lower() == "readme.md":
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except Exception:
                continue
            meta, body = _parse_skill_md(text)
            if not isinstance(meta, dict):
                continue
            raw_triggers = meta.get("triggers")
            triggers = (
                [str(t).lower() for t in raw_triggers if t]
                if isinstance(raw_triggers, list)
                else []
            )
            sid = str(meta.get("id") or path.stem)
            skills.append({
                "id": sid,
                "name": str(meta.get("name") or sid),
                "segment": str(meta.get("segment") or "any"),
                "status": str(meta.get("status") or "active"),
                "priority": _safe_int(meta.get("priority"), 0),
                "triggers": triggers,
                "body": body if isinstance(body, str) else "",
            })
        return skills
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("[skills] load_skills failed: %s", exc)
        return []
