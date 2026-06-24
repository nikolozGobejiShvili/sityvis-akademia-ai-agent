"""ADULT LLM engine — cultural-events flow tool-calling loop.

Mirrors the design of ``parent_llm_engine`` (P3-C SAFE):

  * Builds a compact system prompt from ``system_adult_v1.md`` plus
    adult sales policy context.
  * Adds the current lead context (name, phone, age, interest).
  * Appends the last ten conversation turns plus the current user
    message.
  * Asks OpenAI to either reply directly or call one of the closed-set
    tools registered in ``adult_tools.ADULT_TOOLS``.

Tool execution runs through ``AdultToolExecutor`` (the security
boundary). The engine itself never books Calendar (there is no
booking tool here), never writes Sheets directly, never sends the
manager email directly — it only orchestrates the conversation.

Failure mode is QUIET: any exception or empty final response returns
``""`` so ``conversation_service`` can fall back to the legacy
``adult_flow.handle`` state machine without crashing the webhook.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.agent.llm.prompt_loader import load_prompt
from app.agent.tools.adult_tool_executor import AdultToolExecutor, serialize_result
from app.agent.tools.adult_tools import (
    ADULT_TOOLS,
    TOOL_SUBSCRIBE_TO_ADULT_EVENT_UPDATES,
)
from app.config import settings
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.services import openai_service

logger = logging.getLogger(__name__)


MAX_TOOL_ITERATIONS = 5
HISTORY_WINDOW = 10
DEFAULT_MAX_TOKENS = 500
DEFAULT_TEMPERATURE = 0.7


# =========================================================================
# Off-Topic Guard — deterministic scope check (added 2026-06-02)
# =========================================================================
#
# Live observation: the ADULT engine answered general-knowledge questions
# ("ვინაა ელტონ ჯონი?", "მუფასა სიმბას მამა თუ დედა?") that have nothing
# to do with the brand's configured events. The bot is NOT a general
# ChatGPT — it is a bounded business assistant for სიტყვის აკადემია.
#
# Fix shape: deterministic guard BEFORE OpenAI is called. The guard
# compares the user message against
#   (a) configured event content (titles, guests, themes, formats,
#       locations, descriptions) sourced live from admin_config;
#   (b) a closed-set list of in-scope domain stems (event vocab,
#       reservation vocab, manager vocab, age/conversation vocab);
#   (c) general-knowledge question patterns ("ვინაა X?", "ვინ არის X?",
#       "რა არის X?", relation questions with "?").
#
# Decision tree:
#   * Length < 10 chars      → None (short replies / acks skip guard).
#   * Configured event match → None (user is asking about a real event).
#   * In-scope stem match    → None (user is asking about brand domain).
#   * General-knowledge ptn  → return deterministic redirect.
#   * Otherwise              → None (ambiguous; let the LLM handle).

# In-scope domain stems. Any substring hit means the message is on-topic
# enough for the LLM to handle (it may still call tools and answer
# from configured data). Conservative: false-positives here only mean
# the LLM gets to run; the system-prompt OFF-TOPIC rule is the second
# line of defence.
_ADULT_IN_SCOPE_STEMS: tuple[str, ...] = (
    # Brand
    "სიტყვის აკადემი", "აკადემი",
    # Events
    "ღონისძიებ", "საღამო", "შეხვედრ", "კონცერტ",
    # Categories
    "კულტურულ", "ლიტერატურ", "პოეტურ",
    "პოეზი", "მუსიკ", "წიგნ", "კლუბ", "ფესტივალ", "გამოფენ",
    # Booking
    "ბილეთ", "ჯავშნ", "ჯავშან", "რეგისტრაც", "გადახდ",
    # Practical event-facts vocab.
    # NOTE: use "ფასი" (4 chars) not "ფას" (3 chars) — short "ფას" is a
    # substring of "მუფასა" / "ანდრეფასტი" etc. and produces
    # false-positive in-scope matches that defeat the off-topic guard.
    "ფასი", "ფასს", "ფასე", "ღირებ",
    "ლოკაცი", "თარიღ", "ასაკი", "ადგილ", "მისამართ",
    "სად ტარდე", "როდის",
    # Manager / contact
    "მენეჯერ", "კონტაქტ", "კავშირ", "დარეკ", "ნომერ",
    # Conversational
    "გამარჯობა", "სალამი", "მადლობა", "მაინტერესებ",
    "მინდა", "გნებავთ",
    # Age phrasing
    "წლის", "წელი", "ბრძანდები",
    # Camp / child cues — handled separately by _user_wants_parent_flow
    # but also recognised as in-scope so the off-topic guard doesn't
    # fire on them by mistake.
    "ბანაკ", "ბავშვ", "შვილ",
    # Subscription notification delivery (A-1/A-2, 2026-06-12) — a
    # subscriber's „where will the notification arrive?" question is
    # in-scope; the off-topic guard must NEVER redirect it with the
    # forbidden „ამ კითხვაზე ვერ დაგეხმარებით". The deterministic
    # delivery handler answers it before the guard runs; these stems are
    # a safety net so any missed phrasing falls to the LLM (graceful),
    # never the redirect.
    "შეტყობინ", "შემატყობ",
)

# General-knowledge "who is X / what is X" interrogatives. The guard
# only fires when one of these matches AND nothing in-scope is present.
_OFFTOPIC_WHO_PATTERNS: tuple[str, ...] = (
    "ვინაა", "ვინ არის", "ვინ იყო", "ვინ იქნება",
    "ვინ წერდა", "ვინ ცეკვავდა", "ვინ მღეროდა",
)
_OFFTOPIC_WHAT_PATTERNS: tuple[str, ...] = (
    "რა არის", "რა იყო", "რა იქნება",
)
_OFFTOPIC_ABOUT_PATTERN_OPEN = "მითხარი"
_OFFTOPIC_ABOUT_PATTERN_TAIL = "შესახებ"

# Generic-knowledge category stems — if the message says one of these
# AND no in-scope keyword is present, fire the redirect even without
# the "ვინ/რა" interrogative (a plain statement like „კლიმატის ცვლილება
# საინტერესოა" should also redirect).
_OFFTOPIC_TOPIC_STEMS: tuple[str, ...] = (
    "კლიმატ", "გლობალუ", "მათემატიკ", "ფიზიკ", "ქიმი", "ბიოლოგი",
    "ფილოსოფი", "ფსიქოლოგი",
    "პოლიტიკ", "არჩევნებ", "ომი",
    # Fictional characters / pop figures the live bug surfaced.
    "მუფასა", "სიმბ", "ჰარი პოტერ", "გენდალფ", "ბეტმენ",
    # Generic "celebrity?" stems
    "ცნობილი მსახიობ", "ცნობილი მომღერალ",
)

# Two off-topic redirect variants. The "name not in program" version
# is used when the message is a clear "who is X?" question; the
# generic version is used for "what is X?" / topic statements.
_OFFTOPIC_REPLY_NAME_NOT_CONFIGURED: str = (
    "ეს კითხვა ჩვენი პროგრამის გარეთაა. "
    "თუ გსურთ, ზრდასრულთა კულტურულ ღონისძიებებს სიამოვნებით გაგაცნობთ."
)
_OFFTOPIC_REPLY_GENERIC: str = (
    "ამ კითხვაზე ვერ დაგეხმარებით.\n"
    "თუ ჩვენს ღონისძიებებზე გაქვთ კითხვა, სიამოვნებით გიპასუხებთ."
)


# Wording Fix (2026-06-11) — BUG 2. A subscribed user asking WHERE/HOW the
# subscription notification will arrive („და სად მომივა შეტყობინება
# მესენჯერში?") is a LEGITIMATE question — it must NOT be redirected as
# off-topic and must NOT re-subscribe. This deterministic handler answers
# it directly (platform-aware), BEFORE the subscription / off-topic / LLM
# layers. The system prompt is intentionally NOT changed.
# A-1/A-2 broadening (2026-06-12). The old list was word-order-locked and
# covered only 3/10 realistic phrasings — „შეტყობინება სად მომივა?"
# (noun-then-verb) missed and hit the FORBIDDEN off-topic redirect. The
# detector below is morphology / word-order tolerant via stem groups, but
# kept NARROW so it does not hijack unrelated questions:
#   * a bare notification word („შემატყობინეთ") or a bare „სად" is NOT a
#     delivery question on its own;
#   * a delivery question is (where/how + subject-or-arrival) OR
#     (channel + arrival) OR („აქ" standalone + write/arrival + „?").
# This preserves the subscription-consent path („კი გამომიგზავნეთ",
# „შემატყობინეთ") and location/price questions („სად ტარდება?",
# „ფასი რა არის?"), which must NOT be intercepted here.
_DELIVERY_WHERE_HOW_STEMS: tuple[str, ...] = (
    "სად", "როგორ", "რანაირად", "რომელ",
)
_DELIVERY_SUBJECT_STEMS: tuple[str, ...] = (
    "შეტყობინ",   # შეტყობინება / შეტყობინებას
    "შემატყობ",   # შემატყობინებთ (you-will-notify-me)
    "დეტალ",      # დეტალები / დეტალებს
    "ლინკ", "ბმულ",
)
_DELIVERY_ARRIVAL_STEMS: tuple[str, ...] = (
    "მომივა", "მოვა", "მოდის", "მივიღებ", "ვნახავ",
    "გამომიგზავნ", "მომწერ", "გავიგებ", "შემატყობ",
)
_DELIVERY_CHANNEL_STEMS: tuple[str, ...] = (
    "მესენჯ", "მეილ", "ინსტაგრამ", "ინსტა", "დაირექტ", "direct",
)
_DELIVERY_HERE_ARRIVAL_STEMS: tuple[str, ...] = (
    "მომწერ", "მომივა", "მოვა", "მოდის", "მივიღებ", "ვნახავ", "გამომიგზავნ",
)
_DELIVERY_ENGLISH_PATTERNS: tuple[str, ...] = (
    "where will i get notified",
    "where will the notification",
    "how will i get notified",
)

_NOTIFICATION_DELIVERY_REPLY_MESSENGER: str = (
    "შეტყობინებას სწორედ აქ, Messenger-ში მიიღებთ — ამავე ჩატში. "
    "როცა ახალი ზრდასრულთა ღონისძიება დაემატება, დეტალებსა და "
    "ბილეთის ბმულს გამოგიგზავნით."
)
_NOTIFICATION_DELIVERY_REPLY_INSTAGRAM: str = (
    "შეტყობინებას სწორედ აქ, Instagram-ის პირად შეტყობინებაში მიიღებთ — "
    "ამავე ჩატში. როცა ახალი ზრდასრულთა ღონისძიება დაემატება, დეტალებსა "
    "და ბილეთის ბმულს გამოგიგზავნით."
)
_NOTIFICATION_DELIVERY_REPLY_WHATSAPP: str = (
    "შეტყობინებას სწორედ აქ, WhatsApp-ში მიიღებთ — ამავე ჩატში. "
    "როცა ახალი ზრდასრულთა ღონისძიება დაემატება, დეტალებსა და "
    "ბილეთის ბმულს გამოგიგზავნით."
)


def _has_standalone_here(low: str) -> bool:
    """True when „აქ" (here) appears as a standalone token, not as a
    substring of „აქედან" / „აქვს" / „აქა" etc."""
    return any(tok == "აქ" for tok in re.split(r"[\s\?\!\.,;:()]+", low))


def _is_notification_delivery_question(message: str) -> bool:
    low = (message or "").casefold()
    if not low:
        return False
    # English explicit patterns.
    if any(p in low for p in _DELIVERY_ENGLISH_PATTERNS):
        return True
    has_where_how = any(s in low for s in _DELIVERY_WHERE_HOW_STEMS)
    has_subject = any(s in low for s in _DELIVERY_SUBJECT_STEMS)
    has_arrival = any(s in low for s in _DELIVERY_ARRIVAL_STEMS)
    has_channel = any(s in low for s in _DELIVERY_CHANNEL_STEMS)
    # Branch 1 — „where/how" + (notification subject OR arrival verb).
    #   „შეტყობინება სად მომივა?" / „დეტალებს სად გამომიგზავნით?" /
    #   „სად შემატყობინებთ?" / „სად ვნახავ შეტყობინებას?" / „სად გავიგებ?".
    if has_where_how and (has_subject or has_arrival):
        return True
    # Branch 2 — a channel is named + an arrival verb (no „where" needed):
    #   „მესენჯერში მომივა შეტყობინება?" / „მეილზე მოდის თუ აქ?".
    if has_channel and has_arrival:
        return True
    # Branch 3 — „აქ" (here, standalone) + write/arrival verb in a
    #   question: „აქ მომწერთ?".
    if "?" in message and _has_standalone_here(low) and any(
        s in low for s in _DELIVERY_HERE_ARRIVAL_STEMS
    ):
        return True
    return False


