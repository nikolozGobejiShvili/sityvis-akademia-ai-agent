"""Today-first consultation availability in Asia/Tbilisi local time (hotfix 2026-06-28).

Live bug:
  User : „უახლოესი თავისუფალი დრო რაც არის"
  Agent: „უახლოესი თავისუფალი დროებია: 30 ივნისი, 10:00; 30 ივნისი, 11:00; …"  (TOMORROW)
  User : „დღეს არ არის თავისუფალი?"
  Bad  : „დღეს უკვე გადაცილებულია სამუშაო საათები კონსულტაციისთვის. …"

…even though it was ~15:00 Asia/Tbilisi and today (work hours 10:00–21:00) still
had free afternoon slots. Root cause: the no-date slot loader started the search
at TOMORROW (`_load_available_slots` used `range(1, 8)`), so today's remaining
slots were never considered, and the LLM then rationalised „today is over".

Fix (deterministic, Asia/Tbilisi LOCAL time, engine ON, planner/slim OFF):
  * `_load_available_slots` now starts at offset 0 (today);
  * a new `_maybe_handle_availability_question` answers a „nearest free time" /
    „is today free?" question by checking TODAY first and only then the next
    day(s); it says „today's hours are over" ONLY when local time is genuinely
    past the booking cutoff.

Minimum lead time: the existing today-only `SLOT_BUFFER` (business_hours.yaml
`slot.buffer_minutes` = 120) is PRESERVED — a today slot must start ≥ now + 2 h.
So at 15:00 the earliest offered today slot is 17:00; 16:00 (and any past hour)
is never offered. These tests exercise the REAL `calendar_service.get_free_slots`
with a pinned Asia/Tbilisi clock + a Free/Busy stub, so the timezone + buffer +
business-hours filtering is genuinely covered (not pre-baked).
"""
from __future__ import annotations

import dataclasses
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

import app.config as config_module
from app.flows import parent_flow
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.services import calendar_service, conversation_service, messenger_service

TBILISI = ZoneInfo("Asia/Tbilisi")

# 2026-06-29 is a Monday (open booking day); 2026-06-30 a Tuesday.
_MON_JUN29 = date(2026, 6, 29)
_SUN_JUL05 = date(2026, 7, 5)  # Sunday — closed booking day

_HOURS_OVER_MARKERS = ("დასრულდა", "გადაცილებ", "სამუშაო საათ")
_ENGINE_MARK = "[ENGINE-FALLBACK]"


# =====================================================================
# Fixtures / helpers
# =====================================================================
@pytest.fixture(autouse=True)
def _reset():
    conversation_service.conversations.clear()
    yield
    conversation_service.conversations.clear()


@pytest.fixture
def engine_on(monkeypatch):
    swapped = dataclasses.replace(
        config_module.settings,
        USE_PARENT_LLM_ENGINE=True,
        USE_CONVERSATION_PLANNER=False,
        CONVERSATION_PLANNER_AUTHORITATIVE=False,
        USE_SLIM_PROMPTS=False,
    )
    monkeypatch.setattr(parent_flow, "settings", swapped)
    monkeypatch.setattr(messenger_service, "get_user_profile", lambda sid, plat: {})
    # The engine must NOT be reached for an availability question — if it is, the
    # mark makes the failure obvious.
    monkeypatch.setattr(
        parent_flow, "_run_llm_engine_safely",
        lambda c, m: f"{_ENGINE_MARK} ვუპასუხებ ბანაკზე.",
    )
    return swapped


