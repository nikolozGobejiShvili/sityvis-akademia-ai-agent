"""LLM prompt loader.

Reads prompt files from ``app/agent/prompts/<name>.md`` and returns the file
contents UNCHANGED — no strip, no normalize, no trailing-newline manipulation.
Whatever bytes are on disk (decoded as UTF-8 with universal-newline translation
disabled) is what the caller gets back.

Rationale: every prompt was migrated byte-identically from a Python string
constant. Any normalization here would silently break that contract and the
LLM would see different input than the pre-migration code did.

Usage::

    from app.agent.llm.prompt_loader import load_prompt

    system = load_prompt("system_base")
    detect = load_prompt("detect_segment")

The loader caches every prompt on first read; call ``reset_cache()`` from
tests to force reload.
"""

from __future__ import annotations

from pathlib import Path
from threading import Lock

PROMPTS_DIR = Path(__file__).resolve().parents[2] / "agent" / "prompts"

_SUFFIX = ".md"


class PromptNotFound(FileNotFoundError):
    """Raised when a named prompt cannot be located on disk."""


_cache: dict[str, str] = {}
_cache_lock = Lock()


def _path_for(name: str) -> Path:
    # Accept both "system_base" and "system_base.md". We do NOT accept dotted
    # paths like "system.base" — prompts live in a single flat folder and
    # giving them ad-hoc namespaces would invite drift between docs and code.
    stem = name[:-len(_SUFFIX)] if name.endswith(_SUFFIX) else name
    return PROMPTS_DIR / f"{stem}{_SUFFIX}"


def load_prompt(name: str) -> str:
    """Return the raw text of the named prompt, byte-identical to the file.

    Raises ``PromptNotFound`` (a FileNotFoundError subclass) if the file
    does not exist, with a message naming the expected path so the developer
    can fix the typo without grepping.
    """
    with _cache_lock:
        cached = _cache.get(name)
        if cached is not None:
            return cached

    path = _path_for(name)
    if not path.is_file():
        raise PromptNotFound(
            f"Prompt {name!r} not found at {path}. "
            f"Expected a .md file under {PROMPTS_DIR}."
        )

    # newline="" disables universal-newline translation so a single "\n" on
    # disk stays a single "\n" in the returned string (Windows would otherwise
    # silently convert "\r\n" → "\n" on read, which is fine here, but
    # disabling it is the safer contract).
    with path.open("r", encoding="utf-8", newline="") as fh:
        text = fh.read()

    with _cache_lock:
        _cache[name] = text
    return text


def reset_cache() -> None:
    """Drop the in-memory cache (intended for tests)."""
    with _cache_lock:
        _cache.clear()
