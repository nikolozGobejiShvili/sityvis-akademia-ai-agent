"""Follow-up Scheduler — local QA simulation.

Runs the live `followup_service.check_and_send_followups()` against
seeded in-memory conversations and prints what WOULD be sent. The
Meta send path is mocked — no real Instagram / Messenger DM is
delivered, ever. The script is safe to run against the live `.env`.

Scenarios:

  A) 24h eligible   → expects `followup_24h` send + stage = first_24h
  B) 3d eligible    → expects `followup_3d` send + stage = second_3d
  C) 7d eligible    → expects `followup_7d` send + stage = third_7d
                      + followup_blocked_reason = followup_exhausted
  D) not-yet (<24h) → no send, stage stays ""
  E) booked         → no send (lead.calendly_booked=True)
  F) declined       → no send (followup_blocked_reason="declined")
  G) kill switch    → no send (AGENT_ENABLED=false)

Stage values are STRINGS that match the keys in
`app/agent/knowledge/followup_strategy.yaml`:

    ""           # initial / unsent
    "first_24h"  # after 24h send
    "second_3d"  # after 72h send
    "third_7d"   # after 168h send (terminal)

Run with:

    PYTHONIOENCODING=utf-8 python tools/sim_followup.py --case all
    PYTHONIOENCODING=utf-8 python tools/sim_followup.py --case 24h
    PYTHONIOENCODING=utf-8 python tools/sim_followup.py --case kill_switch

The Meta send is replaced by a recorder; the script prints sender_id,
platform, and message preview for each would-be send.
"""

from __future__ import annotations

import argparse
import dataclasses
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import app.config as config_module  # noqa: E402
from app.models.conversation import Conversation  # noqa: E402
from app.models.lead import Lead  # noqa: E402
from app.services import (  # noqa: E402
    comment_service,
    conversation_service,
    followup_service,
    kill_switch,
    messenger_service,
)


# -- mocked send -----------------------------------------------------------


_RECORDED_SENDS: list[dict] = []


def _fake_send_message(*, sender_id: str, platform: str, text: str) -> bool:
    _RECORDED_SENDS.append({
        "sender_id": sender_id,
        "platform": platform,
        "text": text,
    })
    return True


def _install_send_mock() -> None:
    """Replace the real Meta send with the recorder. Patches BOTH
    `messenger_service.send_message` (in case any other module imports
    the function symbol) AND `followup_service.messenger_service`'s
    handle, mirroring the test-suite pattern."""
    from types import SimpleNamespace

    messenger_service.send_message = _fake_send_message  # type: ignore[assignment]
    followup_service.messenger_service = SimpleNamespace(
        send_message=_fake_send_message,
    )


# -- agent kill switch helpers --------------------------------------------


def _set_agent_enabled(value: bool) -> None:
    """Swap the per-module settings reference the same way the test
    suite does. Doesn't mutate the global Settings dataclass."""
    swapped = dataclasses.replace(config_module.settings, AGENT_ENABLED=value)
    kill_switch.settings = swapped
    followup_service.settings = swapped
    comment_service.settings = swapped


# -- conversation factory --------------------------------------------------


def _seed_conversation(
    *,
    sender_id: str,
    last_bot_offset: timedelta | None,
    followup_stage: str = "",
    followup_blocked_reason: str = "",
    booked: bool = False,
    segment: str = "PARENT",
    platform: str = "instagram",
    name: str = "ნინო",
) -> Conversation:
    conv = Conversation(sender_id=sender_id, platform=platform)
    conv.segment = segment
    conv.state = "ASK_NAME"
    conv.followup_stage = followup_stage
    conv.followup_blocked_reason = followup_blocked_reason
    if last_bot_offset is not None:
        ts = datetime.utcnow() - last_bot_offset
        conv.last_bot_message_at = ts.isoformat()
    lead = Lead(sender_id=sender_id, platform=platform, segment=segment)
    lead.name = name
    lead.calendly_booked = booked
    conv.lead = lead
    conversation_service.conversations[sender_id] = conv
    return conv


# -- reporting -------------------------------------------------------------


def _reset_state() -> None:
    _RECORDED_SENDS.clear()
    conversation_service.conversations.clear()


def _report(case: str, conv: Conversation, expected_send: bool) -> bool:
    """Print before/after snapshot and return True iff the result
    matches expectation."""
    sent_now = [s for s in _RECORDED_SENDS if s["sender_id"] == conv.sender_id]
    actual_send = bool(sent_now)
    pass_send = actual_send == expected_send

    print(f"\n--- {case} ---")
    print(f"  sender_id           = {conv.sender_id}")
    print(f"  platform            = {conv.platform}")
    print(f"  segment             = {conv.segment}")
    print(f"  stage_after_tick    = {conv.followup_stage!r}")
    print(f"  blocked_reason      = {conv.followup_blocked_reason!r}")
    print(f"  send_attempted      = {actual_send}   (expected {expected_send})")
    for s in sent_now:
        preview = s["text"].replace("\n", " ⏎ ")
        if len(preview) > 80:
            preview = preview[:77] + "…"
        print(f"  sent_text_preview   = {preview}")
        print(f"  send_platform       = {s['platform']}")
    status = "✅ PASS" if pass_send else "❌ FAIL"
    print(f"  result              = {status}")
    return pass_send


# -- scenarios -------------------------------------------------------------


def scenario_24h_eligible() -> bool:
    _reset_state()
    _set_agent_enabled(True)
    conv = _seed_conversation(
        sender_id="test-user-followup-24h",
        last_bot_offset=timedelta(hours=25),
        followup_stage="",
    )
    followup_service.check_and_send_followups()
    ok = _report("A — 24h eligible", conv, expected_send=True)
    ok = ok and conv.followup_stage == "first_24h"
    print(f"  stage_advanced_ok   = {conv.followup_stage == 'first_24h'}")
    return ok


