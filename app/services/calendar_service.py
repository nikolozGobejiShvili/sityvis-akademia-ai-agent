import logging
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from googleapiclient.discovery import build

from app.agent.services.knowledge_loader import load_knowledge
from app.config import Settings, has_value, settings
from app.models.lead import Lead
from app.services.google_credentials import load_google_credentials
from data.prompts import (
    CALENDAR_EVENT_DESCRIPTION,
    CALENDAR_EVENT_SUMMARY,
    CALENDAR_OPTIONS_SEPARATOR,
    CALENDAR_SLOT_CHOICE_PROMPT,
)

logger = logging.getLogger(__name__)

CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar"

# Business-hours / scheduling constants — sourced from
# app/agent/knowledge/business_hours.yaml. Module-level evaluation runs once
# at import; behaviour is unchanged from the previous hardcoded values.
def _parse_hm(value: str) -> time:
    hh, mm = value.split(":", 1)
    return time(int(hh), int(mm))


_BUSINESS = load_knowledge("business_hours")["business"]
TIMEZONE_NAME = _BUSINESS["timezone"]
TIMEZONE = ZoneInfo(TIMEZONE_NAME)
WORK_START = _parse_hm(_BUSINESS["work_hours"]["start"])
WORK_END = _parse_hm(_BUSINESS["work_hours"]["end"])
BUSINESS_HOUR_START = _parse_hm(_BUSINESS["business_hours"]["start"])
BUSINESS_HOUR_END = _parse_hm(_BUSINESS["business_hours"]["end"])
SLOT_DURATION = timedelta(minutes=int(_BUSINESS["slot"]["duration_minutes"]))
SLOT_BUFFER = timedelta(minutes=int(_BUSINESS["slot"]["buffer_minutes"]))

# Scheduling availability policy. Consultations are bookable
# Monday–Saturday; Sunday remains closed. Python's date.weekday() maps
# Monday=0 … Friday=4, Saturday=5, Sunday=6, so only weekday()==6 (Sunday)
# is a closed booking day. (Until 2026-06-16 BOTH Saturday and Sunday were
# closed via `weekday() >= 5`; Saturday is now treated as a normal booking
# day and follows the same working-hours / buffer / FreeBusy rules as any
# weekday.) Centralised here so slot generation, business-hours validation,
# and the tool-executor pre-checks all stay in lock-step.
CLOSED_WEEKDAYS = frozenset({6})  # 6 = Sunday


def is_closed_booking_day(day) -> bool:
    """True when ``day`` (a ``date`` or ``datetime``) falls on a day the
    business does not take consultation bookings.

    Only Sunday is closed; Saturday and all weekdays are open.
    """
    return day.weekday() in CLOSED_WEEKDAYS

# Georgian month names for display ("15 მაისი") — sourced from
# app/agent/knowledge/i18n/ka_months.yaml. Cast keys to int because YAML
# integer-keyed mappings are loaded as int but we want to be explicit.
GEORGIAN_MONTHS = {
    int(k): v
    for k, v in load_knowledge("i18n/ka_months")["months_nominative"].items()
}

NUMBER_EMOJIS = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"]


def get_available_slots() -> list[dict]:
    try:
        now = datetime.now(TIMEZONE)
        buffer_cutoff = now + SLOT_BUFFER
        search_until = now + timedelta(days=30)
        booked_ranges = _booked_ranges(now, search_until)
        slots = []
        current_day = now.date()

        while len(slots) < 5 and current_day <= search_until.date():
            if not is_closed_booking_day(current_day):
                slot_start = datetime.combine(current_day, WORK_START, tzinfo=TIMEZONE)
                work_end = datetime.combine(current_day, WORK_END, tzinfo=TIMEZONE)

                while slot_start + SLOT_DURATION <= work_end:
                    slot_end = slot_start + SLOT_DURATION
                    if slot_start >= buffer_cutoff and not _overlaps_booked(slot_start, slot_end, booked_ranges):
                        slots.append(_format_slot(slot_start))
                        if len(slots) == 5:
                            break
                    slot_start += SLOT_DURATION

            current_day += timedelta(days=1)

        logger.info("[CALENDAR] Available slots loaded: count=%s", len(slots))
        return slots
    except Exception as exc:
        logger.exception("[CALENDAR] Failed to get available slots: %s", exc)
        return []


