"""ADULT LLM engine — OpenAI tool registry.

Mirrors the design of ``parent_tools.py``:

  * Data only. No execution logic here.
  * The LLM may propose arguments — backend always validates.
  * Closed set of tool names; anything else is rejected by the
    executor as ``unknown_tool``.

Six tools cover the adult cultural-events flow:

  1. ``get_adult_events``               — list active events
                                          (optionally filtered by age).
  2. ``get_adult_event_details``        — detail for one event.
  3. ``save_adult_lead_info``           — in-memory Lead update only.
  4. ``request_adult_manager_callback`` — Sheets + manager email +
                                          manager phone return.
  5. ``provide_adult_reservation_link`` — reservation link OR
                                          manager handoff fallback.
  6. ``switch_to_parent_flow``          — flip the conversation to
                                          PARENT (camp inquiry).
"""

from __future__ import annotations

from typing import Any

TOOL_GET_ADULT_EVENTS = "get_adult_events"
TOOL_GET_ADULT_EVENT_DETAILS = "get_adult_event_details"
TOOL_SAVE_ADULT_LEAD_INFO = "save_adult_lead_info"
TOOL_REQUEST_ADULT_MANAGER_CALLBACK = "request_adult_manager_callback"
TOOL_PROVIDE_ADULT_RESERVATION_LINK = "provide_adult_reservation_link"
TOOL_SWITCH_TO_PARENT_FLOW = "switch_to_parent_flow"
TOOL_SUBSCRIBE_TO_ADULT_EVENT_UPDATES = "subscribe_to_adult_event_updates"


ALLOWED_ADULT_TOOL_NAMES: frozenset[str] = frozenset({
    TOOL_GET_ADULT_EVENTS,
    TOOL_GET_ADULT_EVENT_DETAILS,
    TOOL_SAVE_ADULT_LEAD_INFO,
    TOOL_REQUEST_ADULT_MANAGER_CALLBACK,
    TOOL_PROVIDE_ADULT_RESERVATION_LINK,
    TOOL_SWITCH_TO_PARENT_FLOW,
    TOOL_SUBSCRIBE_TO_ADULT_EVENT_UPDATES,
})


