"""Persona-driven multi-turn conversation SIMULATION driver + scorer + report.

EXTENDS the existing `evals/` infrastructure (reuses `Harness`, `safety`,
`judge`, `conversation_trace`, `admin_config_service`). A diverse set of Georgian
personas (`evals.personas`) converse with the REAL engine
(`conversation_service.process_message` via `Harness.process`); each conversation
is scored on FIVE components and gated by HARD invariants, then a report is
produced.

EVAL-ONLY — this module changes NO agent behaviour. READ-ONLY is enforced by
`evals.safety` in the live orchestrator (`run_all`); every real side effect is a
recording dry-run stub.

The FIVE score components and where each reads from:
  (1) quality    — `Harness.judge` (Claude binary rubric) over persona.success_criteria
  (2) template   — approved fact tokens from `admin_config_service` (price / link /
                   manager phone / installments) → "used template" vs "improvised"
  (3) handler    — the per-turn `conversation_trace` block (route / answered_by /
                   handler) → deterministic handler vs engine fallthrough
  (4) grammar    — `evals.judge.grade_grammar` (the SAME Georgian-grammar evaluator
                   the base harness runs) on every agent reply
  (5) invariants — HARD checks on every reply (phone-echo / age-reask / adult-misroute)

The driver is fully INJECTABLE (`SimDeps`) so the harness self-tests can drive a
scripted conversation with NO live LLM.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable

from evals import personas as personas_mod
from evals import safety
from evals import user_sim
from evals.personas import PERSONAS, Persona, get_persona


# ═══════════════════════════ PURE CHECK HELPERS ═══════════════════════════════
# All deterministic + side-effect-free so they can be unit-tested directly and
# reused by the driver.

def _child_age_int(lead: Any) -> int | None:
    if lead is None:
        return None
    m = re.search(r"\d{1,2}", str(getattr(lead, "child_age", "") or ""))
    return int(m.group()) if m else None


# ── (2) template / rule adherence ─────────────────────────────────────────────
_PRICE_RE = re.compile(r"ფას|რა\s*ღირს|ღირს|რამდენი\s*ჯდება|ღირებულებ|თანხა")
_INSTALL_RE = re.compile(r"გადანაწილ|განვად|ნაწილ.?ნაწილ|თვემდე|\d+\s*თვე")
_REG_RE = re.compile(r"რეგისტრაცი|ბმულ|ლინკ|დარეგისტრ|link")
_MANAGER_RE = re.compile(r"მენეჯერ")
_MANAGER_CONTACT_RE = re.compile(r"ნომერ|ტელეფონ|კონტაქტ|დარეკ")


def detect_template_intent(user_msg: str) -> str | None:
    """Map a user turn to a canonical template, or None. Order = most specific
    first. Deliberately avoids the ``ინფორმაცია`` ⊃ ``ფორმა`` false-positive by
    NOT keying registration on a bare „ფორმა" token."""
    m = user_msg or ""
    if _REG_RE.search(m):
        return "registration"
    if _MANAGER_RE.search(m) and _MANAGER_CONTACT_RE.search(m):
        return "manager"
    if _INSTALL_RE.search(m):
        return "installment"
    if _PRICE_RE.search(m):
        return "price"
    return None


def template_satisfied(intent: str, reply: str, facts: dict[str, Any]) -> bool:
    """True when the reply contains the approved fact token for this intent
    (i.e. the engine "used the template"); False = it improvised."""
    r = reply or ""
    if intent == "price":
        pg = facts.get("price_gel")
        return bool(pg) and str(pg) in r
    if intent == "installment":
        return any(t in r for t in ("გადანაწილ", "განვად", "6 თვე", "თვემდე"))
    if intent == "registration":
        url = (facts.get("registration_url") or "").strip()
        return bool(url) and url in r
    if intent == "manager":
        ph = re.sub(r"\D", "", facts.get("manager_phone") or "")
        return bool(ph) and re.search(r"[\s\-]*".join(ph), r) is not None
    return True


# ── (5) hard invariants ───────────────────────────────────────────────────────
_AGE_Q_RE = re.compile(r"რამდენი\s*წლ|რა\s*ასაკის|შვილი\s*რამდენი|ბავშვი\s*რამდენი|რამდენი\s*წელ")
_NEW_CHILD_RE = re.compile(
    r"მეორე\s*(შვილ|ბავშ)|სხვა\s*(შვილ|ბავშ)|კიდევ\s*ერთ.{0,4}(შვილ|ბავშ)"
    r"|ორივე\s*(შვილ|ბავშ)|ორი\s*(შვილ|ბავშ)")
