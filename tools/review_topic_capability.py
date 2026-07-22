"""Review runner for Capability #1 (camp-topic facts tool, USE_PROGRAM_TOPICS).

Drives every question in ``evals/review_topic_questions_2026_07_22.yaml``
through the agent ONCE in a given config and captures the reply, so the
operator can judge the two configs side by side:

  * ``baseline``    — USE_PROGRAM_TOPICS=false  → the canned camp-topic
                       interceptor answers directly (free, deterministic,
                       NO OpenAI call — even a "varied"-bucket miss falls
                       back to the free legacy state machine because real
                       httpx is blocked for this config).
  * ``capability``   — USE_PROGRAM_TOPICS=true + USE_PARENT_LLM_ENGINE=true
                       → the interceptor yields and the LLM reasons over the
                       ``get_program_topic`` tool. PAID — makes REAL OpenAI
                       calls. Requires ``--yes``.

Usage:
    .venv/Scripts/python.exe tools/review_topic_capability.py --config baseline --yes
    .venv/Scripts/python.exe tools/review_topic_capability.py --config capability --yes   # PAID
    .venv/Scripts/python.exe tools/review_topic_capability.py --compare

Design notes (see docs/... none — this file is the source of truth):
  * Flags are read from THIS process's environment by ``app/config.py``
    (``_env`` reads ``os.environ`` first). We set ``os.environ`` BEFORE
    importing anything under ``app.*`` — the same env+restart toggle
    production uses — so the operator only ever picks ``--config``.
  * READ-ONLY: every turn is driven behind ``evals.safety.install_readonly``
    (Calendar/Sheets/Meta/SMTP dry-run stubs + a hard SMTP tripwire; real
    httpx is ALSO blocked for ``baseline`` so that config can never spend
    money even on an interceptor miss).
  * The camp ended 2026-07-20, so registration is closed in the live config;
    without reopening it, a topic question would get swallowed by the
    dead-season "registration closed" interceptor before ever reaching the
    topic handler. We monkeypatch
    ``admin_config_service.get_camp_registration_status`` to return
    ``"open"`` for the run only (module-attribute patch — safe for a
    one-shot script process; see ``reopen_camp_registration_for_run``).
  * Each question gets a FRESH conversation (mirrors
    ``evals/harness.py::Harness.seed`` / ``Harness.process``), pre-seeded
    with one assistant turn so the first-turn static welcome never
    short-circuits the topic question.
  * This script NEVER calls ``evals.run_evals`` / ``evals.harness.run_all``
    and NEVER writes ``evals/baseline.json`` — it drives
    ``conversation_service.process_message`` directly, exactly like the
    eval harness does. ``evals/baseline.json`` is additionally
    snapshotted + restored around the whole run as belt-and-braces, and its
    md5 is printed at the end.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

QUESTIONS_PATH = ROOT / "evals" / "review_topic_questions_2026_07_22.yaml"
REPORTS_DIR = ROOT / "tools" / "reports"
BASELINE_JSON_PATH = ROOT / "evals" / "baseline.json"

CAPABILITY_WARNING = (
    "\n"
    "======================================================================\n"
    "  WARNING: --config capability makes REAL, PAID OpenAI calls.\n"
    "\n"
    "  It sets USE_PROGRAM_TOPICS=true + USE_PARENT_LLM_ENGINE=true and\n"
    "  drives all review questions through the live parent LLM engine\n"
    "  (get_program_topic tool). Every question is one real OpenAI request.\n"
    "======================================================================\n"
)


# ---------------------------------------------------------------------------
# Env flags — MUST run before any `app.*` import (fresh-process env toggle,
# the same mechanism production uses via .env + restart).
# ---------------------------------------------------------------------------
def set_env_for_config(config: str) -> None:
    import os

    if config in ("baseline", "baseline-live"):
        os.environ["USE_PROGRAM_TOPICS"] = "false"
        # Engine ON is production-faithful (live default) and is what lets
        # the turn actually reach the camp-topic interceptor at all — the
        # interceptor call site only exists inside the USE_PARENT_LLM_ENGINE
        # branch of app/flows/parent_flow.py. `baseline` blocks real httpx so a
        # varied-bucket interceptor MISS falls to the free legacy state machine
        # (understates the true "today" answer). `baseline-live` allows OpenAI
        # (sends still stubbed) so a MISS reaches the real engine-WITHOUT-tool —
        # the faithful "today" comparison for the varied bucket (PAID, --yes).
        os.environ["USE_PARENT_LLM_ENGINE"] = "true"
    elif config == "capability":
        os.environ["USE_PROGRAM_TOPICS"] = "true"
        os.environ["USE_PARENT_LLM_ENGINE"] = "true"
    else:
        raise ValueError(f"unknown config: {config!r}")


# Configs that make real (paid) OpenAI calls and need the --yes gate.
_PAID_CONFIGS = ("capability", "baseline-live")


def install_review_guard(config: str):
    """Install the eval read-only guard (Calendar/Sheets/Meta/SMTP dry-run +
    tripwires). ``block_httpx`` mirrors evals/run_evals.py's own contract:
    True for a deterministic-only (no OpenAI) config, False for the one
    config that is EXPECTED to call OpenAI."""
    from evals import safety

    log = safety.SideEffectLog()
    safety.install_readonly(log, block_httpx=(config not in _PAID_CONFIGS))
    return log


def reopen_camp_registration_for_run() -> None:
    """Reopen camp registration for the run (camp ended 2026-07-20) so a
    topic question reaches the topic handler instead of the dead-season
    "registration closed" interceptor. Raw module-attribute patch — safe
    for a one-shot script process (it exits right after). Tests should use
    pytest's `monkeypatch` fixture on the same target instead, so it
    auto-reverts and never leaks into other tests."""
    import app.services.admin_config_service as admin_config_service

    admin_config_service.get_camp_registration_status = lambda: "open"


# ---------------------------------------------------------------------------
# Questions
# ---------------------------------------------------------------------------
def load_questions() -> list[dict]:
    import yaml

    data = yaml.safe_load(QUESTIONS_PATH.read_text(encoding="utf-8")) or {}
    questions = data.get("questions") or []
    if not questions:
        raise RuntimeError(f"no questions found in {QUESTIONS_PATH}")
    return questions


# ---------------------------------------------------------------------------
# Driving a single turn — mirrors evals/harness.py::Harness.seed + .process
# ---------------------------------------------------------------------------
def drive_question(question: dict, config: str) -> str:
    """Drive ONE question through a FRESH conversation and return the
    agent's reply. Never reuses state across questions."""
    from app.models.conversation import Conversation
    from app.models.lead import Lead
    from app.services import conversation_service

    qid = str(question.get("id") or "q")
    sender_id = f"review-topic-{config}-{qid}"
    platform = "instagram"

    conv = Conversation(sender_id=sender_id, platform=platform, segment="PARENT")
    conv.state = "ASK_CHALLENGE"
    # Pre-seed one assistant turn so the first-turn static welcome (which
    # fires unconditionally at state=="START" with no prior assistant turn)
    # never short-circuits the topic question — mirrors the pattern used by
    # tests/test_program_topic_tool_2026_07_22.py's e2e test.
    conv.history.append({"role": "assistant", "content": "_prior"})
    # Known, in-range child_age so neither config's reply gets an extra
    # "თქვენი შვილი რამდენი წლისაა?" tacked on by the unrelated
    # `_ensure_camp_age_question` post-processor — that would confound the
    # side-by-side comparison with noise unrelated to the topic answer itself.
    conv.lead = Lead(
        sender_id=sender_id, platform=platform, segment="PARENT", child_age="12",
    )
    conversation_service.conversations[sender_id] = conv

    reply = conversation_service.process_message(sender_id, question["q"], platform)
    return reply or ""


