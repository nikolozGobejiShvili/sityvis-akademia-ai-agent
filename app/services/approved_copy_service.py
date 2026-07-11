"""Program-scoped approved-copy loader.

This module is intentionally read-only and side-effect free. It loads approved
copy from ``app/agent/templates/approved_copy/programs.yaml`` and returns exact
strings by program/key path. Runtime call sites are not routed here yet.
"""
from __future__ import annotations

from pathlib import Path
from threading import Lock
from typing import Any, Mapping

import yaml


APPROVED_COPY_PATH = (
    Path(__file__).resolve().parents[1]
    / "agent"
    / "templates"
    / "approved_copy"
    / "programs.yaml"
)


class ApprovedCopyError(Exception):
    """Base class for approved-copy loading/rendering failures."""


class ApprovedCopyNotFound(ApprovedCopyError, KeyError):
    """Raised when a requested program/key path does not exist."""


class ApprovedCopyFormatError(ApprovedCopyError):
    """Raised when placeholder rendering fails."""


_cache: dict[str, Any] | None = None
_cache_lock = Lock()


def _load_yaml() -> dict[str, Any]:
    try:
        with APPROVED_COPY_PATH.open("r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
    except FileNotFoundError as exc:
        raise ApprovedCopyNotFound(
            f"Approved copy file not found: {APPROVED_COPY_PATH}"
        ) from exc
    if not isinstance(raw, Mapping):
        raise ApprovedCopyFormatError("Approved copy YAML root must be a mapping")
    programs = raw.get("programs")
    if not isinstance(programs, Mapping):
        raise ApprovedCopyFormatError("Approved copy YAML must contain 'programs'")
    return {"programs": dict(programs)}


def _data() -> dict[str, Any]:
    global _cache
    with _cache_lock:
        if _cache is None:
            _cache = _load_yaml()
        return _cache


def reset_cache() -> None:
    """Clear the in-memory YAML cache. Intended for tests."""
    global _cache
    with _cache_lock:
        _cache = None


def _split_request(program: str, key_path: str | None) -> tuple[str, str]:
    program = (program or "").strip()
    key_path = (key_path or "").strip() if key_path is not None else None
    if key_path:
        if not program:
            raise ApprovedCopyNotFound("Approved copy program is required")
        return program, key_path
    if "." not in program:
        raise ApprovedCopyNotFound(
            "Approved copy path must be 'program.key.path' or pass key_path"
        )
    program_name, _, rest = program.partition(".")
    if not program_name or not rest:
        raise ApprovedCopyNotFound(f"Invalid approved copy path: {program!r}")
    return program_name, rest


def _resolve(program: str, key_path: str) -> str:
    programs = _data()["programs"]
    if program not in programs:
        raise ApprovedCopyNotFound(f"Approved copy program not found: {program}")
    node: Any = programs[program]
    traversed = [program]
    for part in key_path.split("."):
        if not isinstance(node, Mapping) or part not in node:
            path = ".".join(traversed + [part])
            raise ApprovedCopyNotFound(f"Approved copy key not found: {path}")
        node = node[part]
        traversed.append(part)
    if not isinstance(node, str):
        raise ApprovedCopyNotFound(
            f"Approved copy key is not a string: {'.'.join(traversed)}"
        )
    return node


def get_approved_copy(
    program: str,
    key_path: str | None = None,
    context: dict[str, Any] | None = None,
    **kwargs: Any,
) -> str:
    """Return approved copy for a program-scoped key.

    Supports both ``get_approved_copy("camp.price.full_block")`` and
    ``get_approved_copy("camp", "price.full_block")``. If placeholders are
    present, callers must provide all required values via ``context`` and/or
    keyword arguments; missing placeholders fail closed.
    """
    program_name, path = _split_request(program, key_path)
    template = _resolve(program_name, path)
    values: dict[str, Any] = {}
    if context:
        values.update(context)
    values.update(kwargs)
    try:
        return template.format(**values)
    except KeyError as exc:
        missing = exc.args[0]
        raise ApprovedCopyFormatError(
            f"Missing approved-copy placeholder {missing!r} for "
            f"{program_name}.{path}"
        ) from exc
    except Exception as exc:
        raise ApprovedCopyFormatError(
            f"Failed to render approved copy {program_name}.{path}: {exc}"
        ) from exc
