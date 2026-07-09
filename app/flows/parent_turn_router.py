"""Parent Turn Router — deterministic-first interrupt dispatcher.

Sits between the user-facing message and the existing PARENT state
machine. On every turn it asks two questions, in order:

  1. Does a *deterministic* keyword detector recognise this message as
     an interrupt (booking / manager / identity / price / dates /
     location / conditions / registration)? — implemented in
     `app/agent/intent/parent_intent_detector.py`.
  2. If not, and ``USE_LLM_TURN_ANALYZER=true``, does the LLM analyzer
     classify it as one of the same intents? — implemented in
     `app/agent/llm/parent_turn_analyzer.py`.

If either step returns an intent, the router produces a premium Georgian
reply from knowledge YAML (no LLM in the reply itself, except when the
existing PARENT_BOOKING_CONFIRMED template renders after a real Calendar
write). Otherwise it returns ``None`` and `parent_flow.handle` continues
to the scripted state machine.

DESIGN RULES (Phase 3.9+, hardened):

  * **Backend decides.** The LLM analyzer is advisory; backend validates
    everything and routes by closed whitelists.
  * **No fake booking confirmations.** "დაჯავშნილია" / "ჩაწერილი ხართ"
    only ship after ``calendar_service.book_slot`` returned True. A
    final-stage guard in `parent_flow.handle` enforces this independently.
  * **Strict intent priority.** When a message matches multiple intents,
    we route by the highest-priority one only. The detector enforces
    priority by walking its `INTENT_PRIORITY` tuple; the LLM-analyzer
    branch also picks the highest-priority equivalent.
  * **State preservation.** Identity / factual / out-of-scope responses
    must not advance the discovery state. Manager responses also do not
    advance. Only booking_request can transition to DONE — and only
    after a successful Calendar booking.
  * **No LLM in the reply path of an interrupt.** Replies are built
    deterministically from knowledge YAML. This keeps them auditable,
    cheap, and impervious to hallucination.

Deterministic-first runs **regardless** of `USE_LLM_TURN_ANALYZER`. The
flag only controls whether the LLM analyzer is consulted as a fallback
on messages the deterministic detector didn't recognise.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, time, timedelta
from typing import Any, Mapping

from app.agent.intent.parent_intent_detector import (
    INTENT_BOOKING_REQUEST,
    INTENT_CONDITIONS_QUESTION,
    INTENT_DATES_QUESTION,
    INTENT_IDENTITY_QUESTION,
    INTENT_LOCATION_QUESTION,
    INTENT_MANAGER_REQUEST,
    INTENT_NO_CONCERN,
    INTENT_OUT_OF_SCOPE,
    INTENT_PRICE_QUESTION,
    INTENT_REGISTRATION_QUESTION,
    detect_parent_interrupt_intent,
)
from app.agent.llm.parent_turn_analyzer import (
    LOW_CONFIDENCE_THRESHOLD,
    analyze_parent_turn,
)
from app.agent.services.knowledge_loader import load_knowledge
from app.agent.services.timestamps import extract_colloquial_hour
from app.config import settings
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.services.session_key_service import conversation_cache_key

logger = logging.getLogger(__name__)


# Per-conversation flag for the soft-vs-explicit manager escalation path
# (retained from earlier Phase 3.9 work but only consulted when the LLM
# analyzer is on — the deterministic detector treats all manager intents
# the same and routes by lead.phone presence alone, per current spec
# PART 5.C).
manager_offer_shown: dict[str, bool] = {}


# Phrases that ALL of: must NOT appear in a router reply unless the
# Calendar booking just succeeded. PART 8 enforcement is final-stage
# (in `parent_flow.handle`); these stems are exposed here so other
# modules / tests can share them.
FAKE_BOOKING_CONFIRMATION_STEMS: tuple[str, ...] = (
    "დაგაჯავშნე",                # "დაგაჯავშნეთ" — "we booked you"
    "დაჯავშნილია",               # "is booked"
    "ჩაწერილი ხართ",             # "you are registered"
    "ჩაგწერეთ",                  # "we wrote you in"
    "ჩავწერეთ",                  # variant
    "დადასტურდა ჯავშანი",        # "the reservation is confirmed"
    "ჯავშანი დადასტურდა",
    # P3-C PATCH 5 — additional past-tense booking confirmations the
    # live test surfaced. These must NEVER appear without
    # `lead.calendly_booked` being True. Pre-booking subjunctive forms
    # ("ჩავნიშნოთ", "ჩავნიშნო") are intentionally NOT included — the
    # sanitiser rewrites the wrong forms into subjunctive, and the
    # subjunctive itself is safe pre-booking.
    "ჩანიშნულია",                # "is scheduled"
    "ჩავნიშნე",                  # "I scheduled it"
    "ჩაგინიშნეთ",                # "we scheduled you"
    "ჩაგინიშნავთ",               # "we will schedule you" (assertive)
    "კონსულტაცია ჩაინიშნა",      # "the consultation was scheduled"
    "კონსულტაცია ჩანიშნულია",
    "კონსულტაცია დაგიდასტურდათ",
    "დაგიჯავშნეთ",              # past-tense variant
)


# -- helpers: knowledge accessors -----------------------------------------


def _camp() -> dict[str, Any]:
    return load_knowledge("camp_2026")["camp"]


def _company() -> dict[str, Any]:
    return load_knowledge("company")["company"]


def _instrumental_bank(name: str) -> str:
    """Render a bank/instrument name in the Georgian instrumental case.

    "ბანკი" → "ბანკით" (drop final "ი", append "ით"). For non-Georgian
    tokens (e.g. "TBC") we attach "-ით" with a hyphen — that's the
    common transliterated style. Used by the price-answer builder so we
    don't get "TBC ან საქართველოს ბანკი-ით", which puts the suffix on
    the conjunction instead of the bank.
    """
    if not name:
        return name
    if name.endswith("ი"):
        return name[:-1] + "ით"
    return name + "-ით"


def _locative_location(location: str) -> str:
    """Convert a nominative-case Georgian location to the locative ("-ში").

    Used so we render "ამბასადორ კაჭრეთში" instead of the awkward
    "ამბასადორი კაჭრეთი-ში" that the previous templates produced. Drops
    the final "ი" from every word and appends "ში" to the last word.

    Examples:
      "ამბასადორი კაჭრეთი" → "ამბასადორ კაჭრეთში"
      "თბილისი"            → "თბილისში"
      "ბათუმი"             → "ბათუმში"
    """
    if not location:
        return ""
    words = location.split()
    if not words:
        return location
    transformed: list[str] = []
    for word in words[:-1]:
        transformed.append(word[:-1] if word.endswith("ი") else word)
    last = words[-1]
    last = (last[:-1] if last.endswith("ი") else last) + "ში"
    transformed.append(last)
    return " ".join(transformed)


# -- helpers: contact-request detection (deterministic safety net) --------
#
# Used only inside the LLM-analyzer branch to distinguish soft human
# requests from explicit "give me the number" requests. The
# deterministic detector returns ``manager_request`` for both; the
# branch decides by lead.phone presence (PART 5.C), so this regex is
# kept for back-compat / LLM-branch nuance.

_EXPLICIT_CONTACT_STEMS = (
    "მენეჯერ",
    "ნომერ",
    "საკონტაქტო",
    "კონტაქტ",
    "ტელეფონ",
)


def _is_explicit_contact_request(message: str) -> bool:
    text = (message or "").lower()
    return any(stem in text for stem in _EXPLICIT_CONTACT_STEMS)


# -- safe field application (analyzer branch only) ------------------------


def _apply_safe_fields(
    lead: Lead, fields: Mapping[str, Any], primary_intent: str,
) -> None:
    """Apply analyzer-extracted ``provided_fields`` to the lead.

    See PART 7: psychological fields are only applied when the analyzer
    reports the user is genuinely answering the script question. Phone
    is NEVER trusted here — the canonical parser is in parent_flow.
    """
    age = fields.get("child_age")
    if isinstance(age, str) and age and not lead.child_age:
        lead.child_age = age

    name = fields.get("name")
    if isinstance(name, str) and name and not lead.name:
        # Live Bug 2 (2026-06-11) — never store a month / date / time /
        # booking artifact even from the analyzer-extracted field.
        try:
            from app.flows.parent_flow import is_valid_person_name
            valid = is_valid_person_name(name)
        except Exception:
            valid = True
        if valid:
            lead.name = name

    if primary_intent != "answer_flow_question":
        return

    challenge = fields.get("challenge")
    if isinstance(challenge, str) and challenge and not lead.challenge:
        lead.challenge = challenge

    deeper = fields.get("deeper_concern")
    if isinstance(deeper, str) and deeper and not lead.deeper_concern:
        lead.deeper_concern = deeper

    desired = fields.get("desired_change")
    if isinstance(desired, str) and desired and not lead.desired_change:
        lead.desired_change = desired


# -- premium reply builders (PART 5) --------------------------------------


def _build_identity_answer() -> str:
    """One short line: who the bot is. Never resets state, never repeats
    the segment-routing menu, never starts discovery. (PART 5.A)"""
    return (
        "მე სიტყვის აკადემიის ონლაინ ასისტენტი ვარ. შემიძლია ბანაკის "
        "პირობები აგიხსნათ, კითხვებზე გიპასუხოთ და სურვილის შემთხვევაში "
        "მენეჯერთან კონსულტაციაზეც ჩაგწეროთ."
    )


def _build_premium_price_answer(
    conversation: Conversation, message: str,
) -> str | None:
    """Delegate camp price/payment rendering to the canonical parent flow.

    `parent_flow` imports this router at module load, so the reverse import must
    stay function-local to avoid a circular import. The helper name remains for
    legacy call sites, but it no longer owns Georgian price copy.
    """
    from app.flows import parent_flow as canonical_parent_flow

    canonical = canonical_parent_flow._maybe_handle_repeat_camp_price(
        conversation, message,
    )
    if canonical is not None:
        return canonical
    if canonical_parent_flow._is_camp_price_amount_question(message):
        return canonical_parent_flow._camp_price_direct_answer()
    return None


def _build_premium_dates_answer() -> str:
    """Stream dates from knowledge. PART 5.E. No invented dates."""
    camp = _camp()
    # Camp Stream Date Filter — drop streams whose start date has arrived.
    # When none remain we fall through to the manager-handoff line below
    # rather than inventing dates.
    from app.services import admin_config_service
    streams = admin_config_service.get_visible_camp_streams(
        camp.get("streams") or [], year=camp.get("year"),
    )
    if not streams:
        return (
            "ბანაკის ზუსტ თარიღებს მენეჯერი დაგიდასტურებთ. "
            "გნებავთ, თქვენი ნომერი მომწერეთ — დაგიკავშირდებათ."
        )
    lines = ["2026 წლის ბანაკი სამ ნაკადად ტარდება:"]
    for stream in streams:
        name = stream.get("name", "")
        dates = stream.get("dates_text", "")
        lines.append(f"— {name}: {dates}")
    lines.append(
        "თუ გნებავთ, რეგისტრაციის ბმულსაც გამოგიგზავნით ან მენეჯერთან "
        "დაგაკავშირებთ."
    )
    return "\n".join(lines)


def _build_premium_location_answer() -> str:
    """Location from knowledge. PART 5.F.

    Critical: never appends "აკადემია" to "კაჭრეთი" — owner-flagged
    regression. The knowledge YAML stores the correct nominative form.
    """
    camp = _camp()
    locative = _locative_location(camp.get("location", ""))
    return (
        f"ბანაკი ტარდება {locative} — სასტუმრო კომპლექსში, მშვიდ და "
        f"დაცულ გარემოში.\n\n"
        "თუ კიდევ რამე გაინტერესებთ, ბანაკის პირობებსაც გაგიზიარებთ ან "
        "მენეჯერთან კონსულტაციაზე ჩაგწერთ."
    )


def _build_premium_conditions_answer() -> str:
    """Concise conditions from knowledge. PART 5.G + PART 7 polish.

    Short paragraph (not a bulleted menu). Ends with one soft next step.
    Uses the locative case for the location.
    """
    camp = _camp()
    duration = camp.get("duration_days", "")
    age_min = camp.get("age_min", "")
    age_max = camp.get("age_max", "")
    locative = _locative_location(camp.get("location", ""))
    includes = ", ".join(camp.get("includes") or [])
    price = camp.get("price_gel", "")
    return (
        f"სიტყვის აკადემიის ბანაკი არის {duration}-დღიანი პროგრამა "
        f"{age_min}-{age_max} წლის მოზარდებისთვის, {locative}. "
        f"ფასში — {price} ლარი — შედის {includes}.\n\n"
        "თუ გნებავთ, მენეჯერი მოკლე კონსულტაციაზე დაგიკავშირდებათ "
        "და დეტალებს დაგიდასტურებთ."
    )


def _build_premium_registration_answer() -> str:
    """PART 5.H — business rule: consultation precedes registration.

    Rather than handing out the raw link blindly (which would let the
    user register without an age/fit check), explain that a brief
    consultation comes first, then ask for a preferred time or phone.
    The link from knowledge is provided as backup at the end so a
    determined user can still find it.
    """
    camp = _camp()
    url = camp.get("registration_url", "")
    return (
        "რეგისტრაციამდე მოკლე კონსულტაცია სჯობს, რომ ბავშვის ასაკი და "
        "საჭიროება სწორად გადავამოწმოთ. მითხარით სასურველი დღე და საათი, "
        "ან მომწერეთ თქვენი ნომერი — მენეჯერი დაგიკავშირდებათ.\n\n"
        f"რეგისტრაციის ბმული: {url}"
    )


def _build_out_of_scope_answer() -> str:
    """PART 5.I — polite scoping, no menu, no flow reset."""
    return (
        "შემიძლია დაგეხმაროთ სიტყვის აკადემიის ბანაკთან ან კონსულტაციასთან "
        "დაკავშირებულ ნებისმიერ შეკითხვაში. რა გაინტერესებთ?"
    )


def _build_no_concern_answer() -> str:
    """P2 PART 5 — "no problem, just want camp" path.

    Accept the parent's stance naturally, frame the camp as a positive
    environment (NOT as a problem-fix), and offer a useful next step.
    No menu, no "გნებავთ A თუ B?" phrasing, no psychological framing.
    """
    return (
        "კარგი. ბანაკი ცოცხალი გარემოა — ახალი მეგობრები, "
        "თვითდამოუკიდებლობა და საინტერესო ზაფხული.\n\n"
        "თუ გნებავთ, თარიღებსაც გაგიზიარებთ, ან კონსულტაციაზე ჩაგწერთ "
        "და დეტალებს მენეჯერი დაგიდასტურებთ."
    )


def _build_clarifying_question() -> str:
    """Low-confidence fallback (LLM-analyzer branch). P2 polish.

    Removed the awkward "ცოტა ზუსტად რომ მესმოდეს" / "პირობებზე
    გელაპარაკოთ" phrasing flagged in the live test. The replacement is
    a short, neutral open question — no menu, no "A or B" framing.
    """
    return "კონკრეტულად რა გაინტერესებთ ბანაკზე? — დაგეხმარებით."


# -- manager handler (PART 5.C) -------------------------------------------


def _build_manager_ask_phone() -> str:
    return (
        "კი, რა თქმა უნდა. მომწერეთ თქვენი ნომერი და მენეჯერი "
        "დაგიკავშირდებათ."
    )


def _build_manager_handoff_with_phone() -> str:
    return "კი, გადავცემ მენეჯერს და დაგიკავშირდებათ."


def _handle_manager_request(
    conversation: Conversation, lead: Lead, _message: str,
) -> str:
    """Route a manager request by lead.phone presence (PART 5.C).

    If we already have a phone (from a previous turn), notify the manager
    and confirm handoff. If we don't, simply ask for the phone — no
    A/B menu, no discovery question.
    """
    sender_id = conversation.sender_id

    if lead.phone:
        # Hot-lead path: try to record + notify, but never let a service
        # failure mask the user-facing acknowledgement. Errors are
        # logged and swallowed.
        try:
            from app.services import notification_service, sheets_service
            try:
                sheets_service.create_lead(lead)
            except Exception as exc:
                logger.warning(
                    "[turn_router] sheets save failed during manager "
                    "handoff (sender=%s): %s",
                    sender_id, exc,
                )
            try:
                notification_service.send_manager_notification(lead, "")
            except Exception as exc:
                logger.warning(
                    "[turn_router] manager notification failed during "
                    "handoff (sender=%s): %s",
                    sender_id, exc,
                )
        except Exception as exc:
            logger.warning(
                "[turn_router] service module import failed during "
                "manager handoff (sender=%s): %s",
                sender_id, exc,
            )

        logger.info(
            "[turn_router] manager_request: handoff with known phone "
            "(sender=%s)", sender_id,
        )
        return _build_manager_handoff_with_phone()

    logger.info(
        "[turn_router] manager_request: phone unknown — asking for phone "
        "(sender=%s)", sender_id,
    )
    return _build_manager_ask_phone()


# -- booking handler (PART 5.B) -------------------------------------------


def _build_booking_ask_time(message: str) -> str:
    """No date/time provided — ask naturally.

    If the user also asked about price in the same message, briefly
    acknowledge the price (from knowledge) before pivoting. This is
    PART 3's "may briefly acknowledge the factual part" rule — booking
    remains the main action.
    """
    if _looks_like_price_question(message):
        camp = _camp()
        price = camp.get("price_gel", "")
        return (
            f"კი, ჩაგწერთ. ბანაკის ღირებულება {price} ლარია — დეტალებს "
            "კონსულტაციაზე მენეჯერი დაგიდასტურებთ. მითხარით, რომელი დღე "
            "და საათი გირჩევნიათ."
        )
    return (
        "კი, დაგეხმარებით. მითხარით, რომელი დღე და საათი გირჩევნიათ "
        "კონსულტაციისთვის — გადავამოწმებ თავისუფალ დროს."
    )


def _build_booking_ask_contact() -> str:
    return (
        "ამ დროს გადავამოწმებ. კონსულტაციის დასადასტურებლად მომწერეთ "
        "თქვენი სახელი და საკონტაქტო ნომერი."
    )


def _build_booking_ask_phone_only() -> str:
    return (
        "ამ დროს გადავამოწმებ. დასადასტურებლად მომწერეთ თქვენი ნომერი."
    )


def _build_booking_safe_fallback() -> str:
    """PART 8 — safe message when Calendar booking fails or is uncertain.

    NEVER contains 'დაჯავშნ' / 'ჩაგწერეთ' / 'ჩაწერილი ხართ'.
    """
    return (
        "ამ დროის დაჯავშნა ვერ დავადასტურე. მომწერეთ თქვენი ნომერი და "
        "მენეჯერი დაგიკავშირდებათ, ან შეგირჩევთ სხვა თავისუფალ დროს."
    )


def _looks_like_price_question(message: str) -> bool:
    text = (message or "").lower()
    return any(stem in text for stem in (
        "ფასი", "ღირს", "ღირებულება", "გადახდ", "თანხა",
    ))


def _parse_booking_datetime(message: str) -> str | None:
    """Best-effort parse of a Georgian date+time phrase.

    Accepts:
      * "DD MMMMს HH:MM"            → "22 მაისს 14:00"
      * "DD MMMMს N საათ(-ი/-ზე)"   → "22 მაისს 5 საათზე"
      * "ხვალ / ზეგ / დღეს HH:MM"   → "ხვალ 15:00"
      * "ხვალ / ზეგ / დღეს N საათ"  → "ხვალ 5 საათზე"

    Returns an ISO-8601 string in the camp's business timezone, or None
    if nothing parseable was found. The result is *advisory* — the
    canonical availability check goes through
    `calendar_service.check_slot_available`.

    Imports from parent_flow are lazy to avoid the circular import
    (parent_flow itself imports this module).
    """
    text = (message or "").lower()

    # -- time --------------------------------------------------------------
    # Georgian Colloquial Time Patch (2026-06-10): delegate to the shared
    # `extract_colloquial_hour` so the PM heuristic, typo variants
    # („სათზე" / „8-ზე" / „სთ-ზე" / „საათისთვის"), and explicit
    # morning/evening qualifiers behave IDENTICALLY here and in the
    # executor's normalisation chokepoint. The old inline regex only
    # supported „საათ"/„სთ" and produced inconsistent results.
    extracted = extract_colloquial_hour(text)
    if extracted is None:
        return None
    hour, minute = extracted
    if not (0 <= hour <= 23) or not (0 <= minute <= 59):
        return None

    # -- date --------------------------------------------------------------
    try:
        from app.flows.parent_flow import GEORGIAN_MONTH_STEMS, TBILISI_TZ
    except Exception as exc:
        logger.warning("[turn_router] datetime parse: parent_flow import failed: %s", exc)
        return None

    now = datetime.now(TBILISI_TZ)
    target_date: date | None = None

    day_month = re.search(r"\b(\d{1,2})\s+([ა-ჰ]+)", text)
    if day_month:
        day_num = int(day_month.group(1))
        month_word = day_month.group(2)
        for stem, month_num in GEORGIAN_MONTH_STEMS.items():
            if month_word.startswith(stem):
                try:
                    candidate = date(now.year, month_num, day_num)
                    if candidate < now.date():
                        candidate = date(now.year + 1, month_num, day_num)
                    target_date = candidate
                except ValueError:
                    pass
                break

    if target_date is None:
        if "ხვალ" in text:
            target_date = (now + timedelta(days=1)).date()
        elif "ზეგ" in text:
            target_date = (now + timedelta(days=2)).date()
        elif "დღეს" in text:
            target_date = now.date()

    if target_date is None:
        return None

    return datetime.combine(
        target_date, time(hour, minute), tzinfo=TBILISI_TZ,
    ).isoformat()


def _attempt_router_booking(
    conversation: Conversation, lead: Lead, datetime_iso: str,
) -> str:
    """Attempt a calendar booking from inside the router.

    The full booking path mirrors `parent_flow._book_selected_slot`:
    pre-check availability → book → mark lead → save to Sheets → notify
    manager → state=DONE → render `PARENT_BOOKING_CONFIRMED`.

    On ANY failure (slot busy, calendar API error, parsing failure)
    return `_build_booking_safe_fallback` — PART 8 guarantees no
    confirmation language ships unless `book_slot` succeeded.
    """
    try:
        from app.flows.parent_flow import GEORGIAN_MONTHS_NOM, slots_shown_for_state
        from app.services import (
            calendar_service, notification_service, openai_service, sheets_service,
        )
        from data.prompts import PARENT_BOOKING_CONFIRMED
    except Exception as exc:
        logger.warning("[turn_router] booking imports failed: %s", exc)
        return _build_booking_safe_fallback()

    try:
        slot_dt = datetime.fromisoformat(datetime_iso)
    except ValueError as exc:
        logger.warning("[turn_router] booking: bad ISO %r: %s", datetime_iso, exc)
        return _build_booking_safe_fallback()

    # availability pre-check
    try:
        available = calendar_service.check_slot_available(slot_dt)
    except Exception as exc:
        logger.warning(
            "[turn_router] booking: check_slot_available raised: %s", exc,
        )
        conversation.pending_booking = None
        return _build_booking_safe_fallback()
    if not available:
        logger.info("[turn_router] booking: slot %s busy/invalid", datetime_iso)
        conversation.pending_booking = None
        return _build_booking_safe_fallback()

    # the actual write
    try:
        booked = calendar_service.book_slot(datetime_iso=datetime_iso, lead=lead)
    except Exception as exc:
        logger.warning("[turn_router] booking: book_slot raised: %s", exc)
        conversation.pending_booking = None
        return _build_booking_safe_fallback()
    if not booked:
        logger.error("[turn_router] booking: book_slot returned False for %s", datetime_iso)
        conversation.pending_booking = None
        return _build_booking_safe_fallback()

    # success — mirror parent_flow's post-booking side effects
    lead.calendly_booked = True
    lead.booked_datetime_iso = datetime_iso
    lead.status = "Booked"
    try:
        lead.conversation_summary = openai_service.generate_summary(conversation.history)
    except Exception:
        # summary failure is non-fatal — leave whatever is there
        pass

    try:
        sheets_service.create_lead(lead)
    except Exception as exc:
        logger.warning("[turn_router] sheets save failed after booking: %s", exc)
    try:
        notification_service.send_manager_notification(lead, lead.conversation_summary)
    except Exception as exc:
        logger.warning("[turn_router] manager notification failed after booking: %s", exc)

    conversation.state = "DONE"
    conversation.pending_booking = None
    slots_shown_for_state.pop(conversation_cache_key(conversation), None)

    date_text = f"{slot_dt.day} {GEORGIAN_MONTHS_NOM[slot_dt.month]}"
    time_text = slot_dt.strftime("%H:%M")
    return PARENT_BOOKING_CONFIRMED.format(date=date_text, time=time_text).strip()


def _handle_booking_request(
    conversation: Conversation, lead: Lead, message: str,
) -> str:
    """Premium booking dispatcher (PART 5.B + Phase-4 pending booking).

    Decision tree:
      1. message contains a parseable date+time AND lead.name + lead.phone
         are populated → attempt real Calendar booking.
      2. message contains a parseable date+time but contact info is
         missing → store ``conversation.pending_booking`` so the next
         turn can continue the booking even if it has no booking keyword,
         then ask only for the missing piece. State preserved.
      3. message has no parseable date/time → ask for preferred day/time.
         No pending_booking yet (we have nothing to remember).

    At no point does this function produce booking-confirmation language
    unless step 1's `_attempt_router_booking` actually wrote to Calendar.
    """
    datetime_iso = _parse_booking_datetime(message)
    has_name = bool((lead.name or "").strip())
    has_phone = bool((lead.phone or "").strip())

    if datetime_iso and has_name and has_phone:
        logger.info(
            "[turn_router] booking_request: all data present — attempting "
            "calendar booking for sender=%s", conversation.sender_id,
        )
        return _attempt_router_booking(conversation, lead, datetime_iso)

    if datetime_iso:
        # We have time, need contact info. Persist a pending_booking
        # entry so subsequent bare-phone / bare-name messages from this
        # sender can be recognised as a continuation by the dedicated
        # `maybe_handle_pending_booking_continuation` hook.
        missing = _missing_contact_fields(lead)
        conversation.pending_booking = _build_pending_booking_record(
            datetime_iso, missing,
        )
        logger.info(
            "[turn_router] booking_request: datetime parsed but contact "
            "info missing (name=%s phone=%s) — set pending_booking, "
            "missing=%s",
            has_name, has_phone, missing,
        )
        if has_name and not has_phone:
            return _build_booking_ask_phone_only()
        return _build_booking_ask_contact()

    # No datetime — no pending_booking written.
    logger.info(
        "[turn_router] booking_request: no datetime — asking for time "
        "(sender=%s)", conversation.sender_id,
    )
    return _build_booking_ask_time(message)


# -- pending booking record helpers ---------------------------------------


def _missing_contact_fields(lead: Lead) -> list[str]:
    """Return which of {name, phone} are not yet captured. Order matters —
    we ask for name first, then phone (matches the existing ASK_NAME UX).
    """
    missing: list[str] = []
    if not (lead.name or "").strip():
        missing.append("name")
    if not (lead.phone or "").strip():
        missing.append("phone")
    return missing


def _build_pending_booking_record(
    requested_datetime_iso: str, missing: list[str],
) -> dict[str, Any]:
    """Construct the JSON-safe ``pending_booking`` dict.

    Spec PART 1/2: everything in here is str / int / list / None — no
    Python datetime objects, no Lead refs, nothing the JSON encoder
    would choke on. ``requested_date_text`` / ``requested_time_text``
    are derived for display so we don't re-parse the ISO string in the
    UI layer.
    """
    try:
        from app.flows.parent_flow import GEORGIAN_MONTHS_NOM, TBILISI_TZ
        slot_dt = datetime.fromisoformat(requested_datetime_iso)
        date_text = f"{slot_dt.day} {GEORGIAN_MONTHS_NOM[slot_dt.month]}"
        time_text = slot_dt.strftime("%H:%M")
        now_iso = datetime.now(TBILISI_TZ).isoformat()
    except Exception as exc:
        # Defensive: a malformed ISO string here means we still record
        # the booking intent but with empty display fields. The router
        # will re-parse the canonical ISO on attempt.
        logger.warning(
            "[turn_router] pending_booking: derive display fields failed: %s",
            exc,
        )
        date_text = ""
        time_text = ""
        now_iso = datetime.utcnow().isoformat()

    return {
        "requested_datetime_iso": requested_datetime_iso,
        "requested_date_text": date_text,
        "requested_time_text": time_text,
        "source": "booking_interrupt",
        "missing_fields": list(missing),
        "created_at": now_iso,
        "attempts": 0,
    }


# -- intent → response dispatcher -----------------------------------------


def _response_for_intent(
    intent: str, conversation: Conversation, lead: Lead, message: str,
) -> str | None:
    """Map a *validated* intent label to a deterministic premium reply.

    Returns None if the intent is unknown — caller will treat that as
    "fall through to the state machine".
    """
    if intent == INTENT_BOOKING_REQUEST:
        return _handle_booking_request(conversation, lead, message)

    if intent == INTENT_MANAGER_REQUEST:
        return _handle_manager_request(conversation, lead, message)

    if intent == INTENT_IDENTITY_QUESTION:
        return _build_identity_answer()

    if intent == INTENT_PRICE_QUESTION:
        return _build_premium_price_answer(conversation, message)

    if intent == INTENT_DATES_QUESTION:
        return _build_premium_dates_answer()

    if intent == INTENT_LOCATION_QUESTION:
        return _build_premium_location_answer()

    if intent == INTENT_CONDITIONS_QUESTION:
        return _build_premium_conditions_answer()

    if intent == INTENT_REGISTRATION_QUESTION:
        return _build_premium_registration_answer()

    if intent == INTENT_NO_CONCERN:
        return _build_no_concern_answer()

    if intent == INTENT_OUT_OF_SCOPE:
        return _build_out_of_scope_answer()

    return None


# -- LLM-analyzer → deterministic-intent mapping --------------------------


# Map the analyzer's primary_intent vocabulary (defined in
# parent_turn_analyzer.py) onto the deterministic intent labels used by
# the response dispatcher above. Anything not in this map (e.g.
# answer_flow_question, provide_phone, choose_slot, no_concern,
# proceed_to_booking) means the analyzer is telling us NOT to interrupt
# — let the state machine handle it.
_ANALYZER_INTENT_MAP: dict[str, str] = {
    "ask_manager":      INTENT_MANAGER_REQUEST,
    "ask_price":        INTENT_PRICE_QUESTION,
    "ask_dates":        INTENT_DATES_QUESTION,
    "ask_location":     INTENT_LOCATION_QUESTION,
    "ask_conditions":   INTENT_CONDITIONS_QUESTION,
    "ask_registration": INTENT_REGISTRATION_QUESTION,
}


# -- main entry point -----------------------------------------------------


def _analyzer_enabled() -> bool:
    """Indirection so tests can monkeypatch without touching frozen Settings."""
    return bool(getattr(settings, "USE_LLM_TURN_ANALYZER", False))


# Kept for backwards compatibility with the prior Phase 3.9 test suite.
# The deterministic detector now ALWAYS runs; this flag only gates the
# LLM analyzer fallback step.
def _router_enabled() -> bool:
    return _analyzer_enabled()


# States in which the router skips interrupt detection entirely. These
# all have specialised input handlers (phone parser, slot picker, etc.)
# that would be broken by an out-of-band interrupt. The cost of skipping:
# a user typing "მენეჯერი მინდა" at the slot-picker won't be caught
# automatically — but they can retry on the next message.
_SKIP_STATES: frozenset[str] = frozenset({
    "PRESENT_VALUE",
    "OFFER_BOOKING",
    "ASK_NAME",
    "DONE",
})


def maybe_handle_analyzer_interrupt(
    conversation: Conversation, lead: Lead, message: str,
) -> str | None:
    """Top-level dispatcher.

    Returns:
      * a string — backend has decided to bypass the scripted state
        machine for this turn (premium interrupt reply, or a Calendar-
        confirmed booking).
      * None — neither the deterministic detector nor (optionally) the
        LLM analyzer recognised an interrupt; the caller continues with
        the existing state machine.

    Never raises. Never mutates state EXCEPT through the booking path
    (which transitions to ``DONE`` only after a real Calendar write).
    """
    if conversation.state in _SKIP_STATES:
        return None

    # 1. Deterministic detector — ALWAYS runs (PART 7).
    det_result = detect_parent_interrupt_intent(message)
    if det_result is not None:
        intent = det_result["intent"]
        entities = det_result.get("entities") or {}
        logger.info(
            "[turn_router] deterministic: state=%s intent=%s conf=%.2f",
            conversation.state, intent, det_result.get("confidence", 0.0),
        )
        # Apply safe entity extractions BEFORE producing the reply, so
        # the user's incidentally-provided age isn't lost when they
        # also ask a factual question. Manager intents intentionally
        # skip this — a manager request that happens to contain "8 წლის"
        # shouldn't write child_age until the user gives that detail
        # in a non-escalation context.
        if intent != INTENT_MANAGER_REQUEST:
            age = entities.get("child_age")
            if age and not lead.child_age:
                lead.child_age = age
        reply = _response_for_intent(intent, conversation, lead, message)
        if reply is not None:
            return reply
        # Unknown intent label — fall through to the analyzer / state machine.

    # 2. LLM analyzer — only when flag is on AND deterministic returned None.
    if not _analyzer_enabled():
        return None

    try:
        result = analyze_parent_turn(
            current_state=conversation.state,
            user_message=message,
            lead=lead,
            conversation_history=conversation.history,
        )
    except Exception as exc:
        logger.warning(
            "[turn_router] analyzer raised unexpectedly (state=%s): %s — passthrough",
            conversation.state, exc,
        )
        return None

    if result is None:
        return None

    primary_intent = result["primary_intent"]
    confidence = result["confidence"]

    # Apply SAFE provided_fields before branching.
    _apply_safe_fields(lead, result.get("provided_fields") or {}, primary_intent)

    # PART 7: low confidence → clarifying question (not silent script).
    if confidence < LOW_CONFIDENCE_THRESHOLD:
        logger.info(
            "[turn_router] analyzer: low confidence %.2f → clarifying question",
            confidence,
        )
        return _build_clarifying_question()

    # PART 3 strict priority — map analyzer intent to deterministic
    # vocabulary (which already encodes priority).
    mapped = _ANALYZER_INTENT_MAP.get(primary_intent)
    if mapped is not None:
        reply = _response_for_intent(mapped, conversation, lead, message)
        if reply is not None:
            logger.info(
                "[turn_router] analyzer: mapped %s → %s",
                primary_intent, mapped,
            )
            return reply

    # `no_concern` is special — the user has rejected discovery. If they
    # also asked a factual question, answer that; otherwise softly ask
    # which information they want.
    if primary_intent == "no_concern":
        fact_types = result.get("fact_types_requested") or []
        if "price" in fact_types:
            return _build_premium_price_answer(conversation, message) or (
                _build_clarifying_question()
            )
        if "dates" in fact_types:
            return _build_premium_dates_answer()
        if "location" in fact_types:
            return _build_premium_location_answer()
        if "conditions" in fact_types:
            return _build_premium_conditions_answer()
        if "registration" in fact_types:
            return _build_premium_registration_answer()
        return _build_clarifying_question()

    if primary_intent == "unclear":
        return _build_clarifying_question()

    # answer_flow_question / continue_flow / proceed_to_booking /
    # provide_phone / choose_slot → let the existing state machine run.
    return None


# -- PART 8 — fake-booking guard ------------------------------------------


def contains_booking_confirmation(text: str) -> bool:
    """Cheap scan for booking-confirmation phrases.

    Used by the final-stage guard in `parent_flow.handle` to detect text
    that *looks* like a confirmation. The guard then cross-checks
    against `lead.calendly_booked` / `conversation.state` to decide
    whether the text is legitimate or hallucinated.
    """
    lowered = (text or "").lower()
    return any(stem in lowered for stem in FAKE_BOOKING_CONFIRMATION_STEMS)


# -- PART 4 — pending booking continuation --------------------------------
#
# When the previous turn set ``conversation.pending_booking`` (we asked
# the user for a phone / name to complete a booking they requested with a
# concrete day/time), the next message must NOT be treated as a discovery
# answer — even when it carries no booking keyword. A bare "599123456" or
# "ნიკა" is the most common case.
#
# This hook runs BEFORE the silent intent router but still respects user
# intent: identity / manager / factual / cancel interrupts during pending
# booking are honoured per PART 5.


# Stems that mean "abandon this booking" — checked first so a cancel
# always wins over phone-extraction. "მერე" ("later") on its own is
# ambiguous, but inside a pending-booking context it almost always means
# "let's do this later" — i.e. cancel.
_CANCEL_STEMS: tuple[str, ...] = (
    "აღარ მინდა",
    "გაუქმე",                   # გაუქმება / გაუქმდეს
    "არ მინდა ჩაწერ",
    "მერე",
    "სხვა დროს",
    "გაუქმდე",
)


def _is_cancellation(message: str) -> bool:
    text = (message or "").lower().strip()
    return any(stem in text for stem in _CANCEL_STEMS)


def _build_cancel_response() -> str:
    return (
        "კარგი, ჩაწერას აღარ გავაგრძელებ. თუ მოგვიანებით გადაწყვეტთ, "
        "მომწერეთ სასურველი დღე და საათი."
    )


# Premium prompts shown during the continuation loop. Short, one
# next-step, no menu, no robotic phrasing.

def _build_pending_ask_phone() -> str:
    return (
        "ამ დროს გადავამოწმებ. დასადასტურებლად მომწერეთ თქვენი საკონტაქტო ნომერი."
    )


def _build_pending_ask_name() -> str:
    return "ნომერი მივიღე. გვითხარით თქვენი სახელი — და კონსულტაციას დაგიდასტურებთ."


def _build_pending_ask_contact() -> str:
    return (
        "ამ დროს გადავამოწმებ. დასადასტურებლად მომწერეთ თქვენი სახელი და "
        "საკონტაქტო ნომერი."
    )


def _build_pending_invalid_phone() -> str:
    return (
        "ნომერი ცოტა არასწორად ჩანს — 9-ციფრიანი ნომერი მჭირდება (5/7/8-ით "
        "დაწყებული). მაგ. 599 12 34 56."
    )


def _build_pending_unrelated_reminder(missing: list[str]) -> str:
    if "phone" in missing and "name" not in missing:
        return (
            "კონსულტაციის დასადასტურებლად ჯერ საკონტაქტო ნომერი მჭირდება. "
            "მომწერეთ ნომერი და დროს გადავამოწმებ."
        )
    if "name" in missing and "phone" not in missing:
        return (
            "კონსულტაციის დასადასტურებლად სახელი მჭირდება. "
            "გვითხარით თქვენი სახელი და დროს გადავამოწმებ."
        )
    return (
        "კონსულტაციის დასადასტურებლად თქვენი სახელი და საკონტაქტო ნომერი "
        "მჭირდება. მომწერეთ ცალცალკე ან ერთად."
    )


def _add_pending_reminder(base: str, pending: dict[str, Any]) -> str:
    """Append a short reminder to a factual answer (PART 5.C)."""
    missing = pending.get("missing_fields") or []
    if "phone" in missing and "name" in missing:
        tail = (
            "კონსულტაციის დასადასტურებლად კი თქვენი სახელი და საკონტაქტო "
            "ნომერი მჭირდება."
        )
    elif "phone" in missing:
        tail = (
            "კონსულტაციის დასადასტურებლად კი თქვენი საკონტაქტო ნომერი "
            "მჭირდება."
        )
    elif "name" in missing:
        tail = "კონსულტაციის დასადასტურებლად კი თქვენი სახელი მჭირდება."
    else:
        return base
    return f"{base}\n\n{tail}"


# A tight set of intents we explicitly honour while pending booking is
# active. Any intent NOT listed here is treated as continuation noise
# (we'll then attempt phone/name extraction and fall back to the gentle
# reminder).
_PENDING_INTERRUPT_INTENTS = (
    INTENT_IDENTITY_QUESTION,
    INTENT_MANAGER_REQUEST,
    INTENT_PRICE_QUESTION,
    INTENT_DATES_QUESTION,
    INTENT_LOCATION_QUESTION,
    INTENT_CONDITIONS_QUESTION,
    INTENT_REGISTRATION_QUESTION,
    INTENT_BOOKING_REQUEST,
)


def _has_georgian_letter(text: str) -> bool:
    """Used to filter out generic ASCII "Hi" / "ok" / etc. from being
    treated as a Georgian name during pending booking continuation.
    Most legitimate name candidates carry at least one Georgian letter;
    the rare English-name edge case is acceptable collateral here."""
    return bool(re.search(r"[ა-ჰ]", text or ""))


def _looks_like_phone_attempt(message: str) -> bool:
    """Does the message contain digits that could plausibly be a phone?

    Used after `_parse_name_phone` returns no phone — if the user typed
    digits AND we still don't have a valid phone, treat that as an
    invalid-phone attempt rather than an unrelated message.
    """
    if not message:
        return False
    digits = re.sub(r"\D", "", message)
    return len(digits) >= 3


def maybe_handle_pending_booking_continuation(
    conversation: Conversation, lead: Lead, message: str,
) -> str | None:
    """Continue a pending booking across turns. Returns string if handled.

    Priority order inside the continuation:

      1. Cancellation keywords → clear pending + polite response.
      2. Re-issued booking request with a NEW datetime → refresh the
         pending record's datetime then fall into continuation logic.
      3. Manager request → drop pending, hand off (PART 5.B). The manager
         handler will ask for a phone or confirm based on lead.phone.
      4. Identity question → answer briefly; pending preserved.
      5. Factual question (price/dates/location/conditions/registration)
         → answer briefly + reminder; pending preserved.
      6. Otherwise → parse name/phone via the canonical parser and update
         the lead. When all fields are filled, attempt the real Calendar
         booking. When some are still missing, ask premium-style for the
         missing piece. When the message is unrelated noise, gentle
         reminder.

    Never raises. Never advances state directly except through the
    booking-attempt path (which transitions to DONE only on Calendar
    success). Never stores a bare phone or unrelated message as
    challenge / deeper_concern / desired_change.
    """
    pending = conversation.pending_booking
    if not pending:
        return None

    sender_id = conversation.sender_id

    # 1. cancellation
    if _is_cancellation(message):
        logger.info(
            "[turn_router] pending_booking: cancelled by user (sender=%s)",
            sender_id,
        )
        conversation.pending_booking = None
        return _build_cancel_response()

    # 2. interrupts (identity / manager / factual / re-issued booking)
    det = detect_parent_interrupt_intent(message)
    if det is not None:
        intent = det["intent"]

        if intent == INTENT_MANAGER_REQUEST:
            logger.info(
                "[turn_router] pending_booking: manager interrupt — "
                "dropping pending, handing off (sender=%s)", sender_id,
            )
            conversation.pending_booking = None
            return _handle_manager_request(conversation, lead, message)

        if intent == INTENT_IDENTITY_QUESTION:
            logger.info(
                "[turn_router] pending_booking: identity interrupt — "
                "answering, pending preserved (sender=%s)", sender_id,
            )
            return _build_identity_answer()

        if intent == INTENT_BOOKING_REQUEST:
            # User re-issued the booking request, maybe with a new time.
            # Refresh the pending datetime and continue.
            new_dt = _parse_booking_datetime(message)
            if new_dt:
                pending["requested_datetime_iso"] = new_dt
                try:
                    from app.flows.parent_flow import GEORGIAN_MONTHS_NOM
                    slot_dt = datetime.fromisoformat(new_dt)
                    pending["requested_date_text"] = (
                        f"{slot_dt.day} {GEORGIAN_MONTHS_NOM[slot_dt.month]}"
                    )
                    pending["requested_time_text"] = slot_dt.strftime("%H:%M")
                except Exception as exc:  # display-only
                    logger.warning(
                        "[turn_router] pending: refresh date_text failed: %s", exc,
                    )
            # Fall through to continuation extraction below — they may
            # also have provided phone in the same message.

        elif intent in _PENDING_INTERRUPT_INTENTS:
            # Factual question — answer + reminder; pending preserved.
            logger.info(
                "[turn_router] pending_booking: factual interrupt %s — "
                "answer + reminder (sender=%s)", intent, sender_id,
            )
            base = _response_for_intent(intent, conversation, lead, message)
            if base is not None:
                return _add_pending_reminder(base, pending)

    # 3. continuation — extract name/phone via the canonical parser
    pending["attempts"] = pending.get("attempts", 0) + 1

    try:
        from app.flows.parent_flow import (
            _parse_name_phone,
            is_valid_person_name as parent_flow_is_valid_person_name,
        )
    except Exception as exc:
        logger.error("[turn_router] pending: parser import failed: %s", exc)
        return _build_pending_unrelated_reminder(
            pending.get("missing_fields") or ["phone"],
        )

    extracted_name, extracted_phone = _parse_name_phone(message)

    updated = False
    if extracted_phone and not lead.phone:
        lead.phone = extracted_phone
        updated = True
        logger.info(
            "[turn_router] pending_booking: phone captured (sender=%s)", sender_id,
        )

    if (
        extracted_name
        and _has_georgian_letter(extracted_name)
        and not lead.name
        # Live Bug 2 (2026-06-11) — never capture a month / date / time /
        # booking artifact as the name on the legacy continuation path.
        and parent_flow_is_valid_person_name(extracted_name)
    ):
        lead.name = extracted_name
        updated = True
        logger.info(
            "[turn_router] pending_booking: name captured (sender=%s, name=%r)",
            sender_id, extracted_name,
        )

    # Detect an invalid-phone attempt — digits present but the canonical
    # validator rejected them.
    if (
        not extracted_phone
        and not lead.phone
        and _looks_like_phone_attempt(message)
    ):
        logger.info(
            "[turn_router] pending_booking: invalid phone format "
            "(sender=%s, head=%r)", sender_id, (message or "")[:30],
        )
        return _build_pending_invalid_phone()

    # Recalculate what's still missing.
    missing = _missing_contact_fields(lead)
    pending["missing_fields"] = missing

    if not missing:
        logger.info(
            "[turn_router] pending_booking: all fields captured — "
            "attempting calendar booking (sender=%s)", sender_id,
        )
        # _attempt_router_booking clears pending_booking in both
        # success and failure paths.
        return _attempt_router_booking(
            conversation, lead, pending["requested_datetime_iso"],
        )

    if updated:
        # We made progress this turn; ask for what's still missing.
        if "phone" in missing and "name" not in missing:
            return _build_pending_ask_phone()
        if "name" in missing and "phone" not in missing:
            return _build_pending_ask_name()
        return _build_pending_ask_contact()

    # Nothing extractable from this message — gentle reminder.
    logger.info(
        "[turn_router] pending_booking: unrelated message — reminder "
        "(sender=%s, missing=%s)", sender_id, missing,
    )
    return _build_pending_unrelated_reminder(missing)