def _maybe_handle_notification_delivery_question(
    user_message: str, platform: str,
) -> str | None:
    """Answer „where/how will the subscription notification arrive?"
    directly (platform-aware). Returns None when the message is not such a
    question. Never re-subscribes / writes anything (BUG 2)."""
    if not _is_notification_delivery_question(user_message):
        return None
    p = (platform or "").lower()
    if "insta" in p:
        return _NOTIFICATION_DELIVERY_REPLY_INSTAGRAM
    if "whats" in p or "wa" == p:
        return _NOTIFICATION_DELIVERY_REPLY_WHATSAPP
    return _NOTIFICATION_DELIVERY_REPLY_MESSENGER


def _gather_configured_adult_terms() -> set[str]:
    """Collect every casefold'ed term from admin_config that could
    plausibly identify an event.

    Returns a set of lowercased substrings — titles, guests, themes,
    formats, descriptions, locations. Short tokens (< 3 chars) are
    dropped so common 1–2 character word fragments don't false-match.
    Failures are swallowed; the worst case is "no configured terms"
    which makes the off-topic guard slightly stricter — safe.
    """
    out: set[str] = set()
    try:
        from app.services import admin_config_service
        for event in admin_config_service.get_adult_events():
            for field in ("title", "guest", "theme", "format",
                          "location", "description"):
                value = (event.get(field) or "").strip().casefold()
                if value and len(value) >= 3:
                    out.add(value)
            # Also split title/guest into word tokens — a guest's first
            # name alone ("ელტონ" without "ჯონი") should still match.
            for field in ("title", "guest"):
                value = (event.get(field) or "").strip().casefold()
                for token in value.split():
                    token = token.strip(",.!?;:()")
                    if len(token) >= 3:
                        out.add(token)
    except Exception:
        return out
    return out


def _maybe_adult_offtopic_reply(
    user_message: str, conversation: Conversation,
) -> str | None:
    """Deterministic off-topic guard. Returns a redirect string for
    clear out-of-scope queries; ``None`` otherwise.

    Runs BEFORE OpenAI. Keeps the bot bounded to სიტყვის აკადემიის
    cultural events. See the module-level commentary above for the
    decision tree.

    The guard is intentionally conservative — it errs on the side of
    letting the LLM handle ambiguous cases. False-negatives (off-topic
    questions that slip through) get a second pass at the system-prompt
    OFF-TOPIC rule. False-positives (in-scope questions that get
    redirected) are the cost we are NOT willing to pay, so the in-scope
    stem list is generous and the message-length floor (≥ 10 chars)
    excludes short conversational acks.
    """
    text = (user_message or "").strip().casefold()
    if not text or len(text) < 10:
        return None

    # 0. A subscription delivery question („where/how will the
    # notification / details / link arrive?") is ALWAYS in-scope and is
    # answered by the dedicated handler (A-1/A-2, 2026-06-12). In the live
    # flow that handler runs BEFORE this guard, but keeping the guard
    # delivery-aware makes the „never redirect a delivery question"
    # invariant hold for any direct caller too (e.g. „დეტალებს სად
    # გამომიგზავნით?" has no notification stem but is still a delivery
    # question).
    if _is_notification_delivery_question(user_message):
        return None

    # 1. Configured-event content match → in-scope. Even a generic
    # "ვინაა X?" is fine if X is a configured guest / title.
    configured_terms = _gather_configured_adult_terms()
    for term in configured_terms:
        if term and term in text:
            return None

    # 2. In-scope domain stem match → in-scope.
    for stem in _ADULT_IN_SCOPE_STEMS:
        if stem in text:
            return None

    # 3. General-knowledge interrogative pattern → redirect.
    if any(p in text for p in _OFFTOPIC_WHO_PATTERNS):
        return _OFFTOPIC_REPLY_NAME_NOT_CONFIGURED

    if any(p in text for p in _OFFTOPIC_WHAT_PATTERNS):
        return _OFFTOPIC_REPLY_GENERIC

    if _OFFTOPIC_ABOUT_PATTERN_OPEN in text and _OFFTOPIC_ABOUT_PATTERN_TAIL in text:
        return _OFFTOPIC_REPLY_GENERIC

    # 4. Direct off-topic category stems → redirect.
    if any(stem in text for stem in _OFFTOPIC_TOPIC_STEMS):
        return _OFFTOPIC_REPLY_GENERIC

    # 5. Relation question without configured-event context: covers
    # "X-ის მამა / დედა / ცოლი / ქმარი ვინ არის?" / "მამაა თუ დედა?".
    if "?" in user_message and any(
        rel in text for rel in ("მამაა", "დედაა", "მამა თუ", "დედა თუ")
    ):
        return _OFFTOPIC_REPLY_GENERIC

    return None


# Trigger phrases that indicate the user wants the PARENT (children's
# camp) flow rather than adult events. The engine checks these BEFORE
# calling OpenAI so the switch is deterministic and cheap.
#
# ADULT Context Routing Fix (2026-06-02): a child / sibling mention
# alone is NOT enough to trigger the switch. The user can ask about
# adult cultural events on behalf of a child — that's still ADULT.
# `_ADULT_EVENT_SIGNALS` below short-circuits the switch when the
# user's message also names an adult-event context.
#
# Live QA Patch (2026-06-05) — Bug 2 tightening: soft cues
# „ჩემი შვილის" / „შვილისთვის მინდა" / „ბავშვისთვის მინდა" are no
# longer triggers. In the ADULT flow, bare „ჩემი შვილისთვის" means
# „an adult event for my child" and must be handled via the
# relative-capture + age-question path, NOT by auto-switching to
# camp. Only HARD camp markers trigger the switch.
_PARENT_SWITCH_KEYWORDS: tuple[str, ...] = (
    "ბანაკის შესახებ მითხარი",
    "ბანაკის შესახებ",
    "საზაფხულო ბანაკი",
    "საზაფხულო ბანაკ",
    "ბანაკ",  # broad — covers "ბანაკი", "ბანაკში", "ბანაკის"
    "ბავშვთა პროგრამა",
    "ბავშვების პროგრამა",
)

# Keywords that, alone, prove camp intent regardless of adult-event
# signals. These are the "hard" camp markers — if the user wrote
# „ბანაკი" or „საზაფხულო", they want camp even if they also said
# „კულტურული".
_HARD_CAMP_KEYWORDS: frozenset[str] = frozenset({
    "ბანაკის შესახებ მითხარი",
    "ბანაკის შესახებ",
    "საზაფხულო ბანაკი",
    "საზაფხულო ბანაკ",
    "ბანაკ",
    "ბავშვთა პროგრამა",
    "ბავშვების პროგრამა",
})

# Adult-event vocabulary. When ANY of these appear in the message, a
# „child / sibling" cue alone does NOT trigger the PARENT switch — the
# user is asking about an adult event on behalf of someone else.
_ADULT_EVENT_SIGNALS: tuple[str, ...] = (
    "ღონისძიებ",   # ღონისძიება, ღონისძიების, ღონისძიებებზე
    "საღამო",
    "კულტურულ",   # კულტურული, კულტურულ საღამოზე
    "კონცერტ",
    "ლიტერატურ",
    "პოეტურ",
    "პოეზი",
    "ბილეთ",
)

# A child-age pattern like "12 წლის ბავშვისთვის" / "15 წლის შვილისთვის".
# We don't switch on adult ages here (the engine handles those via the
# normal LLM tool flow).
_CHILD_AGE_HINT_RE = re.compile(
    r"\b(\d{1,2})\s*წლის\s+(ბავშვ|შვილ)",
)


def _user_wants_parent_flow(message: str) -> bool:
    """Heuristic — does the inbound message look like a camp inquiry?

    Decision tree:
      * Empty / no keywords        → False.
      * Hard camp keyword present  → True (camp wins even with adult
        signal — the user explicitly said „ბანაკი").
      * Soft cue („ჩემი შვილის" /
        „შვილისთვის მინდა" /
        „ბავშვისთვის მინდა") + no
        adult-event signal         → True.
      * Soft cue + adult-event
        signal („კულტურული საღამო",
        „ღონისძიება", etc.)        → False (stays ADULT — the user is
        asking about adult events on behalf of someone).
      * Age 9–17 + ბავშვ/შვილ +
        no adult-event signal      → True.
      * Otherwise                  → False.
    """
    text = (message or "").strip().lower()
    if not text:
        return False

    has_adult_signal = any(sig in text for sig in _ADULT_EVENT_SIGNALS)

    for kw in _PARENT_SWITCH_KEYWORDS:
        if kw not in text:
            continue
        if kw in _HARD_CAMP_KEYWORDS:
            return True
        # Soft cue: child/relative mention without a hard camp word.
        # If the user ALSO named an adult-event signal, keep the
        # conversation in ADULT and let the LLM clarify the target.
        if has_adult_signal:
            continue
        return True

    # Live QA Patch (2026-06-05) — Bug 2 tightening: bare „N წლის
    # ბავშვისთვის" without a hard camp keyword no longer auto-switches
    # to PARENT. The ADULT engine asks the relative's age and stays in
    # the adult-event flow; the LLM can confirm camp intent later if
    # the user names „ბანაკი" explicitly.
    return False


# =========================================================================
# Relative-target intent — deterministic capture (added 2026-06-02)
# =========================================================================
#
# „ჩემი დისთვის" / „ჩემი ძმისთვის" / „მეგობრისთვის" / „დედისთვის" /
# „მამისთვის" / „მეუღლისთვის" — when the user says any of these in the
# ADULT flow, the inquiry is for a relative, NOT the user themselves.
# The relation label belongs in `lead.adult_target_relation`; the
# relative's age (when given inline, e.g. „ჩემი 14 წლის დისთვის") belongs
# in `lead.adult_target_age`.
#
# Detection runs BEFORE the LLM so the context block already reflects
# the capture; the LLM is also instructed via prompt to call
# `save_adult_lead_info(adult_target_relation=..., adult_target_age=...)`
# whenever it sees these cues.

_ADULT_RELATIVE_PATTERNS: tuple[tuple[str, str], ...] = (
    # (substring needle in message, canonical relation label saved on lead)
    ("მეუღლისთვის", "მეუღლე"),
    ("მეუღლის",     "მეუღლე"),
    ("მეგობრისთვის", "მეგობარი"),
    ("მეგობრის",     "მეგობარი"),
    ("დედისთვის",    "დედა"),
    ("მამისთვის",    "მამა"),
    ("ძმისთვის",     "ძმა"),
    ("ძმის",         "ძმა"),
    ("დისთვის",      "და"),
    ("ოჯახის წევრისთვის", "ოჯახის წევრი"),
    # Live QA Patch (2026-06-05) — Bug 2: „შვილისთვის" /
    # „ბავშვისთვის" are now also captured here. Bare „ჩემი
    # შვილისთვის" in the ADULT flow no longer auto-switches to PARENT;
    # the relative-capture records the relation so the follow-up
    # question can ask the child's age, and the LLM offers events that
    # match. Hard camp keyword („ბანაკი" / „საზაფხულო") still wins
    # via `_user_wants_parent_flow`.
    ("შვილისთვის",   "შვილი"),
    ("შვილის",       "შვილი"),
    ("ბავშვისთვის",  "ბავშვი"),
    # B-1 fix (2026-06-12) — DATIVE forms „ჩემ შვილს უნდა" / „ბავშვს
    # უნდა" were missed (genitive-only above), so adult-for-child was
    # LLM-luck (the live „inconsistent on one account" symptom). Add the
    # dative needles so the relation is captured deterministically and a
    # known `child_age` is reused. NOTE: „შვილს" is NOT a substring of
    # „შვილის"/„შვილისთვის" (those have the extra „ი"), and „ბავშვს" is
    # NOT a substring of „ბავშვის"/„ბავშვისთვის", so these never shadow
    # the genitive captures above. „შვილსაც" contains „შვილს" → covered.
    ("შვილს",        "შვილი"),
    ("ბავშვს",       "ბავშვი"),
)

# Optional age inline, e.g. „ჩემი 14 წლის დისთვის".
_RELATIVE_AGE_HINT_RE = re.compile(r"(\d{1,2})\s*წლის")

# The user's OWN age, e.g. „მე ვარ 30 წლის" / „ჩემი ასაკია 30 წლის". An age
# bound to a self-reference is the USER'S adult age, NOT the relative/child's —
# so a mixed „ჩემთვის და ჩემი შვილისთვის ... მე ვარ 30 წლის" must not store 30
# as adult_target_age (2026-06-24 surgical fix). „ჩემი 14 წლის დისთვის" has no
# self-age marker, so the relative age is still captured normally.
_SELF_OWN_AGE_RE = re.compile(r"(?:მე\s+ვარ|ჩემი\s+ასაკი(?:ა)?)\s*(\d{1,2})\s*წლ")

