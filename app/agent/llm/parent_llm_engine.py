"""P3-C SAFE — PARENT LLM engine (tool-calling loop).

The engine is the *reasoning* layer. It builds a compact system prompt
from ``system_parent_v2.md``, injects the current lead/state context,
appends the last ten conversation turns plus the current user message,
and asks OpenAI to either reply directly or call one of the closed-set
tools registered in ``parent_tools.PARENT_TOOLS``.

Tool execution runs through ``ParentToolExecutor`` (the security
boundary). The engine itself never books Calendar, never writes Sheets,
never notifies the manager — it only orchestrates the conversation.

Failure mode is *quiet*: any exception, or any empty final response,
returns ``""`` so ``parent_flow.handle`` can fall back to the existing
P0/P1/P2 state machine without crashing the webhook.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.agent.llm.prompt_loader import load_prompt
from app.agent.services.knowledge_loader import load_knowledge
from app.agent.services.timestamps import (
    now_tbilisi,
    resolve_relative_datetime,
)
from app.agent.tools.parent_tool_executor import ParentToolExecutor, serialize_result
from app.agent.tools.parent_tools import (
    DYNAMIC_PROGRAM_TOOLS,
    LEARNING_TOOLS,
    PARENT_TOOLS,
    TOPIC_TOOLS,
)
from app.config import settings
from app.domain.decision.models import ProgramId, reserved_program_ids
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.reasoning.age_question import (
    AGE_QUESTION_RE,
    contains_child_age_question,
    strip_child_age_questions,
)
from app.services import openai_service

logger = logging.getLogger(__name__)


def build_active_tools(
    use_dynamic: bool, use_learning: bool = False, use_topics: bool = False,
) -> list[dict]:
    """Flag-off ⇒ exactly PARENT_TOOLS (byte-identical). Flag-on ⇒ + generic
    program tools (`use_dynamic`) and/or the operator-approved-answer tool
    (`use_learning`) and/or the program-topic facts tool (`use_topics`). The
    three flags compose independently. `use_learning`/`use_topics` default to
    False so existing callers (e.g. the Phase-1 test's `build_active_tools(False)`
    / `build_active_tools(True)`) stay valid."""
    tools = list(PARENT_TOOLS)
    if use_dynamic:
        tools = tools + DYNAMIC_PROGRAM_TOOLS
    if use_learning:
        tools = tools + LEARNING_TOOLS
    if use_topics:
        tools = tools + TOPIC_TOOLS
    return tools


# Reserved program ids (Phase 0a hardening, 2026-07-20) — these three keep
# their curated deterministic handlers/tools and `get_program_info` REFUSES
# all of them (parent_tool_executor._get_program_info, reason
# "use_specific_tool"). Previously this suffix only excluded "summer_camp",
# so an active `sunday_school`/`adult_events` section was listed as a
# "dynamic" program the LLM should call get_program_info on — a
# self-contradiction (the tool would then refuse it). Single source of truth:
# `app.domain.decision.models.ProgramId`, the same enum `parent_flow.py` and
# `parent_tool_executor.py` derive their own `_HARDCODED_PROGRAM_IDS` from.
_RESERVED_PROGRAM_IDS = frozenset(p.value for p in ProgramId)


def _dynamic_programs_prompt_suffix() -> str:
    """Tell the LLM the generic tools exist and list active non-reserved programs.
    Empty string when the flag is off or there are none (so flag-off prompt is unchanged)."""
    if not getattr(settings, "USE_DYNAMIC_PROGRAMS", False):
        return ""
    try:
        from app.services import admin_config_service
        others = [
            s for s in admin_config_service.get_active_sections()
            if s.get("id") not in reserved_program_ids()
        ]
    except Exception:
        return ""
    if not others:
        return ""
    names = ", ".join(f"{s.get('name')} (id: {s.get('id')})" for s in others if s.get("id"))
    suffix = (
        "\n\n[დინამიური პროგრამები] გარდა ბანაკისა, აქტიურია: " + names +
        ". ამ პროგრამებზე ნებისმიერ კითხვაზე ჯერ გამოიძახე list_programs, "
        "შემდეგ get_program_info(program_id). ფაქტები მხოლოდ ხელსაწყოს პასუხიდან "
        "აიღე — არასდროს მოიგონო."
    )
    if getattr(settings, "USE_PROGRAM_ISOLATION", False):
        # Program isolation (2026-07-23): each program is self-contained. When
        # answering about a specific non-camp program, use ONLY that program's
        # get_program_info data and never borrow another program's (e.g. camp's)
        # location/price/age/date. Fixes the eval leak where a robotics answer
        # invented the camp location „ამბასადორი".
        suffix += (
            " თითოეული პროგრამა დამოუკიდებელია: კონკრეტული პროგრამის კითხვაზე "
            "გამოიყენე მხოლოდ ამ პროგრამის get_program_info-ს მონაცემი და არასდროს "
            "აურიო სხვა პროგრამის (მაგალითად ბანაკის) ლოკაცია, ფასი, ასაკი ან თარიღი. "
            "თუ ამ პროგრამის კონკრეტული დეტალი ხელსაწყოში არ არის, თქვი რომ დეტალს "
            "მენეჯერი დააზუსტებს — არ ჩაანაცვლო სხვა პროგრამის ფაქტით."
        )
    if getattr(settings, "USE_DYNAMIC_CONTACT_CAPTURE", False):
        # Dynamic contact capture (2026-07-23): the multi-turn contact turn
        # reaches the engine but the LLM sometimes only acknowledges the
        # name/phone in text and skips save_lead_info (eval RC-CC1 turn2=[]).
        suffix += (
            " როცა მომხმარებელი მოგაწვდის სახელს ან/და ტელეფონის ნომერს, "
            "დაუყოვნებლივ გამოიძახე save_lead_info მათ ჩასაწერად (name/phone) — "
            "მხოლოდ ტექსტში დადასტურება არ არის საკმარისი."
        )
    return suffix


def _approved_answer_prompt_suffix() -> str:
    """Tell the LLM to check for an operator-approved answer on an unclear
    question. Empty string when the flag is off (so flag-off prompt is
    unchanged) — mirrors the `_dynamic_programs_prompt_suffix` guard."""
    if not getattr(settings, "USE_LEARNING", False):
        return ""
    return (
        "\n\n[დამტკიცებული პასუხები] გაურკვეველ ან ვარიაციულ კითხვაზე ჯერ "
        "გამოიძახე get_approved_answer(question). თუ დაბრუნდა ოპერატორის "
        "დამტკიცებული პასუხი (success:true), გამოიყენე ის. თუ არა "
        "(success:false), უპასუხე ჩვეულებრივ."
    )


def _topic_tool_prompt_suffix() -> str:
    """Tell the LLM the program-topic facts tool exists. Empty string when the
    flag is off (so flag-off prompt is unchanged) — mirrors
    `_approved_answer_prompt_suffix`."""
    if not getattr(settings, "USE_PROGRAM_TOPICS", False):
        return ""
    return (
        "\n\nროცა მშობელი კითხულობს ბანაკის კონკრეტულ თემაზე (უსაფრთხოება, კვება, "
        "გაჯეტები, სამედიცინო, მშობელთან კომუნიკაცია, განთავსება, დასვენება), "
        "გამოიძახე get_program_topic და უპასუხე დაბრუნებული ფაქტებით — ბუნებრივად, "
        "არ გამოიგონო. თუ თემა ვერ მოიძებნა (success=false), უპასუხე ბუნებრივად, "
        "ფაქტების გამოგონების გარეშე. უსაფრთხოებისა და სამედიცინო კითხვებზე ჯერ "
        "get_program_topic-ის დამამშვიდებელი ფაქტები თქვი (მაგ. სამედიცინო "
        "პერსონალი 24/7), და მხოლოდ მერე, თუ მშობლის საჭიროება ინდივიდუალურია "
        "(მაგ. კონკრეტული წამლის გრაფიკი), შესთავაზე მენეჯერთან დაკავშირება — "
        "პირდაპირ მენეჯერზე ნუ გადახვალ ფაქტების გარეშე."
    )


def _skills_prompt_suffix(message: str = "", segment: str = "") -> str:
    """Inject the situational SKILL.md capability pack(s) selected for this turn.
    Empty string when USE_SKILLS is off OR nothing matches, so the flag-off (and
    no-match) prompt is byte-identical. Never raises."""
    if not getattr(settings, "USE_SKILLS", False):
        return ""
    try:
        from app.services import skills_service
        skills = skills_service.select_skills(message, segment)
    except Exception:
        return ""
    blocks = "\n\n".join(
        f"### {s.get('name')}\n{(s.get('body') or '').strip()}"
        for s in skills if (s.get("body") or "").strip()
    )
    if not blocks.strip():
        return ""
    return (
        "\n\n[სიტუაციური უნარები] ქვემოთ მოცემული სახელმძღვანელო(ები) "
        "მიესადაგება ამ საუბარს — გამოიყენე მათი მიდგომა პასუხში:\n\n" + blocks
    )


def _trace_parent_llm_decision(**fields) -> None:
    try:
        from app.reasoning import conversation_trace as _trace

        payload = {
            "domain": "camp",
            "used_llm": True,
        }
        payload.update(fields)
        _trace.set_route_decision(**payload)
    except Exception:  # pragma: no cover - trace must never affect replies
        pass

# Generous cap on the tool-call → tool-result → next-call loop. Five
# iterations comfortably cover the realistic case (camp_info + slots +
# book + final answer = 4 LLM turns) while still bounding worst-case
# token spend. Beyond five we treat the model as confused and bail.
MAX_TOOL_ITERATIONS = 5


# Standalone 1–2 digit number — used by the post-turn child_age fallback.
_AGE_TOKEN_PATTERN = re.compile(r"(?<!\d)(\d{1,2})(?!\d)")

# FIX 4 / M1 (2026-06-13) — spelled-out Georgian cardinals for the camp age
# band (9–17). Resolved ONLY with age context (the same წლ/წელ/child-word/
# pending gate as the digit path) and only as a WHOLE token, so „ცხრა"/„ათი"
# never fire inside an unrelated word. Digit parsing is unchanged.
_GEORGIAN_AGE_NUMERALS: dict[str, int] = {
    "ცხრა": 9, "ათი": 10, "თერთმეტი": 11, "თორმეტი": 12, "ცამეტი": 13,
    "თოთხმეტი": 14, "თხუთმეტი": 15, "თექვსმეტი": 16, "ჩვიდმეტი": 17,
}

# B1 fix (2026-06-13) — explicit age self-correction. A correction marker lets
# the user UPDATE an already-set child_age („არა, 15" / „აბა 9 წლის"). STRONG
# markers may also relax the bare-number age-context gate so „არა, 15" (no
# „წლის") still updates the age; „აბა" is too common a filler to relax the
# bare-number gate, so it only triggers an overwrite alongside an explicit age
# word. A SECOND / different-child mention is NEVER a correction — it must keep
# the first child's age („10 და 14 წლის" / „ჩემი მეორე შვილი 14 წლისაა").
_AGE_CORRECTION_MARKERS: tuple[str, ...] = (
    "არა", "შევცვალე", "უფრო სწორად", "ვგულისხმობდი", "აბა",
)
_AGE_CORRECTION_STRONG_MARKERS: tuple[str, ...] = (
    "არა", "შევცვალე", "უფრო სწორად", "ვგულისხმობდი",
)
_AGE_CORRECTION_EXCLUDE: tuple[str, ...] = (
    "მეორე შვილ", "მეორე ბავშვ", "სხვა შვილ", "სხვა ბავშვ",
)


def _is_explicit_age_correction(message: str, *, strong_only: bool = False) -> bool:
    """True when the message explicitly CORRECTS a previously-stated child age
    („არა, 15" / „აბა 9 წლის"). A second/different-child mention is excluded —
    that keeps the first child's age. ``strong_only`` uses the narrower marker
    set that may relax the bare-number age gate."""
    low = (message or "").lower()
    if not low:
        return False
    if any(x in low for x in _AGE_CORRECTION_EXCLUDE):
        return False
    markers = (
        _AGE_CORRECTION_STRONG_MARKERS if strong_only else _AGE_CORRECTION_MARKERS
    )
    return any(m in low for m in markers)

# Phone-context tokens. When any of these appear in the message we treat
# any digits as phone fragments, not age — this prevents "595 ..." or
# "ნომერი 599..." from being misread as the child's age.
_PHONE_HINT_TOKENS: tuple[str, ...] = (
    "ნომერ", "ტელეფონ", "მობილურ",
    "+995", "595", "598", "599", "555", "557", "511", "574", "577", "568",
)

# Age-range / menu-echo patterns (FIX 1, 2026-06-11). The camp's
# advertised age band („9-17", „9 წლიდან 17 წლამდე", „9 დან 17") must
# NEVER be read as the child's actual age — that was the live bug
# („ბავშვების საზაფხულო ბანაკი 9-17" → child_age wrongly set to „9").
_AGE_RANGE_DASH_PATTERN = re.compile(r"\d+\s*[-–—]\s*\d+")
_AGE_RANGE_DAN_PATTERN = re.compile(r"\d+\D{0,5}დან\D{0,8}\d+")

# Stems that, immediately after a number, mark it as a clock time or a
# calendar date rather than an age („12 საათზე", „11 ივნისს", „20:00").
# „ზე" / „-ზე" is the colloquial Georgian hour marker („8-ზე" = „at 8",
# i.e. 20:00 per timestamps.extract_colloquial_hour). Without it a time
# like „შვილი 8-ზე მოვა" („my child arrives at 8") would leak „8" as the
# child's age — the same bug class as the „9-17" range leak.
_TIME_DATE_AFTER_STEMS: tuple[str, ...] = (
    "საათ", "სთ", "ზე",
    "ივნ", "ივლ", "აგვ", "სექ", "ოქტ", "ნოემ", "დეკ",
    "იან", "თებ", "მარ", "აპრ", "მაის",
)


def _contains_age_range(message: str) -> bool:
    """True when the message carries a numeric range („9-17", „9 დან 17",
    „… 17 წლამდე") — i.e. the camp age band / menu, not a single age."""
    if not message:
        return False
    if _AGE_RANGE_DASH_PATTERN.search(message):
        return True
    if _AGE_RANGE_DAN_PATTERN.search(message):
        return True
    if "წლამდე" in message and any(ch.isdigit() for ch in message):
        return True
    return False


def _number_is_time_or_date(message: str, match: "re.Match[str]") -> bool:
    """True when the matched number is immediately followed by a time
    („12 საათზე", „20:00") or month-name date („11 ივნისს") marker."""
    end = match.end(1)
    rest = message[end:end + 16]
    if rest[:1] == ":":  # HH:MM
        return True
    rest_l = rest.lower().lstrip(" -")
    return any(rest_l.startswith(stem) for stem in _TIME_DATE_AFTER_STEMS)


def _strip_phone_numbers(message: str) -> str:
    """Return ``message`` with any recognised Georgian phone number removed.

    Live bug (2026-06-20): a phone in the SAME turn („14 წლის არის
    595999733") must not block child-age capture, and its digits must never
    be misread as an age. We strip the phone BEFORE age extraction — the
    standalone 1–2 digit age pattern already cannot match inside a 9-digit
    run, and stripping also removes spaced-phone fragments („595 99 97 33")
    that could otherwise leak a 2-digit token. Reuses the canonical phone
    detector; on any failure it falls back to stripping 7+ digit runs.
    """
    if not message:
        return message
    out = message
    try:
        from app.flows.parent_flow import (
            PHONE_CANDIDATE_PATTERN, VALID_LOCAL_PREFIXES,
        )

        for match in PHONE_CANDIDATE_PATTERN.finditer(message):
            token = match.group(0)
            digits = re.sub(r"\D", "", token)
            if not digits:
                continue
            local = digits[3:] if digits.startswith("995") else digits
            is_local_phone = (
                len(local) == 9 and local[0] in VALID_LOCAL_PREFIXES
            )
            # A clean local phone OR any long digit run (≥7) is a phone, not
            # an age — strip it. Short runs (an age, a count) are preserved.
            if is_local_phone or len(digits) >= 7:
                out = out.replace(token, " ", 1)
    except Exception:
        # Defensive fallback — never let phone stripping break age capture.
        out = re.sub(r"\d{7,}", " ", message)
    return out


def maybe_capture_child_age_fallback(
    lead: Lead, message: str, *, age_question_pending: bool = False,
) -> None:
    """Belt-and-braces structured capture of the child's age when the
    LLM acknowledges it verbally but skips ``save_lead_info``.

    Conservative + state-aware by design (FIX 1, 2026-06-11):

    * No-op when ``lead.child_age`` is already populated — never
      overwrites.
    * NEVER extracts from an age RANGE / menu echo („9-17",
      „9 დან 17 წლამდე") — that is the camp's advertised band, not the
      child's age. This was the live bug.
    * NEVER reads a number that is a clock time („12 საათზე", „20:00")
      or a calendar date („11 ივნისს") as an age.
    * Only matches *standalone* 1–2 digit numbers, so a Georgian phone
      „595999733" / „+995595999733" never gets misread as age.
    * Requires AGE CONTEXT: an explicit „წლ/წელ" mention, a child word
      („შვილ"/„ბავშვ"), OR ``age_question_pending`` (the bot just asked
      for the child's age). A bare number outside any age context is
      NOT captured.
    * Accepts only the structured ``5..20`` range. Eligibility is still
      enforced separately by the tool executor; this helper only
      ensures the value lands on the Lead so downstream booking / email
      / Sheets / follow-up have the field.
    * Multiple ages (``"11 და 14"`` — two children): keeps the FIRST
      valid age and stops. Never combines, never crashes.
    * Pure mutation on ``lead.child_age``. Never triggers booking,
      never alters response text, never calls an external service.
    """
    if lead is None:
        return
    if not message:
        return
    # B1 fix (2026-06-13): the first captured age is normally locked (no
    # overwrite), EXCEPT when the message is an explicit correction. A
    # second/different-child mention is not a correction (see helper).
    existing_child_age = (lead.child_age or "").strip()
    is_correction = bool(existing_child_age) and _is_explicit_age_correction(message)
    if existing_child_age and not is_correction:
        return
    is_strong_correction = bool(existing_child_age) and _is_explicit_age_correction(
        message, strong_only=True,
    )

    # Live bug fix (2026-06-20): a phone in the SAME message („14 წლის არის
    # 595999733") must NOT block age capture. Strip recognised phone numbers
    # FIRST, then read the age from what remains. (Previously any phone
    # prefix — „595…" — bailed out of age capture entirely, so the parent
    # got asked the child's age again and again.)
    age_source = _strip_phone_numbers(message)
    text = age_source.lower()

    # FIX 1 — never treat the camp's advertised age band / a range as the
    # child's age.
    if _contains_age_range(age_source):
        logger.info(
            "[lead_capture] age range / menu echo ignored (head=%r)",
            age_source[:60],
        )
        return

    # Age context gate: without an explicit age word, a child word, or a
    # pending age question, a bare number is a price / count / time / phone,
    # not the child's age.
    has_age_word = "წლ" in text or "წელ" in text
    has_child_word = "შვილ" in text or "ბავშვ" in text
    if not (
        has_age_word or has_child_word or age_question_pending
        or is_strong_correction  # B1: „არა, 15" (bare number) updates the age
    ):
        return

    for match in _AGE_TOKEN_PATTERN.finditer(age_source):
        if _number_is_time_or_date(age_source, match):
            continue
        try:
            age = int(match.group(1))
        except ValueError:
            continue
        if 5 <= age <= 20:
            lead.child_age = str(age)
            logger.info(
                "[lead_capture] child_age fallback captured age=%s "
                "(message head=%r)",
                age, age_source[:60],
            )
            return

    # FIX 4 / M1 (2026-06-13) — no DIGIT age captured above → try a spelled-out
    # Georgian numeral (whole token). The age-context gate already passed, so
    # „ცამეტი წლის" → 13 while a bare „ცამეტი" with no context never reaches
    # here. Age ranges („9-17") are already excluded above.
    for raw_tok in re.split(r"[\s,.:!?\-]+", text):
        if raw_tok in _GEORGIAN_AGE_NUMERALS:
            spelled_age = _GEORGIAN_AGE_NUMERALS[raw_tok]
            lead.child_age = str(spelled_age)
            logger.info(
                "[lead_capture] child_age spelled-out numeral captured age=%s "
                "(message head=%r)",
                spelled_age, age_source[:60],
            )
            return


# A COMPACT multi-age expression: two+ 1-2 digit numbers connected by a range
# dash, „და", or comma (optionally with an intervening „წლ…", repeated). This is
# how a parent states siblings' ages — „12-14" / „12 და 14" / „12, 14" /
# „12 წლის და 14 წლის" / „12 და 14 და 16" — NOT two numbers scattered across a
# sentence in different roles („10 დღიანია? … ჩემი შვილი 14 წლისაა").
_MULTI_AGE_EXPR_PATTERN = re.compile(
    r"(?<!\d)\d{1,2}(?:\s*წლ\w*)?\s*(?:[-–—]|და|,)\s*"
    r"\d{1,2}(?:(?:\s*წლ\w*)?\s*(?:და|,)\s*\d{1,2})*(?!\d)"
)
# Camp-eligibility QUESTION markers — „ბანაკი 12-14 წლის ბავშვებისთვისაა?" asks
# who the camp is FOR; combined with „ბანაკ" it is never a parent stating their
# OWN children's ages.
_ELIGIBILITY_TARGET_MARKERS: tuple[str, ...] = (
    "ბავშვებისთვის", "ბავშვებზეა", "ასაკისთვისაა", "წლისთვისაა", "ვისთვის",
)


def extract_distinct_child_ages(
    message: str, *, age_min: int = 9, age_max: int = 17,
    age_question_pending: bool = False,
) -> list[int]:
    """Return the distinct plausible child ages (5–20) a parent stated in a
    COMPACT multi-age expression, first-seen order.

    Detects the sibling-age forms „12-14 წლის" / „12 და 14 წლის" / „12, 14 წლის"
    / „12 წლის და 14 წლის" (and a bare „12 და 14" / „12-14" right after the age
    question, via ``age_question_pending``). Returns ``[]`` when:
      * there is NO compact multi-age expression — a lone single age is NOT
        multi-child (left to the single-age fallback), and two numbers scattered
        across a sentence in different roles („10 დღიანია … 14 წლისაა") are not
        harvested;
      * the expression is the advertised camp band (dash-range on the EXACT
        bounds „9-17", or a „…დან…წლამდე" construction);
      * the message is a camp-eligibility QUESTION („ბანაკი … ბავშვებისთვისაა?");
      * there is no age context (no წლ/წელ, no child word, no
        ``age_question_pending``).

    Numbers are limited to 5–20 so a phone / price / day-count is never
    harvested. Callers treat ``len(ages) >= 2`` as the multi-child signal, and
    should filter to ``age_min..age_max`` for the single-value booking gate.
    Pure — never mutates the lead, never asks anything, never books.
    """
    if not message:
        return []
    age_source = _strip_phone_numbers(message)
    text = age_source.lower()
    # Age context is required (or the bot just asked the age — a bare „12 და 14").
    has_age_word = "წლ" in text or "წელ" in text
    has_child_word = "შვილ" in text or "ბავშვ" in text
    if not (has_age_word or has_child_word or age_question_pending):
        return []
    # A camp-eligibility QUESTION („ბანაკი … ბავშვებისთვისაა?") is not the
    # parent's OWN children's ages.
    if "ბანაკ" in text and any(m in text for m in _ELIGIBILITY_TARGET_MARKERS):
        return []
    # Advertised-band „…დან…წლამდე" construction → never child ages.
    if _AGE_RANGE_DAN_PATTERN.search(age_source) or "წლამდე" in text:
        return []
    try:
        lo_bound, hi_bound = int(age_min), int(age_max)
    except (TypeError, ValueError):
        lo_bound, hi_bound = 9, 17
    # A COMPACT multi-age expression must be present — otherwise this is not a
    # sibling-age input.
    expr = _MULTI_AGE_EXPR_PATTERN.search(age_source)
    if not expr:
        return []
    span = expr.group(0)
    nums = [int(n) for n in re.findall(r"\d{1,2}", span)]
    # A dash-range on the EXACT camp bounds is the advertised band, not ages.
    is_dash = any(d in span for d in ("-", "–", "—"))
    if is_dash and len(nums) == 2 and {nums[0], nums[1]} == {lo_bound, hi_bound}:
        return []
    # Distinct plausible child ages (5–20), first-seen order.
    ages: list[int] = []
    for n in nums:
        if 5 <= n <= 20 and n not in ages:
            ages.append(n)
    return ages


def maybe_capture_phone_fallback(lead: Lead, message: str) -> None:
    """Belt-and-braces capture of the parent's phone — the phone counterpart
    of :func:`maybe_capture_child_age_fallback`. Lets the deterministic state
    hold the phone even when the LLM acknowledges it in prose but skips
    ``save_lead_info`` (live bug: „14 წლის არის 595999733" left the phone
    un-persisted on the direct-answer path).

    Conservative by design:

    * No-op when ``lead.phone`` is already set — never overwrites.
    * No-op unless EXACTLY ONE distinct valid 9-digit Georgian number is
      present — two numbers must be disambiguated by the agent, not guessed.
    * Reuses the canonical ``parent_flow`` phone parser; never duplicates the
      regex. Pure mutation on ``lead.phone`` — NEVER touches ``child_age`` /
      ``name`` / any other field, never books, never calls a service.
    """
    if lead is None or not message:
        return
    if (lead.phone or "").strip():
        return
    try:
        from app.flows.parent_flow import (
            _parse_name_phone, _distinct_valid_phones,
        )
    except Exception:  # pragma: no cover - import safety
        return
    try:
        if len(_distinct_valid_phones(message)) != 1:
            return
        _name, phone = _parse_name_phone(message)
    except Exception:
        logger.exception("[lead_capture] phone fallback raised — ignored")
        return
    if phone:
        lead.phone = phone
        logger.info(
            "[lead_capture] phone fallback captured (mask=***%s)",
            phone[-3:] if len(phone) >= 3 else "***",
        )


def _bot_recently_asked_child_age(conversation: Conversation) -> bool:
    """True when the most recent assistant turn asked for the child's
    age — used to allow a bare standalone number („12") to be read as
    the child's age ONLY in that state."""
    history = list(getattr(conversation, "history", []) or [])
    for turn in reversed(history):
        if not isinstance(turn, dict):
            continue
        if turn.get("role") != "assistant":
            continue
        content = str(turn.get("content") or "").lower()
        return (
            "რამდენი წლის" in content
            or "შვილის ასაკი" in content
            or "ბავშვის ასაკი" in content
        )
    return False


# -- challenge fallback ----------------------------------------------------
#
# Closed-set Georgian stems for the four challenge categories the live
# data shows most often. Each category maps onto the stems / phrases
# the parent typically uses. The capture is conservative: we never
# invent a clinical label and never use the word "პრობლემა" unless the
# user wrote it.

_CHALLENGE_CATEGORIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("screen", (
        "ეკრან", "ტელეფონ", "გაჯეტ", "თამაშ", "იუთუბ", "ტიკტოკ",
        "სმარტფონ",
    )),
    ("communication", (
        "კომუნიკაცი", "ურთიერთობ", "მეგობრ", "სოციალიზ", "ჩაკეტილ",
        "მორცხვ", "მარტო ი",
    )),
    ("confidence", (
        "თავდაჯერ", "გამოხატ", "შიში", "ერიდება", "არ აქტიურობს",
    )),
    ("development", (
        "განვითარ", "ახალი გარემო", "თავგადასავალ", "დამოუკიდებე",
        "ქართულ", "ენა", "ზაფხული",
    )),
)