def scenario_3d_eligible() -> bool:
    _reset_state()
    _set_agent_enabled(True)
    conv = _seed_conversation(
        sender_id="test-user-followup-3d",
        last_bot_offset=timedelta(hours=73),
        followup_stage="first_24h",
    )
    followup_service.check_and_send_followups()
    ok = _report("B — 3d eligible", conv, expected_send=True)
    ok = ok and conv.followup_stage == "second_3d"
    print(f"  stage_advanced_ok   = {conv.followup_stage == 'second_3d'}")
    return ok


def scenario_7d_eligible() -> bool:
    _reset_state()
    _set_agent_enabled(True)
    conv = _seed_conversation(
        sender_id="test-user-followup-7d",
        last_bot_offset=timedelta(hours=170),
        followup_stage="second_3d",
    )
    followup_service.check_and_send_followups()
    ok = _report("C — 7d eligible", conv, expected_send=True)
    ok = ok and conv.followup_stage == "third_7d"
    ok = ok and conv.followup_blocked_reason == "followup_exhausted"
    print(f"  stage_advanced_ok   = {conv.followup_stage == 'third_7d'}")
    print(f"  exhausted_marker_ok = {conv.followup_blocked_reason == 'followup_exhausted'}")
    return ok


def scenario_not_yet() -> bool:
    _reset_state()
    _set_agent_enabled(True)
    conv = _seed_conversation(
        sender_id="test-user-followup-not-yet",
        last_bot_offset=timedelta(hours=12),
        followup_stage="",
    )
    followup_service.check_and_send_followups()
    ok = _report("D — not-yet (<24h)", conv, expected_send=False)
    ok = ok and conv.followup_stage == ""
    return ok


def scenario_booked() -> bool:
    _reset_state()
    _set_agent_enabled(True)
    conv = _seed_conversation(
        sender_id="test-user-followup-booked",
        last_bot_offset=timedelta(hours=25),
        followup_stage="",
        booked=True,
    )
    followup_service.check_and_send_followups()
    ok = _report("E — booked lead", conv, expected_send=False)
    return ok


def scenario_declined() -> bool:
    _reset_state()
    _set_agent_enabled(True)
    conv = _seed_conversation(
        sender_id="test-user-followup-declined",
        last_bot_offset=timedelta(hours=25),
        followup_stage="",
        followup_blocked_reason="declined",
    )
    followup_service.check_and_send_followups()
    ok = _report("F — declined", conv, expected_send=False)
    return ok


def scenario_kill_switch() -> bool:
    _reset_state()
    _set_agent_enabled(False)
    conv = _seed_conversation(
        sender_id="test-user-followup-killed",
        last_bot_offset=timedelta(hours=25),
        followup_stage="",
    )
    followup_service.check_and_send_followups()
    ok = _report("G — kill switch (AGENT_ENABLED=false)", conv, expected_send=False)
    ok = ok and conv.followup_stage == ""
    return ok


def scenario_messenger_platform() -> bool:
    """Sanity: Messenger conversations route through send_message with
    platform='messenger'."""
    _reset_state()
    _set_agent_enabled(True)
    conv = _seed_conversation(
        sender_id="test-user-followup-messenger",
        last_bot_offset=timedelta(hours=25),
        followup_stage="",
        platform="messenger",
    )
    followup_service.check_and_send_followups()
    ok = _report("H — messenger platform routing", conv, expected_send=True)
    ok = ok and any(
        s["platform"] == "messenger"
        for s in _RECORDED_SENDS if s["sender_id"] == conv.sender_id
    )
    return ok


# -- CLI -------------------------------------------------------------------


_CASES: dict[str, tuple[str, callable]] = {
    "24h": ("24h eligible", scenario_24h_eligible),
    "3d": ("3d eligible", scenario_3d_eligible),
    "7d": ("7d eligible (exhausted)", scenario_7d_eligible),
    "not_yet": ("not-yet skip", scenario_not_yet),
    "booked": ("booked skip", scenario_booked),
    "declined": ("declined skip", scenario_declined),
    "kill_switch": ("kill switch skip", scenario_kill_switch),
    "messenger": ("messenger platform routing", scenario_messenger_platform),
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument(
        "--case", default="all",
        help="Scenario id: " + ", ".join(_CASES) + ", or 'all'",
    )
    args = parser.parse_args()

    _install_send_mock()

    cases: list[str]
    if args.case == "all":
        cases = list(_CASES)
    elif args.case in _CASES:
        cases = [args.case]
    else:
        print(f"Unknown case: {args.case!r}. Choose from {list(_CASES)} or 'all'.")
        return 2

    print("=" * 64)
    print("Follow-up Scheduler — local QA simulation")
    print("Mocked send: no real Meta DM will be delivered.")
    print("=" * 64)

    results: list[tuple[str, bool]] = []
    for case_id in cases:
        label, runner = _CASES[case_id]
        ok = runner()
        results.append((label, ok))

    print()
    print("=" * 64)
    print("Summary")
    print("=" * 64)
    pass_count = sum(1 for _, ok in results if ok)
    for label, ok in results:
        mark = "✅" if ok else "❌"
        print(f"  {mark} {label}")
    print()
    print(f"  {pass_count} / {len(results)} scenarios passed")

    # Ensure we leave AGENT_ENABLED in the live state.
    _set_agent_enabled(True)
    return 0 if pass_count == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
