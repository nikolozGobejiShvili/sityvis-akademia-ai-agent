"""PARENT Reschedule State + Segment Override Patch (2026-06-10).

Three live bugs (same Messenger conversation, child_age=14 already in
Redis, lead booked 12 June 10:00):

  BUG 1 — child age asked again although it was already known.
  BUG 2 — consultation reschedule misrouted to the ADULT event flow
          (segment was sticky-ADULT from earlier adult-event testing).
  BUG 3 — unqualified colloquial 1–9 hour rejected as „outside hours"
          by a direct LLM reply that bypassed the executor's PM
          normalization.

Root causes:
  * `conversation_service` only re-classifies segment when it is NOT
    already PARENT/ADULT → a sticky ADULT segment swallowed consultation
    messages.
  * the ADULT escape hatch only fires on hard camp keywords.
  * the deterministic colloquial-hour normalization lives in the
    executor (tool path); a direct LLM text reply never reached it.

Fixes (all deterministic, code-side):
  * `_is_parent_consultation_intent` overrides a sticky ADULT segment.
  * `_strip_redundant_age_question_if_known` never re-asks a known age.
  * `_repair_colloquial_hour_rejection` re-runs the slot check on the
    PM-normalized datetime and answers from the real reason.

State reuse is verified via `Conversation.from_dict` (the Redis restore
path) — the live key `conversation:messenger:<id>` round-trips child_age
/ name / phone / segment / pending reschedule with a ~7-day TTL.
"""

from __future__ import annotations

import pytest

from app.models.conversation import Conversation
from app.models.lead import Lead
from app.flows import parent_flow
from app.services import conversation_service as cs


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _booked_parent_lead(sender="s_resched") -> Lead:
    return Lead(
        sender_id=sender, platform="messenger", segment="PARENT",
        child_age="14", name="ნიკა", phone="595999733",
        calendly_booked=True, booked_datetime_iso="2026-06-12T10:00:00+04:00",
        status="Booked",
    )


def _conv(segment="ADULT", sender="s_resched", pending=None) -> Conversation:
    c = Conversation(sender_id=sender, platform="messenger")
    c.segment = segment
    c.lead = _booked_parent_lead(sender)
    c.history.append({"role": "assistant", "content": "_prior"})
    if pending is not None:
        c.pending_booking = pending
    return c


# ===========================================================================
# A. consultation/reschedule intent overrides sticky ADULT segment (BUG 2)
# ===========================================================================


@pytest.mark.parametrize("msg", [
    "კონსულტაციის გადატანა მინდა",
    "ჩვენ ჩავნიშნეთ 12 ივნის 10 საათზე და მინდა 13 ივნის 8 საათზე რომ ჩავნიშნოთ",
    "შესაძლებელია კონსულტაცია 15 ივნის 8 საათზე რომ გადავიტანოთ?",
    "ბანაკზე გეუბნები",
    "ბანაკის კონსულტაცია მაინტერესებს",
])
def test_consultation_intent_detected(msg):
    assert cs._is_parent_consultation_intent(msg) is True


@pytest.mark.parametrize("msg", [
    "ზრდასრულთა ღონისძიება მაინტერესებს",
    "კონცერტი როდის არის?",
    "გამარჯობა",
    "",
])
def test_non_consultation_not_detected(msg):
    assert cs._is_parent_consultation_intent(msg) is False


def test_sticky_adult_overridden_to_parent_on_reschedule(monkeypatch):
    """A sticky-ADULT conversation with a consultation/reschedule message
    routes to PARENT, NOT ADULT — and the known child_age is preserved."""
    routed = {"parent": 0, "adult": 0}
    monkeypatch.setattr(
        parent_flow, "handle",
        lambda conv, msg: routed.__setitem__("parent", routed["parent"] + 1) or "PARENT_REPLY",
    )
    from app.flows import adult_flow
    monkeypatch.setattr(
        adult_flow, "handle",
        lambda conv, msg: routed.__setitem__("adult", routed["adult"] + 1) or "ADULT_REPLY",
    )
    conv = _conv(segment="ADULT")
    cs.conversations[conv.sender_id] = conv
    try:
        out = cs._process_message_impl(
            conv.sender_id, "კონსულტაციის გადატანა მინდა", "messenger",
        )
    finally:
        cs.conversations.pop(conv.sender_id, None)
    assert routed["parent"] == 1 and routed["adult"] == 0
    assert conv.segment == "PARENT"
    assert conv.lead.child_age == "14"          # preserved
    assert conv.lead.phone == "595999733"        # preserved


