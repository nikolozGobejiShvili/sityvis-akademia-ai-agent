"""Live Bugfix (2026-06-11) — PARENT contact extraction, booking state,
and challenge save-path cleanup.

Covers four live bugs found in production conversations:

  * LIVE BUG 1 — a contact-only message („ჯონი 595999733") triggered a
    booking against a STALE confirmed pending slot („16:45 წარსული
    დროა"). The engine pending-commit path must never auto-book a past
    datetime; it saves the contact and asks for a fresh time instead.
  * LIVE BUG 2 — a month/date/time/booking word was captured as the
    parent's name („595999733 16 ივნის მინდა 10 საათზე" → name=„ივნის").
    The name parser + every save chokepoint now reject those tokens.
  * LIVE BUG 3 — „თქვენი სახელი უკვე ვიცი" for an invalid stored name.
    A stored name that is actually a month/date artifact is cleared
    before the engine builds its context; adult-subscription data is
    never used as PARENT contact data.
  * LIVE BUG 4 — a tacked-on factual question polluted the Sheets
    challenge column. The SAVE chokepoint (not only the email rendering)
    now strips the question, keeping only the camp goal.

All external services are mocked. Tests must pass with no network.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.agent.llm.parent_llm_engine import (
    clean_challenge_for_storage,
    maybe_capture_challenge_fallback,
    maybe_capture_child_age_fallback,
)
from app.agent.tools import parent_tool_executor
from app.agent.tools.parent_tool_executor import ParentToolExecutor
from app.flows import parent_flow
from app.flows.parent_flow import (
    TBILISI_TZ,
    _maybe_commit_pending_booking_engine,
    _parse_name_phone,
    _sanitise_invalid_stored_name,
    is_valid_person_name,
)
from app.models.conversation import Conversation
from app.models.lead import Lead


# -- helpers ---------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_executor_state():
    parent_tool_executor.reset_state()
    yield
    parent_tool_executor.reset_state()


def _conv(**kwargs) -> Conversation:
    conv = Conversation(sender_id=kwargs.pop("sender_id", "sender_bugfix"),
                        platform=kwargs.pop("platform", "instagram"))
    conv.segment = kwargs.pop("segment", "PARENT")
    conv.state = kwargs.pop("state", "START")
    for key, value in kwargs.items():
        setattr(conv, key, value)
    return conv


def _lead(conv: Conversation, **kwargs) -> Lead:
    lead = Lead(sender_id=conv.sender_id, platform=conv.platform, segment="PARENT")
    for key, value in kwargs.items():
        setattr(lead, key, value)
    conv.lead = lead
    return lead


def _future_weekday_iso(hour: int = 11) -> str:
    """A future weekday datetime inside business hours (Tbilisi)."""
    d = datetime.now(TBILISI_TZ) + timedelta(days=3)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d.replace(hour=hour, minute=0, second=0, microsecond=0).isoformat()


def _stale_iso(hour: int = 16, minute: int = 45) -> str:
    """A clearly-past datetime (yesterday) — the live „16:45" shape."""
    d = datetime.now(TBILISI_TZ) - timedelta(days=1)
    return d.replace(hour=hour, minute=minute, second=0, microsecond=0).isoformat()


def _confirmed_pending(iso: str, **extra) -> dict:
    pending = {
        "requested_datetime_iso": iso,
        "requested_date_text": "ხვალ",
        "requested_time_text": "11:00",
        "user_confirmed_datetime": True,
        "source": "user_requested_exact_slot",
        "created_at": "2026-06-11T10:00:00",
        "attempts": 0,
        "missing_fields": [],
    }
    pending.update(extra)
    return pending


