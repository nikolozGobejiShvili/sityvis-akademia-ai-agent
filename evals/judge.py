"""LLM-as-judge (OpenAI by default; Anthropic optional).

Strict BINARY rubric, one criterion at a time. Used ONLY for the nuanced
"response quality" / "naturalness" dimensions. Deterministic / objective checks
never use the judge. Returns (criterion, passed, reason) tuples.

Backend is selected by ``EVAL_JUDGE_BACKEND`` (default ``openai`` — the
operator's live OpenAI key; ``anthropic`` for a Claude cross-check). Every model
call goes through the single ``_judge_completion`` chokepoint so the three
rubrics (response-quality ``judge``, ``grade_grammar``, and naturalness) share
one backend + model + token-param path.

Fail-safe: if the selected backend's SDK is missing OR its API key is unset, the
judge is DISABLED and the harness marks judge checks JUDGE-SKIPPED (never a
silent pass). The judge itself performs NO side-effect beyond the grading API
call. Using a DIFFERENT model than the agent under test (agent = gpt-4.1-mini,
judge = gpt-5.4-mini) keeps the grader stronger than and distinct from the
gradee, limiting self-judging bias.
"""
from __future__ import annotations

import json
import os
from typing import Iterable

# Backend + model. OpenAI is the default because the operator has a live OpenAI
# key; gpt-5.4-mini is the strongest model on that account AND a different model
# than the agent under test (gpt-4.1-mini) — stronger grader, less self-bias.
_JUDGE_BACKEND = (os.environ.get("EVAL_JUDGE_BACKEND", "openai") or "openai").strip().lower()
_DEFAULT_JUDGE_MODEL = {"openai": "gpt-5.4-mini", "anthropic": "claude-sonnet-4-6"}
_JUDGE_MODEL = (
    os.environ.get("EVAL_JUDGE_MODEL", "").strip()
    or _DEFAULT_JUDGE_MODEL.get(_JUDGE_BACKEND, "gpt-5.4-mini")
)


def _openai_api_key() -> str:
    """OPENAI_API_KEY from os.environ first, then the app's .env resolver
    (Railway/local parity). Empty string when unset."""
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if key:
        return key
    try:
        from app.config import _env
        return (_env("OPENAI_API_KEY") or "").strip()
    except Exception:
        return ""


def _openai_uses_completion_tokens(model: str) -> bool:
    """gpt-5.x / o1 / o3 / o4 / anything containing '5.4' → max_completion_tokens
    (mirrors app.services.openai_service._uses_max_completion_tokens)."""
    m = (model or "").lower()
    return ("5.4" in m) or m.startswith(("gpt-5", "o1", "o3", "o4"))


def _judge_completion(system: str, user: str, *, max_tokens: int,
                      temperature: float = 0.0) -> str:
    """ONE judge model call → the model's text output. Backend selected by
    ``_JUDGE_BACKEND`` (read at call time so tests/env can override). Raises on a
    hard SDK/transport error (callers treat that as JUDGE-ERROR / a dropped
    naturalness run)."""
    if _JUDGE_BACKEND == "anthropic":
        import anthropic
        client = anthropic.Anthropic()
        resp = client.messages.create(
            model=_JUDGE_MODEL, max_tokens=max_tokens, temperature=temperature,
            system=system, messages=[{"role": "user", "content": user}],
        )
        return "".join(getattr(b, "text", "") for b in resp.content).strip()
    # default: OpenAI (the operator's live key)
    from openai import OpenAI
    client = OpenAI(api_key=_openai_api_key())
    token_kw = ("max_completion_tokens"
                if _openai_uses_completion_tokens(_JUDGE_MODEL) else "max_tokens")
    resp = client.chat.completions.create(
        model=_JUDGE_MODEL,
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": user}],
        temperature=temperature,
        **{token_kw: max_tokens},
    )
    return (resp.choices[0].message.content or "").strip()


_SYSTEM = (
    "You are a STRICT evaluator of a Georgian-language sales agent's replies. "
    "For each criterion answer ONLY whether it is satisfied. Be conservative: "
    "if uncertain, fail it. Judge solely the criterion stated, in Georgian "
    "context. Return STRICT JSON: a list where each item is "
    '{"index": <int>, "pass": <true|false>, "reason": "<short Georgian/English>"}.'
)


