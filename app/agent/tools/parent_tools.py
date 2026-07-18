"""P3-C SAFE — OpenAI tool registry for the PARENT LLM engine.

This module declares the schema the LLM is allowed to call. It is data
only — no execution logic here. The runtime side-effects live in
``parent_tool_executor.py``; the engine wires them together.

Design rules (must hold even when the LLM hallucinates):

  * The LLM may *propose* arguments — backend always validates.
  * The LLM may not invent facts. ``get_camp_info`` is the only fact
    source it has access to; the executor reads from
    ``app/agent/knowledge/camp_2026.yaml``.
  * The LLM may not write to Sheets directly. ``save_lead_info`` only
    mutates the in-memory ``Lead`` — it never touches the CRM. The CRM
    row is created only on a successful ``book_consultation`` or
    ``request_manager_callback`` with a valid phone.
  * The LLM may not notify the manager directly. ``request_manager_callback``
    triggers notification only when backend phone validation passes.
  * The LLM may not book Calendar slots that are past, outside business
    hours, or for an age-ineligible child — the executor enforces all of
    that before calling ``calendar_service.book_slot``.
"""

from __future__ import annotations

from typing import Any

# Tool names — exported so the executor and the engine share the same
# closed set. Anything else the model emits is rejected as "unknown_tool".

TOOL_GET_CAMP_INFO = "get_camp_info"
TOOL_GET_AVAILABLE_SLOTS = "get_available_slots"
TOOL_BOOK_CONSULTATION = "book_consultation"
TOOL_REQUEST_MANAGER_CALLBACK = "request_manager_callback"
TOOL_SAVE_LEAD_INFO = "save_lead_info"
# P3-C PATCH 1 — additional tools to cover cancel/reschedule and the
# adult-segment escape hatch surfaced by the live test.
TOOL_MANAGE_CONSULTATION_BOOKING = "manage_consultation_booking"
TOOL_SWITCH_TO_ADULT_FLOW = "switch_to_adult_flow"
# P3-C PATCH 6 — exact-slot availability check. The LLM must call this
# when the parent asks about a SPECIFIC date/time (e.g. "27 მაისს 15:00")
# instead of inferring unavailability from a truncated get_available_slots
# list.
TOOL_CHECK_CONSULTATION_SLOT = "check_consultation_slot"
TOOL_LIST_PROGRAMS = "list_programs"
TOOL_GET_PROGRAM_INFO = "get_program_info"

ALLOWED_TOOL_NAMES: frozenset[str] = frozenset({
    TOOL_GET_CAMP_INFO,
    TOOL_GET_AVAILABLE_SLOTS,
    TOOL_BOOK_CONSULTATION,
    TOOL_REQUEST_MANAGER_CALLBACK,
    TOOL_SAVE_LEAD_INFO,
    TOOL_MANAGE_CONSULTATION_BOOKING,
    TOOL_SWITCH_TO_ADULT_FLOW,
    TOOL_CHECK_CONSULTATION_SLOT,
    TOOL_LIST_PROGRAMS,
    TOOL_GET_PROGRAM_INFO,
})

# ``get_camp_info`` accepts only this closed set of topics. Anything else
# is rejected by the executor (returns success=false rather than reading
# something arbitrary out of the YAML).
CAMP_INFO_TOPICS: tuple[str, ...] = (
    "price",
    "dates",
    "location",
    "conditions",
    "registration",
    "age_range",
    "all",
)