# Tokens that, when present, mean the message is contact / slot disclosure
# rather than concern. We refuse to capture challenge in these cases so a
# phone or a slot answer never lands on ``lead.challenge`` by accident.
_CHALLENGE_SKIP_TOKENS: tuple[str, ...] = (
    "ნომერ", "ტელეფონის ნომერი", "+995",
    "595", "598", "599", "555", "557", "511", "574", "577", "568",
    "საათზე", ":00", ":30",
    # Lead Field Separation Patch (2026-06-04) — adult cultural-event
    # vocabulary. A PARENT-flow challenge fallback must never capture
    # adult-event interest; that belongs on ``lead.event_interest`` and
    # is owned by the ADULT executor.
    "ზრდასრულთა", "ზრდასრულ",
    "კულტურულ საღამო", "კულტურული საღამო",
    "კულტურულ ღონისძიებ", "კულტურული ღონისძიებ",
    "ღონისძიებ",
    "საღამოს ღონისძიებ",
    "ბილეთ",
    "პოეზიის საღამო",
)

# Minimum length so single-word noise ("ჰო", "კი") never gets stored.
_CHALLENGE_MIN_LEN = 6
# Upper cap so we never ship a multi-paragraph user rant as a CRM field.
_CHALLENGE_MAX_LEN = 200


# ---------------------------------------------------------------------------
# Challenge save-path cleanup (Live Bug 4, 2026-06-11).
#
# A parent often states a real camp goal AND tacks on a separate factual
# question in the same message („…მეგობრები და ასევე მაინტერესებს ბანაკი
# როდის ტარდება?"). Only the goal belongs in ``lead.challenge`` (which is
# written verbatim to the Sheets CRM via ``Lead.to_sheet_row``); the
# question must NOT pollute it. This cleans the value at the SAVE
# chokepoint so the Sheet row itself is clean — distinct from
# ``notification_service._clean_challenge_for_email`` which only cleans the
# manager-email rendering and (deliberately) canonicalises wording.
#
# Unlike the email cleaner, this preserves the parent's own wording (no
# canonicalisation) — it only DROPS factual-question clauses and strips
# leading connective filler.
# ---------------------------------------------------------------------------

# A clause containing any of these is a factual question, not a goal. The
# stems are deliberately specific (multi-char phrases, not bare „სად" /
# „ღირ"/„ღირებულება") so a real goal („ახალი გარემო", „თვითღირსება",
# „ღირებულებები") is never dropped.
_CHALLENGE_QUESTION_STEMS: tuple[str, ...] = (
    "?",
    "როდის", "საათზე",
    "რა ღირს", "რამდენი ღირს", "ფასი",
    "რა შედის", "რას მოიცავ", "რა შემავალ",
    "როგორ ჩავეწერ", "როგორ ჩავწერ", "როგორ დავრეგისტრირდე",
    "სად ტარდება", "სად არის", "სად იქნება",
    "რა იგულისხმება", "პირობებში რა",
)

# Leading connective filler stripped from a kept clause. Longest first so a
# shorter substring never pre-empts the full phrase.
_CHALLENGE_LEADING_FILLER: tuple[str, ...] = (
    "და ასევე მაინტერესებს", "ასევე მაინტერესებს",
    "ასევე მინდა ვიცოდე", "მაინტერესებს ასევე",
    "და ასევე", "ასევე", "მაინტერესებს",
)


def _split_challenge_clauses(raw: str) -> list[str]:
    """Split a raw challenge string into clauses on commas / semicolons and
    the connector „ასევე". A standalone „და" inside a clause is left intact
    so a legitimate two-goal clause („ეკრანი და კომუნიკაცია") keeps its
    natural wording — the „და"-split only kicks in for QUESTION clauses, to
    salvage a leading goal (see ``clean_challenge_for_storage``)."""
    parts = re.split(r"[,;]|\bასევე\b", raw or "")
    return [p.strip(" .,-—\t") for p in parts if p.strip(" .,-—\t")]


def _salvage_goal_before_question(clause: str) -> str:
    """A clause is a factual question, but it may carry a leading goal
    joined by „და" („კომუნიკაცია და როდის ტარდება?"). Split on the
    standalone „და" connector and return the non-question goal sub-parts
    (preserving wording), or "" when nothing salvageable remains.

    `\\bდა\\b` matches only the standalone word „და" — never a substring,
    so „დასთან" / „დამოუკიდებლობა" are unaffected."""
    kept: list[str] = []
    for sub in re.split(r"\bდა\b", clause or ""):
        sub = sub.strip(" .,-—\t")
        if not sub or _challenge_clause_is_question(sub):
            continue
        cleaned = _strip_challenge_clause_filler(sub)
        if cleaned:
            kept.append(cleaned)
    return ", ".join(kept)


def _challenge_clause_is_question(clause: str) -> bool:
    low = (clause or "").casefold()
    return any(stem in low for stem in _CHALLENGE_QUESTION_STEMS)


def _strip_challenge_clause_filler(clause: str) -> str:
    out = clause or ""
    for filler in _CHALLENGE_LEADING_FILLER:
        out = re.sub(re.escape(filler), " ", out, flags=re.IGNORECASE)
    out = re.sub(r"\s+", " ", out).strip(" .,-—\t")
    # Drop a dangling connector „და" left after splitting on „ასევе".
    if out.endswith(" და"):
        out = out[:-3].strip(" .,-—\t")
    if out in {"და", "ასევე"}:
        out = ""
    return out


def clean_challenge_for_storage(raw: str | None) -> str:
    """Return only the meaningful camp goal(s) from a raw challenge
    string — factual-question clauses and connective filler removed —
    preserving the parent's own wording (no canonicalisation). Returns ""
    when nothing meaningful remains (e.g. the message was ONLY a question).
    """
    base = (raw or "").strip()
    if not base:
        return ""
    kept: list[str] = []
    seen: set[str] = set()
    for clause in _split_challenge_clauses(base):
        if _challenge_clause_is_question(clause):
            # The clause is a question, but it may carry a leading goal
            # joined by „და" („კომუნიკაცია და როდის ტარდება?") — salvage it.
            cleaned = _salvage_goal_before_question(clause)
        else:
            cleaned = _strip_challenge_clause_filler(clause)
        if not cleaned:
            continue
        key = cleaned.casefold()
        if key in seen:
            continue
        seen.add(key)
        kept.append(cleaned)
    return dedupe_challenge_text(", ".join(kept))


# Challenge text dedupe (Cleanup Fix 2026-06-11 — BUG B).
#
# Live bug: the stored PARENT `lead.challenge` (written verbatim to the
# Sheets CRM) carried a repeated concept — „მეგობრები კომუნიკაცია მეგობრები
# კომუნიკაცია". The manager email already deduped via
# `notification_service._dedupe_repeated_phrase`; the SAVE path did not, so
# the Sheet row diverged. This collapses a verbatim repeated block at the
# save chokepoint so the Sheet payload matches the email payload. Kept
# duplicated (not imported from notification_service) to avoid pulling the
# SMTP chain into the conversation hot path.


def _dedupe_repeated_block(text: str) -> str:
    """Collapse a verbatim repeated block: „X Y X Y" → „X Y", „X X" → „X".

    Splits on each space/comma boundary and returns the left half when the
    left and right halves are case-insensitively identical."""
    s = (text or "").strip()
    if not s:
        return s
    for idx in range(1, len(s)):
        if s[idx] not in (" ", ","):
            continue
        left = s[:idx].strip(" ,")
        right = s[idx:].strip(" ,")
        if left and right and left.casefold() == right.casefold():
            return left
    return s


def challenge_word_set(text: str) -> set[str]:
    """Case-folded word set of a challenge string (separators dropped).
    Used to detect when a new challenge's concepts are already covered by
    the existing one (comma/space-insensitive), without word-level mangling
    of legitimate multi-word concepts."""
    return {w for w in re.split(r"[\s;,]+", (text or "").casefold()) if w}


