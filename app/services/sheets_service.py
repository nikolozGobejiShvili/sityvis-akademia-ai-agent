import json
import logging
from datetime import datetime, timedelta
from typing import Any

import gspread
from gspread.exceptions import WorksheetNotFound

from app.agent.services.timestamps import (
    TBILISI_TZ,
    format_tbilisi_datetime,
    now_tbilisi,
    to_tbilisi,
)
from app.config import Settings, has_value, settings
from app.models.lead import Lead
from app.services.google_credentials import load_google_credentials

logger = logging.getLogger(__name__)

# gspread's historical default scopes (spreadsheets + drive). Passed
# explicitly so `gspread.authorize(load_google_credentials(...))` behaves
# identically to the previous `gspread.service_account_from_dict(...)`.
SHEETS_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def _sheets_client() -> gspread.Client:
    """Authorised gspread client. Single auth chokepoint — credentials are
    resolved Railway-safely via the shared loader (GOOGLE_CREDENTIALS_JSON
    env wins; per-service path / inline JSON fallback)."""
    credentials = load_google_credentials(
        SHEETS_SCOPES,
        file_value=settings.GOOGLE_SHEETS_CREDENTIALS_JSON,
    )
    return gspread.authorize(credentials)

HEADERS = [
    "ID",
    "Sender ID",
    "Platform",
    "Segment",
    "Name",
    "Phone",
    "Child Age",
    "Challenge",
    "Deeper Concern",
    "Desired Change",
    "Event Interest",
    "Consultation Booked",
    "Conversation Summary",
    "Status",
    "Created At",
    "Last Activity",
    "Follow-up Sent",
]

# Adult Event Subscription Patch (2026-06-08): subscribers tab.
# A dedicated Sheets tab that stores adult/cultural-event broadcast
# subscribers. The tab is created on first write; one active row per
# (platform, sender_id) pair. The broadcast service reads it to fan
# out new-event notifications.
EVENTS_TAB = "events"
EVENT_SUBSCRIBER_HEADERS = [
    "Created At",
    "Updated At",
    "Platform",
    "Sender ID",
    "Name",
    "Phone",
    "Status",
    "Consent",
    "Consent At",
    "Source Event ID",
    "Source Event Title",
    "Source Event Link",
    "Age",
    "Last Notified Event ID",
    "Last Notified At",
    "Notified Event IDs",
    "Unsubscribe At",
    "Notes",
]
EVENT_SUBSCRIBER_COLUMN_INDEX = {
    header: index for index, header in enumerate(EVENT_SUBSCRIBER_HEADERS, start=1)
}
EVENT_SUBSCRIBER_UPDATE_COLUMNS = {
    "created_at": "Created At",
    "updated_at": "Updated At",
    "platform": "Platform",
    "sender_id": "Sender ID",
    "name": "Name",
    "phone": "Phone",
    "status": "Status",
    "consent": "Consent",
    "consent_at": "Consent At",
    "source_event_id": "Source Event ID",
    "source_event_title": "Source Event Title",
    "source_event_link": "Source Event Link",
    "age": "Age",
    "last_notified_event_id": "Last Notified Event ID",
    "last_notified_at": "Last Notified At",
    "notified_event_ids": "Notified Event IDs",
    "unsubscribe_at": "Unsubscribe At",
    "notes": "Notes",
}

COMMENTS_TAB = "Comments"
COMMENT_HEADERS = [
    "Comment ID",
    "Post ID",
    "Sender ID",
    "User Name",
    "Platform",
    "Segment",
    "Comment Text",
    "Intent",
    "DM Sent",
    "Status",
    "Created At",
]
COMMENT_COLUMN_INDEX = {header: index for index, header in enumerate(COMMENT_HEADERS, start=1)}
COMMENT_UPDATE_COLUMNS = {
    "comment_id": "Comment ID",
    "post_id": "Post ID",
    "sender_id": "Sender ID",
    "user_name": "User Name",
    "platform": "Platform",
    "segment": "Segment",
    "comment_text": "Comment Text",
    "intent": "Intent",
    "dm_sent": "DM Sent",
    "status": "Status",
    "created_at": "Created At",
}

COLUMN_INDEX = {header: index for index, header in enumerate(HEADERS, start=1)}
UPDATE_COLUMNS = {
    "id": "ID",
    "sender_id": "Sender ID",
    "platform": "Platform",
    "segment": "Segment",
    "name": "Name",
    "phone": "Phone",
    "child_age": "Child Age",
    "challenge": "Challenge",
    "deeper_concern": "Deeper Concern",
    "desired_change": "Desired Change",
    "event_interest": "Event Interest",
    "consultation_booked": "Consultation Booked",
    "calendly_booked": "Consultation Booked",
    "conversation_summary": "Conversation Summary",
    "status": "Status",
    "created_at": "Created At",
    "last_activity": "Last Activity",
    "last_message_at": "Last Activity",
    "followup_sent": "Follow-up Sent",
    "follow_up_sent": "Follow-up Sent",
}


def _active_leads_headers() -> list[str]:
    """The Leads header row for the CURRENT flag state.

    Per-Product Booking (Cap #2 / R1): with ``USE_PER_PRODUCT_BOOKING`` ON a
    trailing ``"Program"`` column is appended so a booking lead can carry its
    admin product id. OFF ⇒ the canonical 17-column ``HEADERS`` unchanged
    (byte-identical). Adding a trailing column never shifts an existing column,
    so every existing reader (``_row_to_lead``, ``COLUMN_INDEX``) is unaffected.
    """
    if getattr(settings, "USE_PER_PRODUCT_BOOKING", False):
        return HEADERS + ["Program"]
    return HEADERS


def _leads_last_col_a1() -> str:
    """A1 column letter of the final Leads header (``Q`` for 17 cols, ``R`` for
    18 when the per-product Program column is active)."""
    return chr(ord("A") + len(_active_leads_headers()) - 1)