def _result_row(question: dict, reply: str) -> dict:
    return {
        "id": question.get("id"),
        "topic": question.get("topic"),
        "bucket": question.get("bucket"),
        "source": question.get("source"),
        "question": question.get("q"),
        "reply": reply,
    }


def write_results_json(config: str, results: list[dict]) -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    # `baseline-live` IS the baseline for the report — write it to the baseline
    # path so `--compare` (which reads topic_review_baseline.json) uses the
    # faithful, engine-live baseline replies.
    file_config = "baseline" if config == "baseline-live" else config
    out_path = REPORTS_DIR / f"topic_review_{file_config}.json"
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def run_config(config: str) -> Path:
    """Drive every question in the review set through `config` and write
    tools/reports/topic_review_<config>.json. Caller is responsible for
    having already called `set_env_for_config` (before ANY app.* import)."""
    log = install_review_guard(config)
    reopen_camp_registration_for_run()

    from evals import safety

    questions = load_questions()
    results = [_result_row(q, drive_question(q, config)) for q in questions]
    out_path = write_results_json(config, results)

    print(f"\n[{config}] drove {len(results)} question(s) → {out_path}")
    print(safety.render_banner(
        log, llm_used=(config in _PAID_CONFIGS), httpx_blocked=(config not in _PAID_CONFIGS),
    ))
    return out_path