def dedupe_challenge_text(text: str) -> str:
    """Deduplicate repeated concepts in a challenge string — clause-level
    (on commas/semicolons) plus a verbatim repeated block — preserving order
    and the parent's wording. Idempotent."""
    s = (text or "").strip()
    if not s:
        return s
    parts = re.split(r"\s*[;,]\s*", s)
    seen: set[str] = set()
    kept: list[str] = []
    for p in parts:
        p = _dedupe_repeated_block(p.strip(" .,-—\t"))
        if not p:
            continue
        k = p.casefold()
        if k in seen:
            continue
        seen.add(k)
        kept.append(p)
    return _dedupe_repeated_block(", ".join(kept))


def maybe_capture_challenge_fallback(lead: Lead, message: str) -> None:
    """Belt-and-braces structured capture of the parent's stated
    concern / interest when the LLM acknowledges it verbally but
    doesn't call ``save_lead_info``.

    Conservative by design — same contract as
    ``maybe_capture_child_age_fallback``:

    * No-op when ``lead.challenge`` is already populated. Never
      overwrites.
    * Requires a recognisable challenge stem (closed-set Georgian
      keyword groups: screen / communication / confidence /
      development). Single greetings, "კი", "ჰო", "მადლობა",
      phone disclosures, and slot answers don't trigger.
    * Stores the *original* short user phrase trimmed and length-
      capped — never invents a label, never uses the word
      "პრობლემა" unless the parent wrote it.
    * Pure mutation on ``lead.challenge``. Never triggers booking,
      never alters response text, never calls Calendar / Sheets /
      Notification / Redis.
    """
    if lead is None:
        return
    if (lead.challenge or "").strip():
        return
    if not message:
        return

    text = message.strip()
    if len(text) < _CHALLENGE_MIN_LEN:
        return

    lowered = text.lower()

    # Refuse contact / slot disclosures.
    for skip in _CHALLENGE_SKIP_TOKENS:
        if skip in lowered:
            return

    matched_category: str | None = None
    for category, stems in _CHALLENGE_CATEGORIES:
        if any(stem in lowered for stem in stems):
            matched_category = category
            break
    if matched_category is None:
        return

    # Length cap. We preserve the parent's exact wording within the
    # cap so the manager email reads naturally.
    captured = text if len(text) <= _CHALLENGE_MAX_LEN else text[:_CHALLENGE_MAX_LEN].rstrip()
    # Live Bug 4 (2026-06-11) — drop any tacked-on factual question so the
    # Sheets challenge column stores only the camp goal, never the user's
    # separate question („…მეგობრები და ასევე მაინტერესებს ბანაკი როდის
    # ტარდება?" → „…მეგობრები").
    cleaned = clean_challenge_for_storage(captured)
    if not cleaned:
        return
    lead.challenge = cleaned
    logger.info(
        "[lead_capture] challenge fallback captured category=%s text=%r",
        matched_category, cleaned[:80],
    )


# Window of conversation history we forward to the LLM. The model also
# has its own context limit; ten turns is a sane default that keeps
# prompt-token cost predictable.
HISTORY_WINDOW = 10

DEFAULT_MAX_TOKENS = 500
DEFAULT_TEMPERATURE = 0.7


