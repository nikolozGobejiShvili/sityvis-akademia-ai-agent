"""Live test 2026-07-31 (second run) — four defects, each proven by a log line.

The Railway logs only became readable this session: the app had never called
`logging.basicConfig`, so every `logger.info` diagnostic was dropped and only
`print()` survived. With INFO reaching stdout, the exact inputs and the exact
tool arguments are on record, and each test below pins the FACT the live run
got wrong rather than the wording it used.

1. „კი დაჯავშნე" — a bare confirmation naming no day and no hour. The model
   re-derived the ISO from scratch and passed the wrong YEAR:

     [slot_check] requested_datetime=2026-08-01T15:00:00 -> available=True
     [slot_check] requested_datetime=2025-07-18T15:00:00 -> available=False
                                     reason=past_datetime

   so the slot the parent had just confirmed came back as "past".
2. „მენჯერის ნომრი რომმომწეროთ" — Georgian syncopates ნომერი -> ნომრი, so the
   nominative-only contact marker missed it, the deterministic disclosure never
   fired, and the model called request_manager_callback instead (manager email
   + Qualified CRM row, no number for the parent).
3. The reply carried `**bold**` and a full `|---|` table, which Messenger shows
   literally. The live prompt layers were themselves full of both.
4. An empty engine turn returned straight out of the hoisted path, so
   webhook.py logged „Empty response — skipping send" and the parent got
   silence.
"""
from __future__ import annotations

import re
from pathlib import Path

from app.agent.tools.parent_tool_executor import (
    ParentToolExecutor,
    _message_names_a_datetime,
)
from app.flows import parent_flow
from app.models.conversation import Conversation
from app.models.lead import Lead

LIVE_MANAGER_REQUEST = "მენჯერის ნომრი რომმომწეროთ"   # exact input, 13:51:16 UTC
CONFIRMED_ISO = "2026-08-01T15:00:00+04:00"           # what the parent confirmed
HALLUCINATED_ISO = "2025-07-18T15:00:00+04:00"        # what the model then sent


# ── 1. confirmed-slot anchor ───────────────────────────────────────────────


def _executor(user_message: str, pending_iso: str) -> ParentToolExecutor:
    conversation = Conversation(sender_id="t-1", platform="messenger")
    conversation.pending_booking = (
        {"requested_datetime_iso": pending_iso} if pending_iso else None
    )
    return ParentToolExecutor(
        conversation=conversation,
        lead=Lead(sender_id="t-1", platform="messenger", segment="PARENT"),
        sender_id="t-1",
        platform="messenger",
        user_message=user_message,
    )


def test_bare_confirmation_names_no_datetime():
    for message in ("კი დაჯავშნე", "კი", "დაადასტურე", "კარგი, ჩამწერე"):
        assert not _message_names_a_datetime(message), message


def test_a_message_naming_a_day_or_an_hour_is_not_treated_as_bare():
    for message in ("ხვალ 3 საათზე", "ხვალ", "1 აგვისტოს", "15:00", "ზეგ"):
        assert _message_names_a_datetime(message), message


def test_hallucinated_iso_on_a_bare_confirmation_is_anchored_to_the_confirmed_slot():
    executor = _executor("კი დაჯავშნე", CONFIRMED_ISO)
    assert (
        executor._normalise_datetime_iso_from_message(HALLUCINATED_ISO)
        == CONFIRMED_ISO
    )


def test_red_without_a_stashed_slot_the_wrong_iso_survives_untouched():
    """RED-check: the anchor is the only thing correcting this. With no
    pending_booking the old (broken) behaviour must return."""
    executor = _executor("კი დაჯავშნე", "")
    assert (
        executor._normalise_datetime_iso_from_message(HALLUCINATED_ISO)
        == HALLUCINATED_ISO
    )


def test_a_message_that_names_a_time_is_left_to_the_existing_passes():
    """The anchor must never override a parent who names a NEW time — that is
    a reschedule, not a confirmation."""
    executor = _executor("ხვალ 3 საათზე", "2026-08-01T09:00:00+04:00")
    out = executor._normalise_datetime_iso_from_message(CONFIRMED_ISO)
    assert out != "2026-08-01T09:00:00+04:00"


def test_anchor_is_a_no_op_when_the_model_already_agrees():
    executor = _executor("კი დაჯავშნე", CONFIRMED_ISO)
    assert (
        executor._normalise_datetime_iso_from_message(CONFIRMED_ISO) == CONFIRMED_ISO
    )