def judge_available() -> tuple[bool, str]:
    """Is the configured judge backend usable? OpenAI (default) needs the openai
    SDK + an OPENAI_API_KEY; Anthropic needs the anthropic SDK +
    ANTHROPIC_API_KEY. Never raises — a False verdict marks judge checks
    JUDGE-SKIPPED (never a silent pass)."""
    if _JUDGE_BACKEND == "anthropic":
        try:
            import anthropic  # noqa: F401
        except Exception:
            return False, "anthropic SDK not installed"
        if not os.environ.get("ANTHROPIC_API_KEY"):
            return False, "ANTHROPIC_API_KEY not set"
        return True, ""
    try:
        from openai import OpenAI  # noqa: F401
    except Exception:
        return False, "openai SDK not installed"
    if not _openai_api_key():
        return False, "OPENAI_API_KEY not set"
    return True, ""


def judge(context: str, criteria: list[str]) -> list[tuple[str, bool, str]]:
    """Grade `context` against each binary `criteria` item. Raises only on a
    hard SDK/transport error (the caller treats that as JUDGE-ERROR)."""
    numbered = "\n".join(f"{i}. {c}" for i, c in enumerate(criteria))
    user = (
        f"CONTEXT (conversation excerpt):\n{context}\n\n"
        f"CRITERIA (binary, judge each independently):\n{numbered}\n\n"
        "Return the JSON list now."
    )
    text = _judge_completion(_SYSTEM, user, max_tokens=1024)
    # Extract the JSON array defensively.
    start, end = text.find("["), text.rfind("]")
    parsed = json.loads(text[start:end + 1]) if start != -1 and end != -1 else []
    by_index = {int(item.get("index", -1)): item for item in parsed if isinstance(item, dict)}
    out: list[tuple[str, bool, str]] = []
    for i, crit in enumerate(criteria):
        item = by_index.get(i, {})
        out.append((crit, bool(item.get("pass", False)), str(item.get("reason", "no verdict"))))
    return out


# ════════════════════════ GEORGIAN GRAMMAR EVALUATOR ════════════════════════
# A SEPARATE rubric (never mixed into the response_quality judge). Run on every
# agent reply generated during a full_turn case. Each criterion is binary; on a
# FAIL the judge returns the concrete error(s): {fragment, correction, rule}.

# (id, short label shown in the report, exact criterion sent to the judge)
GRAMMAR_CRITERIA: list[tuple[str, str, str]] = [
    ("cases", "ბრუნვა",
     "ბრუნვები სწორია — ყველა არსებითი სახელი/ზედსართავი კონტექსტის შესაბამის "
     "ბრუნვაშია (სახელობითი/მოთხრობითი/მიცემითი/ნათესაობითი/მოქმედებითი/"
     "ვითარებითი/წოდებითი)."),
    ("conjugation", "უღლება",
     "ზმნის უღლება და პირი სწორია — პირი, რიცხვი, დრო და მწკრივი ემთხვევა "
     "კონტექსტს; ზრდილობითი მე-2 პირი (-თ) დაცულია."),
    ("agreement", "თანხმობა",
     "Subject–verb თანხმობა დაცულია — ქვემდებარე და შემასმენელი ერთ პირსა და "
     "რიცხვშია."),
    ("spelling", "მართლწერა",
     "მართლწერა სწორია — ტექსტი typo-ების (გამოტოვებული/შეცვლილი ასოები) გარეშეა."),
    ("word_order", "სიტყვათწყობა",
     "სიტყვათწყობა ბუნებრივი, სასაუბრო ქართულია — არა სიტყვასიტყვით ნათარგმნი ან "
     "ხელოვნური."),
    ("mixed_script", "mixed-script",
     "Mixed-script არ აქვს — ლათინური ან კირილიცა ასოები არ ერევა ქართულ "
     "სიტყვებში (ცალკე მდგომი URL/ბრენდის ლათინური სახელის გარდა)."),
]

_GRAMMAR_SYSTEM = (
    "You are a STRICT Georgian-language grammar checker. Evaluate ONLY grammar / "
    "orthography of the AGENT reply (ignore whether the content is correct). For "
    "each criterion return whether it is satisfied; be conservative (if unsure, "
    "fail). For EVERY failing criterion list the concrete mistakes, each as "
    '{"fragment": "<exact text from the reply>", "correction": "<corrected form '
    'OR short explanation>", "rule": "<which rule, in Georgian — e.g. ნათესაობითი>"}. '
    'Return STRICT JSON: {"results": [{"id": "<criterion id>", "pass": <bool>, '
    '"errors": [ ... ]}, ...]} with one entry per criterion id, in order.'
)