# P3-C PATCH 1 + PATCH 2 — robotic / literal phrases the live tests
# surfaced. When the LLM emits any of these, the engine rewrites the
# offending phrase into the preferred Georgian wording. Replacement is
# done as a final string pass: it is intentionally simple (no regex /
# morphology) so a new entry can be added without test churn.
# Replacements are applied in declaration order — keep the more
# specific patterns first.
FORBIDDEN_PHRASE_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    # Live P0/P1 Hotfix BUG C (2026-06-15) — „მოგიწოდებთ, მომწერეთ…" reads as
    # abrupt/wrong. The verb is LLM free-generation (not in any template), so
    # rewrite it deterministically to the neutral „გთხოვთ" here.
    ("მოგიწოდებთ", "გთხოვთ"),
    # PATCH 1 — phone/help robotic phrases
    (
        "გაიმეორეთ, გთხოვთ, თქვენი ტელეფონის ნომერი",
        "მომწერეთ თქვენი 9-ნიშნა საკონტაქტო ნომერი",
    ),
    (
        "გაიმეორეთ თქვენი ტელეფონის ნომერი",
        "მომწერეთ თქვენი 9-ნიშნა საკონტაქტო ნომერი",
    ),
    (
        "გაიმეორეთ ნომერი",
        "მომწერეთ თქვენი საკონტაქტო ნომერი",
    ),
    (
        "გაიმეორეთ",
        "მომწერეთ",
    ),
    (
        "შეკვეთოთ დამატებითი კითხვები",
        "თუ გაქვთ დამატებითი კითხვა, აქვე მომწერეთ",
    ),
    (
        "შეკვეთოთ",
        "მომწერეთ",
    ),
    (
        "ყოველთვის მზად ვარ, როცა დაგჭირდებათ",
        "თუ კიდევ რაიმე გაგიჩნდებათ, შემეხმიანეთ",
    ),
    (
        "ყოველთვის მზად ვარ",
        "თუ კიდევ რაიმე გაგიჩნდებათ, შემეხმიანეთ",
    ),
    (
        "კიდევ რაიმეში დაგჭირდეთ დახმარება",
        "თუ კიდევ რამე გჭირდებათ, შემეხმიანეთ",
    ),
    (
        "დამიმტკიცეთ",
        "დამიდასტურეთ",
    ),
    # PATCH 2 — manager-handoff / payment / location wording
    # The manager-callback phrasing the live LLM kept emitting:
    (
        "მენეჯერი დაგიკავშირდებათ რაც მალე იქნება შესაძლებელი",
        "მენეჯერი დაგიკავშირდებათ",
    ),
    (
        "მენეჯერი დაგიკავშირდებათ უმოკლეს დროში",
        "მენეჯერი დაგიკავშირდებათ",
    ),
    (
        "მენეჯერი დაგიკავშირდებათ უმოკლეს ვადებში",
        "მენეჯერი დაგიკავშირდებათ",
    ),
    (
        "მენეჯერი დაგიკავშირდებათ რაც შეიძლება მალე",
        "მენეჯერი დაგიკავშირდებათ",
    ),
    (
        "მენეჯერი დაგიკავშირდებათ შესაძლებლისთანავე",
        "მენეჯერი დაგიკავშირდებათ",
    ),
    (
        "მენეჯერის კავშირი",
        "მენეჯერთან დაკავშირება",
    ),
    (
        "მენეჯერს გადასცე",
        "მენეჯერს გადავცემ",
    ),
    # "გთხოვთ მომწერეთ" is two contradictory commands joined; either
    # drop the polite hedge or use the proper subjunctive.
    (
        "გთხოვთ მომწერეთ",
        "მომწერეთ",
    ),
    # Payment grammar — "განვადებაში" is wrong case; instrumental
    # "განვადებით" or the longer paraphrase reads correctly.
    (
        "გადანაწილება განვადებაში",
        "გადახდის გადანაწილება",
    ),
    (
        "განვადებაში",
        "განვადებით",
    ),
    # NOTE (2026-06-23 source-of-truth cleanup) — the awkward dash-line LOCATION
    # reformat („ადგილი - X" → „ლოკაცია — X") and the age-range TYPOGRAPHY fix
    # („N-დან M წლამდე" → „N–M წლის") moved to `_apply_dynamic_fact_normalisations`.
    # They previously baked the camp location („ამბასადორ კაჭრეთი") and band
    # („9–17") into the REPLACEMENT, which let the sanitizer reinsert a stale fact
    # after an operator edited Admin Config. The dynamic pass keeps whatever
    # location/numbers the model produced (sourced from get_camp_info) and only
    # fixes the label/typography — it never hardcodes a camp fact.
    # PATCH 4 — live-sales wording fixes surfaced by the latest test.
    (
        "მენეჯერი დეტალებს ცოცხლად აგიხსნით",
        "მენეჯერი დეტალურად აგიხსნით",
    ),
    (
        "მენეჯერი დეტალებს ცოცხლად",
        "მენეჯერი დეტალურად",
    ),
    (
        "რას მიიჩნევთ ყველაზე მნიშვნელოვანია",
        "რას ელოდებით ბანაკისგან",
    ),
    (
        "რას მიიჩნევთ ყველაზე მნიშვნელოვნად",
        "რას ელოდებით ბანაკისგან",
    ),
    (
        "რისი მიღებაც გინდათ თქვენი შვილმა",
        "რისი მიღება გსურთ თქვენი შვილისთვის",
    ),
    (
        "რისი მიღებაც გსურთ თქვენი შვილმა",
        "რისი მიღება გსურთ თქვენი შვილისთვის",
    ),
    # "ჩამოუყალიბეთ" is the wrong verb form — drop it for the natural
    # alternative the policy prescribes.
    (
        "ჩამოუყალიბეთ თქვენი შვილის ასაკი",
        "მითხარით თქვენი შვილის ასაკი",
    ),
    (
        "ჩამოუყალიბეთ შვილის ასაკი",
        "მითხარით თქვენი შვილის ასაკი",
    ),
    (
        "ჩამოუყალიბეთ",
        "მითხარით",
    ),
    # BUG 2 (2026-07-06) — animate-possession grammar. Children take „გყავთ"
    # (animate), never „გაქვთ" (inanimate). The plural-children age question
    # is LLM free-generation (in no template), so rewrite it here.
    (
        "შვილები გაქვთ",
        "შვილები გყავთ",
    ),
    (
        "ბავშვები გაქვთ",
        "ბავშვები გყავთ",
    ),
    # BUG 3 (2026-07-06) — „ეს გასაგები მოთხოვნაა" is banned in user-facing
    # replies. Catch the phrase (and its „ძალიან …" variant) straight from
    # model output, and rewrite the whole „აზრი აქვს" family to the neutral
    # „გასაგებია". Longer/more-specific forms are listed first so the bare
    # entry never partially rewrites them.
    (
        "ეს გასაგები მოთხოვნაა",
        "გასაგებია",
    ),
    (
        "გასაგები მოთხოვნაა",
        "გასაგებია",
    ),
    (
        "ეს ძალიან აზრი აქვს",
        "გასაგებია",
    ),
    (
        "ამას აზრი აქვს",
        "გასაგებია",
    ),
    (
        "აზრი აქვს",
        "გასაგებია",
    ),
    # BUG 4 (2026-07-06) — polite verb form: „გირჩევნიათ", never „გირჩევთ"
    # („you prefer", 2nd-person plural). LLM free-generation grammar slip.
    (
        "რომელი დრო გირჩევთ",
        "რომელი დრო გირჩევნიათ",
    ),
    # BUG 5 (2026-07-06) — a booking confirmation must never carry the stray
    # „მოგწერეთ" the model sometimes emits („მივიღე, მოგწერეთ …"). The clean
    # opener is „მივიღე" — the parent's name is added deterministically upstream.
    (
        "მივიღე, მოგწერეთ",
        "მივიღე",
    ),
    # Standalone "გეწყებათ?" is awkward.
    (
        "გეწყებათ?",
        "რომელი დრო გაწყობთ?",
    ),
    # PATCH 5 — wording surfaced by the live booking-commit test.
    # "რომ სწორად გითხრათ" is a filler / hedging phrase ("to be precise")
    # that should be dropped entirely in front of the next sentence.
    (
        "რომ სწორად გითხრათ, ",
        "",
    ),
    (
        "რომ სწორად გითხრათ ",
        "",
    ),
    (
        "რომ სწორად გითხრათ",
        "",
    ),
    # "გაგივლით" reads as "we'll go over you" in this context; the
    # natural Georgian for "we'll explain" is "აგიხსნით".
    (
        "დეტალურად გაგივლით პროგრამას",
        "დეტალურად აგიხსნით პროგრამას",
    ),
    (
        "დეტალებს გაგივლით",
        "დეტალებს აგიხსნით",
    ),
    (
        "გაგივლით პროგრამას",
        "აგიხსნით პროგრამას",
    ),
    (
        "გაგივლით",
        "აგიხსნით",
    ),
    # "დაგიბაროთ" / "დაგიბარებთ" sound like "we'll summon you to come
    # in person". The neutral pre-booking phrasing is "ჩავნიშნოთ" /
    # "ჩაგინიშნავთ" — works before AND after the actual Calendar write.
    (
        "კონსულტაცია ჩაგიბაროთ",
        "კონსულტაცია ჩაგინიშნოთ",
    ),
    (
        "კონსულტაცია დაგიბაროთ",
        "კონსულტაცია ჩავნიშნოთ",
    ),
    (
        "კონსულტაცია დაგიბარებთ",
        "კონსულტაცია ჩავნიშნოთ",
    ),
    (
        "კონსულტაცია დაგიბარებთ",
        "კონსულტაცია ჩავნიშნოთ",
    ),
    (
        "კონსულტაციაზე დაგიბარებთ",
        "კონსულტაციაზე ჩაგწერთ",
    ),
    (
        "დაგიბარებთ",
        "ჩავნიშნოთ",
    ),
    (
        "დაგიბაროთ",
        "ჩავნიშნოთ",
    ),
    (
        "დაგიბარებთ",
        "ჩავნიშნოთ",
    ),
    # PATCH 7 — live QA polish.
    # 1. "precisely" — English drift, drop entirely.
    (
        "precisely",
        "",
    ),
    (
        "Precisely",
        "",
    ),
    # 2. "ეკრან რეჟიმიდან" missing genitive — fix grammar.
    (
        "ეკრან რეჟიმიდან",
        "ეკრანის რეჟიმიდან",
    ),
    # 3. Age-suitability wording — the LLM kept saying "სრულად ერგება
    # ბანაკის ასაკობრივ ჩარჩოს" which reads as bureaucratic. Replace with
    # natural Georgian. (The number-bearing „სრულად ერგება N–M წლის ბავშვების
    # ბანაკს" variant is normalised fact-agnostically in
    # `_apply_dynamic_fact_normalisations` so it carries no hardcoded „9–17".)
    (
        "სრულად ერგება ბანაკის ასაკობრივ ჩარჩოს",
        "ეს ასაკი ბანაკისთვის შესაფერისია",
    ),
    (
        "ბავშვი სრულად ერგება ბანაკის ასაკობრივ ჩარჩოს",
        "თქვენი შვილის ასაკი ამ ბანაკისთვის შესაფერისია",
    ),
    (
        "სრულად ერგება",
        "შესაფერისია",
    ),
    # 4. Robotic closing "შემეხმიანეთ დაგეხმაროთ" — replace with
    # natural alternative.
    (
        "შემეხმიანეთ დაგეხმაროთ",
        "მომწერეთ და დაგეხმარებით",
    ),
    # 5. Duplicated "თუ ... თუ ..." closings the live test emitted —
    # collapse to a single clause.
    (
        "თუ მომავალში რაიმე კითხვა გაგიჩნდებათ, თუ კიდევ რაიმე გაგიჩნდებათ",
        "თუ კიდევ რაიმე კითხვა გაგიჩნდებათ",
    ),
    (
        "თუ კიდევ რაიმე გაგიჩნდებათ, თუ მომავალში რაიმე კითხვა გაგიჩნდებათ",
        "თუ კიდევ რაიმე კითხვა გაგიჩნდებათ",
    ),
    (
        "თუ რაიმე კითხვა გაგიჩნდებათ, თუ კიდევ რაიმე გაგიჩნდებათ",
        "თუ კიდევ რაიმე კითხვა გაგიჩნდებათ",
    ),
    # PATCH 8 — false "delayed message" promises in adult-switch reply.
    # The system prompt example used to suggest "ერთ წუთში გავხსნი
    # თქვენთვის სწორ მიმართულებას" which is misleading — there is no
    # scheduler that would send an auto-follow-up. Strip both forms.
    (
        "ერთ წუთში გავხსნი თქვენთვის სწორ მიმართულებას",
        "",
    ),
    (
        "ერთ წუთში გავხსნი",
        "",
    ),
    (
        "ცოტა ხანში მოგწერთ",
        "",
    ),
    # Generic / robotic assistant greeting variants that surfaced in
    # the engine path. These get replaced with the brand prompt.
    (
        "როგორ შემიძლია დაგეხმაროთ დღეს?",
        "გვითხარით, რა გაინტერესებთ?",
    ),
    (
        "როგორ შემიძლია დაგეხმაროთ?",
        "გვითხარით, რა გაინტერესებთ?",
    ),
    # Parent-greeting safety net. The static PARENT_WELCOME at
    # state=START is supposed to preempt any LLM call, but if a later
    # turn produces "მოგესალმებით! როგორ შემიძლია დაგეხმაროთ ..."
    # collapse it to the brand prompt instead of letting it ship.
    (
        "მოგესალმებით! როგორ შემიძლია დაგეხმაროთ ბავშვთა საზაფხულო ბანაკის შესახებ?",
        "გვითხარით, რა გაინტერესებთ?",
    ),
    (
        "მოგესალმებით! როგორ შემიძლია დაგეხმაროთ?",
        "გვითხარით, რა გაინტერესებთ?",
    ),
    (
        "მოგესალმებით! როგორ შემიძლია დაგეხმაროთ",
        "გვითხარით, რა გაინტერესებთ",
    ),
    (
        "თუ რაიმეში დაგჭირდებათ დახმარება, მზად ვარ დაგეხმაროთ",
        "თუ კიდევ რაიმე კითხვა გაგიჩნდებათ, მომწერეთ",
    ),
    (
        "მზად ვარ დაგეხმაროთ",
        "",
    ),
    # "გადაგამისამართებთ" without delivering anything sounds like a
    # promised transfer. Collapse the adult-switch line.
    (
        "ზრდასრულთა ღონისძიებებზე გადაგამისამართებთ —",
        "ზრდასრულთა ღონისძიებებზე დაგეხმარებით.",
    ),
    (
        "ზრდასრულთა ღონისძიებებზე გადაგამისამართებთ",
        "ზრდასრულთა ღონისძიებებზე დაგეხმარებით",
    ),
    # ===========================================================
    # Georgian wording polish patch (post-Redis live QA)
    # ===========================================================
    # Slot-confirmation: the LLM was emitting "გეთანხმებით ამ დროით"
    # ("I agree with this time") which is unnatural and inverts the
    # confirmation direction — the USER should confirm, not the bot.
    # Order matters: the multi-word phrase MUST come before the
    # standalone "გეთანხმებით" replacement so the longer form wins.
    (
        "კონსულტაციის ჩასანიშნად დამიდასტურეთ, გეთანხმებით ამ დროით",
        "თუ ეს დრო გაწყობთ, დამიდასტურეთ და კონსულტაციას ჩავნიშნავ",
    ),
    (
        "გეთანხმებით ამ დროით",
        "თუ ეს დრო გაწყობთ, დამიდასტურეთ",
    ),
    # Standalone "გეთანხმებით" — drop entirely; the bot should not
    # express agreement when it's asking for the user's confirmation.
    (
        "გეთანხმებით.",
        "",
    ),
    (
        ", გეთანხმებით",
        "",
    ),
    (
        " გეთანხმებით",
        "",
    ),
    # Misspelling fixes: "დაჭვება" / "დაეჭვება" are not valid Georgian
    # nouns. The intended meaning is "კითხვა" ("question") in the
    # post-help closing context the live transcript captured.
    (
        "დაეჭვება",
        "კითხვა",
    ),
    (
        "დაჭვება",
        "კითხვა",
    ),
    # Repeated double-conditional closings that the LLM keeps emitting
    # in the "thanks / done" turn. Collapse to one natural clause. The
    # generic _collapse_duplicated_tu regex handles the cleaner
    # `გაგიჩნდებათ` form; these literal entries catch the messier
    # `დაგჭირდებათ` variants where the user-message log surfaced them.
    (
        "თუ რამე დაგჭირდებათ, თუ კიდევ რამე",
        "თუ დამატებითი კითხვა გაგიჩნდებათ",
    ),
    (
        "თუ რამე დაგჭირდება, თუ კიდევ რამე",
        "თუ დამატებითი კითხვა გაგიჩნდებათ",
    ),
    (
        "თუ კიდევ რამე დაგჭირდებათ, თუ კიდევ",
        "თუ კიდევ რამე გაგიჩნდებათ",
    ),
    (
        "თუ რამე დაგჭირდებათ, თუ კიდევ",
        "თუ დამატებითი კითხვა გაგიჩნდებათ",
    ),
    (
        "თუ რამე დაგჭირდება, თუ კიდევ",
        "თუ დამატებითი კითხვა გაგიჩნდებათ",
    ),
    # Robotic "always available" closings — already partially covered
    # earlier in this list, but the standalone forms reach final
    # output when the LLM puts them at sentence-start.
    (
        "ყოველთვის მზად ვარ.",
        "",
    ),
    (
        " ყოველთვის მზად ვარ",
        "",
    ),
    # "აქ ვარ" used as a robotic assistant closer ("Hi, I'm here for
    # you"). Always appears with surrounding context ("მე აქ ვარ" /
    # "კიდევ აქ ვარ" / "აქ ვარ თქვენთვის"); the bare 5-character
    # match is safe because the phrase has no other natural use in
    # the brand voice.
    (
        "მე აქ ვარ თქვენთვის",
        "",
    ),
    (
        "აქ ვარ თქვენთვის",
        "",
    ),
    (
        " აქ ვარ.",
        ".",
    ),
    # ======================================================
    # Georgian wording quality patch (post-scenario QA)
    # ======================================================
    #
    # Live scenario run surfaced a handful of leaked awkward phrases
    # the prior sanitiser didn't catch. Each entry is annotated so
    # future regressions are obvious.

    # 1. Duplicated "რომელი დრო რომელი დრო" — LLM keeps doubling.
    (
        "რომელი დრო რომელი დრო გირჩევნიათ?",
        "რომელი დრო იქნება თქვენთვის მოსახერხებელი?",
    ),
    (
        "რომელი დრო რომელი დრო გაწყობთ?",
        "რომელი დრო იქნება თქვენთვის მოსახერხებელი?",
    ),
    (
        "რომელი დრო რომელი დრო",
        "რომელი დრო",
    ),

    # 2. "ეს ბუნებრივია სრულად" — unnatural ordering; reorder.
    (
        "ეს ბუნებრივია სრულად",
        "ეს სრულიად ბუნებრივია",
    ),
    (
        "ბუნებრივი სურვილია",
        "სრულიად ბუნებრივი სურვილია",
    ),

    # 3. "ეს გასაგები მოტივაცია(ა)" — wrong word for objection.
    # The parent is RAISING an objection ("ძალიან ძვირია"), not
    # explaining motivation. Soften without inventing pricing.
    (
        "ეს გასაგები მოტივაციაა.",
        "გასაგებია, ფასი ნამდვილად მნიშვნელოვანი ფაქტორია.",
    ),
    (
        "ეს გასაგები მოტივაციაა",
        "გასაგებია, ფასი ნამდვილად მნიშვნელოვანი ფაქტორია",
    ),

    # 4. "კონსულტაციაზე ჩასაწერად საჭირო დეტალების გასარკვევად
    # გვითხარით…" — bureaucratic. Use brand wording.
    (
        "კონსულტაციაზე ჩასაწერად საჭირო დეტალების გასარკვევად გვითხარით, გთხოვთ, თქვენი სახელი.",
        "კი, ჩაგწერთ. მომწერეთ თქვენი სახელი და 9-ნიშნა საკონტაქტო ნომერი.",
    ),
    (
        "კონსულტაციაზე ჩაწერისთვის საჭირო დეტალების გარკვევისთვის გვითხარით, გთხოვთ, თქვენი სახელი.",
        "კი, ჩაგწერთ. მომწერეთ თქვენი სახელი და 9-ნიშნა საკონტაქტო ნომერი.",
    ),
    (
        "საჭირო დეტალების გასარკვევად",
        "",
    ),
    (
        "საჭირო დეტალების გარკვევისთვის",
        "",
    ),

    # 5. "გვითხარით თქვენი სახელი" alone — must ask for both
    # name AND 9-digit phone in one sentence.
    (
        "გვითხარით, გთხოვთ, თქვენი სახელი.",
        "მომწერეთ თქვენი სახელი და 9-ნიშნა საკონტაქტო ნომერი.",
    ),
    (
        "გვითხარით თქვენი სახელი.",
        "მომწერეთ თქვენი სახელი და 9-ნიშნა საკონტაქტო ნომერი.",
    ),

    # 6. "ამ პროგრამაში თქვენი ბავშვის ჩაწერას ვერ დავადასტურებთ" — harsh.
    # Softened to the gentler brand line in `_apply_dynamic_fact_normalisations`,
    # where the age band comes from the canonical `get_camp_age_bounds()` rather
    # than a hardcoded „9–17" literal (so an operator age edit propagates here).

    # 7. Past-date wording — the LLM sometimes still emits the old
    # "ეს დრო უკვე გასულია" phrasing. The brand line is the gentler
    # past-tense framing.
    (
        "ეს დრო უკვე გასულია.",
        "წარსულ თარიღზე კონსულტაციას ვერ ჩავნიშნავთ, მაგრამ შემიძლია თავისუფალი დროები შემოგთავაზოთ.",
    ),
    (
        "ეს დრო უკვე გასულია",
        "წარსულ თარიღზე კონსულტაციას ვერ ჩავნიშნავთ, მაგრამ შემიძლია თავისუფალი დროები შემოგთავაზოთ",
    ),
    (
        "უკვე გასულია",
        "წარსულია, ვერ ჩავნიშნავთ",
    ),

    # 8. Angry-user defensive wording — never use "თუ ... მოგეჩვენათ"
    # which sounds like deflecting blame. The brand response opens
    # with a direct apology + reassurance.
    (
        "ბოდიშს გიხდით, თუ პასუხი დაგვიანებულად ან არასაკმარისად მოგეჩვენათ",
        "ბოდიშს გიხდით. ვეცდები, სწრაფად და ზუსტად დაგეხმაროთ",
    ),
    (
        "თუ პასუხი დაგვიანებულად ან არასაკმარისად მოგეჩვენათ",
        "ვეცდები, სწრაფად და ზუსტად დაგეხმაროთ",
    ),
    (
        "თუ პასუხი დაგვიანებულად მოგეჩვენათ",
        "ვეცდები, სწრაფად და ზუსტად დაგეხმაროთ",
    ),
    # Booked State Memory Response Polish (2026-05-30).
    # Live observation: the LLM emitted "მყარი ჯავშანი გაქვთ 29 მაისს,
    # 15:00 საათზე" when summarising a booked consultation. "მყარი
    # ჯავშანი" is unnatural Georgian for this context — the natural
    # phrasing is "კონსულტაცია ჩანიშნულია".
    (
        "მყარი ჯავშანი გაქვთ",
        "კონსულტაცია ჩანიშნულია",
    ),
    (
        "მყარი ჯავშანი",
        "კონსულტაცია",
    ),
    # Typo / awkward declension surfaced in the same live response:
    # "ეკრანსიგან" should be "ეკრანისგან" (გან-prefix declension on
    # "ეკრანი" → "ეკრანისგან"). Same fix for "ეკრანსიგან დისტანცია".
    (
        "ეკრანსიგან დისტანციის მიღება",
        "ეკრანისგან დისტანცია",
    ),
    (
        "ეკრანსიგან დისტანცია",
        "ეკრანისგან დისტანცია",
    ),
    (
        "ეკრანსიგან",
        "ეკრანისგან",
    ),
    # Expired Booking Memory Fix — Sensitive Needs Wording Polish.
    # The LLM occasionally framed manager handoff as "მენეჯერთან
    # გავარკვევთ" ("let's clarify with the manager"), which sounds
    # bureaucratic and uses a 1st-person-plural verb where the user is
    # the subject ("გავარკვევთ" reads as us-and-the-user solving it
    # together, which is wrong for a handoff). Replace with the brand
    # phrasing — manager OWNS the clarification.
    (
        "ამ საკითხს მენეჯერთან გავარკვევთ",
        "ამ საკითხს მენეჯერი დეტალებში დაგიზუსტებთ",
    ),
    (
        "მენეჯერთან გავარკვევთ ამ საკითხს",
        "მენეჯერი დეტალებში დაგიზუსტებთ ამ საკითხს",
    ),
    (
        "მენეჯერთან გავარკვევთ",
        "მენეჯერი დეტალებს დაგიზუსტებთ",
    ),
    # And the misspelled / similarly-shaped variant.
    (
        "მენეჯერთან გავარჩევთ",
        "მენეჯერი დეტალებს დაგიზუსტებთ",
    ),
    # Agent Wording Cleanup Patch (2026-06-03). The LLM occasionally
    # produced „მენეჯერთან კავშირს მოგიწყობთ" / „მენეჯერთან კავშირსაც
    # მოგიწყობთ" / „კავშირს მოგიწყობთ" — the verb „მოგიწყობთ"
    # ("will arrange") reads as service-desk filler in this context.
    # The brand-preferred phrasing centres the manager call as a
    # direct offer the user can accept.
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
    # Calendar Multi-Busy Check Patch (2026-06-04) — reschedule wording.
    # Live bug: bot said „კონსულტაციის გადატანას დავეხმარები" — the
    # noun-case construction is unnatural; the brand form uses the
    # locative „გადატანაში დაგეხმარებით".
    (
        "კონსულტაციის გადატანას დავეხმარები",
        "კონსულტაციის გადატანაში დაგეხმარებით",
    ),
    (
        "გადატანას დაგეხმარებით",
        "გადატანაში დაგეხმარებით",
    ),
    (
        "გადატანას დაგეხმარები",
        "გადატანაში დაგეხმარებით",
    ),
    (
        "გადატანას დავეხმარები",
        "გადატანაში დაგეხმარებით",
    ),
    (
        "შეცვლას დაგეხმარებით",
        "შეცვლაში დაგეხმარებით",
    ),
    (
        "შეცვლას დაგეხმარები",
        "შეცვლაში დაგეხმარებით",
    ),
    # Booking Availability Patch (2026-06-03) — old 10:00–18:00 /
    # 10:00–19:00 phrasings replaced with the new 10:00–21:00 window.
    # The LLM may still echo the older numbers from cached training
    # context; sanitiser brings them in line with the new policy.
    (
        "10:00-დან 18:00-მდე",
        "10:00-დან 21:00-მდე",
    ),
    (
        "10:00-დან 19:00-მდე",
        "10:00-დან 21:00-მდე",
    ),
    (
        "10:00–18:00",
        "10:00–21:00",
    ),
    (
        "10:00–19:00",
        "10:00–21:00",
    ),
    # Live QA Patch (2026-06-05 Session 2) — Bug 6 manager handoff
    # wording. „მენეჯერთან კავშირით" reads as broken Georgian;
    # bare „დაგაკავშირებთ." without a noun is incomplete. Both →
    # brand-standard „დაგაკავშირებთ მენეჯერთან".
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
    # Live QA Patch (2026-06-05 Session 2) — Bug 10 redundant
    # confirmation. „<X> საათზე ჩამწერეთ კონსულტაცია" echoes the
    # user's own command and reads awkwardly. Unconditionally strip
    # — there is NO context in which that phrase is correct.
    #
    # The "თუ ეს დრო გაწყობთ, დამიდასტურეთ" phrase is also redundant
    # AFTER the user explicitly said „ჩამწერეთ", but it remains the
    # natural confirmation in the new-booking path. We DO NOT strip
    # it here unconditionally — see
    # `_strip_redundant_confirmation_after_command` in parent_flow,
    # which only runs when the user message carries an explicit
    # booking command.
    (" საათზე ჩამწერეთ კონსულტაცია, თუ ეს დრო გაწყობთ, დამიდასტურეთ.", ""),
    (" საათზე ჩამწერეთ კონსულტაცია, თუ ეს დრო გაწყობთ, დამიდასტურეთ", ""),
    (" საათზე ჩამწერეთ კონსულტაცია.", ""),
    (" საათზე ჩამწერეთ კონსულტაცია", ""),
    # Live QA Patch (2026-06-05) — 8 wording fixes from live transcript.
    #
    # Bug 1.1 — „გმადლობთ, რომ გაზიარეთ" is filler that adds no
    #            information. Strip outright.
    ("გმადლობთ, რომ გაზიარეთ.", ""),
    ("გმადლობთ, რომ გაზიარეთ ", ""),
    ("გმადლობთ, რომ გაზიარეთ", ""),
    # Bug 1.2 — „დასთვის" is wrong Georgian; relative noun „და" in
    #            dative is „დისთვის".
    ("დასთვის", "დისთვის"),
    # Bug 1.3 — „მიმოწმების შედეგად" reads as bureaucratic noun
    #            phrase; the verb form „გადავამოწმე" is natural.
    ("მიმოწმების შედეგად,", "გადავამოწმე —"),
    ("მიმოწმების შედეგად", "გადავამოწმე"),
    # Bug 1.4 — „სიამოვნებით დაგიდგებით გვერდში" is the awkward
    #            apology form; the brand handoff phrase is the
    #            preferred wording.
    (
        "სიამოვნებით დაგიდგებით გვერდში.",
        "თუ გსურთ, დაგაკავშირებთ მენეჯერთან?",
    ),
    (
        "სიამოვნებით დაგიდგებით გვერდში",
        "თუ გსურთ, დაგაკავშირებთ მენეჯერთან?",
    ),
    # Bug 1.5 — „თუ დაგეხმაროთ სხვა გზით" is an indirect manager
    #            handoff form; standardise to the brand line.
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
    # Bug 1.6/7/8 — three slot-question variants the live LLM tried.
    # The brand-standard ask is „რომელი დროა თქვენთვის
    # მოსახერხებელი".
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
    # Client smoke regression (2026-06-09) — LLM leaked a robotics phrase
    # that references internal memory state. The brand voice never exposes
    # implementation details to the user.
    (
        "კომპიუტერის მეხსიერების მიხედვით,",
        "ამ ეტაპზე",
    ),
    (
        "კომპიუტერის მეხსიერების მიხედვით",
        "ამ ეტაპზე",
    ),
    (
        "ჩემი მეხსიერების მიხედვით,",
        "ამ ეტაპზე",
    ),
    (
        "ჩემი მეხსიერების მიხედვით",
        "ამ ეტაპზე",
    ),
    # Live Polish Patch (2026-06-09) — awkward phone-receipt phrases.
    # "Happy to receive your number" reads as robotic/unnatural in Georgian.
    # The neutral acknowledgement is "ნომერი მივიღე."
    (
        "მიხარია ნომრის მიღება",
        "ნომერი მივიღე",
    ),
    (
        "მოხარული ვარ ნომრის მიღებით",
        "ნომერი მივიღე",
    ),
    # Standalone "სიამოვნებით." as the sole response to "მადლობა" is
    # unnatural. Strip it so the system-prompt rule for context-aware
    # closings takes effect. The longer form "სიამოვნებით დაგიდგებით
    # გვერდში" already has its own entry earlier in this table, so this
    # catch-all only fires on the bare phrase that slips through.
    (
        "სიამოვნებით.",
        "",
    ),
    # No emoji in production agent replies (2026-06-03 wording polish).
    # Replace with a leading space when the emoji follows a token, so
    # the surrounding sentence keeps its rhythm.
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