def _install_fake_booking(monkeypatch) -> dict:
    """Patch the Calendar write so a successful booking stamps the lead.

    Returns a dict whose ``called`` flag flips True if a real book is
    attempted (used to assert booking did NOT happen on stale paths)."""
    state = {"called": False, "booked_iso": ""}

    def _fake_book_selected_slot(conversation, lead, slot):
        state["called"] = True
        state["booked_iso"] = slot.get("datetime_iso", "")
        lead.calendly_booked = True
        lead.booked_datetime_iso = slot.get("datetime_iso", "")
        lead.calendar_event_id = "evt_test_id"
        lead.status = "Booked"
        conversation.state = "DONE"
        return True

    monkeypatch.setattr(parent_flow, "_book_selected_slot", _fake_book_selected_slot)

    from app.services import calendar_service
    monkeypatch.setattr(calendar_service, "check_slot_available", lambda *_a, **_k: True)
    return state


# ===========================================================================
# Contact extraction tests
# ===========================================================================


def test_01_contact_only_saves_name_and_phone_no_booking(monkeypatch):
    """„ჯონი 595999733" after a contact request: name + phone saved, NO
    booking attempted against a stale slot."""
    booking = _install_fake_booking(monkeypatch)
    conv = _conv()
    lead = _lead(conv, child_age="12")
    conv.pending_booking = _confirmed_pending(_stale_iso())

    reply = _maybe_commit_pending_booking_engine(conv, "ჯონი 595999733")

    assert lead.name == "ჯონი"
    assert lead.phone == "595999733"
    assert not lead.calendly_booked
    assert booking["called"] is False
    assert reply is not None
    assert "ჯონი" in reply
    assert "16:45" not in reply


def test_02_contact_only_no_confirmed_slot_asks_for_time(monkeypatch):
    """Contact-only input with an active booking sub-flow but no confirmed
    slot → save contact and ask for preferred time."""
    booking = _install_fake_booking(monkeypatch)
    conv = _conv()
    lead = _lead(conv, child_age="12")
    # Booking sub-flow active but no confirmed datetime recorded yet.
    conv.pending_booking = {"missing_fields": ["name", "phone"], "attempts": 0}

    reply = _maybe_commit_pending_booking_engine(conv, "ჯონი 595999733")

    assert lead.name == "ჯონი"
    assert lead.phone == "595999733"
    assert booking["called"] is False
    assert reply is not None
    assert "დრო" in reply  # asks for the preferred date/time


def test_03_known_name_kept_when_phone_and_date_in_message():
    """Known name=ჯონი + „595999733 16 ივნის მინდა 10 საათზე": name stays
    ჯონი, never overwritten with „ივნის"."""
    name, phone = _parse_name_phone("595999733 16 ივნის მინდა 10 საათზე")
    assert phone == "595999733"
    assert name == ""  # no garbage name extracted
    assert "ივნის" not in name


def test_04_unknown_name_phone_date_message_does_not_invent_name(monkeypatch):
    """Unknown name + „595999733 16 ივნის მინდა 10 საათზе": phone parsed,
    but name is NOT set to a month word."""
    conv = _conv()
    lead = _lead(conv, child_age="12")
    executor = ParentToolExecutor(
        conversation=conv, lead=lead,
        sender_id=conv.sender_id, platform=conv.platform,
    )
    # The LLM might mistakenly pass the month word as the name.
    result = executor.execute("save_lead_info", {"name": "ივნის", "phone": "595999733"})
    assert lead.name == ""  # month word rejected
    assert lead.phone == "595999733"
    assert "name" in (result.get("invalid_fields") or [])


@pytest.mark.parametrize("month", [
    # NOTE: „მარტი"/„მარტა" (March) is intentionally NOT here — it collides
    # with real names and is excluded from the name guard (see test_27).
    "ივნის", "ივნისს", "ივნისი", "ივლის", "ივლისს", "მაისს",
    "იანვარი", "თებერვალი", "აპრილი", "აგვისტო",
    "სექტემბერი", "ოქტომბერი", "ნოემბერი", "დეკემბერი",
])
def test_05_month_names_rejected_as_name(month):
    assert is_valid_person_name(month) is False
    name, _phone = _parse_name_phone(month)
    assert name == ""


@pytest.mark.parametrize("word", [
    "საათზე", "სთ", "დღეს", "ხვალ", "ზეგ", "დრო", "მინდა",
    "კონსულტაცია", "ჩაწერა", "გადატანა", "10:00", "16",
])
def test_06_date_time_booking_words_rejected_as_name(word):
    assert is_valid_person_name(word) is False


