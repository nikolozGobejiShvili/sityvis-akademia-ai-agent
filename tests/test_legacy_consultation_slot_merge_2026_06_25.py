"""Legacy consultation booking slot-merge / slot-memory (live bug 2026-06-25).

Once a booking slot is known it must never be re-asked, a known set must proceed
to booking, and a confirmation („კი ჩანიშნეთ") must never be stored/echoed as a
name. Legacy/giant-prompt path (engine ON, planner+slim OFF).

Root causes fixed:
  * `_maybe_commit_pending_booking_engine` never captured child_age from the
    turn → deferred to the stochastic LLM, which re-asked the known name+phone;
  * a confirmation token parsed as a name („ჩანიშნ" not in the reject set);
  * a name-only reply relied on the LLM (the contact collector required a phone).

These tests drive the deterministic chokepoint directly (no real OpenAI). The
booking executor is mocked so no Calendar/Sheets/Meta is touched.
"""
from __future__ import annotations

import pytest

from app.agent.tools import parent_tool_executor as pte
from app.flows import parent_flow
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.services import admin_config_service
from app.services.session_key_service import conversation_cache_key


@pytest.fixture(autouse=True)
def _reset():
    pte._last_slots_by_sender.clear()
    pte.book_consultation_success_for_conversation.clear()
    yield
    pte._last_slots_by_sender.clear()
    pte.book_consultation_success_for_conversation.clear()


@pytest.fixture
def camp_registration_open(monkeypatch):
    monkeypatch.setattr(
        admin_config_service, "get_camp_registration_status", lambda: "open",
    )


@pytest.fixture
def booking_executor(monkeypatch, camp_registration_open):
    """Mock the executor's book_consultation so a complete booking 'succeeds'
    without touching Calendar/Sheets/Meta, capturing the args it was called
    with so tests can assert the stored name/phone are used."""
    captured: dict = {}

    def fake_execute(self, tool, args):
        captured["tool"] = tool
        captured["args"] = dict(args)
        if tool == "book_consultation":
            pte.book_consultation_success_for_conversation[self.cache_key] = True
            self.lead.calendly_booked = True
            self.lead.booked_datetime_iso = args.get("datetime_iso", "")
            self.conversation.state = "DONE"
            return {"success": True, "booked_date": "26 ივნისი", "booked_time": "12:00"}
        return {"success": False, "reason": "unmocked"}

    monkeypatch.setattr(pte.ParentToolExecutor, "execute", fake_execute)
    return captured


def _conv(sid="slot", *, name="", phone="", child_age=""):
    conv = Conversation(sender_id=sid, platform="instagram", segment="PARENT")
    conv.lead = Lead(
        sender_id=sid, platform="instagram", segment="PARENT",
        name=name, phone=phone, child_age=child_age,
    )
    return conv


def _offer(sid, iso="2027-06-26T12:00:00", display="26 ივნისი 12:00"):
    key = conversation_cache_key(platform="instagram", sender_id=sid)
    pte._last_slots_by_sender[key] = [{"slot_id": 1, "datetime_iso": iso, "display": display}]


def _no_name_phone_reask(out: str) -> bool:
    low = (out or "").lower()
    return ("მომწერეთ თქვენი სახელი და" not in low) and ("რომლითაც უკვე მომწერეთ" not in low)


# ── get_consultation_booking_slots source-of-truth ────────────────────────────
def test_slot_helper_merges_lead_and_pending():
    conv = _conv(name="ნიკოლოზი", phone="595999733", child_age="14")
    conv.pending_booking = {
        "requested_datetime_iso": "2027-06-26T12:00:00",
        "requested_date_text": "26 ივნისი", "requested_time_text": "12:00",
        "user_confirmed_datetime": True,
    }
    slots = parent_flow.get_consultation_booking_slots(conv)
    assert slots["parent_name"] == "ნიკოლოზი"
    assert slots["phone"] == "595999733"
    assert slots["child_age"] == "14"
    assert slots["desired_date"] == "26 ივნისი"
    assert slots["desired_time"] == "12:00"
    assert slots["missing"] == []


def test_slot_helper_reports_missing():
    conv = _conv(name="ნიკოლოზი", phone="", child_age="")
    slots = parent_flow.get_consultation_booking_slots(conv)
    assert "phone" in slots["missing"]
    assert "child_age" in slots["missing"]
    assert "parent_name" not in slots["missing"]


def test_slot_helper_rejects_confirmation_token_as_name():
    conv = _conv(name="ჩანიშნეთ", phone="595999733")  # a leaked confirmation
    slots = parent_flow.get_consultation_booking_slots(conv)
    assert slots["parent_name"] is None
    assert "parent_name" in slots["missing"]