# Relation labels that mean „the user's own child" — the ONLY relations for
# which a known PARENT `child_age` may be reused as `adult_target_age`.
_ADULT_CHILD_RELATIONS: frozenset[str] = frozenset({"შვილი", "ბავშვი"})


def _looks_like_child_age(value: str) -> bool:
    """True when ``value`` is a plausible 1–2 digit child age."""
    s = (value or "").strip()
    if not s.isdigit():
        return False
    try:
        n = int(s)
    except ValueError:
        return False
    return 1 <= n <= 20


# B4 fix (2026-06-13) — explicit SELF-reference markers. When the user
# corrects the target back to themselves („არა, ჩემთვის" / „მე მინდა"), a
# previously-captured child/relative target must be cleared. Only fires when
# the message carries NO relative cue, so „ჩემი შვილისთვის" / „ჩემ შვილს" /
# „ბავშვს" still mean the child.
_ADULT_SELF_REFERENCE_MARKERS: tuple[str, ...] = (
    "ჩემთვის", "მე მინდა", "მე მაინტერესებს", "ჩემთან",
)


def _is_adult_self_reference(text: str) -> bool:
    return any(m in text for m in _ADULT_SELF_REFERENCE_MARKERS)


def _has_adult_relative_cue(text: str) -> bool:
    return any(needle in text for needle, _label in _ADULT_RELATIVE_PATTERNS)


def _maybe_capture_adult_target(user_message: str, lead: Lead) -> None:
    """Pre-LLM deterministic capture of „for my X (age Y)" cues.

    Mutates `lead.adult_target_relation` / `lead.adult_target_age` when
    a relative cue is detected. NEVER overwrites a non-empty existing
    value (except an explicit SELF-revert — see B4 below). NEVER touches
    `lead.child_age` or `lead.adult_age`. Safe to call on every turn —
    short-circuits when the lead already has both values OR when the
    message has no relative cue.
    """
    if lead is None:
        return
    text = (user_message or "").strip().lower()
    if not text:
        return

    existing_rel = (getattr(lead, "adult_target_relation", "") or "").strip()
    existing_age = (getattr(lead, "adult_target_age", "") or "").strip()

    # B4 fix (2026-06-13): explicit self-reference reverts a previously-set
    # child/relative target back to SELF — but only when the message has NO
    # relative cue (so „ჩემი შვილისთვის" / „ჩემ შვილს" / „ბავშვს" still mean
    # the child). Clears the target fields; never touches child_age/adult_age.
    if _is_adult_self_reference(text) and not _has_adult_relative_cue(text):
        if (existing_rel or existing_age) and hasattr(lead, "adult_target_relation"):
            lead.adult_target_relation = ""
            lead.adult_target_age = ""
            logger.info(
                "[adult_llm_engine] B4 self-revert: cleared adult target to self",
            )
        return

    if existing_rel and existing_age:
        return

    detected_relation: str | None = None
    for needle, label in _ADULT_RELATIVE_PATTERNS:
        if needle in text:
            detected_relation = label
            break

    if detected_relation is None:
        return

    if not existing_rel and hasattr(lead, "adult_target_relation"):
        lead.adult_target_relation = detected_relation
        logger.info(
            "[adult_llm_engine] captured adult_target_relation=%s",
            detected_relation,
        )

    # Mixed self+child intent fix (2026-06-24): if the message states the
    # USER'S OWN age („მე ვარ 30 წლის"), that age belongs to the user — record
    # it as `adult_age` (kept separate from child_age) and NEVER attribute it to
    # the relative target below. Pure „ჩემი 14 წლის დისთვის" has no self-age
    # marker, so `self_own_age` stays None and the relative age is captured as
    # before.
    self_own_age: str | None = None
    m_self = _SELF_OWN_AGE_RE.search(text)
    if m_self:
        try:
            n_self = int(m_self.group(1))
        except (TypeError, ValueError):
            n_self = -1
        if 0 <= n_self <= 120:
            self_own_age = str(n_self)
            if (
                hasattr(lead, "adult_age")
                and not (getattr(lead, "adult_age", "") or "").strip()
            ):
                lead.adult_age = self_own_age
                logger.info(
                    "[adult_llm_engine] captured own adult_age=%s "
                    "(self+relative mixed intent)", self_own_age,
                )

    if not existing_age:
        target_age: str | None = None
        for m in _RELATIVE_AGE_HINT_RE.finditer(user_message or ""):
            # Skip an age that is the user's OWN stated age, not the relative's.
            if self_own_age is not None and m.group(1) == self_own_age:
                continue
            target_age = m.group(1)
            break
        if target_age is not None:
            try:
                age_int = int(target_age)
            except (TypeError, ValueError):
                age_int = -1
            if 0 <= age_int <= 120 and hasattr(lead, "adult_target_age"):
                lead.adult_target_age = str(age_int)
                logger.info(
                    "[adult_llm_engine] captured adult_target_age=%s",
                    age_int,
                )

    # State Reuse Fix (2026-06-11) — BUG 1. When the relative is the
    # user's OWN child and we ALREADY know that child's age from the
    # PARENT/camp flow, reuse it instead of re-asking „თქვენი შვილი
    # რამდენი წლისაა?". Only for the SAME child: an explicit „სხვა
    # შვილ…" (a DIFFERENT child) is excluded so the new child's age is
    # asked. Copies child_age → adult_target_age; NEVER touches
    # child_age or adult_age (they coexist). Generic + state-based.
    target_age_now = (getattr(lead, "adult_target_age", "") or "").strip()
    if (
        not target_age_now
        and detected_relation in _ADULT_CHILD_RELATIONS
        and "სხვა" not in text
        and hasattr(lead, "adult_target_age")
    ):
        known_child_age = (getattr(lead, "child_age", "") or "").strip()
        if _looks_like_child_age(known_child_age):
            lead.adult_target_age = known_child_age
            logger.info(
                "[adult_llm_engine] reused known child_age=%s as "
                "adult_target_age (same-child adult inquiry)",
                known_child_age,
            )


# Final-stage sanitiser — Georgian wording polish + brand voice + the
# explicit forbidden-phrase list from the patch spec (Part 6 + Part 10).
# Order matters: more specific phrases first.
ADULT_FORBIDDEN_PHRASE_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    # Live P0/P1 Hotfix BUG C (2026-06-15) — „მოგიწოდებთ" → neutral „გთხოვთ"
    # (mirrors the PARENT sanitiser; LLM free-generation, not a template).
    ("მოგიწოდებთ", "გთხოვთ"),
    # ---- Genitive correction (Part 10) ---------------------------------
    # Specific multi-word opener first so it doesn't survive into the
    # output after the standalone genitive fix.
    (
        "კეთილი იყოს თქვენი ვიზიტი სიტყვის აკადემიაის კულტურულ სივრცეში",
        "",
    ),
    (
        "კეთილი იყოს თქვენი ვიზიტი სიტყვის აკადემიის კულტურულ სივრცეში",
        "",
    ),
    (
        "კეთილი იყოს თქვენი ვიზიტი",
        "",
    ),
    # Wrong genitive everywhere it appears.
    (
        "სიტყვის აკადემიაის",
        "სიტყვის აკადემიის",
    ),
    (
        "აკადემიაის",
        "აკადემიის",
    ),
    # ---- Unnatural opener (Part 6) -------------------------------------
    (
        "სიამოვნებით გაგაცნობთ ჩვენს კულტურულ საღამოებს",
        "",
    ),
    (
        "სიამოვნებით გაგაცნობთ ჩვენი კულტურული საღამოების შესახებ",
        "",
    ),
    # ---- Retail / ticket-counter style ---------------------------------
    (
        "ბილეთი შეიძინეთ ახლავე",
        "",
    ),
    (
        "ბილეთი შეიძინეთ",
        "",
    ),
    (
        "ბილეთის შეძენა",
        "ბილეთის დაჯავშნა",
    ),
    (
        "სალაროდან",
        "",
    ),
    (
        "სალაროში",
        "",
    ),
    (
        "სალაროს",
        "",
    ),
    (
        "სალარო",
        "",
    ),
    # ---- Urgency / pressure words --------------------------------------
    (
        "იჩქარეთ",
        "",
    ),
    (
        "სასწრაფოდ",
        "",
    ),
    (
        "ბოლო ადგილები",
        "",
    ),
    (
        "ბოლო რამდენიმე ადგილი",
        "",
    ),
    # ---- False delayed-message promises (Part 6) -----------------------
    (
        "ერთ წუთში გავხსნი",
        "",
    ),
    (
        "ცოტა ხანში მოგწერთ",
        "",
    ),
    (
        "მალე გადაგამისამართებთ",
        "",
    ),
    (
        "გადაგამისამართებთ —",
        "",
    ),
    # ---- Generic robotic openings --------------------------------------
    (
        "მოგესალმებით! როგორ შემიძლია დაგეხმაროთ?",
        "გვითხარით, რა გაინტერესებთ?",
    ),
    (
        "როგორ შემიძლია დაგეხმაროთ?",
        "გვითხარით, რა გაინტერესებთ?",
    ),
    (
        "ყოველთვის მზად ვარ",
        "",
    ),
    (
        "მზად ვარ დაგეხმაროთ",
        "",
    ),
    # ---- English drift -------------------------------------------------
    (
        "precisely",
        "",
    ),
    (
        "Precisely",
        "",
    ),
    # ---- ADULT Live QA Polish Patch (2026-06-02) -----------------------
    # Bug 1 — Wrong "who is this for?" phrasing. The literal
    # „თქვენთვისაა ღონისძიებები თუ თქვენი შვილისთვის?" reads as a
    # broken sentence to the user; the correct brand phrasing is
    # "ღონისძიების შერჩევა თქვენთვის გსურთ".
    #
    # Live QA Session 7 Patch (2026-06-06) — Bug 3: revert to the
    # brand-owner-preferred form „თქვენთვის გსურთ თუ თქვენი
    # შვილისთვის?". Variants of the intermediate „სხვა ადამიანისთვის"
    # wording are normalised back to „თქვენი შვილისთვის" here so the
    # sanitiser stays idempotent across model fluctuations.
    (
        "ღონისძიების შერჩევა თქვენთვის გსურთ თუ სხვა ადამიანისთვის?",
        "ღონისძიების შერჩევა თქვენთვის გსურთ თუ თქვენი შვილისთვის?",
    ),
    (
        "ღონისძიების შერჩევა თქვენთვის გსურთ თუ შვილისთვის?",
        "ღონისძიების შერჩევა თქვენთვის გსურთ თუ თქვენი შვილისთვის?",
    ),
    (
        "თქვენთვისაა ღონისძიებები თუ თქვენი შვილისთვის?",
        "ღონისძიების შერჩევა თქვენთვის გსურთ თუ თქვენი შვილისთვის?",
    ),
    (
        "თქვენთვისაა ღონისძიებები თუ შვილისთვის?",
        "ღონისძიების შერჩევა თქვენთვის გსურთ თუ თქვენი შვილისთვის?",
    ),
    (
        "თქვენთვისაა ღონისძიებები",
        "ღონისძიების შერჩევა თქვენთვის გსურთ",
    ),
    # ---- Live QA Patch (2026-06-05 Session 2) — manager handoff -------
    # Bug 6 wording polish; mirror of the PARENT entries.
    (
        "მენეჯერთან კავშირით უფრო დაწვრილებით შეგიძლიათ გაიგოთ",
        "დამატებითი დეტალებისთვის, თუ გსურთ, დაგაკავშირებთ მენეჯერთან",
    ),
    (
        "მენეჯერთან კავშირით",
        "თუ გსურთ, დაგაკავშირებთ მენეჯერთან",
    ),
    (
        "თუ გსურთ, დაგაკავშირებთ.",
        "თუ გსურთ, დაგაკავშირებთ მენეჯერთან.",
    ),
    (
        "თუ გსურთ, დაგაკავშირდებათ.",
        "თუ გსურთ, დაგაკავშირდებათ მენეჯერი.",
    ),
    # ---- Live QA Patch (2026-06-05) ------------------------------------
    # Same 8 wording fixes that apply to PARENT also apply to ADULT —
    # the live transcript surfaced them in the adult flow too.
    ("გმადლობთ, რომ გაზიარეთ.", ""),
    ("გმადლობთ, რომ გაზიარეთ ", ""),
    ("გმადლობთ, რომ გაზიარეთ", ""),
    ("დასთვის", "დისთვის"),
    ("მიმოწმების შედეგად,", "გადავამოწმე —"),
    ("მიმოწმების შედეგად", "გადავამოწმე"),
    (
        "სიამოვნებით დაგიდგებით გვერდში.",
        "თუ გსურთ, დაგაკავშირებთ მენეჯერთან?",
    ),
    (
        "სიამოვნებით დაგიდგებით გვერდში",
        "თუ გსურთ, დაგაკავშირებთ მენეჯერთან?",
    ),
    (
        "თუ დაგეხმაროთ სხვა გზით?",
        "გსურთ, დაგაკავშიროთ მენეჯერთან?",
    ),
    (
        "თუ დაგეხმაროთ სხვა გზით.",
        "გსურთ, დაგაკავშიროთ მენეჯერთან?",
    ),
    (
        "თუ დაგეხმაროთ სხვა გზით",
        "გსურთ, დაგაკავშიროთ მენეჯერთან?",
    ),
    (
        "რომელი დრო გიჭერს მხარს?",
        "რომელი დროა თქვენთვის მოსახერხებელი?",
    ),
    (
        "რომელი დრო გიჭერს მხარს",
        "რომელი დროა თქვენთვის მოსახერხებელი",
    ),
    (
        "გიჭერს მხარს",
        "გაწყობთ",
    ),
    (
        "რომელი დრო გჭირდებათ?",
        "რომელი დროა თქვენთვის მოსახერხებელი?",
    ),
    (
        "რომელი დრო გჭირდებათ",
        "რომელი დროა თქვენთვის მოსახერხებელი",
    ),
    (
        "გნებავთ პირვანდელ დროზე დარჩეთ?",
        "რომელი დროა თქვენთვის მოსახერხებელი?",
    ),
    (
        "გნებავთ პირვანდელ დროზე დარჩეთ",
        "რომელი დროა თქვენთვის მოსახერხებელი",
    ),
    (
        "პირვანდელ დროზე დარჩეთ",
        "თქვენთვის მოსახერხებელი დრო შევარჩიოთ",
    ),
    # Bug 2 — Event-grounding hallucination. The bot was filling
    # missing `date_text` / `price_text` fields with the placeholder
    # „თარიღები და ფასები ახლახან ზუსტდება" — that wording was NEVER
    # in admin_config. Strip it; the prompt rule says to defer to the
    # manager wording „ამ დეტალს მენეჯერი დაგიზუსტებთ." instead.
    (
        "თარიღები და ფასები ახლახან ზუსტდება",
        "",
    ),
    (
        "ფასები ახლახან ზუსტდება",
        "",
    ),
    (
        "თარიღები ახლახან ზუსტდება",
        "",
    ),
    (
        "ახლახან ზუსტდება",
        "",
    ),
    # ---- Agent Wording Cleanup Patch (2026-06-03) ----------------------
    # „კავშირს მოგიწყობთ" verb construction reads as service-desk
    # filler. The brand-preferred form centres the offer.
    (
        "თუ გსურთ, მენეჯერთან კავშირსაც მოგიწყობთ",
        "თუ გსურთ, დაგაკავშირებთ მენეჯერთან",
    ),
    (
        "თუ გსურთ, მენეჯერთან კავშირს მოგიწყობთ",
        "თუ გსურთ, დაგაკავშირებთ მენეჯერთან",
    ),
    (
        "მენეჯერთან კავშირსაც მოგიწყობთ",
        "დაგაკავშირებთ მენეჯერთან",
    ),
    (
        "მენეჯერთან კავშირს მოგიწყობთ",
        "დაგაკავშირებთ მენეჯერთან",
    ),
    (
        "კავშირს მოგიწყობთ",
        "დაგაკავშირებთ მენეჯერთან",
    ),
    (
        "მენეჯერთან დაკავშირებაში დაგეხმარებით",
        "თუ გსურთ, დაგაკავშირებთ მენეჯერთან",
    ),
    (
        "მენეჯერს დაგაკავშირებთ",
        "დაგაკავშირებთ მენეჯერთან",
    ),
    # Live Polish Patch (2026-06-09) — standalone "სიამოვნებით." as the
    # sole response to user thanks is unnatural. Strip it so the system
    # prompt rule for context-aware closings takes effect instead.
    (
        "სიამოვნებით.",
        "",
    ),
    # ---- Emoji removal (production agent replies are emoji-free) -------
    (" 🌿", ""),
    ("🌿", ""),
    (" 😊", ""),
    ("😊", ""),
    (" ✨", ""),
    ("✨", ""),
    (" ✅", ""),
    ("✅", ""),
    (" ❌", ""),
    ("❌", ""),
)


