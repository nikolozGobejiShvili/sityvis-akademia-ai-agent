"""Eval runner: drives cases, scores per-dimension, prints failures + banner.

Two check kinds:
  * code  — objective, deterministic assertions (intent / entity / segment /
            tool-call+args / follow-up decision). Cheap & exact.
  * judge — Claude binary rubric for nuanced response quality.

The harness is READ-ONLY (see evals.safety). Deterministic cases need no LLM;
full_turn / judge cases self-skip unless --llm / --judge are enabled.
"""
from __future__ import annotations

import dataclasses
import os
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

from evals import safety

TBILISI = ZoneInfo("Asia/Tbilisi")
DIMENSIONS = ("understanding", "extraction", "routing", "response_quality", "followup")


# ── result model ─────────────────────────────────────────────────────────────
@dataclass
class Check:
    name: str
    passed: bool
    expected: str
    actual: str


@dataclass
class CaseOutcome:
    checks: list[Check] = field(default_factory=list)
    skipped: bool = False
    skip_reason: str = ""


@dataclass
class EvalCase:
    id: str
    dimension: str
    title: str
    source: str
    run: Callable[["Harness"], CaseOutcome]
    # stochastic = drives the real LLM (engine turn / judge). When the LLM is
    # enabled it is run best-of-N and each check is decided by MAJORITY vote so
    # the baseline number is stable across runs.
    stochastic: bool = False


# Best-of-N for stochastic LLM cases.
_LLM_REPEAT = 3


def _majority_vote(outcomes: list[CaseOutcome]) -> CaseOutcome:
    """Aligns checks by index across N runs; each check passes if it passed in a
    MAJORITY of runs. `actual` carries the vote tally + a representative sample."""
    real = [o for o in outcomes if not o.skipped]
    if not real:
        return outcomes[0]
    n_checks = max(len(o.checks) for o in real)
    agg: list[Check] = []
    for i in range(n_checks):
        votes = [o.checks[i] for o in real if i < len(o.checks)]
        npass = sum(1 for c in votes if c.passed)
        majority_pass = npass * 2 >= len(votes)        # ties → pass (odd N: no ties)
        rep = next((c for c in votes if c.passed == majority_pass), votes[0])
        agg.append(Check(
            name=rep.name, passed=majority_pass, expected=rep.expected,
            actual=f"[{npass}/{len(votes)} runs passed] sample: {rep.actual}",
        ))
    return CaseOutcome(agg)


def chk(name: str, passed: bool, expected: Any, actual: Any) -> Check:
    return Check(name=name, passed=bool(passed), expected=str(expected), actual=str(actual))