def get_free_slots(
    target_date: date | None = None,
    duration_minutes: int = 60,
    *,
    start_date: date | None = None,
    days: int = 1,
) -> list[dict]:
    """Return free Calendar slots.

    Backwards-compatible signature:

      * `get_free_slots(target_date)` — legacy single-day behaviour
        (unchanged byte-for-byte from the pre-PATCH-4 implementation).
      * `get_free_slots(start_date=..., days=N)` — P3-C PATCH 4
        range search. Iterates `days` weekdays starting at `start_date`
        and concatenates the per-day slot lists. Callers that need
        date-aware availability for "26 May" / "27 May" use this form
        without touching the legacy positional path.
      * `get_free_slots()` with no args — sensible default: today plus
        the next `days` weekdays. Useful from the executor when the LLM
        asks for slots without naming a date.

    `duration_minutes` is honoured by both forms. Timezone handling is
    Asia/Tbilisi throughout — no caller needs to think about it.
    """
    # Legacy positional form takes priority — preserves the byte-identity
    # of every existing call site (parent_flow._load_available_slots,
    # tests, etc.).
    if target_date is not None and start_date is None:
        return _get_free_slots_for_day(target_date, duration_minutes)

    # Range form. Default to today when `start_date` is omitted.
    if start_date is None:
        start_date = datetime.now(TIMEZONE).date()

    if days < 1:
        days = 1

    collected: list[dict] = []
    for offset in range(days):
        day = start_date + timedelta(days=offset)
        collected.extend(_get_free_slots_for_day(day, duration_minutes))
    logger.info(
        "[CALENDAR] get_free_slots range: start=%s days=%d → %d slots",
        start_date, days, len(collected),
    )
    return collected