# =========================================================================
# Transition follow-up guard — Bug 4 fix (added 2026-06-02)
# =========================================================================
#
# Live observation: when the user wrote "ზრდასრულთა ღონისძიებები
# მაინტერესებს", the LLM replied with just „გასაგებია, ზრდასრულთა
# ღონისძიებებზე დაგეხმარებით." and stopped — no question, no list, no
# next-step offer. Dead-end. The follow-up guard detects this short
# confirmation-only shape and appends the appropriate next question
# based on what the lead already knows.
#
# Conservative: only fires on the specific bare-confirmation patterns
# the live bug surfaced. The prompt rule is the primary line of
# defence; this guard is the safety net.

# Explicit bare-confirmation patterns the live bug surfaced. Kept for
# matching even when the broadened heuristic below ("acknowledgement
# + adult-event keyword, no question, short") wouldn't fire — these
# always trigger.
_ADULT_BARE_INTRO_PATTERNS: tuple[str, ...] = (
    "გასაგებია, ზრდასრულთა ღონისძიებებზე დაგეხმარებით.",
    "გასაგებია, ზრდასრულთა ღონისძიებებზე დაგეხმარებით",
    "გასაგებია, ღონისძიებებზე დაგეხმარებით.",
    "გასაგებია, კულტურულ საღამოებზე დაგეხმარებით.",
    "ზრდასრულთა ღონისძიებებზე დაგეხმარებით.",
    # Live QA Bug Fix Patch (2026-06-04) — gpt-5.4-mini variations
    # the previous patterns missed.
    "გასაგებია. ზრდასრულთა ღონისძიებებზე დაგეხმარებით.",
    "გასაგებია — ზრდასრულთა ღონისძიებებზე დაგეხმარებით.",
    "კულტურულ საღამოებზე დაგეხმარებით.",
    "კულტურულ ღონისძიებებზე დაგეხმარებით.",
    "ზრდასრულთა საღამოებზე დაგეხმარებით.",
)

# Acknowledgement openers — when the response leads with one of these
# AND mentions an adult-event keyword AND has no question, the
# broader heuristic treats it as a bare confirmation.
_ADULT_INTRO_ACK_OPENERS: tuple[str, ...] = (
    "გასაგებია",
    "კარგი",
    "კარგით",
    "მშვენიერია",
    "მადლობა",
)

# Adult-event keywords that, when present in a short ack response,
# indicate the LLM acknowledged the transition but stopped without
# asking the next question.
_ADULT_INTRO_TOPIC_KEYWORDS: tuple[str, ...] = (
    "ღონისძიებ",
    "საღამო",
    "კულტურულ",
    "ზრდასრულ",
)

_ADULT_FOLLOWUP_QUESTION_WHO: str = (
    # Live QA Session 7 Patch (2026-06-06) — Bug 3: revert to the
    # brand-owner-preferred form „თქვენთვის გსურთ თუ თქვენი
    # შვილისთვის?". The intermediate Session 6/7 wording
    # „სხვა ადამიანისთვის?" is dropped per operator preference.
    # The relative-capture logic (`_maybe_capture_adult_target` +
    # _ADULT_RELATIVE_PATTERNS) still routes „ჩემი დისთვის" /
    # „ჩემი ძმისთვის" / „ჩემი მეგობრისთვის" answers correctly —
    # the question wording change is purely conversational.
    "ღონისძიების შერჩევა თქვენთვის გსურთ თუ თქვენი შვილისთვის?"
)
_ADULT_FOLLOWUP_QUESTION_WHO_OR_OTHER: str = (
    "ღონისძიების შერჩევა თქვენთვის გსურთ თუ თქვენი შვილისთვის?"
)
_ADULT_FOLLOWUP_QUESTION_RELATIVE_AGE: str = (
    "ვისთვის გსურთ ღონისძიების შერჩევა და რამდენი წლის არის?"
)
_ADULT_FOLLOWUP_QUESTION_RELATIVE_AGE_NAMED: str = (
    "თქვენი {relation} რამდენი წლისაა?"
)
_ADULT_FOLLOWUP_QUESTION_AGE_SELF: str = "რამდენი წლის ბრძანდებით?"
_ADULT_FOLLOWUP_OFFER_LIST: str = (
    "გნებავთ, აქტიური ღონისძიებები შემოგთავაზოთ?"
)


def _looks_like_bare_intro(text: str) -> bool:
    """Heuristic: short ack response with an adult-event keyword and
    no question. Catches near-miss phrasings the literal pattern list
    can't enumerate (e.g. „გასაგებია, კულტურულ საღამოებზე
    უპასუხებთ", „კარგი, ღონისძიებებზე ვისაუბროთ").
    """
    stripped = (text or "").strip()
    if not stripped:
        return False
    if "?" in stripped:
        return False
    if len(stripped) > 120:
        return False
    lower = stripped.lower()
    if not any(opener in lower for opener in _ADULT_INTRO_ACK_OPENERS):
        return False
    if not any(kw in lower for kw in _ADULT_INTRO_TOPIC_KEYWORDS):
        return False
    return True


def _ends_with_dagexmarebit(text: str) -> bool:
    """Live QA Bug Fix Patch (2026-06-04) — broader catch-all.

    gpt-5.4-mini sometimes produces short adult-flow ack responses
    that end with „დაგეხმარებით." but don't match the
    acknowledgement-opener heuristic (e.g. „ზრდასრულთა ღონისძიებებზე
    დაგეხმარებით." with no leading „გასაგებია"). Any short response
    (under 120 chars) ending with this verb form is a candidate for
    the next-step question append.
    """
    stripped = (text or "").strip()
    if not stripped:
        return False
    return stripped.endswith("დაგეხმარებით.") or stripped.endswith("დაგეხმარებით")


def _ensure_adult_intro_followup(response: str, lead: Lead) -> str:
    """Append a next-step question if the response is a bare confirmation.

    Looks for the live-bug pattern (a short confirmation with no
    question mark) and decides what to append based on what we
    already know about the lead:

      * adult_target_age known (relative)   → soft "show list" offer.
      * adult_target_relation known but
        target age missing                  → ask the relative's age.
      * adult_age known (self)              → soft "show list" offer.
      * Nothing on record                   → ask who the event is for.

    Returns the response untouched when:
      * The response already contains a question mark.
      * The response is longer than 120 chars (LLM produced a real
        answer already).
      * The response doesn't match any of the bare-confirmation
        patterns AND doesn't look like a generic short ack with
        adult-event vocab AND doesn't end with „დაგეხმარებით.".
    """
    if not response:
        return response
    text = response.strip()
    if "?" in text:
        return response
    if len(text) > 120:
        return response

    matched_literal = any(pat in text for pat in _ADULT_BARE_INTRO_PATTERNS)
    matched_heuristic = _looks_like_bare_intro(text)
    # Live QA Bug Fix Patch (2026-06-04) — catch-all: any short
    # response ending in „დაგეხმარებით." (with or without trailing
    # period) is treated as a bare intro confirmation.
    matched_verb_ending = _ends_with_dagexmarebit(text)
    if not (matched_literal or matched_heuristic or matched_verb_ending):
        return response

    target_age = (getattr(lead, "adult_target_age", "") or "").strip()
    target_relation = (getattr(lead, "adult_target_relation", "") or "").strip()
    adult_age = (getattr(lead, "adult_age", "") or "").strip()

    if target_age:
        # Relative + age both known — offer to show events.
        next_q = _ADULT_FOLLOWUP_OFFER_LIST
    elif target_relation:
        # Relative known but no age — ask their age by relation name.
        next_q = _ADULT_FOLLOWUP_QUESTION_RELATIVE_AGE_NAMED.format(
            relation=target_relation,
        )
    elif adult_age:
        # Self age known — offer to show events.
        next_q = _ADULT_FOLLOWUP_OFFER_LIST
    else:
        # No context — ask who the event is for.
        next_q = _ADULT_FOLLOWUP_QUESTION_WHO

    sep = " " if not text.endswith(("\n", " ")) else ""
    return f"{text}{sep}{next_q}"


# Live QA Patch (2026-06-08): wording rewrites layered on top of the
# main ADULT_FORBIDDEN_PHRASE_REPLACEMENTS table. These run on EVERY
# turn regardless of sold_out state — they don't touch availability
# claims.
_ADULT_WORDING_REWRITES: tuple[tuple[str, str], ...] = (
    # Bug 5: „გინდა" is too informal for ADULT cultural-event copy.
    ("გინდა,", "გსურთ,"),
    ("გინდა ", "გსურთ "),
    ("გინდა?", "გსურთ?"),
    ("გინდათ,", "გსურთ,"),
    ("გინდათ ", "გსურთ "),
    ("გინდათ?", "გსურთ?"),
)