# ── harness (driver the cases use) ───────────────────────────────────────────
class Harness:
    def __init__(self, log: safety.SideEffectLog, *, llm_enabled: bool, judge_enabled: bool):
        self.log = log
        self.llm_enabled = llm_enabled
        self.judge_enabled = judge_enabled
        self.last_tool_calls: list[tuple[str, dict]] = []
        self.engine_invocations: int = 0
        self.current_case_id: str = ""
        self.responses: list[tuple[str, str, str]] = []   # (case_id, user_msg, agent reply)
        self._install_tool_recorder()

    # -- conversation seeding -------------------------------------------------
    def seed(self, *, sender_id: str | None = None, segment: str = "PARENT",
             state: str = "ASK_CHALLENGE", platform: str = "instagram",
             history: list[dict] | None = None, **lead_fields: Any):
        from app.models.conversation import Conversation
        from app.models.lead import Lead
        from app.services import conversation_service
        sid = sender_id or f"eval-{abs(hash((segment, state, str(lead_fields)))) % 10**8}"
        conv = Conversation(sender_id=sid, platform=platform, segment=segment)
        conv.state = state
        for turn in (history or []):
            conv.history.append(turn)
        conv.lead = Lead(sender_id=sid, platform=platform, segment=segment, **lead_fields)
        conversation_service.conversations[sid] = conv
        return conv

    def seed_followup(self, *, stage: str = "", booked: bool = False, blocked: str = ""):
        """Seed a follow-up scenario: returns (conversation, t0) where t0 is the
        frozen `last_bot_message_at` anchor (Tbilisi)."""
        t0 = datetime(2026, 6, 29, 10, 0, tzinfo=TBILISI)
        conv = self.seed(segment="PARENT", state="DONE", platform="messenger",
                         calendly_booked=booked)
        conv.last_bot_message_at = t0.isoformat()
        conv.followup_stage = stage
        conv.followup_blocked_reason = blocked
        return conv, t0

    # -- full turn (real engine; records tool calls) --------------------------
    def process(self, conv, message: str) -> str:
        from app.services import conversation_service
        self.last_tool_calls = []
        self.engine_invocations = 0
        reply = self._process_with_engine_spy(conversation_service, conv, message)
        # Capture every agent reply (+ the user turn that triggered it) for the
        # separate Georgian-grammar and naturalness evaluators.
        if reply and reply.strip():
            self.responses.append((self.current_case_id, message, reply))
        return reply

    def _process_with_engine_spy(self, conversation_service, conv, message: str) -> str:
        # Engine-reach counter (Task 1, anti-confound guard): wrap the SAME
        # target `_install_engine_spy` in evals/interception.py patches
        # (`parent_llm_engine.run_parent_llm_turn` on the module object) —
        # `parent_flow.handle` re-imports it fresh on every call, so patching
        # the module attribute is observed at call time. This wrap COUNTS then
        # DELEGATES to the real function (never replaces it), so the engine
        # still actually runs under `--llm`; offline (no --llm) a deterministic
        # interceptor short-circuits before the engine is ever reached, so the
        # real function underneath is never invoked either way in offline tests.
        import app.agent.llm.parent_llm_engine as _ple
        _orig_run = _ple.run_parent_llm_turn

        def _counting_run(*a, **k):
            self.engine_invocations += 1
            return _orig_run(*a, **k)

        _ple.run_parent_llm_turn = _counting_run
        try:
            return conversation_service.process_message(conv.sender_id, message, conv.platform)
        finally:
            _ple.run_parent_llm_turn = _orig_run

    def _install_tool_recorder(self) -> None:
        from app.agent.tools.parent_tool_executor import ParentToolExecutor
        if getattr(ParentToolExecutor, "_eval_wrapped", False):
            ParentToolExecutor._eval_harness = self  # type: ignore[attr-defined]
            return
        original = ParentToolExecutor.execute

        def wrapped(self_exec, tool_name, tool_args):
            h = getattr(ParentToolExecutor, "_eval_harness", None)
            if h is not None:
                h.last_tool_calls.append((tool_name, dict(tool_args or {})))
            return original(self_exec, tool_name, tool_args)

        ParentToolExecutor.execute = wrapped            # type: ignore[assignment]
        ParentToolExecutor._eval_wrapped = True         # type: ignore[attr-defined]
        ParentToolExecutor._eval_harness = self         # type: ignore[attr-defined]

    # -- follow-up decision (mocked clock; no real send) ----------------------
    def followup_decide(self, conv, now: datetime) -> tuple[str, dict | None]:
        from app.services import followup_service
        before = self.log.count("outbound_dm")
        result = followup_service._maybe_send_followup_for_conversation(conv, now)
        sent = None
        if self.log.count("outbound_dm") > before:
            sent = self.log.intercepted["outbound_dm"][-1]
        return result, sent

    # -- judge ----------------------------------------------------------------
    def judge(self, context: str, criteria: list[str]) -> list[tuple[str, bool, str]]:
        from evals import judge as judge_mod
        return judge_mod.judge(context, criteria)