def _pin_now(monkeypatch, fixed_now: datetime) -> None:
    """Freeze calendar_service.datetime.now() (and therefore
    `calendar_service.now_tbilisi()` used by the availability handler) so both
    the slot generator's buffer/business-hours math and the handler's
    today/cutoff reasoning resolve from a single Asia/Tbilisi clock."""
    class _FakeDT(calendar_service.datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return fixed_now.replace(tzinfo=None)
            return fixed_now.astimezone(tz)

    monkeypatch.setattr(calendar_service, "datetime", _FakeDT)


def _busy_except(day: date, free_starts: set[int]) -> list[tuple[datetime, datetime]]:
    """Free/Busy intervals that make ONLY `free_starts` (whole-hour slot starts
    10..20) free on `day`; every other hour-block is busy."""
    return [
        (
            datetime(day.year, day.month, day.day, h, 0, tzinfo=TBILISI),
            datetime(day.year, day.month, day.day, h + 1, 0, tzinfo=TBILISI),
        )
        for h in range(10, 21)
        if h not in free_starts
    ]


def _stub_freebusy(monkeypatch, busy_by_date: dict[date, list]) -> None:
    """Stub the Calendar Free/Busy lookup. Unlisted dates are fully free."""
    def _fake(window_start, window_end):
        return list(busy_by_date.get(window_start.date(), []))

    monkeypatch.setattr(calendar_service, "_free_busy_intervals", _fake)


def _conv(prior_assistant: str, *, phone: str = "", child_age: str = "14") -> Conversation:
    """A discovery-state PARENT conversation with a prior assistant turn (so the
    static welcome does NOT fire) and NO booking context (so the booking
    date/time handler defers and the availability handler is reached)."""
    c = Conversation(sender_id="av", platform="instagram", segment="PARENT")
    c.state = "DISCOVERY"
    c.history.append({"role": "assistant", "content": prior_assistant})
    c.lead = Lead(
        sender_id="av", platform="instagram", segment="PARENT",
        child_age=child_age, phone=phone,
    )
    return c


def _says_hours_over(text: str) -> bool:
    return any(m in (text or "") for m in _HOURS_OVER_MARKERS)


# =====================================================================
# Required test 1 — same-day future slots are offered (not tomorrow)
# =====================================================================
def test_1_same_day_future_slots_offered(engine_on, monkeypatch):
    _pin_now(monkeypatch, datetime(2026, 6, 29, 15, 0, tzinfo=TBILISI))
    _stub_freebusy(monkeypatch, {_MON_JUN29: _busy_except(_MON_JUN29, {16, 17, 18})})

    conv = _conv("რით შემიძლია დაგეხმაროთ ბანაკთან დაკავშირებით?")
    out = parent_flow.handle(conv, "უახლოესი თავისუფალი დრო რაც არის")

    assert "დღეს" in out                                  # answers about TODAY
    assert ("17:00" in out) or ("18:00" in out)           # today's remaining slots
    assert "30 ივნისი" not in out                         # did NOT jump to tomorrow
    assert not _says_hours_over(out)                      # never „hours are over"
    assert _ENGINE_MARK not in out                        # handled deterministically
    # 16:00 is within the 2 h lead-time buffer at 15:00 → never offered.
    assert "16:00" not in out


# =====================================================================
# Required test 2 — „today?" follow-up rechecks today (ignores prior offer)
# =====================================================================
def test_2_today_followup_rechecks_today(engine_on, monkeypatch):
    _pin_now(monkeypatch, datetime(2026, 6, 29, 15, 0, tzinfo=TBILISI))
    _stub_freebusy(monkeypatch, {_MON_JUN29: _busy_except(_MON_JUN29, {18, 19})})

    # The agent previously offered TOMORROW's slots — the follow-up must re-check
    # today regardless of that prior answer.
    conv = _conv("უახლოესი თავისუფალი დროებია: 30 ივნისი, 10:00; 30 ივნისი, 11:00. რომელი დრო გსურთ?")
    out = parent_flow.handle(conv, "დღეს არ არის თავისუფალი?")

    assert "დღეს" in out
    assert "18:00" in out and "19:00" in out
    assert "30 ივნისი" not in out                          # rechecked today, did NOT reuse tomorrow
    assert not _says_hours_over(out)
    assert _ENGINE_MARK not in out


# =====================================================================
# Required test 3 — no same-day slots BUT still within working hours
# =====================================================================
def test_3_no_today_slots_within_hours(engine_on, monkeypatch):
    _pin_now(monkeypatch, datetime(2026, 6, 29, 15, 0, tzinfo=TBILISI))
    # Today fully busy; tomorrow free.
    _stub_freebusy(monkeypatch, {_MON_JUN29: _busy_except(_MON_JUN29, set())})

    conv = _conv("რით დაგეხმაროთ?")
    out = parent_flow.handle(conv, "დღეს არ არის თავისუფალი?")

    assert "აღარ ჩანს" in out                              # today no free time visible
    assert "უახლოეს" in out                                # offers nearest next slots
    assert "30 ივნისი" in out                              # tomorrow
    assert not _says_hours_over(out)                       # NOT „working hours over"
    assert _ENGINE_MARK not in out


# =====================================================================
# Required test 4 — after-hours message only after the local cutoff
# =====================================================================
def test_4_after_hours_message_after_cutoff(engine_on, monkeypatch):
    _pin_now(monkeypatch, datetime(2026, 6, 29, 21, 30, tzinfo=TBILISI))
    _stub_freebusy(monkeypatch, {})  # everything free, but today is past cutoff

    conv = _conv("რით დაგეხმაროთ?")
    out = parent_flow.handle(conv, "დღეს არ არის თავისუფალი?")

    assert "დასრულდა" in out                               # today's hours are over (OK now)
    assert "30 ივნისი" in out                              # offers next available slots
    assert _ENGINE_MARK not in out


# =====================================================================
# Required test 5 — before-hours: today's morning slots offered
# =====================================================================
def test_5_before_hours_offers_today(engine_on, monkeypatch):
    _pin_now(monkeypatch, datetime(2026, 6, 29, 9, 0, tzinfo=TBILISI))
    _stub_freebusy(monkeypatch, {_MON_JUN29: _busy_except(_MON_JUN29, {10, 11})})

    conv = _conv("რით დაგეხმაროთ?")
    out = parent_flow.handle(conv, "დღეს თავისუფალია?")

    assert "დღეს" in out
    assert "11:00" in out                                  # 09:00 + 2 h buffer → 11:00
    assert not _says_hours_over(out)
    assert _ENGINE_MARK not in out
    # 10:00 is within the 2 h buffer at 09:00 → not offered.
    assert "10:00" not in out


# =====================================================================
# Required test 6 — never offer past / within-buffer slots
# =====================================================================
def test_6_does_not_offer_past_slots(engine_on, monkeypatch):
    _pin_now(monkeypatch, datetime(2026, 6, 29, 15, 0, tzinfo=TBILISI))
    # Today free at 10:00 (past), 12:00 (past) and 18:00 (valid future).
    _stub_freebusy(monkeypatch, {_MON_JUN29: _busy_except(_MON_JUN29, {10, 12, 18})})

    conv = _conv("რით დაგეხმაროთ?")
    out = parent_flow.handle(conv, "დღეს თავისუფალია?")

    assert "18:00" in out                                  # the valid future slot
    assert "10:00" not in out                              # past
    assert "12:00" not in out                              # past
    assert not _says_hours_over(out)
    assert _ENGINE_MARK not in out


# =====================================================================
# Required test 7 — timezone regression (UTC must be read as Tbilisi local)
# =====================================================================
def test_7a_utc_clock_read_as_tbilisi_local_offers_today(engine_on, monkeypatch):
    # 11:00 UTC == 15:00 Asia/Tbilisi. The working-hours check must see local
    # 15:00 (within hours) and offer today — never „outside hours".
    _pin_now(monkeypatch, datetime(2026, 6, 29, 11, 0, tzinfo=timezone.utc))
    _stub_freebusy(monkeypatch, {_MON_JUN29: _busy_except(_MON_JUN29, {17, 18})})

    conv = _conv("რით დაგეხმაროთ?")
    out = parent_flow.handle(conv, "უახლოესი თავისუფალი დრო რაც არის")

    assert "დღეს" in out
    assert ("17:00" in out) or ("18:00" in out)
    assert not _says_hours_over(out)


def test_7b_utc_clock_discriminates_after_cutoff(engine_on, monkeypatch):
    # 17:30 UTC == 21:30 Asia/Tbilisi → past the local cutoff → „hours over".
    # A naive-UTC bug would read 17:30 (still within hours) and NOT say so.
    _pin_now(monkeypatch, datetime(2026, 6, 29, 17, 30, tzinfo=timezone.utc))
    _stub_freebusy(monkeypatch, {})

    conv = _conv("რით დაგეხმაროთ?")
    out = parent_flow.handle(conv, "დღეს არ არის თავისუფალი?")

    assert "დასრულდა" in out                               # saw 21:30 Tbilisi, not 17:30 UTC
    assert "30 ივნისი" in out


# =====================================================================
# Detector unit coverage
# =====================================================================
def test_detector_matches_availability_questions():
    f = parent_flow._looks_like_availability_question
    assert f("უახლოესი თავისუფალი დრო რაც არის") is True
    assert f("დღეს არ არის თავისუფალი?") is True
    assert f("დღეს თავისუფალია?") is True


def test_detector_defers_on_specific_hour():
    # A specific clock time → exact-slot request, not a general availability ask.
    f = parent_flow._looks_like_availability_question
    assert f("დღეს 16:00-ზე შეიძლება?") is False           # no „free" stem anyway
    assert f("დღეს თავისუფალია 17:00-ზე?") is False         # has „free" + hour → defer
    assert f("დღეს 8 საათზე თავისუფალია?") is False


def test_detector_ignores_unrelated_messages():
    f = parent_flow._looks_like_availability_question
    assert f("ზრდასრულთა ღონისძიებები რა გაქვთ?") is False
    assert f("ბანაკის ფასი რა არის?") is False
    assert f("ორშაბათს, საღამოს საათებში") is False
    assert f("გამარჯობა") is False


# =====================================================================
# Cutoff helper unit coverage (Asia/Tbilisi local time)
# =====================================================================
@pytest.mark.parametrize(
    "hour,minute,expected",
    [
        (9, 0, False),    # before hours, today still bookable
        (15, 0, False),   # mid-afternoon, bookable
        (18, 0, False),   # now + 2 h = 20:00 == last slot start → still open
        (18, 1, True),    # now + 2 h > 20:00 → no whole-hour slot left
        (21, 30, True),   # after close
    ],
)
def test_today_closed_by_time(monkeypatch, hour, minute, expected):
    now = datetime(2026, 6, 29, hour, minute, tzinfo=TBILISI)  # Monday
    assert parent_flow._today_consultation_closed(now) is expected


def test_today_closed_on_sunday_regardless_of_time():
    # Sunday is a closed booking day even at 11:00.
    now = datetime(_SUN_JUL05.year, _SUN_JUL05.month, _SUN_JUL05.day, 11, 0, tzinfo=TBILISI)
    assert parent_flow._today_consultation_closed(now) is True


# =====================================================================
# Age-eligibility gate — an ineligible child age never gets a slot offer
# =====================================================================
def test_ineligible_age_defers_to_engine(engine_on, monkeypatch):
    _pin_now(monkeypatch, datetime(2026, 6, 29, 15, 0, tzinfo=TBILISI))
    _stub_freebusy(monkeypatch, {_MON_JUN29: _busy_except(_MON_JUN29, {17, 18})})

    # Child below the camp minimum (age band 9–17) → cannot book; the handler
    # must NOT deterministically offer slots, it defers to the engine (which
    # carries the ineligible-age guards).
    conv = _conv("რით დაგეხმაროთ?", child_age="6")
    assert parent_flow._maybe_handle_availability_question(
        conv, "დღეს თავისუფალია?",
    ) is None

    out = parent_flow.handle(conv, "დღეს თავისუფალია?")
    assert "17:00" not in out and "18:00" not in out       # no slot offering
    assert _ENGINE_MARK in out                             # deferred to the engine


def test_eligible_and_unknown_age_still_offer_today(engine_on, monkeypatch):
    _pin_now(monkeypatch, datetime(2026, 6, 29, 15, 0, tzinfo=TBILISI))
    _stub_freebusy(monkeypatch, {_MON_JUN29: _busy_except(_MON_JUN29, {17, 18})})

    # Eligible age → offered.
    out_elig = parent_flow.handle(_conv("რით დაგეხმაროთ?", child_age="14"), "დღეს თავისუფალია?")
    assert "17:00" in out_elig
    # Unknown age (parent asking before disclosing) → still offered (bug scenario).
    out_unknown = parent_flow.handle(_conv("რით დაგეხმაროთ?", child_age=""), "დღეს თავისუფალია?")
    assert "17:00" in out_unknown


# =====================================================================
# Non-availability message must still reach the engine (no hijack)
# =====================================================================
def test_non_availability_message_reaches_engine(engine_on, monkeypatch):
    _pin_now(monkeypatch, datetime(2026, 6, 29, 15, 0, tzinfo=TBILISI))
    _stub_freebusy(monkeypatch, {})

    conv = _conv("რით დაგეხმაროთ?")
    out = parent_flow.handle(conv, "ბანაკის შესახებ მინდა ინფორმაცია")
    assert _ENGINE_MARK in out


# =====================================================================
# _load_available_slots now includes TODAY (engine-path defense)
# =====================================================================
def test_load_available_slots_includes_today(monkeypatch):
    _pin_now(monkeypatch, datetime(2026, 6, 29, 15, 0, tzinfo=TBILISI))
    _stub_freebusy(monkeypatch, {_MON_JUN29: _busy_except(_MON_JUN29, {17, 18, 19})})

    slots = parent_flow._load_available_slots("av")
    times = {s.get("time") for s in slots}
    # Today's remaining afternoon slots come FIRST (was previously skipped).
    assert "17:00" in times
    assert all(s.get("date") == "29 ივნისი" for s in slots)