# ===========================================================================
# Phase 4, Task 4 — USE_LEAN_SANITIZER partition of the table above.
# ===========================================================================
#
# The 183-entry table is TWO different things wearing one coat:
#
#   * a SAFETY NET — strips, spelling/grammar/agreement fixes, stale-fact
#     corrections, false-promise and internal-leak removals, and the
#     „sanitizer-coupled" guardrails catalogued in
#     `docs/PHASE4_GUARDRAIL_MAP_2026_07_21.md` §5; and
#   * a CONVERGENCE ENGINE — entries whose only job is to force ONE approved
#     phrasing over another equally-correct one, which is what makes every
#     reply sound like the same script.
#
# `USE_LEAN_SANITIZER` (default OFF) keeps the safety net and relaxes the
# convergence engine. Flag OFF ⇒ the FULL table is applied, in declaration
# order, byte-identical to the pre-Task-4 behaviour.
#
# Classification rule (conservative — "when unsure, keep it"):
#   An entry is SAFETY when ANY of these holds —
#     S1  the replacement is "" (a strip);
#     S2  it fixes a typo / wrong case / wrong verb form / animate agreement /
#         an invalid word form, or collapses a literally duplicated fragment;
#     S3  it removes a FALSE or STALE claim (timing promise, past-date wording,
#         old business hours, false booking/transfer claim), an INTERNAL leak
#         („ჩემი მეხსიერების მიხედვით"), a HARSH/defensive line, or a leaked
#         greeting — i.e. it is traceable to a live production bug;
#     S4  it is named in the guardrail map §5 (sanitizer-coupled), or is a
#         documented "never remove" banned-phrase family in CLAUDE.md;
#     S5  it produces a token a downstream deterministic path keys on (the
#         „9-ნიშნა საკონტაქტო ნომერი" ask arms `_bot_recently_asked_for_contact`);
#     S6  it is AMBIGUOUS between a grammar fix and a convergence mandate.
#   Everything else — well-formed Georgian rewritten purely into the approved
#   house phrasing — is a WORDING MANDATE and is skipped under the flag.
#
# NOTHING is deleted, retyped or reordered: the safety subset is built by
# filtering the tuple above BY POSITION, so it holds references to the very
# same tuple objects in the very same relative order (the rewrites are
# order-dependent — see the comment in `sanitise_response_wording`).
_SANITIZER_WORDING_MANDATE_INDEXES: frozenset[int] = frozenset(
    {
        24,   # „რას მიიჩნევთ ყველაზე მნიშვნელოვნად" → a different (approved)
              #   discovery question. Needle is correct Georgian; index 23 keeps
              #   the ungrammatical „…მნიშვნელოვანია" variant.
        58,   # „სრულად ერგება ბანაკის ასაკობრივ ჩარჩოს" → bureaucratic-vs-natural
        59,   #   style only. The NUMBER-bearing variant is normalised by
        60,   #   `_AGE_SUITABILITY_BAND_RE` in the structural pass, which still runs.
        68,   # „როგორ შემიძლია დაგეხმაროთ დღეს?" → brand ask. Generic-assistant
        69,   # „როგორ შემიძლია დაგეხმაროთ?"      → phrasing, no guarantee attached.
              #   (Indexes 70–72 keep the „მოგესალმებით!" greeting-leak strip;
              #   dropping 68/69 actually lets 71/72 match the full greeting.)
        98,   # „ბუნებრივი სურვილია" → „სრულიად ბუნებრივი სურვილია": intensifier
              #   insertion, nothing else.
        # 153/154 REMOVED (code review, 2026-07-21): the needle „სიამოვნებით
        # დაგიდგებით გვერდში" is a vague warm closing that offers NOTHING
        # concrete; the replacement injects a real manager-handoff offer.
        # Dropping these two therefore REMOVES an offer from the reply (a
        # warm dead-end with no next step) rather than merely rewording one —
        # that is load-bearing under the plan's own rule ("adding/removing a
        # manager-handoff offer" is explicitly called out as SAFETY). Kept as
        # SAFETY. 155–157 stay dropped: their needle „თუ დაგეხმაროთ სხვა
        # გზით" is ITSELF an indirect offer of further help, so dropping
        # those only downgrades an offer's specificity, not remove one.
        155,  # „თუ დაგეხმაროთ სხვა გზით" → the brand manager-handoff line. Same.
        156,
        157,
        161,  # „რომელი დრო გჭირდებათ?" → „რომელი დროა თქვენთვის მოსახერხებელი?":
        162,  #   correct Georgian, converged to the house slot question. (158–160
              #   stay — „დრო გიჭერს მხარს" is a misused idiom, i.e. S2/S6.)
    }
)

# Positional indexes are only valid for the table they were derived from. If
# the table is edited, fail SAFE: fall back to the full table (never silently
# drop the wrong entry).
#
# A length check alone is NOT enough: this table is appended to frequently,
# but an in-place edit or a same-length reorder would silently re-target
# these positional indexes at *different* entries — disabling the wrong
# guardrails with every existing test still green (the tests read phrases
# out of the table BY INDEX too, so they'd drift in lock-step). Guard against
# that by also pinning the exact needle text expected at each dropped index,
# derived programmatically from the table below (never hand-retyped — a
# transcription typo would silently defeat the guard).
_SANITIZER_TABLE_SIZE_AT_PARTITION = 183

#: (index, expected needle) pairs for every index in
#: `_SANITIZER_WORDING_MANDATE_INDEXES`, sliced from `FORBIDDEN_PHRASE_REPLACEMENTS`
#: at import time — i.e. a golden snapshot of what each position held when the
#: partition was authored. Built by slicing, never retyped.
_SANITIZER_WORDING_MANDATE_EXPECTED_NEEDLES: tuple[tuple[int, str], ...] = tuple(
    (idx, FORBIDDEN_PHRASE_REPLACEMENTS[idx][0])
    for idx in sorted(_SANITIZER_WORDING_MANDATE_INDEXES)
)


def _build_sanitizer_safety_entries(
    table: tuple[tuple[str, str], ...] = FORBIDDEN_PHRASE_REPLACEMENTS,
) -> tuple[tuple[str, str], ...]:
    if len(table) != _SANITIZER_TABLE_SIZE_AT_PARTITION:
        return table
    for idx, expected_needle in _SANITIZER_WORDING_MANDATE_EXPECTED_NEEDLES:
        if table[idx][0] != expected_needle:
            # Same length, but the entry at this position no longer matches
            # what the partition was built against (in-place edit / reorder).
            # The positional indexes are no longer trustworthy — fail SAFE.
            return table
    return tuple(
        entry
        for idx, entry in enumerate(table)
        if idx not in _SANITIZER_WORDING_MANDATE_INDEXES
    )


#: The SAFETY subset — references (never copies) of the entries above, in the
#: same relative order. Used only when `USE_LEAN_SANITIZER` is ON.
_SANITIZER_SAFETY_ENTRIES: tuple[tuple[str, str], ...] = (
    _build_sanitizer_safety_entries()
)


def _use_lean_sanitizer() -> bool:
    """Lean Sanitizer mode (Phase 4, Task 4). When ON, `sanitise_response_wording`
    still runs every structural pass and still applies `_SANITIZER_SAFETY_ENTRIES`,
    but skips the pure wording-mandate entries so the model's own phrasing
    survives. Default OFF ⇒ the full table applies, byte-identical."""
    return bool(getattr(settings, "USE_LEAN_SANITIZER", False))


# P3-C PATCH 7 — duplicated "თუ … თუ …" clause collapser.
# The LLM sometimes emits TWO consecutive "თუ X გაგიჩნდებათ" clauses
# (e.g. "თუ მომავალში რაიმე კითხვა გაგიჩნდებათ, თუ კიდევ რაიმე
# გაგიჩნდებათ, შემეხმიანეთ…"). A targeted regex collapses them down to
# the second one, which is the more natural "თუ კიდევ რაიმე…" form.
_DUP_TU_PATTERN = re.compile(
    r"თუ\s+[^,]{1,60}?გაგიჩნდებათ,\s*თუ\s+([^,]{1,60}?გაგიჩნდებათ)",
)
# Live QA Session 8 Patch (2026-06-07) — Bug 1 broadened: live model
# also produces „თუ კიდევ რაიმე დაგაინტერესებთ, თუ კიდევ რაიმე
# გაგიჩნდებათ, მომწერეთ და დაგეხმარებით." (mixed verb pair). Collapse
# both verb variants in either order.
_DUP_TU_MIXED_PATTERN = re.compile(
    r"თუ\s+[^,]{1,60}?(?:დაგაინტერესებთ|გაგიჩნდებათ),\s*"
    r"თუ\s+([^,]{1,60}?(?:დაგაინტერესებთ|გაგიჩნდებათ))",
)


def _collapse_duplicated_tu(text: str) -> str:
    if not text or "თუ" not in text:
        return text
    out = _DUP_TU_PATTERN.sub(r"თუ \1", text)
    out = _DUP_TU_MIXED_PATTERN.sub(r"თუ \1", out)
    return out


# Wording Fix (2026-06-11) — BUG 1. Ban the awkward „შეშფოთება"
# (concern / anxiety — an alarming, medical-sounding word for a parent's
# camp goal) and the hallucinated „თქვენი ინფორმაცია უკვე მაქვს ასაკისა და
# შეშფოთების შესახებ…" preamble from user-facing PARENT replies. Source:
# LLM free-generation (the system prompt uses „შეშფოთება" as the term for
# the parent's challenge). The prompt is intentionally NOT changed — this
# is a minimal deterministic sanitizer.

# 1. Drop the whole „I already have your INFORMATION about age/concern"
#    preamble SENTENCE. Anchored on the word „ინფორმაცია" (the bad preamble
#    says „თქვენი ინფორმაცია უკვე მაქვს …" — „I have your information") AND
#    („უკვე მაქვს"|„უკვე ვიცი") AND („ასაკ"|„შეშფოთებ"). The „ინფორმაცია"
#    anchor is what keeps legitimate sentences that merely contain
#    „უკვე ვიცი"+„ასაკ" intact — e.g. „სახელი უკვე ვიცი, რა არის ბავშვის
#    ასაკი?" / „ბავშვის ასაკი უკვე ვიცი, ხუთი წლის." (adversarial-review
#    fix: the old regexes over-stripped those).
def _is_concern_preamble_sentence(sentence: str) -> bool:
    s = sentence or ""
    return (
        "ინფორმაცია" in s
        and ("უკვე მაქვს" in s or "უკვე ვიცი" in s)
        and ("ასაკ" in s or "შეშფოთებ" in s)
    )


# Wording Fix (2026-06-12) — BUG 3. Ban the „I already know YOUR age / name /
# information" announcing preamble during PARENT contact collection
# („თქვენი ასაკი უკვე ვიცი, 15 წლისაა." — where 15 is the CHILD's age, absurd
# to tell a parent; „თქვენი სახელი უკვე ვიცი. მომწერეთ ნომერი."). The
# discriminator is „თქვენი" (announcing what it knows about *you*) + a
# knowledge verb („უკვე ვიცი"/„უკვე მაქვს"). This is what keeps the
# legitimate, „თქვენი"-less wording intact — „სახელი უკვე ვიცი, რა არის
# ბავშვის ასაკი?" / „ბავშვის ასაკი უკვე ვიცი, ხუთი წლის." — and never touches
# the Task 2 privacy notice („თქვენი ინფორმაცია გამოიყენება…", which has no
# „უკვე ვიცი/მაქვს") or a booking/reschedule confirmation.
def _is_known_about_you_preamble(sentence: str) -> bool:
    s = sentence or ""
    return (
        "თქვენი" in s
        and ("ასაკ" in s or "სახელ" in s or "ინფორმაცია" in s)
        and ("უკვე ვიცი" in s or "უკვე მაქვს" in s)
    )


# 2. Replace any residual „შეშფოთებ"-stem word with a neutral declension
#    (longest forms first; the bare stem is the catch-all last). Per spec,
#    „შეშფოთება" (alarming concern/anxiety word) is banned from user-facing
#    PARENT replies — „მოლოდინი" (expectation) is an allowed alternative.
_CONCERN_WORD_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    ("შეშფოთებაზე", "მოლოდინზე"),
    ("შეშფოთებას", "მოლოდინს"),
    ("შეშფოთების", "მოლოდინის"),
    ("შეშფოთებამ", "მოლოდინმა"),
    ("შეშფოთებაა", "მოლოდინია"),
    ("შეშფოთება", "მოლოდინი"),
    ("შეშფოთებ", "მოლოდინ"),
)


def _strip_concern_wording(text: str) -> str:
    """Remove the awkward „შეშფოთება" / „info already known about age &
    concern" preamble from a PARENT reply (BUG 1). Never touches the
    legitimate „სახელი/ასაკი უკვე ვიცი/მაქვს" wording or the privacy
    notice (neither carries the „ინფორმაცია" anchor + the dropped form)."""
    if not text:
        return text
    sentences = re.split(r"(?<=[.?!])\s+", text)
    out = " ".join(
        s for s in sentences
        if not _is_concern_preamble_sentence(s)
        and not _is_known_about_you_preamble(s)
    ).strip()
    for needle, repl in _CONCERN_WORD_REPLACEMENTS:
        if needle in out:
            out = out.replace(needle, repl)
    out = re.sub(r"\s+([.,!?])", r"\1", out)
    out = re.sub(r"  +", " ", out)
    return out.strip()


def _camp_age_bounds_safe() -> tuple[int, int]:
    """Canonical camp age band for the sanitizer's fact-aware rewrite.

    Reads the SAME canonical source as `_build_system_prompt` / `_age_status`
    (`admin_config_service.get_camp_age_bounds` — admin-first, safe 9/17
    default, never raises). Wrapped so a config read can never crash an
    outgoing reply.
    """
    try:
        from app.services import admin_config_service

        return admin_config_service.get_camp_age_bounds()
    except Exception:  # pragma: no cover - defensive; helper never raises today
        return (9, 17)


# Number-agnostic age-range typography: „N-დან M წლამდე [ბავშვებისთვის]"
# → „N–M წლის [...]". Preserves whatever band the model produced (sourced from
# get_camp_info) and only fixes the dash form — never asserts a camp fact.
_AGE_RANGE_TYPO_CHILDREN_RE = re.compile(r"(\d+)-დან (\d+) წლამდე ბავშვებისთვის")
_AGE_RANGE_TYPO_RE = re.compile(r"(\d+)-დან (\d+) წლამდე")
# Bureaucratic „სრულად ერგება N–M წლის ბავშვების ბანაკს" → fact-free sentence.
_AGE_SUITABILITY_BAND_RE = re.compile(r"სრულად ერგება \d+–\d+ წლის ბავშვების ბანაკს")
# Sentinel for the harsh under-age rejection (both verb endings share a prefix).
_HARSH_REJECTION_PREFIX = "ამ პროგრამაში თქვენი ბავშვის ჩაწერას ვერ და"
# BUG 1 (2026-07-06) — a camp-price answer must never use the awkward
# „გადახდა ბანაკში N ლარია" / bare „ბანაკში N ლარია" phrasing. Normalise to the
# approved „ბანაკის ღირებულება N ლარია". Number-agnostic (keeps the model's
# price); the payment form is listed first so the bare form never double-hits it.
_BAD_PRICE_PAYMENT_RE = re.compile(r"გადახდა\s+ბანაკში\s+(\d[\d\s]*?)\s*ლარია")
_BAD_PRICE_BARE_RE = re.compile(r"ბანაკში\s+(\d[\d\s]*?)\s*ლარია")


def _apply_dynamic_fact_normalisations(text: str) -> str:
    """Config-aware wording/typography fixes that must NEVER hardcode a camp
    fact (age band / location).

    Source-of-truth cleanup (2026-06-23): these rewrites previously lived in
    ``FORBIDDEN_PHRASE_REPLACEMENTS`` with the literal „ამბასადორ კაჭრეთი" /
    „9–17" baked into the REPLACEMENT, which let the sanitizer reinsert a stale
    fact even after an operator edited Admin Config. Now:
      * the location label „ადგილი - X" / „ადგილი — X" → „ლოკაცია — X" keeps the
        model's own location text (sourced from get_camp_info) — location-agnostic;
      * the age-range typography keeps the model's numbers — number-agnostic;
      * the only rewrite that needs the band (the harsh under-age softener) reads
        it from the canonical ``get_camp_age_bounds()``.
    Idempotent.
    """
    out = text
    # BUG 1 (2026-07-06) — awkward camp-price phrasing → approved wording.
    # Payment form („გადახდა ბანაკში …") first, then the bare form.
    out = _BAD_PRICE_PAYMENT_RE.sub(r"ბანაკის ღირებულება \1 ლარია", out)
    out = _BAD_PRICE_BARE_RE.sub(r"ბანაკის ღირებულება \1 ლარია", out)
    # Location label only — keep whatever location the model produced.
    out = out.replace("ადგილი - ", "ლოკაცია — ")
    out = out.replace("ადგილი — ", "ლოკაცია — ")
    # Age-range typography — the specific („ბავშვებისთვის") form first.
    out = _AGE_RANGE_TYPO_CHILDREN_RE.sub(r"\1–\2 წლის ბავშვებისთვის", out)
    out = _AGE_RANGE_TYPO_RE.sub(r"\1–\2 წლის", out)
    # Bureaucratic age-suitability phrasing → natural, fact-free sentence. Runs
    # before the literal „სრულად ერგება" entry so the full phrase is replaced.
    out = _AGE_SUITABILITY_BAND_RE.sub("ეს ასაკი ამ ბანაკისთვის შესაფერისია", out)
    # Harsh under-age rejection → gentler brand line; band from canonical source.
    if _HARSH_REJECTION_PREFIX in out:
        lo, hi = _camp_age_bounds_safe()
        softened = f"ბავშვების ბანაკი {lo}–{hi} წლის ასაკისთვისაა"
        out = out.replace(
            "ამ პროგრამაში თქვენი ბავშვის ჩაწერას ვერ დავადასტურებთ", softened
        )
        out = out.replace(
            "ამ პროგრამაში თქვენი ბავშვის ჩაწერას ვერ დაგიდასტურებთ", softened
        )
    return out