# ── runner + scoring + report ────────────────────────────────────────────────
def run_all(*, llm: bool, judge: bool, category: str | None = None,
            case_id: str | None = None) -> int:
    from evals.cases import CASES

    log = safety.SideEffectLog()
    safety.install_readonly(log, block_httpx=not llm)

    judge_enabled = judge
    judge_note = ""
    if judge:
        from evals import judge as judge_mod
        ok, why = judge_mod.judge_available()
        if not ok:
            judge_enabled = False
            judge_note = f" (judge requested but disabled: {why})"

    h = Harness(log, llm_enabled=llm, judge_enabled=judge_enabled)

    cases = [c for c in CASES if (not category or c.dimension == category)
             and (not case_id or c.id == case_id)]

    repeat_llm = (llm or judge_enabled)
    results: list[tuple[EvalCase, CaseOutcome, int]] = []
    for case in cases:
        h.current_case_id = case.id
        reps = _LLM_REPEAT if (case.stochastic and repeat_llm) else 1
        runs: list[CaseOutcome] = []
        for _ in range(reps):
            try:
                runs.append(case.run(h))
            except Exception as exc:  # never let one case crash the run
                runs.append(CaseOutcome(checks=[chk(
                    "CASE ERROR", False, "no exception",
                    f"{type(exc).__name__}: {exc}\n{traceback.format_exc(limit=2)}")]))
            if runs[-1].skipped:      # a skip won't change on repeat
                break
        if runs[0].skipped or len(runs) == 1:
            outcome = runs[0]
        else:
            outcome = _majority_vote(runs)
        results.append((case, outcome, len(runs)))

    grammar = _grade_grammar(h, llm=llm, judge_requested=judge, judge_enabled=judge_enabled)
    naturalness = _grade_naturalness(h, llm=llm, judge_requested=judge, judge_enabled=judge_enabled)

    return _report(results, log, grammar, naturalness, llm=llm, judge_requested=judge,
                   judge_enabled=judge_enabled, judge_note=judge_note)


def _grade_grammar(h: "Harness", *, llm: bool, judge_requested: bool, judge_enabled: bool) -> dict:
    """Run the SEPARATE Georgian-grammar judge over every captured agent reply.
    Returns a summary dict with a `status` that drives the report label."""
    g = {"status": "", "passed": 0, "total": 0, "replies": 0, "errors": 0, "blocks": []}
    if not llm:
        g["status"] = "N/A (needs --llm)"
        return g
    if not judge_requested:
        g["status"] = "N/A (needs --judge)"
        return g
    if not judge_enabled:
        g["status"] = "JUDGE-SKIPPED (no ANTHROPIC_API_KEY)"
        return g

    from evals import judge as judge_mod
    seen: set[str] = set()       # one representative reply per case (bounds cost)
    for cid, _msg, text in h.responses:
        if cid in seen or not text.strip():
            continue
        seen.add(cid)
        try:
            graded = judge_mod.grade_grammar(text)
        except Exception as exc:
            g["errors"] += 1
            g["blocks"].append(f"  🇬🇪 GRAMMAR ERROR — [{cid}]: {type(exc).__name__}: {exc}")
            continue
        g["replies"] += 1
        g["passed"] += sum(1 for c in graded if c["pass"])
        g["total"] += len(graded)
        block = judge_mod.render_grammar_issues(cid, text, graded)
        if block:
            g["blocks"].append(block)
    g["status"] = "scored"
    return g