# Live QA Patch (2026-06-08) — Bug 1: phrases the LLM has been
# observed to invent when no sold_out signal exists in the tool data.
# The sanitiser strips these by default; the per-conversation
# `adult_sold_out_disclosed_for_conversation` flag (set by the
# executor when an operator-flagged sold_out event is returned)
# disables the strip so legitimate sold-out copy can pass through.
_ADULT_SOLD_OUT_INVENTED_PHRASES: tuple[str, ...] = (
    "ადგილები ამჟამად ამოწურულია",
    "ადგილები ამოწურულია",
    "ადგილები აღარ არის",
    "ადგილები არ არის",
    "ადგილები შემოიფარგლა",
    "ადგილები შეზღუდულია",
    "ბილეთები ამოწურულია",
    "ბილეთები აღარ არის",
    "sold out",
)

# Live QA Patch (2026-06-08) — Bug 4: the LLM has been observed
# opening adult turns with a filler „გმადლობთ." before asking for
# age. The pattern is sentence-initial, so we match anchored.
_ADULT_LEADING_THANKS_PATTERNS: tuple[str, ...] = (
    "გმადლობთ. რამდენი წლის ბრძანდებით",
    "გმადლობთ! რამდენი წლის ბრძანდებით",
    "გმადლობთ, რამდენი წლის ბრძანდებით",
    "გმადლობთ. რამდენი წლის ხართ",
    "გმადლობთ! რამდენი წლის ხართ",
)


# Live QA Patch (2026-06-08 — price hallucination): sentence-initial
# fragments the LLM has been observed to emit when it thinks an event
# has no operator-saved price. The sanitiser strips these whole
# sentences ONLY when the executor flagged the conversation as
# price-disclosed for this turn (price_text or price_gel was actually
# returned). Without the flag the legitimate „ფასი ამ ეტაპზე
# მითითებული არ არის." canonical phrasing passes through.
_ADULT_PRICE_MISSING_INVENTED_PHRASES: tuple[str, ...] = (
    "დასწრების საფასური ღონისძიების კონფიგურაციაში მითითებული არაა",
    "დასწრების საფასური მითითებული არ არის",
    "დასწრების საფასური მითითებული არაა",
    "საფასური კონფიგურაციაში მითითებული არაა",
    "საფასური კონფიგურაციაში მითითებული არ არის",
    "ფასი ღონისძიების კონფიგურაციაში არ მოდის",
    "ფასი კონფიგურაციაში მითითებული არ არის",
    "ფასი კონფიგურაციაში მითითებული არაა",
    "ფასის შესახებ ინფორმაცია არ მაქვს",
    "ფასი ცნობილი არ არის",
    "ფასი მოცემული არ არის",
    "ფასი ცნობილი არაა",
)


def _strip_invented_price_missing_phrases(text: str) -> str:
    """Sentence-level removal mirroring the sold-out strip. Only
    called when the executor confirmed at least one event was
    returned with a non-blank price for this turn.
    """
    out = text
    for phrase in _ADULT_PRICE_MISSING_INVENTED_PHRASES:
        lower = out.casefold()
        needle = phrase.casefold()
        if needle not in lower:
            continue
        idx = lower.find(needle)
        while idx >= 0:
            start = idx
            while start > 0 and out[start - 1] not in ".!?\n":
                start -= 1
            end = idx + len(phrase)
            while end < len(out) and out[end] not in ".!?\n":
                end += 1
            if end < len(out):
                end += 1
            out = out[:start] + out[end:]
            lower = out.casefold()
            idx = lower.find(needle)
    return out


def _strip_invented_sold_out_phrases(text: str) -> str:
    """Strip sold-out claims that the LLM invented. Only called when
    the executor did NOT mark the conversation as sold-out-disclosed
    for this turn.

    Removes whole sentences when the phrase forms one — operator
    review found that a partial strip leaves „. ." artefacts and
    sometimes flips meaning. Whole-sentence strip is conservative:
    surrounding sentences carry the event detail anyway.
    """
    out = text
    for phrase in _ADULT_SOLD_OUT_INVENTED_PHRASES:
        if phrase.casefold() not in out.casefold():
            continue
        # Sentence-level removal: find the phrase and erase from the
        # nearest sentence start to the nearest sentence end.
        lower = out.casefold()
        idx = lower.find(phrase.casefold())
        while idx >= 0:
            start = idx
            while start > 0 and out[start - 1] not in ".!?\n":
                start -= 1
            end = idx + len(phrase)
            while end < len(out) and out[end] not in ".!?\n":
                end += 1
            if end < len(out):
                end += 1  # include the punctuation
            out = out[:start] + out[end:]
            lower = out.casefold()
            idx = lower.find(phrase.casefold())
    return out


def _strip_leading_adult_thanks(text: str) -> str:
    """Bug 4: drop the filler „გმადლობთ." opener before age questions."""
    stripped = text.lstrip()
    for pattern in _ADULT_LEADING_THANKS_PATTERNS:
        if stripped.startswith(pattern):
            # Remove just the „გმადლობთ.[!,]" head, keep the question.
            for sep in (". ", "! ", ", "):
                head = "გმადლობთ" + sep
                if stripped.startswith(head):
                    return stripped[len(head):]
    return text


# Adult Subscription Confirmation Patch (2026-06-11): subscription
# list-membership success claims. When the executor did NOT confirm a
# successful Sheets write for THIS turn, any of these is a hallucination
# („the agent says it added the user to the list but no row was
# written") and is stripped sentence-level. The honest failure line is
# appended when a claim was removed and no manager handoff remains.
_SUBSCRIPTION_FALSE_SUCCESS_PHRASES: tuple[str, ...] = (
    "ჩაგწერეთ სიაში",
    "სიაში ჩაგწერეთ",
    "ჩაგწერთ სიაში",
    "სიაში ჩაგწერთ",
    "დაგამატეთ სიაში",
    "სიაში დაგამატეთ",
    "დაგიმატეთ სიაში",
    "სიაში დაგიმატეთ",
    "უკვე ხართ სიაში",
    "სიაში უკვე ხართ",
    "სიაში ხართ დამატებული",
)

# Honest fallback line appended when a false subscription claim is
# stripped and the remaining text no longer offers a manager handoff.
_SUBSCRIBE_FAILED_MSG: str = (
    "ამ მომენტში სიაში დამატება ტექნიკურად ვერ მოხერხდა. "
    "მენეჯერს გადავცემ და შეგატყობინებთ."
)


def _strip_false_subscription_success(text: str) -> str:
    """Sentence-level removal of subscription success claims. Only
    called when the executor did NOT mark a confirmed subscribe for
    this turn — see `sanitise_adult_response`."""
    out = text
    stripped_any = False
    for phrase in _SUBSCRIPTION_FALSE_SUCCESS_PHRASES:
        lower = out.casefold()
        needle = phrase.casefold()
        while needle in lower:
            idx = lower.find(needle)
            start = idx
            while start > 0 and out[start - 1] not in ".!?\n":
                start -= 1
            end = idx + len(phrase)
            while end < len(out) and out[end] not in ".!?\n":
                end += 1
            if end < len(out):
                end += 1  # include the trailing punctuation
            out = out[:start] + out[end:]
            stripped_any = True
            lower = out.casefold()
    out = out.strip()
    if stripped_any and "მენეჯერ" not in out:
        sep = " " if out and not out.endswith((" ", "\n")) else ""
        out = (out + sep + _SUBSCRIBE_FAILED_MSG).strip()
    return out


def sanitise_adult_response(
    text: str, sender_id: str | None = None,
) -> str:
    """Apply the forbidden-phrase rewrite list to an outgoing ADULT reply.

    Idempotent. Returns the same string when nothing matched. Exposed at
    module scope so tests can assert the table directly and the
    simulation tool can reuse it.

    When ``sender_id`` is provided AND
    ``adult_sold_out_disclosed_for_conversation[sender_id]`` is False
    (the default), invented sold-out copy is stripped. Pass
    ``sender_id=None`` (e.g. from a unit test) to get the bare
    rewrite pipeline without the sold-out filter.
    """
    if not text:
        return text
    out = text
    for needle, replacement in ADULT_FORBIDDEN_PHRASE_REPLACEMENTS:
        if needle in out:
            out = out.replace(needle, replacement)
    for needle, replacement in _ADULT_WORDING_REWRITES:
        if needle in out:
            out = out.replace(needle, replacement)
    # Drop the filler „გმადლობთ." opener.
    out = _strip_leading_adult_thanks(out)
    # Strip invented sold-out / price-missing copy when the executor
    # did NOT flag the relevant disclosure for this turn.
    if sender_id is not None:
        from app.agent.tools import adult_tool_executor as _executor

        if not _executor.is_sold_out_disclosed(sender_id):
            out = _strip_invented_sold_out_phrases(out)
        if _executor.is_price_disclosed(sender_id):
            # The executor returned an event with a non-blank price,
            # so any "price missing" copy is a hallucination — strip it.
            out = _strip_invented_price_missing_phrases(out)
        if not _executor.is_subscription_confirmed(sender_id):
            # No subscription row was written this turn — strip any
            # invented „ჩაგწერეთ სიაში" / „უკვე ხართ სიაში" success copy
            # so the agent never implies a subscription that didn't
            # happen (Core rule — honest confirmation).
            out = _strip_false_subscription_success(out)
    # Collapse double-spaces / orphaned punctuation from empty replacements.
    if "  " in out:
        out = re.sub(r"  +", " ", out)
    out = re.sub(r"\s+\.", ".", out)
    out = re.sub(r"\s+,", ",", out)
    out = re.sub(r"\.{2,}", ".", out)
    return out.strip()


# =========================================================================
# Adult-event subscription — deterministic consent path (2026-06-11)
# =========================================================================
#
# Live bug: the user explicitly consented to future-event notifications
# („კი გამომიგზავნეთ" right after the agent's own offer, or a direct
# „ჩამწერეთ სადმე? რომ ღონისძიება ავტომატურად მომივიდეს?") but the
# stochastic LLM either off-topic-redirected the reply or merely
# acknowledged WITHOUT calling `subscribe_to_adult_event_updates`.
# Result: no Sheets `events` row was written, yet the agent implied
# „შეგატყობინებთ" success.
#
# Fix: a deterministic layer (mirroring the existing deterministic
# unsubscribe short-circuit) that runs BEFORE the off-topic guard and
# BEFORE the LLM. It performs the actual Sheets write through the same
# `AdultToolExecutor` the LLM would use, and only ever confirms success
# AFTER the executor reports the row was written. The subscription
# service/executor never call the broadcast path, so this can never
# fan out a DM.

# Short standalone affirmations. These count as subscription consent
# ONLY when the OFFER was the immediately-preceding assistant turn (so
# „კი" inside „კიდევ ერთი კითხვა" never subscribes, AND a stale „asked"
# marker from an earlier offer can't turn a later unrelated „კი" into a
# subscribe). Matched as whole tokens.
_PENDING_CONSENT_TOKENS: frozenset[str] = frozenset({
    "კი", "კიო", "ჰო", "ჰოო", "დიახ", "ok", "okay", "yes", "yeah", "sure",
})

# Unambiguous "send / notify ME" verbs. Safe as substrings — they do not
# appear inside unrelated words and always denote subscription intent.
# Matched on the broader pending-offer signal (status=="asked" OR the
# last assistant turn was the offer). NOTE: the consent verb „გამომიგზავნოთ"
# (send to ME) is distinct from the OFFER verb „გამოგიგზავნოთ" (we send
# to YOU), so there is no collision with the offer-question detector.
_PENDING_CONSENT_VERB_PHRASES: tuple[str, ...] = (
    "გამომიგზავნეთ",
    "გამომიგზავნე",
    "გამომიგზავნოთ",
    "გამოგზავნეთ",
    "გამოგზავნოთ",
    "შემატყობინეთ",
    "შემატყობინე",
    "შემატყობინოთ",
    "დამამატეთ",
    "ჩამწერეთ",
    "ჩამამატეთ",
)

# „მინდა" („I want") is far too common to substring-match — „ბილეთი
# მინდა" / „მინდა ფასი ვიცოდე" / „მინდა მენეჯერი" are NOT subscription
# consent. It counts as consent ONLY when (a) the offer was the
# immediately-preceding turn AND (b) the message is a PURE affirmation:
# every token is in this whitelist (no competing-intent content word).
_CONSENT_AFFIRMATION_TOKENS: frozenset[str] = frozenset({
    "კი", "კიო", "ჰო", "ჰოო", "დიახ", "ok", "okay", "yes", "yeah", "sure",
    "მინდა", "მინდაც", "რა", "თქმა", "უნდა", "ძალიან", "აუცილებლად",
    "ნამდვილად", "ნამდვილადაც", "კია", "რათქმაუნდა",
})

