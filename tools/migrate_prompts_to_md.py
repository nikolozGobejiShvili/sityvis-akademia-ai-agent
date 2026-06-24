"""Phase 1 migration generator (PROMPT → .md).

Extracts each AI prompt constant from data/prompts.py and writes it byte-
identically to a .md file under app/agent/prompts/.

This script writes the EXACT Python string to disk — no strip, no normalize,
no trailing-newline manipulation. Python's `Path.write_text(..., encoding="utf-8",
newline="")` preserves the string verbatim.

Run from repo root:
    .venv/Scripts/python.exe tools/migrate_prompts_to_md.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from data import prompts  # noqa: E402

PROMPTS_DIR = REPO_ROOT / "app" / "agent" / "prompts"

# (python_constant_name, target_md_filename)
MIGRATION: list[tuple[str, str]] = [
    ("SYSTEM_PROMPT_BASE", "system_base.md"),
    ("SYSTEM_PROMPT_PARENT", "system_parent.md"),
    ("SYSTEM_PROMPT_ADULT", "system_adult.md"),
    ("DETECT_SEGMENT", "detect_segment.md"),
    ("START_INTENT_DETECT", "detect_start_intent.md"),
    ("COMMENT_INTENT_PROMPT", "detect_comment_intent.md"),
    ("SUMMARY_PROMPT", "summary.md"),
    ("PARENT_PRESENT_VALUE_CONTEXT", "parent_present_value.md"),
]


def main() -> int:
    PROMPTS_DIR.mkdir(parents=True, exist_ok=True)
    written = 0
    for constant_name, filename in MIGRATION:
        value = getattr(prompts, constant_name)
        target = PROMPTS_DIR / filename
        # newline="" disables universal-newline translation; bytes go to disk
        # exactly as they exist in the Python string (single "\n" stays "\n",
        # not "\r\n" on Windows).
        with target.open("w", encoding="utf-8", newline="") as fh:
            fh.write(value)

        # Round-trip read to confirm the on-disk bytes decode back to the
        # original string.
        with target.open("r", encoding="utf-8", newline="") as fh:
            loaded = fh.read()
        if loaded != value:
            print(
                f"[FAIL] {constant_name} round-trip mismatch: "
                f"py_len={len(value)} md_len={len(loaded)}"
            )
            return 1
        written += 1
        print(
            f"[write] {target.relative_to(REPO_ROOT)}  "
            f"len={len(value)} ends_with_newline={value.endswith(chr(10))}"
        )

    print(f"\nAll {written} prompt files written and round-trip OK.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