# ---------------------------------------------------------------------------
# baseline.json protection
# ---------------------------------------------------------------------------
def _md5_of(path: Path) -> str:
    if not path.exists():
        return "(missing)"
    return hashlib.md5(path.read_bytes()).hexdigest()


def run_and_report(config: str, *, yes: bool) -> int:
    if config in _PAID_CONFIGS:
        print(CAPABILITY_WARNING)
        if not yes:
            print(
                f"Refusing to run --config {config} without --yes "
                "(this makes REAL, PAID OpenAI calls). Re-run with --yes to proceed.",
            )
            return 1
        print(f"Proceeding with --config {config} (--yes given) — real OpenAI calls will be made.\n")

    md5_before = _md5_of(BASELINE_JSON_PATH)
    snapshot = BASELINE_JSON_PATH.read_bytes() if BASELINE_JSON_PATH.exists() else None

    # This runner never calls anything that writes evals/baseline.json (only
    # evals/harness.py::_report() does that, and only on a `run_all(llm=True)`
    # call — which this script never makes). Snapshot + restore is
    # belt-and-braces on top of that.
    set_env_for_config(config)  # MUST precede any app.* import — see module docstring.
    try:
        out_path = run_config(config)
    finally:
        if snapshot is not None:
            BASELINE_JSON_PATH.write_bytes(snapshot)
        elif BASELINE_JSON_PATH.exists():
            BASELINE_JSON_PATH.unlink()

    md5_after = _md5_of(BASELINE_JSON_PATH)
    print(f"\nevals/baseline.json md5 before run: {md5_before}")
    print(f"evals/baseline.json md5 after run:  {md5_after}")
    if md5_before != md5_after:
        print(
            "WARNING: evals/baseline.json md5 CHANGED during this run despite "
            "the snapshot/restore guard — investigate before trusting this report.",
        )
    print(f"[{config}] report written -> {out_path}")
    return 0


# ---------------------------------------------------------------------------
# --compare
# ---------------------------------------------------------------------------
def _md_cell(value) -> str:
    text = "" if value is None else str(value)
    text = text.replace("\r\n", "\n").replace("\n", "<br>")
    return text.replace("|", "\\|")