def test_genuine_adult_question_stays_adult(monkeypatch):
    routed = {"parent": 0, "adult": 0}
    monkeypatch.setattr(
        parent_flow, "handle",
        lambda conv, msg: routed.__setitem__("parent", routed["parent"] + 1) or "P",
    )
    from app.flows import adult_flow
    monkeypatch.setattr(
        adult_flow, "handle",
        lambda conv, msg: routed.__setitem__("adult", routed["adult"] + 1) or "A",
    )
    conv = _conv(segment="ADULT", sender="s_adult")
    conv.lead.calendly_booked = False  # avoid booked→PARENT guard
    cs.conversations[conv.sender_id] = conv
    try:
        cs._process_message_impl(
            conv.sender_id, "ზრდასრულთა ღონისძიება მაინტერესებს", "messenger",
        )
    finally:
        cs.conversations.pop(conv.sender_id, None)
    assert routed["adult"] == 1 and routed["parent"] == 0
    assert conv.segment == "ADULT"


# ===========================================================================
# B. never re-ask known child age (BUG 1)
# ===========================================================================


def test_age_question_stripped_when_age_known():
    conv = _conv()
    resp = "გასაგებია, ბანაკის შესახებ დაგეხმარებით. თქვენი შვილი რამდენი წლისაა?"
    out = parent_flow._strip_redundant_age_question_if_known(conv, resp)
    assert "რამდენი წლის" not in out
    assert "ბანაკის შესახებ დაგეხმარებით" in out


def test_age_question_only_response_replaced_with_continue():
    conv = _conv()
    out = parent_flow._strip_redundant_age_question_if_known(
        conv, "თქვენი შვილი რამდენი წლისაა?",
    )
    assert "რამდენი წლის" not in out
    assert "14" in out  # acknowledges the known age
    assert out.strip() != ""


def test_age_question_kept_when_age_unknown():
    conv = _conv()
    conv.lead.child_age = ""  # genuinely unknown
    resp = "გასაგებია. თქვენი შვილი რამდენი წლისაა?"
    out = parent_flow._strip_redundant_age_question_if_known(conv, resp)
    assert out == resp


def test_no_age_question_passthrough():
    conv = _conv()
    resp = "15 ივნისი, 20:00 საათი თავისუფალია. დამიდასტურეთ."
    out = parent_flow._strip_redundant_age_question_if_known(conv, resp)
    assert out == resp


# ===========================================================================
# C. colloquial-hour outside-hours repair (BUG 3)
# ===========================================================================


def test_resolve_repair_datetime_from_message_date():
    conv = _conv()
    iso = parent_flow._resolve_repair_datetime_iso(
        conv, "15 ივნის 8 საათზე ?", 20,
    )
    # Date-bomb fix (2026-06-16): „15 ივნის" resolves to June 15 of the
    # current-or-next year (the resolver rolls a past date forward), so assert
    # the month-day + PM normalization (8 → 20:00) without pinning the year.
    assert iso is not None and "-06-15T20:00" in iso


def test_resolve_repair_datetime_time_only_uses_active_date():
    conv = _conv(pending={"requested_datetime_iso": "2026-06-15T20:00:00+04:00"})
    iso = parent_flow._resolve_repair_datetime_iso(conv, "7 საათზე ?", 19)
    assert iso is not None and "2026-06-15T19:00" in iso


def _patch_slot_check(monkeypatch, result):
    """Patch the executor slot check; capture the iso it receives."""
    captured = {}
    from app.agent.tools.parent_tool_executor import ParentToolExecutor

    def fake(self, args):
        captured["iso"] = args.get("datetime_iso")
        return result
    monkeypatch.setattr(ParentToolExecutor, "_check_consultation_slot", fake)
    return captured