def _grade_naturalness(h: "Harness", *, llm: bool, judge_requested: bool, judge_enabled: bool) -> dict:
    """Run the SEPARATE naturalness judge (bot-vs-human) over one representative
    agent reply per case, using the SAME OpenAI/Anthropic judge backend as the
    grammar grader. `score_sum`/`replies` give the mean 0-4 naturalness; `blocks`
    the per-case templated-tell issues. Same gating + one-reply-per-case cost
    bound as `_grade_grammar`. A per-case SKIP (judge unavailable / every N-run
    dropped) is counted, never scored as a fake 0."""
    n = {"status": "", "score_sum": 0, "replies": 0, "skipped": 0, "blocks": []}
    if not llm:
        n["status"] = "N/A (needs --llm)"
        return n
    if not judge_requested:
        n["status"] = "N/A (needs --judge)"
        return n
    if not judge_enabled:
        n["status"] = "JUDGE-SKIPPED (judge unavailable)"
        return n

    from evals import naturalness as naturalness_mod
    seen: set[str] = set()       # one representative reply per case (bounds cost)
    for cid, msg, text in h.responses:
        if cid in seen or not text.strip():
            continue
        seen.add(cid)
        result = naturalness_mod.grade_naturalness(msg, text)
        score = result.get("score")
        if score is None:          # explicit SKIP — never a fake 0
            n["skipped"] += 1
            continue
        n["replies"] += 1
        n["score_sum"] += score
        if result.get("issues"):
            lines = "\n".join(f"     • {iss}" for iss in result["issues"])
            n["blocks"].append(f"  🤖 NATURALNESS — [{cid}] {score}/4\n{lines}")
    n["status"] = "scored" if n["replies"] else "JUDGE-SKIPPED (all runs skipped)"
    return n


_INTELLIGENCE_DIMS = ("understanding", "routing", "response_quality")
_MECHANICS_DIMS = ("extraction", "followup")