# Direct subscription-intent phrases. These subscribe even WITHOUT a
# pending offer — the user is unambiguously asking to be added to the
# future-event list (Fix 2).
_DIRECT_SUBSCRIPTION_PHRASES: tuple[str, ...] = (
    "ჩამწერეთ სადმე",
    "სიაში ჩამწერეთ",
    "სიაში ჩამამატეთ",
    "სიაში დამამატეთ",
    "ავტომატურად მომივიდეს",
    "ავტომატურად მომდიოდეს",
    "ავტომატურად მოვიდეს",
    "ავტომატურად მომდის",
    "როცა დაემატება მომივიდეს",
    "როცა ახალი ღონისძიება დაემატება",
    "შემატყობინეთ როცა",
    "შემატყობინეთ, როცა",
    "მინდა შეტყობინებები",
    "მინდა შეტყობინება",
    "მომივიდეს ღონისძიებები",
    "მომივიდეს შეტყობინება",
    "მომივიდეს ახალი ღონისძიება",
    "ახალი ღონისძიებების შესახებ მომწერეთ",
    "ახალი ღონისძიებების შესახებ",
    "ახალი ღონისძიებები მომწერეთ",
    "როცა ახალი ღონისძიება იქნება",
    "ღონისძიებები ავტომატურად",
    "მსგავსი ღონისძიებების მიღება",
)


# User-facing deterministic subscription responses. Hardcoded here on
# purpose — this mirrors the existing deterministic UNSUBSCRIBE canned
# confirmations a few lines below in `run_adult_llm_turn`; both are
# engine-owned deterministic replies, not LLM-composed copy.
_SUBSCRIBE_SUCCESS_MSG: str = (
    "ჩაგწერეთ სიაში. როცა ახალი ზრდასრულთა ღონისძიება დაემატება, "
    "დეტალებს პირად შეტყობინებაში გამოგიგზავნით. "
    "გამოწერის გასაუქმებლად მოგვწერეთ: აღარ გამომიგზავნოთ."
)
_SUBSCRIBE_ALREADY_MSG: str = (
    "თქვენ უკვე ხართ სიაში. ახალი ზრდასრულთა ღონისძიებების "
    "დამატებისას შეგატყობინებთ."
)
_SUBSCRIBE_ASK_PHONE_MSG: str = (
    "მომწერეთ თქვენი საკონტაქტო ნომერი, რომ მომავალ "
    "ღონისძიებებზე ინფორმაციის გამოგზავნა შევძლოთ."
)
_SUBSCRIBE_ASK_NAME_MSG: str = (
    "სახელიც მომწერეთ, რომ სწორად შეგინახოთ."
)
_SUBSCRIBE_ASK_BOTH_MSG: str = (
    "სახელი და საკონტაქტო ნომერი მომწერეთ, რომ მომავალ "
    "ღონისძიებებზე ინფორმაციის გამოგზავნა შევძლოთ."
)


def _tokenize_ka(text: str) -> list[str]:
    """Unicode letter-run tokeniser (Georgian + Latin). Used so short
    affirmations like „კი" match as whole tokens and never inside
    „კიდევ"."""
    return re.findall(r"[^\W\d_]+", (text or "").casefold(), re.UNICODE)


def _is_subscription_offer_question(text: str) -> bool:
    """True when the outgoing/previous bot message is the future-event
    notification OFFER question.

    Discriminator: the offer uses the subjunctive „…გამოგიგზავნოთ?"
    while the success confirmation uses the indicative „…გამოგიგზავნით".
    „გამოგიგზავნოთ" is therefore unique to the question."""
    return "გამოგიგზავნოთ" in (text or "")


def _last_assistant_was_subscription_offer(conversation: Conversation) -> bool:
    history = list(getattr(conversation, "history", []) or [])
    for turn in reversed(history):
        if not isinstance(turn, dict):
            continue
        if turn.get("role") != "assistant":
            continue
        return _is_subscription_offer_question(str(turn.get("content") or ""))
    return False


def _has_pending_subscription_offer(conversation: Conversation) -> bool:
    """True when the agent has an outstanding subscription offer — either
    the conversation marker is „asked" OR the last assistant turn was the
    offer question (inference fallback when the marker wasn't persisted).
    """
    status = (
        getattr(conversation, "adult_subscription_status", "") or ""
    ).strip()
    if status == "asked":
        return True
    return _last_assistant_was_subscription_offer(conversation)


def _is_subscription_consent(
    user_message: str, *, conversation: Conversation,
) -> bool:
    """Decide whether the message is subscription CONSENT.

    Two tiers, both requiring that an offer is actually open:

      1. Unambiguous "send / notify ME" verbs (გამომიგზავნეთ /
         შემატყობინეთ / ჩამწერეთ …) — accepted when an offer is pending
         (status=="asked" OR the last assistant turn was the offer).
      2. Short standalone affirmations („კი" / „დიახ" / „ok") OR a PURE
         „მინდა" affirmation — accepted ONLY when the offer was the
         IMMEDIATELY-preceding assistant turn. This guards against a
         stale „asked" marker (an earlier offer + a later unrelated
         „კი") and against „მინდა" inside an unrelated „I want X"
         sentence.

    Negative phrases always lose.
    """
    text = (user_message or "").strip()
    if not text:
        return False
    from app.services import adult_subscription_service
    if adult_subscription_service.is_negative_subscription_phrase(text):
        return False

    lowered = text.casefold()
    offer_is_last = _last_assistant_was_subscription_offer(conversation)
    status = (
        getattr(conversation, "adult_subscription_status", "") or ""
    ).strip()
    pending = offer_is_last or status == "asked"

    # Tier 1 — unambiguous send/notify verbs (broader pending signal).
    if pending and any(p in lowered for p in _PENDING_CONSENT_VERB_PHRASES):
        return True

    # Tier 2 — short affirmations / pure „მინდა": require immediate
    # adjacency to the offer.
    if offer_is_last:
        tokens = set(_tokenize_ka(lowered))
        if tokens & _PENDING_CONSENT_TOKENS:
            return True
        if "მინდა" in tokens and tokens <= _CONSENT_AFFIRMATION_TOKENS:
            return True
    return False


def _is_direct_subscription_intent(user_message: str) -> bool:
    """Strong, unambiguous subscription requests — subscribe even with
    no pending offer (Fix 2). Negative phrases always lose."""
    text = (user_message or "").strip()
    if not text:
        return False
    from app.services import adult_subscription_service
    if adult_subscription_service.is_negative_subscription_phrase(text):
        return False
    lowered = text.casefold()
    return any(phrase in lowered for phrase in _DIRECT_SUBSCRIPTION_PHRASES)


def _deterministic_subscribe(
    conversation: Conversation,
    lead: Lead,
    sender_id: str,
    platform: str,
) -> str:
    """Perform the subscription Sheets write deterministically and return
    an HONEST user-facing confirmation.

    Routes through `AdultToolExecutor` so the name/phone fallback,
    source-event recovery, lead mirroring, and conversation-status
    marking all match the LLM tool path exactly. Never claims success
    unless the executor reports a written row. Never calls broadcast.
    """
    from app.services import adult_subscription_service

    # Already subscribed → confirm honestly without re-asking for data.
    try:
        already = adult_subscription_service.is_already_subscribed(
            platform, sender_id,
        )
    except Exception:
        already = False
    if already:
        try:
            conversation.adult_subscription_status = "subscribed"
        except Exception:
            pass
        return _SUBSCRIBE_ALREADY_MSG

    executor = AdultToolExecutor(
        conversation=conversation,
        lead=lead,
        sender_id=sender_id,
        platform=platform,
    )
    result = executor.execute(TOOL_SUBSCRIBE_TO_ADULT_EVENT_UPDATES, {})

    if result.get("success"):
        return _SUBSCRIBE_SUCCESS_MSG

    reason = result.get("reason")
    if reason == "missing_phone":
        # Keep the offer pending so the contact-collection follow-up
        # turn is still recognised as part of the subscription flow.
        try:
            conversation.adult_subscription_status = "asked"
        except Exception:
            pass
        return _SUBSCRIBE_ASK_PHONE_MSG
    if reason == "missing_name":
        try:
            conversation.adult_subscription_status = "asked"
        except Exception:
            pass
        return _SUBSCRIBE_ASK_NAME_MSG
    if reason == "missing_name_and_phone":
        try:
            conversation.adult_subscription_status = "asked"
        except Exception:
            pass
        return _SUBSCRIBE_ASK_BOTH_MSG
    # sheets_save_failed / tool_error / anything else → honest failure.
    return _SUBSCRIBE_FAILED_MSG


def _maybe_handle_subscription(
    user_message: str,
    conversation: Conversation,
    lead: Lead,
    sender_id: str,
    platform: str,
) -> str | None:
    """Deterministic subscription entry. Returns a reply string when the
    message is a subscription consent (with a pending offer) or a direct
    subscription request; ``None`` otherwise (let the LLM run)."""
    text = (user_message or "").strip()
    if not text:
        return None
    from app.services import adult_subscription_service

    pending = _has_pending_subscription_offer(conversation)

    # Explicit decline while an offer is pending — clear the marker and
    # let the LLM compose the natural decline. NEVER subscribe.
    if pending and adult_subscription_service.is_negative_subscription_phrase(text):
        try:
            conversation.adult_subscription_status = "declined"
        except Exception:
            pass
        return None

    if _is_direct_subscription_intent(text) or _is_subscription_consent(
        text, conversation=conversation,
    ):
        logger.info(
            "[adult_llm_engine] deterministic subscription sender=%s "
            "pending=%s",
            sender_id, pending,
        )
        return _deterministic_subscribe(conversation, lead, sender_id, platform)
    return None


def _mark_subscription_offer_if_present(
    conversation: Conversation, response: str,
) -> None:
    """Record the pending-offer marker when the agent just asked the
    future-event notification question, so the NEXT turn's consent
    („კი" / „კი გამომიგზავნეთ") is recognised deterministically even if
    the LLM phrased the question itself."""
    try:
        status = (
            getattr(conversation, "adult_subscription_status", "") or ""
        ).strip()
        if status in ("subscribed", "unsubscribed"):
            return
        if _is_subscription_offer_question(response):
            conversation.adult_subscription_status = "asked"
    except Exception:
        pass


# -- P0 Live Hotfix — BUG 2 (2026-06-14): deterministic named-event answer --
#
# When the user names a specific adult event that resolves in the active
# data, answer it directly from event data instead of letting the LLM ask
# the self/child target + age first (the prior audit's AD-1/AD-4 ordering)
# and then append the future-event subscription CTA (AD-2, prompt-emitted).
# This bypasses the LLM for that one turn, so the prompt's subscription CTA
# is never produced. Only the answer FIELDS the operator specified are
# rendered: title / date / format-location / price / link. A soft
# „სხვა ღონისძიებებიც ჩამოგითვალოთ?" follow-up is allowed (it is NOT the
# subscription CTA). Unknown / ambiguous references return None → the
# existing LLM unknown-event / disambiguation path is kept unchanged.
_ADULT_EVENT_REFERENCE_WORDS: tuple[str, ...] = ("საღამო", "ღონისძიებ", "კონცერ")
# Generic interrogatives / months / fillers that must NOT, on their own,
# count as a specific event NAME (else a bare „რომელი ღონისძიება გაქვთ?"
# spuriously resolves via a description word like „რომელიც").
_ADULT_GENERIC_QUERY_TOKENS: tuple[str, ...] = (
    "რომელ", "რომელი", "გაქვთ", "მაქვს", "ყველა", "ნახე", "არის", "როდის",
    "ივლის", "ივნის", "აგვისტ", "მაის", "აპრილ", "მარტ", "თებერვ", "იანვ",
    "სექტემბ", "ოქტომბ", "ნოემბ", "დეკემბ",
)


def _has_specific_event_name(tokens: list[str]) -> bool:
    """True when at least one query token looks like a specific event NAME
    (≥4 chars, not a generic interrogative / month / filler)."""
    for t in tokens:
        if len(t) < 4:
            continue
        if any(t == g or t.startswith(g) or g.startswith(t)
               for g in _ADULT_GENERIC_QUERY_TOKENS):
            continue
        return True
    return False


def _adult_named_event_price(event: dict) -> str:
    pt = str(event.get("price_text") or "").strip()
    if pt:
        return f"{pt} ლარი" if pt.isdigit() else pt
    pg = event.get("price_gel")
    if isinstance(pg, int) and pg > 0:
        return f"{pg} ლარი"
    return ""


