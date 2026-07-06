"""Deterministic hardening patch — 7 confirmed live/latent bugs (2026-07-06).

BUG 1 — price grammar („გადახდა ბანაკში N ლარია" → „ბანაკის ღირებულება N ლარია").
BUG 2 — unknown reservation FEE amount → manager defer (never invented).
BUG 3 — name overwrite: generic words rejected as names; a valid name is never
        overwritten by a tool echo.
BUG 4 — time grammar („რომელი დრო გირჩევთ" → „…გირჩევნიათ").
BUG 5 — booking confirmation is deterministic, never carries „მოგწერეთ".
BUG 6 — consultation slots come from the REAL calendar (no invented examples).
BUG 7 — Georgian Latin translit availability routes to the free-slot flow.

Plus regression guards for c98a5d9 (multi-child) and 742bad1 (name ack / plural
grammar / forbidden phrase). Calendar/FreeBusy is mocked; no real LLM/API call.
"""
from __future__ import annotations

import dataclasses
from datetime import datetime

import pytest

import app.config as config_module
from app.agent.llm.parent_llm_engine import sanitise_response_wording
from app.flows import parent_flow
from app.models.conversation import Conversation
from app.models.lead import Lead

_MANAGER = "558 67 47 33"


# ── shared helpers ────────────────────────────────────────────────────────────
def _parent_conv(sid="dh", *, state="", name="", phone="", child_age="",
                 challenge="", pending=None, history=None) -> Conversation:
    c = Conversation(sender_id=sid, platform="instagram", segment="PARENT")
    if state:
        c.state = state
    c.lead = Lead(sender_id=sid, platform="instagram", segment="PARENT",
                  name=name, phone=phone, child_age=child_age, challenge=challenge)
    if pending is not None:
        c.pending_booking = pending
    for turn in history or []:
        c.history.append(turn)
    return c


@pytest.fixture
def mock_calendar(monkeypatch):
    """Deterministic FreeBusy: hourly slots 10:00–20:00 on any day, not Sunday,
    fixed Tuesday `now`. Returns a handle so a test can override the slot set."""
    from app.services import calendar_service

    state = {"slots": [{"date": "d", "time": f"{h:02d}:00"} for h in range(10, 21)]}

    def _slots(day):
        return list(state["slots"])

    monkeypatch.setattr(calendar_service, "get_free_slots", _slots)
    monkeypatch.setattr(calendar_service, "is_closed_booking_day", lambda now: False)
    monkeypatch.setattr(
        calendar_service, "now_tbilisi",
        lambda: datetime(2026, 7, 7, 9, 0, tzinfo=calendar_service.TIMEZONE),
    )
    return state


def _booking_ctx_conv(sid="bkctx"):
    """A conversation where the bot just asked for the consultation date/time."""
    return _parent_conv(
        sid, state="OFFER_BOOKING", name="სალომე", phone="558914814", child_age="14",
        history=[{"role": "assistant",
                  "content": "რომელი დღე და დრო გირჩევნიათ კონსულტაციისთვის?"}],
    )


# ══ BUG 1 — price grammar ════════════════════════════════════════════════════
def test_bug1_gadaxda_bankshi_normalised():
    out = sanitise_response_wording("გადახდა ბანაკში 2150 ლარია.")
    assert "გადახდა ბანაკში" not in out
    assert "ბანაკის ღირებულება 2150 ლარია" in out


def test_bug1_bare_bankshi_price_normalised():
    out = sanitise_response_wording("ბანაკში 2150 ლარია, დანარჩენს მენეჯერი გეტყვით.")
    assert "ბანაკში 2150 ლარია" not in out
    assert "ბანაკის ღირებულება 2150 ლარია" in out


def test_bug1_price_normalisation_is_idempotent():
    once = sanitise_response_wording("გადახდა ბანაკში 2150 ლარია.")
    assert sanitise_response_wording(once) == once


def test_bug1_good_price_wording_untouched():
    good = "ბანაკის ღირებულება 2150 ლარია."
    assert sanitise_response_wording(good) == good