def _get_free_slots_for_day(target_date: date, duration_minutes: int) -> list[dict]:
    """Single-day implementation. Extracted from the legacy
    `get_free_slots` body so the public function remains a thin
    dispatcher.

    P3-C PATCH 6: ``SLOT_BUFFER`` (default 2 h) is now applied ONLY
    when ``target_date`` is today's date in Asia/Tbilisi. Before this
    patch the buffer was applied to every date, which over-aggressively
    pruned afternoon slots on future dates (the LLM then offered a
    truncated set and concluded the missing slots — e.g. 27 May 15:00 —
    were 'unavailable' when in fact they were free).
    """
    logger.info(
        "[get_free_slots] start_date=%s days=1 timezone=%s duration=%d "
        "working_hours=%s-%s buffer_minutes=%d",
        target_date, TIMEZONE_NAME, duration_minutes,
        BUSINESS_HOUR_START.strftime("%H:%M"),
        BUSINESS_HOUR_END.strftime("%H:%M"),
        int(SLOT_BUFFER.total_seconds() // 60),
    )

    if is_closed_booking_day(target_date):
        logger.info("[get_free_slots] %s is a closed booking day (Sunday) — no slots", target_date)
        return []

    now = datetime.now(TIMEZONE)
    today_tbilisi = now.date()
    buffer_applied = target_date == today_tbilisi
    buffer_cutoff = now + SLOT_BUFFER

    logger.info(
        "[get_free_slots] slot_date=%s today_tbilisi=%s buffer_applied=%s",
        target_date, today_tbilisi, buffer_applied,
    )

    day_start = datetime.combine(target_date, BUSINESS_HOUR_START, tzinfo=TIMEZONE)
    day_end = datetime.combine(target_date, BUSINESS_HOUR_END, tzinfo=TIMEZONE)

    try:
        busy = _free_busy_intervals(day_start, day_end)
    except Exception as exc:
        logger.exception("[get_free_slots] Free/Busy API failed for %s: %s", target_date, exc)
        return []

    logger.info(
        "[get_free_slots] Free/Busy API returned %d busy intervals", len(busy),
    )

    free_slots: list[dict] = []
    candidates = 0
    duration = timedelta(minutes=duration_minutes)
    slot_start = day_start
    while slot_start + duration <= day_end:
        candidates += 1
        slot_end = slot_start + duration
        within_buffer = buffer_applied and slot_start < buffer_cutoff
        if not within_buffer and not _overlaps_booked(slot_start, slot_end, busy):
            free_slots.append(_format_slot(slot_start))
        slot_start += duration

    logger.info(
        "[get_free_slots] generated_candidates=%d available_slots=%d for %s: %s",
        candidates, len(free_slots), target_date,
        [s["datetime_iso"] for s in free_slots],
    )
    return free_slots


def is_within_business_hours(
    slot_datetime: datetime, duration_minutes: int = 60,
) -> tuple[bool, str]:
    """Single source of truth for business-hour validation.

    Booking Availability Patch (2026-06-03):
      * Slots must start on the hour (minute == 0). Half-hour requests
        (10:30 / 11:30 / 20:30) are rejected with
        ``reason='half_hour_not_supported'``.
      * Business hours are 10:00–21:00; last valid 1-hour slot starts
        at 20:00 (20:00–21:00).

    Reason strings (stable contract — LLM branches wording on them):

      * ``past_datetime``           — slot is at or before "now".
      * ``weekend``                 — Sunday (closed booking day; Saturday
                                      is now an open booking day).
      * ``half_hour_not_supported`` — start minute ≠ 0.
      * ``outside_business_hours``  — start before 10:00 OR end after 21:00.
      * ``buffer_today``            — today only, within the 2 h buffer.
      * ``''`` (with ``True``)      — slot is acceptable.
    """
    if slot_datetime.tzinfo is None:
        slot_datetime = slot_datetime.replace(tzinfo=TIMEZONE)
    slot_datetime = slot_datetime.astimezone(TIMEZONE)
    slot_end = slot_datetime + timedelta(minutes=duration_minutes)
    now = datetime.now(TIMEZONE)

    if slot_datetime <= now:
        return False, "past_datetime"

    if is_closed_booking_day(slot_datetime):
        return False, "weekend"

    # Booking Availability Patch — whole-hour alignment is a hard rule.
    # Reported BEFORE the business-hours window so the LLM can offer
    # the brand-specific half-hour wording instead of a generic
    # "outside hours" message.
    if slot_datetime.minute != 0 or slot_datetime.second != 0:
        return False, "half_hour_not_supported"

    if slot_datetime.time() < BUSINESS_HOUR_START or slot_end.time() > BUSINESS_HOUR_END:
        return False, "outside_business_hours"

    # Today-only buffer. A future date is never rejected by the buffer.
    today_tbilisi = now.date()
    if slot_datetime.date() == today_tbilisi:
        if slot_datetime < now + SLOT_BUFFER:
            return False, "buffer_today"

    return True, ""


def check_slot_available(slot_datetime: datetime, duration_minutes: int = 60) -> bool:
    """Legacy bool API. The new ``is_within_business_hours`` helper +
    ``check_slot_calendar_only`` form a more granular pair the engine
    uses to distinguish business-hour rejections from Calendar busy
    states. This wrapper preserves the existing callers' contract.
    """
    if slot_datetime.tzinfo is None:
        slot_datetime = slot_datetime.replace(tzinfo=TIMEZONE)
    slot_datetime = slot_datetime.astimezone(TIMEZONE)
    slot_end = slot_datetime + timedelta(minutes=duration_minutes)

    logger.info(
        "[CALENDAR] check_slot_available called: slot=%s duration=%d",
        slot_datetime.isoformat(), duration_minutes,
    )

    ok, reason = is_within_business_hours(slot_datetime, duration_minutes)
    if not ok:
        logger.info(
            "[CALENDAR] Custom slot requested: %s — available=False (%s)",
            slot_datetime.isoformat(), reason,
        )
        return False

    try:
        busy = _free_busy_intervals(slot_datetime, slot_end)
    except Exception as exc:
        # Booking Availability Patch — fail CLOSED on Calendar API
        # errors. Returning False here forces the booking path to
        # surface the manager-callback fallback rather than risk a
        # blind double-book against an undeterminable busy state.
        logger.exception(
            "[CALENDAR] check_slot_available freebusy failed (fail-closed): %s",
            exc,
        )
        return False

    is_free = not _overlaps_booked(slot_datetime, slot_end, busy)
    logger.info(
        "[CALENDAR] Custom slot requested: %s — available=%s (busy_intervals=%d)",
        slot_datetime.isoformat(), is_free, len(busy),
    )
    return is_free


def check_slot_calendar_only(
    slot_datetime: datetime, duration_minutes: int = 60,
) -> bool:
    """Calendar-only availability check, skipping business-hour gates.

    Used by the new ``check_consultation_slot`` executor path where we
    have ALREADY confirmed business-hours validity and want a clean
    yes/no answer about Calendar busy state. Separating these prevents
    a busy-Calendar from being reported as ``outside_business_hours``
    and vice versa.
    """
    if slot_datetime.tzinfo is None:
        slot_datetime = slot_datetime.replace(tzinfo=TIMEZONE)
    slot_datetime = slot_datetime.astimezone(TIMEZONE)
    slot_end = slot_datetime + timedelta(minutes=duration_minutes)
    try:
        busy = _free_busy_intervals(slot_datetime, slot_end)
    except Exception as exc:
        logger.exception(
            "[CALENDAR] check_slot_calendar_only freebusy failed: %s", exc,
        )
        return False
    return not _overlaps_booked(slot_datetime, slot_end, busy)


class _BusyCalendarQueryError(Exception):
    """Raised by ``_free_busy_intervals`` when ANY configured busy
    calendar query fails (single calendar exception, FreeBusy ``errors``
    block for one calendar, or unexpected response shape).

    The caller treats this as a hard FAIL-CLOSED signal: do not book
    blindly when one of the busy calendars is unreachable, because the
    agent cannot prove the slot is free.
    """


def _free_busy_intervals(start_at: datetime, end_at: datetime) -> list[tuple[datetime, datetime]]:
    """Return the union of busy intervals across every configured
    calendar.

    Calendar Multi-Busy Check Patch (2026-06-04):
      * Queries ALL ids returned by ``settings.busy_calendar_ids()``
        in a single FreeBusy request (Google Calendar supports a
        multi-item ``items: [{id: ...}, ...]`` body).
      * Booking calendar is always included as the first entry so a
        booking the agent created appears as busy on the next check
        (preserving the existing single-calendar contract).
      * Returns the flattened list of (start, end) tuples — order is
        not contractual; ``_overlaps_booked`` only checks intersections.
      * Raises ``_BusyCalendarQueryError`` if ANY calendar in the list
        is unreachable (HTTP failure) OR reports a per-calendar
        ``errors`` block in the response. The caller surfaces this as
        a fail-CLOSED "slot unavailable" decision so we never blind-book
        against a calendar we couldn't read.

    Compatibility: callers using the legacy single-calendar deploy
    (BUSY_CALENDAR_IDS empty AND BOOKING_CALENDAR_ID empty) see the
    pre-patch behaviour — one query against ``GOOGLE_CALENDAR_ID``.
    """
    calendar_ids = settings.busy_calendar_ids()
    if not calendar_ids:
        # Defensive: with no configured calendar the agent can't make
        # any availability claim. Treat as fail-CLOSED.
        raise _BusyCalendarQueryError("no busy calendars configured")

    body = {
        "timeMin": start_at.isoformat(),
        "timeMax": end_at.isoformat(),
        "timeZone": TIMEZONE_NAME,
        "items": [{"id": cid} for cid in calendar_ids],
    }
    try:
        response = _calendar_service().freebusy().query(body=body).execute()
    except Exception as exc:
        raise _BusyCalendarQueryError(
            f"FreeBusy query failed for {len(calendar_ids)} calendar(s): {exc}"
        ) from exc

    calendars = response.get("calendars", {}) or {}
    result: list[tuple[datetime, datetime]] = []
    for cid in calendar_ids:
        cal_data = calendars.get(cid)
        if cal_data is None:
            # Google returns an entry per requested calendar; missing
            # entry = unrecoverable shape mismatch. Fail-CLOSED.
            raise _BusyCalendarQueryError(
                f"FreeBusy response missing calendar id={cid}"
            )
        errors = cal_data.get("errors")
        if errors:
            # Per-calendar permission / not-found errors. Surface as
            # fail-CLOSED — operator must fix sharing or remove the
            # calendar from BUSY_CALENDAR_IDS.
            raise _BusyCalendarQueryError(
                f"FreeBusy reported errors for calendar id={cid}: {errors}"
            )
        for period in cal_data.get("busy", []) or []:
            try:
                bstart = _parse_iso_datetime(period["start"])
                bend = _parse_iso_datetime(period["end"])
                result.append((bstart, bend))
            except Exception:
                # Skip a malformed period — the rest still apply. Do
                # not fail the whole query for one bad row; Google's
                # contract guarantees well-formed ISO datetimes here.
                continue
    return result


def _build_event_title(lead: Lead) -> str:
    name = (lead.name or "").strip() or "უცნობი მშობელი"
    age = (lead.child_age or "").strip()
    if age:
        return f"კონსულტაცია — {name} (ბავშვი: {age})"
    return f"კონსულტაცია — {name}"


def _build_event_description(lead: Lead) -> str:
    try:
        from app.flows.parent_flow import _format_phone_display
        phone_display = _format_phone_display(lead.phone or "")
    except Exception as exc:
        logger.warning(
            "[CALENDAR] _format_phone_display import failed (using raw phone): %s", exc,
        )
        phone_display = lead.phone or "არ მითითებული"

    parts = [
        f"📞 ნომერი: {phone_display}",
        f"👶 ბავშვის ასაკი: {lead.child_age or 'არ მითითებული'}",
        f"💭 გამოწვევა: {lead.challenge or 'არ მითითებული'}",
        "",
        f"Platform: {lead.platform or 'unknown'}",
        f"Sender ID: {lead.sender_id or 'unknown'}",
    ]
    return "\n".join(parts)


def book_slot(
    datetime_iso: str,
    lead: Lead,
    duration_minutes: int = 60,
) -> bool:
    logger.info(
        "[CALENDAR] book_slot called: iso=%s sender=%s name=%r phone=%r",
        datetime_iso, lead.sender_id, lead.name, lead.phone,
    )
    try:
        start_at = datetime.fromisoformat(datetime_iso)
        if start_at.tzinfo is None:
            start_at = start_at.replace(tzinfo=TIMEZONE)
        start_at = start_at.astimezone(TIMEZONE)
        end_at = start_at + timedelta(minutes=duration_minutes)
        logger.info(
            "[CALENDAR] Parsed slot start=%s end=%s tz=%s",
            start_at.isoformat(), end_at.isoformat(), TIMEZONE_NAME,
        )

        title = _build_event_title(lead)
        description = _build_event_description(lead)
        logger.info("[CALENDAR] Event title=%r", title)
        logger.info("[CALENDAR] Event description (first 120 chars)=%r", description[:120])

        event = {
            "summary": title,
            "description": description,
            "start": {"dateTime": start_at.isoformat(), "timeZone": TIMEZONE_NAME},
            "end": {"dateTime": end_at.isoformat(), "timeZone": TIMEZONE_NAME},
            "reminders": {
                "useDefault": False,
                "overrides": [{"method": "popup", "minutes": 60}],
            },
        }

        # Calendar Multi-Busy Check Patch (2026-06-04) — the agent
        # ONLY ever creates events on the booking calendar. Busy
        # calendars are read-only sources for availability checks.
        booking_calendar = settings.booking_calendar_id()
        logger.info("[CALENDAR] Inserting event into calendar_id=%s", booking_calendar)
        result = _calendar_service().events().insert(
            calendarId=booking_calendar,
            body=event,
        ).execute()
        event_id = result.get("id") or ""
        logger.info("[CALENDAR] ✅ Slot booked: iso=%s event_id=%s",
                    datetime_iso, event_id)
        # P3-C PATCH 1: stash the event_id on the lead so the cancel /
        # reschedule path can safely modify the event. Older callers
        # that ignore this attribute still work — book_slot's return
        # contract is unchanged (still bool).
        if event_id:
            try:
                lead.calendar_event_id = event_id
            except Exception:  # pragma: no cover — defensive
                pass
        return True
    except Exception as exc:
        logger.exception("[CALENDAR] ❌ Failed to book slot %s: %s", datetime_iso, exc)
        return False


def cancel_calendar_event(event_id: str) -> bool:
    """P3-C PATCH 1 — delete a previously-booked Calendar event.

    Returns True ONLY when Google Calendar's ``events().delete`` returns
    cleanly. Any exception (network error, 404 on a stale ID, permission
    issue) is logged and surfaces as False. The caller never sees an
    exception — propagating one would let the LLM engine claim "გავაუქმე"
    against backend failure, which is exactly what we are guarding against.

    The function is intentionally minimal: no business-hour checks, no
    timezone math — Calendar deletion is idempotent at the API level
    (deleting a missing event returns 410, which we treat as failure
    because the executor's contract is "did we actually delete something
    this call".)
    """
    if not event_id:
        logger.warning("[CALENDAR] cancel_calendar_event called with empty event_id")
        return False

    try:
        _calendar_service().events().delete(
            calendarId=settings.booking_calendar_id(),
            eventId=event_id,
        ).execute()
        logger.info("[CALENDAR] ✅ Event cancelled: event_id=%s", event_id)
        return True
    except Exception as exc:
        logger.exception(
            "[CALENDAR] ❌ Failed to cancel event_id=%s: %s", event_id, exc,
        )
        return False


def create_event(summary: str, description: str, start, end) -> dict:
    start_iso = start.isoformat() if hasattr(start, "isoformat") else str(start)
    end_iso = end.isoformat() if hasattr(end, "isoformat") else str(end)
    logger.info(
        "[CALENDAR] create_event called: summary=%s start=%s end=%s",
        summary, start_iso, end_iso,
    )

    body = {
        "summary": summary,
        "description": description,
        "start": {"dateTime": start_iso, "timeZone": TIMEZONE_NAME},
        "end": {"dateTime": end_iso, "timeZone": TIMEZONE_NAME},
    }
    try:
        result = _calendar_service().events().insert(
            calendarId=settings.booking_calendar_id(),
            body=body,
        ).execute()
        logger.info("[CALENDAR] ✅ Event created: id=%s summary=%s",
                    result.get("id"), summary)
        return result
    except Exception as exc:
        logger.exception("[CALENDAR] ❌ create_event failed: %s", exc)
        raise


def format_slots_for_chat(slots: list) -> str:
    lines = []
    for index, slot in enumerate(slots[:5], start=1):
        emoji = NUMBER_EMOJIS[index - 1]
        lines.append(f"{emoji} {slot['date']} - {slot['time']}")

    options = _format_options(len(lines))
    return "\n".join(lines) + "\n\n" + CALENDAR_SLOT_CHOICE_PROMPT.format(options=options)


class CalendarService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def configured(self) -> bool:
        return all(
            [
                has_value(self.settings.GOOGLE_CALENDAR_CREDENTIALS_JSON),
                has_value(self.settings.GOOGLE_CALENDAR_ID),
            ],
        )

    def create_consultation(
        self,
        *,
        lead: Lead,
        summary: str,
        description: str,
    ) -> str | None:
        datetime_iso = getattr(lead, "preferred_time", None)
        if not datetime_iso:
            return None

        booked = book_slot(datetime_iso=datetime_iso, lead=lead)
        return datetime_iso if booked else None


def _calendar_service():
    credentials = load_google_credentials(
        [CALENDAR_SCOPE],
        file_value=settings.GOOGLE_CALENDAR_CREDENTIALS_JSON,
    )
    return build("calendar", "v3", credentials=credentials)


def _booked_ranges(start_at: datetime, end_at: datetime) -> list[tuple[datetime, datetime]]:
    # Legacy helper used by `get_available_slots`. It only reads the
    # booking calendar's events list — the production pipeline uses
    # `_free_busy_intervals` which honours BUSY_CALENDAR_IDS. This
    # helper is kept for back-compat callers; new code should not use
    # it.
    events = _calendar_service().events().list(
        calendarId=settings.booking_calendar_id(),
        timeMin=start_at.isoformat(),
        timeMax=end_at.isoformat(),
        singleEvents=True,
        orderBy="startTime",
    ).execute()

    ranges = []
    for event in events.get("items", []):
        event_start = _event_datetime(event.get("start", {}), is_end=False)
        event_end = _event_datetime(event.get("end", {}), is_end=True)
        if event_start and event_end:
            ranges.append((event_start, event_end))
    return ranges


def _event_datetime(value: dict, *, is_end: bool) -> datetime | None:
    if value.get("dateTime"):
        return _parse_iso_datetime(value["dateTime"])
    if value.get("date"):
        parsed_date = date.fromisoformat(value["date"])
        event_time = time(23, 59) if is_end else time(0, 0)
        return datetime.combine(parsed_date, event_time, tzinfo=TIMEZONE)
    return None


def _parse_iso_datetime(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=TIMEZONE)
    return parsed.astimezone(TIMEZONE)


def _overlaps_booked(
    slot_start: datetime,
    slot_end: datetime,
    booked_ranges: list[tuple[datetime, datetime]],
) -> bool:
    return any(slot_start < booked_end and slot_end > booked_start for booked_start, booked_end in booked_ranges)


def _format_slot(slot_start: datetime) -> dict:
    return {
        "date": f"{slot_start.day} {GEORGIAN_MONTHS[slot_start.month]}",
        "time": slot_start.strftime("%H:%M"),
        "datetime_iso": slot_start.isoformat(),
    }


def _format_options(count: int) -> str:
    if count <= 0:
        return ""
    if count == 1:
        return "1"
    if count == 2:
        return f"1{CALENDAR_OPTIONS_SEPARATOR}2"

    numbers = [str(index) for index in range(1, count + 1)]
    return f"{', '.join(numbers[:-1])}{CALENDAR_OPTIONS_SEPARATOR}{numbers[-1]}"
