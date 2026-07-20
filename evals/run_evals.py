"""CLI entry for the agent-understanding eval harness.

  python -m evals.run_evals                  # deterministic, FREE, fully offline
  python -m evals.run_evals --llm            # + full_turn cases (real OpenAI)
  python -m evals.run_evals --llm --judge    # + Claude LLM-as-judge (needs ANTHROPIC_API_KEY)
  python -m evals.run_evals --category routing
  python -m evals.run_evals --case E1

Exit code 0 = all run checks passed AND no READ-ONLY tripwire hit; 1 otherwise.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow `python evals/run_evals.py` as well as `-m evals.run_evals`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="Agent-understanding eval harness (READ-ONLY).")
    ap.add_argument("--llm", action="store_true",
                    help="enable full_turn cases (real OpenAI — small cost)")
    ap.add_argument("--judge", action="store_true",
                    help="enable Claude LLM-as-judge for response quality (needs ANTHROPIC_API_KEY)")
    ap.add_argument("--category", choices=(
        "understanding", "extraction", "routing", "response_quality", "followup"),
        help="run only one dimension")
    ap.add_argument("--case", help="run only one case id (e.g. E1)")
    args = ap.parse_args()

    from evals.harness import run_all
    return run_all(llm=args.llm, judge=args.judge,
                   category=args.category, case_id=args.case)


if __name__ == "__main__":
    raise SystemExit(main())
