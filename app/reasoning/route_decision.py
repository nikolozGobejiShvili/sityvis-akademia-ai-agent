"""Safe per-turn route decision metadata.

This module is observability-only. It must not decide routes, change answer
copy, or require callers to provide every field. Raw page IDs, sender IDs, and
canonical session keys are masked before the object is serialized into traces.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, fields, replace
from enum import Enum
from typing import Any


class RouteOwner(str, Enum):
    CONVERSATION_SERVICE = "conversation_service"
    PLANNER = "planner"
    PARENT_FLOW = "parent_flow"
    PARENT_TURN_ROUTER = "parent_turn_router"
    PARENT_LLM_ENGINE = "parent_llm_engine"
    PARENT_TOOL_EXECUTOR = "parent_tool_executor"
    ADULT_FLOW = "adult_flow"
    ADULT_LLM_ENGINE = "adult_llm_engine"
    ADULT_TOOL_EXECUTOR = "adult_tool_executor"
    COMMENT_SERVICE = "comment_service"
    WEBHOOK = "webhook"
    RESPONSE_POLICY = "response_policy"
    KILL_SWITCH = "kill_switch"
    UNKNOWN = "unknown"


class AnswerSource(str, Enum):
    APPROVED_COPY = "approved_copy"
    TEMPLATE = "template"
    ADMIN_CONFIG = "admin_config"
    KNOWLEDGE_YAML = "knowledge_yaml"
    DETERMINISTIC_HANDLER = "deterministic_handler"
    ROUTER_DELEGATE = "router_delegate"
    LLM_DIRECT = "llm_direct"
    LLM_TOOL_LOOP = "llm_tool_loop"
    TOOL_RESULT = "tool_result"
    RESPONSE_POLICY = "response_policy"
    UNCLEAR_MENU = "unclear_menu"
    KILL_SWITCH = "kill_switch"
    FALLBACK = "fallback"
    UNKNOWN = "unknown"


class RouteDomain(str, Enum):
    CAMP = "camp"
    ADULT_EVENTS = "adult_events"
    COMMENT = "comment"
    OFF_TOPIC = "off_topic"
    UNKNOWN = "unknown"


def _enum_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    return value


def _clean_str(value: Any) -> str:
    value = _enum_value(value)
    if value is None:
        return ""
    return str(value).strip()


def mask_identifier(value: str | None) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if len(raw) <= 4:
        return raw[:1] + "***"
    if len(raw) <= 8:
        return raw[:2] + "***" + raw[-1:]
    return raw[:4] + "***" + raw[-2:]


def mask_session_key(session_key: str | None) -> str:
    raw = str(session_key or "").strip()
    if not raw:
        return ""
    parts = raw.split(":")
    if len(parts) == 3:
        return f"{parts[0]}:{mask_identifier(parts[1])}:{mask_identifier(parts[2])}"
    return mask_identifier(raw)


def hash_identifier(value: str | None) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


@dataclass(frozen=True)
class RouteDecision:
    session_key: str = ""
    session_hash: str = ""
    platform: str = ""
    page_id_masked: str = ""
    sender_id_masked: str = ""
    message_id_hash: str = ""
    route_owner: str = RouteOwner.UNKNOWN.value
    domain: str = RouteDomain.UNKNOWN.value
    intent: str = ""
    sub_intent: str = ""
    confidence: float | None = None
    segment_before: str = ""
    segment_after: str = ""
    state_before: str = ""
    state_after: str = ""
    answer_source: str = AnswerSource.UNKNOWN.value
    answer_template_id: str = ""
    approved_copy_id: str = ""
    used_llm: bool = False
    used_tool: bool = False
    handoff_requested: bool = False
    deterministic_reason: str = ""
    fallback_reason: str = ""
    trace_id: str = ""

    @classmethod
    def from_turn(
        cls,
        *,
        session_key: str = "",
        platform: str = "",
        page_id: str = "",
        sender_id: str = "",
        message_id: str = "",
        trace_id: str = "",
    ) -> "RouteDecision":
        return cls(
            session_key=mask_session_key(session_key),
            session_hash=hash_identifier(session_key),
            platform=_clean_str(platform),
            page_id_masked=mask_identifier(page_id),
            sender_id_masked=mask_identifier(sender_id),
            message_id_hash=hash_identifier(message_id),
            trace_id=_clean_str(trace_id),
        )

    @classmethod
    def from_trace_dict(cls, values: dict[str, Any] | None) -> "RouteDecision":
        if not values:
            return cls()
        known = {field.name for field in fields(cls)}
        clean: dict[str, Any] = {}
        for key, value in values.items():
            if key in known:
                clean[key] = _enum_value(value)
        return cls(**clean)

    def with_updates(self, **updates: Any) -> "RouteDecision":
        known = {field.name for field in fields(self)}
        clean: dict[str, Any] = {}
        for key, value in updates.items():
            if key not in known or value is None:
                continue
            if key in {"used_llm", "used_tool", "handoff_requested"}:
                clean[key] = bool(value)
            elif key == "confidence":
                clean[key] = value
            else:
                clean[key] = _clean_str(value)
        if not clean:
            return self
        return replace(self, **clean)

    def to_trace_dict(self) -> dict[str, Any]:
        return {
            field.name: getattr(self, field.name)
            for field in fields(self)
            if getattr(self, field.name) not in {"", None}
        }