# ══ BUG 2 — unknown reservation fee → manager defer ══════════════════════════
@pytest.mark.parametrize("q", [
    "ჯავშნის საფასური რამდენია?",
    "რამდენია ჯავშანი?",
    "რამდენი უნდა გადავიხადო დასაჯავშნად?",
])
def test_bug2_reservation_fee_defers_to_manager(q):
    out = parent_flow._maybe_handle_reservation_fee_question(_parent_conv(), q)
    assert out == (
        "რაც შეეხება ჯავშნის საფასურს, ამ დეტალებს მენეჯერი გაგაცნობთ: " + _MANAGER
    )


def test_bug2_does_not_invent_fee_wording():
    out = parent_flow._maybe_handle_reservation_fee_question(
        _parent_conv(), "ჯავშნის საფასური რამდენია?",
    )
    assert "სრული ბანაკის ღირებულების ნაწილი" not in out
    assert _MANAGER in out


def test_bug2_payment_method_question_not_hijacked():
    # A payment-METHOD question keeps its own answer (not the fee defer).
    assert parent_flow._maybe_handle_reservation_fee_question(
        _parent_conv(), "როგორ ხდება გადახდა?",
    ) is None


def test_bug2_consultation_price_not_hijacked():
    # „how much is the consultation" has no reservation reference → not this handler.
    assert parent_flow._maybe_handle_reservation_fee_question(
        _parent_conv(), "რამდენი ღირს კონსულტაცია?",
    ) is None


# ══ BUG 3 — unknown-detail fallback regression (room distribution) ═══════════
def test_bug3grp_room_detail_still_manager_fallback():
    out = parent_flow._maybe_handle_unknown_operational_early(
        _parent_conv(), "ოთახში რამდენი ბავშვი იქნება?",
    )
    assert out is not None
    assert "მენეჯერი გაგაცნობთ" in out
    assert _MANAGER in out
    # …and it is NOT the reservation-fee (booking) handler.
    assert parent_flow._maybe_handle_reservation_fee_question(
        _parent_conv(), "ოთახში რამდენი ბავშვი იქნება?",
    ) is None


# ══ BUG 3 — name overwrite / data corruption ═════════════════════════════════
@pytest.mark.parametrize("word,valid", [
    ("მოგწერეთ", False), ("მომწერეთ", False), ("გასაგებია", False),
    ("გასაგები", False), ("ნებისმიერი", False), ("ხვალ", False),
    ("სულ ერთია", False), ("მადლობა", False),
    ("მარიამი", True), ("ნინო", True), ("სულიკო", True),
])
def test_bug3_name_validator(word, valid):
    assert parent_flow.is_valid_person_name(word) is valid


def test_bug3_save_lead_info_never_overwrites_valid_name():
    from app.agent.tools.parent_tool_executor import ParentToolExecutor
    lead = Lead(sender_id="n", platform="instagram", segment="PARENT", name="მარიამი")
    conv = _parent_conv("n", name="მარიამი")
    conv.lead = lead
    ex = ParentToolExecutor(conversation=conv, lead=lead, sender_id="n", platform="instagram")
    res = ex.execute("save_lead_info", {"name": "მოგწერეთ"})
    assert lead.name == "მარიამი"            # existing valid name preserved
    assert "name" not in (res.get("saved") or [])


def test_bug3_save_lead_info_sets_name_when_absent():
    from app.agent.tools.parent_tool_executor import ParentToolExecutor
    lead = Lead(sender_id="n2", platform="instagram", segment="PARENT")
    conv = _parent_conv("n2")
    conv.lead = lead
    ex = ParentToolExecutor(conversation=conv, lead=lead, sender_id="n2", platform="instagram")
    ex.execute("save_lead_info", {"name": "ნინო"})
    assert lead.name == "ნინო"               # first valid name still captured


def test_bug3_phone_then_name_then_generic_keeps_real_name():
    # phone captured → name captured → a later generic echo must NOT overwrite it.
    conv = _parent_conv(
        "flow", name="მარიამი", phone="595999733",
        history=[{"role": "assistant",
                  "content": "მადლობა, მარიამი. რომელი დღე და დრო გირჩევნიათ?"}],
    )
    from app.agent.tools.parent_tool_executor import ParentToolExecutor
    ex = ParentToolExecutor(conversation=conv, lead=conv.lead, sender_id="flow", platform="instagram")
    ex.execute("save_lead_info", {"name": "გასაგებია"})
    assert conv.lead.name == "მარიამი"