def sanitise_response_wording(text: str) -> str:
    """Apply the forbidden-phrase rewrite list to an outgoing reply.

    Returns the same string when nothing matched. Idempotent. Exposed at
    module scope so tests can assert the rewrite table directly and
    other code paths (manual sim) can reuse it.
    """
    if not text:
        return text
    out = text
    # First pass — collapse duplicated "თუ … თუ …" clauses BEFORE the
    # literal rewrites so the resulting single clause can still be
    # matched/replaced if it's on the forbidden list.
    out = _collapse_duplicated_tu(out)
    # Wording Fix (2026-06-11) BUG 1 — strip the „შეშფოთება" / info-already-
    # known-about-age-and-concern preamble before the literal rewrites.
    out = _strip_concern_wording(out)
    # Config-aware fact/typography normalisations (location label, age-range
    # typography, harsh under-age softener). Must run BEFORE the literal table
    # so the fact-free „სრულად ერგება N–M …" rewrite precedes the generic
    # „სრულად ერგება" entry. NONE of these hardcode a camp fact.
    out = _apply_dynamic_fact_normalisations(out)
    # Phase 4, Task 4 — flag OFF (default) applies the FULL table; flag ON
    # applies the SAFETY subset only (same objects, same relative order).
    table = (
        _SANITIZER_SAFETY_ENTRIES
        if _use_lean_sanitizer()
        else FORBIDDEN_PHRASE_REPLACEMENTS
    )
    for needle, replacement in table:
        if needle in out:
            out = out.replace(needle, replacement)
    # Tidy any double spaces that the empty-replacement entries
    # ("precisely" → "") could have created.
    if "  " in out:
        out = re.sub(r"  +", " ", out)
    # Collapse orphaned punctuation runs (". .", " ,", " .") that
    # remain after an empty replacement chops out the surrounding text.
    out = re.sub(r"\s+\.", ".", out)
    out = re.sub(r"\s+,", ",", out)
    out = re.sub(r"\.{2,}", ".", out)
    return out.strip()


# -- anti-repeat guard + pre-turn capture ---------------------------------
#
# The system prompt already forbids re-asking a known fact; this is a
# deterministic safety net for the live „14 წლის არის …" bug so a stochastic
# model can NEVER ask for the child's age once it is on the lead.

# Real Georgian forms of "what age is the child?" are matched by the shared
# AGE_QUESTION_RE (app/reasoning/age_question.py). It catches the many ways a
# live model asks the age („რა წლისაა", „რამდენ წლისაა", „ასაკი მითხარით",
# „რომელ კლასში") that the old two-substring tuple missed, while leaving a
# CONFIRMATION („თქვენი შვილის ასაკი 14 წელია") and an ELIGIBILITY statement
# („9–17 წლის ბავშვებისთვის") untouched.

# Code-level next-step copy (NOT a prompt file) used only when the guard has
# to replace a redundant age question. Matches the existing booking wording.
_ASK_PHONE_AFTER_AGE = (
    "გმადლობთ. კონსულტაციის დასადასტურებლად მომწერეთ თქვენი ნომერი."
)
_ASK_DAYTIME_AFTER_AGE = (
    "გმადლობთ. რომელი დღე და საათი მოგწონთ კონსულტაციისთვის? "
    "გნებავთ, თავისუფალ დროებსაც შემოგთავაზებთ."
)


def _next_missing_contact_prompt(lead: Lead) -> str:
    """Ask only for the NEXT missing booking detail after the age is known:
    phone if we still need it, otherwise the preferred day/time."""
    if not (lead.phone or "").strip():
        return _ASK_PHONE_AFTER_AGE
    return _ASK_DAYTIME_AFTER_AGE


def _suppress_redundant_age_question(
    text: str, lead: Lead, conversation: Conversation,
) -> str:
    """Anti-repeat guard: if the child's age is already known but the reply
    still asks for it, STRIP only the age question (sentence-level) and keep the
    rest of the answer. When the whole reply was just the age question, replace
    it with the next missing detail. When the age is genuinely unknown the reply
    is returned untouched (asking is correct then). Uses the shared
    AGE_QUESTION_RE so every real phrasing is caught."""
    if not text:
        return text
    if not (lead.child_age or "").strip():
        return text
    if not contains_child_age_question(text):
        return text
    stripped = strip_child_age_questions(text)
    if stripped:
        logger.info(
            "[parent_llm_engine] anti-repeat: stripped a redundant child-age "
            "question, kept the rest (child_age already known)",
        )
        return stripped
    logger.info(
        "[parent_llm_engine] anti-repeat: replaced an age-only reply with the "
        "next step (child_age already known)",
    )
    return _next_missing_contact_prompt(lead)


_PHONE_ASK_VERBS = (
    "მომწერეთ", "მოგვწერეთ", "მიუთითეთ", "გაიმეორეთ", "გამომიგზავნეთ", "მოგვაწოდეთ",
)


def _sentence_is_phone_ask(sent: str) -> bool:
    """A sentence that ASKS for the phone (an ask verb + „ნომერ"). A confirmation
    („ნომერი მივიღე") or a manager-callback mention („მენეჯერი დაგიკავშირდებათ
    ნომერზე") carries no ask verb → not matched."""
    return "ნომერ" in sent and any(v in sent for v in _PHONE_ASK_VERBS)


def _strip_phone_questions(text: str) -> str:
    """Drop only the sentence(s) that re-ask for the phone; keep everything else."""
    parts = re.split(r"(?<=[.!?])\s+", text)
    kept = [p for p in parts if p.strip() and not _sentence_is_phone_ask(p)]
    return " ".join(kept).strip()


def _suppress_redundant_phone_question(
    text: str, lead: Lead, conversation: Conversation,
) -> str:
    """BUG-1 anti-repeat (2026-07-26 live test): the dynamic booking path confirmed a
    slot and then RE-asked for the phone the user had already given („ნომერი მივიღე"
    → time chosen → „მომწერეთ ნომერი" again). Mirrors _suppress_redundant_age_question:
    when lead.phone is known but the reply still asks for it, STRIP only the phone
    question and keep the rest; a phone-only reply falls back to the next missing
    detail. Phone genuinely unknown → untouched (asking is correct). Gated by
    USE_DYNAMIC_CONTACT_CAPTURE ⇒ OFF is byte-identical."""
    if not text:
        return text
    if not getattr(settings, "USE_DYNAMIC_CONTACT_CAPTURE", False):
        return text
    if not (lead.phone or "").strip():
        return text
    if not _sentence_is_phone_ask(text):
        return text
    stripped = _strip_phone_questions(text)
    if stripped:
        logger.info(
            "[parent_llm_engine] anti-repeat: stripped a redundant phone question, "
            "kept the rest (phone already known)",
        )
        return stripped
    logger.info(
        "[parent_llm_engine] anti-repeat: replaced a phone-only reply with the next "
        "step (phone already known)",
    )
    return _next_missing_contact_prompt(lead)


# Sentence-initial Georgian greeting openers. The static welcome owns the
# FIRST greeting of a conversation; a greeting on a LATER turn is a scripted
# "reset" (live bug: the agent said „გამარჯობა" mid-conversation while handling
# a manager request) and is stripped. Only a LEADING opener is removed.
_LEADING_GREETING_RE = re.compile(
    r"^\s*(?:გამარჯობა(?:თ)?|სალამი|მოგესალმებით)\s*[\s,.!:;—–-]+",
)


def _conversation_has_assistant_turn(conversation: Conversation) -> bool:
    """True when the bot has already produced at least one reply in history."""
    for turn in (getattr(conversation, "history", []) or []):
        if isinstance(turn, dict) and turn.get("role") == "assistant":
            return True
    return False


def _strip_mid_conversation_greeting(
    text: str, conversation: Conversation,
) -> str:
    """Remove a sentence-initial greeting once the conversation is underway.

    A greeting is legitimate ONLY on the bot's first reply (owned by the static
    welcome). On every later turn a leading „გამარჯობა"/„სალამი"/„მოგესალმებით"
    is a scripted reset and is stripped. Never touches mid-sentence text."""
    if not text:
        return text
    if not _conversation_has_assistant_turn(conversation):
        return text  # first reply — a greeting is fine
    stripped = _LEADING_GREETING_RE.sub("", text, count=1).lstrip()
    if stripped and stripped != text:
        logger.info(
            "[parent_llm_engine] stripped mid-conversation greeting opener",
        )
        return stripped
    return text


def _capture_turn_facts(
    conversation: Conversation, lead: Lead, user_message: str,
) -> None:
    """Pre-turn deterministic capture of the facts the parent gave THIS turn
    (child age + phone) onto the lead, BEFORE the LLM context is built — so
    the model is never asked to re-request something it already has. Both
    helpers are conservative no-ops when the field is set or the value is not
    clearly present. Never raises."""
    try:
        maybe_capture_child_age_fallback(
            lead, user_message,
            age_question_pending=_bot_recently_asked_child_age(conversation),
        )
    except Exception:
        logger.exception(
            "[parent_llm_engine] pre-turn child_age capture raised — ignored",
        )
    try:
        maybe_capture_phone_fallback(lead, user_message)
    except Exception:
        logger.exception(
            "[parent_llm_engine] pre-turn phone capture raised — ignored",
        )


# -- reasoning pass: GROUND (Phase 2, USE_REASONING_PASS) ------------------
#
# GROUND preselects ONLY the facts the ANALYZE plan named, from the CORRECT
# source, as a PER-CLASS dict. The per-class shape is load-bearing: REFLECT
# (Task 4) judges ONLY the classes present here, so a class must appear ONLY
# when we have a genuine trusted value for it (never an empty placeholder) —
# that is what keeps REFLECT from flagging a correct answer it can't ground.
# camp facts → get_camp_facts(); manager phone → get_manager_phone() (NOT the
# camp `phone` field). Never raises.

# Georgian labels for the ANSWER directive block, per grounded fact-class.
_REASONING_FACT_LABELS: dict[str, str] = {
    "price": "ფასი",
    "location": "ლოკაცია",
    "age": "ასაკი",
    "dates": "თარიღები",
    "registration": "რეგისტრაცია",
    "phone": "მენეჯერი",
}


def _reasoning_ground(needed_facts: list[str]) -> dict[str, str]:
    """Return {fact_class: trusted_value} for ONLY the classes in
    ``needed_facts`` that we can genuinely source. A class we cannot cleanly
    source is OMITTED (never guessed). ``[]``/``None`` → ``{}``. Never raises."""
    try:
        if not needed_facts:
            return {}
        wanted = {str(f).lower() for f in needed_facts if f}
        if not wanted:
            return {}
        from app.services import admin_config_service

        facts = admin_config_service.get_camp_facts() or {}
        out: dict[str, str] = {}

        if "price" in wanted:
            price = str(facts.get("price_text") or "").strip() or str(
                facts.get("price_gel") or "").strip()
            if price:
                out["price"] = price
        if "location" in wanted:
            loc = str(facts.get("location") or "").strip()
            if loc:
                out["location"] = loc
        if "age" in wanted:
            amin, amax = facts.get("age_min"), facts.get("age_max")
            if amin is not None and amax is not None:
                out["age"] = f"{amin}-{amax}"
        if "registration" in wanted:
            url = str(facts.get("registration_url") or "").strip()
            if url:
                out["registration"] = url
        if "dates" in wanted:
            streams = facts.get("streams")
            if isinstance(streams, list):
                parts = [
                    str(s.get("dates_text") or s.get("name") or "").strip()
                    for s in streams if isinstance(s, dict)
                ]
                joined = ", ".join(p for p in parts if p)
                if joined:
                    out["dates"] = joined
        if "phone" in wanted:
            phone = str(admin_config_service.get_manager_phone() or "").strip()
            if phone:
                out["phone"] = phone
        # `conditions` is intentionally NOT grounded (no clean single source);
        # REFLECT will therefore not judge it.
        return out
    except Exception:  # pragma: no cover - GROUND must never break a turn
        logger.exception("[parent_llm_engine] _reasoning_ground raised — ignored")
        return {}


def _reasoning_ground_text(grounded: dict[str, str]) -> str:
    """Compact Georgian "label: value" block of the grounded facts for the
    ANSWER directive. ``{}`` → ``""``. Never raises."""
    try:
        if not grounded:
            return ""
        lines = [
            f"{_REASONING_FACT_LABELS.get(k, k)}: {v}"
            for k, v in grounded.items() if v
        ]
        return "\n".join(lines)
    except Exception:  # pragma: no cover - defensive
        return ""


# -- reasoning pass: REFLECT (Phase 2, USE_REASONING_PASS) -----------------
#
# REFLECT is the conservative money/fact reliability guard. It judges ONLY the
# fact-classes GROUND actually populated, and uses the "correct-value-absent"
# rule: it flags a hallucination ONLY when the grounded value is NOT present in
# the answer yet a DIFFERENT token of that same class IS — i.e. the model stated
# a price/phone/link but not the grounded one. If the grounded value appears
# (even alongside others), or the class was not grounded, or no token of that
# class is present, REFLECT does NOT flag — favouring letting a good answer
# through (a false-positive fallback hurts both naturalness and reliability).
# Reuses the shipped fact regex from parent_reply_composer. Never raises.

_REASONING_SAFE_FALLBACK = (
    "ამ დეტალს მენეჯერი დაგიზუსტებთ. თუ გსურთ, დაგაკავშირებთ მენეჯერთან."
)


def _reasoning_digits(text: str) -> str:
    return "".join(ch for ch in str(text) if ch.isdigit())


_REASONING_MSG_PHONE_RE = re.compile(r"\d[\d\s\-]{5,}\d")


def _reasoning_message_has_phone(user_message: str) -> bool:
    """True when the user's OWN message this turn carries a phone-like run —
    the answer is then likely acknowledging their callback number, so
    phone-REFLECT is skipped to avoid replacing a legitimate acknowledgment."""
    try:
        return bool(_REASONING_MSG_PHONE_RE.search(user_message or ""))
    except Exception:  # pragma: no cover
        return False


def _reasoning_reflect(
    answer: str, grounded: dict, *, user_message: str = "",
) -> tuple[str, bool]:
    """Verify ``answer``'s facts against ``grounded`` (per-class). Returns
    ``(final_answer, replaced)``. Replaces the answer with a safe fallback ONLY
    on a clear contradiction on a GROUNDED class (grounded value absent but a
    different same-class token present). Never raises → ``(answer, False)``."""
    try:
        if not answer or not isinstance(answer, str) or not grounded:
            return (answer, False)
        from app.agent.llm import parent_reply_composer as prc

        # PRICE — compare numeric parts.
        if "price" in grounded:
            gnum = _reasoning_digits(grounded["price"])
            ans_nums = [n for n in
                        (_reasoning_digits(t) for t in prc._PRICE_PATTERN.findall(answer))
                        if n]
            if gnum and ans_nums and gnum not in ans_nums:
                return (_REASONING_SAFE_FALLBACK, True)

        # PHONE — compare digit-normalised numbers. Skip when the user's own
        # message carried a phone (review Important: the answer is then likely
        # acknowledging the parent's callback number, not stating a wrong
        # manager phone — replacing it would deflect a natural reply).
        if "phone" in grounded and not _reasoning_message_has_phone(user_message):
            gph = _reasoning_digits(grounded["phone"])
            ans_ph = [p for p in
                      (_reasoning_digits(t) for t in prc._PHONE_PATTERN.findall(answer))
                      if p]
            if gph and ans_ph and gph not in ans_ph:
                return (_REASONING_SAFE_FALLBACK, True)

        # REGISTRATION URL — grounded url must appear if any url is present.
        if "registration" in grounded:
            gurl = str(grounded["registration"]).strip().rstrip("/")
            urls = [u.strip().rstrip(".,)").rstrip("/") for u in prc._URL_PATTERN.findall(answer)]
            if gurl and urls and not any(gurl in u or u in gurl for u in urls):
                return (_REASONING_SAFE_FALLBACK, True)

        # dates/location intentionally not verified (fuzzy → false-positive risk).
        return (answer, False)
    except Exception:  # pragma: no cover - REFLECT must never break a turn
        logger.exception("[parent_llm_engine] _reasoning_reflect raised — ignored")
        return (answer, False)


# -- reasoning pass: ANSWER orchestration (Phase 2, USE_REASONING_PASS) ----
#
# Ties ANALYZE→GROUND into a (grounded_facts, plan_directive) pair consumed by
# run_parent_llm_turn. Flag-gated; SKIPS dynamic-program turns (not camp-
# groundable → REFLECT would false-positive on their prices); fail-safe → the
# normal ANSWER path runs untouched on any failure. Flag OFF ⇒ ({}, None) ⇒
# no directive appended + no REFLECT ⇒ byte-identical.

_REASONING_KNOWLEDGE_KEYS = (
    "price", "dates", "location", "age", "registration", "conditions", "phone",
)


def _reasoning_is_dynamic_program_turn(user_message: str) -> bool:
    """True when the message NAMES an active NON-reserved (dynamic) program —
    such a turn isn't camp-groundable, so the reasoning pass skips it. Safe."""
    try:
        from app.services import admin_config_service
        from app.reasoning.dynamic_program_match import match_dynamic_program
        m = match_dynamic_program(
            user_message, admin_config_service.get_active_sections(),
        )
        return bool(m and m.get("program_id") not in reserved_program_ids())
    except Exception:
        return False