def test_07_explicit_correction_updates_name():
    """„სახელი ჯონი" → name=ჯონი (the word „სახელი" is filler)."""
    name, _phone = _parse_name_phone("სახელი ჯონი")
    assert name == "ჯონი"
    assert is_valid_person_name("ჯონი") is True


# ===========================================================================
# Booking state tests
# ===========================================================================


def test_08_stale_pending_1645_not_booked(monkeypatch):
    """„ჯონი 595999733" must NOT use a stale/default 16:45 slot."""
    booking = _install_fake_booking(monkeypatch)
    conv = _conv()
    lead = _lead(conv, child_age="12")
    conv.pending_booking = _confirmed_pending(_stale_iso(16, 45))

    reply = _maybe_commit_pending_booking_engine(conv, "ჯონი 595999733")

    assert booking["called"] is False
    assert not lead.calendly_booked
    # The stale datetime is cleared so the LLM never re-attempts it.
    assert not (conv.pending_booking or {}).get("requested_datetime_iso")
    assert reply is not None


def test_08b_stale_clear_with_question_defers_to_engine(monkeypatch):
    """Adversarial-review regression: a stale slot is cleared, but the
    user's message is a QUESTION (not contact) and the lead already has
    name/phone — the commit helper must NOT hijack with an ask-time
    reply; it returns None so the engine answers the question."""
    booking = _install_fake_booking(monkeypatch)
    conv = _conv()
    lead = _lead(conv, name="ჯონი", phone="595999733", child_age="12")
    conv.pending_booking = _confirmed_pending(_stale_iso())

    reply = _maybe_commit_pending_booking_engine(conv, "რა ღირს ბანაკი?")

    assert reply is None  # defers to the engine to answer the price question
    assert booking["called"] is False
    # The stale datetime is still cleared so the LLM cannot re-book it.
    assert not (conv.pending_booking or {}).get("requested_datetime_iso")


def test_09_booking_blocked_until_required_fields_present():
    """book_consultation requires name + phone + datetime + child_age."""
    conv = _conv()
    lead = _lead(conv)  # nothing known yet
    executor = ParentToolExecutor(
        conversation=conv, lead=lead,
        sender_id=conv.sender_id, platform=conv.platform,
    )
    res = executor.execute("book_consultation", {
        "phone": "595999733",
        "datetime_iso": _future_weekday_iso(11),
        "child_age": "12",
        "user_confirmed_datetime": True,
    })
    assert res["success"] is False
    assert res["reason"] == "missing_name"


def test_10_future_pending_confirmation_books_that_slot(monkeypatch):
    """A future confirmed pending slot + „კი" with contact present → books
    that exact slot."""
    booking = _install_fake_booking(monkeypatch)
    future_iso = _future_weekday_iso(11)
    conv = _conv()
    lead = _lead(conv, name="ჯონი", phone="595999733", child_age="12")
    conv.pending_booking = _confirmed_pending(future_iso)

    reply = _maybe_commit_pending_booking_engine(conv, "კი")

    assert booking["called"] is True
    assert booking["booked_iso"] == future_iso
    assert lead.calendly_booked
    assert reply is not None
    assert "ჩაგინიშნეთ" in reply


def test_11_contact_after_future_slot_books_confirmed_slot(monkeypatch):
    """Contact arriving after a FUTURE slot confirmation books only that
    confirmed slot — never a random stale time."""
    booking = _install_fake_booking(monkeypatch)
    future_iso = _future_weekday_iso(11)
    conv = _conv()
    lead = _lead(conv, name="ჯონი", child_age="12")  # phone missing
    conv.pending_booking = _confirmed_pending(future_iso)

    reply = _maybe_commit_pending_booking_engine(conv, "595999733")

    assert booking["called"] is True
    assert booking["booked_iso"] == future_iso
    assert lead.phone == "595999733"
    assert lead.calendly_booked
    assert reply is not None