# Adult-misroute marker anchored on „ზრდასრულთა" so it never false-fires on the
# camp flow's legitimate „მონაწილეობა" (participation) wording. The spec lists
# „ზრდასრულთა ღონისძიებ" / „მონაწილე"; a BARE „მონაწილე" would flag nearly every
# camp reply, so we require the adult anchor.
_ADULT_MISROUTE_RE = re.compile(r"ზრდასრულთა\s*ღონისძიებ|ზრდასრულთა[^.\n]{0,40}მონაწილ")


def check_invariants(
    persona: Persona, user_msg: str, reply: str,
    age_before: int | None, lead_after: Any,
) -> list[str]:
    """Return the list of HARD invariant breaches for one reply. Empty = clean.
    Categories: invariant_leak (phone echo) / age_reask / adult_misroute."""
    breaches: list[str] = []
    r = reply or ""

    # user's OWN phone must never be echoed in clear (masked „595***733" is OK).
    ph = re.sub(r"\D", "", getattr(lead_after, "phone", "") or "") if lead_after else ""
    if len(ph) >= 9 and re.search(r"[\s\-]*".join(ph), r):
        breaches.append("invariant_leak")

    age_after = _child_age_int(lead_after)

    # known child_age (9–17) already on record → the age must NOT be re-asked.
    # Excused when the user just introduced a NEW/second child, or for personas
    # that legitimately juggle two ages (multi_child).
    if (not persona.allow_age_questions) and age_before is not None and 9 <= age_before <= 17:
        if _AGE_Q_RE.search(r) and not _NEW_CHILD_RE.search(user_msg or ""):
            breaches.append("age_reask")

    # known child_age (9–17) → NO adult-events phrasing (that is a misroute).
    if age_after is not None and 9 <= age_after <= 17 and _ADULT_MISROUTE_RE.search(r):
        breaches.append("adult_misroute")

    return breaches


def reply_answers_off_topic(persona: Persona, reply: str) -> bool:
    """Deterministic gate for the controlled off_topic persona: True if the reply
    STATES an off-topic answer (e.g. the math result). Redirect/decline replies
    never contain it, so they score as a (correct) refusal."""
    r = reply or ""
    for probe in persona.off_topic_probes:
        ar = probe.get("answer_re")
        if ar and re.search(ar, r):
            return True
    return False


# ── (3) handler identity from the trace block ─────────────────────────────────
def handler_label(block: dict | None) -> str:
    if not block:
        return "(no-trace)"
    if block.get("handler"):
        return str(block["handler"])
    if block.get("answered_by"):
        return str(block["answered_by"])
    route = block.get("route")
    return f"{route}:deterministic" if route == "parent_flow" else str(route or "unknown")


def handler_kind(block: dict | None) -> str:
    if not block:
        return "no-trace"
    ans, route = block.get("answered_by"), block.get("route")
    if ans == "parent_llm_engine":
        return "engine"
    if ans == "legacy_state_machine":
        return "legacy"
    if route == "adult_flow":
        return "adult"
    if route in ("parent_flow", "greeting_after_decline"):
        return "deterministic"
    if route == "unclear_routing":
        return "unclear"
    return str(route or "unknown")


# ═══════════════════════════════ DATA MODEL ═══════════════════════════════════
@dataclass
class TurnRecord:
    index: int
    user: str
    reply: str
    route: str = ""
    handler: str = ""
    handler_kind: str = ""
    template_intent: str | None = None
    template_ok: bool | None = None       # None = no template intent this turn
    grammar_ok: bool | None = None        # None = not graded
    grammar_issues: str = ""
    breaches: list[str] = field(default_factory=list)


@dataclass
class ConversationResult:
    persona_id: str
    label: str
    in_domain: bool
    sender_id: str
    turns: list[TurnRecord] = field(default_factory=list)
    criteria: list[tuple[str, bool | None, str]] = field(default_factory=list)
    passed: bool = False
    failure_types: set[str] = field(default_factory=set)
    answered_off_topic: bool = False
    adult_route_seen: bool = False
    errored: bool = False
    error: str = ""