# ── Test 1 — phone, then name, then age+time in one message ───────────────────
def test_1_age_and_time_together_books_without_reask(booking_executor):
    conv = _conv("t1", name="ნიკოლოზი", phone="595999733", child_age="")
    _offer("t1")
    out = parent_flow._maybe_commit_pending_booking_engine(
        conv, "ჩემი შვილი 14 წლის არის და 26 ში 12:00 საათზე მაწყობს",
    )
    assert conv.lead.child_age == "14"
    assert conv.lead.name == "ნიკოლოზი"
    assert conv.lead.phone == "595999733"
    assert conv.lead.calendly_booked is True            # booked, not re-asked
    assert _no_name_phone_reask(out)
    assert booking_executor["args"]["name"] == "ნიკოლოზი"
    assert "14" in str(booking_executor["args"]["child_age"])


# ── Test 2 — confirmation does not become the name ────────────────────────────
def test_2_confirmation_not_stored_as_name(booking_executor):
    conv = _conv("t2", name="ნიკოლოზი", phone="595999733", child_age="14")
    conv.pending_booking = {
        "requested_datetime_iso": "2027-06-26T12:00:00",
        "requested_date_text": "26 ივნისი", "requested_time_text": "12:00",
        "user_confirmed_datetime": True, "source": "user_selected_slot",
    }
    out = parent_flow._maybe_commit_pending_booking_engine(conv, "კი ჩანიშნეთ")
    assert conv.lead.calendly_booked is True
    assert conv.lead.name == "ნიკოლოზი"                 # not overwritten
    assert booking_executor["args"]["name"] == "ნიკოლოზი"
    assert "ჩანიშნეთ" != conv.lead.name
    assert "მივიღე, ჩანიშნ" not in (out or "")
    assert "მივიღე, კი" not in (out or "")
    # the confirmation phrase is not a valid name
    assert parent_flow._parse_name_phone("კი ჩანიშნეთ") == ("", "")


# ── Test 3 — all info in one message ──────────────────────────────────────────
def test_3_all_info_one_message(booking_executor):
    conv = _conv("t3")
    out = parent_flow._maybe_commit_pending_booking_engine(
        conv, "ნიკოლოზი 595999733, ჩემი შვილი 14 წლის არის და 26 ივნისს 12:00 მაწყობს",
    )
    assert conv.lead.name == "ნიკოლოზი"
    assert conv.lead.phone == "595999733"
    assert conv.lead.child_age == "14"
    slots = parent_flow.get_consultation_booking_slots(conv)
    assert "parent_name" not in slots["missing"]
    assert "phone" not in slots["missing"]
    assert "child_age" not in slots["missing"]
    assert conv.lead.calendly_booked is True


# ── Test 4 — name+phone+age known, user gives only the time → book ─────────────
def test_4_only_time_given_books(booking_executor):
    conv = _conv("t4", name="ნიკოლოზი", phone="595999733", child_age="14")
    _offer("t4")
    out = parent_flow._maybe_commit_pending_booking_engine(conv, "12:00 მაწყობს")
    assert _no_name_phone_reask(out)
    assert conv.lead.calendly_booked is True
    assert booking_executor["args"]["name"] == "ნიკოლოზი"


# ── Test 5 — only phone missing → ask only for phone ──────────────────────────
def test_5_only_phone_missing_asks_phone(booking_executor):
    conv = _conv("t5", name="ნიკოლოზი", phone="", child_age="14")
    _offer("t5")
    out = parent_flow._maybe_commit_pending_booking_engine(conv, "12:00 მაწყობს")
    assert out is not None
    assert "ნომერ" in out                                # asks for the number
    assert "მომწერეთ თქვენი სახელი და" not in out        # not name+phone
    assert conv.lead.calendly_booked is False            # not booked yet


# ── Test 6 — only name missing → ask only for name ────────────────────────────
def test_6_only_name_missing_asks_name(booking_executor):
    conv = _conv("t6", name="", phone="595999733", child_age="14")
    _offer("t6")
    out = parent_flow._maybe_commit_pending_booking_engine(conv, "12:00 მაწყობს")
    assert out is not None
    assert "სახელ" in out                                # asks for the name
    assert conv.lead.calendly_booked is False


# ── name-only reply captured deterministically (real-transcript step 3) ───────
def test_name_only_reply_captured_after_name_ask():
    conv = _conv("tn", phone="595999733", child_age="")
    conv.history = [
        {"role": "assistant", "content": "ნომერი მივიღე. მომწერეთ თქვენი სახელი, რომ კონსულტაცია ჩავნიშნოთ."},
    ]
    out = parent_flow._maybe_handle_contact_collection(conv, "ნიკოლოზი")
    assert conv.lead.name == "ნიკოლოზი"
    assert out is not None


def test_question_with_pending_not_hijacked(booking_executor):
    # A question asked while a slot is pending must NOT be turned into a
    # contact ask — only one slot missing but the turn did not advance booking.
    conv = _conv("tq", name="ნიკოლოზი", phone="", child_age="14")
    conv.pending_booking = {
        "requested_datetime_iso": "2027-06-26T12:00:00",
        "requested_date_text": "26 ივნისი", "requested_time_text": "12:00",
        "user_confirmed_datetime": True,
    }
    out = parent_flow._maybe_commit_pending_booking_engine(
        conv, "მენეჯერი რომელ საათამდე მუშაობს?",
    )
    assert out is None                                   # deferred, not hijacked