def test_12_explicit_morning_slot_parsed_as_10():
    """16 ივნისი 10 საათზე → explicit morning business-hour slot stays
    10:00 (not shifted to 22:00)."""
    from app.flows.parent_turn_router import _parse_booking_datetime
    iso = _parse_booking_datetime("16 ივნისს 10 საათზე")
    assert iso is not None
    dt = datetime.fromisoformat(iso)
    assert dt.hour == 10


def test_13_colloquial_pm_time_unchanged():
    """7 საათზე / 8 საათზე colloquial PM behaviour stays 19:00 / 20:00."""
    from app.agent.services.timestamps import extract_colloquial_hour
    assert extract_colloquial_hour("7 საათზე")[0] == 19
    assert extract_colloquial_hour("8 საათზე")[0] == 20


# ===========================================================================
# State reuse tests
# ===========================================================================


def test_14_valid_name_kept_phone_missing():
    """A valid stored name survives sanitisation (so „name already known,
    ask phone" is legitimate)."""
    lead = Lead(sender_id="s", platform="instagram", segment="PARENT", name="ჯონი")
    _sanitise_invalid_stored_name(lead)
    assert lead.name == "ჯონი"


def test_15_invalid_month_name_cleared():
    """A stored month artifact is cleared so the engine never says „სახელი
    უკვე ვიცი" for invalid data."""
    lead = Lead(sender_id="s", platform="instagram", segment="PARENT", name="ივნის")
    _sanitise_invalid_stored_name(lead)
    assert lead.name == ""


def test_16_adult_subscription_data_not_used_as_parent_contact(monkeypatch):
    """An adult-subscription Sheets record for the same sender must NOT
    hydrate the PARENT lead's name/phone."""
    from app.services import sheets_service

    # An adult subscriber row exists for this sender.
    monkeypatch.setattr(
        sheets_service, "get_event_subscriber",
        lambda *_a, **_k: {"name": "ADULT-SUB", "phone": "599000000",
                           "status": "subscribed", "consent": True},
        raising=False,
    )
    booking = _install_fake_booking(monkeypatch)
    conv = _conv()
    lead = _lead(conv, child_age="12")  # PARENT lead starts with no name/phone
    conv.pending_booking = {"missing_fields": ["name", "phone"], "attempts": 0}

    # A discovery-style message that is NOT contact disclosure.
    _maybe_commit_pending_booking_engine(conv, "რა ღირს ბანაკი?")

    assert lead.name == ""           # never pulled from the adult row
    assert lead.phone == ""
    assert booking["called"] is False


def test_17_old_redis_state_with_missing_fields_loads_safely():
    """A stale snapshot missing newer keys loads without crashing."""
    payload = {
        "sender_id": "s1", "platform": "instagram",
        # no pending_booking, no follow-up markers, no lead
    }
    conv = Conversation.from_dict(payload)
    assert conv.sender_id == "s1"
    assert conv.pending_booking is None
    assert conv.lead is None


# ===========================================================================
# Challenge cleanup tests
# ===========================================================================


def test_18_clean_challenge_no_question():
    assert clean_challenge_for_storage(
        "ეკრანისგან დისტანცია, გარემო, მეგობრები"
    ) == "ეკრანისგან დისტანცია, გარემო, მეგობრები"


def test_19_clean_challenge_drops_trailing_question():
    cleaned = clean_challenge_for_storage(
        "ეკრანისგან დისტანცია, გარემო, მეგობრები და ასევე "
        "მაინტერესებს ბანაკი როდის ტარდება?"
    )
    assert "ეკრანისგან დისტანცია" in cleaned
    assert "მეგობრები" in cleaned
    assert "როდის" not in cleaned
    assert "ტარდება" not in cleaned


def test_20_clean_challenge_keeps_goal_drops_price_question():
    cleaned = clean_challenge_for_storage("კომუნიკაცია და ასევე რა ღირს?")
    assert cleaned == "კომუნიკაცია"
    assert "ღირს" not in cleaned


def test_21_question_only_yields_empty():
    assert clean_challenge_for_storage("ბანაკი როდის ტარდება?") == ""