def _append_lead_row_aligned(worksheet: Any, row: list[Any]) -> None:
    """Append a Leads row to an EXPLICIT, A-anchored full-row range.

    P0 data-integrity fix (2026-06-18): the previous
    ``worksheet.append_row(row, value_input_option="USER_ENTERED")`` sent
    gspread's default UNBOUNDED sheet range (``'Leads'``) to the Sheets
    ``values.append`` API, which then relied on Google's "logical table"
    auto-detection to choose BOTH the target row AND the start column. On a
    live sheet whose data region was not cleanly anchored at column A, that
    detection placed the new row under the detected table's FIRST column —
    to the right of A — so every value landed under the wrong header (the
    shift the operator observed).

    Writing to an explicit ``A{n}:{last}{n}`` range pins all
    ``len(HEADERS)`` values to columns A..{last} in header order,
    independent of any table-detection heuristic. ``next_row`` is computed
    from the current data extent so the row is appended after the last
    populated row. ``value_input_option="USER_ENTERED"`` preserves the
    historical cell parsing (numeric ID, TRUE/FALSE booleans, Asia/Tbilisi
    datetime strings) so new rows match the older correctly-aligned rows
    byte-for-byte. The Leads schema (headers / order / count) is unchanged.
    """
    next_row = len(worksheet.get_all_values()) + 1
    # Anchor the range to the ACTUAL row width so the flag-gated 18th "Program"
    # column (Cap #2 / R1) lands in R while a legacy 17-col row still writes
    # A..Q byte-identically. Deriving from len(row) keeps range and payload in
    # lock-step regardless of flag state.
    last_col = chr(ord("A") + len(row) - 1)
    worksheet.update(
        range_name=f"A{next_row}:{last_col}{next_row}",
        values=[row],
        value_input_option="USER_ENTERED",
    )


def save_lead(lead: Lead) -> bool:
    logger.info(
        "[SHEETS] save_lead called: sender_id=%s segment=%s status=%s",
        lead.sender_id, lead.segment, lead.status,
    )
    try:
        worksheet = _worksheet()
        row = _lead_to_row(lead, _next_id(worksheet))
        _append_lead_row_aligned(worksheet, row)
        logger.info(
            "[SHEETS] ✅ Lead row appended (A-anchored): sender_id=%s",
            lead.sender_id,
        )
        return True
    except Exception as exc:
        logger.exception("[SHEETS] ❌ Failed to save lead sender_id=%s: %s", lead.sender_id, exc)
        return False


def append_lead(lead: Lead) -> bool:
    return save_lead(lead)


def update_lead(sender_id: str, updates: dict) -> bool:
    try:
        worksheet = _worksheet()
        row_index = _find_row_by_sender_id(worksheet, sender_id)
        if row_index is None:
            logger.warning("[SHEETS] Lead not found for update: sender_id=%s", sender_id)
            return False

        changed = False
        for key, value in updates.items():
            header = UPDATE_COLUMNS.get(key, key)
            column_index = COLUMN_INDEX.get(header)
            if not column_index:
                logger.warning("[SHEETS] Ignored unknown update column: %s", key)
                continue

            worksheet.update_cell(row_index, column_index, _serialize_cell(value))
            changed = True

        logger.info("[SHEETS] Lead updated: sender_id=%s", sender_id)
        return changed
    except Exception as exc:
        logger.exception("[SHEETS] Failed to update lead sender_id=%s: %s", sender_id, exc)
        return False


def mark_old_booking_rescheduled(
    sender_id: str,
    *,
    new_status: str = "Rescheduled",
    booked_status_label: str = "Booked",
) -> tuple[bool, str]:
    """Live QA Session 8 Patch (2026-06-07) — Bug 2.

    Locate the OLDEST row matching ``sender_id`` whose ``Status`` cell
    equals ``booked_status_label`` and update it to ``new_status``.
    Leaves any LATER ``booked_status_label`` row alone — that is the
    fresh active booking the reschedule just created.

    Why this exists: the legacy ``update_lead(sender_id, {"status":
    "Rescheduled"})`` matches the FIRST sender_id row regardless of
    status, which can be a pre-booking discovery row. The live
    consequence was that the OLD booking row was left as ``Booked``
    and a non-booking row was relabelled instead — two ``Booked``
    rows survived for one sender. This helper enforces the
    single-active-booking invariant directly.

    Returns ``(True, "ok")`` on a successful update. Returns
    ``(False, reason)`` when nothing was matched / Sheets API failed
    — callers MUST NOT claim CRM consistency in that case. Never
    raises.

    Privacy: log lines mask the sender id via the standard
    ``sentry_service.mask_sender`` helper. No raw phone / name / row
    content is emitted.
    """
    from app.services import sentry_service
    masked_sender = sentry_service.mask_sender(sender_id)
    try:
        worksheet = _worksheet()
    except Exception as exc:
        logger.warning(
            "[SHEETS] mark_old_booking_rescheduled: worksheet open failed "
            "sender=%s: %s", masked_sender, exc,
        )
        return False, "worksheet_unavailable"

    try:
        sender_col = COLUMN_INDEX["Sender ID"]
        status_col = COLUMN_INDEX["Status"]
        sender_values = worksheet.col_values(sender_col)
        status_values = worksheet.col_values(status_col)
    except Exception as exc:
        logger.warning(
            "[SHEETS] mark_old_booking_rescheduled: read failed "
            "sender=%s: %s", masked_sender, exc,
        )
        return False, "read_failed"

    candidates: list[int] = []
    sender_clean = str(sender_id).strip()
    booked_label_clean = str(booked_status_label).strip()
    for idx, value in enumerate(sender_values, start=1):
        if idx == 1:  # header row
            continue
        if str(value).strip() != sender_clean:
            continue
        if idx - 1 >= len(status_values):
            continue
        status_value = (
            status_values[idx - 1] if idx - 1 < len(status_values) else ""
        )
        if str(status_value).strip() == booked_label_clean:
            candidates.append(idx)

    if not candidates:
        logger.warning(
            "[SHEETS] mark_old_booking_rescheduled: no booked row found "
            "sender=%s", masked_sender,
        )
        return False, "no_booked_row"

    # Oldest = lowest row index.
    target_row = candidates[0]
    try:
        worksheet.update_cell(target_row, status_col, str(new_status))
    except Exception as exc:
        logger.warning(
            "[SHEETS] mark_old_booking_rescheduled: write failed "
            "sender=%s row=%d: %s", masked_sender, target_row, exc,
        )
        return False, "write_failed"

    logger.info(
        "[SHEETS] mark_old_booking_rescheduled: sender=%s row=%d "
        "status=%s booked_rows_total=%d",
        masked_sender, target_row, new_status, len(candidates),
    )
    return True, "ok"


