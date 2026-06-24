"""ADULT LLM engine — backend tool executor.

Mirrors ``parent_tool_executor`` for the cultural-events flow. This is
the security boundary between the LLM (which decides what it wants to
do) and the real side-effects (Sheets writes + manager email +
manager-phone disclosure).

Invariants enforced here, NOT by the LLM:

  * ``request_adult_manager_callback`` requires a Georgian phone — the
    parser is reused from ``parent_flow._parse_name_phone`` for byte-
    identical behaviour.
  * Manager notification fires AT MOST ONCE per conversation. A repeat
    call returns ``already_notified=true``.
  * Adult flow NEVER books Google Calendar — there is no booking tool.
  * ``provide_adult_reservation_link`` never invents a link. Missing
    URL → structured ``reason=link_missing`` so the LLM falls back to
    manager handoff.
  * ``save_adult_lead_info`` only mutates the in-memory Lead — never
    writes Sheets, never notifies.
  * Manager phone is sourced from
    ``admin_config_service.get_manager_phone()`` — never hard-coded.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from app.agent.tools.adult_tools import (
    ALLOWED_ADULT_TOOL_NAMES,
    TOOL_GET_ADULT_EVENT_DETAILS,
    TOOL_GET_ADULT_EVENTS,
    TOOL_PROVIDE_ADULT_RESERVATION_LINK,
    TOOL_REQUEST_ADULT_MANAGER_CALLBACK,
    TOOL_SAVE_ADULT_LEAD_INFO,
    TOOL_SUBSCRIBE_TO_ADULT_EVENT_UPDATES,
    TOOL_SWITCH_TO_PARENT_FLOW,
)
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.services import sentry_service

logger = logging.getLogger(__name__)


# Per-conversation "manager notified for adult lead" flag. Distinct
# namespace from the parent guard so a user who switched flows can
# still trigger handoffs in both segments without collision.
adult_manager_notified_for_conversation: dict[str, bool] = {}


# Live QA Patch (2026-06-08): per-conversation "the operator-flagged
# sold_out state for an event was surfaced this turn" — the sanitiser
# uses this to decide whether the LLM is allowed to say
# „ადგილები ამოწურულია". Without the flag, sold-out claims are
# stripped (Bug 1 fix — agent invented sold-out copy).
adult_sold_out_disclosed_for_conversation: dict[str, bool] = {}


def mark_sold_out_disclosed(sender_id: str) -> None:
    """Allow the LLM to mention „ადგილები ამოწურულია" for this turn —
    called by the executor when an operator-flagged sold_out event
    appears in the tool result."""
    adult_sold_out_disclosed_for_conversation[sender_id] = True


def is_sold_out_disclosed(sender_id: str) -> bool:
    return adult_sold_out_disclosed_for_conversation.get(sender_id, False)


def clear_sold_out_disclosed(sender_id: str) -> None:
    adult_sold_out_disclosed_for_conversation.pop(sender_id, None)


# Live QA Patch (2026-06-08 — price hallucination): per-conversation
# "the operator-saved price for at least one event was surfaced this
# turn" flag. The sanitiser uses it to decide whether to strip the
# „ფასი მითითებული არ არის" / „დასწრების საფასური მითითებული არაა"
# fillers — those are valid ONLY when neither `price_text` nor
# `price_gel` was returned for any event surfaced this turn.
adult_price_disclosed_for_conversation: dict[str, bool] = {}


def mark_price_disclosed(sender_id: str) -> None:
    adult_price_disclosed_for_conversation[sender_id] = True


def is_price_disclosed(sender_id: str) -> bool:
    return adult_price_disclosed_for_conversation.get(sender_id, False)


def clear_price_disclosed(sender_id: str) -> None:
    adult_price_disclosed_for_conversation.pop(sender_id, None)


# Adult Subscription Confirmation Patch (2026-06-11): per-conversation
# "a subscription row was actually written this turn" flag. Set ONLY when
# `subscribe_to_adult_event_updates` returns success=True. The ADULT
# sanitiser uses it as a safety net: when the flag is NOT set, any
# „ჩაგწერეთ სიაში" / „დაგამატეთ სიაში" / „უკვე ხართ სიაში" success claim
# the LLM may have invented is stripped, so the agent never implies a
# subscription that was not persisted (Core rule — honest confirmation).
adult_subscription_confirmed_for_conversation: dict[str, bool] = {}


def mark_subscription_confirmed(sender_id: str) -> None:
    adult_subscription_confirmed_for_conversation[sender_id] = True


def is_subscription_confirmed(sender_id: str) -> bool:
    return adult_subscription_confirmed_for_conversation.get(sender_id, False)


def clear_subscription_confirmed(sender_id: str) -> None:
    adult_subscription_confirmed_for_conversation.pop(sender_id, None)


def _adult_manager_notified_redis_key(sender_id: str) -> str:
    return f"adult_manager_notified:{sender_id}"


def _is_adult_manager_notified(sender_id: str) -> bool:
    """In-memory dict first (fast path); Redis fallback for restart safety."""
    if adult_manager_notified_for_conversation.get(sender_id, False):
        return True
    try:
        from app.services import redis_state_service
        if redis_state_service.is_enabled() and redis_state_service.exists(
            _adult_manager_notified_redis_key(sender_id),
        ):
            adult_manager_notified_for_conversation[sender_id] = True
            return True
    except Exception as exc:
        logger.warning(
            "[redis] adult_manager_notified read failed for sender=%s: %s",
            sender_id, exc,
        )
    return False


def _mark_adult_manager_notified(sender_id: str) -> None:
    adult_manager_notified_for_conversation[sender_id] = True
    try:
        from app.services import redis_state_service
        if redis_state_service.is_enabled():
            redis_state_service.set_json(
                _adult_manager_notified_redis_key(sender_id),
                {"sender_id": sender_id, "notified": True},
            )
    except Exception as exc:
        logger.warning(
            "[redis] adult_manager_notified write failed for sender=%s: %s",
            sender_id, exc,
        )


def reset_state() -> None:
    """Clear the module-level dicts. Intended for tests."""
    adult_manager_notified_for_conversation.clear()
    adult_sold_out_disclosed_for_conversation.clear()
    adult_price_disclosed_for_conversation.clear()
    adult_subscription_confirmed_for_conversation.clear()


def _mask_phone(phone: str | None) -> str:
    """Return a phone string safe for logs (matches parent_tool_executor)."""
    if not phone:
        return ""
    digits = "".join(ch for ch in str(phone) if ch.isdigit())
    if len(digits) < 6:
        return "***"
    return f"{digits[:3]}***{digits[-3:]}"


@dataclass
class AdultToolExecutor:
    """Executes the closed-set of tools the ADULT LLM is allowed to call.

    One instance per inbound user message; mutates the live Lead and
    Conversation in place.
    """

    conversation: Conversation
    lead: Lead
    sender_id: str
    platform: str

    def execute(self, tool_name: str, tool_args: dict[str, Any]) -> dict[str, Any]:
        if tool_name not in ALLOWED_ADULT_TOOL_NAMES:
            logger.warning(
                "[adult_executor] Unknown tool requested: %r (args=%r)",
                tool_name, tool_args,
            )
            return {"success": False, "reason": "unknown_tool", "tool": tool_name}

        args = tool_args or {}
        try:
            if tool_name == TOOL_GET_ADULT_EVENTS:
                return self._get_adult_events(args)
            if tool_name == TOOL_GET_ADULT_EVENT_DETAILS:
                return self._get_adult_event_details(args)
            if tool_name == TOOL_SAVE_ADULT_LEAD_INFO:
                return self._save_adult_lead_info(args)
            if tool_name == TOOL_REQUEST_ADULT_MANAGER_CALLBACK:
                return self._request_adult_manager_callback(args)
            if tool_name == TOOL_PROVIDE_ADULT_RESERVATION_LINK:
                return self._provide_adult_reservation_link(args)
            if tool_name == TOOL_SWITCH_TO_PARENT_FLOW:
                return self._switch_to_parent_flow(args)
            if tool_name == TOOL_SUBSCRIBE_TO_ADULT_EVENT_UPDATES:
                return self._subscribe_to_adult_event_updates(args)
        except Exception as exc:  # pragma: no cover — defensive
            logger.exception(
                "[adult_executor] Tool %s raised: %s (args=%r)",
                tool_name, exc, args,
            )
            sentry_service.capture_exception(
                exc,
                context={
                    "area": "adult_tool_executor",
                    "tool": tool_name,
                },
            )
            return {"success": False, "reason": "tool_error", "tool": tool_name}

        return {"success": False, "reason": "unknown_tool", "tool": tool_name}

    # -- get_adult_events -------------------------------------------------

    def _get_adult_events(self, args: dict[str, Any]) -> dict[str, Any]:
        from app.services import admin_config_service

        user_age_raw = args.get("user_age")
        user_age: int | None = None
        if user_age_raw is not None:
            try:
                user_age = int(user_age_raw)
            except (TypeError, ValueError):
                user_age = None

        # ADULT Context Routing Fix (2026-06-02) — STRICT child_age
        # leakage guard. If the LLM passed a `user_age` that matches
        # the existing `lead.child_age` AND no adult/self age is on
        # record AND no relative target was confirmed, the LLM has
        # mistakenly carried the camp child's age over into ADULT
        # eligibility. Refuse the filter and let the LLM (or follow-up
        # rule) re-ask who the event is for.
        if user_age is not None:
            child_age_raw = (self.lead.child_age or "").strip()
            adult_age_raw = (self.lead.adult_age or "").strip()
            target_age_raw = (self.lead.adult_target_age or "").strip()
            relation_raw = (self.lead.adult_target_relation or "").strip().lower()
            child_is_target = relation_raw in {
                "child", "შვილი", "შვილის", "ბავშვი", "ბავშვის",
            }
            try:
                child_age_int = int(child_age_raw) if child_age_raw.isdigit() else None
            except ValueError:
                child_age_int = None
            if (
                child_age_int is not None
                and user_age == child_age_int
                and not adult_age_raw
                and not target_age_raw
                and not child_is_target
            ):
                logger.warning(
                    "[adult_executor] blocked child_age=%s leakage into adult "
                    "event eligibility (sender=%s)",
                    child_age_raw, self.sender_id,
                )
                user_age = None

        # ADULT Live QA Polish Patch — if the LLM omitted `user_age`,
        # fall back to the lead state in priority order:
        #   adult_target_age (relative the event is for) →
        #   adult_age (self)
        # NEVER fall back to `child_age` — that field belongs to the
        # PARENT/camp flow and never controls ADULT eligibility.
        if user_age is None:
            target_stored = (self.lead.adult_target_age or "").strip()
            if target_stored:
                try:
                    user_age = int(target_stored)
                except ValueError:
                    user_age = None
        if user_age is None:
            stored = (self.lead.adult_age or "").strip()
            if stored:
                try:
                    user_age = int(stored)
                except ValueError:
                    user_age = None

        try:
            events = admin_config_service.get_active_adult_events(user_age)
        except Exception as exc:
            logger.exception("[adult_executor] get_active_adult_events failed: %s", exc)
            return {
                "success": False,
                "reason": "events_load_error",
                "events": [],
            }

        if not events:
            return {
                "success": True,
                "events": [],
                "reason": "no_active_events",
                "user_age": user_age,
            }

        any_sold_out = False
        any_price = False
        compact: list[dict[str, Any]] = []
        for e in events:
            sold_out = bool(e.get("sold_out"))
            entry: dict[str, Any] = {
                "id": e["id"],
                "title": e["title"],
                "min_age": e["min_age"],
                "date_text": e["date_text"],
                "location": e["location"],
                "theme": e["theme"],
                "description": e.get("description", ""),
                "guest": e["guest"],
                "format": e["format"],
                "price_text": e["price_text"],
                "has_reservation_url": bool(e["reservation_url"]),
                "sold_out": sold_out,
            }
            # Live QA Patch (2026-06-08) — price hallucination: also
            # surface `price_gel` when the operator entered a value,
            # so the LLM has a fallback when `price_text` is blank but
            # `price_gel` was filled.
            price_gel = e.get("price_gel")
            if isinstance(price_gel, int) and price_gel > 0:
                entry["price_gel"] = price_gel
            # Live QA Patch (2026-06-08) — price hallucination flag.
            # Set when either `price_text` is non-blank OR `price_gel`
            # is positive — these are the two operator-driven sources
            # of truth for adult event price.
            if (e.get("price_text") or "").strip() or (
                isinstance(price_gel, int) and price_gel > 0
            ):
                any_price = True
            # Live QA Patch (2026-06-08) — Bug 1: omit `seats_available`
            # entirely when zero / unset. A bare `0` was being
            # interpreted by the LLM as „no seats left" → invented
            # „ადგილები ამოწურულია" copy. Surface the number ONLY when
            # the operator entered a positive value.
            seats = int(e.get("seats_available") or 0)
            if seats > 0:
                entry["seats_available"] = seats
            if sold_out:
                any_sold_out = True
            compact.append(entry)
        if any_sold_out:
            mark_sold_out_disclosed(self.sender_id)
        if any_price:
            mark_price_disclosed(self.sender_id)
        return {
            "success": True,
            "events": compact,
            "user_age": user_age,
        }

    # -- get_adult_event_details ------------------------------------------

    def _get_adult_event_details(self, args: dict[str, Any]) -> dict[str, Any]:
        from app.services import admin_config_service

        needle = (args.get("event_id_or_title") or "").strip()
        if not needle:
            return {"success": False, "reason": "missing_event_id"}

        # Live QA Patch (2026-06-08) — Bug 2: stem-aware multi-match
        # lookup so „ქართული პოეზია" finds „ქართული პოეზიის საღამო".
        # When > 1 candidate matches we return success=False with a
        # candidate list so the LLM can ask the user to disambiguate
        # instead of silently picking one.
        candidates = admin_config_service.find_adult_events_matching(needle)
        if not candidates:
            # The user may be asking about an event that exists but is
            # inactive — surface that distinct reason so the LLM can
            # respond with the "not currently active" wording instead
            # of the generic unknown-event miss.
            inactive_candidates = (
                admin_config_service.find_adult_events_matching(
                    needle, include_inactive=True,
                )
            )
            if inactive_candidates:
                return {
                    "success": False,
                    "reason": "event_inactive",
                    "requested": needle,
                    "matched_titles": [
                        c.get("title", "") for c in inactive_candidates
                    ],
                }
            return {
                "success": False,
                "reason": "unknown_event",
                "requested": needle,
            }
        if len(candidates) > 1:
            return {
                "success": False,
                "reason": "ambiguous_event",
                "requested": needle,
                "candidates": [
                    {"id": c["id"], "title": c.get("title", "")}
                    for c in candidates
                ],
            }

        event = candidates[0]

        # Adult Event Date Filter (2026-06-10): a user may name a PAST
        # event by title even though the future-only list never offered
        # it. Never surface its ticket link as bookable — return the
        # `event_past` reason so the LLM sends the ended-event message.
        try:
            if admin_config_service.is_adult_event_past(event):
                return {
                    "success": False,
                    "reason": "event_past",
                    "requested": needle,
                    "title": event.get("title", ""),
                }
        except Exception as exc:
            logger.warning(
                "[adult_executor] past-event check raised: %s", exc,
            )

        sold_out = bool(event.get("sold_out"))
        if sold_out:
            mark_sold_out_disclosed(self.sender_id)

        payload: dict[str, Any] = {
            "id": event["id"],
            "title": event["title"],
            "status": event["status"],
            "min_age": event["min_age"],
            "date_text": event["date_text"],
            "location": event["location"],
            "theme": event["theme"],
            "description": event.get("description", ""),
            "guest": event["guest"],
            "format": event["format"],
            "price_text": event["price_text"],
            "has_reservation_url": bool(event["reservation_url"]),
            "sold_out": sold_out,
        }
        # Live QA Patch (2026-06-08) — price hallucination: also
        # surface `price_gel` when present. The prompt instructs the
        # LLM to render numeric-only `price_text` as „<n> ლარი" and
        # to fall back to `price_gel` when `price_text` is blank.
        price_gel = event.get("price_gel")
        if isinstance(price_gel, int) and price_gel > 0:
            payload["price_gel"] = price_gel
        if (event.get("price_text") or "").strip() or (
            isinstance(price_gel, int) and price_gel > 0
        ):
            mark_price_disclosed(self.sender_id)
        # Live QA Patch (2026-06-08) — Bug 3: surface the actual
        # reservation URL alongside the boolean so the LLM can include
        # it in the same response when the user selects an event,
        # rather than forcing a second `provide_adult_reservation_link`
        # round-trip.
        reservation_url = (event.get("reservation_url") or "").strip()
        if reservation_url:
            payload["reservation_url"] = reservation_url
        payment_terms = (event.get("payment_terms") or "").strip()
        if payment_terms:
            payload["payment_terms"] = payment_terms
        # Surface `seats_available` ONLY when the operator entered a
        # positive number — see compact `_get_adult_events` rule.
        seats = int(event.get("seats_available") or 0)
        if seats > 0:
            payload["seats_available"] = seats

        return {
            "success": True,
            "event": payload,
        }

    # -- save_adult_lead_info ---------------------------------------------

    def _save_adult_lead_info(self, args: dict[str, Any]) -> dict[str, Any]:
        from app.flows import parent_flow

        saved: list[str] = []
        invalid: list[str] = []

        if "name" in args and (args.get("name") or "").strip():
            self.lead.name = args["name"].strip()
            saved.append("name")

        if "phone" in args and (args.get("phone") or "").strip():
            _parsed_name, parsed_phone = parent_flow._parse_name_phone(
                str(args["phone"]),
            )
            if parsed_phone:
                self.lead.phone = parsed_phone
                saved.append("phone")
            else:
                invalid.append("phone")

        if "adult_age" in args and str(args.get("adult_age") or "").strip():
            raw = str(args["adult_age"]).strip()
            # Only store if it parses as 0–120. Conservative — refuse
            # nonsense values rather than persisting them. The
            # CRITICAL invariant: NEVER write to lead.child_age from
            # this branch. Adult age belongs in adult_age only.
            digits = ""
            for ch in raw:
                if ch.isdigit():
                    digits += ch
                elif digits:
                    break
            if digits:
                try:
                    age_int = int(digits)
                except ValueError:
                    age_int = -1
                if 0 <= age_int <= 120:
                    self.lead.adult_age = str(age_int)
                    saved.append("adult_age")
                else:
                    invalid.append("adult_age")
            else:
                invalid.append("adult_age")

        if "adult_target_relation" in args and (
            args.get("adult_target_relation") or ""
        ).strip():
            # Free-form label captured verbatim for manager / CRM context.
            # Trim to a sane length so a bug in the LLM can't blow up
            # Sheets cell sizes.
            self.lead.adult_target_relation = args["adult_target_relation"].strip()[:80]
            saved.append("adult_target_relation")

        if "adult_target_age" in args and str(args.get("adult_target_age") or "").strip():
            raw = str(args["adult_target_age"]).strip()
            # Re-use the same conservative 0–120 validator as adult_age.
            # CRITICAL invariant: NEVER writes to lead.child_age from
            # this branch. Relative's age belongs in adult_target_age.
            digits = ""
            for ch in raw:
                if ch.isdigit():
                    digits += ch
                elif digits:
                    break
            if digits:
                try:
                    age_int = int(digits)
                except ValueError:
                    age_int = -1
                if 0 <= age_int <= 120:
                    self.lead.adult_target_age = str(age_int)
                    saved.append("adult_target_age")
                else:
                    invalid.append("adult_target_age")
            else:
                invalid.append("adult_target_age")

        if "event_interest" in args and (args.get("event_interest") or "").strip():
            new_interest = args["event_interest"].strip()
            existing = (self.lead.event_interest or "").strip()
            # Preserve richer field — same logic as parent challenge merge.
            if not existing or new_interest.lower() not in existing.lower():
                if existing and existing.lower() not in new_interest.lower():
                    merged = f"{existing}; {new_interest}"
                    self.lead.event_interest = merged[:300]
                else:
                    self.lead.event_interest = new_interest
                saved.append("event_interest")

        if "preferred_event" in args and (args.get("preferred_event") or "").strip():
            self.lead.preferred_event = args["preferred_event"].strip()
            saved.append("preferred_event")

        if "seat_count" in args and str(args.get("seat_count") or "").strip():
            self.lead.seat_count = str(args["seat_count"]).strip()
            saved.append("seat_count")

        if "notes" in args and (args.get("notes") or "").strip():
            note = args["notes"].strip()
            existing = (self.lead.conversation_summary or "").strip()
            self.lead.conversation_summary = (
                f"{existing}\n{note}".strip() if existing else note
            )
            saved.append("notes")

        # Make sure segment stays ADULT for downstream code.
        self.lead.segment = "ADULT"
        if self.lead.status == "New":
            self.lead.status = "Qualified"

        result: dict[str, Any] = {"success": True, "saved_fields": saved}
        if invalid:
            result["invalid_fields"] = invalid
        return result

    # -- request_adult_manager_callback -----------------------------------

    def _request_adult_manager_callback(self, args: dict[str, Any]) -> dict[str, Any]:
        from app.flows import parent_flow
        from app.services import (
            admin_config_service,
            notification_service,
            sheets_service,
        )

        name = (args.get("name") or "").strip()
        phone_raw = (args.get("phone") or "").strip()
        event_interest = (args.get("event_interest") or "").strip()
        notes = (args.get("notes") or "").strip()

        if name and not self.lead.name:
            self.lead.name = name

        phone_for_validation = phone_raw or (self.lead.phone or "")
        if phone_for_validation:
            _parsed_name, parsed_phone = parent_flow._parse_name_phone(
                phone_for_validation,
            )
            if parsed_phone:
                self.lead.phone = parsed_phone

        if not (self.lead.phone or "").strip():
            return {"success": False, "reason": "missing_phone"}

        # Manager phone for the user-facing reply — sourced from
        # admin_config / settings / company.yaml. Never hard-coded.
        manager_phone = admin_config_service.get_manager_phone() or ""

        # Already notified this conversation? Don't double-fire.
        if _is_adult_manager_notified(self.sender_id):
            return {
                "success": True,
                "manager_notified": False,
                "manager_phone": manager_phone,
                "reason": "already_notified",
            }

        # Capture event interest if the LLM passed one.
        if event_interest:
            existing = (self.lead.event_interest or "").strip()
            if event_interest.lower() not in existing.lower():
                self.lead.event_interest = (
                    f"{existing}; {event_interest}"[:300]
                    if existing
                    else event_interest
                )

        # Notes → append to summary.
        if notes:
            existing_summary = (self.lead.conversation_summary or "").strip()
            self.lead.conversation_summary = (
                f"{existing_summary}\n{notes}".strip()
                if existing_summary
                else notes
            )

        self.lead.segment = "ADULT"
        if self.lead.status not in {"Booked", "ManagerHandoff"}:
            self.lead.status = "Qualified"
        self.lead.reservation_status = "ManagerHandoff"

        logger.info(
            "[adult_executor] manager handoff sender=%s phone=%s "
            "event_interest=%r",
            self.sender_id, _mask_phone(self.lead.phone),
            (self.lead.event_interest or "")[:60],
        )

        try:
            sheets_service.create_lead(self.lead)
        except Exception as exc:
            logger.exception(
                "[adult_executor] sheets_service.create_lead raised: %s", exc,
            )

        try:
            notification_service.send_manager_notification(
                self.lead, self.lead.conversation_summary or "",
            )
        except Exception as exc:
            logger.exception(
                "[adult_executor] send_manager_notification raised: %s", exc,
            )

        _mark_adult_manager_notified(self.sender_id)

        return {
            "success": True,
            "manager_notified": True,
            "manager_phone": manager_phone,
        }

    # -- provide_adult_reservation_link -----------------------------------

    def _provide_adult_reservation_link(self, args: dict[str, Any]) -> dict[str, Any]:
        from app.services import admin_config_service

        event_id = (args.get("event_id") or "").strip()
        if not event_id:
            return {"success": False, "reason": "missing_event_id"}

        event = admin_config_service.find_adult_event(event_id)
        if not event:
            return {
                "success": False,
                "reason": "unknown_event",
                "event_id": event_id,
            }

        url = (event.get("reservation_url") or "").strip()
        if not url:
            return {
                "success": False,
                "reason": "link_missing",
                "event_id": event["id"],
                "event_title": event["title"],
            }

        # Remember the chosen event on the lead.
        self.lead.preferred_event = event["id"]
        self.lead.reservation_status = "LinkSent"

        return {
            "success": True,
            "event_id": event["id"],
            "event_title": event["title"],
            "reservation_url": url,
        }

    # -- switch_to_parent_flow --------------------------------------------

    def _switch_to_parent_flow(self, args: dict[str, Any]) -> dict[str, Any]:
        """Flip the conversation segment so the next inbound message
        routes to ``parent_flow.handle``.

        Soft handoff. We do NOT clear the lead, do NOT cancel any
        pending adult action. The user can come back and the data is
        preserved.
        """
        self.conversation.segment = "PARENT"
        self.conversation.state = "START"
        return {
            "success": True,
            "segment": "PARENT",
            "reason": (args.get("reason") or "").strip() or "camp_interest",
        }

    # -- subscribe_to_adult_event_updates ---------------------------------

    def _subscribe_to_adult_event_updates(
        self, args: dict[str, Any],
    ) -> dict[str, Any]:
        """Persist the operator-consented subscriber to the Sheets
        `events` tab via `adult_subscription_service.subscribe`.

        The LLM is expected to call this ONLY after explicit consent.
        Backend enforces name + phone presence — without them the tool
        returns a structured reason so the LLM can ask for the missing
        data without claiming subscribed status.

        Side-effects:
          * On success: also updates `lead.name` and `lead.phone` so
            other parts of the conversation pick up the freshly-collected
            data.
          * Sets a conversation-level marker so the LLM doesn't ask the
            consent question again in the same conversation.
        """
        from app.services import adult_subscription_service

        # Prefer the LLM-passed args, fall back to lead state for
        # values already on hand. This lets the LLM call the tool
        # right after the user says "კი" without having to re-supply
        # name / phone the user provided earlier.
        name = (args.get("name") or self.lead.name or "").strip()
        phone = (args.get("phone") or self.lead.phone or "").strip()
        source_event_id = (args.get("source_event_id") or "").strip()
        source_event_title = (args.get("source_event_title") or "").strip()
        source_event_link = (args.get("source_event_link") or "").strip()
        age = (args.get("age") or self.lead.adult_age or "").strip()

        # If the LLM omitted source-event context, recover it from the
        # lead's preferred_event field when populated.
        if not source_event_id and self.lead.preferred_event:
            source_event_id = self.lead.preferred_event

        result = adult_subscription_service.subscribe(
            platform=self.platform,
            sender_id=self.sender_id,
            name=name,
            phone=phone,
            source_event_id=source_event_id,
            source_event_title=source_event_title,
            source_event_link=source_event_link,
            age=age,
        )

        if result.get("success"):
            # Mirror the collected data onto the Lead so downstream
            # turns don't re-ask.
            if name and not (self.lead.name or "").strip():
                self.lead.name = name
            if phone and not (self.lead.phone or "").strip():
                self.lead.phone = phone
            # Conversation-level marker so the LLM won't re-ask the
            # consent question.
            try:
                self.conversation.adult_subscription_status = "subscribed"
            except Exception:
                # Conversation dataclass may not expose the attribute
                # on older snapshots; ignore — Sheets is source of truth.
                pass
            # Per-turn flag so the sanitiser allows the genuine
            # „ჩაგწერეთ სიაში" / „დაგამატეთ სიაში" success copy through.
            mark_subscription_confirmed(self.sender_id)
            logger.info(
                "[adult_executor] subscribed sender=%s event=%s",
                self.sender_id, source_event_id or "(none)",
            )
        return result


def serialize_result(result: dict[str, Any]) -> str:
    """JSON-dump with ensure_ascii=False so Georgian text round-trips."""
    return json.dumps(result, ensure_ascii=False)
