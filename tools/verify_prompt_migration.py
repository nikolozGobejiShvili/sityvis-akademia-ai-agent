"""Phase 1 byte-identity verification (PROMPT migration).

For every prompt constant in the migration map, this script:
  1. reads the constant from data.prompts (Python literal — until Step 3, then
     a prompt_loader alias)
  2. loads the corresponding .md via app.agent.llm.prompt_loader
  3. asserts byte-identical equality AND equal length
  4. on mismatch, prints the constant name, both lengths, the first differing
     character index, and a short context window around it
  5. exits non-zero if any mismatch

IMPORTANT — verification ordering (Phase 1, Step 2 vs Step 4):

  Step 2 (BEFORE swap): data.prompts.X is still the original Python literal.
                        This run is the real GROUND-TRUTH byte check between
                        the Python literal and the new .md file.

  Step 4 (AFTER swap):  data.prompts.X is a prompt_loader alias. This run is
                        a STRUCTURAL SANITY check only (loader vs loader). It
                        proves every alias resolves to a string, but the
                        byte-identity proof comes from Step 2 — not from this
                        run.

Run from repo root:
    .venv/Scripts/python.exe tools/verify_prompt_migration.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

# Force UTF-8 stdout on Windows so Georgian context can be printed safely.
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

from app.agent.llm.prompt_loader import (  # noqa: E402
    load_prompt,
    reset_cache,
)
from data import prompts  # noqa: E402

# (python_constant_name, prompt_name)
CASES: list[tuple[str, str]] = [
    ("SYSTEM_PROMPT_BASE", "system_base"),
    ("SYSTEM_PROMPT_PARENT", "system_parent"),
    ("SYSTEM_PROMPT_ADULT", "system_adult"),
    ("DETECT_SEGMENT", "detect_segment"),
    ("START_INTENT_DETECT", "detect_start_intent"),
    ("COMMENT_INTENT_PROMPT", "detect_comment_intent"),
    ("SUMMARY_PROMPT", "summary"),
    ("PARENT_PRESENT_VALUE_CONTEXT", "parent_present_value"),
]


def _first_diff_index(a: str, b: str) -> int:
    for i, (ca, cb) in enumerate(zip(a, b)):
        if ca != cb:
            return i
    return min(len(a), len(b))


def _diff_report(constant_name: str, expected: str, actual: str) -> str:
    idx = _first_diff_index(expected, actual)
    window = 30
    start = max(0, idx - window)
    end_e = min(len(expected), idx + window)
    end_a = min(len(actual), idx + window)
    return (
        f"  - {constant_name}:\n"
        f"      lengths: py={len(expected)} md={len(actual)}  "
        f"(diff={len(actual) - len(expected):+d})\n"
        f"      first differing char index: {idx}\n"
        f"      py …{expected[start:end_e]!r}…\n"
        f"      md …{actual[start:end_a]!r}…"
    )


def main() -> int:
    reset_cache()
    failures: list[str] = []

    for constant_name, prompt_name in CASES:
        if not hasattr(prompts, constant_name):
            failures.append(
                f"  - {constant_name}: missing from data.prompts "
                f"(audit drift)"
            )
            continue
        expected = getattr(prompts, constant_name)
        try:
            actual = load_prompt(prompt_name)
        except Exception as exc:
            failures.append(
                f"  - {constant_name} -> {prompt_name}: loader raised {exc!r}"
            )
            continue

        if len(expected) != len(actual):
            failures.append(_diff_report(constant_name, expected, actual))
            continue
        if expected != actual:
            failures.append(_diff_report(constant_name, expected, actual))
            continue

        print(
            f"[ok] {constant_name:32s} == {prompt_name}.md  "
            f"(len={len(expected)})"
        )

    print()
    if failures:
        print(f"=== {len(failures)} mismatch(es) ===")
        for failure in failures:
            print(failure)
        return 1

    print(f"All {len(CASES)} prompts byte-identical "
          f"between data.prompts and prompt_loader.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