# ══ BUG 4 — time-choice grammar ══════════════════════════════════════════════
def test_bug4_time_grammar_gircevt_to_gircevniat():
    out = sanitise_response_wording("რომელი დრო გირჩევთ?")
    assert "რომელი დრო გირჩევთ" not in out
    assert "რომელი დრო გირჩევნიათ?" in out


def test_bug4_correct_time_grammar_untouched():
    good = "რომელი დრო გირჩევნიათ?"
    assert sanitise_response_wording(good) == good


# ══ BUG 5 — booking confirmation ═════════════════════════════════════════════
def test_bug5_sanitiser_strips_mogweret_from_confirmation():
    out = sanitise_response_wording(
        "მივიღე, მოგწერეთ კონსულტაცია 7 ივლისს, 10:00 საათზე ჩაგინიშნეთ. "
        "მენეჯერი დაგიკავშირდებათ."
    )
    assert "მოგწერეთ" not in out
    assert "ჩაგინიშნეთ" in out


def _commit_with_name(monkeypatch, name: str) -> str:
    """Drive `_maybe_commit_pending_booking_engine` to a mocked booking success
    with the given stored name, and return the confirmation string."""
    from app.agent.tools import parent_tool_executor as pte

    def _fake_execute(self, tool, args):
        return {"success": True, "booked_date": "7 ივლისს", "booked_time": "10:00"}

    monkeypatch.setattr(pte.ParentToolExecutor, "execute", _fake_execute)
    conv = _parent_conv(
        "commit", name=name, phone="595999733", child_age="14",
        pending={"user_confirmed_datetime": True,
                 "requested_datetime_iso": "2030-07-07T10:00:00+04:00"},
    )
    return parent_flow._maybe_commit_pending_booking_engine(conv, "კი")


def test_bug5_success_confirmation_is_deterministic_and_clean(monkeypatch):
    out = _commit_with_name(monkeypatch, "მარიამი")
    assert out is not None
    assert "ჩაგინიშნეთ" in out                 # deterministic confirmation owns the turn
    assert "მოგწერეთ" not in out
    assert "მარიამი" in out                     # a valid name is greeted


def test_bug5_corrupted_name_never_leaks_into_confirmation(monkeypatch):
    # Defense-in-depth: with an invalid stored name the commit REFUSES to book
    # (returns None), and the confirmation-name guard means „მოგწერეთ" can never
    # surface as „მივიღე, მოგწერეთ …". Either way the bad name never reaches the
    # user in a confirmation.
    out = _commit_with_name(monkeypatch, "მოგწერეთ")
    assert out is None or "მოგწერეთ" not in out


# ══ BUG 6 — calendar-driven slot suggestions ═════════════════════════════════
def test_bug6_day_reply_offers_only_real_slots(mock_calendar):
    out = parent_flow._maybe_handle_booking_datetime_reply(_booking_ctx_conv(), "ხვალ")
    assert "თავისუფალია" in out
    assert "რომელი დრო გირჩევნიათ" in out
    # only the mocked free times are offered; nothing else invented.
    assert "10:00" in out and "11:00" in out and "12:00" in out
    assert "მაგალითად" not in out              # no hardcoded example list
    assert "მენეჯერი დაგიზუსტებ" not in out    # never manager fallback for scheduling


def test_bug6_evening_daypart_filters_to_evening_slots(mock_calendar):
    out = parent_flow._maybe_handle_booking_datetime_reply(
        _booking_ctx_conv(), "ორშაბათს, საღამოს საათებში",
    )
    assert ("17:00" in out) or ("18:00" in out) or ("19:00" in out)
    assert "10:00" not in out                   # morning slots excluded by daypart


def test_bug6_busy_example_slot_never_offered(mock_calendar):
    # Calendar has ONLY 15:00 free → an unchecked „12:00/18:00" is never offered.
    mock_calendar["slots"] = [{"date": "d", "time": "15:00"}]
    out = parent_flow._maybe_handle_booking_datetime_reply(_booking_ctx_conv(), "ხვალ")
    assert "15:00" in out
    assert "12:00" not in out and "18:00" not in out


