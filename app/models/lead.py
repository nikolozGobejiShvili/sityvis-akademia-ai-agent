from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any


def _parse_iso_or_now(value: Any) -> datetime:
    """Best-effort ISO-string → datetime, falling back to ``utcnow``."""
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            pass
    return datetime.utcnow()


@dataclass
class Lead:
    sender_id: str
    platform: str
    segment: str
    name: str = ""
    phone: str = ""
    child_age: str = ""
    challenge: str = ""
    deeper_concern: str = ""
    desired_change: str = ""
    event_interest: str = ""
    calendly_booked: bool = False
    # P2 — exact slot the user booked (ISO-8601 in Asia/Tbilisi). Used by
    # the post-booking composer to answer "ჩავეწერე?" / "როდის
    # დამიკავშირდებიან?" without re-querying Calendar. Empty until a
    # successful Calendar write. Not persisted to Sheets — kept on the
    # in-memory Lead only.
    booked_datetime_iso: str = ""
    # P3-C PATCH 1 — Google Calendar event ID returned from book_slot.
    # Required for safe cancel / reschedule via manage_consultation_booking.
    # Empty when no Calendar event exists yet, or when an older booking
    # predates this field. Cancel paths that find this empty MUST NOT
    # claim cancellation success — they hand off to the manager instead.
    calendar_event_id: str = ""
    conversation_summary: str = ""
    status: str = "New"
    followup_sent: bool = False
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_message_at: datetime = field(default_factory=datetime.utcnow)
    # ADULT LLM Engine — minimal lead fields for the cultural-events
    # flow. ``preferred_event`` is the event id (or title) the user said
    # they're interested in; ``seat_count`` is the number of seats they
    # asked about; ``reservation_status`` follows a CRM-style state
    # machine (New → Qualified → ManagerHandoff → ReservationRequested →
    # LinkSent → Lost). All empty by default so PARENT leads round-trip
    # unchanged through ``model_dump`` / ``from_dict``.
    preferred_event: str = ""
    seat_count: str = ""
    reservation_status: str = ""
    # ADULT Live QA Polish Patch (2026-06-02). The adult's OWN age is
    # kept in a dedicated field so the PARENT/camp flow can never read
    # it as ``child_age`` by accident and offer a children's camp to a
    # 30-year-old. CRITICAL INVARIANT enforced everywhere this field is
    # touched:
    #   * ``lead.child_age`` → ONLY for child/camp context (PARENT flow).
    #   * ``lead.adult_age`` → ONLY for adult/self context (ADULT flow).
    #   * NEVER cross-assign between the two.
    # The ADULT engine surfaces this field in its system-prompt context
    # so a second "რამდენი წლის ბრძანდებით?" never gets asked once the
    # user has disclosed their age. The PARENT→ADULT switch in
    # parent_tool_executor._switch_to_adult_flow transfers child_age
    # over ONLY when child_age is outside the camp range [9, 17] — at
    # that point it was misclassified and belongs in adult_age.
    adult_age: str = ""
    # ADULT Context Routing Fix (2026-06-02). When the user is asking
    # about an ADULT event for someone OTHER than themselves (sister,
    # brother, mother, friend, etc.), the relative's age belongs HERE
    # — never in `child_age` (which is camp-only) and never in
    # `adult_age` (which is self-only). The relation label is a free
    # string (e.g. "და", "ძმა", "მეგობარი") captured so manager
    # notifications and Sheets exports can read it; it is NOT used for
    # event-filtering logic.
    #   * `adult_target_relation` → free-form relation label.
    #   * `adult_target_age` → the relative's age, used by
    #     `_get_adult_events` event-filtering when set.
    # Eligibility resolution priority in `_get_adult_events`:
    #   LLM-passed `user_age` → `adult_target_age` → `adult_age`.
    # `child_age` is NEVER used as a fallback — preserving the strict
    # separation invariant.
    adult_target_relation: str = ""
    adult_target_age: str = ""

    def model_dump(self, mode: str | None = None) -> dict[str, Any]:
        data = asdict(self)
        if mode == "json":
            data["created_at"] = self.created_at.isoformat()
            data["last_message_at"] = self.last_message_at.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Lead":
        """Reconstruct a Lead from a ``model_dump(mode="json")`` payload.

        Symmetric with ``model_dump``. Defensive against missing keys so
        older serialised payloads (e.g. from a future Redis store) still
        load cleanly.
        """
        return cls(
            sender_id=str(data.get("sender_id", "")),
            platform=str(data.get("platform", "")),
            segment=str(data.get("segment", "")),
            name=str(data.get("name", "") or ""),
            phone=str(data.get("phone", "") or ""),
            child_age=str(data.get("child_age", "") or ""),
            challenge=str(data.get("challenge", "") or ""),
            deeper_concern=str(data.get("deeper_concern", "") or ""),
            desired_change=str(data.get("desired_change", "") or ""),
            event_interest=str(data.get("event_interest", "") or ""),
            calendly_booked=bool(data.get("calendly_booked", False)),
            booked_datetime_iso=str(data.get("booked_datetime_iso", "") or ""),
            calendar_event_id=str(data.get("calendar_event_id", "") or ""),
            conversation_summary=str(data.get("conversation_summary", "") or ""),
            status=str(data.get("status", "New") or "New"),
            followup_sent=bool(data.get("followup_sent", False)),
            created_at=_parse_iso_or_now(data.get("created_at")),
            last_message_at=_parse_iso_or_now(data.get("last_message_at")),
            preferred_event=str(data.get("preferred_event", "") or ""),
            seat_count=str(data.get("seat_count", "") or ""),
            reservation_status=str(data.get("reservation_status", "") or ""),
            adult_age=str(data.get("adult_age", "") or ""),
            adult_target_relation=str(data.get("adult_target_relation", "") or ""),
            adult_target_age=str(data.get("adult_target_age", "") or ""),
        )

    def to_sheet_row(self, reply: str) -> list[Any]:
        return [
            self.sender_id,
            self.platform,
            self.segment,
            self.name,
            self.phone,
            self.child_age,
            self.challenge,
            self.deeper_concern,
            self.desired_change,
            self.event_interest,
            self.calendly_booked,
            self.conversation_summary,
            self.status,
            self.created_at.isoformat(),
            self.last_message_at.isoformat(),
            self.followup_sent,
        ]