def test_repair_unqualified_8_runs_check_and_reports_available(monkeypatch):
    conv = _conv()
    captured = _patch_slot_check(monkeypatch, {
        "success": True, "available": True,
        "datetime_iso": "2026-06-15T20:00:00+04:00", "reason": "",
        "alternative_slots": [],
    })
    wrong = "15 ივნისი, 8 საათზე კონსულტაციები არ ინიშნება, რადგან ეს სამუშაო საათების გარეთაა."
    out = parent_flow._repair_colloquial_hour_rejection(
        conv, "15 ივნის 8 საათზე ?", wrong,
    )
    # The slot check was invoked with the PM-normalized 20:00.
    assert captured["iso"] and "T20:00" in captured["iso"]
    # The wrong outside-hours rejection is gone; availability is reported.
    assert "არ ინიშნება" not in out
    assert "სამუშაო საათების გარეთ" not in out
    assert "თავისუფალია" in out


def test_repair_weekend_reports_weekend_not_hours(monkeypatch):
    conv = _conv()
    _patch_slot_check(monkeypatch, {
        "success": True, "available": False,
        "datetime_iso": "2026-06-13T20:00:00+04:00", "reason": "weekend",
        "alternative_slots": [],
    })
    wrong = "13 ივნისი, 8 საათზე კონსულტაციები არ ინიშნება, რადგან ეს სამუშაო საათების გარეთაა."
    out = parent_flow._repair_colloquial_hour_rejection(
        conv, "13 ივნის 8 საათზე ?", wrong,
    )
    # Saturday is now an open booking day — the weekend rejection must
    # name only Sunday and no longer say „შაბათ-კვირას".
    assert "კვირას" in out
    assert "შაბათ" not in out
    assert "სამუშაო საათების გარეთ" not in out


def test_repair_noop_for_explicit_morning(monkeypatch):
    conv = _conv()
    # If the repair were to run it would call the (patched) check; assert
    # it does NOT by leaving the patched check raising.
    from app.agent.tools.parent_tool_executor import ParentToolExecutor

    def boom(self, args):
        raise AssertionError("slot check must not run for explicit morning")
    monkeypatch.setattr(ParentToolExecutor, "_check_consultation_slot", boom)
    resp = "დილის 8 საათზე კონსულტაციები არ ინიშნება, სამუშაო საათების გარეთაა."
    out = parent_flow._repair_colloquial_hour_rejection(
        conv, "დილის 8 საათზე ?", resp,
    )
    assert out == resp  # unchanged — 08:00 is legitimately outside hours


def test_repair_noop_when_no_rejection_marker(monkeypatch):
    conv = _conv()
    from app.agent.tools.parent_tool_executor import ParentToolExecutor
    monkeypatch.setattr(
        ParentToolExecutor, "_check_consultation_slot",
        lambda self, args: (_ for _ in ()).throw(AssertionError("should not run")),
    )
    resp = "15 ივნისი, 20:00 საათი თავისუფალია. დამიდასტურეთ."
    out = parent_flow._repair_colloquial_hour_rejection(conv, "8 საათზე?", resp)
    assert out == resp


@pytest.mark.parametrize("reason, needle", [
    ("weekend", "კვირას"),
    ("calendar_busy", "დაკავებულია"),
    ("past_datetime", "წარსულ"),
])
def test_format_repaired_response_reasons(reason, needle):
    out = parent_flow._format_repaired_slot_response({
        "available": False, "reason": reason,
        "datetime_iso": "2026-06-15T20:00:00+04:00",
    })
    assert needle in out


# ===========================================================================
# D. state reuse round-trip (Redis restore path)
# ===========================================================================


def test_conversation_from_dict_preserves_parent_reschedule_state():
    d = {
        "sender_id": "27823120887291096", "platform": "messenger",
        "segment": "PARENT", "state": "START",
        "lead": {
            "sender_id": "27823120887291096", "platform": "messenger",
            "segment": "PARENT", "child_age": "14", "name": "ნიკა",
            "phone": "595999733", "calendly_booked": True,
            "booked_datetime_iso": "2026-06-12T10:00:00+04:00",
            "status": "Booked", "adult_age": "30",
        },
        "pending_booking": {
            "requested_datetime_iso": "2026-06-15T20:00:00+04:00",
            "user_confirmed_datetime": True, "source": "reschedule",
            "old_booked_datetime_iso": "2026-06-12T10:00:00+04:00",
        },
        "adult_subscription_status": "subscribed",
    }
    c = Conversation.from_dict(d)
    assert c.lead.child_age == "14"
    assert c.lead.phone == "595999733"
    assert c.segment == "PARENT"
    assert (c.pending_booking or {}).get("source") == "reschedule"
    # child_age (PARENT) and adult_age (ADULT) coexist without collision.
    assert c.lead.adult_age == "30"