def _reasoning_build_directive(plan: dict, grounded: dict) -> str | None:
    """Assemble the extra ANSWER system directive from the plan + grounded
    facts + a SOFT suggested-tool hint. None when there's nothing useful."""
    try:
        parts: list[str] = []
        p = str(plan.get("plan") or "").strip()
        if p:
            parts.append(p)
        facts = _reasoning_ground_text(grounded)
        if facts:
            parts.append(
                "გადამოწმებული ფაქტები — ფასზე/თარიღზე/ტელეფონზე/ბმულზე უპასუხე "
                "მხოლოდ ამათგან; თუ საჭირო ფაქტი აქ არ არის, ჰკითხე ან შესთავაზე "
                "მენეჯერი, ნუ იგონებ:\n" + facts
            )
        st = plan.get("suggested_tool")
        if st:
            parts.append(
                f"ანალიზი მიუთითებს, რომ სავარაუდოდ საჭიროა ხელსაწყო `{st}` — "
                "გამოიძახე ჯერ, თუ კითხვას ეს ფაქტები სჭირდება."
            )
        if not parts:
            return None
        return "[მსჯელობის გეგმა]\n" + "\n\n".join(parts)
    except Exception:  # pragma: no cover - defensive
        return None


def _reasoning_prepare(
    conversation: Conversation, lead: Lead, user_message: str,
) -> tuple[dict, str | None]:
    """Flag-gated ANALYZE + GROUND. Returns (grounded_facts, plan_directive).
    Flag OFF / dynamic-program turn / any failure → ({}, None). Never raises."""
    try:
        if not getattr(settings, "USE_REASONING_PASS", False):
            return ({}, None)
        if _reasoning_is_dynamic_program_turn(user_message):
            return ({}, None)
        from app.agent.llm import parent_turn_analyzer
        tool_names = [
            t.get("function", {}).get("name")
            for t in build_active_tools(
                getattr(settings, "USE_DYNAMIC_PROGRAMS", False),
                getattr(settings, "USE_LEARNING", False),
            )
        ]
        tool_names = [t for t in tool_names if t]
        plan = parent_turn_analyzer.analyze_for_engine(
            user_message=user_message, lead=lead, conversation=conversation,
            knowledge_keys=list(_REASONING_KNOWLEDGE_KEYS), tool_names=tool_names,
        )
        if not plan:
            return ({}, None)
        grounded = _reasoning_ground(plan.get("needed_facts", []))
        directive = _reasoning_build_directive(plan, grounded)
        return (grounded, directive)
    except Exception:  # pragma: no cover - the pass is best-effort
        logger.exception("[parent_llm_engine] _reasoning_prepare raised — ignored")
        return ({}, None)


# -- public entry ---------------------------------------------------------


def run_parent_llm_turn(
    *,
    user_message: str,
    conversation: Conversation,
    lead: Lead,
    sender_id: str,
    platform: str,
) -> str:
    """Run one PARENT turn through the LLM engine.

    Returns the final assistant text, or ``""`` on any failure so the
    caller (parent_flow.handle) can fall back to the legacy flow. Never
    raises.
    """
    try:
        system_prompt = _build_system_prompt(user_message, "PARENT")
    except Exception as exc:
        logger.exception(
            "[parent_llm_engine] system prompt assembly failed: %s", exc,
        )
        _trace_parent_llm_decision(
            answer_source="fallback",
            fallback_reason="prompt_unavailable",
        )
        return ""

    # Pre-turn structured capture (live bug „14 წლის არის 595999733"): land
    # the child age + phone the parent gave THIS turn onto the lead BEFORE we
    # build the context, so the model never re-asks for a fact it already has.
    _capture_turn_facts(conversation, lead, user_message)

    # Reasoning pass (Phase 2, USE_REASONING_PASS) — think before answering.
    # Flag OFF ⇒ ({}, None) ⇒ no directive appended + no REFLECT ⇒ byte-identical.
    _reason_grounded, _reason_directive = _reasoning_prepare(
        conversation, lead, user_message,
    )

    if _use_slim_prompts():
        # Slim mode: inject ONLY the planner policy + selected_state (topic-
        # scoped) instead of the full lead-context + giant sales context.
        slim_state, slim_policy = _build_slim_context(conversation, lead)
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "system", "content": slim_state},
            {"role": "system", "content": slim_policy},
        ]
        _trace_prompt_mode("slim", slim_state)
    else:
        context_message = _build_context_message(conversation, lead, user_message)
        sales_context = _build_sales_context(conversation, lead, user_message)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "system", "content": context_message},
            {"role": "system", "content": sales_context},
        ]
        _trace_prompt_mode("giant", None)
    messages.extend(_recent_history(conversation))
    # Reasoning directive (a SEPARATE system message — never concatenated into
    # the giant prompt). Present only when the flag-gated pass produced a plan.
    if _reason_directive:
        messages.append({"role": "system", "content": _reason_directive})
    messages.append({"role": "user", "content": user_message})

    executor = ParentToolExecutor(
        conversation=conversation,
        lead=lead,
        sender_id=sender_id,
        platform=platform,
        user_message=user_message or "",
    )

    iterations = 0
    saw_tool_call = False
    while iterations < MAX_TOOL_ITERATIONS:
        iterations += 1
        try:
            response = openai_service.chat_with_tools(
                messages=messages,
                tools=build_active_tools(
                    settings.USE_DYNAMIC_PROGRAMS,
                    settings.USE_LEARNING,
                    getattr(settings, "USE_PROGRAM_TOPICS", False),
                ),
                tool_choice="auto",
                max_tokens=DEFAULT_MAX_TOKENS,
                temperature=DEFAULT_TEMPERATURE,
            )
        except Exception as exc:
            logger.exception(
                "[parent_llm_engine] chat_with_tools failed (iter=%d): %s",
                iterations, exc,
            )
            _trace_parent_llm_decision(
                answer_source="fallback",
                fallback_reason="llm_chat_error",
                used_tool=saw_tool_call,
            )
            return ""

        choice = _first_choice(response)
        if choice is None:
            logger.warning(
                "[parent_llm_engine] response had no choices (iter=%d)",
                iterations,
            )
            _trace_parent_llm_decision(
                answer_source="fallback",
                fallback_reason="llm_no_choices",
                used_tool=saw_tool_call,
            )
            return ""

        msg = _choice_message(choice)
        tool_calls = _tool_calls(msg)
        final_content = _message_content(msg)

        if not tool_calls:
            # Model answered directly — return its text. Empty content
            # is treated as a soft failure and triggers the fallback.
            if not final_content:
                logger.warning(
                    "[parent_llm_engine] empty final content with no tool calls",
                )
                _trace_parent_llm_decision(
                    answer_source="fallback",
                    fallback_reason="llm_empty_final",
                    used_tool=saw_tool_call,
                )
                return ""
            # Post-turn structured-state fallback: if the LLM
            # acknowledged the child's age / challenge in prose but
            # never called ``save_lead_info`` for it, capture from the
            # user message so downstream context (booking, manager
            # email, follow-up, CRM) still has the field.
            try:
                maybe_capture_child_age_fallback(
                    lead, user_message,
                    age_question_pending=_bot_recently_asked_child_age(
                        conversation,
                    ),
                )
            except Exception:
                logger.exception(
                    "[parent_llm_engine] child_age fallback raised — ignored",
                )
            try:
                maybe_capture_challenge_fallback(lead, user_message)
            except Exception:
                logger.exception(
                    "[parent_llm_engine] challenge fallback raised — ignored",
                )
            cleaned = sanitise_response_wording(final_content.strip())
            # Anti-repeat safety net: never re-ask the child's age once known.
            cleaned = _suppress_redundant_age_question(cleaned, lead, conversation)
            # BUG-1 (2026-07-26 live test): never re-ask a phone the user already gave.
            cleaned = _suppress_redundant_phone_question(cleaned, lead, conversation)
            # Never greet again mid-conversation (scripted-reset guard).
            final_answer = _strip_mid_conversation_greeting(cleaned, conversation)
            # REFLECT (Phase 2) — verify the answer's facts against the grounded
            # ones; replace a clear hallucination with a safe fallback. No-op
            # when the pass didn't ground anything (flag off ⇒ {} ⇒ unchanged).
            if _reason_grounded:
                final_answer, _reason_replaced = _reasoning_reflect(
                    final_answer, _reason_grounded, user_message=user_message,
                )
                if _reason_replaced:
                    logger.info("[parent_llm_engine] REFLECT replaced a hallucinated fact")
            _trace_parent_llm_decision(
                route_owner="parent_llm_engine",
                intent="parent_llm_response",
                answer_source="llm_tool_loop" if saw_tool_call else "llm_direct",
                used_tool=saw_tool_call,
            )
            return final_answer

        saw_tool_call = True

        # Append the assistant message that issued tool_calls so the
        # next round of messages references it correctly.
        messages.append(_assistant_message_for_tool_calls(msg))

        for tool_call in tool_calls:
            tool_name = _tool_name(tool_call)
            raw_args = _tool_args(tool_call)
            parsed_args = _parse_tool_args(raw_args)

            logger.info(
                "[parent_llm_engine] tool_call name=%s args=%r",
                tool_name, parsed_args,
            )

            result = executor.execute(tool_name, parsed_args)

            logger.info(
                "[parent_llm_engine] tool_result name=%s success=%s reason=%s",
                tool_name, result.get("success"), result.get("reason"),
            )

            messages.append({
                "role": "tool",
                "tool_call_id": _tool_call_id(tool_call),
                "name": tool_name,
                "content": serialize_result(result),
            })

    # Loop budget exhausted. Bail to the legacy flow.
    logger.warning(
        "[parent_llm_engine] tool iteration cap (%d) reached — falling back",
        MAX_TOOL_ITERATIONS,
    )
    _trace_parent_llm_decision(
        answer_source="fallback",
        fallback_reason="tool_loop_limit",
        used_tool=saw_tool_call,
    )
    return ""


# -- prompt + context assembly -------------------------------------------


def _use_slim_prompts() -> bool:
    """Slim Prompt mode (Class 4). When ON, the engine loads the short
    `parent_core.md` core prompt instead of the 100 KB `system_parent_v2.md`,
    and injects only the planner policy + selected_state (the giant
    situation-aware sales context is replaced)."""
    return bool(getattr(settings, "USE_SLIM_PROMPTS", False))


def _use_lean_prompt() -> bool:
    """Lean Prompt mode (Phase 4, Task 3). When ON, the engine loads the
    ~120-160 line `parent_lean.md` instead of the 468-line
    `system_parent_v2.md`. Every guardrail is preserved per the
    executor-verified map (`docs/PHASE4_GUARDRAIL_MAP_2026_07_21.md`) —
    short behavioral rules where a backend mechanism enforces the
    guarantee, exact verbatim sentences where it's prompt-only. Default
    OFF ⇒ `system_parent_v2.md` still loads, byte-identical."""
    return bool(getattr(settings, "USE_LEAN_PROMPT", False))


# Off-topic intelligence (USE_OFFTOPIC_INTELLIGENCE, 2026-07-25) — rewrite the two
# camp-specific off-topic scripts in the loaded prompt to be PROGRAM-AGNOSTIC and
# logic-oriented. Targeted substring swaps (no tricky Georgian quotes) so an exact
# match is robust; a no-op when the flag is off or the anchor text is absent (e.g. a
# slim/lean prompt), so flag-off is byte-identical.
_OFFTOPIC_POLITICAL_OLD = "ბანაკთან დაკავშირებულ კითხვებზე დაგეხმარებით"
_OFFTOPIC_POLITICAL_NEW = "სიამოვნებით დაგეხმარებით ჩვენს პროგრამებთან დაკავშირებით"
_OFFTOPIC_UNCLEAR_OLD = "- როცა მომხმარებლის ფრაზა გაუგებარია, ჰკითხე თავაზიანად: "
_OFFTOPIC_UNCLEAR_NEW = (
    "- თუ მომხმარებლის კითხვა ჩვენს პროგრამებს არ ეხება (მაგ. მულტფილმის/წიგნის "
    "პერსონაჟი, ამინდი, ზოგადი ცოდნა) — ბრმად ნუ დააზუსტებ ფრაზის გამეორებით და ნუ "
    "ახსენებ პოლიტიკას; თავაზიანად თქვი, რომ ეს შენი დახმარების სფეროს გარეთაა და "
    "შესთავაზე ჩვენი აქტიური პროგრამები. მხოლოდ ნამდვილი აკრეფის-შეცდომისას ჰკითხე "
    "თავაზიანად: "
)


# BUG-2 (2026-07-26 live test): the ~24KB camp-centric system prompt made the LLM
# default to offering „საზაფხულო ბანაკი" even on an OFF-TOPIC turn (asked the weather
# → „თუ ბანაკის პროგრამის დეტალები გაინტერესებთ…"), despite USE_OFFTOPIC_INTELLIGENCE
# being on. The 2 targeted line rewrites can't overcome the camp-saturated body, so we
# APPEND a strong program-agnostic directive: state the camp-off reality and route every
# redirect to the ACTIVE programs from the tool. Logic (reflects camp status = data), not
# a sanitizer ban. Reflects the camp-always-off constraint; gated by the same flag.
_OFFTOPIC_PROGRAM_AGNOSTIC_DIRECTIVE = (
    "\n\n[პროგრამა-აგნოსტიკური წესი — CRITICAL] საზაფხულო ბანაკი ამჟამად დასრულებულია "
    "და აქტიური შეთავაზება არ არის. *არასოდეს* შესთავაზო ან default-ად ახსენო ბანაკი, "
    "როგორც ხელმისაწვდომი. როცა კითხვა ჩვენს პროგრამებს არ ეხება (off-topic), ან "
    "გჭირდება გადამისამართება, ან მომხმარებელი კითხულობს რას სთავაზობთ — ახსენე მხოლოდ "
    "ამჟამად აქტიური პროგრამები — მათი სახელები აიღე list_programs / get_program_info "
    "ხელსაწყოდან, არა მეხსიერებიდან. თუ არ იცი აქტიური პროგრამები, გამოიძახე list_programs."
)


def _apply_offtopic_intelligence(prompt: str) -> str:
    """Program-agnostic, logic-oriented off-topic guidance. Flag off ⇒ unchanged."""
    if not getattr(settings, "USE_OFFTOPIC_INTELLIGENCE", False):
        return prompt
    rewritten = (
        prompt
        .replace(_OFFTOPIC_POLITICAL_OLD, _OFFTOPIC_POLITICAL_NEW)
        .replace(_OFFTOPIC_UNCLEAR_OLD, _OFFTOPIC_UNCLEAR_NEW)
    )
    return rewritten + _OFFTOPIC_PROGRAM_AGNOSTIC_DIRECTIVE


def _build_system_prompt(message: str = "", segment: str = "") -> str:
    # Canonical Admin Config age band (5A-2 migration) — runtime prompt
    # context only; the `system_parent_v2.md` file is untouched. With the
    # shipped config the band stays 9–17, so the rendered prompt is identical.
    from app.services import admin_config_service
    age_min, age_max = admin_config_service.get_camp_age_bounds()

    company_name = settings.COMPANY_NAME or "სიტყვის აკადემია"
    # Class 4: slim mode loads the short core prompt; Phase 4 lean mode loads
    # the guardrail-preserving lean prompt; default loads the giant prompt
    # exactly as before (do NOT load system_parent_v2.md when slim/lean).
    if _use_slim_prompts():
        prompt_name = "parent_core"
    elif _use_lean_prompt():
        prompt_name = "parent_lean"
    else:
        prompt_name = "system_parent_v2"
    raw = load_prompt(prompt_name)
    base_prompt = raw.format(
        company_name=company_name,
        age_min=age_min,
        age_max=age_max,
    )
    base_prompt = _apply_offtopic_intelligence(base_prompt)
    return (
        base_prompt
        + _dynamic_programs_prompt_suffix()
        + _approved_answer_prompt_suffix()
        + _topic_tool_prompt_suffix()
        + _skills_prompt_suffix(message, segment)
    )


def _build_slim_context(conversation, lead) -> tuple[str, str]:
    """Build the (selected_state, planner_policy) system blocks for slim mode
    from the turn plan stashed on the conversation. Topic-scoped: only the
    relevant state reaches the LLM (Class 3). Never raises."""
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


# =========================================================================
# Live Polish Patch (2026-06-09) — confirmation intent normalization
# and context-aware thank-you closing helpers.
# =========================================================================

# Closed-set phrases that mean "yes, I want the consultation you offered."
# Stored lower-cased; matched against the stripped lower-cased user message.
_BOOKING_CONFIRMATION_PHRASES: frozenset[str] = frozenset({
    "კი მინდა",
    "კიმინდა",
    "დიახ მინდა",
    "მინდა",
    "კი",
    "დიახ",
    "მაწყობს",
    "კი მაწყობს",
    "დამიდასტურეთ",
    "ვადასტურებ",
})

# Phrases whose presence in the LAST ASSISTANT turn means a booking offer
# was extended. We check the most recent assistant turn only.
#
# Live Smoke Followup (2026-06-10): the brand-standard slot offer reads
# „<date>, <time> საათი თავისუფალია. თუ ეს დრო გაწყობთ, დამიდასტურეთ და
# კონსულტაციას ჩავნიშნავ.“ — none of the original stems matched it
# („ჩავნიშნავ" ≠ „ჩავნიშნო", and „კონსულტაცია ჩავნიშნავ" missed the
# genitive „კონსულტაცია**ს** ჩავნიშნავ"). Added the literal offer
# markers so `_last_bot_offered_booking` recognises the real wording.
_BOOKING_OFFER_STEMS: tuple[str, ...] = (
    "კონსულტაციაზე ჩაგწერთ",
    "კონსულტაციაზე ჩამიწერ",
    "კონსულტაცია ჩავნიშნავ",
    "ჩავნიშნოთ",
    "ჩაგინიშნავ",
    "ჩაგწერთ",
    "ჩავნიშნო",
    "ჩავნიშნავ",
    "დამიდასტურეთ",
    "თავისუფალია",
)