def _adult_named_event_link(event: dict) -> str:
    return (
        str(event.get("reservation_url") or "").strip()
        or str(event.get("payment_terms") or "").strip()
    )


def _render_named_adult_event(event: dict) -> str:
    """Direct event answer — ONLY title / date / format-location / price /
    link, in paragraphs. NO description, NO subscription CTA. A soft
    list-others follow-up is appended (allowed, not the subscription CTA)."""
    title = str(event.get("title") or "").strip()
    blocks: list[str] = [title] if title else []
    facts: list[str] = []
    date_text = str(event.get("date_text") or "").strip()
    if date_text:
        facts.append(f"თარიღი: {date_text}")
    location = str(event.get("location") or "").strip()
    if location:
        facts.append(f"ფორმატი/ლოკაცია: {location}")
    price = _adult_named_event_price(event)
    if price:
        facts.append(f"ფასი: {price}")
    if facts:
        blocks.append("\n".join(facts))
    link = _adult_named_event_link(event)
    if link:
        blocks.append(f"ბილეთის ბმული: {link}")
    blocks.append("სხვა ღონისძიებებიც ჩამოგითვალოთ?")
    return "\n\n".join(b for b in blocks if b)


# BUG B (2026-06-15) — stems that mark a future-updates / subscription /
# notify-me request rather than a named-event lookup. When present, the
# PAST / NOT-FOUND branches defer (return None) so the subscription path /
# LLM handles it and the user never gets a spurious „ვერ მოვძებნე".
_NAMED_EVENT_DEFER_STEMS: tuple[str, ...] = (
    "შემატყობინ", "შეტყობინ", "გამომიგზავნ", "გამოგზავნ", "სიაში",
)

# BUG B hardening (2026-06-15) — query tokens that survive the tokenizer but
# are NOT event names: target / relation pronouns, generic descriptors and
# continuation fillers. The PAST / NOT-FOUND branches require a token OUTSIDE
# this set so a generic interest phrase („ღონისძიება მაინტერესებს ჩემთვის",
# „კიდევ რა ღონისძიება გაქვთ?", „კულტურული საღამო რა არის?") is NOT mistaken
# for a named-event lookup and wrongly answered „ვერ მოვძებნე".
_NON_EVENT_NAME_TOKENS: tuple[str, ...] = (
    "ჩემთვ", "ჩემთა", "ჩემი", "თქვენთვ", "თქვენ",
    "შვილ", "ბავშვ", "ადამიან", "მეგობ", "ოჯახ",
    "კულტურულ", "ზრდასრულ", "მაინტერეს", "დაინტერეს",
    "კიდევ", "სხვა", "ახალ", "ნებისმ", "ზოგად", "უბრალ", "მინდა", "მსურს",
    "ასევე",  # „also" — a continuation word, never an event name (BUG 2 hardening)
)


def _has_genuine_event_name_token(tokens: list[str]) -> bool:
    """Stricter than `_has_specific_event_name`: True only when a query token
    looks like a real event NAME / proper noun — excluding generic
    interrogatives / months (`_ADULT_GENERIC_QUERY_TOKENS`) AND target /
    relation / descriptor / filler words (`_NON_EVENT_NAME_TOKENS`). Gates
    the PAST / NOT-FOUND branches (BUG B hardening, 2026-06-15)."""
    for t in tokens:
        if len(t) < 4:
            continue
        if any(t == g or t.startswith(g) or g.startswith(t)
               for g in _ADULT_GENERIC_QUERY_TOKENS):
            continue
        if any(t.startswith(s) or s.startswith(t) for s in _NON_EVENT_NAME_TOKENS):
            continue
        return True
    return False


def _render_active_events_list() -> str:
    """A short list of the current active events (title + date), or a clear
    „none active" line. Appended after a PAST / NOT-FOUND named-event answer
    so the user always gets the live options (BUG B, 2026-06-15)."""
    try:
        from app.services import admin_config_service
        active = admin_config_service.get_active_adult_events()
    except Exception:  # pragma: no cover — defensive
        active = []
    if not active:
        return "ამ ეტაპზე აქტიური ღონისძიება არ გვაქვს."
    lines = ["ამ ეტაპზე აქტიური ღონისძიებები:"]
    for ev in active:
        title = str(ev.get("title") or "").strip()
        if not title:
            continue
        date_text = str(ev.get("date_text") or "").strip()
        lines.append(f"— {title}" + (f" ({date_text})" if date_text else ""))
    return "\n".join(lines)


def _render_past_named_event(event: dict) -> str:
    """„This event has already taken place {date}" + the active list. NO
    target/age question, NO invented data (BUG B, 2026-06-15)."""
    title = str(event.get("title") or "").strip()
    date_text = str(event.get("date_text") or "").strip()
    if title:
        head = f"ღონისძიება {title} უკვე გაიმართა"
    else:
        head = "ეს ღონისძიება უკვე გაიმართა"
    if date_text:
        head += f" — {date_text}"
    head += "."
    return f"{head}\n\n{_render_active_events_list()}"


def _render_unknown_named_event() -> str:
    """„No event found by that name" + the active list + manager-verify. NO
    target/age question, NO invented data (BUG B, 2026-06-15)."""
    return (
        "ამ სახელით ღონისძიება ვერ მოვძებნე.\n\n"
        f"{_render_active_events_list()}\n\n"
        "დეტალები მენეჯერთან შეგიძლიათ გადაამოწმოთ."
    )


def _maybe_handle_named_adult_event(user_message: str) -> str | None:
    """Return a deterministic direct event answer when the message names a
    specific event. Resolves, BEFORE any target/age question:
      * exactly one ACTIVE match → direct answer (unchanged);
      * the named event EXISTS but is PAST → „already took place" + list;
      * NO match at all → „not found" + active list + manager-verify;
      * ambiguous (>1) → None (keep existing LLM handling).
    Returns None for generic chatter / non-specific queries."""
    low = (user_message or "").lower()
    # Must clearly be an event reference (avoids firing on generic chatter).
    if not any(w in low for w in _ADULT_EVENT_REFERENCE_WORDS):
        return None
    try:
        from app.services import admin_config_service
        # Need a SPECIFIC name token, not a bare „ღონისძიება მაინტერესებს"
        # or a generic „რომელი ღონისძიება გაქვთ?" (only generic vocabulary →
        # let the LLM ask/list, don't spuriously resolve via a description
        # word like „რომელიც").
        tokens = admin_config_service._event_query_tokens(user_message)
        if not _has_specific_event_name(tokens):
            return None
        matches = admin_config_service.find_active_events_by_reference(user_message)
        if len(matches) == 1:
            return _render_named_adult_event(matches[0])
        if len(matches) >= 2:
            # Ambiguous ACTIVE match → keep the existing LLM handling.
            return None
        # 0 ACTIVE matches → BUG B (2026-06-15): resolve PAST vs NOT-FOUND
        # deterministically here so the agent never asks self/child target
        # before answering the event question. BUT a future-updates /
        # subscription / notify request („ახალ ღონისძიებებზე შემატყობინეთ")
        # is NOT a named-event lookup — defer it so the subscription path /
        # LLM handles it (never „ვერ მოვძებნე").
        low_msg = (user_message or "").casefold()
        if any(stem in low_msg for stem in _NAMED_EVENT_DEFER_STEMS):
            return None
        if not _has_genuine_event_name_token(tokens):
            # Generic interest / target / descriptor phrase — NOT a named-event
            # lookup. Defer to the LLM (never a spurious „ვერ მოვძებნე").
            return None
        all_matches = admin_config_service.find_events_by_reference(
            user_message, include_past=True,
        )
        if (
            len(all_matches) == 1
            and admin_config_service.is_adult_event_past(all_matches[0])
        ):
            return _render_past_named_event(all_matches[0])
        if not all_matches:
            return _render_unknown_named_event()
        # >1 past / mixed ambiguity → keep the existing LLM handling.
        return None
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning(
            "[adult_llm_engine] named-event direct answer raised: %s", exc,
        )
        return None


# -- public entry ---------------------------------------------------------


