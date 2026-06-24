"""Capture template + prompt + calendar-constant snapshots for BEFORE/AFTER
render-equivalence checks.

Run BEFORE Phase 3 changes:
    .venv/Scripts/python.exe tools/snapshot_templates.py before

Run AFTER Phase 3 changes:
    .venv/Scripts/python.exe tools/snapshot_templates.py after

Then diff:
    .venv/Scripts/python.exe tools/snapshot_templates.py diff
"""

from __future__ import annotations

import difflib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

SNAPSHOT_DIR = REPO_ROOT / "tools" / "_snapshots"


# Templates whose raw text is the rendered text (no .format() at call site,
# or template has no placeholders). These are the ones we must keep render-
# identical except for the explicit location correction.
TEMPLATE_KEYS: list[tuple[str, str]] = [
    # parent/price.yaml — contains price, location, URL, stream dates
    ("parent", "price_first_response"),
    ("parent", "price_in_flow"),
    ("parent", "book_fast_track"),
    ("parent", "info_first_response"),
    # parent/welcome.yaml — no facts but include for control
    ("parent", "welcome"),
    ("parent", "welcome_with_concern"),
    # parent other text (no facts but useful as control)
    ("parent", "ask_challenge"),
    ("parent", "ask_deeper"),
    ("parent", "ask_desire"),
    ("parent", "present_value_fallback"),
    ("parent", "ask_name"),
    ("parent", "ask_phone_only"),
    ("parent", "ask_name_retry"),
    ("parent", "ask_phone_retry_invalid"),
    ("parent", "offer_consultation"),
    ("parent", "booking_confirmed"),
    ("parent", "done_response"),
    ("parent", "slot_unavailable"),
    ("parent", "clarify_slot_choice"),
    ("parent", "booking_failed"),
    ("parent", "followup"),
    ("parent", "fallback_response"),
    ("parent", "context"),
    ("parent", "summary_fallback"),
    # adult
    ("adult", "welcome"),
    ("adult", "clarify_event"),
    ("adult", "no_events"),
    ("adult", "event_list_item"),
    ("adult", "event_details"),
    ("adult", "event_context"),
    ("adult", "done_context"),
    ("adult", "send_booking"),
    ("adult", "booking_forwarded"),
    ("adult", "followup"),
    ("adult", "summary_fallback"),
    # common — error contains phone
    ("common", "unclear_routing"),
    ("common", "error_message"),
    # comments — name placeholder only, no facts
    ("comments", "reply_dm_sent"),
    ("comments", "reply_fallback"),
    ("comments", "followup_reply"),
    # notifications — placeholders only, no facts
    ("notifications", "email_subject"),
    ("notifications", "email_body"),
    ("notifications", "whatsapp_body"),
    ("notifications", "sms_body"),
    ("notifications", "details_parent"),
    ("notifications", "details_adult"),
    ("notifications", "short_parent"),
    ("notifications", "short_adult"),
    ("notifications", "booking_text_yes"),
    ("notifications", "booking_text_no"),
    # calendar — placeholders only
    ("calendar", "summary"),
    ("calendar", "description"),
    ("calendar", "slot_choice_prompt"),
    ("calendar", "options_separator"),
]

PROMPT_NAMES = [
    "system_base",
    "system_parent",
    "system_adult",
    "detect_segment",
    "detect_start_intent",
    "detect_comment_intent",
    "summary",
    "parent_present_value",
]


def _capture() -> dict:
    from app.agent.services.template_loader import (
        get_template,
        reset_cache as reset_templates,
    )
    from app.agent.llm.prompt_loader import (
        load_prompt,
        reset_cache as reset_prompts,
    )

    reset_templates()
    reset_prompts()

    snapshot: dict = {"templates": {}, "prompts": {}, "calendar": {}}
    for group, key in TEMPLATE_KEYS:
        snapshot["templates"][f"{group}/{key}"] = get_template(group, key)
    for name in PROMPT_NAMES:
        snapshot["prompts"][name] = load_prompt(name)

    # Calendar / parent_flow runtime constants — capture as JSON-safe shape.
    from app.services import calendar_service as cs
    from app.flows import parent_flow as pf

    snapshot["calendar"]["TIMEZONE_NAME"] = cs.TIMEZONE_NAME
    snapshot["calendar"]["WORK_START"] = cs.WORK_START.isoformat()
    snapshot["calendar"]["WORK_END"] = cs.WORK_END.isoformat()
    snapshot["calendar"]["BUSINESS_HOUR_START"] = cs.BUSINESS_HOUR_START.isoformat()
    snapshot["calendar"]["BUSINESS_HOUR_END"] = cs.BUSINESS_HOUR_END.isoformat()
    snapshot["calendar"]["SLOT_DURATION_seconds"] = int(cs.SLOT_DURATION.total_seconds())
    snapshot["calendar"]["SLOT_BUFFER_seconds"] = int(cs.SLOT_BUFFER.total_seconds())
    snapshot["calendar"]["GEORGIAN_MONTHS"] = dict(cs.GEORGIAN_MONTHS)
    snapshot["calendar"]["GEORGIAN_MONTHS_NOM"] = dict(pf.GEORGIAN_MONTHS_NOM)
    snapshot["calendar"]["GEORGIAN_MONTH_STEMS"] = dict(pf.GEORGIAN_MONTH_STEMS)

    return snapshot


