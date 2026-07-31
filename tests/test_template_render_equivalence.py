"""Render-equivalence tests for Phase 3.

Goal: confirm that the Phase 3 knowledge migration did NOT change the bytes
of any customer-facing template render, EXCEPT for the two intentional
location corrections in parent/price.yaml.

These tests do not call OpenAI. They compare the BEFORE snapshot captured
by tools/snapshot_templates.py against the current loader output.

If the snapshot file is missing (e.g. fresh checkout), the test is skipped
with a clear message — it is a regression guard, not a build gate.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
BEFORE_PATH = REPO_ROOT / "tools" / "_snapshots" / "before.json"

# Exact location-correction substitution allowed by Phase 3 spec.
ALLOWED_LOCATION_DIFF: dict[str, tuple[str, str]] = {
    "parent/price_first_response": (
        "ამბასადორი კაჭრეთის აკადემიაში", "ამბასადორი კაჭრეთში",
    ),
    "parent/info_first_response": (
        "ამბასადორი კაჭრეთის აკადემიაში", "ამბასადორი კაჭრეთში",
    ),
}


# ST-2 adult no-active copy alignment (19698cb). Keep this as an exact
# old-to-new substitution so unrelated drift inside the same key still fails.
ALLOWED_EXACT_TEMPLATE_DIFFS: dict[str, tuple[str, str]] = {
    "adult/no_events": (
        "ამ ეტაპზე ღონისძიებების განრიგი ზუსტდება.",
        "ამ ეტაპზე აქტიური ღონისძიება სიაში არ მაქვს. თუ გსურთ, მენეჯერთან დაგაკავშირებთ.",
    ),
    # Live 2026-07-31: the booking confirmation told the parent a *consultant*
    # would call. The person who calls back is the MANAGER — the agent itself is
    # the online consultant. Same correction applied in the live prompts, which
    # had been offering „მენეჯერს/კონსულტანტს" as interchangeable.
    "parent/ask_phone_only": (
        "რომ კონსულტანტი დაგიკავშირდეთ",
        "რომ მენეჯერი დაგიკავშირდეთ",
    ),
}

ALLOWED_EXACT_PROMPT_DIFFS: dict[str, tuple[str, str]] = {
    "system_adult": (
        '"ამ ეტაპზე ღონისძიებების განრიგი ზუსტდება. როგორც კი დადასტურდება, სიამოვნებით გაგიზიარებთ თარიღებსა და თემებს."',
        '"ამ ეტაპზე აქტიური ღონისძიება სიაში არ მაქვს. თუ გსურთ, მენეჯერთან დაგაკავშირებთ."',
    ),
}


# Owner-requested intentional rewrites in the P2 task — these templates
# were rewritten in full (not by substring patch) to remove the
# problem-assumption framing flagged in the live test. Any change to a
# key listed here is accepted by this regression guard.
ALLOWED_FULL_REWRITES: set[str] = {
    "parent/ask_challenge",
    "parent/ask_deeper",
    "parent/present_value_fallback",
    # COMMENT FLOW PATCH 3 — public reply text became uniform (no
    # {name} placeholder) so the rendered byte length is shorter than
    # the snapshot. The new text is asserted by the dedicated
    # `test_patch3_public_reply_text_template_updated` test.
    "comments/reply_dm_sent",
    # Parent-greeting fix — parent/welcome is now the static two-option
    # menu so the bot's first reply at state=START never has to round-
    # trip through the LLM engine. The camp-specific framing + age
    # question moved to parent/welcome_camp_opener and is asserted by
    # the dedicated greeting tests in test_parent_llm_engine.py.
    "parent/welcome",
    # Email Wording Polish Patch — notification templates rewritten so
    # the programmatic email body builder owns the wording (correct
    # Georgian genitive, conditional `deeper_concern`, no duplicated
    # challenge). Asserted by the dedicated `test_manager_email_wording`
    # suite (29 tests).
    "notifications/booking_text_no",
    "notifications/details_parent",
    "notifications/email_body",
    "notifications/short_parent",
    # Agent Wording Cleanup Patch (2026-06-03) — decorative emojis
    # (🌿 / 😊 / ✨) and the unnatural „კეთილი იყოს თქვენი ვიზიტი…" /
    # „დაჯავშნილია 🌿" / leading-greeting-emoji constructs were
    # removed from every user-facing static template. Asserted by the
    # dedicated `test_agent_wording_cleanup.py` suite.
    "parent/welcome_with_concern",
    "parent/price_first_response",
    "parent/price_in_flow",
    "parent/book_fast_track",
    "parent/info_first_response",
    "parent/booking_confirmed",
    "parent/done_response",
    "parent/booking_failed",
    "parent/followup",
    "common/unclear_routing",
    "adult/welcome",
    "comments/reply_fallback",
}

# P3-C PATCH 2 — owner-requested rewrite of the CRM summary prompt to
# add an explicit Georgian-only / no-English instruction. The change is
# additive (the original Georgian summary line is preserved verbatim),
# but the byte length differs, so list the key here so the snapshot
# regression guard doesn't trip.
ALLOWED_FULL_PROMPT_REWRITES: set[str] = {
    "summary",
    # Agent Wording Cleanup Patch (2026-06-03) — emoji line + manager-
    # handoff preferred-phrase block added; example responses dropped
    # decorative emojis. Behaviour validated by
    # `tests/test_agent_wording_cleanup.py`.
    "system_base",
    "system_parent_v2",
    "system_adult_v1",
    "parent_communication_style",
}


def _is_exact_substitution(
    before: str,
    after: str,
    old: str,
    new: str,
) -> bool:
    return (
        before.count(old) == 1
        and after.count(new) == 1
        and before.replace(old, new, 1) == after
    )


@pytest.fixture(scope="module")
def before_snapshot() -> dict:
    if not BEFORE_PATH.exists():
        pytest.skip(
            f"BEFORE snapshot missing at {BEFORE_PATH} — "
            "run tools/snapshot_templates.py before this test"
        )
    with BEFORE_PATH.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def test_all_templates_render_identical_except_allowed_location_correction(
    before_snapshot: dict,
) -> None:
    from app.agent.services.template_loader import (
        get_template,
        reset_cache,
    )

    reset_cache()
    diffs: list[str] = []
    allowed_seen: list[str] = []
    exact_seen: list[str] = []

    for key, before in before_snapshot["templates"].items():
        group, name = key.split("/", 1)
        after = get_template(group, name)
        if before == after:
            continue
        if key in ALLOWED_LOCATION_DIFF:
            old, new = ALLOWED_LOCATION_DIFF[key]
            if before.replace(old, new) == after:
                allowed_seen.append(key)
                continue
        if key in ALLOWED_EXACT_TEMPLATE_DIFFS:
            old, new = ALLOWED_EXACT_TEMPLATE_DIFFS[key]
            if _is_exact_substitution(before, after, old, new):
                exact_seen.append(key)
                continue
        if key in ALLOWED_FULL_REWRITES:
            # P2 owner-requested neutral rewrite. Just record that we
            # saw a change here — full byte-equivalence is intentionally
            # not enforced on these.
            allowed_seen.append(key)
            continue
        diffs.append(
            f"  {key}: before len={len(before)} after len={len(after)}"
        )

    assert not diffs, "Unexpected template diffs:\n" + "\n".join(diffs)
    # The exact-substitution corrections from Phase 3 MUST still be in
    # place. The P2 full-rewrite whitelist is an OK-if-changed set, so
    # we only require it as a superset check.
    seen = set(allowed_seen)
    missing_location = set(ALLOWED_LOCATION_DIFF) - seen
    assert not missing_location, (
        f"Expected these Phase 3 location corrections to still apply but "
        f"they were not seen as diffs: {sorted(missing_location)}"
    )
    missing_exact = set(ALLOWED_EXACT_TEMPLATE_DIFFS) - set(exact_seen)
    assert not missing_exact, (
        f"Expected these exact template substitutions to still apply but "
        f"they were not seen as diffs: {sorted(missing_exact)}"
    )


def test_all_prompts_render_identical(before_snapshot: dict) -> None:
    from app.agent.llm.prompt_loader import load_prompt, reset_cache

    reset_cache()
    diffs: list[str] = []
    exact_seen: list[str] = []
    for name, before in before_snapshot["prompts"].items():
        after = load_prompt(name)
        if before == after:
            continue
        if name in ALLOWED_EXACT_PROMPT_DIFFS:
            old, new = ALLOWED_EXACT_PROMPT_DIFFS[name]
            if _is_exact_substitution(before, after, old, new):
                exact_seen.append(name)
                continue
        if name in ALLOWED_FULL_PROMPT_REWRITES:
            # Owner-approved expansion; skip the byte-equivalence check.
            # The wording-rule + integration tests (see
            # test_parent_llm_engine.py and the polish manual sim) cover
            # the post-rewrite behaviour.
            continue
        diffs.append(
            f"  {name}: before len={len(before)} after len={len(after)}"
        )
    assert not diffs, "Prompt diffs found:\n" + "\n".join(diffs)
    missing_exact = set(ALLOWED_EXACT_PROMPT_DIFFS) - set(exact_seen)
    assert not missing_exact, (
        f"Expected these exact prompt substitutions to still apply but "
        f"they were not seen as diffs: {sorted(missing_exact)}"
    )


def test_calendar_constants_unchanged(before_snapshot: dict) -> None:
    from app.flows import parent_flow as pf
    from app.services import calendar_service as cs

    current = {
        "TIMEZONE_NAME": cs.TIMEZONE_NAME,
        "WORK_START": cs.WORK_START.isoformat(),
        "WORK_END": cs.WORK_END.isoformat(),
        "BUSINESS_HOUR_START": cs.BUSINESS_HOUR_START.isoformat(),
        "BUSINESS_HOUR_END": cs.BUSINESS_HOUR_END.isoformat(),
        "SLOT_DURATION_seconds": int(cs.SLOT_DURATION.total_seconds()),
        "SLOT_BUFFER_seconds": int(cs.SLOT_BUFFER.total_seconds()),
        "GEORGIAN_MONTHS": {str(k): v for k, v in cs.GEORGIAN_MONTHS.items()},
        "GEORGIAN_MONTHS_NOM": {str(k): v for k, v in pf.GEORGIAN_MONTHS_NOM.items()},
        "GEORGIAN_MONTH_STEMS": {str(k): int(v) for k, v in pf.GEORGIAN_MONTH_STEMS.items()},
    }

    # Booking Availability Patch (2026-06-03): consultation window
    # widened to 10:00–21:00 and slot duration standardised at 60 min.
    # The before-snapshot still records the pre-patch values; whitelist
    # those constants here so the snapshot guard doesn't flag the
    # intentional change. Other constants (Georgian months, timezone)
    # must still match byte-for-byte.
    BOOKING_AVAILABILITY_OVERRIDES: set[str] = {
        "WORK_END",
        "BUSINESS_HOUR_END",
        "SLOT_DURATION_seconds",
    }

    before = before_snapshot["calendar"]
    # JSON serialises dict keys as strings, so compare in string-key shape.
    diffs = []
    for key in current:
        if key in BOOKING_AVAILABILITY_OVERRIDES:
            continue
        a = current[key]
        b = before.get(key)
        if isinstance(a, dict):
            a = {str(k): v for k, v in a.items()}
        if isinstance(b, dict):
            b = {str(k): v for k, v in b.items()}
        if a != b:
            diffs.append(f"  {key}: before={b!r} after={a!r}")
    assert not diffs, "Calendar constants changed:\n" + "\n".join(diffs)