# ── 2. manager number — Georgian syncope ───────────────────────────────────


def test_syncopated_nomri_is_an_explicit_manager_number_request():
    assert parent_flow._is_explicit_manager_number_request(LIVE_MANAGER_REQUEST)


def test_nominative_and_other_declensions_still_match():
    for message in (
        "მენეჯერის ნომერი მომწერეთ",
        "მენეჯერის ნომრის გაგზავნა შეგიძლიათ?",
        "მენეჯერის ტელეფონი მომეცით",
        "მენეჯერის კონტაქტი მინდა",
    ):
        assert parent_flow._is_explicit_manager_number_request(message), message


def test_red_dropping_the_syncopated_stem_reproduces_the_live_miss(monkeypatch):
    """RED-check: without „ნომრ" the exact live message stops matching, which is
    precisely how it reached the LLM and became a manager-callback."""
    monkeypatch.setattr(
        parent_flow,
        "_MANAGER_CONTACT_MARKERS",
        tuple(m for m in parent_flow._MANAGER_CONTACT_MARKERS if m != "ნომრ"),
    )
    assert not parent_flow._is_explicit_manager_number_request(LIVE_MANAGER_REQUEST)


def test_a_parent_supplying_their_own_number_is_not_a_manager_request():
    """The strict gate must hold: leaving a callback number is not a request
    for the manager's number."""
    assert not parent_flow._is_explicit_manager_number_request(
        "მენეჯერმა დამირეკოს, ჩემი ნომრი 595999733"
    )


def test_a_message_without_a_contact_word_is_still_not_a_number_request():
    assert not parent_flow._is_explicit_manager_number_request("მენეჯერი მინდა")


# ── 3. live prompt layers carry no markdown the model can imitate ──────────

_AGENT = Path(parent_flow.__file__).resolve().parents[1] / "agent"
# `parent_present_value.md` is deliberately ABSENT. It feeds the legacy
# composer, which is OFF in production (`USE_LLM_COMPOSER=False` in the boot
# log), so it is not a live prompt layer — and it is still byte-locked to its
# pre-migration original by `test_template_render_equivalence`. Stripping its
# markdown would have meant weakening that migration guard for a file the
# customer never sees. `system_parent.md` (engine-off fallback) is out for the
# same "not live" reason.
_LIVE_LAYERS = [
    _AGENT / "prompts" / "system_parent_v2.md",
    _AGENT / "prompts" / "system_base.md",
    _AGENT / "prompts" / "parent_lean.md",
    _AGENT / "prompts" / "parent_communication_style.md",
    _AGENT / "prompts" / "summary.md",
    _AGENT / "prompts" / "system_adult_v1.md",
    _AGENT / "policies" / "parent_sales_policy.md",
    _AGENT / "policies" / "adult_sales_policy.md",
]

_TABLE_SEPARATOR = re.compile(r"^\s*\|[\s\-:|]+\|\s*$", re.M)


def test_live_prompt_layers_carry_no_bold_markers():
    for path in _LIVE_LAYERS:
        assert path.exists(), path
        assert "**" not in path.read_text(encoding="utf-8"), (
            f"{path.name} still carries `**` — the model imitates it and "
            f"Messenger shows the asterisks literally"
        )


def test_live_prompt_layers_carry_no_markdown_tables():
    for path in _LIVE_LAYERS:
        found = _TABLE_SEPARATOR.findall(path.read_text(encoding="utf-8"))
        assert not found, f"{path.name} still carries a markdown table: {found}"


def test_skill_layer_carries_no_bold_markers():
    """`app/agent/skills/*.md` is the fourth live prompt layer (USE_SKILLS)."""
    for path in sorted((_AGENT / "skills").glob("*.md")):
        if path.name.lower() == "readme.md":
            continue
        assert "**" not in path.read_text(encoding="utf-8"), path.name


# ── 4. an empty engine turn is never silence ──────────────────────────────


def test_empty_engine_turn_never_yields_an_empty_reply(monkeypatch):
    """webhook.py drops an empty response without sending anything, so any
    path that returns "" is silence on the customer's screen. Pins the
    documented contract: engine fail/empty falls back, it does not return "".
    """
    monkeypatch.setattr(parent_flow, "_run_llm_engine_safely", lambda *a, **k: "")
    conversation = Conversation(sender_id="t-2", platform="messenger")
    out = parent_flow.handle(conversation, "რა თარიღი ვერ იპოვე ?")
    assert (out or "").strip(), "empty engine turn produced silence"