def get_cold_leads() -> list[Lead]:
    try:
        worksheet = _worksheet()
        rows = worksheet.get_all_records()
        # Timezone-aware cutoff in Asia/Tbilisi. Sheets writes timestamps
        # via `_datetime_text` (`format_tbilisi_datetime` → ISO with
        # explicit +04:00 offset), so `last_activity` parsed from a row
        # is tz-aware. Comparing it against a naive `datetime.utcnow()`
        # raises `TypeError: can't compare offset-naive and offset-aware
        # datetimes` — that's the bug `HANDOFF.md §5 IMPORTANT 3` flags.
        # Use `now_tbilisi()` so both sides of the comparison live in
        # the same timezone.
        cutoff = now_tbilisi() - timedelta(hours=48)
        cold_leads = []

        for row in rows:
            status = str(row.get("Status", "")).strip()
            followup_sent = _to_bool(row.get("Follow-up Sent"))
            last_activity = _parse_datetime(row.get("Last Activity"))

            if status not in {"New", "Qualified"}:
                continue
            if followup_sent:
                continue
            if not last_activity:
                continue
            # `_parse_datetime` can return either an aware or a naive
            # datetime depending on the cell value. Promote naive to
            # Asia/Tbilisi (the canonical write-side timezone) so the
            # comparison against `cutoff` is always like-for-like.
            if last_activity.tzinfo is None:
                last_activity = to_tbilisi(last_activity)
            if last_activity >= cutoff:
                continue

            cold_leads.append(_row_to_lead(row))

        logger.info("[SHEETS] Cold leads loaded: count=%s", len(cold_leads))
        return cold_leads
    except Exception as exc:
        logger.exception("[SHEETS] Failed to get cold leads: %s", exc)
        return []


def get_lead(sender_id: str) -> Lead | None:
    try:
        worksheet = _worksheet()
        row_index = _find_row_by_sender_id(worksheet, sender_id)
        if row_index is None:
            logger.info("[SHEETS] Lead not found: sender_id=%s", sender_id)
            return None

        values = worksheet.row_values(row_index)
        row = {
            header: values[index] if index < len(values) else ""
            for index, header in enumerate(HEADERS)
        }
        logger.info("[SHEETS] Lead loaded: sender_id=%s", sender_id)
        return _row_to_lead(row)
    except Exception as exc:
        logger.exception("[SHEETS] Failed to get lead sender_id=%s: %s", sender_id, exc)
        return None


def create_lead(lead: Lead) -> bool:
    return save_lead(lead)


class SheetsService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def configured(self) -> bool:
        return all(
            [
                has_value(self.settings.GOOGLE_SHEETS_CREDENTIALS_JSON),
                has_value(self.settings.GOOGLE_SHEETS_SPREADSHEET_ID),
                has_value(self.settings.GOOGLE_SHEETS_LEADS_TAB),
            ],
        )

    def append_lead(self, lead: Lead, reply: str = "") -> bool:
        return save_lead(lead)


def _worksheet() -> Any:
    client = _sheets_client()
    spreadsheet = client.open_by_key(settings.GOOGLE_SHEETS_SPREADSHEET_ID)

    try:
        worksheet = spreadsheet.worksheet(settings.GOOGLE_SHEETS_LEADS_TAB)
    except WorksheetNotFound:
        worksheet = spreadsheet.add_worksheet(
            title=settings.GOOGLE_SHEETS_LEADS_TAB,
            rows=1000,
            cols=len(_active_leads_headers()),
        )
        logger.info("[SHEETS] Worksheet created: %s", settings.GOOGLE_SHEETS_LEADS_TAB)

    _ensure_headers(worksheet)
    return worksheet


def _ensure_headers(worksheet: Any) -> None:
    headers = _active_leads_headers()
    current_headers = worksheet.row_values(1)
    if current_headers != headers:
        last_col = chr(ord("A") + len(headers) - 1)
        worksheet.resize(cols=len(headers))
        worksheet.update(f"A1:{last_col}1", [headers])
        logger.info("[SHEETS] Header row updated (cols=A1:%s1)", last_col)


def _next_id(worksheet: Any) -> int:
    values = worksheet.col_values(COLUMN_INDEX["ID"])[1:]
    ids = []
    for value in values:
        try:
            ids.append(int(value))
        except (TypeError, ValueError):
            continue
    return max(ids, default=0) + 1


_ADULT_EVENT_INTEREST_STEMS_FOR_SCRUB: tuple[str, ...] = (
    "ზრდასრულთა",
    "ზრდასრულ",
    "კულტურულ საღამო",
    "კულტურული საღამო",
    "კულტურულ ღონისძიებ",
    "კულტურული ღონისძიებ",
    "ღონისძიებ",
    "საღამოს ღონისძიებ",
    "პოეზიის საღამო",
    "მუსიკალური საღამო",
    "ლიტერატურული საღამო",
    "მუფასა",
    "ელტონ ჯონ",
    # Bare „საღამო" / „ბილეთ" alone are intentionally OMITTED — they
    # could appear in a legitimate PARENT-flow note without implying
    # adult-event intent. The scrub list is conservative: it only
    # trips on phrases that mean cultural-events specifically.
)


