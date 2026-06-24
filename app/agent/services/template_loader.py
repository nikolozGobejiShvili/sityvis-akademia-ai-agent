"""User-facing template loader.

Loads YAML templates from ``app/agent/templates/<group>/*.yaml`` and returns
raw template strings. Rendering (``str.format(**vars)``) is the caller's
responsibility — this loader never substitutes placeholders.

Group = subfolder name (parent, adult, common, comments, notifications,
calendar). Each group merges all ``*.yaml`` files in its folder into a single
flat key namespace; keys MUST be unique within a group, and an
``AmbiguousTemplateKey`` is raised if two files in the same group declare the
same top-level key.

Usage::

    from app.agent.services.template_loader import get_template

    raw = get_template("parent", "welcome")         # by group + key
    raw = get_template("parent.welcome_with_concern") # by "group.key" path
    text = raw.format(child_age="9")                # caller renders

The loader caches every group on first access; call ``reset_cache()`` from
tests to reload from disk.
"""

from __future__ import annotations

from pathlib import Path
from threading import Lock
from typing import Mapping

import yaml

TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "agent" / "templates"


class TemplateNotFound(KeyError):
    """Raised when a template key (or its group) does not exist."""


class AmbiguousTemplateKey(RuntimeError):
    """Raised when two YAML files in the same group declare the same key."""


_cache: dict[str, dict[str, str]] = {}
_cache_lock = Lock()


def _read_yaml(path: Path) -> dict[str, str]:
    with path.open("r", encoding="utf-8") as fh:
        payload = yaml.safe_load(fh) or {}
    if not isinstance(payload, Mapping):
        raise TemplateNotFound(
            f"Template file {path} must be a YAML mapping at the top level"
        )
    out: dict[str, str] = {}
    for key, value in payload.items():
        if not isinstance(value, str):
            raise TemplateNotFound(
                f"Template {path}:{key!r} must be a string, got "
                f"{type(value).__name__}"
            )
        out[str(key)] = value
    return out


def _load_group(group: str) -> dict[str, str]:
    group_dir = TEMPLATES_DIR / group
    if not group_dir.is_dir():
        raise TemplateNotFound(
            f"Template group {group!r} not found "
            f"(expected directory: {group_dir})"
        )

    merged: dict[str, str] = {}
    origin: dict[str, Path] = {}
    for yaml_path in sorted(group_dir.glob("*.yaml")):
        entries = _read_yaml(yaml_path)
        for key, value in entries.items():
            if key in merged:
                raise AmbiguousTemplateKey(
                    f"Template key {group!r}/{key!r} declared in both "
                    f"{origin[key]} and {yaml_path}"
                )
            merged[key] = value
            origin[key] = yaml_path

    if not merged:
        raise TemplateNotFound(
            f"Template group {group!r} contains no .yaml files at {group_dir}"
        )
    return merged


def _get_group(group: str) -> dict[str, str]:
    with _cache_lock:
        if group not in _cache:
            _cache[group] = _load_group(group)
        return _cache[group]


def get_template(group: str, key: str | None = None) -> str:
    """Return the raw template string for ``group/key``.

    Two call styles are supported, both equivalent::

        get_template("parent", "welcome")
        get_template("parent.welcome")

    Raises ``TemplateNotFound`` if either the group or the key is absent.
    """
    if key is None:
        if "." not in group:
            raise TemplateNotFound(
                f"Template path {group!r} must be 'group.key' or pass key "
                f"as a second argument"
            )
        group, _, key = group.partition(".")

    entries = _get_group(group)
    if key not in entries:
        available = ", ".join(sorted(entries)) or "(none)"
        raise TemplateNotFound(
            f"Template key {group!r}/{key!r} not found. "
            f"Available keys in {group!r}: {available}"
        )
    return entries[key]


def reset_cache() -> None:
    """Drop the in-memory cache (intended for tests)."""
    with _cache_lock:
        _cache.clear()