def run_adult_llm_turn(
    *,
    user_message: str,
    conversation: Conversation,
    lead: Lead,
    sender_id: str,
    platform: str,
) -> str:
    """Run one ADULT turn through the LLM engine.

    Returns the final assistant text, or ``""`` on any failure so the
    caller (``conversation_service`` / ``adult_flow``) can fall back to
    the legacy state machine. Never raises.

    A deterministic short-circuit at the top catches "ბანაკი / ბავშვი"
    intent and switches the segment back to PARENT before the LLM ever
    sees the message.
    """
    # Live QA Patch (2026-06-08) — Bug 1 + price hallucination: clear
    # any leftover disclosure flags from a previous turn so the
    # sanitiser only acts on what the EXECUTOR re-confirmed for THIS
    # turn.
    from app.agent.tools import adult_tool_executor as _executor_module
    _executor_module.clear_sold_out_disclosed(sender_id)
    _executor_module.clear_price_disclosed(sender_id)
    _executor_module.clear_subscription_confirmed(sender_id)

    # Adult Event Subscription Patch (2026-06-08): deterministic
    # unsubscribe phrase detection. Runs BEFORE the LLM so an explicit
    # „აღარ გამომიგზავნოთ" / „unsubscribe" can never be confused with
    # generic decline copy by the LLM. The handler updates the Sheets
    # `events` row and returns the canned confirmation directly.
    try:
        from app.services import adult_subscription_service
        if adult_subscription_service.is_unsubscribe_phrase(user_message):
            logger.info(
                "[adult_llm_engine] deterministic unsubscribe sender=%s",
                sender_id,
            )
            result = adult_subscription_service.unsubscribe(
                platform=platform, sender_id=sender_id,
            )
            if result.get("success"):
                return (
                    "კარგი, მომავალ ღონისძიებებზე "
                    "შეტყობინებებს აღარ გამოგიგზავნით."
                )
            if result.get("reason") == "not_subscribed":
                return "ამ სიაში ამ ეტაპზე არ ხართ დამატებული."
            # Sheets failure — degrade gracefully, ask manager handoff.
            return (
                "ამ ეტაპზე ცვლილების შენახვა ვერ მოხერხდა. "
                "თუ გსურთ, დაგაკავშირებთ მენეჯერთან."
            )
    except Exception as exc:
        logger.warning(
            "[adult_llm_engine] unsubscribe path raised: %s", exc,
        )

    # Deterministic parent-flow switch BEFORE any OpenAI call.
    if _user_wants_parent_flow(user_message):
        logger.info(
            "[adult_llm_engine] deterministic switch_to_parent_flow sender=%s",
            sender_id,
        )
        conversation.segment = "PARENT"
        conversation.state = "START"
        return (
            "გასაგებია, ბანაკის შესახებ დაგეხმარებით. "
            "თქვენი შვილი რამდენი წლისაა?"
        )

    # Wording Fix (2026-06-11) — BUG 2: a „where/how will the subscription
    # notification arrive?" question is legitimate. Answer it directly
    # (platform-aware) BEFORE the subscription / off-topic / LLM layers so
    # it is never redirected as off-topic and never re-subscribes.
    delivery_reply = _maybe_handle_notification_delivery_question(
        user_message, platform,
    )
    if delivery_reply is not None:
        logger.info(
            "[adult_llm_engine] deterministic notification-delivery answer "
            "sender=%s", sender_id,
        )
        return delivery_reply

    # Adult Subscription Confirmation Patch (2026-06-11): deterministic
    # subscription consent / direct-intent path. Runs BEFORE the
    # off-topic guard and BEFORE the LLM so an explicit „კი გამომიგზავნეთ"
    # (after the agent's own offer) or a direct „ჩამწერეთ სადმე …" ALWAYS
    # performs the Sheets write — never depends on the stochastic LLM
    # remembering to call the tool, and never claims success unless the
    # row was actually written. Subscription never triggers a broadcast.
    try:
        subscription_reply = _maybe_handle_subscription(
            user_message, conversation, lead, sender_id, platform,
        )
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning(
            "[adult_llm_engine] subscription path raised: %s", exc,
        )
        subscription_reply = None
    if subscription_reply is not None:
        return subscription_reply

    # Off-Topic Guard — deterministic redirect for general-knowledge
    # questions that aren't grounded in configured event data. Runs
    # BEFORE OpenAI so the bot doesn't pay for a token round-trip just
    # to answer an out-of-scope question (and so the LLM can't drift
    # into ChatGPT mode and explain who Elton John or Mufasa is).
    offtopic_reply = _maybe_adult_offtopic_reply(user_message, conversation)
    if offtopic_reply is not None:
        logger.info(
            "[adult_llm_engine] deterministic off-topic redirect sender=%s",
            sender_id,
        )
        return offtopic_reply

    # P0 Live Hotfix — BUG 2 (2026-06-14): when the user NAMES a specific
    # event that RESOLVES in the active list, answer it DIRECTLY from event
    # data (title / date / format-location / price / link) — skip the
    # self/child + age questions, and do NOT append the future-event
    # subscription CTA (that CTA is emitted by the PROMPT; bypassing the LLM
    # here means it is never generated). Unknown / ambiguous references fall
    # through to the existing LLM unknown-event handling. Runs BEFORE
    # `_maybe_capture_adult_target`, so FIX 3 (adult target self/child) is
    # left completely intact for every non-resolved message.
    # Turn Intent Gateway (Reasoning Layer Phase 2, 2026-06-23) — central,
    # deterministic, metadata-only. An AGE statement („მე ვარ 29 წლის") or a
    # DECLINE / manager-phone request must NOT trigger the named-event search:
    # the loose genuine-name gate mis-read „გავეცნო" as an event name and
    # answered „ამ სახელით ვერ მოვძებნე". A genuine event name or a real date
    # keeps `block_event_inquiry` False, so real references still resolve here.
    try:
        from app.reasoning.reasoning_layer import analyze_turn_intent as _gw_fn
        _gw = _gw_fn(user_message)
    except Exception:  # pragma: no cover — defensive; analyzer never raises
        _gw = None
    if _gw is None or not getattr(_gw, "block_event_inquiry", False):
        named_event_reply = _maybe_handle_named_adult_event(user_message)
        if named_event_reply is not None:
            logger.info(
                "[adult_llm_engine] deterministic named-event direct answer sender=%s",
                sender_id,
            )
            return named_event_reply
    else:
        logger.info(
            "[adult_llm_engine] named-event search blocked by gateway "
            "(intent=%s) sender=%s",
            getattr(_gw, "intent", "?"), sender_id,
        )

    # ADULT Context Routing Fix — capture „ჩემი დისთვის / ძმისთვის /
    # მეგობრისთვის / დედისთვის / მამისთვის" cues before the LLM runs
    # so the context block reflects them and the follow-up guard knows
    # which question to ask. Mutates lead in place; safe no-op when no
    # relative cue is present.
    # Response-Planner Hardening (2026-06-23, finding C) — when the gateway says
    # the user is asking for THEMSELVES (self-reference or an adult age, NOT a
    # child) and gave an age, capture `lead.adult_age` so the follow-up offers
    # the event list instead of the redundant „თქვენთვის თუ შვილისთვის?"
    # clarifier. Never overwrites an existing adult_age / a relative target, and
    # never touches child_age.
    try:
        if _gw is not None and getattr(_gw, "is_adult_self", False) \
                and getattr(_gw, "age", None) is not None \
                and not (getattr(lead, "adult_age", "") or "").strip() \
                and not (getattr(lead, "adult_target_relation", "") or "").strip() \
                and not (getattr(lead, "child_age", "") or "").strip() \
                and hasattr(lead, "adult_age"):
            lead.adult_age = str(_gw.age)
            logger.info(
                "[adult_llm_engine] adult-self captured adult_age=%s (gateway)",
                _gw.age,
            )
    except Exception:  # pragma: no cover — defensive
        pass

    try:
        _maybe_capture_adult_target(user_message, lead)
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning(
            "[adult_llm_engine] relative-target capture failed: %s", exc,
        )

    try:
        system_prompt = _build_system_prompt()
    except Exception as exc:
        logger.exception(
            "[adult_llm_engine] system prompt assembly failed: %s", exc,
        )
        return ""

    if _use_slim_prompts():
        slim_state, slim_policy = _build_slim_context(conversation, lead)
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "system", "content": slim_state},
            {"role": "system", "content": slim_policy},
        ]
        _trace_prompt_mode("slim", slim_state)
    else:
        context_message = _build_context_message(conversation, lead)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "system", "content": context_message},
        ]
        _trace_prompt_mode("giant", None)
    messages.extend(_recent_history(conversation))
    messages.append({"role": "user", "content": user_message})

    executor = AdultToolExecutor(
        conversation=conversation,
        lead=lead,
        sender_id=sender_id,
        platform=platform,
    )

    iterations = 0
    while iterations < MAX_TOOL_ITERATIONS:
        iterations += 1
        try:
            response = openai_service.chat_with_tools(
                messages=messages,
                tools=ADULT_TOOLS,
                tool_choice="auto",
                max_tokens=DEFAULT_MAX_TOKENS,
                temperature=DEFAULT_TEMPERATURE,
            )
        except Exception as exc:
            logger.exception(
                "[adult_llm_engine] chat_with_tools failed (iter=%d): %s",
                iterations, exc,
            )
            return ""

        choice = _first_choice(response)
        if choice is None:
            logger.warning(
                "[adult_llm_engine] response had no choices (iter=%d)",
                iterations,
            )
            return ""

        msg = _choice_message(choice)
        tool_calls = _tool_calls(msg)
        final_content = _message_content(msg)

        if not tool_calls:
            if not final_content:
                logger.warning(
                    "[adult_llm_engine] empty final content with no tool calls",
                )
                return ""
            sanitised = sanitise_adult_response(
                final_content.strip(), sender_id=sender_id,
            )
            # ADULT Live QA Polish Patch — append a next question if
            # the LLM produced just a bare "გასაგებია, ზრდასრულთა
            # ღონისძიებებზე დაგეხმარებით." confirmation.
            sanitised = _ensure_adult_intro_followup(sanitised, lead)
            # Adult Subscription Confirmation Patch (2026-06-11): if the
            # agent just asked the future-event notification question,
            # record the pending-offer marker so the NEXT user turn's
            # „კი" is recognised deterministically.
            _mark_subscription_offer_if_present(conversation, sanitised)
            return sanitised

        messages.append(_assistant_message_for_tool_calls(msg))

        for tool_call in tool_calls:
            tool_name = _tool_name(tool_call)
            raw_args = _tool_args(tool_call)
            parsed_args = _parse_tool_args(raw_args)

            logger.info(
                "[adult_llm_engine] tool_call name=%s args=%r",
                tool_name, parsed_args,
            )

            result = executor.execute(tool_name, parsed_args)

            logger.info(
                "[adult_llm_engine] tool_result name=%s success=%s reason=%s",
                tool_name, result.get("success"), result.get("reason"),
            )

            messages.append({
                "role": "tool",
                "tool_call_id": _tool_call_id(tool_call),
                "name": tool_name,
                "content": serialize_result(result),
            })

    logger.warning(
        "[adult_llm_engine] tool iteration cap (%d) reached — falling back",
        MAX_TOOL_ITERATIONS,
    )
    return ""


# -- prompt + context assembly -------------------------------------------


def _use_slim_prompts() -> bool:
    """Slim Prompt mode (Class 4) — load `adult_core.md` instead of the 54 KB
    `system_adult_v1.md` and inject only planner policy + selected_state."""
    return bool(getattr(settings, "USE_SLIM_PROMPTS", False))


def _build_system_prompt() -> str:
    # Class 4: slim mode loads the short core prompt; default loads the giant
    # prompt exactly as before (do NOT load system_adult_v1.md when slim).
    prompt_name = "adult_core" if _use_slim_prompts() else "system_adult_v1"
    raw = load_prompt(prompt_name)
    company_name = settings.COMPANY_NAME or "სიტყვის აკადემია"
    return raw.format(company_name=company_name)


def _build_slim_context(conversation, lead) -> tuple[str, str]:
    """Build (selected_state, planner_policy) system blocks for slim mode from
    the turn plan stashed on the conversation. Topic-scoped (Class 3): the
    adult-self flow sees adult_age only — never the child's age. Never raises."""
    try:
        from app.reasoning import selected_state as _ss
        plan = getattr(conversation, "_turn_plan", None)
        selected = _ss.build_selected_state(plan, lead, conversation)
        return _ss.format_selected_state(selected), _ss.format_planner_policy(plan)
    except Exception:  # pragma: no cover — slim context must never break a reply
        return "SELECTED STATE: (ცარიელია)", "PLANNER POLICY: (none)"


def _trace_prompt_mode(mode: str, selected_block) -> None:
    try:
        from app.reasoning import conversation_trace as _trace
        _trace.set(prompt_mode=mode)
        if selected_block is not None:
            _trace.set(selected_state=selected_block)
    except Exception:  # pragma: no cover — trace must never break a reply
        pass


def _build_context_message(conversation: Conversation, lead: Lead) -> str:
    """Compact one-block context summary appended after the main system
    prompt. Kept short — the model treats it as state, not narrative.
    """
    parts = [
        f"name={(lead.name or '').strip() or '—'}",
        f"phone={(lead.phone or '').strip() or '—'}",
        f"adult_age={(getattr(lead, 'adult_age', '') or '').strip() or '—'}",
        f"adult_target_relation={(getattr(lead, 'adult_target_relation', '') or '').strip() or '—'}",
        f"adult_target_age={(getattr(lead, 'adult_target_age', '') or '').strip() or '—'}",
        f"event_interest={(lead.event_interest or '').strip() or '—'}",
        f"preferred_event={(lead.preferred_event or '').strip() or '—'}",
        f"seat_count={(lead.seat_count or '').strip() or '—'}",
        f"reservation_status={(lead.reservation_status or '').strip() or '—'}",
        f"state={conversation.state}",
    ]
    return "Current ADULT lead context: " + "; ".join(parts) + "."


def _recent_history(conversation: Conversation) -> list[dict[str, str]]:
    """Last HISTORY_WINDOW turns normalised to OpenAI's message format."""
    out: list[dict[str, str]] = []
    history = list(conversation.history or [])[-HISTORY_WINDOW:]
    for turn in history:
        if not isinstance(turn, dict):
            continue
        role = turn.get("role")
        content = turn.get("content")
        if role in {"user", "assistant"} and content:
            out.append({"role": role, "content": str(content)})
    return out


# -- response-shape helpers (work against both real and mocked clients) --


def _first_choice(response: Any) -> Any:
    choices = getattr(response, "choices", None)
    if not choices:
        if isinstance(response, dict):
            choices = response.get("choices")
    if not choices:
        return None
    return choices[0]


def _choice_message(choice: Any) -> Any:
    msg = getattr(choice, "message", None)
    if msg is None and isinstance(choice, dict):
        msg = choice.get("message")
    return msg


def _tool_calls(msg: Any) -> list[Any]:
    tool_calls = getattr(msg, "tool_calls", None)
    if tool_calls is None and isinstance(msg, dict):
        tool_calls = msg.get("tool_calls")
    return list(tool_calls or [])


def _message_content(msg: Any) -> str:
    content = getattr(msg, "content", None)
    if content is None and isinstance(msg, dict):
        content = msg.get("content")
    return content or ""


def _tool_name(tool_call: Any) -> str:
    fn = getattr(tool_call, "function", None)
    if fn is None and isinstance(tool_call, dict):
        fn = tool_call.get("function")
    name = getattr(fn, "name", None)
    if name is None and isinstance(fn, dict):
        name = fn.get("name")
    return str(name or "")


def _tool_args(tool_call: Any) -> str:
    fn = getattr(tool_call, "function", None)
    if fn is None and isinstance(tool_call, dict):
        fn = tool_call.get("function")
    args = getattr(fn, "arguments", None)
    if args is None and isinstance(fn, dict):
        args = fn.get("arguments")
    return args or ""


def _tool_call_id(tool_call: Any) -> str:
    cid = getattr(tool_call, "id", None)
    if cid is None and isinstance(tool_call, dict):
        cid = tool_call.get("id")
    return str(cid or "")


def _parse_tool_args(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
    if not isinstance(parsed, dict):
        return {}
    return parsed


def _assistant_message_for_tool_calls(msg: Any) -> dict[str, Any]:
    """Re-serialize the assistant message that issued tool calls so the
    OpenAI chat completions API can match the next round's tool results
    back to those calls.
    """
    content = _message_content(msg)
    tool_calls = _tool_calls(msg)
    serialised_calls: list[dict[str, Any]] = []
    for tc in tool_calls:
        fn = getattr(tc, "function", None)
        if fn is None and isinstance(tc, dict):
            fn = tc.get("function")
        name = getattr(fn, "name", None)
        if name is None and isinstance(fn, dict):
            name = fn.get("name")
        args = getattr(fn, "arguments", None)
        if args is None and isinstance(fn, dict):
            args = fn.get("arguments")
        if args is None:
            args = ""
        if isinstance(args, dict):
            args = json.dumps(args, ensure_ascii=False)
        serialised_calls.append({
            "id": _tool_call_id(tc),
            "type": "function",
            "function": {"name": str(name or ""), "arguments": str(args or "")},
        })
    return {
        "role": "assistant",
        "content": content or "",
        "tool_calls": serialised_calls,
    }