@dataclass
class SimDeps:
    """Injectable seam bundling every external dependency of the driver so the
    self-tests can run a scripted conversation with NO live LLM / engine."""
    seed_fn: Callable[[str], Any]
    process_fn: Callable[[Any, str], str]
    trace_reset: Callable[[], None]
    trace_read: Callable[[], dict | None]
    user_responder: Callable[..., str | None]
    judge_fn: Callable[[str, list[str]], list[tuple[str, bool, str]]] | None
    grammar_fn: Callable[[str], list[dict]] | None
    facts: dict[str, Any]
    max_grammar_turns: int = 0            # 0 = grade every reply

    @classmethod
    def live(cls, harness, facts: dict[str, Any], *, judge_enabled: bool,
             max_grammar_turns: int = 0) -> "SimDeps":
        from app.reasoning import conversation_trace as tr
        from evals import judge as judge_mod

        def _trace_read() -> dict | None:
            hist = tr.history()
            return hist[-1] if hist else None

        return cls(
            seed_fn=lambda sid: harness.seed(sender_id=sid, segment="PARENT", state="START"),
            process_fn=lambda conv, msg: harness.process(conv, msg),
            trace_reset=tr.reset_history,
            trace_read=_trace_read,
            user_responder=user_sim.next_user_message,
            judge_fn=(harness.judge if judge_enabled else None),
            grammar_fn=(judge_mod.grade_grammar if judge_enabled else None),
            facts=facts,
            max_grammar_turns=max_grammar_turns,
        )


# ═══════════════════════════════ THE DRIVER ═══════════════════════════════════
def _transcript_text(transcript: list[dict[str, str]]) -> str:
    lines = []
    for t in transcript:
        who = "მომხმარებელი" if t["role"] == "user" else "აგენტი"
        lines.append(f"{who}: {t['content']}")
    return "\n".join(lines)


def run_conversation(persona: Persona, sender_id: str, deps: SimDeps) -> ConversationResult:
    """Drive ONE persona conversation end-to-end and score it. Never raises — a
    user_sim / engine failure marks the conversation errored and returns."""
    res = ConversationResult(persona_id=persona.id, label=persona.label,
                             in_domain=persona.in_domain, sender_id=sender_id)
    transcript: list[dict[str, str]] = []
    try:
        deps.trace_reset()
        conv = deps.seed_fn(sender_id)
    except Exception as exc:  # seeding must never crash the batch
        res.errored = True
        res.error = f"seed: {type(exc).__name__}: {exc}"
        res.failure_types.add("other")
        return res

    for i in range(persona.max_turns):
        try:
            user_msg = deps.user_responder(persona, transcript, deps.facts, turn_index=i)
        except Exception as exc:
            res.errored = True
            res.error = f"user_sim turn {i}: {type(exc).__name__}: {exc}"
            break
        if not user_msg:
            break
        transcript.append({"role": "user", "content": user_msg})

        age_before = _child_age_int(getattr(conv, "lead", None))
        try:
            reply = deps.process_fn(conv, user_msg)
        except Exception as exc:
            res.errored = True
            res.error = f"engine turn {i}: {type(exc).__name__}: {exc}"
            res.turns.append(TurnRecord(index=i, user=user_msg, reply="",
                                        handler="(engine-error)", handler_kind="error"))
            break
        reply = reply or ""
        transcript.append({"role": "assistant", "content": reply})

        try:
            block = deps.trace_read()
        except Exception:
            block = None
        lead_after = getattr(conv, "lead", None)

        rec = TurnRecord(
            index=i, user=user_msg, reply=reply,
            route=str((block or {}).get("route") or ""),
            handler=handler_label(block), handler_kind=handler_kind(block),
        )
        if rec.handler_kind == "adult":
            res.adult_route_seen = True
        rec.template_intent = detect_template_intent(user_msg)
        if rec.template_intent:
            rec.template_ok = template_satisfied(rec.template_intent, reply, deps.facts)
        rec.breaches = check_invariants(persona, user_msg, reply, age_before, lead_after)
        if (not persona.in_domain) and reply_answers_off_topic(persona, reply):
            res.answered_off_topic = True

        res.turns.append(rec)
        if rec.breaches:      # hard breach → stop early (cost + clarity)
            break

    # ── (4) grammar — the SAME evaluator on every agent reply ──
    if deps.grammar_fn is not None:
        graded = 0
        for rec in res.turns:
            if not rec.reply.strip():
                continue
            if deps.max_grammar_turns and graded >= deps.max_grammar_turns:
                rec.grammar_issues = "(grammar skipped — max_grammar_turns cap)"
                continue
            try:
                out = deps.grammar_fn(rec.reply)
            except Exception as exc:
                rec.grammar_issues = f"(grammar error: {type(exc).__name__}: {exc})"
                continue
            graded += 1
            failing = [g for g in out if not g.get("pass", True)]
            rec.grammar_ok = not failing
            if failing:
                from evals import judge as judge_mod
                rec.grammar_issues = judge_mod.render_grammar_issues(
                    f"{persona.id}:t{rec.index}", rec.reply, out)

    # ── (1) quality — judge the whole transcript against success_criteria ──
    if deps.judge_fn is None:
        res.criteria = [(c, None, "JUDGE-SKIPPED") for c in persona.success_criteria]
    elif res.errored:
        res.criteria = [(c, None, "skipped (errored)") for c in persona.success_criteria]
    else:
        try:
            res.criteria = list(deps.judge_fn(_transcript_text(transcript),
                                              list(persona.success_criteria)))
        except Exception as exc:
            res.criteria = [(c, False, f"judge-error: {type(exc).__name__}: {exc}")
                            for c in persona.success_criteria]

    _finalize(persona, res)
    return res