def _save(label: str) -> None:
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    snap = _capture()
    path = SNAPSHOT_DIR / f"{label}.json"
    with path.open("w", encoding="utf-8") as fh:
        json.dump(snap, fh, ensure_ascii=False, indent=2, sort_keys=True)
    print(f"[snapshot:{label}] wrote {path.relative_to(REPO_ROOT)}")
    print(f"  templates: {len(snap['templates'])}")
    print(f"  prompts:   {len(snap['prompts'])}")
    print(f"  calendar constants: {len(snap['calendar'])}")


def _diff() -> int:
    before_path = SNAPSHOT_DIR / "before.json"
    after_path = SNAPSHOT_DIR / "after.json"
    if not before_path.exists() or not after_path.exists():
        print("Need both before.json and after.json. Run 'before' then 'after' first.")
        return 1

    with before_path.open("r", encoding="utf-8") as fh:
        before = json.load(fh)
    with after_path.open("r", encoding="utf-8") as fh:
        after = json.load(fh)

    # Allowed-diff allowlist: location correction in price.yaml templates.
    ALLOWED_DIFFS: dict[str, tuple[str, str]] = {
        "parent/price_first_response": (
            "ამბასადორი კაჭრეთის აკადემიაში", "ამბასადორი კაჭრეთში",
        ),
        "parent/info_first_response": (
            "ამბასადორი კაჭრეთის აკადემიაში", "ამბასადორი კაჭრეთში",
        ),
    }

    failures: list[str] = []

    for key in sorted(set(before["templates"]) | set(after["templates"])):
        b = before["templates"].get(key)
        a = after["templates"].get(key)
        if b == a:
            continue

        # Apply the allowed correction to BEFORE and see if it now matches.
        if key in ALLOWED_DIFFS:
            old_phrase, new_phrase = ALLOWED_DIFFS[key]
            adjusted = b.replace(old_phrase, new_phrase)
            if adjusted == a:
                print(
                    f"[allowed-diff] templates/{key}: location correction "
                    f"{old_phrase!r} -> {new_phrase!r}"
                )
                continue

        diff = "\n".join(
            difflib.unified_diff(
                (b or "").splitlines(),
                (a or "").splitlines(),
                fromfile=f"before/{key}",
                tofile=f"after/{key}",
                lineterm="",
            )
        )
        failures.append(f"templates/{key} differs:\n{diff}")

    for key in sorted(set(before["prompts"]) | set(after["prompts"])):
        b = before["prompts"].get(key)
        a = after["prompts"].get(key)
        if b == a:
            continue
        diff = "\n".join(
            difflib.unified_diff(
                (b or "").splitlines(),
                (a or "").splitlines(),
                fromfile=f"before/{key}",
                tofile=f"after/{key}",
                lineterm="",
            )
        )
        failures.append(f"prompts/{key} differs:\n{diff}")

    for key in sorted(set(before["calendar"]) | set(after["calendar"])):
        b = before["calendar"].get(key)
        a = after["calendar"].get(key)
        if b != a:
            failures.append(
                f"calendar/{key} differs: before={b!r} after={a!r}"
            )

    if failures:
        print(f"\n=== {len(failures)} unexpected diff(s) ===\n")
        for f in failures:
            print(f)
            print()
        return 1
    print("\nNo unexpected diffs. Only allowed location corrections found.")
    return 0


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in {"before", "after", "diff"}:
        print(__doc__)
        return 2
    cmd = sys.argv[1]
    if cmd in {"before", "after"}:
        _save(cmd)
        return 0
    return _diff()


if __name__ == "__main__":
    sys.exit(main())