ADULT_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": TOOL_GET_ADULT_EVENTS,
            "description": (
                "Return the currently active adult events from the "
                "admin config. Each entry includes id, title, theme, "
                "date_text, location, guest, format, price_text, "
                "reservation_url, seats_available, and min_age. When "
                "user_age is known, pass it so the executor returns "
                "only events the user is old enough for "
                "(min_age <= user_age). Never list events from memory "
                "— always call this tool."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "user_age": {
                        "type": "integer",
                        "description": (
                            "Optional. Age of the user (or their child "
                            "if the inquiry is for someone else). Pass "
                            "ONLY when explicitly known; backend "
                            "applies min_age filtering."
                        ),
                        "minimum": 0,
                        "maximum": 120,
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": TOOL_GET_ADULT_EVENT_DETAILS,
            "description": (
                "Return full details about a single event identified "
                "by id (e.g. 'poetry_evening') or by title (Georgian "
                "title, case-insensitive contains-match). Use whenever "
                "the user asks about a specific event's theme, date, "
                "location, guest, price, or reservation link. Backend "
                "looks the event up in admin_config; never invent a "
                "field that is empty in the result. If the lookup is "
                "ambiguous (no match), ask the user to clarify which "
                "event."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "event_id_or_title": {
                        "type": "string",
                        "description": (
                            "Event id (preferred) or title fragment "
                            "the user mentioned."
                        ),
                    },
                },
                "required": ["event_id_or_title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": TOOL_SAVE_ADULT_LEAD_INFO,
            "description": (
                "Update in-memory adult-lead fields (name / phone / "
                "adult_age / event_interest / preferred_event / "
                "seat_count / notes) when the user volunteers them. "
                "This tool DOES NOT write to Google Sheets, DOES NOT "
                "send manager email, and DOES NOT return a "
                "reservation link. Use it to remember what the user "
                "said so you don't re-ask. Phone is validated by the "
                "parser; invalid phones are reported back in "
                "`invalid_fields`. `adult_age` is the ADULT user's OWN "
                "age (e.g. when they say 'მე ვარ 30 წლის' / "
                "'30 წლის ვარ'). NEVER use this field for a child's "
                "age — child ages belong in the PARENT flow."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "phone": {"type": "string"},
                    "adult_age": {
                        "type": "string",
                        "description": (
                            "Adult user's OWN age as a number string "
                            "(e.g. '30'). Use ONLY when the user is "
                            "asking about events for themselves. Do "
                            "NOT use for a child's age, and DO NOT "
                            "use for a relative's age — use "
                            "`adult_target_age` for relatives."
                        ),
                    },
                    "adult_target_relation": {
                        "type": "string",
                        "description": (
                            "Free-form relation label for an event "
                            "the user is asking about on behalf of "
                            "someone else (e.g. 'და', 'ძმა', "
                            "'მეგობარი', 'დედა', 'მამა', 'მეუღლე', "
                            "'შვილი'). Use whenever the user says "
                            "'ჩემი დისთვის' / 'ჩემი ძმისთვის' / "
                            "'მეგობრისთვის' etc. — these stay in the "
                            "ADULT flow, NOT in PARENT/camp."
                        ),
                    },
                    "adult_target_age": {
                        "type": "string",
                        "description": (
                            "Age of the relative the user is asking "
                            "about (e.g. '14' for a 14-year-old "
                            "sister). Used by `get_adult_events` for "
                            "min_age filtering when set. NEVER use "
                            "for a child in the PARENT/camp flow — "
                            "child age belongs in `child_age` there."
                        ),
                    },
                    "event_interest": {
                        "type": "string",
                        "description": "Short label of what the user is interested in.",
                    },
                    "preferred_event": {
                        "type": "string",
                        "description": "Specific event id or title the user picked.",
                    },
                    "seat_count": {
                        "type": "string",
                        "description": "Number of seats / tickets the user asked about.",
                    },
                    "notes": {"type": "string"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": TOOL_REQUEST_ADULT_MANAGER_CALLBACK,
            "description": (
                "Hand the lead off to the human manager. Backend "
                "requires a valid Georgian phone number — without one, "
                "returns `missing_phone` and the LLM must ask the user "
                "for the phone. With a valid phone, backend (a) saves "
                "the lead to the Sheets `Leads` tab with segment=ADULT, "
                "(b) sends the manager-notification email, (c) returns "
                "the manager's phone number from config so the LLM can "
                "share it with the user. Idempotent per conversation: "
                "a second call returns `already_notified=true` without "
                "double-firing. ABSOLUTELY DOES NOT book Google "
                "Calendar — adult flow has no consultation booking."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "phone": {"type": "string"},
                    "event_interest": {"type": "string"},
                    "notes": {"type": "string"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": TOOL_PROVIDE_ADULT_RESERVATION_LINK,
            "description": (
                "Return the configured reservation / payment link for "
                "the given event id. Use when the user has chosen an "
                "event and explicitly wants to reserve or pay. Backend "
                "looks the event up in admin_config; "
                "  - success=true + reservation_url → share naturally;\n"
                "  - success=false + reason=link_missing → DO NOT "
                "    invent a link. Ask the user for name+phone and "
                "    call `request_adult_manager_callback`.\n"
                "  - success=false + reason=unknown_event → ask the "
                "    user to clarify which event."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "event_id": {
                        "type": "string",
                        "description": "Event id (e.g. 'poetry_evening').",
                    },
                },
                "required": ["event_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": TOOL_SUBSCRIBE_TO_ADULT_EVENT_UPDATES,
            "description": (
                "Subscribe the user to future adult/cultural-event "
                "broadcasts. Call this ONLY after the user has explicitly "
                "consented (e.g. ki/diakh/minda/gamogigzavnet/yes). "
                "The tool persists the subscriber to the Sheets `events` "
                "tab; the broadcast service later sends a private DM "
                "with full event details when the operator activates a "
                "new adult event. REQUIRES a non-empty name AND a valid "
                "Georgian phone number — without either the tool returns "
                "`missing_name` / `missing_phone` / "
                "`missing_name_and_phone` and the LLM must ask the user "
                "for the missing data. Do NOT claim subscribed status "
                "to the user until the tool returns `success=true`. "
                "Pass `source_event_id` / `source_event_title` / "
                "`source_event_link` when known so the CRM row "
                "preserves the discovery context."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "phone": {"type": "string"},
                    "source_event_id": {"type": "string"},
                    "source_event_title": {"type": "string"},
                    "source_event_link": {"type": "string"},
                    "age": {
                        "type": "string",
                        "description": (
                            "Optional. Adult user's own age when known."
                        ),
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": TOOL_SWITCH_TO_PARENT_FLOW,
            "description": (
                "Switch this conversation out of the ADULT flow back "
                "into the PARENT (children's camp) flow. Call when the "
                "user clearly indicates they are interested in the "
                "summer camp / a child's program rather than adult "
                "cultural evenings (e.g. 'ბანაკი მაინტერესებს', "
                "'12 წლის ბავშვისთვის მინდა', 'საზაფხულო ბანაკი'). "
                "After calling, briefly acknowledge — the next user "
                "message will be re-routed to parent_flow."
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
]