def _finalize(persona: Persona, res: ConversationResult) -> None:
    """Compute failure_types + the PASS verdict from the recorded turns."""
    for rec in res.turns:
        for b in rec.breaches:
            res.failure_types.add(b)          # adult_misroute / age_reask / invariant_leak
    grammar_failed = any(rec.grammar_ok is False for rec in res.turns)
    if grammar_failed:
        res.failure_types.add("grammar")
    if any(rec.template_ok is False for rec in res.turns):
        res.failure_types.add("template_missed")   # informational — does NOT gate
    criteria_failed = any(p is False for _c, p, _r in res.criteria)
    if criteria_failed or res.errored:
        res.failure_types.add("other")
    if (not persona.in_domain) and res.answered_off_topic:
        res.failure_types.add("answered_off_topic")

    hard_breach = bool(res.failure_types & {"adult_misroute", "age_reask", "invariant_leak"})
    res.passed = (
        not res.errored
        and not hard_breach
        and not grammar_failed
        and not criteria_failed
        and not ((not persona.in_domain) and res.answered_off_topic)
    )


def run_batch(personas: list[Persona], runs: int, deps: SimDeps) -> list[ConversationResult]:
    """Run every persona × N runs. One conversation's failure never stops the
    batch (run_conversation already contains its own errors)."""
    results: list[ConversationResult] = []
    for persona in personas:
        for r in range(runs):
            sid = f"sim-{persona.id}-r{r}"
            results.append(run_conversation(persona, sid, deps))
    return results


# ═══════════════════════════════ AGGREGATION ══════════════════════════════════
_FAILURE_CATEGORIES = (
    "adult_misroute", "age_reask", "template_missed", "grammar",
    "invariant_leak", "answered_off_topic", "other",
)


@dataclass
class Report:
    total: int = 0
    passed: int = 0
    failed: int = 0
    errored: int = 0
    in_domain_total: int = 0
    in_domain_passed: int = 0
    off_topic_total: int = 0
    off_topic_passed: int = 0
    pass_rate: float = 0.0
    in_domain_pass_rate: float = 0.0
    off_topic_refuse_rate: float = 0.0
    failure_tally: dict[str, int] = field(default_factory=dict)
    per_persona: dict[str, tuple[int, int]] = field(default_factory=dict)
    template_improvised_turns: int = 0


def summarize(results: list[ConversationResult]) -> Report:
    rep = Report(total=len(results))
    rep.failure_tally = {c: 0 for c in _FAILURE_CATEGORIES}
    per: dict[str, list[int]] = {}
    for res in results:
        rep.passed += 1 if res.passed else 0
        rep.errored += 1 if res.errored else 0
        if res.in_domain:
            rep.in_domain_total += 1
            rep.in_domain_passed += 1 if res.passed else 0
        else:
            rep.off_topic_total += 1
            rep.off_topic_passed += 1 if res.passed else 0
        for cat in _FAILURE_CATEGORIES:
            if cat in res.failure_types:
                rep.failure_tally[cat] += 1
        rep.template_improvised_turns += sum(1 for t in res.turns if t.template_ok is False)
        pp = per.setdefault(res.persona_id, [0, 0])
        pp[1] += 1
        pp[0] += 1 if res.passed else 0
    rep.failed = rep.total - rep.passed
    rep.pass_rate = (rep.passed / rep.total) if rep.total else 0.0
    rep.in_domain_pass_rate = (
        rep.in_domain_passed / rep.in_domain_total) if rep.in_domain_total else 0.0
    rep.off_topic_refuse_rate = (
        rep.off_topic_passed / rep.off_topic_total) if rep.off_topic_total else 0.0
    rep.per_persona = {k: (v[0], v[1]) for k, v in per.items()}
    return rep