# Phrases that mark a "thank you" from the user.
_THANKS_PHRASES: tuple[str, ...] = (
    "მადლობა",
    "გმადლობ",
    "მადლობთ",
)


def _last_bot_offered_booking(conversation: Conversation) -> bool:
    """Return True if the most-recent assistant message contained a
    booking-offer phrase.  Returns False on any structure anomaly."""
    for turn in reversed(list(conversation.history or [])):
        if not isinstance(turn, dict):
            continue
        if turn.get("role") == "assistant":
            content = (turn.get("content") or "").lower()
            return any(stem in content for stem in _BOOKING_OFFER_STEMS)
    return False


# Strong, unambiguous confirmation lead phrases — matched even when the
# user appends an extra question / clause in the same message
# (e.g. „კი მაწყობს ეს დრო, მენეჯერი რომელ საათამდე მუშაობს?"). Bare
# tokens like „კი" / „დიახ" / „მინდა" are intentionally EXCLUDED here —
# they stay exact-match only (via `_BOOKING_CONFIRMATION_PHRASES`) so a
# soft objection („კი, მაგრამ ჯერ ფასი…") or an unrelated „მინდა ვიცოდე…"
# never reads as a clean booking confirmation.
_STRONG_CONFIRM_LEAD_PHRASES: tuple[str, ...] = (
    "კი მაწყობს",
    "კი, მაწყობს",
    "დიახ მაწყობს",
    "კი მინდა",
    "კი, მინდა",
    "დიახ მინდა",
    "კი ვადასტურებ",
    "მაწყობს",
    "ვადასტურებ",
    "ვადასტურ",
    "დამიდასტურეთ",
    "დავადასტურებ",
)

# Negation markers — when present in the leading clause, the message is
# NOT a confirmation („არ მინდა" / „არა" / „ვერ").
_CONFIRM_NEGATION_TOKENS: tuple[str, ...] = ("არ ", "არა", "ვერ ")


def _user_confirmed_booking(user_message: str) -> bool:
    """Return True when the user's current message is a confirmation of a
    previously offered consultation booking.

    Live Smoke Followup (2026-06-10): the original implementation only
    matched the WHOLE message exactly against `_BOOKING_CONFIRMATION_PHRASES`,
    so „კი მაწყობს ეს დრო, მენეჯერი რომელ საათამდე მუშაობს?" (a clear
    confirmation + an extra question) did NOT register — the agent then
    re-asked for confirmation. We now also accept a strong confirmation
    phrase at the START of the leading clause, with a negation guard so
    „არ მინდა" / „არა" never reads as a yes.
    """
    text = (user_message or "").strip().lower()
    # Normalize common typo / joined form before matching
    text = text.replace("კიმინდა", "კი მინდა")
    if not text:
        return False
    # Whole-message exact match (covers bare „კი" / „დიახ" / „მინდა").
    if text in _BOOKING_CONFIRMATION_PHRASES:
        return True
    # Leading-clause match for confirmation + extra question / clause.
    head = re.split(r"[?.!,]", text, 1)[0].strip()
    if any(neg in head for neg in _CONFIRM_NEGATION_TOKENS):
        return False
    for phrase in _STRONG_CONFIRM_LEAD_PHRASES:
        if head == phrase or head.startswith(phrase + " "):
            return True
    return False


def _user_said_thanks(user_message: str) -> bool:
    """Return True when the user's message contains a thanks phrase."""
    text = (user_message or "").strip().lower()
    return any(phrase in text for phrase in _THANKS_PHRASES)


def _build_context_message(
    conversation: Conversation,
    lead: Lead,
    user_message: str = "",
) -> str:
    """Compact one-block context summary appended after the main system
    prompt. Kept short on purpose — the model treats it as state, not
    narrative.

    P3-C PATCH 5: when a pending booking has been recorded (e.g. the
    user explicitly chose a slot last turn), surface its datetime here
    so the LLM does not need to remember the slot across a modality
    interruption. The compact key/value form keeps the addition tight.

    Booking Date Parse Patch (2026-06-04): always include today's
    Tbilisi date so the LLM never has to guess. When the user's current
    message contains a Georgian relative-date phrase (ხვალ / ზეგ / დღეს)
    we resolve it server-side and surface the ISO so the LLM never has
    to derive it. This eliminates the live-bug where the LLM treated
    "ხვალ" as a past date.
    """
    now_dt = now_tbilisi()
    # Live QA Patch (2026-06-05) — Bug 4: surface adult-target context
    # to the PARENT engine. When the user first asked about an ADULT
    # event for „ჩემი შვილისთვის" / „ჩემი ძმისთვის" and then switched
    # to camp, the LLM lost sight of the relation/age it already
    # captured under adult_target_relation / adult_target_age. By
    # surfacing them here the camp engine can acknowledge „თქვენი
    # შვილის ასაკი X მიუთითეთ" instead of re-asking.
    adult_target_relation = (
        getattr(lead, "adult_target_relation", "") or ""
    ).strip()
    adult_target_age = (
        getattr(lead, "adult_target_age", "") or ""
    ).strip()
    parts = [
        f"today_iso_tbilisi={now_dt.date().isoformat()}",
        f"now_iso_tbilisi={now_dt.isoformat(timespec='minutes')}",
        f"name={(lead.name or '').strip() or '—'}",
        f"phone={(lead.phone or '').strip() or '—'}",
        f"child_age={(lead.child_age or '').strip() or '—'}",
        f"challenge={(lead.challenge or '').strip() or '—'}",
        f"state={conversation.state}",
        f"booked={'yes' if lead.calendly_booked else 'no'}",
    ]
    if adult_target_relation:
        parts.append(f"adult_target_relation={adult_target_relation}")
    if adult_target_age:
        parts.append(f"adult_target_age={adult_target_age}")
    if lead.booked_datetime_iso:
        parts.append(f"booked_datetime_iso={lead.booked_datetime_iso}")

    pending = getattr(conversation, "pending_booking", None) or {}
    pending_iso = (pending.get("requested_datetime_iso") or "").strip()
    if pending_iso:
        parts.append(
            f"pending_booking_iso={pending_iso}"
            f"; pending_confirmed={'yes' if pending.get('user_confirmed_datetime') else 'no'}"
            f"; pending_source={pending.get('source') or '—'}"
        )

    if user_message:
        try:
            resolved = resolve_relative_datetime(user_message, now=now_dt)
        except Exception:
            resolved = None
        if resolved is not None:
            parts.append(
                f"resolved_relative_datetime_iso={resolved.isoformat(timespec='minutes')}"
            )

    return "Current lead context: " + "; ".join(parts) + "."


# P3-C PATCH 3 — compact sales-context reminder.
# 4–6 short lines, dynamically chosen based on what we know about the
# parent's state. This is *not* the full audience YAML / sales policy —
# it's a runtime hint so the model adapts its tone. The full source
# documents (PDF, DOCX) are NEVER injected into the prompt.

_PRICE_KEYWORDS: tuple[str, ...] = (
    "ფასი", "ღირს", "ღირებულება", "რამდენი", "გადახდა", "გადანაწილება",
)
_DECLINE_KEYWORDS: tuple[str, ...] = (
    "არ მინდა", "არა მადლობა", "მერე", "არ არის საჭირო",
    "უარს ვამბობ", "გავაუქმოთ",
)


def _user_asked_price(history: list[dict[str, str]], latest: str) -> bool:
    """Was a price-question asked by the user in the last few turns or
    in the current message?"""
    text = (latest or "").lower()
    if any(kw in text for kw in _PRICE_KEYWORDS):
        return True
    for turn in (history or [])[-6:]:
        if not isinstance(turn, dict) or turn.get("role") != "user":
            continue
        content = (turn.get("content") or "").lower()
        if any(kw in content for kw in _PRICE_KEYWORDS):
            return True
    return False


def _user_declined(conversation: Conversation, latest: str) -> bool:
    if (conversation.followup_blocked_reason or "") in {
        "declined", "asked_no_more_messages",
    }:
        return True
    text = (latest or "").lower()
    return any(kw in text for kw in _DECLINE_KEYWORDS)


def _age_status(lead: Lead) -> str:
    """Return one of 'unknown', 'eligible', 'ineligible'."""
    raw = (lead.child_age or "").strip()
    if not raw:
        return "unknown"
    digits = ""
    for ch in raw:
        if ch.isdigit():
            digits += ch
        elif digits:
            break
    if not digits:
        return "unknown"
    try:
        age = int(digits)
    except ValueError:
        return "unknown"
    # Canonical age band (source-of-truth migration 5A-1, 2026-06-22): the
    # Admin Config camp facts win (was a direct camp_2026.yaml read), so an
    # operator age-range edit reaches this engine eligibility helper too.
    from app.services import admin_config_service
    lo, hi = admin_config_service.get_camp_age_bounds()
    if lo <= age <= hi:
        return "eligible"
    return "ineligible"


def _build_sales_context(
    conversation: Conversation, lead: Lead, user_message: str,
) -> str:
    """Compact, situation-aware reminder of the sales policy.

    Roughly 4–6 lines, all in Georgian, tailored to what we currently
    know. The reminder lists what to do *next*, not a long script. The
    full audience YAML is NOT injected; this is a curated subset.

    Live Polish Patch (2026-06-09):
    - When the previous bot turn offered a consultation AND the current
      user message is a confirmation phrase (კი/მინდა/კიმინდა/…), inject
      an explicit instruction to proceed with the booking flow directly —
      do NOT ask "გსურთ კონსულტაცია?" again.
    - When user says "მადლობა", inject the correct context-aware closing
      hint so the LLM never falls back to standalone "სიამოვნებით.".
    """
    age = _age_status(lead)
    asked_price = _user_asked_price(conversation.history, user_message)
    declined = _user_declined(conversation, user_message)
    booked = bool(lead.calendly_booked)
    adult_subscription_status = (
        getattr(conversation, "adult_subscription_status", "") or ""
    ).strip()

    lines: list[str] = ["Sales context (აუდიტორიაზე მორგებული გაყიდვა):"]

    # --- Confirmation after offer: skip re-asking ---
    if (
        _last_bot_offered_booking(conversation)
        and _user_confirmed_booking(user_message)
        and not booked
    ):
        lines.append(
            "- მომხმარებელმა კონსულტაციაზე ჩაწერა დაადასტურა"
            f" (\"{user_message.strip()}\")."
            " პირდაპირ გააგრძელე ჩაწერის ფლოუ —"
            " *ნუ* ჰკითხო ხელახლა \"გსურთ კონსულტაცია?\"."
        )
        lines.append(
            "- შემდეგი ნაბიჯი: სახელი/ნომერი (თუ აკლია) → სლოტი →"
            " book_consultation."
        )
        return "\n".join(lines)

    # --- Thank-you closing hint ---
    if _user_said_thanks(user_message):
        # Phase 4 / Task 3 (M2): under the lean prompt, don't re-inject the
        # full hardcoded verbatim script here — the exact mandated sentences
        # already live in `parent_lean.md` itself (loaded fresh every turn),
        # so a second literal script in the per-turn context would fight the
        # lean prompt's "let the model reason/vary" goal. A short behavioral
        # pointer is enough. Flag-OFF path below is untouched/byte-identical.
        if _use_lean_prompt():
            if booked:
                lines.append(
                    "- მომხმარებელი მადლობას ხდის დაჯავშნის შემდეგ —"
                    " დაადასტურე თბილად, რომ კონსულტაცია ჩანიშნულია და"
                    " მენეჯერი დაუკავშირდება."
                )
            elif adult_subscription_status in ("subscribed", "ok"):
                lines.append(
                    "- მომხმარებელი მადლობას ხდის სუბსქრიფციის შემდეგ —"
                    " დაადასტურე თბილად მომავალი ღონისძიების შეტყობინების"
                    " პირობა."
                )
            else:
                lines.append(
                    "- მომხმარებელი მადლობას ხდის — მოკლედ და თბილად"
                    " უპასუხე."
                )
            lines.append(
                "- *არასოდეს* გამოიყენო \"სიამოვნებით.\" მარტო — ეს"
                " ზედმეტად ფორმალური/რობოტული ჟღერს."
            )
            return "\n".join(lines)
        if booked:
            lines.append(
                "- მომხმარებელი მადლობას ხდის დაჯავშნის შემდეგ."
                " გამოიყენე: \"მადლობა თქვენ."
                " კონსულტაცია ჩანიშნულია და მენეჯერი დაგიკავშირდებათ.\""
            )
        elif adult_subscription_status in ("subscribed", "ok"):
            lines.append(
                "- მომხმარებელი მადლობას ხდის სუბსქრიფციის შემდეგ."
                " გამოიყენე: \"მადლობა თქვენ."
                " როცა ახალი ღონისძიება დაემატება,"
                " დეტალებს პირად შეტყობინებაში გამოგიგზავნით.\""
            )
        else:
            lines.append(
                "- მომხმარებელი მადლობას ხდის."
                " გამოიყენე: \"მადლობა თქვენ."
                " თუ კიდევ დაგჭირდებათ ინფორმაცია, მომწერეთ.\""
            )
        lines.append(
            "- *არასოდეს* გამოიყენო \"სიამოვნებით.\" — ეს ზედმეტად"
            " ფორმალური/რობოტური ჟღერს."
        )
        return "\n".join(lines)

    if booked:
        lines.append(
            "- მომხმარებელი უკვე დაჯავშნა — დაიცავი DONE-ის წესები."
        )
    elif declined:
        lines.append(
            "- მომხმარებელმა უარი თქვა — *არ* შესთავაზო ბანაკი/კონსულტაცია; "
            "მხოლოდ თბილი დახურვა."
        )
    else:
        if age == "unknown":
            lines.append(
                "- ბავშვის ასაკი უცნობია — ბუნებრივად ჰკითხე ადრე."
            )
        if age == "ineligible":
            lines.append(
                "- ბავშვის ასაკი დიაპაზონს არ ერგება — *არ* შესთავაზო "
                "ბანაკზე დაჯავშნა; შესთავაზე მენეჯერთან გადამოწმება."
            )
        if age == "eligible":
            # Live Smoke Followup (2026-06-10) — Part 3: when the child is
            # eligible but the parent's goal/challenge is not yet captured,
            # ask ONE clean goal question. Once it is known, move on — do
            # not re-ask. Booking is never blocked: an explicit booking
            # confirmation short-circuits earlier (see the confirmation
            # branch above), so this hint only shapes the discovery turn.
            if not (lead.challenge or "").strip():
                # Phase 4 / Task 3 (M2, review finding I-2): the hardcoded
                # verbatim discovery question below is a SECOND script — under
                # the lean prompt it fights `parent_lean.md`'s own "ask one
                # natural motivational question" rule. Emit a behavioral
                # pointer instead, keeping every guarantee (don't force a
                # concern; never block an explicit booking request). Flag-OFF
                # path below is untouched/byte-identical.
                if _use_lean_prompt():
                    lines.append(
                        "- ასაკი დიაპაზონშია, მიზანი უცნობია — დასვი ერთი "
                        "ბუნებრივი მოტივაციური კითხვა; შეშფოთება ნუ "
                        "აიძულებ; ცხადი ჩაწერის მოთხოვნა არ დაბლოკო."
                    )
                else:
                    lines.append(
                        "- ასაკი დიაპაზონშია, მშობლის მიზანი ჯერ უცნობია — "
                        "დასვი ერთი მკაფიო კითხვა: „რა არის მთავარი, რის "
                        "მიღებაც გსურთ ბანაკიდან — ახალი მეგობრები, ეკრანთან "
                        "დროის შემცირება, თვითგამოხატვა, თავდაჯერება თუ სხვა?“ "
                        "შეშფოთება არ აიძულო. თუ მომხმარებელი ცხადად ითხოვს "
                        "ჩაწერას — ჯერ ჩაწერა, მიზანი ნუ დაბლოკავს."
                    )
            else:
                lines.append(
                    "- ასაკი დიაპაზონშია და მშობლის მიზანი ცნობილია — "
                    "გადადი ღირებულებაზე/ჩაწერაზე; მოტივაცია ხელახლა "
                    "ნუ ჰკითხავ."
                )
        if asked_price:
            lines.append(
                "- მომხმარებელმა ფასი იკითხა — ჯერ ფასი თქვი, შემდეგ "
                "მოაქცი ღირებულების კონტექსტში და დაუმატე რბილი CTA."
            )
        else:
            lines.append(
                "- მომხმარებელს ფასი არ უკითხავს — *არ* დაიწყო ფასით; "
                "ჯერ ღირებულება და მოტივაცია."
            )
        lines.append(
            "- ღირებულების კუთხეები: გარემო, ცოცხალი ურთიერთობა, "
            "აზროვნება, ეკრანისგან დისტანცია, სწორი წრე, აზრიანი ზაფხული."
        )
        lines.append(
            "- მოკლე, თბილი ქართული. 1–3 წინადადება. ერთი კითხვა მაქსიმუმ."
        )

    return "\n".join(lines)


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
    return parsed if isinstance(parsed, dict) else {}


def _assistant_message_for_tool_calls(msg: Any) -> dict[str, Any]:
    """Re-serialize the assistant message that issued tool_calls into a
    plain dict so we can re-feed it into ``messages`` on the next loop
    iteration. The OpenAI SDK accepts dicts here even when the original
    response was a Pydantic object."""
    tool_calls_out: list[dict[str, Any]] = []
    for tc in _tool_calls(msg):
        tool_calls_out.append({
            "id": _tool_call_id(tc),
            "type": "function",
            "function": {
                "name": _tool_name(tc),
                "arguments": _tool_args(tc) or "{}",
            },
        })
    return {
        "role": "assistant",
        "content": _message_content(msg) or None,
        "tool_calls": tool_calls_out,
    }
