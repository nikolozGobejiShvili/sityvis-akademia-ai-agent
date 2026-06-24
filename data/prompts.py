# ============================================
# SYSTEM PROMPTS — composable v3
# Composition: BASE + (PARENT or ADULT)
# Brand voice: სიტყვის აკადემია
# Voice DNA: 70% intellectual-emotional + 20% warm-human + 10% authoritative
# ============================================
#
# Migration status:
#   Phase 1 (PROMPT → .md):
#     AI prompt strings now live in app/agent/prompts/*.md and are loaded by
#     app.agent.llm.prompt_loader.load_prompt. The constants below remain as
#     backward-compatible aliases; every existing `from data.prompts import X`
#     continues to work. To edit a prompt, edit the .md file.
#
#   Phase 2 (TEMPLATE → YAML):
#     User-facing TEMPLATE strings live in app/agent/templates/*.yaml and are
#     loaded by app.agent.services.template_loader.get_template. Same alias
#     pattern.
#
#   What still lives here verbatim:
#     - OPENAI_CONTEXT_LABEL  — 10-char single-line formatting label, not a
#       substantive prompt. Per Phase 1 spec, short single-line literals stay.
#     - KNOWLEDGE_FACT defaults (event placeholders, atmosphere fallbacks)
#       — Phase 3 target.
#     - PARENT_CHALLENGE_OPTIONS  — dead empty list kept for back-compat.

from app.agent.llm.prompt_loader import load_prompt as _p
from app.agent.services.template_loader import get_template as _t

# ============================================
# SYSTEM PROMPTS
# (PROMPT — sourced from app/agent/prompts/*.md)
# ============================================

SYSTEM_PROMPT_BASE = _p("system_base")
SYSTEM_PROMPT_PARENT = _p("system_parent")
SYSTEM_PROMPT_ADULT = _p("system_adult")

# ============================================
# SEGMENT DETECTION
# (PROMPT — sourced from app/agent/prompts/detect_segment.md)
# ============================================

DETECT_SEGMENT = _p("detect_segment")

# ============================================
# START INTENT DETECTION
# Detects user's first-message intent so we can route correctly.
# (PROMPT — sourced from app/agent/prompts/detect_start_intent.md)
# ============================================

START_INTENT_DETECT = _p("detect_start_intent")

# ============================================
# PARENT FLOW — START state variants by intent
# (TEMPLATE — sourced from app/agent/templates/parent/*.yaml)
# ============================================

PARENT_WELCOME = _t("parent", "welcome")
PARENT_WELCOME_CAMP_OPENER = _t("parent", "welcome_camp_opener")
PARENT_WELCOME_WITH_CONCERN = _t("parent", "welcome_with_concern")
PARENT_PRICE_FIRST_RESPONSE = _t("parent", "price_first_response")
PARENT_PRICE_IN_FLOW = _t("parent", "price_in_flow")
PARENT_BOOK_FAST_TRACK = _t("parent", "book_fast_track")
PARENT_INFO_FIRST_RESPONSE = _t("parent", "info_first_response")

# ============================================
# PARENT FLOW — Discovery (4 layers)
# (TEMPLATE — sourced from app/agent/templates/parent/*.yaml)
# ============================================

PARENT_ASK_CHALLENGE = _t("parent", "ask_challenge")
PARENT_ASK_DEEPER = _t("parent", "ask_deeper")
PARENT_ASK_DESIRE = _t("parent", "ask_desire")

# Fallback if OpenAI generation fails for PRESENT_VALUE
PARENT_PRESENT_VALUE_FALLBACK = _t("parent", "present_value_fallback")

# PRESENT_VALUE context prompt sent to OpenAI (PROMPT — Phase 1).
PARENT_PRESENT_VALUE_CONTEXT = _p("parent_present_value")

# ============================================
# PARENT FLOW — Contact capture
# (TEMPLATE — sourced from app/agent/templates/parent/*.yaml)
# ============================================

PARENT_ASK_NAME = _t("parent", "ask_name")
PARENT_ASK_PHONE_ONLY = _t("parent", "ask_phone_only")
PARENT_ASK_NAME_RETRY = _t("parent", "ask_name_retry")
PARENT_ASK_PHONE_RETRY_INVALID = _t("parent", "ask_phone_retry_invalid")

# ============================================
# PARENT FLOW — Booking
# (TEMPLATE — sourced from app/agent/templates/parent/*.yaml)
# ============================================

PARENT_OFFER_CONSULTATION = _t("parent", "offer_consultation")
PARENT_BOOKING_CONFIRMED = _t("parent", "booking_confirmed")
PARENT_DONE_RESPONSE = _t("parent", "done_response")
PARENT_SLOT_UNAVAILABLE = _t("parent", "slot_unavailable")
PARENT_CLARIFY_SLOT_CHOICE = _t("parent", "clarify_slot_choice")
PARENT_BOOKING_FAILED = _t("parent", "booking_failed")

PARENT_FOLLOWUP = _t("parent", "followup")

# Kept for backwards compatibility — empty list (no emoji-checkbox UX anymore)
PARENT_CHALLENGE_OPTIONS: list[str] = []

# ============================================
# PARENT FLOW — Internal OpenAI templates
# (TEMPLATE — sourced from app/agent/templates/parent/internal.yaml)
# ============================================