class GrammarGraderError(RuntimeError):
    """Raised when the grammar grader's model output cannot be parsed as JSON
    even after a retry. Callers record this as an EXPLICIT grader_error — never a
    silent pass and never a false FAIL."""


def _extract_json_object(text: str) -> str | None:
    """Return the first COMPLETE top-level ``{...}`` object in ``text``, tolerant
    of surrounding prose, ``` code fences, and trailing text. String-aware: a
    brace inside a JSON string value never truncates the span (the old
    ``find('{')`` / ``rfind('}')`` slice broke on exactly that — a long Georgian
    price reply quoted inside a ``fragment`` field). Returns None when no
    balanced object is present."""
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None            # unbalanced — no complete object


def _grammar_completion(user: str) -> str:
    """One grader model call → the model's text output (via the shared
    backend chokepoint `_judge_completion`)."""
    return _judge_completion(_GRAMMAR_SYSTEM, user, max_tokens=1500)


def grade_grammar(response: str) -> list[dict]:
    """Grade `response` against GRAMMAR_CRITERIA. Returns a list aligned to
    GRAMMAR_CRITERIA: [{id, label, pass, errors:[{fragment,correction,rule}]}].

    Parsing is ROBUST: the grader's JSON is extracted with a string-aware
    balanced-brace scan (survives ``` fences / prose / trailing text / braces
    inside quoted fragments), and on a genuine parse failure the call is RETRIED
    ONCE. Only if BOTH attempts fail does it raise :class:`GrammarGraderError` —
    which the caller records as an explicit grader_error (never a silent pass,
    never a false FAIL). What it JUDGES is unchanged — only the parsing hardened."""
    numbered = "\n".join(f"- id={cid}: {crit}" for cid, _label, crit in GRAMMAR_CRITERIA)
    user = (
        f"AGENT REPLY (Georgian):\n{response}\n\n"
        f"CRITERIA (binary, judge each independently):\n{numbered}\n\n"
        "Return the JSON object now."
    )
    parsed: dict | None = None
    last_err: Exception | None = None
    for _attempt in range(2):        # initial call + ONE retry on a parse failure
        try:
            text = _grammar_completion(user)
            blob = _extract_json_object(text)
            if blob is None:
                raise ValueError("no JSON object found in grader output")
            candidate = json.loads(blob)
            if not isinstance(candidate, dict):
                raise ValueError("grader JSON is not an object")
            parsed = candidate
            break
        except Exception as exc:     # parse OR transport failure → retry once
            last_err = exc
    if parsed is None:
        raise GrammarGraderError(
            "grade_grammar could not parse grader output after retry: "
            f"{type(last_err).__name__}: {last_err}"
        )

    by_id = {str(r.get("id")): r for r in parsed.get("results", []) if isinstance(r, dict)}
    out: list[dict] = []
    for cid, label, _crit in GRAMMAR_CRITERIA:
        r = by_id.get(cid, {})
        errors = [e for e in r.get("errors", []) if isinstance(e, dict)]
        out.append({"id": cid, "label": label, "pass": bool(r.get("pass", True)), "errors": errors})
    return out


def render_grammar_issues(case_id: str, response: str, graded: list[dict]) -> str:
    """Render the 🇬🇪 GRAMMAR ISSUES block for a reply that has ≥1 failing
    criterion. Returns "" when the reply is grammatically clean."""
    failing = [g for g in graded if not g["pass"]]
    if not failing:
        return ""
    lines = [
        f"  🇬🇪 GRAMMAR ISSUES — [{case_id}]",
        "  " + "─" * 40,
        f'  response: "{response}"',
    ]
    for g in failing:
        label = f"{g['label']}:".ljust(15)
        errs = g["errors"] or [{"fragment": "", "correction": "(დეტალი არ დაბრუნდა)", "rule": ""}]
        for e in errs:
            frag = str(e.get("fragment", "")).strip()
            corr = str(e.get("correction", "")).strip()
            rule = str(e.get("rule", "")).strip()
            head = f'"{frag}" → {corr}' if frag else corr
            tail = f" ({rule})" if rule else ""
            lines.append(f"  ✗ {label}{head}{tail}")
            label = " " * 15  # only label the first error line of a criterion
    return "\n".join(lines)

