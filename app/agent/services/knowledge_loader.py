"""Knowledge / business-fact loader.

Loads structured YAML knowledge files from ``app/agent/knowledge/`` and
returns the parsed mapping. There is intentionally NO silent fallback to
defaults — if a knowledge file is missing or malformed, loading fails
loudly with a self-describing error, because facts are the kind of data
where "silently wrong" is the worst possible outcome.

Usage::

    from app.agent.services.knowledge_loader import load_knowledge

    camp  = load_knowledge("camp_2026")
    price = camp["camp"]["price_gel"]                 # 2150
    loc   = camp["camp"]["location"]                  # "ამბასადორი კაჭრეთი"

    months_ka = load_knowledge("i18n/ka_months")      # nested folder
    nom = months_ka["months_nominative"]              # dict[int, str]

Names map directly to files: ``"camp_2026"`` → ``camp_2026.yaml``,
``"i18n/ka_months"`` → ``i18n/ka_months.yaml``.
"""

from __future__ import annotations

from pathlib import Path
from threading import Lock
from typing import Any, Mapping

import yaml

KNOWLEDGE_DIR = Path(__file__).resolve().parents[2] / "agent" / "knowledge"


class KnowledgeNotFound(FileNotFoundError):
    """Raised when a named knowledge file is missing or malformed."""


_cache: dict[str, dict[str, Any]] = {}
_cache_lock = Lock()


def _path_for(name: str) -> Path:
    # Accept "camp_2026", "camp_2026.yaml", "i18n/ka_months", etc.
    stem = name[:-5] if name.endswith(".yaml") else name
    return KNOWLEDGE_DIR / f"{stem}.yaml"


def load_knowledge(name: str) -> dict[str, Any]:
    """Return the parsed YAML mapping for the named knowledge file.

    Raises ``KnowledgeNotFound`` if the file does not exist, parses to
    something that is not a mapping, or contains a parser error. Never
    returns a synthetic default — callers must handle the exception (or,
    typically, let it propagate so the app fails to start rather than
    silently render a wrong fact to a customer).
    """
    with _cache_lock:
        cached = _cache.get(name)
        if cached is not None:
            return cached

    path = _path_for(name)
    if not path.is_file():
        raise KnowledgeNotFound(
            f"Knowledge file {name!r} not found at {path}. "
            f"Expected a .yaml file under {KNOWLEDGE_DIR}."
        )

    try:
        with path.open("r", encoding="utf-8") as fh:
            payload = yaml.safe_load(fh)
    except yaml.YAMLError as exc:
        raise KnowledgeNotFound(
            f"Knowledge file {name!r} at {path} failed to parse: {exc}"
        ) from exc

    if not isinstance(payload, Mapping):
        raise KnowledgeNotFound(
            f"Knowledge file {name!r} at {path} must be a YAML mapping at "
            f"the top level, got {type(payload).__name__}."
        )

    data: dict[str, Any] = dict(payload)
    with _cache_lock:
        _cache[name] = data
    return data


def reset_cache() -> None:
    """Drop the in-memory cache (intended for tests)."""
    with _cache_lock:
        _cache.clear()
