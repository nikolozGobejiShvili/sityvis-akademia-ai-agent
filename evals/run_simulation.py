"""CLI entry for the persona multi-turn conversation SIMULATION harness.

  python -m evals.run_simulation --runs 5                         # 5 per persona (smoke)
  python -m evals.run_simulation --runs 50 --persona price_shopper
  python -m evals.run_simulation --report out.md                 # write the full report
  python -m evals.run_simulation --verbose                       # include passing transcripts
  python -m evals.run_simulation --list                          # list the personas

READ-ONLY throughout (see evals.safety): zero real Calendar / Sheets / Meta /
SMTP / Redis writes. The persona-user + the engine are the models UNDER TEST
(real OpenAI); the judge + Georgian-grammar evaluator are real Claude. Self-skips
with a clear message when no OPENAI_API_KEY is present.

Exit code 0 = pass-rate ≥ --threshold AND no READ-ONLY tripwire; 1 otherwise
(so it can gate a deploy later).

Scaling: a smoke run is `--runs 5` (all 10 personas × 5 = 50 conversations, a few
dollars / minutes). A full pass is `--runs 50` (500 conversations); scope it down
with `--persona <id>` while iterating. `--max-grammar-turns N` caps grammar
grading per conversation to bound Claude cost (0 = grade every reply).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow `python evals/run_simulation.py` as well as `-m evals.run_simulation`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Persona multi-turn conversation simulation (READ-ONLY).")
    ap.add_argument("--runs", type=int, default=5,
                    help="conversations per persona (default 5)")
    ap.add_argument("--persona", action="append", dest="personas",
                    help="run only this persona id (repeatable)")
    ap.add_argument("--report", help="write the full report to this path")
    ap.add_argument("--verbose", action="store_true",
                    help="include full transcripts for PASSING conversations too")
    ap.add_argument("--threshold", type=float, default=0.8,
                    help="min overall pass-rate for exit 0 (default 0.8)")
    ap.add_argument("--max-grammar-turns", type=int, default=0,
                    help="cap grammar grading per conversation (0 = every reply)")
    ap.add_argument("--list", action="store_true",
                    help="list the personas (in_domain vs off_topic) and exit")
    args = ap.parse_args()

    from evals import personas as personas_mod

    if args.list:
        print("Personas:")
        for p in personas_mod.PERSONAS:
            kind = "in_domain " if p.in_domain else "OFF-TOPIC "
            print(f"  {kind} {p.id:<20} {p.label}  (max_turns={p.max_turns})")
        print("\nAllowed domain topics:")
        for k, v in personas_mod.ALLOWED_DOMAIN.items():
            print(f"  {k:<16} {v}")
        return 0

    from evals.simulation import run_all
    return run_all(
        runs=args.runs, persona_ids=args.personas, report_path=args.report,
        verbose=args.verbose, threshold=args.threshold,
        max_grammar_turns=args.max_grammar_turns,
    )


if __name__ == "__main__":
    raise SystemExit(main())