# ═══════════════════════════════ REPORT RENDER ════════════════════════════════
def _mark(ok: bool | None) -> str:
    return "n/a" if ok is None else ("✅" if ok else "❌")


def _conv_judge_mark(res: ConversationResult) -> str:
    if not res.criteria or all(p is None for _c, p, _r in res.criteria):
        return "n/a"
    return "✅" if all(p is not False for _c, p, _r in res.criteria) else "❌"


def render_report(report: Report, results: list[ConversationResult], *,
                  verbose: bool = False, banner: str = "",
                  judge_ok: bool = True, judge_note: str = "") -> str:
    L: list[str] = []
    L.append("═" * 68)
    L.append("  PERSONA MULTI-TURN SIMULATION  ·  READ-ONLY")
    L.append("═" * 68)
    L.append(f"  conversations: {report.total}   ·   ✅ passed: {report.passed} "
             f"({100 * report.pass_rate:.0f}%)   ·   ❌ failed: {report.failed}"
             f"   ·   errored: {report.errored}")
    if not judge_ok:
        L.append(f"  ⚠ quality + grammar SKIPPED — {judge_note or 'no ANTHROPIC_API_KEY'} "
                 "(invariants + off-topic still enforced)")

    L.append("\n  ── TWO READINESS NUMBERS (off-topic never dilutes the domain score) ──")
    L.append(f"  🎯 IN-DOMAIN pass-rate     {report.in_domain_passed}/{report.in_domain_total}"
             f"   ({100 * report.in_domain_pass_rate:.0f}%)")
    L.append(f"  🚧 OFF-TOPIC refuse-rate   {report.off_topic_passed}/{report.off_topic_total}"
             f"   ({100 * report.off_topic_refuse_rate:.0f}%)")

    L.append("\n  ── FAILURE-TYPE TALLY (conversations affected) ──")
    for cat in _FAILURE_CATEGORIES:
        n = report.failure_tally.get(cat, 0)
        tag = "  (informational)" if cat == "template_missed" else ""
        L.append(f"    {cat:<20} {n}{tag}")
    L.append(f"    (template turns improvised: {report.template_improvised_turns})")

    L.append("\n  ── PER-PERSONA PASS-RATE (weakest visible) ──")
    order = {p.id: idx for idx, p in enumerate(PERSONAS)}
    for pid in sorted(report.per_persona, key=lambda k: report.per_persona[k][0] / max(1, report.per_persona[k][1])):
        p, t = report.per_persona[pid]
        persona = get_persona(pid)
        dom = "in-domain" if (persona and persona.in_domain) else "off-topic"
        L.append(f"    {pid:<20} {p}/{t:<3} ({100 * p / t if t else 0:.0f}%)   [{dom}]")

    # FAILED conversations — full transcripts.
    failed = [r for r in results if not r.passed]
    if failed:
        L.append("\n" + "─" * 68)
        L.append("  FAILED CONVERSATIONS (full transcript)")
        L.append("─" * 68)
        for res in failed:
            reasons = ", ".join(sorted(res.failure_types)) or "unknown"
            L.append(f"\n  ✗ [{res.persona_id}] {res.label} · sender={res.sender_id}"
                     f"   → {reasons}"
                     + (f"   ERROR: {res.error}" if res.errored else ""))
            jmark = _conv_judge_mark(res)
            for rec in res.turns:
                tmark = _mark(rec.template_ok)
                gmark = _mark(rec.grammar_ok)
                tinfo = f"·template({rec.template_intent})={tmark}" if rec.template_intent else ""
                L.append(f"    Turn {rec.index + 1}  [handler={rec.handler} "
                         f"·kind={rec.handler_kind} {tinfo} ·judge={jmark} ·grammar={gmark}]"
                         + (f"  ⚠ {', '.join(rec.breaches)}" if rec.breaches else ""))
                L.append(f"       👤 {rec.user}")
                L.append(f"       🤖 {rec.reply}")
                if rec.grammar_issues:
                    for gl in rec.grammar_issues.splitlines():
                        L.append("       " + gl)
            # criteria detail
            for crit, passed, reason in res.criteria:
                L.append(f"       judge {_mark(passed)}  {crit}  — {reason}")

    # PASSED conversations — one line each (unless --verbose).
    passed = [r for r in results if r.passed]
    if passed:
        L.append("\n" + "─" * 68)
        L.append(f"  PASSED CONVERSATIONS ({len(passed)})")
        L.append("─" * 68)
        if verbose:
            for res in passed:
                L.append(f"\n  ✅ [{res.persona_id}] {res.label} · {len(res.turns)} turns · sender={res.sender_id}")
                for rec in res.turns:
                    L.append(f"    Turn {rec.index + 1} [handler={rec.handler}·{rec.handler_kind}]")
                    L.append(f"       👤 {rec.user}")
                    L.append(f"       🤖 {rec.reply}")
        else:
            for res in passed:
                L.append(f"  ✅ [{res.persona_id}] {res.label} · {len(res.turns)} turns ·"
                         f" sender={res.sender_id}")

    if banner:
        L.append("\n" + "═" * 68)
        L.append(banner)
        L.append("═" * 68)
    return "\n".join(L)


