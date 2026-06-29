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
    """True for an EXACT-menu question („ზუსტად რა მენიუ ექნებათ?") — food
    inclusion is known, the exact menu is not."""
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


def _is_unknown_camp_detail(low: str) -> bool:
    """True for a camp question that asks about a specific OPERATIONAL detail we
    have no approved fact for — an operational noun PLUS an interrogative /
    arrangement cue. The noun+cue pairing keeps a parent DESCRIBING the child
    („ერთ ოთახში გამოიკეტება") from being read as a camp-rooms question."""
    cfg = _load_data().get("camp_unknown_detail")
    if not isinstance(cfg, Mapping):
        return False
    if _count(low, cfg.get("noun_markers")) == 0:
        return False
    return _count(low, cfg.get("cue_markers")) > 0


def unknown_detail_answer() -> str | None:
    cfg = _load_data().get("camp_unknown_detail")
    if isinstance(cfg, Mapping):
        ans = str(cfg.get("answer") or "").strip()
        if ans:
            return ans
    return None


def menu_clarification() -> str:
    return str(_load_data().get("camp_menu_clarification") or "").strip()


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
    if _is_excluded(low):
        return None

    # Pre-checks (before generic topic scoring):
    # 1. Doctor / medical / medication → safe medical block (never overpromise).
    if _is_medical(low):
        med = medical_answer()
        if med:
            return med
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

    if _is_unknown_camp_detail(low):
        return unknown_detail_answer()
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