def _scrub_event_interest_for_segment(lead: Lead) -> str:
    """Lead Field Separation — Sheets layer.

    PARENT segment Sheets rows must NOT carry ADULT event-interest
    vocabulary in the Event Interest column. A previous turn in the
    ADULT flow may have set ``lead.event_interest = "ზრდასრულთა
    საღამოები"``; when the same lead later books a camp consultation
    (PARENT) the row write goes through ``_lead_to_row`` and would
    otherwise echo the stale ADULT value back into the CRM.

    Rule:
      * segment == "PARENT" + event_interest contains adult-event
        vocabulary → write empty string in the Event Interest column.
      * Any other shape (ADULT / UNCLEAR / non-matching text) →
        pass through unchanged.

    The function returns the value to write — the in-memory ``lead``
    object is NOT mutated, so the ADULT engine can still read the
    historical interest if the user re-enters the ADULT flow.

    Live QA Bug Fix Patch (2026-06-04).
    """
    raw = lead.event_interest or ""
    if not raw:
        return raw
    if (lead.segment or "").strip().upper() != "PARENT":
        return raw
    lowered = raw.lower()
    for stem in _ADULT_EVENT_INTEREST_STEMS_FOR_SCRUB:
        if stem in lowered:
            return ""
    return raw


def _lead_to_row(lead: Lead, lead_id: int) -> list[Any]:
    event_interest_cell = _scrub_event_interest_for_segment(lead)
    row = [
        lead_id,
        lead.sender_id,
        lead.platform,
        lead.segment,
        lead.name,
        lead.phone,
        lead.child_age,
        lead.challenge,
        lead.deeper_concern,
        lead.desired_change,
        event_interest_cell,
        _bool_text(lead.calendly_booked),
        lead.conversation_summary,
        lead.status,
        _datetime_text(lead.created_at),
        _datetime_text(lead.last_message_at),
        _bool_text(lead.followup_sent),
    ]
    # Per-Product Booking (Cap #2 / R1) — flag-gated trailing "Program" column.
    # OFF ⇒ the 17-col A–Q row above, byte-identical. ON ⇒ append the lead's
    # admin product id (empty for a camp/legacy lead) so the width matches
    # `_active_leads_headers()`.
    if getattr(settings, "USE_PER_PRODUCT_BOOKING", False):
        row.append(getattr(lead, "program_id", "") or "")
    return row


def _row_to_lead(row: dict[str, Any]) -> Lead:
    lead = Lead(
        sender_id=str(row.get("Sender ID", "")),
        platform=str(row.get("Platform", "")),
        segment=str(row.get("Segment", "")),
        name=str(row.get("Name", "")),
        phone=str(row.get("Phone", "")),
        child_age=str(row.get("Child Age", "")),
        challenge=str(row.get("Challenge", "")),
        deeper_concern=str(row.get("Deeper Concern", "")),
        desired_change=str(row.get("Desired Change", "")),
        event_interest=str(row.get("Event Interest", "")),
        calendly_booked=_to_bool(row.get("Consultation Booked")),
        conversation_summary=str(row.get("Conversation Summary", "")),
        status=str(row.get("Status", "New") or "New"),
        created_at=_parse_datetime(row.get("Created At")) or datetime.utcnow(),
        last_message_at=_parse_datetime(row.get("Last Activity")) or datetime.utcnow(),
    )
    lead.followup_sent = _to_bool(row.get("Follow-up Sent"))
    return lead


def _find_row_by_sender_id(worksheet: Any, sender_id: str) -> int | None:
    sender_ids = worksheet.col_values(COLUMN_INDEX["Sender ID"])
    for row_index, value in enumerate(sender_ids, start=1):
        if row_index == 1:
            continue
        if str(value).strip() == str(sender_id).strip():
            return row_index
    return None


def _serialize_cell(value: Any) -> Any:
    if isinstance(value, bool):
        return _bool_text(value)
    if isinstance(value, datetime):
        return _datetime_text(value)
    return value


def _datetime_text(value: datetime) -> str:
    """Render a datetime for persistence in the Leads / Comments sheet.

    P2: ALL Sheets-written timestamps are in Asia/Tbilisi with an explicit
    offset. Naive datetimes (from `datetime.utcnow()` elsewhere in the
    codebase) are interpreted as UTC and converted; aware datetimes are
    converted via `astimezone`. The previous behaviour was to ship the
    naive ISO directly, which Sheets displayed in the wrong timezone.
    """
    return format_tbilisi_datetime(value)


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not value:
        return None

    text = str(value).strip()
    for parser in (
        datetime.fromisoformat,
        lambda item: datetime.strptime(item, "%Y-%m-%d %H:%M:%S"),
        lambda item: datetime.strptime(item, "%Y-%m-%d"),
    ):
        try:
            return parser(text)
        except ValueError:
            continue
    return None


def _to_bool(value: Any) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes", "კი", "დიახ"}