PARENT_CONTEXT = _t("parent", "context")
PARENT_FALLBACK_RESPONSE = _t("parent", "fallback_response")
PARENT_SUMMARY_FALLBACK = _t("parent", "summary_fallback")

# ============================================
# ADULT FLOW MESSAGES
# (TEMPLATE — sourced from app/agent/templates/adult/*.yaml)
# ============================================

ADULT_WELCOME = _t("adult", "welcome")
ADULT_EVENT_DETAILS = _t("adult", "event_details")
ADULT_SEND_BOOKING = _t("adult", "send_booking")
ADULT_FOLLOWUP = _t("adult", "followup")

# ============================================
# GENERAL MESSAGES
# (TEMPLATE — sourced from app/agent/templates/common/*.yaml)
# ============================================

UNCLEAR_ROUTING = _t("common", "unclear_routing")
ERROR_MESSAGE = _t("common", "error_message")

# ============================================
# MANAGER NOTIFICATIONS
# (NOTIFICATION_TEMPLATE — sourced from app/agent/templates/notifications/manager.yaml)
# ============================================

MANAGER_EMAIL_SUBJECT = _t("notifications", "email_subject")
MANAGER_EMAIL_BODY = _t("notifications", "email_body")
MANAGER_WHATSAPP_BODY = _t("notifications", "whatsapp_body")

# Conversation summary prompt sent to OpenAI (PROMPT — Phase 1).
SUMMARY_PROMPT = _p("summary")

# ============================================
# COMMENT INTENT DETECTION
# (PROMPT — sourced from app/agent/prompts/detect_comment_intent.md)
# ============================================

COMMENT_INTENT_PROMPT = _p("detect_comment_intent")

# ============================================
# COMMENT REPLIES
# (TEMPLATE — sourced from app/agent/templates/comments/replies.yaml)
# ============================================

COMMENT_REPLY_DM_SENT = _t("comments", "reply_dm_sent")
COMMENT_REPLY_FALLBACK = _t("comments", "reply_fallback")
COMMENT_FOLLOWUP_REPLY = _t("comments", "followup_reply")

# ============================================
# ADULT FLOW INTERNAL TEMPLATES
# (TEMPLATE — sourced from app/agent/templates/adult/*.yaml)
# ============================================

ADULT_CLARIFY_EVENT = _t("adult", "clarify_event")
ADULT_BOOKING_FORWARDED = _t("adult", "booking_forwarded")
ADULT_NO_EVENTS = _t("adult", "no_events")
ADULT_EVENT_LIST_ITEM = _t("adult", "event_list_item")

# ADULT KNOWLEDGE_FACT defaults — not migrated in Phase 2 (Phase 3 target).
ADULT_EVENT_PLACEHOLDER = "დასაზუსტებელია"
ADULT_EVENT_NAME_PLACEHOLDER = "ღონისძიება"
ADULT_DEFAULT_ATMOSPHERE = "დახვეწილი, მშვიდი და პრემიუმ ატმოსფერო"
ADULT_DEFAULT_EVENT_NAME = "კულტურული საღამო"
ADULT_DEFAULT_EVENT_THEME = "კულტურული შეხვედრა"
ADULT_DEFAULT_EVENT_GUEST = "სპეციალური სტუმარი"
ADULT_DEFAULT_EVENT_LOCATION = "პრემიუმ სივრცე"
ADULT_DEFAULT_EVENT_ATMOSPHERE_TBD = "მშვიდი, დახვეწილი და შინაარსიანი გარემო"

ADULT_DONE_CONTEXT = _t("adult", "done_context")
ADULT_EVENT_CONTEXT = _t("adult", "event_context")
ADULT_SUMMARY_FALLBACK = _t("adult", "summary_fallback")

# ============================================
# MANAGER NOTIFICATION HELPERS
# (NOTIFICATION_TEMPLATE — sourced from app/agent/templates/notifications/manager.yaml)
# ============================================

MANAGER_SMS_BODY = _t("notifications", "sms_body")
MANAGER_DETAILS_PARENT = _t("notifications", "details_parent")
MANAGER_DETAILS_ADULT = _t("notifications", "details_adult")
MANAGER_SHORT_PARENT = _t("notifications", "short_parent")
MANAGER_SHORT_ADULT = _t("notifications", "short_adult")

BOOKING_TEXT_YES = _t("notifications", "booking_text_yes")
BOOKING_TEXT_NO = _t("notifications", "booking_text_no")

# ============================================
# CALENDAR
# (CALENDAR_TEMPLATE — sourced from app/agent/templates/calendar/event.yaml)
# ============================================

CALENDAR_EVENT_SUMMARY = _t("calendar", "summary")
CALENDAR_EVENT_DESCRIPTION = _t("calendar", "description")
CALENDAR_SLOT_CHOICE_PROMPT = _t("calendar", "slot_choice_prompt")
CALENDAR_OPTIONS_SEPARATOR = _t("calendar", "options_separator")

# ============================================
# OPENAI CONTEXT LABEL
# Short single-line formatting prefix, not a substantive prompt.
# Per Phase 1 spec, kept as Python literal — no .md file.
# ============================================

OPENAI_CONTEXT_LABEL = "კონტექსტი:"
