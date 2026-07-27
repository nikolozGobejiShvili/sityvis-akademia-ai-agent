"""P3-C SAFE — backend tool executor for the PARENT LLM engine.

The executor is the security boundary between the LLM (which decides what
it WANTS to do) and the real side-effects (Google Calendar / Google
Sheets / manager notifications). Every dangerous action is validated
here BEFORE it is performed; the LLM can read the structured failure
reason and ask the parent for the missing piece.

Invariants enforced here, NOT by the LLM:

  * Booking requires name + phone + datetime + child_age. Missing any
    one returns ``missing_*`` and does NOT touch Calendar.
  * Child age must fall in ``[camp.age_min, camp.age_max]`` from
    ``camp_2026.yaml``. Out-of-range returns ``age_not_eligible``.
  * Phone must parse as a Georgian number via the existing flow parser
    (9 local digits, prefix in {5, 7, 8}).
  * Datetime must parse as ISO-8601, be in the future (with the
    Calendar buffer applied via ``check_slot_available``), and fall
    inside business hours.
  * The slot must still be free at the moment of booking — race
    conditions return ``slot_unavailable`` with alternatives.
  * Manager notification only fires when a valid phone is on the lead.
  * ``save_lead_info`` never writes to Sheets, never books, never
    notifies — it only mutates the in-memory Lead.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from app.agent.services.knowledge_loader import load_knowledge
from app.agent.services.timestamps import (
    apply_colloquial_time_to_iso,
    now_tbilisi,
    resolve_relative_datetime,
)
from app.domain.decision.models import ProgramId, reserved_program_ids
from app.agent.tools.parent_tools import (
    ALLOWED_TOOL_NAMES,
    CAMP_INFO_TOPICS,
    TOOL_BOOK_CONSULTATION,
    TOOL_CHECK_CONSULTATION_SLOT,
    TOOL_GET_APPROVED_ANSWER,
    TOOL_GET_AVAILABLE_SLOTS,
    TOOL_GET_CAMP_INFO,
    TOOL_GET_PROGRAM_INFO,
    TOOL_GET_PROGRAM_TOPIC,
    TOOL_LIST_PROGRAMS,
    TOOL_MANAGE_CONSULTATION_BOOKING,
    TOOL_REQUEST_MANAGER_CALLBACK,
    TOOL_SAVE_LEAD_INFO,
    TOOL_SWITCH_TO_ADULT_FLOW,
)
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.services import sentry_service
from app.services.session_key_service import conversation_cache_key

logger = logging.getLogger(__name__)


# Per-conversation "manager notified this turn already" flag so the LLM
# can't double-notify by emitting the tool twice. P3-B mirrors this to
# Redis so a server restart cannot accidentally re-fire the manager
# notification when the user sends a post-booking "მადლობა".
manager_notified_for_conversation: dict[str, bool] = {}


def _manager_notified_redis_key(cache_key: str) -> str:
    return f"manager_notified:{cache_key}"


def _is_manager_notified(
    cache_key: str, legacy_sender_id: str | None = None,
) -> bool:
    """In-memory dict first; Redis fallback with legacy sender migration."""
    if manager_notified_for_conversation.get(cache_key, False):
        return True
    try:
        from app.services import redis_state_service
        if not redis_state_service.is_enabled():
            return False

        canonical_redis_key = _manager_notified_redis_key(cache_key)
        if redis_state_service.exists(canonical_redis_key):
            manager_notified_for_conversation[cache_key] = True
            return True

        legacy_sender = str(legacy_sender_id or "").strip()
        if legacy_sender and legacy_sender != cache_key:
            legacy_redis_key = _manager_notified_redis_key(legacy_sender)
            if redis_state_service.exists(legacy_redis_key):
                _mark_manager_notified(cache_key, legacy_sender_id=legacy_sender)
                return True
    except Exception as exc:
        logger.warning(
            "[redis] manager_notified read failed for cache_key=%s: %s",
            cache_key, exc,
        )
    return False


def _mark_manager_notified(
    cache_key: str, legacy_sender_id: str | None = None,
) -> None:
    """Write the duplicate-notification guard in both stores."""
    manager_notified_for_conversation[cache_key] = True
    try:
        from app.services import redis_state_service
        if redis_state_service.is_enabled():
            payload = {
                "sender_id": legacy_sender_id or cache_key,
                "session_key": cache_key,
                "notified": True,
            }
            # Per-session guard: expire on the same rolling window as the
            # conversation (8-day default). Positional TTL for mock-compat.
            redis_state_service.set_json(
                _manager_notified_redis_key(cache_key),
                payload,
                redis_state_service.conversation_ttl_seconds(),
            )
    except Exception as exc:
        logger.warning(
            "[redis] manager_notified write failed for cache_key=%s: %s",
            cache_key, exc,
        )


# A cache of the most recent get_available_slots payload per sender, so
# book_consultation can offer alternatives if a slot races a Calendar
# write.
_last_slots_by_sender: dict[str, list[dict[str, Any]]] = {}


# P3-C PATCH 5 — "did `book_consultation` succeed this turn?" signal.
# Set inside `_book_consultation` and read by the engine + the final
# booking-confirmation guard so a hallucinated "ჩავნიშნე"/"ჩანიშნულია"
# response without a matching tool success is rejected. Reset between
# turns by the engine before each `run_parent_llm_turn`.
book_consultation_success_for_conversation: dict[str, bool] = {}


def _mask_phone(phone: str | None) -> str:
    """Return a phone string safe for logs: first3 + *** + last3.

    Empty input returns empty string. Anything shorter than 6 digits is
    masked entirely. Used by every booking log line so we never emit a
    full Georgian mobile number to disk."""
    if not phone:
        return ""
    digits = "".join(ch for ch in str(phone) if ch.isdigit())
    if len(digits) < 6:
        return "***"
    return f"{digits[:3]}***{digits[-3:]}"


# -- public API ------------------------------------------------------------


def _trace_parent_tool_result(
    tool_name: str, result: dict[str, Any],
) -> dict[str, Any]:
    try:
        from app.reasoning import conversation_trace as _trace

        safe_tool_name = (
            tool_name if tool_name in ALLOWED_TOOL_NAMES else "unknown_tool"
        )
        fields: dict[str, Any] = {
            "route_owner": "parent_tool_executor",
            "domain": "camp",
            "sub_intent": safe_tool_name,
            "answer_source": "tool_result",
            "used_tool": True,
        }
        if bool(
            result.get("manager_notified")
            or result.get("manager_handoff_required")
        ):
            fields["handoff_requested"] = True
        _trace.set_route_decision(**fields)
    except Exception:  # pragma: no cover - trace must never affect tools
        pass
    return result

def _is_camp_registration_open() -> bool:
    try:
        from app.services import admin_config_service
        return admin_config_service.is_camp_registration_open()
    except Exception:  # pragma: no cover - registration actions fail closed
        logger.exception("[parent_executor] camp registration gate failed")
        return False


def _registration_closed_tool_result(**extra: Any) -> dict[str, Any]:
    return {"success": False, "reason": "camp_registration_closed", **extra}


def _camp_public_info_limited_tool_result(topic: str) -> dict[str, Any]:
    try:
        from app.flows import parent_flow

        message = parent_flow._camp_registration_closed_answer()
    except Exception:  # pragma: no cover - defensive structured fallback
        logger.exception("[parent_executor] closed camp policy message failed")
        message = ""
    return {
        "success": False,
        "reason": "camp_public_info_limited",
        "topic": topic,
        "message": message,
    }

@dataclass
class ParentToolExecutor:
    """Executes the closed-set of tools the PARENT LLM is allowed to call.

    One instance per inbound user message — passing the conversation and
    the lead in lets the executor mutate them where appropriate (lead
    fields, ``conversation.state`` on a successful booking) without
    needing global state.

    Booking Date Parse Patch (2026-06-04): ``user_message`` is the raw
    text of the current inbound turn. The slot-check and book paths use
    it to re-resolve Georgian relative-date phrases ("ხვალ" / "ზეგ" /
    "დღეს") when the LLM passes a stale or wrong-year ISO. Optional —
    defaults to ``""`` so legacy callers keep working.
    """

    conversation: Conversation
    lead: Lead
    sender_id: str
    platform: str
    user_message: str = ""

    @property
    def cache_key(self) -> str:
        return conversation_cache_key(
            self.conversation, platform=self.platform, sender_id=self.sender_id,
        )

    def _normalise_datetime_iso_from_message(self, datetime_iso: str) -> str:
        """Booking Date Parse Patch (2026-06-04).

        If ``self.user_message`` contains a Georgian relative-date phrase
        (ხვალ / ზეგ / დღეს / გუშინ / დღევანდელ / ხვალინდელ) AND the LLM
        passed a ``datetime_iso`` whose calendar date does NOT match the
        date the user actually named, override with the resolved date.

        Why: the LLM has no built-in concept of "today" in Tbilisi and
        occasionally encodes "ხვალ" as last week's date — pushing it
        into ``past_datetime`` rejection. The user gave us the relative
        word; if the LLM kept the time portion but used the wrong day,
        keep the user's time and replace the day with the resolved one.

        Returns the (possibly updated) ISO string. Safe no-op when the
        message has no relative-date stem, the LLM passed nothing, or
        the LLM's date already matches the resolved date.

        Georgian Colloquial Time Patch (2026-06-10): after the relative-
        date day override, a SECOND deterministic pass normalises the
        colloquial hour from the user message (e.g. „8 საათზე" / „8 სათზე"
        → 20:00 in PARENT booking context), so the hour no longer depends
        on the stochastic LLM. This pass runs even when the message has
        no relative-date word — covering plain „12 ივნის 8 სათზე" inputs.
        """
        if not datetime_iso:
            return datetime_iso
        if not self.user_message:
            return datetime_iso

        iso = datetime_iso

        # 1. Relative-date DAY override (existing behaviour).
        try:
            resolved = resolve_relative_datetime(self.user_message)
        except Exception:
            resolved = None
        if resolved is not None:
            llm_parsed = _parse_iso_datetime(iso)
            if llm_parsed is None:
                iso = resolved.isoformat()
            elif llm_parsed.date() != resolved.date():
                # Override day only — preserve the LLM's HH:MM here; the
                # colloquial-hour pass below corrects the time when the
                # user actually named one.
                try:
                    combined = datetime.combine(
                        resolved.date(), llm_parsed.time(), tzinfo=resolved.tzinfo,
                    )
                    logger.info(
                        "[parent_executor] relative-date override: llm=%s "
                        "resolved=%s final=%s message_head=%r",
                        llm_parsed.isoformat(), resolved.isoformat(),
                        combined.isoformat(), (self.user_message or "")[:60],
                    )
                    iso = combined.isoformat()
                except Exception:
                    iso = resolved.isoformat()

        # 2. Colloquial-hour HOUR override (PM heuristic + typo variants).
        # Deterministic single source of truth for „N საათზე/სათზე/-ზე"
        # so the same input maps to the same hour across all users /
        # states. Explicit HH:MM and explicit „დილ…"(morning) are honoured
        # literally inside `apply_colloquial_time_to_iso`.
        try:
            normalised = apply_colloquial_time_to_iso(iso, self.user_message)
            if normalised != iso:
                logger.info(
                    "[parent_executor] colloquial-hour override: %s -> %s "
                    "message_head=%r",
                    iso, normalised, (self.user_message or "")[:60],
                )
            iso = normalised
        except Exception:
            pass

        return iso

    def execute(self, tool_name: str, tool_args: dict[str, Any]) -> dict[str, Any]:
        """Run a tool by name and return a JSON-safe result dict.

        Never raises. Unknown tools and unexpected exceptions are caught
        and reported as ``success=false`` so the LLM loop stays alive.
        """
        if tool_name not in ALLOWED_TOOL_NAMES:
            logger.warning(
                "[parent_executor] Unknown tool requested: %r (args=%r)",
                tool_name, tool_args,
            )
            return _trace_parent_tool_result(
                tool_name,
                {"success": False, "reason": "unknown_tool", "tool": tool_name},
            )

        args = tool_args or {}
        try:
            if tool_name == TOOL_GET_CAMP_INFO:
                result = self._get_camp_info(args)
            elif tool_name == TOOL_GET_AVAILABLE_SLOTS:
                result = self._get_available_slots(args)
            elif tool_name == TOOL_BOOK_CONSULTATION:
                result = self._book_consultation(args)
            elif tool_name == TOOL_REQUEST_MANAGER_CALLBACK:
                result = self._request_manager_callback(args)
            elif tool_name == TOOL_SAVE_LEAD_INFO:
                result = self._save_lead_info(args)
            elif tool_name == TOOL_MANAGE_CONSULTATION_BOOKING:
                result = self._manage_consultation_booking(args)
            elif tool_name == TOOL_SWITCH_TO_ADULT_FLOW:
                result = self._switch_to_adult_flow(args)
            elif tool_name == TOOL_CHECK_CONSULTATION_SLOT:
                result = self._check_consultation_slot(args)
            elif tool_name == TOOL_LIST_PROGRAMS:
                result = self._list_programs(args)
            elif tool_name == TOOL_GET_PROGRAM_INFO:
                result = self._get_program_info(args)
            elif tool_name == TOOL_GET_APPROVED_ANSWER:
                result = self._get_approved_answer(args)
            elif tool_name == TOOL_GET_PROGRAM_TOPIC:
                result = self._get_program_topic(args)
            else:
                result = {
                    "success": False,
                    "reason": "unknown_tool",
                    "tool": tool_name,
                }
            return _trace_parent_tool_result(tool_name, result)
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception(
                "[parent_executor] Tool %s raised: %s (args=%r)",
                tool_name, exc, args,
            )
            # Sentry capture: TOOL name + safe area label only. The
            # tool args may contain phone / name / datetime, all of
            # which are intentionally NOT forwarded to Sentry.
            sentry_service.capture_exception(
                exc,
                context={
                    "area": "parent_tool_executor",
                    "tool": tool_name,
                },
            )
            return _trace_parent_tool_result(
                tool_name,
                {"success": False, "reason": "tool_error", "tool": tool_name},
            )

        return _trace_parent_tool_result(
            tool_name,
            {"success": False, "reason": "unknown_tool", "tool": tool_name},
        )
    # -- list_programs / get_program_info (P4-1 Task 3) --------------------

    _REGISTRATION_OPEN_VALUES = frozenset({
        "open", "active", "enabled", "on", "true", "1", "yes",
    })
    # Customer-safe fields the generic tool may surface. Allowlist ⇒ a new
    # operator field never leaks by default.
    _PROGRAM_PUBLIC_FIELDS: tuple[str, ...] = (
        "name", "type", "location", "price_text", "price_gel", "payment_terms",
        "price_monthly", "price_onetime",
        "age_min", "age_max", "description_short", "description_full",
        "schedule_text", "duration_text", "streams", "included_items", "discounts",
    )
    # The 3 hardcoded programs have curated tools/handlers — the generic
    # get_program_info tool must refuse them (gate 3).
    _HARDCODED_PROGRAM_IDS = frozenset(p.value for p in ProgramId)

    def _list_programs(self, args: dict[str, Any]) -> dict[str, Any]:
        from app.services import admin_config_service
        try:
            sections = admin_config_service.get_active_sections()
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("[parent_executor] list_programs failed: %s", exc)
            return {"success": False, "reason": "config_error"}
        programs = [
            {"program_id": s.get("id"), "name": s.get("name"), "type": s.get("type")}
            for s in sections if s.get("id")
        ]
        logger.info("[parent_tool] list_programs count=%d", len(programs))
        return {"success": True, "programs": programs}

    def _get_program_info(self, args: dict[str, Any]) -> dict[str, Any]:
        program_id = str(args.get("program_id") or "").strip()
        if not program_id:
            return {"success": False, "reason": "missing_program_id"}
        if program_id in reserved_program_ids():
            return {"success": False, "reason": "use_specific_tool",
                    "program_id": program_id}
        from app.services import admin_config_service
        try:
            section = admin_config_service.get_section(program_id)
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("[parent_executor] get_program_info failed: %s", exc)
            return {"success": False, "reason": "config_error"}
        if not isinstance(section, dict):
            return {"success": False, "reason": "unknown_program"}
        status = (section.get("status") or "").strip().lower()
        if status != "active":
            return {"success": False, "reason": "program_not_active", "status": status}
        reg_status = str(section.get("registration_status") or "open").strip().lower()
        reg_open = reg_status in self._REGISTRATION_OPEN_VALUES
        facts: dict[str, Any] = {}
        for key in self._PROGRAM_PUBLIC_FIELDS:
            value = section.get(key)
            if value in (None, "", [], {}):
                continue
            facts[key] = value
        if reg_open:
            url = section.get("registration_url")
            if url:
                facts["registration_url"] = url
        logger.info(
            "[parent_tool] get_program_info program_id=%s status=%s reg_open=%s fields=%d",
            program_id, status, reg_open, len(facts),
        )
        # Per-Product Booking (Cap #2 / R1) — tag the lead with the dynamic
        # product the LLM is fetching so a later booking in THIS conversation
        # resolves to the right age band + registration even when the
        # booking-confirmation turn does not re-name the product. Flag-gated;
        # a no-op when off. Best-effort (never blocks the info answer).
        try:
            from app.config import settings as _pp_settings
            if getattr(_pp_settings, "USE_PER_PRODUCT_BOOKING", False):
                self.lead.program_id = program_id
        except Exception:  # pragma: no cover - defensive: tagging is best-effort
            pass
        payload = {
            "success": True, "program_id": program_id,
            "topic": str(args.get("topic") or "all"),
            "name": section.get("name"), "type": section.get("type"),
            "registration_open": reg_open, "facts": facts,
        }
        # Program audience (2026-07-26, USE_PROGRAM_AUDIENCE): surface child/adult/family so
        # the model asks „the PARTICIPANT's age" for a family/adult program (e.g. Formula 1),
        # not „your CHILD's age". OFF ⇒ payload unchanged (byte-identical).
        if getattr(_pp_settings, "USE_PROGRAM_AUDIENCE", False):
            try:
                from app.services import admin_config_service
                payload["audience"] = admin_config_service.get_program_audience(section)
            except Exception:  # pragma: no cover - defensive
                pass
        return payload

    # -- get_approved_answer (Phase 5 Task 5, USE_LEARNING) -----------------

    def _get_approved_answer(self, args: dict[str, Any]) -> dict[str, Any]:
        """Surface an operator-approved answer for the LLM's consideration.

        No deterministic override — the executor only reports what the
        matcher found; the LLM decides whether to use it. Never raises:
        the lead may be missing/partial, so segment is read defensively.
        """
        segment = (
            getattr(self.lead, "segment", "") or getattr(self.conversation, "segment", "") or ""
        )
        from app.services import approved_answers_service
        match = approved_answers_service.find_approved_answer(args.get("question", ""), segment)
        if match:
            return {"success": True, "id": match["id"], "answer": match["answer"]}
        return {"success": False, "reason": "no_approved_answer"}

    # -- get_program_topic (Capability #1 / Task 2, USE_PROGRAM_TOPICS) ----

    def _get_program_topic(self, args: dict) -> dict:
        """Surface a single camp topic's backend-sourced facts to the LLM.

        Reuses the existing LLM-free readers in `camp_topic_facts` — never
        reimplements topic logic. Accepts BOTH the English YAML keys AND the
        Georgian topic names the prompt actually lists: `medical`/`სამედიცინო`
        route through `medical_answer()` (which layers the operator-approved
        copy service); an English key routes through `answer_for_topic(topic)`;
        anything else (a Georgian name, a loose phrasing) falls back to the
        fuzzy `detect_camp_topic` matcher → key → `answer_for_topic`. Never
        raises: a non-string / empty / unresolvable topic surfaces as
        `success=False`.
        """
        from app.reasoning import camp_topic_facts as _ctf

        raw = (args or {}).get("topic", "")
        topic = raw.strip() if isinstance(raw, str) else ""
        if not topic:
            return {"success": False, "topic": "", "facts": ""}
        # Medical is a separate block; accept the English key and the Georgian name.
        if topic in ("medical", "სამედიცინო"):
            text = _ctf.medical_answer()
            return {"success": bool(text), "topic": "medical", "facts": text or ""}
        # Exact English key first; then the fuzzy Georgian→key matcher so the
        # model can pass the Georgian topic names the prompt suffix lists.
        resolved = topic
        text = _ctf.answer_for_topic(topic)
        if not text:
            key = _ctf.detect_camp_topic(topic)
            if key:
                resolved = key
                text = _ctf.answer_for_topic(key)
        if not text:
            return {"success": False, "topic": topic, "facts": ""}
        return {"success": True, "topic": resolved, "facts": text}

    # -- get_camp_info -----------------------------------------------------

    def _get_camp_info(self, args: dict[str, Any]) -> dict[str, Any]:
        # Per-Product Booking (Cap #2 / R1) — a camp-info fetch means the
        # conversation is (now) about CAMP, so clear any dynamic-product sticky
        # tag on the lead. This is the reliable per-turn camp signal (mirror of
        # `_get_program_info`'s flag-gated tag-SET) that keeps `lead.program_id`
        # accurate across topic pivots, so a stale tag from an earlier
        # get_program_info can never apply a dynamic product's WIDER age band to
        # a camp booking and let an under-min child pass camp's age gate. Flag
        # off ⇒ no-op (byte-identical).
        try:
            from app.config import settings as _pp_settings
            if getattr(_pp_settings, "USE_PER_PRODUCT_BOOKING", False):
                if (getattr(self.lead, "program_id", "") or "").strip():
                    self.lead.program_id = ""
        except Exception:  # pragma: no cover - defensive: best-effort clear
            pass
        topic = str(args.get("topic") or "").strip().lower()
        if topic not in CAMP_INFO_TOPICS:
            return {
                "success": False,
                "reason": "invalid_topic",
                "allowed_topics": list(CAMP_INFO_TOPICS),
            }

        registration_open = _is_camp_registration_open()
        if not registration_open:
            if topic == "registration":
                return _registration_closed_tool_result(topic="registration")
            if topic != "price":
                return _camp_public_info_limited_tool_result(topic)
        # Config-unification patch: read camp facts from the admin-first
        # helper so an operator price/location/streams edit in the
        # Admin Panel takes effect immediately for the LLM's
        # `get_camp_info` tool call. The helper falls back to
        # camp_2026.yaml when admin_config is missing or malformed, so
        # the legacy code path is preserved exactly when the admin
        # panel is not in use.
        source = "admin_config"
        try:
            from app.services import admin_config_service
            camp = admin_config_service.get_camp_facts()
            if not camp:
                camp = load_knowledge("camp_2026")["camp"]
                source = "camp_2026.yaml"
        except Exception as exc:
            logger.exception("[parent_executor] camp facts load failed: %s", exc)
            return {"success": False, "reason": "knowledge_error"}

        logger.info(
            "[parent_tool] get_camp_info_called=True topic=%s source=%s "
            "price_gel=%s price_text=%r",
            topic, source,
            camp.get("price_gel"),
            camp.get("price_text"),
        )

        # Camp Stream Date Filter — surface only streams whose start date has
        # not yet arrived. A started stream is dropped here so the LLM never
        # even sees it and cannot quote it; an empty list means the model has
        # no dates to offer (it must not invent any — see system_parent_v2).
        visible_streams = admin_config_service.get_visible_camp_streams(
            camp.get("streams") or [], year=camp.get("year"),
        )

        if topic == "price":
            # `price_text` is the operator-edited display value (e.g.
            # "2200"); when present, surface it to the LLM so the user
            # sees the operator's exact wording. `price_gel` stays
            # available for arithmetic / sanity checks.
            response = {
                "success": True,
                "topic": "price",
                "price_gel": camp.get("price_gel"),
                "includes": list(camp.get("includes") or []),
                "discounts": [
                    {"name": d.get("name"), "percent": d.get("percent")}
                    if isinstance(d, dict) else {"name": str(d), "percent": None}
                    for d in (camp.get("discounts") or [])
                ],
                "payment": dict(camp.get("payment") or {}),
            }
            if camp.get("price_text"):
                response["price_text"] = camp["price_text"]
            if camp.get("payment_terms"):
                response["payment_terms"] = camp["payment_terms"]
            return response

        if topic == "dates":
            return {
                "success": True,
                "topic": "dates",
                "streams": [
                    {"name": s.get("name"), "dates_text": s.get("dates_text")}
                    for s in visible_streams
                ],
                "duration_days": camp.get("duration_days"),
            }

        if topic == "location":
            return {
                "success": True,
                "topic": "location",
                "location": camp.get("location"),
            }

        if topic == "conditions":
            return {
                "success": True,
                "topic": "conditions",
                "duration_days": camp.get("duration_days"),
                "age_min": camp.get("age_min"),
                "age_max": camp.get("age_max"),
                "location": camp.get("location"),
                "includes": list(camp.get("includes") or []),
                "price_gel": camp.get("price_gel"),
            }

        if topic == "age_range":
            return {
                "success": True,
                "topic": "age_range",
                "age_min": camp.get("age_min"),
                "age_max": camp.get("age_max"),
            }

        if topic == "registration":
            # P3-C PATCH 1 — registration vs consultation: when no
            # registration URL is configured in the knowledge YAML, do
            # NOT invent one. The LLM must explain that the link is not
            # in the system and offer the phone/manager instead.
            reg_url = (camp.get("registration_url") or "").strip()
            phone = (camp.get("phone") or "").strip()
            if not reg_url:
                return {
                    "success": False,
                    "reason": "registration_url_missing",
                    "phone": phone or None,
                }
            return {
                "success": True,
                "topic": "registration",
                "registration_url": reg_url,
                "phone": phone or None,
            }

        # topic == "all"
        return {
            "success": True,
            "topic": "all",
            "name": camp.get("name"),
            "year": camp.get("year"),
            "location": camp.get("location"),
            "age_min": camp.get("age_min"),
            "age_max": camp.get("age_max"),
            "duration_days": camp.get("duration_days"),
            "price_gel": camp.get("price_gel"),
            "includes": list(camp.get("includes") or []),
            "streams": [
                {"name": s.get("name"), "dates_text": s.get("dates_text")}
                for s in visible_streams
            ],
            "registration_url": camp.get("registration_url") if registration_open else "",
            "phone": camp.get("phone"),
        }

    # -- get_available_slots ----------------------------------------------

    def _get_available_slots(self, args: dict[str, Any] | None = None) -> dict[str, Any]:
        """Return Calendar slots — date-aware when `date_iso` is passed.

        Argument shape (all optional):
          - date_iso (YYYY-MM-DD): when present, look up slots for that
            specific date (plus `days-1` weekdays after, default 1).
          - days: integer 1–14. Defaults to 1 when `date_iso` is given,
            otherwise 7 (legacy "next week" behaviour).

        With no arguments this falls back to the original
        `parent_flow._load_available_slots` path so the older test
        suite keeps matching it.
        """
        from app.flows import parent_flow
        from app.services import calendar_service

        args = args or {}
        date_iso = (args.get("date_iso") or "").strip()
        days_raw = args.get("days")

        logger.info(
            "[get_slots] called date_iso=%s days=%s sender=%s",
            date_iso or "", days_raw, self.sender_id,
        )

        if not self._registration_open_for_booking():
            return _registration_closed_tool_result(slots=[])
        if date_iso:
            from datetime import date as _date_cls
            try:
                target_date = _date_cls.fromisoformat(date_iso)
            except ValueError:
                return {
                    "success": False,
                    "reason": "invalid_date_iso",
                    "slots": [],
                }
            try:
                days = int(days_raw) if days_raw is not None else 1
            except (TypeError, ValueError):
                days = 1
            days = max(1, min(days, 14))
            try:
                slots = calendar_service.get_free_slots(
                    start_date=target_date, days=days,
                )
            except Exception as exc:
                logger.exception(
                    "[parent_executor] get_free_slots(date_iso=%s) failed: %s",
                    date_iso, exc,
                )
                return {"success": False, "reason": "calendar_error", "slots": []}
        else:
            try:
                slots = parent_flow._load_available_slots(self.cache_key)
            except Exception as exc:
                logger.exception(
                    "[parent_executor] _load_available_slots failed: %s", exc,
                )
                return {"success": False, "reason": "calendar_error", "slots": []}

        logger.info(
            "[get_slots] calendar returned %d slots", len(slots),
        )

        formatted: list[dict[str, Any]] = []
        for index, slot in enumerate(slots[:6], start=1):
            formatted.append({
                "slot_id": index,
                "datetime_iso": slot.get("datetime_iso", ""),
                "display": f"{slot.get('date', '')}, {slot.get('time', '')}".strip(", "),
            })

        _last_slots_by_sender[self.cache_key] = list(formatted)
        return {
            "success": True,
            "slots": formatted,
            **({"date_iso": date_iso} if date_iso else {}),
        }

    # -- check_consultation_slot (PATCH 6) --------------------------------

    def _check_consultation_slot(self, args: dict[str, Any]) -> dict[str, Any]:
        """P3-C PATCH 6 — return granular availability for an exact slot.

        Live bug: the LLM saw a truncated 6-slot list from
        ``get_available_slots`` and concluded an unlisted time
        (e.g. 27 May 15:00) was "not available", offering alternatives
        instead. The truth was that the slot was free in Calendar but
        beyond the list cap.

        This tool consults Calendar directly for ONE specific
        ``datetime_iso`` and separates the three rejection paths the
        old monolithic check muddled together:

          * business-hour rejection (``outside_business_hours`` /
            ``weekend``);
          * today-only buffer (``buffer_today``);
          * Calendar busy (``calendar_busy``);
          * invalid input (``invalid_datetime`` / ``past_datetime``).

        When the slot IS available, we also stash a pending_booking
        record on the conversation so the deterministic PATCH 5 commit
        path can pick it up when the parent later supplies name/phone.
        """
        from app.flows import parent_flow
        from app.services import calendar_service

        datetime_iso = (args.get("datetime_iso") or "").strip()
        datetime_iso = self._normalise_datetime_iso_from_message(datetime_iso)

        logger.info(
            "[slot_check] requested_datetime=%s sender=%s",
            datetime_iso, self.sender_id,
        )

        if not self._registration_open_for_booking():
            return _registration_closed_tool_result(
                datetime_iso=datetime_iso,
                inside_business_hours=False,
                calendar_available=False,
                available=False,
                alternative_slots=[],
            )
        if not datetime_iso:
            logger.warning("[slot_check] reason=invalid_datetime (missing)")
            return {
                "success": True,
                "datetime_iso": "",
                "inside_business_hours": False,
                "calendar_available": False,
                "available": False,
                "reason": "invalid_datetime",
                "alternative_slots": [],
            }

        slot_dt = _parse_iso_datetime(datetime_iso)
        if slot_dt is None:
            logger.warning(
                "[slot_check] reason=invalid_datetime value=%r", datetime_iso,
            )
            return {
                "success": True,
                "datetime_iso": datetime_iso,
                "inside_business_hours": False,
                "calendar_available": False,
                "available": False,
                "reason": "invalid_datetime",
                "alternative_slots": [],
            }

        try:
            tbilisi_tz = parent_flow.TBILISI_TZ
            slot_dt_tz = slot_dt if slot_dt.tzinfo else slot_dt.replace(tzinfo=tbilisi_tz)
            slot_dt_tz = slot_dt_tz.astimezone(tbilisi_tz)
        except Exception:
            return {
                "success": True,
                "datetime_iso": datetime_iso,
                "inside_business_hours": False,
                "calendar_available": False,
                "available": False,
                "reason": "invalid_datetime",
                "alternative_slots": [],
            }

        logger.info(
            "[slot_check] parsed_tbilisi=%s business_hours=%s-%s buffer_minutes=%d",
            slot_dt_tz.isoformat(),
            calendar_service.BUSINESS_HOUR_START.strftime("%H:%M"),
            calendar_service.BUSINESS_HOUR_END.strftime("%H:%M"),
            int(calendar_service.SLOT_BUFFER.total_seconds() // 60),
        )

        ok_hours, hours_reason = calendar_service.is_within_business_hours(slot_dt_tz)
        inside_business_hours = ok_hours
        buffer_applied = (
            slot_dt_tz.date() == datetime.now(tbilisi_tz).date()
        )

        logger.info(
            "[slot_check] inside_business_hours=%s buffer_applied=%s reason_hours=%s",
            inside_business_hours, buffer_applied, hours_reason or "(none)",
        )

        if not ok_hours:
            alternatives = self._alternative_slots_for(slot_dt_tz)
            logger.info(
                "[slot_check] available=False reason=%s alternatives_count=%d",
                hours_reason, len(alternatives),
            )
            return {
                "success": True,
                "datetime_iso": slot_dt_tz.isoformat(),
                "inside_business_hours": False,
                "calendar_available": False,
                "available": False,
                "reason": hours_reason,
                "alternative_slots": alternatives,
            }

        # Inside business hours and outside the today buffer — ask Calendar.
        try:
            calendar_free = calendar_service.check_slot_calendar_only(slot_dt_tz)
        except Exception as exc:
            logger.exception("[slot_check] calendar_only check raised: %s", exc)
            calendar_free = False

        logger.info(
            "[slot_check] calendar_available=%s", calendar_free,
        )

        if not calendar_free:
            alternatives = self._alternative_slots_for(slot_dt_tz)
            logger.info(
                "[slot_check] available=False reason=calendar_busy alternatives_count=%d",
                len(alternatives),
            )
            return {
                "success": True,
                "datetime_iso": slot_dt_tz.isoformat(),
                "inside_business_hours": True,
                "calendar_available": False,
                "available": False,
                "reason": "calendar_busy",
                "alternative_slots": alternatives,
            }

        # Slot IS available. Record a confirmed pending booking so the
        # downstream commit path picks it up after name/phone arrive.
        #
        # Live QA Session 7 Patch (2026-06-06) — Bug 1: when the lead is
        # ALREADY booked at a different time, this slot check is part of
        # a reschedule flow. Stash the old event_id + old booked iso on
        # the pending booking so the commit path can route through
        # `manage_consultation_booking(action="reschedule")` and so the
        # in-flight reschedule state survives the user's confirmation
        # turn ("კი მაწყობს").
        try:
            parent_flow._record_pending_booking_for_slot(
                self.conversation, self.lead,
                {
                    "slot_id": 0,
                    "datetime_iso": slot_dt_tz.isoformat(),
                    "display": f"{_display_date(slot_dt_tz)}, {slot_dt_tz.strftime('%H:%M')}",
                },
            )
            if isinstance(self.conversation.pending_booking, dict):
                is_reschedule = _is_reschedule_scenario(
                    self.lead, slot_dt_tz.isoformat(),
                )
                if is_reschedule:
                    self.conversation.pending_booking["source"] = "reschedule"
                    self.conversation.pending_booking["old_event_id"] = (
                        (self.lead.calendar_event_id or "").strip()
                    )
                    self.conversation.pending_booking["old_booked_datetime_iso"] = (
                        (self.lead.booked_datetime_iso or "").strip()
                    )
                    logger.info(
                        "[slot_check] reschedule scenario detected: "
                        "old_event_id=%s old_iso=%s new_iso=%s",
                        (self.lead.calendar_event_id or "").strip(),
                        (self.lead.booked_datetime_iso or "").strip(),
                        slot_dt_tz.isoformat(),
                    )
                else:
                    # Tag the source so analytics can tell apart user-typed
                    # exact requests from picks off the offered list.
                    self.conversation.pending_booking["source"] = (
                        "user_requested_exact_slot"
                    )
        except Exception as exc:
            logger.warning(
                "[slot_check] could not record pending_booking: %s", exc,
            )

        logger.info(
            "[slot_check] available=True reason=(none) datetime=%s",
            slot_dt_tz.isoformat(),
        )
        return {
            "success": True,
            "datetime_iso": slot_dt_tz.isoformat(),
            "inside_business_hours": True,
            "calendar_available": True,
            "available": True,
            "reason": "",
            "alternative_slots": [],
        }

    def _alternative_slots_for(self, slot_dt) -> list[dict[str, Any]]:
        """Pull alternatives for the same date the user named, fall back
        to the legacy `_load_available_slots` cache if Calendar is
        unreachable. Returns up to 3 slot dicts shaped like
        ``{datetime_iso, display}``."""
        from app.flows import parent_flow
        from app.services import calendar_service

        candidates: list[dict[str, Any]] = []
        try:
            day_slots = calendar_service.get_free_slots(
                start_date=slot_dt.date(), days=1,
            )
            candidates.extend(day_slots or [])
        except Exception as exc:
            logger.warning(
                "[slot_check] alt-slots same-day lookup failed: %s", exc,
            )

        if not candidates:
            try:
                candidates = parent_flow._load_available_slots(self.cache_key) or []
            except Exception as exc:
                logger.warning(
                    "[slot_check] alt-slots fallback failed: %s", exc,
                )
                candidates = []

        formatted: list[dict[str, Any]] = []
        for slot in candidates[:3]:
            formatted.append({
                "datetime_iso": slot.get("datetime_iso", ""),
                "display": f"{slot.get('date', '')}, {slot.get('time', '')}".strip(", "),
            })
        return formatted

    # -- book_consultation ------------------------------------------------

    def _resolve_booking_program_id(self) -> str:
        """Effective admin product id for THIS consultation booking (Cap #2 / R1).

        Booking is the GUARDRAIL zone, so this FAILS CLOSED to camp on any doubt.
        Returns ``""`` (⇒ camp age band + camp registration, byte-identical) when
        ``USE_PER_PRODUCT_BOOKING`` is off. When on, resolution order:
          1. the CURRENT message NAMES a dynamic product → that id (and stick it
             to the lead so a multi-turn confirmation „კი"/„16:00" — which does
             NOT re-name the product — keeps the right band);
          2. the CURRENT message shows explicit CAMP intent → clear any sticky
             tag and return ``""`` (an explicit camp pivot reverts to the camp
             band; the fuzzy matcher never returns ``summer_camp`` because its
             name tokens are ambiguous, so this deterministic camp detector is
             the reliable clear signal);
          3. the product already stuck to this lead (from ``get_program_info`` or
             an earlier book turn this conversation) → that id;
          4. else ``""`` → camp.
        Never a hardcoded/reserved id. Never raises.
        """
        try:
            from app.config import settings
            if not getattr(settings, "USE_PER_PRODUCT_BOOKING", False):
                return ""
        except Exception:  # pragma: no cover - defensive → camp
            return ""
        # 1. current message names a dynamic product → stick it
        try:
            from app.reasoning.dynamic_program_match import match_dynamic_program
            from app.services import admin_config_service
            m = match_dynamic_program(
                self.user_message or "", admin_config_service.get_active_sections(),
                fuzzy=getattr(settings, "USE_FUZZY_PROGRAM_MATCH", False),
            )
            pid = (m or {}).get("program_id") or ""
            if pid and pid not in reserved_program_ids():
                self.lead.program_id = pid
                return pid
        except Exception:  # pragma: no cover - defensive → fall through to camp
            pass
        # 2. explicit camp intent → revert to camp, clear a stale sticky tag
        try:
            from app.flows import parent_flow
            if parent_flow._has_explicit_georgian_camp_intent(self.user_message or ""):
                self.lead.program_id = ""
                return ""
        except Exception:  # pragma: no cover - defensive
            pass
        # 3. sticky product from earlier this conversation. Two camp signals
        #    clear the tag so it stays accurate across the NORMAL flow: explicit
        #    camp intent (step 2, this turn) and any `get_camp_info` fetch (on
        #    ANY turn). (get_program_info sets it; get_camp_info clears it.) The
        #    residual gap — a browse-dynamic-then-book-camp conversation whose
        #    booking turn is a bare confirm AND never fetched get_camp_info — is
        #    the documented single-product-conversation scope limitation (see
        #    docs/ENABLEMENT_USE_PER_PRODUCT_BOOKING.md).
        stuck = (getattr(self.lead, "program_id", "") or "").strip()
        if stuck and stuck not in reserved_program_ids():
            return stuck
        # 4. camp
        return ""

    def _registration_open_for_booking(self) -> bool:
        """Registration-open check for the CONSULTATION booking flow, PER-PRODUCT.

        Live bug (2026-07-23): the slot-check / slot-listing / reschedule paths
        hard-coded `_is_camp_registration_open()`, so once the camp ended EVERY
        consultation was blocked with „registration closed" — even for a dynamic
        product (Disneyland). This mirrors `_book_consultation`'s existing gate:
        resolve the booking product and check ITS registration; fall back to camp
        when there is no per-product context (USE_PER_PRODUCT_BOOKING off, or a
        camp booking) — byte-identical to today. Never raises."""
        try:
            program_id = self._resolve_booking_program_id()
            if program_id:
                from app.services import admin_config_service
                return admin_config_service.is_program_registration_open(program_id)
        except Exception:  # pragma: no cover - defensive → camp
            pass
        return _is_camp_registration_open()

    def _book_consultation(self, args: dict[str, Any]) -> dict[str, Any]:
        from app.flows import parent_flow
        from app.services import admin_config_service, calendar_service

        name = (args.get("name") or "").strip()
        # Live Bug 2 (2026-06-11) — a month / date / time / booking word
        # passed as the name (e.g. „ივნის") must never be stored or
        # confirmed. Drop it; the required-fields check then falls back to
        # any valid name already on the lead, or blocks with missing_name.
        if name and not parent_flow.is_valid_person_name(name):
            logger.info(
                "[book_consultation] ignoring non-name value=%r", name[:40],
            )
            name = ""
        phone_raw = (args.get("phone") or "").strip()
        datetime_iso = (args.get("datetime_iso") or "").strip()
        # Booking Date Parse Patch (2026-06-04) — re-resolve a Georgian
        # relative-day phrase from the user message so "ხვალ 11 საათზე"
        # is never treated as a past date by the LLM's date arithmetic.
        datetime_iso = self._normalise_datetime_iso_from_message(datetime_iso)
        child_age_raw = str(args.get("child_age") or "").strip()
        notes = (args.get("notes") or "").strip()
        # P3-C PATCH 1 — explicit user confirmation gate. The LLM must
        # set this to True ONLY when the parent named/confirmed this
        # exact date and time. Default False prevents the LLM from
        # auto-selecting the first available slot.
        # P3-C PATCH 5 — also honour pending_booking's stored confirmation
        # when the LLM forgot to set the flag but the user already named
        # the slot in a previous turn.
        user_confirmed = bool(args.get("user_confirmed_datetime"))
        if not user_confirmed:
            pending = getattr(self.conversation, "pending_booking", None) or {}
            pending_iso = (pending.get("requested_datetime_iso") or "").strip()
            if (
                pending.get("user_confirmed_datetime")
                and pending_iso
                and pending_iso == datetime_iso
            ):
                user_confirmed = True

        logger.info(
            "[book_consultation] START name_present=%s phone=%s datetime_iso=%s "
            "child_age=%s user_confirmed=%s sender=%s",
            bool(name or (self.lead.name or "").strip()),
            _mask_phone(phone_raw or self.lead.phone),
            datetime_iso,
            child_age_raw or self.lead.child_age,
            user_confirmed,
            self.sender_id,
        )

        # Default the per-conversation success flag to False for this turn;
        # only set True at the very end on a confirmed Calendar+state write.
        book_consultation_success_for_conversation[self.cache_key] = False

        # Per-Product Booking (Cap #2 / R1) — resolve the admin product for this
        # booking. "" ⇒ camp (flag off, or no product context) ⇒ registration +
        # age band below are byte-identical to today. A non-empty id swaps ONLY
        # the registration source and the age-band source (below) to that
        # product's section; every other gate is unchanged.
        program_id = self._resolve_booking_program_id()

        registration_open = (
            admin_config_service.is_program_registration_open(program_id)
            if program_id else _is_camp_registration_open()
        )
        if not registration_open:
            logger.warning(
                "[book_consultation] BLOCKED reason=registration_closed program_id=%s",
                program_id or "summer_camp",
            )
            return _registration_closed_tool_result()

        # 1. Required fields ------------------------------------------------
        if not name and not (self.lead.name or "").strip():
            logger.warning("[book_consultation] BLOCKED reason=missing_name")
            return {"success": False, "reason": "missing_name", "required_field": "name"}
        if not phone_raw and not (self.lead.phone or "").strip():
            logger.warning("[book_consultation] BLOCKED reason=missing_phone")
            return {"success": False, "reason": "missing_phone", "required_field": "phone"}
        if not datetime_iso:
            logger.warning("[book_consultation] BLOCKED reason=missing_datetime")
            return {
                "success": False,
                "reason": "missing_datetime",
                "required_field": "datetime_iso",
            }
        if not child_age_raw and not (self.lead.child_age or "").strip():
            logger.warning("[book_consultation] BLOCKED reason=missing_child_age")
            return {
                "success": False,
                "reason": "missing_child_age",
                "required_field": "child_age",
            }

        logger.info("[book_consultation] required_fields_ok")

        # 1b. Explicit user confirmation — P3-C PATCH 1 + PATCH 5.
        # Live test showed the LLM happily picking the first slot from
        # `get_available_slots` once name + phone + age were collected,
        # without the parent ever naming a time. Backend rejects that
        # path before doing anything destructive.
        if not user_confirmed:
            logger.warning("[book_consultation] BLOCKED reason=datetime_not_confirmed")
            return {
                "success": False,
                "reason": "datetime_not_confirmed",
                "required_field": "user_confirmed_datetime",
            }

        # Live QA Bug Fix Patch (2026-06-04) — verification phrases.
        # When the user's current message is a re-check question
        # („კარგად შეამოწმე თავისუფალია?" / „ნამდვილად
        # თავისუფალია?" / „დარწმუნებული ხარ?" / „ზუსტი
        # ინფორმაციაა?"), they want a fresh availability check, NOT
        # a booking. The LLM occasionally mistakes the question for
        # confirmation and forwards `user_confirmed_datetime=True`;
        # this guard blocks the book and tells the LLM to re-call
        # `check_consultation_slot` instead.
        if _user_requested_verification(self.user_message):
            logger.warning(
                "[book_consultation] BLOCKED reason=verification_requested "
                "user_message_head=%r",
                (self.user_message or "")[:80],
            )
            return {
                "success": False,
                "reason": "verification_requested",
                "next_action": "check_consultation_slot",
                "datetime_iso": datetime_iso,
            }

        # 2. Age eligibility ------------------------------------------------
        # Canonical Admin Config age band (5A-2 migration) — was a direct
        # camp_2026.yaml read; an operator age-range edit now reaches this
        # path. Default stays 9–17, so today's behaviour is identical.
        # Per-Product Booking (Cap #2 / R1): a non-empty program_id swaps the
        # band SOURCE to that product's section (fail-closed to camp on any
        # missing/blank/invalid bound — never a disabled check). program_id=""
        # (flag off / camp / no product) ⇒ camp band, byte-identical.
        if program_id:
            age_min, age_max = admin_config_service.get_program_age_bounds(program_id)
        else:
            age_min, age_max = admin_config_service.get_camp_age_bounds()

        candidate_age = child_age_raw or (self.lead.child_age or "")
        age_int = _extract_age(candidate_age)
        if age_int is None:
            logger.warning(
                "[book_consultation] BLOCKED reason=invalid_child_age value=%r",
                candidate_age,
            )
            return {
                "success": False,
                "reason": "invalid_child_age",
                "required_field": "child_age",
                "age_min": age_min,
                "age_max": age_max,
            }
        eligible = age_min <= age_int <= age_max
        logger.info(
            "[book_consultation] age_check age=%s eligible=%s",
            age_int, eligible,
        )
        if not eligible:
            logger.warning(
                "[book_consultation] BLOCKED reason=age_not_eligible age=%s range=[%s,%s]",
                age_int, age_min, age_max,
            )
            return {
                "success": False,
                "reason": "age_not_eligible",
                "age_min": age_min,
                "age_max": age_max,
                "provided_age": age_int,
            }

        # 3. Phone validation (reuse existing parser for byte-identical
        #    behaviour with the deterministic flow).
        phone_for_validation = phone_raw or self.lead.phone or ""
        _parsed_name, parsed_phone = parent_flow._parse_name_phone(phone_for_validation)
        logger.info(
            "[book_consultation] phone_valid=%s phone=%s",
            bool(parsed_phone), _mask_phone(parsed_phone),
        )
        if not parsed_phone:
            logger.warning("[book_consultation] BLOCKED reason=invalid_phone")
            return {"success": False, "reason": "invalid_phone"}

        # 4. Datetime validation -------------------------------------------
        slot_dt = _parse_iso_datetime(datetime_iso)
        if slot_dt is None:
            logger.warning(
                "[book_consultation] BLOCKED reason=invalid_datetime value=%r",
                datetime_iso,
            )
            return {"success": False, "reason": "invalid_datetime"}
        logger.info("[book_consultation] datetime_parsed=%s", slot_dt.isoformat())

        try:
            tbilisi_tz = parent_flow.TBILISI_TZ
            slot_dt_tz = slot_dt if slot_dt.tzinfo else slot_dt.replace(tzinfo=tbilisi_tz)
            slot_dt_tz = slot_dt_tz.astimezone(tbilisi_tz)
        except Exception:
            return {"success": False, "reason": "invalid_datetime"}

        now = datetime.now(slot_dt_tz.tzinfo)
        if slot_dt_tz <= now:
            logger.warning(
                "[book_consultation] BLOCKED reason=datetime_in_past slot=%s now=%s",
                slot_dt_tz.isoformat(), now.isoformat(),
            )
            return {"success": False, "reason": "datetime_in_past"}

        # Business-hours check before hitting Calendar (avoid noisy API
        # round-trip for obvious rejects). The Calendar service applies
        # the same rule + the 2h buffer; we surface a different reason
        # only when the time is clearly outside business hours.
        business_ok = True
        try:
            from app.services.calendar_service import (
                BUSINESS_HOUR_END,
                BUSINESS_HOUR_START,
                SLOT_DURATION,
                is_closed_booking_day,
            )

            slot_end_dt = slot_dt_tz + SLOT_DURATION
            if (
                is_closed_booking_day(slot_dt_tz)
                or slot_dt_tz.time() < BUSINESS_HOUR_START
                or slot_end_dt.time() > BUSINESS_HOUR_END
            ):
                business_ok = False
                logger.info(
                    "[book_consultation] business_hours_ok=%s", business_ok,
                )
                logger.warning(
                    "[book_consultation] BLOCKED reason=outside_business_hours slot=%s",
                    slot_dt_tz.isoformat(),
                )
                return {
                    "success": False,
                    "reason": "outside_business_hours",
                    "business_hours": (
                        f"{BUSINESS_HOUR_START.strftime('%H:%M')}–"
                        f"{BUSINESS_HOUR_END.strftime('%H:%M')} (Mon-Sat, Asia/Tbilisi)"
                    ),
                }
            logger.info("[book_consultation] business_hours_ok=%s", business_ok)
        except Exception:
            # If business-hours constants are unavailable, defer to
            # check_slot_available below.
            pass

        # 5. Slot availability ---------------------------------------------
        logger.info(
            "[book_consultation] checking slot availability datetime=%s",
            slot_dt_tz.isoformat(),
        )
        try:
            is_available = calendar_service.check_slot_available(slot_dt_tz)
        except Exception as exc:
            logger.exception(
                "[book_consultation] check_slot_available raised: %s", exc,
            )
            is_available = False

        logger.info("[book_consultation] slot_available=%s", is_available)

        if not is_available:
            try:
                alternatives = parent_flow._load_available_slots(self.cache_key)
            except Exception as exc:
                logger.exception(
                    "[book_consultation] alternatives load failed: %s", exc,
                )
                alternatives = []
            logger.warning(
                "[book_consultation] BLOCKED reason=slot_unavailable alternatives=%d",
                len(alternatives or []),
            )
            return {
                "success": False,
                "reason": "slot_unavailable",
                "alternative_slots": [
                    {
                        "datetime_iso": s.get("datetime_iso", ""),
                        "display": f"{s.get('date', '')}, {s.get('time', '')}".strip(", "),
                    }
                    for s in (alternatives or [])[:3]
                ],
            }

        # 6. Execute booking ------------------------------------------------
        if name and not self.lead.name:
            self.lead.name = name
        elif name:
            # If LLM is correcting the name, accept it.
            self.lead.name = name
        self.lead.phone = parsed_phone
        self.lead.child_age = str(age_int)
        if notes:
            # BUG B (2026-06-11) — clean + dedupe so a booking-time note
            # never doubles a concept in the Sheets challenge column.
            from app.agent.llm.parent_llm_engine import dedupe_challenge_text
            existing = (self.lead.challenge or "").strip()
            self.lead.challenge = dedupe_challenge_text(
                f"{existing} {notes}".strip() if existing else notes
            )

        # Live QA Session 7 Patch (2026-06-06) — Bug 1 CRITICAL.
        # If the lead is already booked at a DIFFERENT time and has a
        # valid calendar_event_id, this booking attempt is a reschedule
        # — NOT a new booking. Without this guard the executor creates
        # the new event without cancelling the old one, leaving two
        # active consultations for one user. The reroute happens after
        # all `_book_consultation` validations pass (phone, age, etc.)
        # so the safe-ordering inside `_reschedule_booking` (book new
        # → verify event_id → THEN cancel old) takes over.
        if _is_reschedule_scenario(self.lead, slot_dt_tz.isoformat()):
            logger.info(
                "[book_consultation] reschedule scenario — rerouting to "
                "_reschedule_booking: old_event_id=%s old_iso=%s new_iso=%s",
                (self.lead.calendar_event_id or "").strip(),
                (self.lead.booked_datetime_iso or "").strip(),
                slot_dt_tz.isoformat(),
            )
            reschedule_args = {
                "action": "reschedule",
                "new_datetime_iso": slot_dt_tz.isoformat(),
                "old_datetime_iso": (self.lead.booked_datetime_iso or "").strip(),
            }
            reschedule_result = self._reschedule_booking(
                (self.lead.calendar_event_id or "").strip(),
                reschedule_args,
            )
            if reschedule_result.get("success"):
                book_consultation_success_for_conversation[self.cache_key] = True
                booked_date_out = reschedule_result.get("new_date") or _display_date(slot_dt_tz)
                booked_time_out = (
                    reschedule_result.get("new_time")
                    or slot_dt_tz.strftime("%H:%M")
                )
                # Surface a unified shape so callers (parent_flow commit
                # path, LLM prompt rules) can read both the legacy
                # `booked_date` / `booked_time` AND the reschedule-only
                # `old_cancel_failed` flag.
                return {
                    "success": True,
                    "action": "reschedule",
                    "booked_date": booked_date_out,
                    "booked_time": booked_time_out,
                    "booked_datetime_iso": slot_dt_tz.isoformat(),
                    "new_date": booked_date_out,
                    "new_time": booked_time_out,
                    "new_datetime_iso": slot_dt_tz.isoformat(),
                    "old_cancel_failed": bool(
                        reschedule_result.get("old_cancel_failed"),
                    ),
                    "old_event_id": reschedule_args["old_datetime_iso"],
                }
            return reschedule_result

        slot = {
            "date": _display_date(slot_dt_tz),
            "time": slot_dt_tz.strftime("%H:%M"),
            "datetime_iso": slot_dt_tz.isoformat(),
        }

        logger.info("[book_consultation] calling _book_selected_slot")
        booked = False
        book_exception: Exception | None = None
        try:
            booked = parent_flow._book_selected_slot(
                self.conversation, self.lead, slot,
            )
        except Exception as exc:
            logger.exception(
                "[book_consultation] EXCEPTION: %s", exc,
            )
            booked = False
            book_exception = exc

        # Live QA Bug Fix Patch (2026-06-04) — book_slot may return
        # truthy without populating ``lead.calendar_event_id`` (live
        # observation: Google Calendar replied with HTTP 200 but the
        # response body had no ``id``). Treat an empty event_id as a
        # silent failure — the LLM must NEVER claim „ჩაგინიშნეთ"
        # when the Calendar event isn't persisted.
        event_id = (self.lead.calendar_event_id or "").strip() if booked else ""

        logger.info(
            "[book_consultation] book_slot result booked=%s event_id=%s",
            bool(booked), event_id,
        )

        if not booked or not event_id:
            reason = (
                "calendar_booking_failed"
                if booked and not event_id
                else "calendar_error"
            )
            detail = (
                "Calendar accepted the request but returned no event_id"
                if booked and not event_id
                else "Calendar booking failed before an event was created"
            )
            logger.error(
                "[book_consultation] FAILED reason=%s sender=%s slot=%s "
                "booked=%s event_id=%r",
                reason, self.sender_id, slot.get("datetime_iso"),
                bool(booked), event_id,
            )
            # Sentry capture — area + slot ISO (not name/phone) + masked
            # sender. The exception is the original `book_slot` raise if
            # any; otherwise a synthetic RuntimeError so the dashboard
            # still gets an event.
            try:
                exc_for_capture: Exception = (
                    book_exception
                    if book_exception is not None
                    else RuntimeError(detail)
                )
                sentry_service.capture_exception(
                    exc_for_capture,
                    context={
                        "area": "booking",
                        "slot": slot.get("datetime_iso") or "",
                        "sender": sentry_service.mask_sender(self.sender_id),
                        "reason": reason,
                    },
                )
            except Exception:  # pragma: no cover — Sentry must never raise
                pass
            # Clean up half-written state so a hallucinated „ჩაგინიშნეთ"
            # is impossible: clear the per-turn success flag and any
            # half-written lead booking marks. ``_book_selected_slot``
            # sets ``lead.calendly_booked = True`` BEFORE checking
            # event_id, so the empty-event_id branch needs to roll back
            # those side-effects.
            book_consultation_success_for_conversation[self.cache_key] = False
            try:
                self.lead.calendly_booked = False
                self.lead.booked_datetime_iso = ""
                self.lead.calendar_event_id = ""
                if self.lead.status == "Booked":
                    self.lead.status = "New"
            except Exception:  # pragma: no cover — defensive
                pass
            return {
                "success": False,
                "reason": reason,
                "error": "calendar_booking_failed",
                "detail": detail,
                "manager_handoff_required": True,
            }

        # Live QA Patch (2026-06-05) — Bug 5 CRITICAL: the actually-
        # booked datetime (read back from `lead.booked_datetime_iso`,
        # which `_book_selected_slot` stamps from the slot it just
        # wrote to Calendar) MUST match the datetime the user asked
        # for. The live bug: user said „5 ივნისი 10:00" but the
        # booking went on „8 ივნისი 10:00" because an older offered
        # slot was used. Compare the canonical ISO strings; on a
        # mismatch refuse the confirmation, roll the lead back, and
        # surface `slot_mismatch` to the LLM so it apologises and
        # offers a manager handoff.
        actual_iso = (self.lead.booked_datetime_iso or "").strip()
        requested_iso = (slot.get("datetime_iso") or "").strip()
        try:
            requested_dt = _parse_iso_datetime(requested_iso)
            actual_dt = _parse_iso_datetime(actual_iso) if actual_iso else None
        except Exception:
            requested_dt = None
            actual_dt = None
        if (
            requested_dt is not None
            and actual_dt is not None
            and requested_dt != actual_dt
        ):
            logger.error(
                "[book_consultation] SLOT MISMATCH requested=%s actual=%s "
                "sender=%s event_id=%s — rolling back",
                requested_iso, actual_iso, self.sender_id, event_id,
            )
            try:
                sentry_service.capture_exception(
                    RuntimeError("booked datetime ≠ requested datetime"),
                    context={
                        "area": "booking",
                        "slot": requested_iso,
                        "actual_slot": actual_iso,
                        "sender": sentry_service.mask_sender(self.sender_id),
                        "reason": "slot_mismatch",
                    },
                )
            except Exception:  # pragma: no cover — Sentry must never raise
                pass
            book_consultation_success_for_conversation[self.cache_key] = False
            try:
                self.lead.calendly_booked = False
                self.lead.booked_datetime_iso = ""
                self.lead.calendar_event_id = ""
                if self.lead.status == "Booked":
                    self.lead.status = "New"
            except Exception:  # pragma: no cover — defensive
                pass
            return {
                "success": False,
                "reason": "slot_mismatch",
                "error": "calendar_booking_failed",
                "detail": (
                    f"Calendar booked {actual_iso} but the user "
                    f"requested {requested_iso}"
                ),
                "requested_iso": requested_iso,
                "actual_iso": actual_iso,
                "manager_handoff_required": True,
            }

        # _book_selected_slot already:
        #   - set lead.calendly_booked = True
        #   - set lead.booked_datetime_iso
        #   - set lead.status = "Booked"
        #   - generated summary
        #   - appended Sheets row
        #   - sent manager notification
        # Mirror parent_flow._attempt_booking's state side-effects:
        self.conversation.state = "DONE"
        self.conversation.pending_booking = None
        parent_flow.slots_shown_for_state.pop(self.cache_key, None)

        # P3-C PATCH 5 — record the tool success so the final-stage
        # guard in parent_flow can tell the difference between an LLM
        # response that follows a real Calendar write and an LLM response
        # that hallucinates confirmation language without a tool call.
        book_consultation_success_for_conversation[self.cache_key] = True

        # Live QA Patch (2026-06-05) — Bug 5: derive the confirmation
        # display strings from the ACTUAL booked datetime on the lead,
        # not from `slot` (which the LLM may have built from a stale
        # offered slot). After the mismatch guard above, these are
        # guaranteed equal — but reading from `lead` makes the
        # confirmation the single source of truth.
        actual_iso_for_confirm = (
            (self.lead.booked_datetime_iso or "").strip()
            or slot.get("datetime_iso", "")
        )
        try:
            display_dt = _parse_iso_datetime(actual_iso_for_confirm)
        except Exception:
            display_dt = None
        if display_dt is not None:
            try:
                tbilisi_tz = parent_flow.TBILISI_TZ
                display_dt_tz = (
                    display_dt
                    if display_dt.tzinfo
                    else display_dt.replace(tzinfo=tbilisi_tz)
                )
                display_dt_tz = display_dt_tz.astimezone(tbilisi_tz)
                booked_date_out = _display_date(display_dt_tz)
                booked_time_out = display_dt_tz.strftime("%H:%M")
            except Exception:
                booked_date_out = slot.get("date", "")
                booked_time_out = slot.get("time", "")
        else:
            booked_date_out = slot.get("date", "")
            booked_time_out = slot.get("time", "")

        logger.info(
            "[book_consultation] SUCCESS sender=%s date=%s time=%s iso=%s",
            self.sender_id, booked_date_out, booked_time_out,
            actual_iso_for_confirm,
        )

        return {
            "success": True,
            "booked_date": booked_date_out,
            "booked_time": booked_time_out,
            "booked_datetime_iso": actual_iso_for_confirm,
        }

    # -- request_manager_callback ----------------------------------------

    def _request_manager_callback(self, args: dict[str, Any]) -> dict[str, Any]:
        from app.flows import parent_flow
        from app.services import notification_service, openai_service, sheets_service

        name = (args.get("name") or "").strip()
        phone_raw = (args.get("phone") or "").strip()
        notes = (args.get("notes") or "").strip()

        # Live Bug 2 (2026-06-11) — never store a month / date / time /
        # booking word as the name on the manager-callback path either.
        if name and not self.lead.name and parent_flow.is_valid_person_name(name):
            self.lead.name = name

        # Phone may come from this turn's args, or already live on the
        # lead from a previous turn. Either way, run the parser.
        phone_for_validation = phone_raw or (self.lead.phone or "")
        if phone_for_validation:
            _parsed_name, parsed_phone = parent_flow._parse_name_phone(
                phone_for_validation,
            )
            if parsed_phone:
                self.lead.phone = parsed_phone

        if not (self.lead.phone or "").strip():
            return {"success": False, "reason": "missing_phone"}

        # Already notified this conversation? Don't double-fire.
        # P3-B — checks Redis as a fallback so the guard survives restart.
        already = _is_manager_notified(self.cache_key, legacy_sender_id=self.sender_id)
        if already:
            return {
                "success": True,
                "manager_notified": False,
                "reason": "already_notified",
            }

        if notes:
            existing = (self.lead.challenge or "").strip()
            self.lead.challenge = f"{existing} {notes}".strip() if existing else notes

        # Summary may fail (no OpenAI billing, network blip) — degrade
        # gracefully to whatever is already on the lead, then to a
        # Georgian fallback so the manager never sees an empty or
        # English-only CRM row.
        try:
            summary = openai_service.generate_summary(self.conversation.history)
        except Exception as exc:
            logger.warning(
                "[parent_executor] generate_summary failed for manager handoff: %s",
                exc,
            )
            summary = (self.lead.conversation_summary or "").strip()
        if not summary or not summary.strip():
            summary = openai_service._georgian_summary_fallback()

        if summary:
            self.lead.conversation_summary = summary
        if (self.lead.status or "") not in {"Booked"}:
            self.lead.status = "Qualified"

        # Honest dispatch (false-success fix, live bug 2026-06-22): gate
        # success on the REAL email send. Email-only success counts —
        # WhatsApp is intentionally unconfigured in production, so the legacy
        # email-AND-whatsapp contract would wrongly report failure on every
        # send. Previously this ignored the result and ALWAYS returned
        # success=True (the LLM then claimed a handoff that never dispatched).
        # On failure we do NOT mark notified, so a later turn can retry.
        dispatched = False
        try:
            dispatched = notification_service.send_manager_notification(
                self.lead, self.lead.conversation_summary,
            )
        except Exception as exc:
            logger.exception(
                "[parent_executor] send_manager_notification raised: %s", exc,
            )
            dispatched = False

        if not dispatched:
            return {"success": False, "reason": "dispatch_failed"}

        # Write the CRM lead ONLY after a confirmed dispatch, so a
        # failed-then-retried manager callback never appends a duplicate
        # Leads row (the dispatch gate above can now fail-and-retry).
        try:
            sheets_service.create_lead(self.lead)
        except Exception as exc:
            logger.exception(
                "[parent_executor] sheets_service.create_lead raised: %s", exc,
            )

        _mark_manager_notified(self.cache_key, legacy_sender_id=self.sender_id)
        return {"success": True, "manager_notified": True}

    # -- save_lead_info ---------------------------------------------------

    def _save_lead_info(self, args: dict[str, Any]) -> dict[str, Any]:
        from app.flows import parent_flow

        saved: list[str] = []
        invalid: list[str] = []

        # International phone / name truncation guard (client hotfix 2026-07-03).
        # The LLM occasionally splits a contact like „ნიკოლოზ +995595999733"
        # into name="ნიკოლოზ +" (stray „+") and phone="595999733" (country code
        # dropped) BEFORE it reaches this tool. The deterministic parser on the
        # RAW user message (unit-tested, preserves the country code) recovers the
        # clean name + full number, so prefer it whenever THIS turn's message
        # carries exactly one phone. The Georgian local happy path is unchanged
        # (msg-derived and arg-derived values are identical there).
        _msg_name, _msg_phone = "", ""
        _msg_single_phone = False
        try:
            _msg_name, _msg_phone = parent_flow._parse_name_phone(
                self.user_message or "",
            )
            _distinct = parent_flow._distinct_valid_phones(self.user_message or "")
            _msg_single_phone = bool(_msg_phone) and len(_distinct) == 1
            # +43/+49 hotfix (2026-07-04) — when the message has exactly ONE phone
            # and `_distinct_valid_phones` kept a longer, country-code-preserving
            # form than `_parse_name_phone` (which could otherwise truncate a
            # non-995 „+" number into an embedded 9-digit local window), prefer the
            # FULL international number. Same trailing digits, fuller form.
            if _msg_single_phone:
                _full = _distinct[0]
                _dm = "".join(c for c in (_msg_phone or "") if c.isdigit())
                _df = "".join(c for c in (_full or "") if c.isdigit())
                if _dm and _df and _df.endswith(_dm) and len(_df) > len(_dm):
                    _msg_phone = _full
        except Exception:  # pragma: no cover — defensive, never break a save
            _msg_name, _msg_phone, _msg_single_phone = "", "", False

        if "name" in args and (args.get("name") or "").strip():
            name = args["name"].strip()
            # On a single-phone contact turn, trust the deterministic parse of
            # the raw message (drops the stray „+" the LLM pulled off the number).
            if _msg_single_phone and _msg_name:
                name = _msg_name
            # Live Bug 2 (2026-06-11) — never store a month / date / time /
            # booking word as the parent's name even when the LLM passes it
            # directly (e.g. name="ივნის"). Same deterministic guard the
            # parser uses.
            if name and parent_flow.is_valid_person_name(name):
                # BUG 3 (2026-07-06) — never OVERWRITE an already-captured valid
                # name from a tool echo. The LLM sometimes calls
                # save_lead_info(name=<its own last word>) and clobbered the real
                # name (live: „მარიამი" → „მოგწერეთ"). An explicit user name
                # CORRECTION is handled deterministically pre-engine
                # (`_maybe_handle_contact_correction`), not inferred here.
                existing = (self.lead.name or "").strip()
                if existing and parent_flow.is_valid_person_name(existing):
                    if name != existing:
                        logger.info(
                            "[save_lead_info] kept existing valid name=%r, "
                            "ignored tool name=%r", existing, name[:40],
                        )
                    # else: same name — nothing to do.
                else:
                    self.lead.name = name
                    saved.append("name")
            else:
                logger.info(
                    "[save_lead_info] rejected non-name value=%r", name[:40],
                )
                invalid.append("name")

        if "phone" in args and (args.get("phone") or "").strip():
            _parsed_name, parsed_phone = parent_flow._parse_name_phone(
                str(args["phone"]),
            )
            # Prefer the full number parsed from the raw user message so a country
            # code the LLM dropped from its own phone arg („+995…" → „595999733")
            # is preserved in the lead / Sheet / email / Calendar.
            if _msg_single_phone:
                parsed_phone = _msg_phone
            if parsed_phone:
                self.lead.phone = parsed_phone
                saved.append("phone")
            else:
                invalid.append("phone")

        if "child_age" in args and str(args.get("child_age") or "").strip():
            raw = str(args["child_age"]).strip()
            # FIX 1 (2026-06-11) — never accept the camp's advertised age
            # band / a range („9-17", „9 დან 17 წლამდე") as the child's
            # age, even if the LLM mistakenly passes it. A single age
            # number is required.
            from app.agent.llm.parent_llm_engine import _contains_age_range
            if _contains_age_range(raw):
                logger.info(
                    "[save_lead_info] rejected age-range child_age=%r", raw,
                )
                invalid.append("child_age")
            else:
                self.lead.child_age = raw
                saved.append("child_age")

        if "challenge" in args and (args.get("challenge") or "").strip():
            # P3-C PATCH 4 — preserve an existing challenge. The live
            # test showed the LLM occasionally re-emitting a shorter
            # variant of the same challenge ("ეკრანი" after
            # "ეკრანისგან დისტანცია") which would otherwise overwrite
            # the richer original. Rules:
            #   - empty existing → store the new value verbatim;
            #   - existing already contains the new value (case
            #     insensitive) → no change;
            #   - new value contains the existing (richer detail) → use
            #     the new value;
            #   - otherwise → append, separated by "; ", capped to
            #     keep the field short for Sheets.
            #
            # Lead Field Separation Patch (2026-06-04) — reject
            # adult-event interest phrases. When a parent first asks
            # about adult cultural evenings (for a sister, friend,
            # etc.) and then switches to the camp flow, the LLM
            # occasionally re-encodes "ზრდასრულთა საღამოები" as the
            # PARENT challenge. That's the wrong field — adult event
            # interest lives on `lead.event_interest` and is owned by
            # the ADULT executor. Reject the write here so the CRM
            # PARENT challenge column stays clean.
            new_value = args["challenge"].strip()
            if _looks_like_adult_event_interest(new_value):
                logger.info(
                    "[parent_executor] save_lead_info IGNORED challenge=%r "
                    "— looks like adult event interest (PARENT/ADULT field "
                    "separation, 2026-06-04)",
                    new_value[:80],
                )
                invalid.append("challenge")
            else:
                # Live Bug 4 (2026-06-11) — clean the SAVE payload so a
                # tacked-on factual question never lands in the Sheets
                # challenge column. Fix at the SAVE chokepoint (not only
                # the manager-email rendering) so the CRM row is clean.
                from app.agent.llm.parent_llm_engine import (
                    challenge_word_set,
                    clean_challenge_for_storage,
                )
                cleaned_new = clean_challenge_for_storage(new_value)
                if not cleaned_new:
                    logger.info(
                        "[parent_executor] save_lead_info IGNORED challenge=%r "
                        "— nothing left after question/filler cleanup",
                        new_value[:80],
                    )
                    invalid.append("challenge")
                else:
                    new_value = cleaned_new
                    existing = (self.lead.challenge or "").strip()
                    if not existing:
                        self.lead.challenge = new_value
                    else:
                        low_existing = existing.lower()
                        low_new = new_value.lower()
                        # BUG B (2026-06-11) — containment now also covers the
                        # comma/space-insensitive word-set case so a re-save of
                        # the same concepts (booking / reschedule / adult→parent
                        # re-entry) never doubles the Sheet challenge text. The
                        # substring checks are preserved (a shorter rephrase
                        # like „ეკრანი" ⊂ „ეკრანისგან დისტანცია" stays). Both
                        # ``existing`` and ``new_value`` are already cleaned +
                        # deduped, so the genuine-merge branch keeps the „; "
                        # separator without re-running the block dedup.
                        existing_words = challenge_word_set(existing)
                        new_words = challenge_word_set(new_value)
                        if low_new in low_existing or (
                            new_words and new_words <= existing_words
                        ):
                            pass  # concepts already covered
                        elif low_existing in low_new or (
                            existing_words and existing_words <= new_words
                        ):
                            self.lead.challenge = new_value  # new is richer
                        else:
                            merged = f"{existing}; {new_value}"
                            self.lead.challenge = merged[:300]
                    saved.append("challenge")

        if "notes" in args and (args.get("notes") or "").strip():
            note = args["notes"].strip()
            if _looks_like_adult_event_interest(note):
                logger.info(
                    "[parent_executor] save_lead_info IGNORED notes=%r "
                    "— looks like adult event interest (PARENT/ADULT field "
                    "separation, 2026-06-04)",
                    note[:80],
                )
                invalid.append("notes")
            else:
                # Live Bug 4 (2026-06-11) — notes also append to
                # lead.challenge, so drop any tacked-on factual question
                # here too before it reaches the Sheets challenge column.
                from app.agent.llm.parent_llm_engine import (
                    clean_challenge_for_storage,
                    dedupe_challenge_text,
                )
                cleaned_note = clean_challenge_for_storage(note)
                if not cleaned_note:
                    logger.info(
                        "[parent_executor] save_lead_info IGNORED notes=%r "
                        "— nothing left after question/filler cleanup",
                        note[:80],
                    )
                    invalid.append("notes")
                else:
                    existing = (self.lead.challenge or "").strip()
                    # BUG B (2026-06-11) — dedupe so a note that repeats an
                    # existing concept never doubles the Sheet challenge text.
                    self.lead.challenge = dedupe_challenge_text(
                        f"{existing} {cleaned_note}".strip()
                        if existing else cleaned_note
                    )
                    saved.append("notes")

        result: dict[str, Any] = {"success": True, "saved_fields": saved}
        if invalid:
            result["invalid_fields"] = invalid
        return result

    # -- manage_consultation_booking (cancel / reschedule) ----------------

    def _manage_consultation_booking(self, args: dict[str, Any]) -> dict[str, Any]:
        """P3-C PATCH 1 — cancel or reschedule an existing booking.

        The executor is the boundary: if backend can't safely modify the
        Calendar event, the result carries ``manager_handoff_required``
        and the LLM is instructed to NOT claim success in its reply.
        """
        from app.services import calendar_service

        action = (args.get("action") or "").strip().lower()
        if action not in {"cancel", "reschedule"}:
            return {"success": False, "reason": "invalid_action"}

        if action == "reschedule" and not self._registration_open_for_booking():
            return _registration_closed_tool_result(action="reschedule")
        # Identify the active booking. We trust the in-memory Lead first
        # (the booking we just made this session) and fall back to the
        # values the LLM passed if those are absent.
        event_id = (self.lead.calendar_event_id or "").strip()
        old_iso = (
            (args.get("old_datetime_iso") or "").strip()
            or (self.lead.booked_datetime_iso or "").strip()
        )
        had_booking = bool(self.lead.calendly_booked or old_iso)

        if not had_booking:
            return {
                "success": False,
                "reason": "no_active_booking",
                "manager_handoff_required": True,
            }

        if action == "cancel":
            return self._cancel_booking(event_id, args)

        # action == "reschedule"
        return self._reschedule_booking(event_id, args)

    def _cancel_booking(self, event_id: str, args: dict[str, Any]) -> dict[str, Any]:
        from app.services import calendar_service

        if not event_id:
            # No Calendar event_id stored — we have no safe way to
            # delete the right event. Hand off to the manager rather
            # than claim a cancellation we didn't perform.
            self._maybe_notify_manager_for_handoff(
                args, note="ჯავშნის გაუქმების მოთხოვნა (event_id უცნობია)",
            )
            return {
                "success": False,
                "reason": "missing_event_id",
                "manager_handoff_required": True,
            }

        try:
            ok = calendar_service.cancel_calendar_event(event_id)
        except Exception as exc:
            logger.exception(
                "[parent_executor] cancel_calendar_event raised: %s", exc,
            )
            ok = False

        if not ok:
            self._maybe_notify_manager_for_handoff(
                args, note="ჯავშნის გაუქმების Calendar API ვერ შესრულდა",
            )
            return {
                "success": False,
                "reason": "calendar_cancel_failed",
                "manager_handoff_required": True,
            }

        self.lead.calendly_booked = False
        self.lead.booked_datetime_iso = ""
        self.lead.calendar_event_id = ""
        if self.lead.status == "Booked":
            self.lead.status = "Cancelled"
        # State stays DONE — booking journey is over; future user
        # messages route through _handle_done_state_message which
        # already tolerates post-cancel conversation.
        self._maybe_notify_manager_for_handoff(
            args, note="ჯავშანი გაუქმდა მომხმარებლის თხოვნით",
            silent=True,
        )
        return {"success": True, "action": "cancel"}

    def _reschedule_booking(self, event_id: str, args: dict[str, Any]) -> dict[str, Any]:
        from app.flows import parent_flow
        from app.services import calendar_service

        new_iso = (args.get("new_datetime_iso") or "").strip()
        # Booking Date Parse Patch (2026-06-04) — same relative-day
        # normalisation as new bookings, so "ხვალ 11 საათზე" on a
        # reschedule path resolves correctly.
        new_iso = self._normalise_datetime_iso_from_message(new_iso)
        if not new_iso:
            return {
                "success": False,
                "reason": "missing_new_datetime",
            }

        new_dt = _parse_iso_datetime(new_iso)
        if new_dt is None:
            return {"success": False, "reason": "invalid_datetime"}

        try:
            tbilisi_tz = parent_flow.TBILISI_TZ
            new_dt_tz = new_dt if new_dt.tzinfo else new_dt.replace(tzinfo=tbilisi_tz)
            new_dt_tz = new_dt_tz.astimezone(tbilisi_tz)
        except Exception:
            return {"success": False, "reason": "invalid_datetime"}

        now = datetime.now(new_dt_tz.tzinfo)
        if new_dt_tz <= now:
            return {"success": False, "reason": "datetime_in_past"}

        try:
            from app.services.calendar_service import (
                BUSINESS_HOUR_END,
                BUSINESS_HOUR_START,
                SLOT_DURATION,
                is_closed_booking_day,
            )

            slot_end_dt = new_dt_tz + SLOT_DURATION
            if (
                is_closed_booking_day(new_dt_tz)
                or new_dt_tz.time() < BUSINESS_HOUR_START
                or slot_end_dt.time() > BUSINESS_HOUR_END
            ):
                return {
                    "success": False,
                    "reason": "outside_business_hours",
                }
        except Exception:
            pass

        try:
            is_available = calendar_service.check_slot_available(new_dt_tz)
        except Exception:
            is_available = False

        if not is_available:
            return {
                "success": False,
                "reason": "slot_unavailable",
            }

        if not event_id:
            # No way to cancel the old event safely — refuse rather than
            # silently double-book.
            self._maybe_notify_manager_for_handoff(
                args,
                note=(
                    "გადატანის მოთხოვნა (event_id უცნობია, ძველი "
                    "ჯავშანი backend-ით ვერ წაიშლება)"
                ),
            )
            return {
                "success": False,
                "reason": "missing_event_id",
                "manager_handoff_required": True,
            }

        # Live QA Patch (2026-06-05) — Bug 9 CRITICAL safe ordering.
        #
        # Old logic was: cancel old event FIRST, then create new. If
        # cancel succeeded but create failed, the user lost their slot
        # AND had no replacement. The corrected order:
        #
        #   1. Stash the old event_id + ISO + lead snapshot.
        #   2. Clear the booking state so `_book_selected_slot` writes
        #      a fresh event_id (it short-circuits when the lead
        #      already says calendly_booked=True).
        #   3. Create the NEW Calendar event.
        #   4. Verify the new event_id exists. On failure → restore
        #      old state, do NOT touch old Calendar event, surface
        #      manager handoff.
        #   5. ONLY after the new booking succeeds, attempt to cancel
        #      the old Calendar event. If THAT fails, keep the new
        #      booking, log + Sentry capture, return a partial-success
        #      result so the LLM does NOT claim the old was cancelled.
        old_event_id = event_id
        old_booked_iso = (self.lead.booked_datetime_iso or "").strip()
        old_status = self.lead.status
        old_calendly_booked = self.lead.calendly_booked

        self.lead.calendar_event_id = ""
        self.lead.booked_datetime_iso = ""
        self.lead.calendly_booked = False

        slot = {
            "date": _display_date(new_dt_tz),
            "time": new_dt_tz.strftime("%H:%M"),
            "datetime_iso": new_dt_tz.isoformat(),
        }

        new_booked = False
        new_book_exception: Exception | None = None
        try:
            new_booked = parent_flow._book_selected_slot(
                self.conversation, self.lead, slot,
            )
        except Exception as exc:
            logger.exception(
                "[parent_executor] _book_selected_slot raised in reschedule: %s",
                exc,
            )
            new_book_exception = exc
            new_booked = False

        new_event_id = (self.lead.calendar_event_id or "").strip()
        if not new_booked or not new_event_id:
            # New booking FAILED. Restore the lead's old booking state
            # so the user keeps their original slot. Old Calendar event
            # was NEVER touched.
            logger.warning(
                "[parent_executor] reschedule: new booking failed, "
                "restoring old slot=%s event_id=%s",
                old_booked_iso, old_event_id,
            )
            self.lead.calendar_event_id = old_event_id
            self.lead.booked_datetime_iso = old_booked_iso
            self.lead.calendly_booked = old_calendly_booked
            self.lead.status = old_status
            try:
                sentry_service.capture_exception(
                    new_book_exception
                    if new_book_exception is not None
                    else RuntimeError("reschedule: new Calendar booking failed"),
                    context={
                        "area": "booking_reschedule",
                        "slot": slot.get("datetime_iso") or "",
                        "old_slot": old_booked_iso,
                        "sender": sentry_service.mask_sender(self.sender_id),
                        "reason": "new_booking_failed_old_preserved",
                    },
                )
            except Exception:  # pragma: no cover — Sentry must never raise
                pass
            return {
                "success": False,
                "reason": "calendar_error",
                "error": "calendar_booking_failed",
                "old_booking_preserved": True,
                "manager_handoff_required": True,
            }

        # BUG A (2026-06-11) — the new booking is confirmed (valid
        # event_id). Signal booking success for THIS turn so the privacy
        # notice appears once on a reschedule done via
        # manage_consultation_booking too (the _book_consultation reroute
        # path also sets this after the call — redundant but harmless).
        book_consultation_success_for_conversation[self.cache_key] = True

        # New booking succeeded with a valid event_id. Now (and only
        # now) attempt to cancel the OLD Calendar event.
        cancelled = False
        cancel_exception: Exception | None = None
        try:
            cancelled = calendar_service.cancel_calendar_event(old_event_id)
        except Exception as exc:
            logger.exception(
                "[parent_executor] cancel during reschedule raised: %s", exc,
            )
            cancel_exception = exc
            cancelled = False

        self.conversation.state = "DONE"
        self.conversation.pending_booking = None

        # Live QA Session 8 Patch (2026-06-07) — Bug 2: target the OLD
        # booking row specifically (oldest sender_id row whose Status
        # cell is "Booked"). The legacy `update_lead(sender_id, ...)`
        # call matched the FIRST sender_id row regardless of status,
        # so a pre-booking discovery row could be relabelled instead
        # of the actual old booking — leaving two "Booked" rows for
        # one user in CRM after reschedule.
        sheets_update_ok = False
        sheets_update_detail = ""
        try:
            from app.services import sheets_service
            if cancelled and old_booked_iso:
                sheets_update_ok, sheets_update_detail = (
                    sheets_service.mark_old_booking_rescheduled(
                        self.sender_id, new_status="Rescheduled",
                    )
                )
            elif old_booked_iso:
                # Cancel of old Calendar event failed — surface that
                # via the legacy update so the CRM at least reflects
                # SOMETHING is in flux. The post-cancel branch below
                # logs + Sentries the manager handoff in that case.
                sheets_service.update_lead(
                    self.sender_id, {"status": "Booked"},
                )
                sheets_update_detail = "old_cancel_failed_no_rewrite"
        except Exception as exc:
            logger.warning(
                "[parent_executor] sheets update on reschedule raised "
                "sender=%s old_event_id=%s: %s",
                sentry_service.mask_sender(self.sender_id),
                sentry_service.mask_sender(old_event_id), exc,
            )
            sheets_update_ok = False
            sheets_update_detail = f"exception:{type(exc).__name__}"

        if cancelled and not sheets_update_ok:
            # Privacy-safe — masked sender + masked old_event_id, no
            # raw phone / name / message body.
            logger.warning(
                "[sheets] old booking reschedule status update failed "
                "sender=%s old_event_id=%s reason=%s",
                sentry_service.mask_sender(self.sender_id),
                sentry_service.mask_sender(old_event_id),
                sheets_update_detail or "unknown",
            )
            # Sentry capture — CRM inconsistency is operator-actionable.
            try:
                sentry_service.capture_exception(
                    RuntimeError(
                        "sheets old-booking reschedule status update failed"
                    ),
                    context={
                        "area": "booking_reschedule",
                        "reason": "sheets_old_row_update_failed",
                        "detail": sheets_update_detail or "",
                        "sender": sentry_service.mask_sender(self.sender_id),
                    },
                )
            except Exception:  # pragma: no cover — Sentry must never raise
                pass

        if not cancelled:
            logger.error(
                "[parent_executor] reschedule: new booking SUCCEEDED but "
                "old cancel FAILED old_event_id=%s — manager handoff",
                old_event_id,
            )
            try:
                sentry_service.capture_exception(
                    cancel_exception
                    if cancel_exception is not None
                    else RuntimeError("reschedule: old Calendar cancel failed"),
                    context={
                        "area": "booking_reschedule",
                        "slot": slot.get("datetime_iso") or "",
                        "old_event_id": old_event_id,
                        "sender": sentry_service.mask_sender(self.sender_id),
                        "reason": "old_cancel_failed_new_booking_active",
                    },
                )
            except Exception:  # pragma: no cover — Sentry must never raise
                pass
            return {
                "success": True,
                "action": "reschedule",
                "new_datetime_iso": slot["datetime_iso"],
                "new_date": slot["date"],
                "new_time": slot["time"],
                "old_cancel_failed": True,
                "manager_handoff_required": True,
            }

        return {
            "success": True,
            "action": "reschedule",
            "new_datetime_iso": slot["datetime_iso"],
            "new_date": slot["date"],
            "new_time": slot["time"],
            "old_cancel_failed": False,
        }

    def _maybe_notify_manager_for_handoff(
        self,
        args: dict[str, Any],
        *,
        note: str,
        silent: bool = False,
    ) -> None:
        """Send a manager notification for a cancel/reschedule handoff.

        Skips silently if no valid phone is on the lead (LLM will then
        ask for the phone). ``silent`` controls whether we still call
        out via the same channel after a successful cancel — useful so
        the manager knows the user no longer wants the slot.
        """
        from app.flows import parent_flow
        from app.services import notification_service, sheets_service

        phone_raw = (args.get("phone") or "").strip()
        if phone_raw:
            _name, parsed = parent_flow._parse_name_phone(phone_raw)
            if parsed:
                self.lead.phone = parsed

        if not (self.lead.phone or "").strip():
            # Without a phone we can't ask the manager to call back —
            # the LLM should ask the user for one.
            return

        # Build a short summary describing the handoff request.
        existing_summary = (self.lead.conversation_summary or "").strip()
        suffix = f"[P3-C PATCH 1] {note}"
        self.lead.conversation_summary = (
            f"{existing_summary}\n{suffix}".strip() if existing_summary else suffix
        )

        if (self.lead.status or "") not in {"Cancelled"}:
            self.lead.status = self.lead.status or "Qualified"

        try:
            sheets_service.create_lead(self.lead)
        except Exception as exc:
            logger.exception(
                "[parent_executor] sheets_service.create_lead (handoff) raised: %s",
                exc,
            )

        try:
            notification_service.send_manager_notification(
                self.lead, self.lead.conversation_summary,
            )
        except Exception as exc:
            logger.exception(
                "[parent_executor] send_manager_notification (handoff) raised: %s",
                exc,
            )

        if not silent:
            _mark_manager_notified(self.cache_key, legacy_sender_id=self.sender_id)

    # -- switch_to_adult_flow ---------------------------------------------

    def _switch_to_adult_flow(self, args: dict[str, Any]) -> dict[str, Any]:
        """P3-C PATCH 1 — flip the conversation segment so the next
        inbound message routes to ``adult_flow.handle``.

        This is a soft handoff. We do NOT clear the lead, do NOT cancel
        any pending camp booking — the parent can come back later and
        the data is preserved. Adult flow's state machine starts fresh
        on its first turn.

        ADULT Live QA Polish Patch (2026-06-02): when the parent's
        ``child_age`` is outside the camp range [9, 17] (e.g. 20 or 25)
        the value was clearly misclassified — the "child" is actually
        an adult user. Transfer it to ``lead.adult_age`` so the ADULT
        engine doesn't re-ask "რამდენი წლის ბრძანდებით?" on the next
        turn, and CLEAR ``lead.child_age`` so the camp flow never
        treats a 25-year-old as a child by mistake.

        Ages inside the camp range stay in ``child_age`` — the parent
        may have a 12-year-old AND a separate interest in adult
        events; the two fields stay independent.
        """
        # Canonical Admin Config age band (5A-2 migration) — was a direct
        # camp_2026.yaml read; an operator age-range edit now reaches this
        # path. Default stays 9–17, so today's behaviour is identical.
        from app.services import admin_config_service
        age_min, age_max = admin_config_service.get_camp_age_bounds()

        transferred_age = ""
        raw_child_age = (self.lead.child_age or "").strip()
        if raw_child_age:
            digits = ""
            for ch in raw_child_age:
                if ch.isdigit():
                    digits += ch
                elif digits:
                    break
            if digits:
                try:
                    age_int = int(digits)
                except ValueError:
                    age_int = -1
                if 0 <= age_int <= 120 and not (age_min <= age_int <= age_max):
                    transferred_age = str(age_int)
                    # CRITICAL: only set adult_age if the field exists
                    # on the Lead dataclass (older Redis snapshots may
                    # be missing it after a rolling deploy).
                    if hasattr(self.lead, "adult_age"):
                        self.lead.adult_age = transferred_age
                    # Clear child_age so the PARENT flow never reads
                    # an adult's age as a child's.
                    self.lead.child_age = ""
                    logger.info(
                        "[parent_executor] switch_to_adult_flow transferred "
                        "child_age=%s → adult_age (outside camp range %d–%d)",
                        transferred_age, age_min, age_max,
                    )

        self.conversation.segment = "ADULT"
        self.conversation.state = "START"
        return {
            "success": True,
            "segment": "ADULT",
            "reason": (args.get("reason") or "").strip() or "adult_event_interest",
            "transferred_adult_age": transferred_age or None,
        }


# -- helpers ---------------------------------------------------------------


def reset_state() -> None:
    """Clear the module-level dicts. Intended for tests."""
    manager_notified_for_conversation.clear()
    _last_slots_by_sender.clear()
    book_consultation_success_for_conversation.clear()


# Live QA Bug Fix Patch (2026-06-04) — verification phrases. When the
# user asks the bot to double-check availability („კარგად შეამოწმე
# თავისუფალია?", „ნამდვილად თავისუფალია?", „დარწმუნებული ხარ?",
# „ზუსტი ინფორმაციაა?"), the LLM occasionally treats the message as a
# booking confirmation and calls ``book_consultation`` with
# ``user_confirmed_datetime=True``. The user wanted a fresh slot
# check, NOT a booking. The executor blocks the book call and forces
# the LLM to re-run ``check_consultation_slot`` via the structured
# reason ``verification_requested``.
_BOOKING_VERIFICATION_PHRASES: tuple[str, ...] = (
    "კარგად შეამოწმე",
    "კარგად შემოწმდი",
    "ზუსტად შეამოწმე",
    "ნამდვილად თავისუფალია",
    "ნამდვილად შესაძლებელია",
    "დარწმუნებული ხარ",
    "დარწმუნებული ხართ",
    "ზუსტი ინფორმაცია",
    "ზუსტი ინფორმაციაა",
    "კიდევ შეამოწმე",
    "კიდევ ერთხელ შეამოწმე",
    "გადაამოწმე",
    "გადამოწმდი",
    # Live QA Patch (2026-06-05) — Bug 11 expansion. Additional
    # phrases from the live transcript that ALSO mean „re-check, do
    # NOT book": calendar-specific verbs, „თავისუფალია ნამდვილად"
    # ordering variants, and the negative form „არ არის თავისუფალი".
    "შეამოწმე კალენდარი",
    "კალენდარი შეამოწმე",
    "კალენდარში ნახე",
    "კალენდარში გადაამოწმე",
    "კალენდარში შეამოწმე",
    "თავისუფალია ნამდვილად",
    "ნამდვილად თავისუფალია",
    "არ არის თავისუფალი",
    "დაკავებული უნდა იყოს",
    "კალენდარი გადაამოწმე",
)


# Live QA Session 7 Patch (2026-06-06) — Bug 1 CRITICAL.
# Closed-set reschedule-intent phrases. When the user already has an
# active booking AND writes one of these in the current message, the
# new datetime they propose is a reschedule, NOT a fresh booking. The
# `_check_consultation_slot` + `_book_consultation` reroute logic uses
# the lead's `calendly_booked` + `calendar_event_id` state as the
# primary signal; this list documents the conversational phrases that
# accompany the scenario (also matched in tests).
RESCHEDULE_INTENT_PHRASES: tuple[str, ...] = (
    "მაგ დროს არ მცალია",
    "მაგ დროზე არ მცალია",
    "ეხლა ვნახე",
    "შესაძლებელია",
    "ჩამწეროთ?",
    "ჩამწეროთ ",
    "გადამიტანეთ",
    "გადატანა",
    "შეცვლა მინდა",
    "სხვა დროს მინდა",
    "სხვა დროზე მინდა",
    "უფრო მოსახერხებელია",
    "ძველი კონსულტაცია წაშალეთ",
    "ძველი წაშალეთ",
    "ახალ დროზე ჩამწერეთ",
    "შემიცვალეთ",
)


def _is_reschedule_scenario(lead: Lead, new_datetime_iso: str) -> bool:
    """Return True when ``lead`` currently holds an active booking and
    ``new_datetime_iso`` names a DIFFERENT moment than the current
    booked datetime.

    Used by ``_check_consultation_slot`` and ``_book_consultation`` to
    decide whether to route through the safe-ordering reschedule path
    instead of creating a second (orphan) Calendar event.

    Conservative — returns False on any of: lead missing, no active
    booking, no event_id, missing/invalid ISOs, both ISOs equal.
    """
    if lead is None:
        return False
    if not bool(getattr(lead, "calendly_booked", False)):
        return False
    old_event_id = (getattr(lead, "calendar_event_id", "") or "").strip()
    if not old_event_id:
        return False
    old_iso = (getattr(lead, "booked_datetime_iso", "") or "").strip()
    if not old_iso:
        return False
    new_iso = (new_datetime_iso or "").strip()
    if not new_iso:
        return False
    try:
        old_dt = _parse_iso_datetime(old_iso)
        new_dt = _parse_iso_datetime(new_iso)
    except Exception:
        return False
    if old_dt is None or new_dt is None:
        return False
    return old_dt != new_dt


def _user_requested_verification(message: str) -> bool:
    """Return True when the user's message asks for a re-check rather
    than confirming the booking. Pure substring scan on a lower-cased
    copy; safe on empty input."""
    if not message:
        return False
    lowered = message.lower()
    for phrase in _BOOKING_VERIFICATION_PHRASES:
        if phrase in lowered:
            return True
    return False


_ADULT_EVENT_INTEREST_STEMS: tuple[str, ...] = (
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
    "ბილეთი",
    "ბილეთები",
    "ბილეთის შეძენ",
    "მუფასა",
    "ელტონ ჯონ",
)


def _looks_like_adult_event_interest(text: str) -> bool:
    """Return True when ``text`` looks like an ADULT event interest
    description rather than a PARENT/camp challenge.

    Used by ``_save_lead_info`` to refuse writes that would otherwise
    leak adult event vocabulary into the PARENT ``lead.challenge``
    column. Conservative — matches Georgian stems characteristic of
    cultural-event language, not generic interest words.

    Lead Field Separation Patch (2026-06-04).
    """
    if not text:
        return False
    lowered = text.lower().strip()
    if not lowered:
        return False
    for stem in _ADULT_EVENT_INTEREST_STEMS:
        if stem in lowered:
            return True
    return False


def _extract_age(value: str) -> int | None:
    if not value:
        return None
    digits = ""
    for ch in value:
        if ch.isdigit():
            digits += ch
        elif digits:
            break
    if not digits:
        return None
    try:
        n = int(digits)
    except ValueError:
        return None
    if n < 0 or n > 99:
        return None
    return n


def _parse_iso_datetime(value: str) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    # Accept trailing 'Z' as UTC.
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        # Fall back to a more relaxed parse: "2026-05-25 12:00".
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
            try:
                return datetime.strptime(text, fmt)
            except ValueError:
                continue
    return None


def _display_date(dt: datetime) -> str:
    """Render '25 მაისი' style date string from a tz-aware datetime."""
    try:
        from app.flows.parent_flow import GEORGIAN_MONTHS_NOM

        return f"{dt.day} {GEORGIAN_MONTHS_NOM[dt.month]}"
    except Exception:
        return dt.strftime("%d %b")


def serialize_result(result: dict[str, Any]) -> str:
    """JSON-dump with ensure_ascii=False so Georgian text round-trips."""
    return json.dumps(result, ensure_ascii=False)