def build_compare_markdown(baseline: list[dict], capability: list[dict]) -> str:
    by_id_capability = {row.get("id"): row for row in capability}
    seen_ids = {row.get("id") for row in baseline}

    lines = [
        "# Capability #1 topic review — baseline vs capability",
        "",
        "- **baseline** = `USE_PROGRAM_TOPICS=false` (canned camp-topic interceptor, free/deterministic).",
        "- **capability** = `USE_PROGRAM_TOPICS=true` + `USE_PARENT_LLM_ENGINE=true` "
        "(LLM reasons over `get_program_topic`, real OpenAI).",
        "- Fill in **operator verdict** per row: `baseline` / `capability` / `tie`.",
        "",
        "| id | topic | bucket | question | baseline reply | capability reply | operator verdict |",
        "|---|---|---|---|---|---|---|",
    ]

    def _row(entry: dict, cap_entry: dict | None, missing_label: str) -> str:
        cap_reply = cap_entry.get("reply") if cap_entry is not None else missing_label
        cells = [
            _md_cell(entry.get("id")),
            _md_cell(entry.get("topic")),
            _md_cell(entry.get("bucket")),
            _md_cell(entry.get("question")),
            _md_cell(entry.get("reply") if "reply" in entry else missing_label),
            _md_cell(cap_reply),
            "",  # operator verdict — left blank for the operator to fill in
        ]
        return "| " + " | ".join(cells) + " |"

    for row in baseline:
        cap_row = by_id_capability.get(row.get("id"))
        missing = "(missing — run `--config capability`)"
        lines.append(_row(row, cap_row, missing))

    # Defensive: surface any capability-only question (should not normally
    # happen — both JSONs are driven from the same YAML — but never silently
    # drop a row the operator would otherwise never see).
    for qid, cap_row in by_id_capability.items():
        if qid in seen_ids:
            continue
        placeholder = {"id": qid, "topic": cap_row.get("topic"), "bucket": cap_row.get("bucket"),
                       "question": cap_row.get("question")}
        lines.append(_row(placeholder, cap_row, "(missing — run `--config baseline`)"))

    return "\n".join(lines) + "\n"


def run_compare() -> int:
    baseline_path = REPORTS_DIR / "topic_review_baseline.json"
    capability_path = REPORTS_DIR / "topic_review_capability.json"
    missing = [p for p in (baseline_path, capability_path) if not p.exists()]
    if missing:
        print("Cannot compare — missing report(s):")
        for p in missing:
            print(f"  {p}")
        print("Run --config baseline and --config capability first.")
        return 1

    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    capability = json.loads(capability_path.read_text(encoding="utf-8"))
    markdown = build_compare_markdown(baseline, capability)

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = REPORTS_DIR / "topic_review_compare.md"
    out_path.write_text(markdown, encoding="utf-8")
    print(f"[compare] wrote {out_path}")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description=(
            "Review runner for Capability #1 (camp-topic facts tool, "
            "USE_PROGRAM_TOPICS). Drives evals/review_topic_questions_2026_07_22.yaml "
            "through the agent in baseline (flag off, free) or capability "
            "(flag on, PAID real OpenAI) config, or renders a side-by-side "
            "compare markdown for operator judgement."
        ),
    )
    ap.add_argument(
        "--config", choices=("baseline", "baseline-live", "capability"),
        help=(
            "drive every question in this config once and write "
            "tools/reports/topic_review_<config>.json. baseline = flag off, free "
            "(varied misses fall to the free legacy path — understates 'today'). "
            "baseline-live = flag off but OpenAI ALLOWED so varied misses reach "
            "the real engine-without-tool (faithful 'today', PAID --yes; writes "
            "the baseline report). capability = flag on, PAID --yes."
        ),
    )
    ap.add_argument(
        "--compare", action="store_true",
        help="read both JSONs and emit tools/reports/topic_review_compare.md",
    )
    ap.add_argument(
        "--yes", action="store_true",
        help=(
            "required to actually run --config capability (makes REAL, PAID "
            "OpenAI calls); no-op for --config baseline / --compare"
        ),
    )
    return ap


def _print_usage(ap: argparse.ArgumentParser) -> None:
    ap.print_help()
    print(
        "\nExamples:\n"
        "  .venv/Scripts/python.exe tools/review_topic_capability.py --config baseline --yes\n"
        "  .venv/Scripts/python.exe tools/review_topic_capability.py --config capability --yes   # PAID\n"
        "  .venv/Scripts/python.exe tools/review_topic_capability.py --compare\n",
    )


def main(argv: list[str] | None = None) -> int:
    ap = _build_arg_parser()
    args = ap.parse_args(argv)

    if args.compare:
        return run_compare()
    if args.config:
        return run_and_report(args.config, yes=args.yes)

    _print_usage(ap)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