def _report(results, log, grammar: dict, naturalness: dict, *, llm: bool, judge_requested: bool,
            judge_enabled: bool, judge_note: str) -> int:
    per_dim: dict[str, list[int]] = {d: [0, 0] for d in DIMENSIONS}   # [passed, total]
    total_passed = total_checks = 0
    skipped: list[tuple[EvalCase, str]] = []
    failed: list[tuple[EvalCase, list[Check], int]] = []

    for case, outcome, reps in results:
        if outcome.skipped:
            skipped.append((case, outcome.skip_reason))
            continue
        p = sum(1 for c in outcome.checks if c.passed)
        t = len(outcome.checks)
        per_dim[case.dimension][0] += p
        per_dim[case.dimension][1] += t
        total_passed += p
        total_checks += t
        bad = [c for c in outcome.checks if not c.passed]
        if bad:
            failed.append((case, bad, reps))

    mode = ("full (real OpenAI" + (" + LLM judge)" if judge_enabled else ")")) if llm \
        else ("deterministic-only — free, no LLM" + (" + LLM judge" if judge_enabled else ""))
    pct = (100 * total_passed / total_checks) if total_checks else 0.0

    def grp(dims):
        p = sum(per_dim[d][0] for d in dims)
        t = sum(per_dim[d][1] for d in dims)
        return p, t

    print("\n" + "═" * 64)
    print(f"  AGENT UNDERSTANDING EVAL   ·   mode: {mode}{judge_note}")
    print("═" * 64)
    print(f"  SCORE: {total_passed}/{total_checks} checks  ({pct:.0f}/100)   "
          f"·   {len(results) - len(skipped)} cases run, {len(skipped)} skipped")
    if llm or judge_enabled:
        print(f"  (LLM cases scored best-of-{_LLM_REPEAT} by majority vote)")

    # ── three separate score blocks (Part C) ──
    ip, it = grp(_INTELLIGENCE_DIMS)
    mp, mt = grp(_MECHANICS_DIMS)
    intel_tag = "(full)" if llm else "(partial — needs --llm)"
    print("\n  ── SCORES ──")
    print(f"  🧠 AGENT INTELLIGENCE   {ip}/{it:<3} ({(100*ip/it if it else 0):.0f}%)   "
          f"[understanding + routing + response_quality]   {intel_tag}")
    print(f"  ⚙️  MECHANICS            {mp}/{mt:<3} ({(100*mp/mt if mt else 0):.0f}%)   "
          f"[extraction + followup logic]")
    if grammar["status"] == "scored":
        gp, gt, gr = grammar["passed"], grammar["total"], grammar["replies"]
        gpct = f"{(100*gp/gt if gt else 0):.0f}%"
        print(f"  🇬🇪 GEORGIAN GRAMMAR     {gp}/{gt:<3} ({gpct})   "
              f"[6 criteria × {gr} graded replies]")
    else:
        print(f"  🇬🇪 GEORGIAN GRAMMAR     {grammar['status']}")
    if naturalness["status"] == "scored":
        nr = naturalness["replies"]
        nmean = naturalness["score_sum"] / nr if nr else 0.0
        print(f"  🤖 NATURALNESS          {nmean:.2f}/4   "
              f"[bot-vs-human × {nr} graded replies]")
    else:
        print(f"  🤖 NATURALNESS          {naturalness['status']}")

    print("\n  By dimension:")
    for d in DIMENSIONS:
        p, t = per_dim[d]
        bar = f"{p}/{t}" if t else "—/—"
        dpct = f"{100*p/t:.0f}%" if t else "n/a"
        print(f"    {d:<18} {bar:>7}   ({dpct})")

    if failed:
        print("\n" + "─" * 64)
        print("  FAILED CASES")
        print("─" * 64)
        for case, bad, reps in failed:
            vote = f"  (best-of-{reps})" if reps > 1 else ""
            print(f"\n  [{case.id}] {case.dimension} · {case.title}{vote}")
            print(f"     source:   {case.source}")
            for c in bad:
                print(f"     ✗ check:   {c.name}")
                print(f"        expected: {c.expected}")
                print(f"        actual:   {c.actual}")
    else:
        print("\n  ✅ no failed checks.")

    if skipped:
        print("\n  SKIPPED (enable with the noted flag):")
        for case, reason in skipped:
            print(f"     [{case.id}] {case.dimension} · {case.title} — {reason}")

    # ── Georgian grammar issues (Part B) ──
    if grammar["blocks"]:
        print("\n" + "─" * 64)
        print("  🇬🇪 GEORGIAN GRAMMAR — DETECTED ISSUES")
        print("─" * 64)
        for block in grammar["blocks"]:
            print("\n" + block)
    elif grammar["status"] == "scored":
        print("\n  🇬🇪 no grammar issues found in the graded replies.")

    # ── naturalness templated-tells (stdout only — never written to baseline.json) ──
    if naturalness["blocks"]:
        print("\n" + "─" * 64)
        print("  🤖 NATURALNESS — TEMPLATED TELLS (lower = more botlike)")
        print("─" * 64)
        for block in naturalness["blocks"]:
            print("\n" + block)
    elif naturalness["status"] == "scored":
        print("\n  🤖 no templated tells found in the graded replies.")

    print("\n" + "═" * 64)
    print(safety.render_banner(log, llm_used=llm or judge_enabled, httpx_blocked=not llm))
    print("═" * 64 + "\n")

    # ── persist baseline.json on a FULL run (Part E) ──
    summary = {
        "mode": mode,
        "checks": {"passed": total_passed, "total": total_checks,
                   "score_100": round(pct)},
        "intelligence": {"passed": ip, "total": it, "tag": intel_tag.strip("()")},
        "mechanics": {"passed": mp, "total": mt},
        "grammar": {"status": grammar["status"], "passed": grammar["passed"],
                    "total": grammar["total"], "graded_replies": grammar["replies"],
                    "errors": grammar["errors"]},
        "by_dimension": {d: {"passed": per_dim[d][0], "total": per_dim[d][1]} for d in DIMENSIONS},
        "failed_cases": [c.id for c, _b, _r in failed],
        "skipped_cases": [c.id for c, _r in skipped],
        "readonly": {"live_calls": log.live_total(),
                     "intercepted": {k: len(v) for k, v in log.intercepted.items()}},
    }
    if llm:   # the real-engine baseline (grammar filled once a Claude key is set)
        import json
        from datetime import datetime
        summary["generated_at"] = datetime.now().isoformat(timespec="seconds")
        path = Path(__file__).resolve().parent / "baseline.json"
        path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  📄 baseline written → {path}\n")

    # Exit non-zero if any check failed OR a tripwire was hit.
    return 1 if (failed or log.live_total() > 0) else 0