def test_bug6_calendar_outage_uses_technical_fallback_not_manager(mock_calendar):
    from app.services import calendar_service

    def _boom(day):
        raise RuntimeError("calendar down")

    calendar_service.get_free_slots = _boom
    out = parent_flow._maybe_handle_booking_datetime_reply(_booking_ctx_conv(), "ხვალ")
    assert "ვერ ხერხდება" in out                # technical retry line
    assert "მენეჯერ" not in out                 # NOT a manager handoff


def test_bug6_exact_time_defers_to_booking_flow(mock_calendar):
    # An exact time still defers (None) so the booking commit/engine books it.
    assert parent_flow._maybe_handle_booking_datetime_reply(
        _booking_ctx_conv(), "ხვალ 6-ზე",
    ) is None


# ══ BUG 7 + flexible availability ════════════════════════════════════════════
@pytest.mark.parametrize("msg", [
    "ნებისმიერი დრო",
    "ნებისმიერ დროს შეგიძლიათ დამირეკოთ",
    "სულ ერთია",
    "sul ertia nebismier dros mcalia",
])
def test_bug7_flexible_and_translit_offer_real_slots(mock_calendar, msg):
    out = parent_flow._maybe_handle_booking_datetime_reply(_booking_ctx_conv(), msg)
    assert out is not None
    assert "თავისუფალია" in out                 # real slots, not clarification
    assert "10:00" in out                       # from the mocked free set
    assert "მენეჯერ" not in out                 # not a manager route
    assert "ვერ გავიგე" not in out              # not a clarification ask


def test_bug7_flexible_detector_matches_translit():
    assert parent_flow._looks_like_flexible_availability("sul ertia nebismier dros mcalia")
    assert parent_flow._looks_like_flexible_availability("ნებისმიერი დრო")
    assert not parent_flow._looks_like_flexible_availability("ხვალ 10 საათზე")


# ══ Regression — c98a5d9 (multi-child) ═══════════════════════════════════════
def test_regression_multi_child_records_both_ages():
    conv = _parent_conv("mc")
    out = parent_flow._maybe_handle_multi_child_age(conv, "12-14 წლის")
    assert out is not None
    assert conv.lead.child_age == "12"
    assert "ორი შვილი: 12 და 14 წლის" in conv.lead.deeper_concern


def test_regression_band_9_17_not_captured():
    conv = _parent_conv("band")
    assert parent_flow._maybe_handle_multi_child_age(conv, "9-17 წლის") is None
    assert conv.lead.child_age == ""


def test_regression_booking_not_reask_age_once_known():
    conv = _parent_conv("age", child_age="12")
    reply = "კარგი, რომელი დღე გირჩევნიათ?"
    assert parent_flow._ensure_camp_age_question(conv, "რაიმე", reply) == reply


# ══ Regression — 742bad1 (name ack / plural grammar / forbidden phrase) ══════
def test_regression_742_name_after_phone_no_number_repeat():
    conv = _parent_conv(
        "742", name="", phone="595999733",
        history=[{"role": "user", "content": "595999733"},
                 {"role": "assistant",
                  "content": "ნომერი მივიღე. მომწერეთ თქვენი სახელი, "
                             "რომ კონსულტაცია ჩავნიშნოთ."}],
    )
    out = parent_flow._maybe_handle_contact_collection(conv, "მარიამი")
    assert out is not None
    assert conv.lead.name == "მარიამი"
    assert "ნომერი მივიღე" not in out
    assert "რომელი დღე და დრო" in out


def test_regression_742_plural_children_grammar():
    out = sanitise_response_wording("რა ასაკის შვილები გაქვთ?")
    assert "შვილები გაქვთ" not in out
    assert "შვილები გყავთ" in out


def test_regression_742_forbidden_empathy_phrase_absent():
    out = sanitise_response_wording("მესმის, ეს გასაგები მოთხოვნაა. ბანაკი ეხმარება.")
    assert "ეს გასაგები მოთხოვნაა" not in out
    assert "გასაგებია" in out