PARENT_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": TOOL_GET_CAMP_INFO,
            "description": (
                "Return authoritative facts about the 2026 camp from the "
                "knowledge base. Use whenever the parent asks about price, "
                "dates, location, conditions, registration, the age range, "
                "or wants a general overview. Never answer camp facts from "
                "memory — always call this tool. Topic must be one of: "
                "price, dates, location, conditions, registration, "
                "age_range, all."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "enum": list(CAMP_INFO_TOPICS),
                        "description": (
                            "Which fact to fetch. Use 'all' for a general "
                            "summary; otherwise pick the most specific topic."
                        ),
                    },
                },
                "required": ["topic"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": TOOL_GET_AVAILABLE_SLOTS,
            "description": (
                "Return consultation time slots from Google Calendar "
                "(Asia/Tbilisi). Call when the parent wants to talk to "
                "a consultant, asks when the manager is available, or "
                "asks specifically whether a date/time is free. "
                "Behaviour:\n"
                "- Without arguments → next ~3 free slots across the "
                "  upcoming week (default behaviour, used when the "
                "  parent hasn't named a date).\n"
                "- With `date_iso` (YYYY-MM-DD) → slots for that "
                "  specific date (and optionally `days` more days). "
                "  USE THIS when the parent named a specific date such "
                "  as '26 მაისს' / '27 მაისს' — never offer cached "
                "  slots from a different date.\n"
                "If the result is empty or the parent's exact time is "
                "not present, transparently say the slot is unavailable "
                "and offer the alternatives that came back. Do NOT use "
                "this tool to book — booking goes through "
                "book_consultation, and only after the parent confirms "
                "a specific time."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "date_iso": {
                        "type": "string",
                        "description": (
                            "Optional. Specific date in YYYY-MM-DD "
                            "format (Asia/Tbilisi). Pass when the "
                            "parent has named a date; omit otherwise."
                        ),
                    },
                    "days": {
                        "type": "integer",
                        "description": (
                            "Optional. How many weekdays to search "
                            "from `date_iso` (or from today). Defaults "
                            "to 1 when `date_iso` is given, 7 "
                            "otherwise."
                        ),
                        "minimum": 1,
                        "maximum": 14,
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": TOOL_BOOK_CONSULTATION,
            "description": (
                "Attempt to book a free consultation. Backend validates "
                "every field: name non-empty, phone in Georgian format, "
                "child_age within the camp's age range (9–17), datetime in "
                "Asia/Tbilisi, in the future, within business hours, the "
                "slot must be free, AND the parent must have explicitly "
                "named/confirmed THAT specific date and time on the same "
                "or the immediately previous turn "
                "(user_confirmed_datetime=true). ONLY call this tool when "
                "all five conditions hold. Returns success=false with a "
                "specific reason (missing_*, invalid_*, age_not_eligible, "
                "datetime_not_confirmed, datetime_in_past, "
                "outside_business_hours, slot_unavailable, calendar_error) "
                "when validation fails — read the reason and ask the "
                "parent for exactly what is missing or wrong. NEVER pick "
                "the first available slot yourself; the parent must "
                "choose or confirm one. Never claim the booking succeeded "
                "unless success=true."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Parent's full name as they provided it.",
                    },
                    "phone": {
                        "type": "string",
                        "description": (
                            "Georgian phone in any common form: 599123456, "
                            "599 12 34 56, +995 599 12 34 56."
                        ),
                    },
                    "datetime_iso": {
                        "type": "string",
                        "description": (
                            "Requested slot as ISO-8601 datetime in Asia/Tbilisi, "
                            "e.g. 2026-05-25T12:00:00+04:00."
                        ),
                    },
                    "child_age": {
                        "type": "string",
                        "description": (
                            "Child's age as a number string (e.g. '14'). "
                            "Required — backend rejects booking without it."
                        ),
                    },
                    "user_confirmed_datetime": {
                        "type": "boolean",
                        "description": (
                            "Set to true when the user has explicitly "
                            "requested or confirmed a specific date and "
                            "time — including when they chose one of "
                            "the slots you previously offered (e.g. "
                            "'13:00 საათზე იყოს', '25 მაისს 12:00-ზე', "
                            "'11-ზე იყოს', 'ეგ დრო მაწყობს'). Do NOT "
                            "set false if the user said yes to a "
                            "specific offered slot. Set false / leave "
                            "absent only when you are auto-selecting "
                            "a slot or the user only gave name/phone/"
                            "age without picking a time. Backend "
                            "rejects booking with "
                            "reason=datetime_not_confirmed when this "
                            "is not true."
                        ),
                    },
                    "notes": {
                        "type": "string",
                        "description": (
                            "Optional extra context (challenge, concern, "
                            "etc.) — stored on the lead, not used for "
                            "validation."
                        ),
                    },
                },
                "required": [
                    "name", "phone", "datetime_iso", "child_age",
                    "user_confirmed_datetime",
                ],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": TOOL_MANAGE_CONSULTATION_BOOKING,
            "description": (
                "Cancel or reschedule an EXISTING consultation booking. "
                "Call when the parent says 'გააუქმეთ', 'ჯავშანი "
                "გააუქმეთ', 'გადამიტანეთ', 'სხვა დროზე გადავიტანოთ', or "
                "asks to change a previously confirmed time. Backend "
                "needs the lead's stored calendar_event_id to safely "
                "modify the Calendar — if the ID is missing or the "
                "Calendar delete fails, the tool returns "
                "manager_handoff_required=true and you MUST NOT claim "
                "the change succeeded. For reschedule, new_datetime_iso "
                "is required and the parent must have confirmed that "
                "new time."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["cancel", "reschedule"],
                        "description": "What the parent wants to do.",
                    },
                    "old_datetime_iso": {
                        "type": "string",
                        "description": (
                            "Existing booking time if the parent named "
                            "it (e.g. '27 მაისს 12:00'). Optional — "
                            "backend uses lead.booked_datetime_iso when "
                            "this is omitted."
                        ),
                    },
                    "new_datetime_iso": {
                        "type": "string",
                        "description": (
                            "Required for reschedule. ISO-8601 datetime "
                            "in Asia/Tbilisi for the new slot."
                        ),
                    },
                    "phone": {
                        "type": "string",
                        "description": "Phone if the parent provided one this turn.",
                    },
                    "reason": {
                        "type": "string",
                        "description": "Free-text reason the parent gave.",
                    },
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": TOOL_SWITCH_TO_ADULT_FLOW,
            "description": (
                "Switch this conversation out of the PARENT (children's "
                "camp) flow into the ADULT flow. Call when the parent "
                "clearly indicates they want adult cultural evenings "
                "(ღონისძიება, საღამო, ბილეთი, კულტურული შეხვედრა, "
                "'მე ზრდასრული ვარ') and not the children's camp. After "
                "calling, briefly acknowledge and stop answering with "
                "children's-camp facts; the next user message will be "
                "re-routed to adult_flow."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {
                        "type": "string",
                        "description": "Short note on why the switch is being made.",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": TOOL_REQUEST_MANAGER_CALLBACK,
            "description": (
                "Hand off to the human manager. Call when the parent asks "
                "for a person, asks the manager to call, or refuses the "
                "self-serve flow. Phone is not required by schema because "
                "the parent may ask for the manager before giving a phone "
                "— but backend will NOT notify the manager unless a valid "
                "phone is present on the lead. If the executor returns "
                "missing_phone, ask the parent for their phone."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Parent's name if known.",
                    },
                    "phone": {
                        "type": "string",
                        "description": "Phone if provided in this turn.",
                    },
                    "notes": {
                        "type": "string",
                        "description": "Brief reason for the manager handoff.",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": TOOL_SAVE_LEAD_INFO,
            "description": (
                "Update in-memory lead fields (name / phone / child_age / "
                "challenge / notes) when the parent volunteers them. This "
                "tool DOES NOT write to Google Sheets, DOES NOT book "
                "Calendar, and DOES NOT notify the manager. Use it to "
                "remember what the parent said so you don't ask the same "
                "question twice."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "phone": {"type": "string"},
                    "child_age": {"type": "string"},
                    "challenge": {"type": "string"},
                    "notes": {"type": "string"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": TOOL_CHECK_CONSULTATION_SLOT,
            "description": (
                "Check whether a SPECIFIC consultation date/time is "
                "available. Call this whenever the parent names an "
                "exact time (e.g. '27 მაისს 15:00-ზე შეიძლება?', "
                "'27 მაისს 3 საათზე თუ არის შესაძლებელი', '12 საათზე?'). "
                "Do NOT use get_available_slots to answer such "
                "questions — that tool returns a TRUNCATED list (max 6 "
                "slots) and an exact requested time may legitimately be "
                "free while not appearing in the list. The tool returns "
                "{available, inside_business_hours, calendar_available, "
                "reason, alternative_slots[]}. Reason values: "
                "'past_datetime', 'weekend', 'outside_business_hours', "
                "'buffer_today', 'calendar_busy', 'invalid_datetime'. "
                "Branch your reply on the reason: business-hours / "
                "buffer rejection ≠ Calendar busy. This tool DOES NOT "
                "book; on a positive result, ask for any missing "
                "name/phone and use book_consultation."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "datetime_iso": {
                        "type": "string",
                        "description": (
                            "Exact requested consultation time as "
                            "ISO-8601 in Asia/Tbilisi (e.g. "
                            "2026-05-27T15:00:00+04:00)."
                        ),
                    },
                },
                "required": ["datetime_iso"],
            },
        },
    },
]


# P4-1 Task 2 — generic program tool schemas (data only). Gated by
# USE_DYNAMIC_PROGRAMS; deliberately kept OUT of PARENT_TOOLS so the
# flag-off tool surface is unchanged. Consumed by the executor/engine in
# later tasks.
DYNAMIC_PROGRAM_TOOLS: list[dict[str, Any]] = [
    {"type": "function", "function": {
        "name": TOOL_LIST_PROGRAMS,
        "description": (
            "Return the currently ACTIVE programs the company offers "
            "(program_id + Georgian name + type). Call this before answering "
            "about any program you are not certain is offered. Only programs "
            "returned here exist — never invent one."
        ),
        "parameters": {"type": "object", "properties": {}},
    }},
    {"type": "function", "function": {
        "name": TOOL_GET_PROGRAM_INFO,
        "description": (
            "Return authoritative facts about ONE program from admin config. "
            "Use for ANY question about a program other than the 2026 summer "
            "camp (which still uses get_camp_info). program_id MUST come from "
            "list_programs. topic is a free-form hint; answer ONLY from the "
            "returned facts, never from memory. If success is false, tell the "
            "user the program is unavailable and offer the manager — do not invent."
        ),
        "parameters": {"type": "object", "properties": {
            "program_id": {"type": "string", "description": "id from list_programs"},
            "topic": {"type": "string", "description": "optional free-form topic hint"},
        }, "required": ["program_id"]},
    }},
]
