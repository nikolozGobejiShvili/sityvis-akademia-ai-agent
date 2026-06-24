"""Phase 2 migration generator.

Reads template constants from data/prompts.py and writes them to YAML files
under app/agent/templates/. Uses PyYAML literal block scalar (`|`) for any
multi-line string, with chomping selected automatically by PyYAML based on
trailing whitespace.

After writing each file, this script round-trips the YAML (dump -> load) and
asserts byte-identity against the original Python constant. If any round-trip
fails, the script exits non-zero and reports the offending key. No silent
fixes.

Run from repo root:
    .venv/Scripts/python.exe tools/migrate_templates_to_yaml.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from data import prompts  # noqa: E402

TEMPLATES_DIR = REPO_ROOT / "app" / "agent" / "templates"


# -- Migration map -----------------------------------------------------------
# group/file -> {yaml_key: python_constant_value}
# group = first segment (folder name), file = second segment (yaml filename
# without extension)

MIGRATION: dict[str, dict[str, str]] = {
    "parent/welcome": {
        "welcome": prompts.PARENT_WELCOME,
        "welcome_with_concern": prompts.PARENT_WELCOME_WITH_CONCERN,
    },
    "parent/price": {
        "price_first_response": prompts.PARENT_PRICE_FIRST_RESPONSE,
        "price_in_flow": prompts.PARENT_PRICE_IN_FLOW,
        "book_fast_track": prompts.PARENT_BOOK_FAST_TRACK,
        "info_first_response": prompts.PARENT_INFO_FIRST_RESPONSE,
    },
    "parent/discovery": {
        "ask_challenge": prompts.PARENT_ASK_CHALLENGE,
        "ask_deeper": prompts.PARENT_ASK_DEEPER,
        "ask_desire": prompts.PARENT_ASK_DESIRE,
        "present_value_fallback": prompts.PARENT_PRESENT_VALUE_FALLBACK,
    },
    "parent/contact": {
        "ask_name": prompts.PARENT_ASK_NAME,
        "ask_phone_only": prompts.PARENT_ASK_PHONE_ONLY,
        "ask_name_retry": prompts.PARENT_ASK_NAME_RETRY,
        "ask_phone_retry_invalid": prompts.PARENT_ASK_PHONE_RETRY_INVALID,
    },
    "parent/booking": {
        "offer_consultation": prompts.PARENT_OFFER_CONSULTATION,
        "booking_confirmed": prompts.PARENT_BOOKING_CONFIRMED,
        "done_response": prompts.PARENT_DONE_RESPONSE,
        "slot_unavailable": prompts.PARENT_SLOT_UNAVAILABLE,
        "clarify_slot_choice": prompts.PARENT_CLARIFY_SLOT_CHOICE,
        "booking_failed": prompts.PARENT_BOOKING_FAILED,
    },
    "parent/followup": {
        "followup": prompts.PARENT_FOLLOWUP,
    },
    "parent/fallbacks": {
        "fallback_response": prompts.PARENT_FALLBACK_RESPONSE,
    },
    "parent/internal": {
        "context": prompts.PARENT_CONTEXT,
        "summary_fallback": prompts.PARENT_SUMMARY_FALLBACK,
    },
    "adult/welcome": {
        "welcome": prompts.ADULT_WELCOME,
        "clarify_event": prompts.ADULT_CLARIFY_EVENT,
        "no_events": prompts.ADULT_NO_EVENTS,
        "event_list_item": prompts.ADULT_EVENT_LIST_ITEM,
    },
    "adult/event": {
        "event_details": prompts.ADULT_EVENT_DETAILS,
        "event_context": prompts.ADULT_EVENT_CONTEXT,
        "done_context": prompts.ADULT_DONE_CONTEXT,
    },
    "adult/booking": {
        "send_booking": prompts.ADULT_SEND_BOOKING,
        "booking_forwarded": prompts.ADULT_BOOKING_FORWARDED,
    },
    "adult/followup": {
        "followup": prompts.ADULT_FOLLOWUP,
    },
    "adult/internal": {
        "summary_fallback": prompts.ADULT_SUMMARY_FALLBACK,
    },
    "common/routing": {
        "unclear_routing": prompts.UNCLEAR_ROUTING,
    },
    "common/error": {
        "error_message": prompts.ERROR_MESSAGE,
    },
    "comments/replies": {
        "reply_dm_sent": prompts.COMMENT_REPLY_DM_SENT,
        "reply_fallback": prompts.COMMENT_REPLY_FALLBACK,
        "followup_reply": prompts.COMMENT_FOLLOWUP_REPLY,
    },
    "notifications/manager": {
        "email_subject": prompts.MANAGER_EMAIL_SUBJECT,
        "email_body": prompts.MANAGER_EMAIL_BODY,
        "whatsapp_body": prompts.MANAGER_WHATSAPP_BODY,
        "sms_body": prompts.MANAGER_SMS_BODY,
        "details_parent": prompts.MANAGER_DETAILS_PARENT,
        "details_adult": prompts.MANAGER_DETAILS_ADULT,
        "short_parent": prompts.MANAGER_SHORT_PARENT,
        "short_adult": prompts.MANAGER_SHORT_ADULT,
        "booking_text_yes": prompts.BOOKING_TEXT_YES,
        "booking_text_no": prompts.BOOKING_TEXT_NO,
    },
    "calendar/event": {
        "summary": prompts.CALENDAR_EVENT_SUMMARY,
        "description": prompts.CALENDAR_EVENT_DESCRIPTION,
        "slot_choice_prompt": prompts.CALENDAR_SLOT_CHOICE_PROMPT,
        "options_separator": prompts.CALENDAR_OPTIONS_SEPARATOR,
    },
}


# YAML characters that force a single-line value to be quoted when used as a
# plain scalar. Keeping the explicit list documents intent for the next reader.
_RISKY_LEADING_CHARS = set("[]{}!&*#?|>%@`")
_RISKY_SUBSTRINGS = (": ", " #")


def _needs_quoting(value: str) -> bool:
    if value == "":
        return True
    if value != value.strip():
        # leading or trailing whitespace would be eaten by plain scalar
        return True
    if value[0] in _RISKY_LEADING_CHARS:
        return True
    if value[0] in {'"', "'"}:
        return True
    if any(token in value for token in _RISKY_SUBSTRINGS):
        return True
    # braces anywhere break plain-scalar parsing as a flow indicator
    if "{" in value or "}" in value or "[" in value or "]" in value:
        return True
    return False


def _str_representer(dumper: yaml.Dumper, data: str):  # type: ignore[override]
    if "\n" in data:
        # Literal block scalar; PyYAML auto-picks chomping ("|", "|-", "|+")
        # based on trailing newlines.
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
    if _needs_quoting(data):
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style='"')
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


class _OrderedDumper(yaml.SafeDumper):
    pass


_OrderedDumper.add_representer(str, _str_representer)


def _write_yaml(path: Path, payload: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.dump(
        payload,
        Dumper=_OrderedDumper,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
        width=10_000,
    )
    path.write_text(text, encoding="utf-8")


def _roundtrip_check(path: Path, payload: dict[str, str]) -> list[str]:
    """Load the YAML back and compare byte-identity per key. Return failures."""
    with path.open("r", encoding="utf-8") as fh:
        loaded = yaml.safe_load(fh) or {}
    failures: list[str] = []
    for key, expected in payload.items():
        actual = loaded.get(key)
        if actual != expected:
            failures.append(
                f"  {path.relative_to(REPO_ROOT)} key={key!r}:\n"
                f"    expected (len={len(expected)}, repr): {expected!r}\n"
                f"    actual   (len={len(actual or '')}, repr): {actual!r}"
            )
    return failures


def main() -> int:
    all_failures: list[str] = []
    written = 0
    for group_path, payload in MIGRATION.items():
        target = TEMPLATES_DIR / f"{group_path}.yaml"
        _write_yaml(target, payload)
        failures = _roundtrip_check(target, payload)
        all_failures.extend(failures)
        written += 1
        print(f"[write] {target.relative_to(REPO_ROOT)}  keys={len(payload)}")

    if all_failures:
        print("\n=== ROUND-TRIP FAILURES ===")
        for failure in all_failures:
            print(failure)
        print(f"\n{len(all_failures)} mismatches across {written} files.")
        return 1

    print(f"\nAll {written} files round-trip byte-identical.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
