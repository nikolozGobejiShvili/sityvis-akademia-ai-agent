"""Byte-identity verification for Phase 2 template migration.

For every template listed in the migration map, this script:
  1. imports the original constant from data.prompts
  2. loads the same template via app.agent.services.template_loader
  3. asserts the two values are byte-identical (Python str equality, which
     is unicode-codepoint equality after PyYAML's UTF-8 decode)
  4. on mismatch, prints the constant name, lengths, first differing index,
     and short repr context — and exits non-zero. No silent fixes.

Run from repo root:
    .venv/Scripts/python.exe tools/verify_template_migration.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

# Force UTF-8 stdout on Windows so we can print Georgian context safely.
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

from app.agent.services.template_loader import (  # noqa: E402
    get_template,
    reset_cache,
)
from data import prompts  # noqa: E402

# (python_constant_name, group, key) — single source of truth for the audit.
CASES: list[tuple[str, str, str]] = [
    # parent / welcome
    ("PARENT_WELCOME", "parent", "welcome"),
    ("PARENT_WELCOME_WITH_CONCERN", "parent", "welcome_with_concern"),
    # parent / price
    ("PARENT_PRICE_FIRST_RESPONSE", "parent", "price_first_response"),
    ("PARENT_PRICE_IN_FLOW", "parent", "price_in_flow"),
    ("PARENT_BOOK_FAST_TRACK", "parent", "book_fast_track"),
    ("PARENT_INFO_FIRST_RESPONSE", "parent", "info_first_response"),
    # parent / discovery
    ("PARENT_ASK_CHALLENGE", "parent", "ask_challenge"),
    ("PARENT_ASK_DEEPER", "parent", "ask_deeper"),
    ("PARENT_ASK_DESIRE", "parent", "ask_desire"),
    ("PARENT_PRESENT_VALUE_FALLBACK", "parent", "present_value_fallback"),
    # parent / contact
    ("PARENT_ASK_NAME", "parent", "ask_name"),
    ("PARENT_ASK_PHONE_ONLY", "parent", "ask_phone_only"),
    ("PARENT_ASK_NAME_RETRY", "parent", "ask_name_retry"),
    ("PARENT_ASK_PHONE_RETRY_INVALID", "parent", "ask_phone_retry_invalid"),
    # parent / booking
    ("PARENT_OFFER_CONSULTATION", "parent", "offer_consultation"),
    ("PARENT_BOOKING_CONFIRMED", "parent", "booking_confirmed"),
    ("PARENT_DONE_RESPONSE", "parent", "done_response"),
    ("PARENT_SLOT_UNAVAILABLE", "parent", "slot_unavailable"),
    ("PARENT_CLARIFY_SLOT_CHOICE", "parent", "clarify_slot_choice"),
    ("PARENT_BOOKING_FAILED", "parent", "booking_failed"),
    # parent / followup
    ("PARENT_FOLLOWUP", "parent", "followup"),
    # parent / fallbacks
    ("PARENT_FALLBACK_RESPONSE", "parent", "fallback_response"),
    # parent / internal
    ("PARENT_CONTEXT", "parent", "context"),
    ("PARENT_SUMMARY_FALLBACK", "parent", "summary_fallback"),
    # adult
    ("ADULT_WELCOME", "adult", "welcome"),
    ("ADULT_CLARIFY_EVENT", "adult", "clarify_event"),
    ("ADULT_NO_EVENTS", "adult", "no_events"),
    ("ADULT_EVENT_LIST_ITEM", "adult", "event_list_item"),
    ("ADULT_EVENT_DETAILS", "adult", "event_details"),
    ("ADULT_EVENT_CONTEXT", "adult", "event_context"),
    ("ADULT_DONE_CONTEXT", "adult", "done_context"),
    ("ADULT_SEND_BOOKING", "adult", "send_booking"),
    ("ADULT_BOOKING_FORWARDED", "adult", "booking_forwarded"),
    ("ADULT_FOLLOWUP", "adult", "followup"),
    ("ADULT_SUMMARY_FALLBACK", "adult", "summary_fallback"),
    # common
    ("UNCLEAR_ROUTING", "common", "unclear_routing"),
    ("ERROR_MESSAGE", "common", "error_message"),
    # comments
    ("COMMENT_REPLY_DM_SENT", "comments", "reply_dm_sent"),
    ("COMMENT_REPLY_FALLBACK", "comments", "reply_fallback"),
    ("COMMENT_FOLLOWUP_REPLY", "comments", "followup_reply"),
    # notifications
    ("MANAGER_EMAIL_SUBJECT", "notifications", "email_subject"),
    ("MANAGER_EMAIL_BODY", "notifications", "email_body"),
    ("MANAGER_WHATSAPP_BODY", "notifications", "whatsapp_body"),
    ("MANAGER_SMS_BODY", "notifications", "sms_body"),
    ("MANAGER_DETAILS_PARENT", "notifications", "details_parent"),
    ("MANAGER_DETAILS_ADULT", "notifications", "details_adult"),
    ("MANAGER_SHORT_PARENT", "notifications", "short_parent"),
    ("MANAGER_SHORT_ADULT", "notifications", "short_adult"),
    ("BOOKING_TEXT_YES", "notifications", "booking_text_yes"),
    ("BOOKING_TEXT_NO", "notifications", "booking_text_no"),
    # calendar
    ("CALENDAR_EVENT_SUMMARY", "calendar", "summary"),
    ("CALENDAR_EVENT_DESCRIPTION", "calendar", "description"),
    ("CALENDAR_SLOT_CHOICE_PROMPT", "calendar", "slot_choice_prompt"),
    ("CALENDAR_OPTIONS_SEPARATOR", "calendar", "options_separator"),
]


def _first_diff_index(a: str, b: str) -> int:
    for i, (ca, cb) in enumerate(zip(a, b)):
        if ca != cb:
            return i
    return min(len(a), len(b))


def _diff_context(constant_name: str, expected: str, actual: str) -> str:
    idx = _first_diff_index(expected, actual)
    window = 30
    start = max(0, idx - window)
    end_expected = min(len(expected), idx + window)
    end_actual = min(len(actual), idx + window)
    return (
        f"  - {constant_name}: lengths py={len(expected)} yaml={len(actual)}\n"
        f"    first differing char index: {idx}\n"
        f"    py   …{expected[start:end_expected]!r}…\n"
        f"    yaml …{actual[start:end_actual]!r}…"
    )


def main() -> int:
    reset_cache()
    failures: list[str] = []
    for constant_name, group, key in CASES:
        if not hasattr(prompts, constant_name):
            failures.append(
                f"  - {constant_name}: missing from data.prompts (audit drift)"
            )
            continue
        expected = getattr(prompts, constant_name)
        try:
            actual = get_template(group, key)
        except Exception as exc:
            failures.append(
                f"  - {constant_name} -> {group}/{key}: loader raised {exc!r}"
            )
            continue
        if expected != actual:
            failures.append(_diff_context(constant_name, expected, actual))
        else:
            print(f"[ok] {constant_name:34s} == {group}/{key}")

    print()
    if failures:
        print(f"=== {len(failures)} mismatch(es) ===")
        for failure in failures:
            print(failure)
        return 1

    print(f"All {len(CASES)} templates byte-identical "
          f"between data.prompts and YAML loader.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