def test_22_save_lead_info_stores_cleaned_challenge():
    """The SAVE chokepoint (not only the email) stores the cleaned
    challenge so the Sheets row is clean."""
    conv = _conv()
    lead = _lead(conv)
    executor = ParentToolExecutor(
        conversation=conv, lead=lead,
        sender_id=conv.sender_id, platform=conv.platform,
    )
    res = executor.execute("save_lead_info", {
        "challenge": "კომუნიკაცია, მეგობრები და ასევე მაინტერესებს ფასი?",
    })
    assert res["success"] is True
    assert "ფასი" not in lead.challenge
    assert "მაინტერესებს" not in lead.challenge
    assert "კომუნიკაცია" in lead.challenge
    # The Sheets row reads the cleaned value.
    assert "ფასი" not in lead.to_sheet_row("ok")[6]


def test_22b_challenge_fallback_stores_cleaned():
    lead = Lead(sender_id="s", platform="instagram", segment="PARENT")
    maybe_capture_challenge_fallback(
        lead,
        "ჩემს შვილს ეკრანთან დიდი დრო აქვს, მეგობრები და ასევე "
        "მაინტერესებს ბანაკი როდის ტარდება?",
    )
    assert lead.challenge  # something captured
    assert "როდის" not in lead.challenge


# ===========================================================================
# Regression tests
# ===========================================================================


def test_23_age_range_9_17_not_child_age():
    """„ბავშვების საზაფხულო ბანაკი 9-17" still does NOT set child_age."""
    lead = Lead(sender_id="s", platform="instagram", segment="PARENT")
    maybe_capture_child_age_fallback(lead, "ბავშვების საზაფხულო ბანაკი 9-17")
    assert lead.child_age == ""


def test_24_new_user_unknown_age_still_asked():
    """A PARENT reply with no age stem and unknown child_age gets the age
    question appended."""
    conv = _conv(segment="PARENT")
    _lead(conv)  # no child_age
    out = parent_flow._ensure_camp_age_question(
        conv, "მაინტერესებს ბანაკი", "ბანაკი ძალიან კარგი პროგრამაა.",
    )
    assert "რამდენი წლის" in out or "ასაკი" in out


def test_25_phone_only_still_parses():
    """Regression: plain phone still parses; valid simple names survive."""
    name, phone = _parse_name_phone("595999733")
    assert phone == "595999733"
    assert name == ""
    name2, phone2 = _parse_name_phone("ნიკა 595999733")
    assert phone2 == "595999733"
    assert name2 == "ნიკა"


def test_26_valid_full_name_passes_guard():
    assert is_valid_person_name("ნიკა გობეჯიშვილი") is True
    assert is_valid_person_name("მარიამი") is True
    # „მინდია" is a real name and must NOT be rejected by the „მინდა" rule.
    assert is_valid_person_name("მინდია") is True


def test_27_march_name_not_rejected():
    """Adversarial-review regression: real Georgian names that start with
    the March stem („მარტ") must NOT be rejected; non-camp month March is
    excluded from the name guard. Summer-camp months stay rejected."""
    assert is_valid_person_name("მარტი") is True
    assert is_valid_person_name("მარტა") is True
    name, phone = _parse_name_phone("მარტა 595123456")
    assert phone == "595123456"
    assert name == "მარტა"
    # Summer months still rejected (the actual live bug).
    assert is_valid_person_name("ივნის") is False
    assert is_valid_person_name("ივლის") is False
    assert is_valid_person_name("აგვისტო") is False


def test_28_challenge_goal_and_question_joined_by_da():
    """Adversarial-review regression: a goal joined to a question by plain
    „და" keeps the goal and drops only the question."""
    assert clean_challenge_for_storage("კომუნიკაცია და როდის ტარდება?") == "კომუნიკაცია"
    # Two real goals joined by „და" both survive.
    out = clean_challenge_for_storage("მეგობრები და თავდაჯერებულობა")
    assert "მეგობრები" in out
    assert "თავდაჯერებულობა" in out
    # „ღირებულებები" (values) is a legitimate goal, not a price question.
    assert clean_challenge_for_storage("ღირებულებები") == "ღირებულებები"
