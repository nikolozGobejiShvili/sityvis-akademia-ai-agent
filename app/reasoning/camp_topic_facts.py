"""Deterministic camp-TOPIC classifier + focused answer renderer (2026-06-28).

Live need: a camp-related question („უსაფრთხოება როგორ არის?", „კვება შედის?",
„ბავშვი სულ ტელეფონშია") was answered with the whole camp description. This
module classifies the parent's SPECIFIC concern into ONE of ~16 camp topics and
returns ONLY that topic's focused block — never the full dump.

Design (matches the repo's deterministic-first idiom — cf.
`app/reasoning/legacy_actions.py`, `app/reasoning/age_question.py`):

  * Facts live in `app/agent/knowledge/camp_topic_facts.yaml` (triggers +
    answer per topic). This module loads them via the shared knowledge loader.
  * `detect_camp_topic(message)` lowercases the message, FIRST applies the
    canonical-flow EXCLUSIONS (price / dates / registration link / Sunday
    School / adult events) — returning None so those handlers/engine own the
    turn — then scores every topic by trigger-substring matches and returns the
    highest-scoring topic key (ties break by YAML order = priority). Returns
    None when nothing matches.
  * `answer_for_topic(topic, facts=None)` returns that topic's block. Only
    `general_overview` substitutes canonical {price}/{duration}/{age_min}/
    {age_max} from `admin_config_service.get_camp_facts()` — never hard-coded.

NO LLM is used anywhere here. The classifier deliberately does NOT choose from
one huge blob; it picks among small, independent topic blocks.

Fail-closed: any load/parse error → `detect_camp_topic` returns None (the LLM
engine then answers as before), never raises into the hot path.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Mapping

logger = logging.getLogger(__name__)

# Priority order (highest first). Used only for tie-breaks and as the canonical
# topic set; the per-topic triggers/answers come from the YAML. sports_health is
# intentionally BEFORE activities_creativity so „სპორტული აქტივობები" → sports.
TOPIC_PRIORITY: tuple[str, ...] = (
    "safety",
    "parent_communication",
    "food",
    "gadgets",
    "bullying_empathy",
    "emotional_intelligence",
    "thinking_expression",
    "confidence_motivation",
    "communication_socialization",
    "independence_responsibility",
    "interests_orientation",
    "values_identity",
    "sports_health",
    "activities_creativity",
    "rest_environment",
    "accommodation",
    "general_overview",
)

# ── Canonical-flow EXCLUSIONS ────────────────────────────────────────────────
# A message matching ANY of these belongs to an existing canonical handler / the
# LLM engine, NEVER to a camp topic block. Kept as data here so detect_camp_topic
# is self-contained and unit-testable without importing parent_flow.

# CAMP price question → canonical price handler / engine (must include 2150₾).
_PRICE_MARKERS: tuple[str, ...] = ("ფასი", "ღირს", "ღირებულებ", "გადასახად")
# CAMP dates question → canonical dates handler / engine.
_DATE_MARKERS: tuple[str, ...] = (
    "როდის", "თარიღ", "რიცხვშ", "რომელ რიცხვ", "ნაკად", "დაიწყებ", "ჩატარდებ",
)
# CAMP registration / link / form → canonical registration-link handler.
# NB: NEVER use bare „ფორმა" (it is a substring of „ინფორმაცია").
_REGISTRATION_MARKERS: tuple[str, ...] = (
    "რეგისტრაც", "დარეგისტრ", "დავრეგისტრ", "რეგისტირ", "ლინკ", "ბმულ",
)
# Sunday School → its own coming_soon flow.
_SUNDAY_SCHOOL_MARKERS: tuple[str, ...] = ("საკვირაო",)
# Adult / cultural events → adult flow. „ღონისძიებ" only excludes when NO camp
# keyword is present (so „ბანაკში რა ღონისძიებებია" is not stolen here).
_ADULT_MARKERS: tuple[str, ...] = ("ზრდასრულ", "კულტურულ", "კონცერ", "ბილეთ")
_CAMP_KEYWORDS: tuple[str, ...] = ("ბანაკ", "საზაფხულო", "ლაგერ")

_KNOWLEDGE_NAME = "camp_topic_facts"


def _is_excluded(low: str) -> bool:
    """True when the message belongs to a canonical flow (price / dates /
    registration / Sunday School / adult) and must NOT be answered with a camp
    topic block."""
    if any(m in low for m in _PRICE_MARKERS):
        return True
    if any(m in low for m in _DATE_MARKERS):
        return True
    if any(m in low for m in _REGISTRATION_MARKERS):
        return True
    if any(m in low for m in _SUNDAY_SCHOOL_MARKERS):
        return True
    if any(m in low for m in _ADULT_MARKERS):
        return True
    # „ღონისძიებ" without a camp keyword → adult-event discovery.
    if "ღონისძიებ" in low and not any(k in low for k in _CAMP_KEYWORDS):
        return True
    return False


def _load_data() -> dict[str, Any]:
    """Return the full parsed YAML mapping, or {} on any error (fail-closed)."""
    try:
        from app.agent.services.knowledge_loader import load_knowledge

        data = load_knowledge(_KNOWLEDGE_NAME)
        if isinstance(data, Mapping):
            return dict(data)
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning("[camp_topic_facts] knowledge load failed (%s)", exc)
    return {}


def _load_topics() -> dict[str, dict[str, Any]]:
    """Return {topic: {triggers, context_triggers, answer}} from the YAML."""
    topics = _load_data().get("camp_topic_facts")
    if isinstance(topics, Mapping):
        return {str(k): dict(v) for k, v in topics.items() if isinstance(v, Mapping)}
    return {}


def _has_camp_keyword(low: str) -> bool:
    return any(k in low for k in _CAMP_KEYWORDS)


def _count(low: str, markers: Any) -> int:
    if not isinstance(markers, (list, tuple)):
        return 0
    return sum(1 for m in markers if m and str(m).lower() in low)


def _score(low: str, entry: Mapping[str, Any], camp_ctx: bool) -> int:
    """Plain `triggers` always count; `context_triggers` count ONLY when the
    message also names the camp (so a generic phrase is not over-matched)."""
    score = _count(low, entry.get("triggers"))
    if camp_ctx:
        score += _count(low, entry.get("context_triggers"))
    return score


def detect_camp_topic(message: str) -> str | None:
    """Return the single best-matching camp topic key for the message, or None.

    None is returned when (a) the message belongs to a canonical flow
    (price/dates/registration/Sunday School/adult) or (b) no topic trigger
    matches. Highest trigger-match count wins; ties break by `TOPIC_PRIORITY`.
    """
    low = (message or "").lower().strip()
    if not low:
        return None
    if _is_excluded(low):
        return None

    topics = _load_topics()
    if not topics:
        return None

    camp_ctx = _has_camp_keyword(low)
    best_topic: str | None = None
    best_score = 0
    for topic in TOPIC_PRIORITY:
        entry = topics.get(topic)
        if not entry:
            continue
        s = _score(low, entry, camp_ctx)
        # Strictly-greater so the EARLIER (higher-priority) topic wins ties.
        if s > best_score:
            best_score = s
            best_topic = topic
    return best_topic if best_score > 0 else None


def _is_exact_menu_question(low: str) -> bool:
    """True for an EXACT/detailed-menu question („ზუსტად რა მენიუ ექნებათ?",
    „მენიუ როგორი იქნება?") — food inclusion is known, the exact menu is not."""
    if _count(low, _load_data().get("camp_menu_detail_markers")) > 0:
        return True
    return "მენიუ" in low and any(x in low for x in ("ზუსტ", "კონკრეტ"))


# ── Doctor / medical / medication ────────────────────────────────────────────
def _is_medical(low: str) -> bool:
    cfg = _load_data().get("camp_medical")
    if not isinstance(cfg, Mapping):
        return False
    return _count(low, cfg.get("triggers")) > 0


def medical_answer() -> str | None:
    cfg = _load_data().get("camp_medical")
    if isinstance(cfg, Mapping):
        ans = str(cfg.get("answer") or "").strip()
        if ans:
            return ans
    return None


# ── Parent → child CONTACT during camp (vs the child's own social skills) ─────
# „მე როგორ დავუკავშირდები ბავშვს?", „ბავშვთან კონტაქტი როგორ მექნება?",
# „დღის განმავლობაში ბავშვთან კომუნიკაციას შევძლებ?" → the PARENT communication /
# daily-updates block. A child word PLUS a parent-reaches-child intent, and NOT a
# skill-DEFICIT word — so „კომუნიკაცია უჭირს" / „სოციალიზაცია სჭირდება" still go
# to communication_socialization (they carry no child word + a deficit cue).
_CHILD_WORDS: tuple[str, ...] = ("ბავშვ", "ბავსშვ", "ბავშვტ", "შვილ")  # incl. typos
_PARENT_CONTACT_INTENT: tuple[str, ...] = (
    "კავშირ",        # კავშირი / დაკავშირება / დავუკავშირდები / დაგიკავშირდები
    "კონტაქტ", "კონატაქტ",  # contact (+ typo)
    "ურეკ", "დარეკ", "რეკვ",  # call
    "ლაპარაკ",       # talk
    "ნახვა",         # see
    "ამბავ", "ამბებ",  # news about the child
    "კომუნიკაცი",    # communication WITH the child
)
# A skill-deficit cue means the question is about the CHILD's development, not
# parent→child contact → keep it with communication_socialization.
_CONTACT_DEFICIT_GUARD: tuple[str, ...] = (
    "უჭირ", "სჭირდება", "ჩაკეტ", "სოციალიზ", "მეგობრ", "თანატოლ", "გახსნ",
)


def _is_parent_child_contact(low: str) -> bool:
    if not any(c in low for c in _CHILD_WORDS):
        return False
    if not any(v in low for v in _PARENT_CONTACT_INTENT):
        return False
    if any(d in low for d in _CONTACT_DEFICIT_GUARD):
        return False
    return True


# ── Unknown operational detail → TOPIC-SPECIFIC honest defer (client fix
#    2026-06-29). Names the exact topic, then the EXACT approved ending — never
#    invents, never adds an emoji, „გაგაცნობთ" verbatim, manager phone always. ──
def _unknown_ending() -> str:
    fallback = str(_load_data().get("camp_unknown_ending") or "").strip()
    try:
        from app.services import admin_config_service, approved_copy_service

        phone = (admin_config_service.get_manager_phone() or "").strip()
        if not phone:
            return fallback
        rendered = approved_copy_service.get_approved_copy(
            "camp",
            "manager.unknown_detail_ending",
            manager_phone=phone,
        )
        return rendered or fallback
    except Exception:  # pragma: no cover - defensive fallback keeps current copy
        return fallback


def _fallback_for(topic_phrase: str) -> str:
    """„რაც შეეხება <topic>, ამ დეტალებს მენეჯერი გაგაცნობთ : 558 67 47 33"."""
    return f"რაც შეეხება {topic_phrase}, {_unknown_ending()}"


# Seats / availability — a places question („ადგილები გაქვთ?"), NOT a camp
# LOCATION question („რომელ ადგილას ტარდება?").
_SEATS_AVAIL_CUES: tuple[str, ...] = (
    "გაქვთ", "არის", "იქნებ", "დარჩ", "რჩება", "თავისუფ", "მოვასწ", "დაგვრჩ",
    "მექნებ", "შევძლებ",
)
_SEATS_LOCATION_GUARD: tuple[str, ...] = (
    "რომელ ადგილას", "მდებარე", "ლოკაცი", "მისამართ", "სად ტარდებ", "სად არის ბანაკ",
)
# 2+ children / discount cue for the known+unknown split (own copy — this
# reasoning module must not import parent_flow).
_DISCOUNT_TRIGGERS: tuple[str, ...] = (
    "ორი ბავშვ", "ორ ბავშვ", "ორი შვილ", "ორივე შვილ", "ჩემი შვილები",
    "სამი ბავშვ", "სამ ბავშვ", "და-ძმა", "და ძმა ერთად", "დედმამიშ", "ფასდაკლებ",
)
_AGE_RE = re.compile(r"(\d{1,2})\s*წლ")
_STREAM_NO_RE = re.compile(r"მე-?\s*(\d+)\s*ნაკად")
_STREAM_DATE_RE = re.compile(r"(\d{1,2})\s*[-–]\s*(\d{1,2})\s*(ივნის|ივლის|აგვისტ)")
_MONTH_DATIVE = {"ივნის": "ივნისს", "ივლის": "ივლისს", "აგვისტ": "აგვისტოს"}


def _is_seats_question(low: str) -> bool:
    if "ადგილ" not in low:
        return False
    if any(g in low for g in _SEATS_LOCATION_GUARD):
        return False
    return any(c in low for c in _SEATS_AVAIL_CUES)


def _extract_eligible_age(low: str) -> int | None:
    m = _AGE_RE.search(low)
    if not m:
        return None
    try:
        age = int(m.group(1))
    except ValueError:
        return None
    facts = _canonical_overview_facts()
    try:
        lo, hi = int(facts["age_min"]), int(facts["age_max"])
    except (ValueError, KeyError):
        lo, hi = 9, 17
    return age if lo <= age <= hi else None


def _stream_confirm_line(low: str) -> str:
    """„მე-2 ნაკადი ტარდება 5–11 ივლისს." — only when the message NAMES both the
    stream number AND an explicit date range (best-effort; else "")."""
    mn = _STREAM_NO_RE.search(low)
    md = _STREAM_DATE_RE.search(low)
    if not (mn and md):
        return ""
    dative = _MONTH_DATIVE.get(md.group(3), md.group(3))
    return f"მე-{mn.group(1)} ნაკადი ტარდება {md.group(1)}–{md.group(2)} {dative}."


def _known_prefix_for_seats(low: str) -> str:
    """The known part of a known+unknown split, if present. Priority: explicit
    eligible age → sibling-discount cue → named stream+date. Else ""."""
    age = _extract_eligible_age(low)
    if age is not None:
        facts = _canonical_overview_facts()
        line = str(_load_data().get("camp_age_eligible_line") or "")
        return (line.replace("{age}", str(age))
                    .replace("{age_min}", facts["age_min"])
                    .replace("{age_max}", facts["age_max"])).strip()
    if any(t in low for t in _DISCOUNT_TRIGGERS):
        return str(_load_data().get("camp_sibling_discount_line") or "").strip()
    return _stream_confirm_line(low)


def _seats_answer(low: str) -> str:
    topic = str(_load_data().get("camp_seats_topic") or "").strip()
    fb = _fallback_for(topic)
    prefix = _known_prefix_for_seats(low)
    return f"{prefix}\n\n{fb}" if prefix else fb


def _unknown_categories() -> list[dict[str, Any]]:
    cats = _load_data().get("camp_unknown_categories")
    if isinstance(cats, (list, tuple)):
        return [dict(c) for c in cats if isinstance(c, Mapping)]
    return []


def _match_unknown_category(low: str) -> str | None:
    """First topic-specific category whose noun (+ optional cue) matches."""
    for cat in _unknown_categories():
        if _count(low, cat.get("noun_markers")) == 0:
            continue
        cues = cat.get("cue_markers")
        if cues and _count(low, cues) == 0:
            continue
        topic = str(cat.get("topic") or "").strip()
        if topic:
            return _fallback_for(topic)
    return None


def _match_org(low: str) -> str | None:
    """Organization / team / „who is behind you" → a brief AI-assistant line then
    the organizer/founder details deferred to the manager. Never the camp funnel
    (no camp intro, no child-age question)."""
    if _count(low, _load_data().get("camp_org_markers")) == 0:
        return None
    topic = str(_load_data().get("camp_org_topic") or "").strip()
    if not topic:
        return None
    fb = _fallback_for(topic)
    prefix = str(_load_data().get("camp_org_prefix") or "").strip()
    return f"{prefix}\n\n{fb}" if prefix else fb


def _match_generic_unknown(low: str) -> str | None:
    """LAST-RESORT anti-invention defer for an unsupported operational detail
    whose exact topic can NOT be normalized → „რაც შეეხება ამ საკითხს, …"."""
    if _count(low, _load_data().get("camp_generic_markers")) == 0:
        return None
    topic = str(_load_data().get("camp_generic_topic") or "").strip()
    return _fallback_for(topic) if topic else None


def _resolve_operational(low: str) -> str | None:
    """Seats/availability (with optional known prefix) + organization defer +
    topic-specific unknown operational details + the generic last-resort defer.
    Runs BEFORE the dates/price exclusion so a „ნაკადზე ადგილები" seats question
    is not swallowed as a dates question. Returns None for anything that is NOT
    an unsupported operational detail (known topics answer later)."""
    if _is_seats_question(low):
        return _seats_answer(low)
    org = _match_org(low)
    if org is not None:
        return org
    cat = _match_unknown_category(low)
    if cat is not None:
        return cat
    return _match_generic_unknown(low)


def resolve_operational(message: str) -> str | None:
    """Public entry for the EARLY parent_flow interceptor (client fix 2026-06-29).

    Returns the honest anti-invention defer for an unsupported OPERATIONAL detail
    (seats/availability, room distribution, towels, hotel, transport, day
    schedule, direct-call rules, organizer/founder, or a generic un-normalizable
    detail) — or None for everything else (greetings, discovery, known camp
    topics, canonical price/dates/registration/Sunday-School/adult flows). It is
    deliberately narrow so it can run BEFORE the static welcome / camp intro /
    age question without changing first-turn behaviour for anything else."""
    low = (message or "").lower().strip()
    if not low:
        return None
    return _resolve_operational(low)


def menu_clarification() -> str:
    return str(_load_data().get("camp_menu_clarification") or "").strip()


def direct_call_fallback() -> str:
    """The direct-call manager defer („რაც შეეხება ბავშვთან პირდაპირი კონტაქტის
    წესებს, …") built from the YAML `direct_call` category — public so the
    parent_flow multi-question combiner can reuse the exact approved wording for a
    bare call clause („დარეკვა როგორ იქნება") a cue-gated category would miss."""
    for cat in _unknown_categories():
        if str(cat.get("key") or "") == "direct_call":
            topic = str(cat.get("topic") or "").strip()
            if topic:
                return _fallback_for(topic)
    return _fallback_for("ბავშვთან პირდაპირი კონტაქტის წესებს")


# ── EXACT-DETAIL split: KNOWN general answer + exact-unknown defer ───────────
# (client follow-up 2026-06-30). Returns (general_part, fallback_part). The
# general part uses only the FIRST approved paragraph/line — never invents the
# exact detail. parent_flow renders „general\n\nfallback"; on an immediate
# repeat it drops the general part and returns the fallback only.
_ANY_AGE_RE = re.compile(r"(\d{1,2})\s*წლ")


def _food_general() -> str:
    """First approved paragraph of the food block (no allergy note)."""
    block = answer_for_topic("food") or ""
    return block.split("\n\n", 1)[0].strip()


def _eligibility_line(age: int) -> str:
    facts = _canonical_overview_facts()
    line = str(_load_data().get("camp_age_eligible_line") or "")
    return (line.replace("{age}", str(age))
                .replace("{age_min}", facts["age_min"])
                .replace("{age_max}", facts["age_max"])).strip()


def _extract_any_age(low: str) -> int | None:
    m = _ANY_AGE_RE.search(low)
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None


def resolve_exact_detail(message: str) -> tuple[str, str] | None:
    """Return (general_part, fallback_part) for a KNOWN-general + exact-unknown
    detail question, or None. general_part is '' when only the defer applies.
    Order (most specific first): age-group count → peer presence → staff count →
    food frequency → exact/detailed menu. NEVER invents the exact detail."""
    low = (message or "").lower().strip()
    if not low:
        return None
    data = _load_data()

    # 1. Age-group COUNT („რამდენი ბავშვი იქნება 14 წლის?") → defer only.
    if any(c in low for c in _CHILD_WORDS) and any(c in low for c in ("რამდენი", "რაოდენობ")):
        age = _extract_any_age(low)
        if age is not None:
            tmpl = str(data.get("camp_age_group_count_topic_template") or "")
            topic = tmpl.replace("{age}", str(age)).strip()
            if topic:
                return ("", _fallback_for(topic))

    # 2. Peer / same-age presence → eligibility (if age given) + peer defer.
    if _count(low, data.get("camp_peer_markers")) > 0:
        topic = str(data.get("camp_peer_topic") or "").strip()
        if topic:
            age = _extract_eligible_age(low)
            general = _eligibility_line(age) if age is not None else ""
            return (general, _fallback_for(topic))

    # 3. Staff COUNT → staff line + staff-count defer.
    if (_count(low, data.get("camp_staff_count_nouns")) > 0
            and _count(low, data.get("camp_staff_count_cues")) > 0):
        topic = str(data.get("camp_staff_count_topic") or "").strip()
        if topic:
            return (str(data.get("camp_staff_line") or "").strip(), _fallback_for(topic))

    # 4. Food FREQUENCY → food general + frequency defer.
    if (_count(low, data.get("camp_food_frequency_markers")) > 0
            and _count(low, data.get("camp_food_context_markers")) > 0):
        topic = str(data.get("camp_food_frequency_topic") or "").strip()
        if topic:
            return (_food_general(), _fallback_for(topic))

    # 5. Exact / detailed MENU → food general + menu defer.
    if _count(low, data.get("camp_menu_detail_markers")) > 0:
        topic = str(data.get("camp_menu_topic") or "").strip()
        if topic:
            return (_food_general(), _fallback_for(topic))

    return None


def political_reply(message: str) -> str | None:
    """Neutral redirect for a political / party-identity bait, or None."""
    low = (message or "").lower()
    if _count(low, _load_data().get("camp_political_markers")) == 0:
        return None
    return str(_load_data().get("camp_political_reply") or "").strip() or None


def unclear_phrase_reply(message: str) -> str | None:
    """Polished clarification for a recognised unclear phrase („ხელა ბავშ"), or
    None. Fills the approved template with the client's canonical phrase."""
    low = (message or "").lower()
    if _count(low, _load_data().get("camp_unclear_phrases")) == 0:
        return None
    tmpl = str(_load_data().get("camp_unclear_reply_template") or "").strip()
    phrase = str(_load_data().get("camp_unclear_default_phrase") or "").strip()
    if not tmpl:
        return None
    return tmpl.replace("{phrase}", phrase)


def resolve_camp_answer(message: str) -> str | None:
    """Top-level resolver used by the parent_flow interceptor.

    Order: canonical-flow exclusion → known topic block (with the exact-menu
    clarification appended to FOOD when asked) → honest unknown-operational-detail
    defer → None (the LLM engine answers). Returns exactly ONE focused block — it
    never dumps and never invents an unknown detail.
    """
    low = (message or "").lower().strip()
    if not low:
        return None

    # 0a. Doctor / medical / medication → safe medical block FIRST, so a
    #     „წამლის გრაფიკი" (medication schedule) is medical, never mistaken for
    #     the day-schedule operational fallback below.
    if _is_medical(low):
        med = medical_answer()
        if med:
            return med

    # 0b. Operational unknown-detail + seats / known+unknown split (client fix
    #     2026-06-29). Runs BEFORE the canonical-flow exclusion so a
    #     „ნაკადზე ადგილები" seats question is answered with the honest topic
    #     fallback instead of being swallowed as a dates question. NEVER invents.
    op = _resolve_operational(low)
    if op is not None:
        return op

    if _is_excluded(low):
        return None

    # Pre-checks (before generic topic scoring):
    # 2. Parent→child CONTACT during camp → the parent-communication block
    #    (beats consultation phone/video flow AND communication_socialization).
    if _is_parent_child_contact(low):
        pc = answer_for_topic("parent_communication")
        if pc:
            return pc

    topic = detect_camp_topic(message)
    if topic:
        answer = answer_for_topic(topic)
        if not answer:
            return None
        if topic == "food" and _is_exact_menu_question(low):
            clar = menu_clarification()
            if clar and clar not in answer:
                answer = f"{answer}\n\n{clar}"
        return answer

    return None


def _canonical_overview_facts() -> dict[str, str]:
    """Canonical {price, duration, age_min, age_max} from get_camp_facts(), with
    safe camp_2026 defaults — never hard-coded into the YAML text."""
    price = duration = age_min = age_max = ""
    try:
        from app.services import admin_config_service

        facts = admin_config_service.get_camp_facts() or {}
        price = str(facts.get("price_gel") or facts.get("price_text") or "").strip()
        duration = str(facts.get("duration_days") or "").strip()
        age_min = str(facts.get("age_min") or "").strip()
        age_max = str(facts.get("age_max") or "").strip()
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning("[camp_topic_facts] get_camp_facts failed (%s)", exc)
    return {
        "price": price or "2150",
        "duration": duration or "7",
        "age_min": age_min or "9",
        "age_max": age_max or "17",
    }


def answer_for_topic(topic: str, facts: Mapping[str, Any] | None = None) -> str | None:
    """Return the focused Georgian answer block for `topic`, or None if unknown.

    For `general_overview` the {price}/{duration}/{age_min}/{age_max} tokens are
    filled from the canonical camp facts (admin-first). `facts` may be supplied
    (tests) to override the canonical source.
    """
    topics = _load_topics()
    entry = topics.get(topic)
    if not entry:
        return None
    answer = str(entry.get("answer") or "").strip()
    if not answer:
        return None
    if "{" in answer:
        values = dict(_canonical_overview_facts())
        if facts:
            for k in ("price", "duration", "age_min", "age_max"):
                if facts.get(k) not in (None, ""):
                    values[k] = str(facts.get(k)).strip()
        for token, value in values.items():
            answer = answer.replace("{" + token + "}", value)
    return answer