# ═════════════════════════ LIVE ORCHESTRATOR (safety-wrapped) ═════════════════
def _enable_trace_debug() -> None:
    """Turn CONVERSATION_TRACE_DEBUG on across every module that holds a
    `settings` binding, preserving the safe flags install_readonly already set."""
    import dataclasses
    import importlib

    from app import config as cfg
    swapped = dataclasses.replace(cfg.settings, CONVERSATION_TRACE_DEBUG=True)
    for name in tuple(safety._SETTINGS_MODULES) + ("app.config",):
        try:
            m = importlib.import_module(name)
            if hasattr(m, "settings"):
                setattr(m, "settings", swapped)
        except Exception:
            pass


def run_all(*, runs: int = 5, persona_ids: list[str] | None = None,
            report_path: str | None = None, verbose: bool = False,
            threshold: float = 0.8, max_grammar_turns: int = 0) -> int:
    """Live orchestration: install READ-ONLY safety, enable the trace, drive the
    real engine for every persona × N runs, print + optionally write the report.

    Returns 0 iff pass-rate ≥ threshold AND no READ-ONLY tripwire hit; else 1.
    Self-skips (exit 0) with a clear message when no OPENAI key is available."""
    import os

    import app.config  # noqa: F401 — populates os.environ from .env (keys)

    if not os.environ.get("OPENAI_API_KEY"):
        print("⏭  SKIP: no OPENAI_API_KEY — the persona-user + engine both need it. "
              "Set it (or check .env) to run the simulation.")
        return 0

    log = safety.SideEffectLog()
    safety.install_readonly(log, block_httpx=False)   # --llm mode; side effects stubbed
    _enable_trace_debug()

    from evals import judge as judge_mod
    judge_ok, judge_note = judge_mod.judge_available()

    from evals.harness import Harness
    h = Harness(log, llm_enabled=True, judge_enabled=judge_ok)
    facts = personas_mod.domain_facts()
    deps = SimDeps.live(h, facts, judge_enabled=judge_ok, max_grammar_turns=max_grammar_turns)

    plist = ([get_persona(p) for p in persona_ids] if persona_ids else list(PERSONAS))
    plist = [p for p in plist if p is not None]
    if not plist:
        print("⏭  SKIP: no matching personas.")
        return 0

    results = run_batch(plist, runs, deps)
    report = summarize(results)
    banner = safety.render_banner(log, llm_used=True, httpx_blocked=False)
    text = render_report(report, results, verbose=verbose, banner=banner,
                         judge_ok=judge_ok, judge_note=judge_note)
    print("\n" + text + "\n")

    if report_path:
        try:
            with open(report_path, "w", encoding="utf-8") as fh:
                fh.write(text + "\n")
            print(f"  📄 report written → {report_path}")
        except Exception as exc:
            print(f"  ⚠ could not write report → {report_path}: {exc}")

    ok = (report.pass_rate >= threshold) and (log.live_total() == 0)
    return 0 if ok else 1
