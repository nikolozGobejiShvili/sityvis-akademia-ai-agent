import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.lead import Lead

logger = logging.getLogger(__name__)

# Keys the CURRENT Conversation snapshot writes. Used only to detect a
# stale (older-structure) Redis payload for a privacy-safe log line —
# every field already defaults safely via ``.get`` in ``from_dict``, so
# this is diagnostics only, never a migration step.
_CURRENT_SNAPSHOT_KEYS: frozenset[str] = frozenset({
    "sender_id", "platform", "segment", "state", "history", "lead",
    "created_at", "last_activity", "pending_booking", "last_bot_message_at",
    "followup_stage", "followup_blocked_reason", "last_meaningful_interest",
    "stopped_after", "adult_subscription_status",
})


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
class Conversation:
    sender_id: str
    platform: str
    segment: str = ""
    state: str = "START"
    history: list[dict[str, str]] = field(default_factory=list)
    lead: Lead | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_activity: datetime = field(default_factory=datetime.utcnow)
    # Phase 4 — pending booking continuation. Stores the user's requested
    # date/time + which contact fields are still missing while we wait for
    # them to send the missing piece. Must remain fully JSON-serializable
    # (only str / int / float / bool / list / dict / None inside) so the
    # whole Conversation can be persisted to Redis on a future task.
    # Datetimes here MUST be ISO strings.
    pending_booking: dict[str, Any] | None = None
    # P3-C PATCH 3 — follow-up readiness markers. These are *data only*
    # for a future scheduler (P3-B Redis + APScheduler); no message is
    # actually sent from inside Conversation. All strings, ISO datetimes
    # only, so the whole record stays Redis-JSON safe.
    #
    # `last_user_message_at` is intentionally NOT a new field: the
    # existing `last_activity` already records when the user wrote last
    # (set by `conversation_service.process_message`). Reusing it avoids
    # the dual-source-of-truth bug.
    #
    # `last_bot_message_at` — ISO string; when we last sent an outbound
    # message. Used by the scheduler to know which side spoke last.
    last_bot_message_at: str = ""
    # `followup_stage` — the cadence bucket the scheduler should consider
    # next: "", "first_24h", "second_3d", "third_7d", or "stopped".
    # Stage values match keys in app/agent/knowledge/followup_strategy.yaml.
    followup_stage: str = ""
    # `followup_blocked_reason` — one of the values in
    # `followup_strategy.global_rules.do_not_follow_up_if`:
    # "", "booked", "registered", "declined", "asked_no_more_messages",
    # "manager_handoff_completed".
    followup_blocked_reason: str = ""
    # `last_meaningful_interest` — short tag for what the user last
    # showed interest in (e.g. "conditions", "price", "dates",
    # "registration", "consultation", "manager"). Used by the scheduler
    # to pick the scenario-specific message template.
    last_meaningful_interest: str = ""
    # `stopped_after` — short tag for the LAST piece of information the
    # user shared before going silent: "price", "age", "name", "phone",
    # "will_think", "". Maps directly to
    # `followup_strategy.scenario_followups.<key>` for nuanced cadence.
    stopped_after: str = ""
    # Adult Event Subscription Patch (2026-06-08): in-session marker so
    # the LLM doesn't re-ask the consent question after a confirmed
    # subscribe / decline. Values: "" (not asked), "asked" (consent
    # question shown), "subscribed", "declined", "unsubscribed".
    # The Sheets `events` tab is the source of truth across sessions;
    # this field exists purely to avoid noisy re-asks within ONE
    # conversation turn.
    adult_subscription_status: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe dict representation.

        Datetimes become ISO strings. Nested ``Lead`` uses its own
        ``model_dump(mode="json")``. ``pending_booking`` is passed through
        unchanged — it is the caller's responsibility to keep it JSON-safe
        (see field comment).
        """
        return {
            "sender_id": self.sender_id,
            "platform": self.platform,
            "segment": self.segment,
            "state": self.state,
            "history": list(self.history),
            "lead": self.lead.model_dump(mode="json") if self.lead else None,
            "created_at": self.created_at.isoformat(),
            "last_activity": self.last_activity.isoformat(),
            "pending_booking": self.pending_booking,
            # P3-C PATCH 3 follow-up readiness markers.
            "last_bot_message_at": self.last_bot_message_at,
            "followup_stage": self.followup_stage,
            "followup_blocked_reason": self.followup_blocked_reason,
            "last_meaningful_interest": self.last_meaningful_interest,
            "stopped_after": self.stopped_after,
            "adult_subscription_status": self.adult_subscription_status,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Conversation":
        """Reconstruct a Conversation from a ``to_dict`` payload.

        Symmetric with ``to_dict``. Missing keys fall back to dataclass
        defaults so older serialised payloads (e.g. from a Redis store
        written before this field existed) still load cleanly.
        """
        # FIX 4 (2026-06-11) — state versioning guard. Every field below
        # defaults safely via ``.get`` so an older/incompatible Redis
        # payload never crashes; surface a privacy-safe one-liner when a
        # stale-format snapshot (missing current keys) is loaded so the
        # operator can see it in logs. No PII (no values, no ids logged).
        missing_keys = _CURRENT_SNAPSHOT_KEYS - set(data.keys())
        if missing_keys:
            logger.info(
                "[conversation] loaded stale-format snapshot — %d missing "
                "field(s) defaulted: %s",
                len(missing_keys), sorted(missing_keys),
            )

        lead_payload = data.get("lead")
        lead = Lead.from_dict(lead_payload) if lead_payload else None
        return cls(
            sender_id=data["sender_id"],
            platform=data["platform"],
            segment=data.get("segment", ""),
            state=data.get("state", "START"),
            history=list(data.get("history", [])),
            lead=lead,
            created_at=_parse_iso_or_now(data.get("created_at")),
            last_activity=_parse_iso_or_now(data.get("last_activity")),
            pending_booking=data.get("pending_booking"),
            last_bot_message_at=str(data.get("last_bot_message_at", "") or ""),
            followup_stage=str(data.get("followup_stage", "") or ""),
            followup_blocked_reason=str(data.get("followup_blocked_reason", "") or ""),
            last_meaningful_interest=str(data.get("last_meaningful_interest", "") or ""),
            stopped_after=str(data.get("stopped_after", "") or ""),
            adult_subscription_status=str(data.get("adult_subscription_status", "") or ""),
        )


class IncomingMessage(BaseModel):
    model_config = ConfigDict(extra="allow", arbitrary_types_allowed=True)

    sender_id: str | None = None
    message: str
    channel: str | None = None
    audience: str | None = None
    lead: Lead | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ConversationResponse(BaseModel):
    reply: str
    audience: str
    followup: str | None = None
    calendar_event_id: str | None = None