def _bool_text(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def save_comment(comment_data: dict) -> bool:
    try:
        worksheet = _comments_worksheet()
        row = _comment_to_row(comment_data)
        worksheet.append_row(row, value_input_option="USER_ENTERED")
        logger.info("[SHEETS] Comment saved: %s", comment_data.get("comment_id"))
        return True
    except Exception as exc:
        logger.exception(
            "[SHEETS] Failed to save comment %s: %s",
            comment_data.get("comment_id"),
            exc,
        )
        return False


def update_comment(comment_id: str, updates: dict) -> bool:
    try:
        worksheet = _comments_worksheet()
        row_index = _find_comment_row(worksheet, comment_id)
        if row_index is None:
            logger.warning("[SHEETS] Comment not found for update: %s", comment_id)
            return False

        changed = False
        for key, value in updates.items():
            header = COMMENT_UPDATE_COLUMNS.get(key, key)
            column_index = COMMENT_COLUMN_INDEX.get(header)
            if not column_index:
                logger.warning("[SHEETS] Ignored unknown comment column: %s", key)
                continue

            worksheet.update_cell(row_index, column_index, _serialize_cell(value))
            changed = True

        logger.info("[SHEETS] Comment updated: %s", comment_id)
        return changed
    except Exception as exc:
        logger.exception("[SHEETS] Failed to update comment %s: %s", comment_id, exc)
        return False


def get_pending_comment_followups() -> list[dict]:
    """Comment-followup eligibility — Comment Follow-up Logic Fix
    (2026-05-31).

    A row is eligible only when the INITIAL private DM was confirmed
    sent:

        DM Sent (column I) == TRUE
        Status (column J)   == "DMSent"

    Rows that fail either check are skipped — including the historical
    ``CommentOnly`` rows the old scheduler tried (and failed) to follow
    up via Meta replies API. The previous behaviour drove the 400-loop
    that operators observed every hour.

    Successful sends are marked ``FollowupSent``; permanent failures
    (Meta 400 on the comment_id) are marked ``Expired``. Both states
    are skipped on subsequent ticks.
    """
    try:
        worksheet = _comments_worksheet()
        rows = worksheet.get_all_records()
        cutoff_hours = settings.COMMENT_FOLLOWUP_HOURS
        # Same timezone bug as `get_cold_leads` — Sheets writes Tbilisi-
        # aware ISO strings; compare in the same tz.
        cutoff = now_tbilisi() - timedelta(hours=cutoff_hours)
        pending: list[dict] = []

        for row in rows:
            status = str(row.get("Status", "")).strip()
            # Only the post-DM "waiting for reply" state is eligible.
            # CommentOnly = initial DM never confirmed → skip.
            # FollowupSent / Expired = already terminal → skip.
            if status != "DMSent":
                continue
            # Belt-and-braces: even if Status says "DMSent", require
            # the DM Sent boolean cell to match. Treat empty / missing
            # / non-true values as false.
            if not _to_bool(row.get("DM Sent")):
                continue
            created_at = _parse_datetime(row.get("Created At"))
            if not created_at:
                continue
            if created_at.tzinfo is None:
                created_at = to_tbilisi(created_at)
            if created_at >= cutoff:
                continue
            pending.append(_comment_row_to_dict(row))

        logger.info("[SHEETS] Pending comment follow-ups: %s", len(pending))
        return pending
    except Exception as exc:
        logger.exception("[SHEETS] Failed to load pending comment follow-ups: %s", exc)
        return []


def _comments_worksheet() -> Any:
    client = _sheets_client()
    spreadsheet = client.open_by_key(settings.GOOGLE_SHEETS_SPREADSHEET_ID)

    try:
        worksheet = spreadsheet.worksheet(COMMENTS_TAB)
    except WorksheetNotFound:
        worksheet = spreadsheet.add_worksheet(
            title=COMMENTS_TAB,
            rows=1000,
            cols=len(COMMENT_HEADERS),
        )
        logger.info("[SHEETS] Worksheet created: %s", COMMENTS_TAB)

    _ensure_comment_headers(worksheet)
    return worksheet


def _ensure_comment_headers(worksheet: Any) -> None:
    current_headers = worksheet.row_values(1)
    if current_headers != COMMENT_HEADERS:
        worksheet.resize(cols=len(COMMENT_HEADERS))
        worksheet.update("A1:K1", [COMMENT_HEADERS])
        logger.info("[SHEETS] Comment header row updated")


def _comment_to_row(data: dict) -> list[Any]:
    created_at = data.get("created_at")
    if isinstance(created_at, datetime):
        created_at = _datetime_text(created_at)
    elif isinstance(created_at, str) and created_at:
        # Best-effort: if a caller passed a naive UTC ISO string, re-format
        # into Asia/Tbilisi so Sheets shows the correct local time. Strings
        # that already carry an offset round-trip through `_datetime_text`
        # cleanly.
        try:
            parsed = datetime.fromisoformat(created_at)
            created_at = _datetime_text(parsed)
        except ValueError:
            pass  # leave unparseable strings as-is

    return [
        str(data.get("comment_id", "")),
        str(data.get("post_id", "")),
        str(data.get("sender_id", "")),
        str(data.get("user_name", "")),
        str(data.get("platform", "")),
        str(data.get("segment", "")),
        str(data.get("comment_text", "")),
        str(data.get("intent", "")),
        _bool_text(bool(data.get("dm_sent", False))),
        str(data.get("status", "")),
        str(created_at or _datetime_text(now_tbilisi())),
    ]


def _comment_row_to_dict(row: dict[str, Any]) -> dict:
    return {
        "comment_id": str(row.get("Comment ID", "")),
        "post_id": str(row.get("Post ID", "")),
        "sender_id": str(row.get("Sender ID", "")),
        "user_name": str(row.get("User Name", "")),
        "platform": str(row.get("Platform", "")),
        "segment": str(row.get("Segment", "")),
        "comment_text": str(row.get("Comment Text", "")),
        "intent": str(row.get("Intent", "")),
        "dm_sent": _to_bool(row.get("DM Sent")),
        "status": str(row.get("Status", "")),
        "created_at": row.get("Created At", ""),
    }


def _find_comment_row(worksheet: Any, comment_id: str) -> int | None:
    values = worksheet.col_values(COMMENT_COLUMN_INDEX["Comment ID"])
    for row_index, value in enumerate(values, start=1):
        if row_index == 1:
            continue
        if str(value).strip() == str(comment_id).strip():
            return row_index
    return None


# ---------------------------------------------------------------------------
# Adult Event Subscription Patch (2026-06-08) — `events` tab CRUD
# ---------------------------------------------------------------------------
#
# A dedicated Sheets tab persists adult-event subscribers. The tab is
# created on first write; one active row per (platform, sender_id)
# pair. The broadcast service reads it to fan out new-event notifications
# and marks `Notified Event IDs` after each successful send.
#
# Phones are NEVER logged in full. Logs use the `sentry_service.mask_sender`
# helper for ids and a small `_mask_phone` for phones.


def _event_subscribers_worksheet() -> Any:
    client = _sheets_client()
    spreadsheet = client.open_by_key(settings.GOOGLE_SHEETS_SPREADSHEET_ID)
    try:
        worksheet = spreadsheet.worksheet(EVENTS_TAB)
    except WorksheetNotFound:
        worksheet = spreadsheet.add_worksheet(
            title=EVENTS_TAB,
            rows=1000,
            cols=len(EVENT_SUBSCRIBER_HEADERS),
        )
        logger.info("[SHEETS] Worksheet created: %s", EVENTS_TAB)
    _ensure_event_subscriber_headers(worksheet)
    return worksheet


def _ensure_event_subscriber_headers(worksheet: Any) -> None:
    current_headers = worksheet.row_values(1)
    if current_headers != EVENT_SUBSCRIBER_HEADERS:
        last_col = chr(ord("A") + len(EVENT_SUBSCRIBER_HEADERS) - 1)
        worksheet.resize(cols=len(EVENT_SUBSCRIBER_HEADERS))
        worksheet.update(f"A1:{last_col}1", [EVENT_SUBSCRIBER_HEADERS])
        logger.info("[SHEETS] events header row written")


def _mask_phone(phone: str | None) -> str:
    if not phone:
        return ""
    digits = "".join(ch for ch in str(phone) if ch.isdigit())
    if len(digits) < 6:
        return "***"
    return f"{digits[:3]}***{digits[-3:]}"


# ---------------------------------------------------------------------------
# Sunday School Lead Log (2026-06-22) — a SEPARATE tab, intentionally
# decoupled from the camp-booking A-Q "Leads" schema. It NEVER touches the
# booking sheet (`_worksheet` / HEADERS / `_append_lead_row_aligned`). The
# tab is created on first write. Best-effort: a failure here returns False
# and is logged but MUST NOT block the Sunday-school email handoff.
# ---------------------------------------------------------------------------
SUNDAY_SCHOOL_TAB = "SundaySchoolLeads"
SUNDAY_SCHOOL_HEADERS = [
    "created_at",
    "channel",
    "sender_id_masked",
    "name",
    "phone",
    "lead_type",
    "source",
    "user_message",
    "status",
    "notification_status",
]


def _mask_sender_id(sender_id: str | None) -> str:
    s = str(sender_id or "")
    if len(s) <= 4:
        return "***"
    return f"{s[:2]}***{s[-3:]}"


def _sunday_school_worksheet() -> Any:
    client = _sheets_client()
    spreadsheet = client.open_by_key(settings.GOOGLE_SHEETS_SPREADSHEET_ID)
    try:
        worksheet = spreadsheet.worksheet(SUNDAY_SCHOOL_TAB)
    except WorksheetNotFound:
        worksheet = spreadsheet.add_worksheet(
            title=SUNDAY_SCHOOL_TAB,
            rows=1000,
            cols=len(SUNDAY_SCHOOL_HEADERS),
        )
        logger.info("[SHEETS] Worksheet created: %s", SUNDAY_SCHOOL_TAB)
    _ensure_sunday_school_headers(worksheet)
    return worksheet


def _ensure_sunday_school_headers(worksheet: Any) -> None:
    current_headers = worksheet.row_values(1)
    if current_headers != SUNDAY_SCHOOL_HEADERS:
        last_col = chr(ord("A") + len(SUNDAY_SCHOOL_HEADERS) - 1)
        worksheet.resize(cols=len(SUNDAY_SCHOOL_HEADERS))
        worksheet.update(f"A1:{last_col}1", [SUNDAY_SCHOOL_HEADERS])
        logger.info("[SHEETS] SundaySchoolLeads header row written")


def log_sunday_school_lead(
    lead: Lead,
    *,
    user_message: str = "",
    notification_status: str = "sent",
) -> bool:
    """Append ONE row to the SEPARATE ``SundaySchoolLeads`` tab.

    Best-effort and isolated:
      * returns False (never raises) when Sheets is unconfigured or the write
        fails — the caller MUST NOT let this block the email handoff;
      * does NOT touch the camp-booking ``Leads`` (A-Q) schema or any other tab.
    """
    if not has_value(settings.GOOGLE_SHEETS_SPREADSHEET_ID):
        logger.warning(
            "[SHEETS] SundaySchoolLeads skipped — Sheets not configured",
        )
        return False
    try:
        worksheet = _sunday_school_worksheet()
        row = [
            now_tbilisi().isoformat(),
            lead.platform or "",
            _mask_sender_id(lead.sender_id),
            lead.name or "",
            lead.phone or "",
            "sunday_school",
            "messenger_dm",
            (user_message or "")[:300],
            "new",
            notification_status,
        ]
        worksheet.append_row(row)
        logger.info(
            "[SHEETS] SundaySchoolLeads row appended sender=%s",
            _mask_sender_id(lead.sender_id),
        )
        return True
    except Exception as exc:
        logger.exception("[SHEETS] SundaySchoolLeads write failed: %s", exc)
        return False


def _normalise_notified_ids(value: Any) -> list[str]:
    """Parse the `Notified Event IDs` cell — accepts comma-separated
    text or a JSON array; returns a deduplicated, ordered list."""
    if not value:
        return []
    text = str(value).strip()
    if not text:
        return []
    if text.startswith("["):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                seen: set[str] = set()
                out: list[str] = []
                for item in parsed:
                    s = str(item).strip()
                    if s and s not in seen:
                        seen.add(s)
                        out.append(s)
                return out
        except json.JSONDecodeError:
            pass
    seen: set[str] = set()
    out: list[str] = []
    for chunk in text.split(","):
        s = chunk.strip()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def _serialise_notified_ids(ids: list[str]) -> str:
    """Persist the notified-ids list as a CSV string. Comma-separated is
    operator-friendly in Sheets (no JSON brackets to fight with), and
    `_normalise_notified_ids` re-parses either form."""
    if not ids:
        return ""
    return ", ".join(ids)


def _find_event_subscriber_row(
    worksheet: Any, platform: str, sender_id: str,
) -> int | None:
    """Return the 1-based row index of the subscriber matching
    (platform, sender_id), or None."""
    platform_clean = (str(platform) or "").strip()
    sender_clean = (str(sender_id) or "").strip()
    if not sender_clean:
        return None
    platforms = worksheet.col_values(
        EVENT_SUBSCRIBER_COLUMN_INDEX["Platform"],
    )
    senders = worksheet.col_values(
        EVENT_SUBSCRIBER_COLUMN_INDEX["Sender ID"],
    )
    for idx in range(2, len(senders) + 1):
        row_sender = senders[idx - 1] if idx - 1 < len(senders) else ""
        row_platform = (
            platforms[idx - 1] if idx - 1 < len(platforms) else ""
        )
        if (
            str(row_sender).strip() == sender_clean
            and (
                not platform_clean
                or str(row_platform).strip() == platform_clean
            )
        ):
            return idx
    return None


def _event_subscriber_row(data: dict) -> list[Any]:
    """Render a dict into the event-subscribers row order."""
    now_text = _datetime_text(now_tbilisi())
    return [
        str(data.get("created_at") or now_text),
        str(data.get("updated_at") or now_text),
        str(data.get("platform", "")),
        str(data.get("sender_id", "")),
        str(data.get("name", "")),
        str(data.get("phone", "")),
        str(data.get("status") or "subscribed"),
        _bool_text(bool(data.get("consent", False))),
        str(data.get("consent_at", "")),
        str(data.get("source_event_id", "")),
        str(data.get("source_event_title", "")),
        str(data.get("source_event_link", "")),
        str(data.get("age", "")),
        str(data.get("last_notified_event_id", "")),
        str(data.get("last_notified_at", "")),
        str(data.get("notified_event_ids", "")),
        str(data.get("unsubscribe_at", "")),
        str(data.get("notes", "")),
    ]


def _event_subscriber_row_to_dict(row_values: list[Any]) -> dict:
    out: dict[str, Any] = {}
    for idx, header in enumerate(EVENT_SUBSCRIBER_HEADERS):
        out[header] = row_values[idx] if idx < len(row_values) else ""
    return {
        "created_at": out["Created At"],
        "updated_at": out["Updated At"],
        "platform": out["Platform"],
        "sender_id": out["Sender ID"],
        "name": out["Name"],
        "phone": out["Phone"],
        "status": (out["Status"] or "").strip(),
        "consent": _to_bool(out["Consent"]),
        "consent_at": out["Consent At"],
        "source_event_id": out["Source Event ID"],
        "source_event_title": out["Source Event Title"],
        "source_event_link": out["Source Event Link"],
        "age": out["Age"],
        "last_notified_event_id": out["Last Notified Event ID"],
        "last_notified_at": out["Last Notified At"],
        "notified_event_ids": _normalise_notified_ids(
            out["Notified Event IDs"],
        ),
        "unsubscribe_at": out["Unsubscribe At"],
        "notes": out["Notes"],
    }


def save_event_subscriber(data: dict) -> tuple[bool, str]:
    """Insert OR update a subscriber row by (platform, sender_id).

    Returns ``(True, "ok")`` on success, ``(False, reason)`` on Sheets
    failure. Never raises. Phones are masked in log lines.
    """
    from app.services import sentry_service

    platform = (str(data.get("platform") or "")).strip()
    sender_id = (str(data.get("sender_id") or "")).strip()
    if not platform or not sender_id:
        return False, "missing_identity"

    masked_sender = sentry_service.mask_sender(sender_id)
    try:
        worksheet = _event_subscribers_worksheet()
    except Exception as exc:
        logger.warning(
            "[SHEETS] events worksheet open failed sender=%s: %s",
            masked_sender, exc,
        )
        return False, "worksheet_unavailable"

    now_text = _datetime_text(now_tbilisi())
    data = dict(data)
    data.setdefault("created_at", now_text)
    data["updated_at"] = now_text
    if data.get("status") is None:
        data["status"] = "subscribed"

    try:
        existing_row = _find_event_subscriber_row(
            worksheet, platform, sender_id,
        )
    except Exception as exc:
        logger.warning(
            "[SHEETS] events lookup failed sender=%s: %s",
            masked_sender, exc,
        )
        return False, "read_failed"

    try:
        if existing_row is None:
            row = _event_subscriber_row(data)
            worksheet.append_row(row, value_input_option="USER_ENTERED")
            logger.info(
                "[SHEETS] events row appended platform=%s sender=%s "
                "phone=%s status=%s",
                platform, masked_sender,
                _mask_phone(data.get("phone")), data.get("status"),
            )
        else:
            # Read the existing row so we only overwrite fields that the
            # caller actually provided (operator UX: a partial save
            # should never wipe notified_event_ids).
            existing_values = worksheet.row_values(existing_row)
            existing_dict = _event_subscriber_row_to_dict(existing_values)
            merged: dict[str, Any] = dict(existing_dict)
            for k, v in data.items():
                if v is None:
                    continue
                if isinstance(v, str) and not v.strip():
                    continue
                merged[k] = v
            # Re-serialise the notified-ids list back to text form.
            if isinstance(merged.get("notified_event_ids"), list):
                merged["notified_event_ids"] = _serialise_notified_ids(
                    merged["notified_event_ids"],
                )
            row = _event_subscriber_row(merged)
            last_col = chr(ord("A") + len(EVENT_SUBSCRIBER_HEADERS) - 1)
            worksheet.update(
                f"A{existing_row}:{last_col}{existing_row}", [row],
            )
            logger.info(
                "[SHEETS] events row updated platform=%s sender=%s "
                "phone=%s status=%s",
                platform, masked_sender,
                _mask_phone(merged.get("phone")), merged.get("status"),
            )
    except Exception as exc:
        logger.warning(
            "[SHEETS] events write failed sender=%s: %s",
            masked_sender, exc,
        )
        return False, "write_failed"

    return True, "ok"


def get_event_subscriber(platform: str, sender_id: str) -> dict | None:
    """Return the subscriber row for (platform, sender_id), or None.
    Never raises — returns None on any Sheets failure.
    """
    from app.services import sentry_service
    masked_sender = sentry_service.mask_sender(sender_id)
    try:
        worksheet = _event_subscribers_worksheet()
        row_idx = _find_event_subscriber_row(worksheet, platform, sender_id)
        if row_idx is None:
            return None
        values = worksheet.row_values(row_idx)
        return _event_subscriber_row_to_dict(values)
    except Exception as exc:
        logger.warning(
            "[SHEETS] events get failed sender=%s: %s",
            masked_sender, exc,
        )
        return None


def list_event_subscribers(
    *,
    status: str | None = "subscribed",
    consent_required: bool = True,
) -> list[dict]:
    """Return every subscriber matching the filter (default: status =
    "subscribed" AND consent = TRUE). Never raises.
    """
    try:
        worksheet = _event_subscribers_worksheet()
        all_values = worksheet.get_all_values()
    except Exception as exc:
        logger.warning("[SHEETS] events list failed: %s", exc)
        return []
    if not all_values:
        return []
    out: list[dict] = []
    for row_values in all_values[1:]:  # skip header
        record = _event_subscriber_row_to_dict(row_values)
        if not (record["platform"] and record["sender_id"]):
            continue
        if status is not None and record["status"] != status:
            continue
        if consent_required and not record["consent"]:
            continue
        out.append(record)
    return out


def unsubscribe_event_subscriber(
    platform: str, sender_id: str,
) -> tuple[bool, str]:
    """Flip status → 'unsubscribed' and stamp `Unsubscribe At`.

    Returns ``(True, "ok")`` when the row was found and updated,
    ``(False, reason)`` otherwise. Reasons: ``not_subscribed``,
    ``worksheet_unavailable``, ``read_failed``, ``write_failed``.
    """
    from app.services import sentry_service
    masked_sender = sentry_service.mask_sender(sender_id)
    try:
        worksheet = _event_subscribers_worksheet()
    except Exception as exc:
        logger.warning(
            "[SHEETS] events unsubscribe worksheet open failed sender=%s: %s",
            masked_sender, exc,
        )
        return False, "worksheet_unavailable"
    try:
        row_idx = _find_event_subscriber_row(worksheet, platform, sender_id)
    except Exception as exc:
        logger.warning(
            "[SHEETS] events unsubscribe lookup failed sender=%s: %s",
            masked_sender, exc,
        )
        return False, "read_failed"
    if row_idx is None:
        return False, "not_subscribed"
    now_text = _datetime_text(now_tbilisi())
    try:
        worksheet.update_cell(
            row_idx, EVENT_SUBSCRIBER_COLUMN_INDEX["Status"], "unsubscribed",
        )
        worksheet.update_cell(
            row_idx, EVENT_SUBSCRIBER_COLUMN_INDEX["Updated At"], now_text,
        )
        worksheet.update_cell(
            row_idx, EVENT_SUBSCRIBER_COLUMN_INDEX["Unsubscribe At"], now_text,
        )
    except Exception as exc:
        logger.warning(
            "[SHEETS] events unsubscribe write failed sender=%s: %s",
            masked_sender, exc,
        )
        return False, "write_failed"
    logger.info(
        "[SHEETS] events unsubscribed sender=%s row=%s",
        masked_sender, row_idx,
    )
    return True, "ok"


def mark_event_subscriber_notified(
    platform: str, sender_id: str, event_id: str,
) -> tuple[bool, str]:
    """Append ``event_id`` to a subscriber's `Notified Event IDs` cell
    and stamp `Last Notified Event ID` + `Last Notified At`.

    Returns ``(True, "ok")`` on success. Returns ``(False, "duplicate")``
    when the event_id was already present (caller can skip a send).
    Returns ``(False, reason)`` on any other failure.
    """
    from app.services import sentry_service
    masked_sender = sentry_service.mask_sender(sender_id)
    eid = (str(event_id) or "").strip()
    if not eid:
        return False, "missing_event_id"
    try:
        worksheet = _event_subscribers_worksheet()
        row_idx = _find_event_subscriber_row(worksheet, platform, sender_id)
        if row_idx is None:
            return False, "not_subscribed"
        existing_values = worksheet.row_values(row_idx)
        existing_dict = _event_subscriber_row_to_dict(existing_values)
        notified = existing_dict["notified_event_ids"]
        if eid in notified:
            return False, "duplicate"
        notified.append(eid)
        now_text = _datetime_text(now_tbilisi())
        worksheet.update_cell(
            row_idx, EVENT_SUBSCRIBER_COLUMN_INDEX["Notified Event IDs"],
            _serialise_notified_ids(notified),
        )
        worksheet.update_cell(
            row_idx, EVENT_SUBSCRIBER_COLUMN_INDEX["Last Notified Event ID"],
            eid,
        )
        worksheet.update_cell(
            row_idx, EVENT_SUBSCRIBER_COLUMN_INDEX["Last Notified At"],
            now_text,
        )
        worksheet.update_cell(
            row_idx, EVENT_SUBSCRIBER_COLUMN_INDEX["Updated At"],
            now_text,
        )
        return True, "ok"
    except Exception as exc:
        logger.warning(
            "[SHEETS] events mark_notified failed sender=%s event=%s: %s",
            masked_sender, eid, exc,
        )
        return False, "write_failed"
