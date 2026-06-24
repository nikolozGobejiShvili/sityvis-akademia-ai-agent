"""Deterministic PARENT-turn intent detector.

A pure-Python, no-LLM, no-state classifier that scans the user's message
for Georgian intent stems and returns the *highest-priority* interrupt
intent. Returns ``None`` when the message looks like a normal flow answer
(no interrupt) — in that case the caller should fall through to the
existing state machine, optionally consulting the LLM analyzer first.

Why deterministic-first:

  * Always available. Works even when ``USE_LLM_TURN_ANALYZER=false``,
    when OpenAI is unreachable, or when the user is on a network where
    every saved millisecond matters.
  * Predictable. Keyword stems are auditable; an LLM classifier is not.
  * Cheap. No tokens, no latency.

When the LLM analyzer **is** enabled, this detector still runs first.
If it produces an answer, we use it directly; if not, we ask the LLM.
That gives us the best of both worlds: deterministic for the easy cases,
LLM for the genuinely ambiguous ones.

Stems are matched as substrings on a lower-cased message — Georgian
morphology means "მენეჯერი / მენეჯერთან / მენეჯერის" all share the stem
"მენეჯერ", and so on.

The detector exposes one public function::

    detect_parent_interrupt_intent(message: str) -> dict | None

Returned dict shape (when an interrupt is detected):

    {
      "intent": "booking_request | manager_request | identity_question
                 | price_question | dates_question | location_question
                 | conditions_question | registration_question
                 | out_of_scope",
      "confidence": float in [0,1],
      "entities": {
        "date_text": str,
        "time_text": str,
        "phone": str,
        "name": str,
      },
      "source": "deterministic"
    }

Returning ``None`` means "no interrupt detected — let the state machine
(or the LLM analyzer) handle this turn normally". This is NOT the same
as the analyzer's low-confidence case; uncertainty is the LLM's job to
flag, not the keyword matcher's.
"""

from __future__ import annotations

import re
from typing import Any

# -- intent labels (closed set — used by the router) -----------------------

INTENT_BOOKING_REQUEST = "booking_request"
INTENT_MANAGER_REQUEST = "manager_request"
INTENT_IDENTITY_QUESTION = "identity_question"
INTENT_PRICE_QUESTION = "price_question"
INTENT_DATES_QUESTION = "dates_question"
INTENT_LOCATION_QUESTION = "location_question"
INTENT_CONDITIONS_QUESTION = "conditions_question"
INTENT_REGISTRATION_QUESTION = "registration_question"
# P2 — "no concern, I just want camp for my child" path. Caught so the
# router can produce a positive, problem-free response instead of
# letting the scripted ASK_CHALLENGE → ASK_DEEPER chain assume a problem.
INTENT_NO_CONCERN = "no_concern_simple"
INTENT_OUT_OF_SCOPE = "out_of_scope"

# Priority order. The detector returns the **first** matched intent in
# this order and stops. Spec PART 3: when one message matches multiple
# intents, only the highest-priority intent is handled.
INTENT_PRIORITY: tuple[str, ...] = (
    INTENT_BOOKING_REQUEST,
    INTENT_MANAGER_REQUEST,
    INTENT_IDENTITY_QUESTION,
    INTENT_PRICE_QUESTION,
    INTENT_DATES_QUESTION,
    INTENT_LOCATION_QUESTION,
    INTENT_CONDITIONS_QUESTION,
    INTENT_REGISTRATION_QUESTION,
    INTENT_NO_CONCERN,
    INTENT_OUT_OF_SCOPE,
)


# -- stem inventories ------------------------------------------------------
#
# Each set captures the morphological *root* of a Georgian keyword that
# strongly signals one intent. The matcher uses plain substring
# containment, so e.g. "ჩამწერ" catches "ჩამწერე", "ჩამწერო", "ჩამწერეთ".


# booking / consultation request
# "კონსულტაცი" alone is enough — in this product, consultation IS the
# booking endpoint. Verb forms ("ჩაწერა", "ჩამწერე", "დავჯავშნ") count too.
_BOOKING_STEMS: tuple[str, ...] = (
    "კონსულტაცი",        # კონსულტაცია / კონსულტაციაზე / კონსულტაცი მინდა
    "ჩაწერ",             # ჩაწერა, ჩაწერო — "ჩაწერა მინდა"
    "ჩამწერ",            # ჩამწერე, ჩამწერეთ
    "ჩამიწერ",           # ჩამიწერე
    "ჩავიწერ",           # ჩავიწერო
    "დაჯავშნ",           # დაჯავშნა
    "დავჯავშნ",          # დავჯავშნე
    "ვჯავშნ",            # ვჯავშნი
    "ვწერი ბანაკზე",
)


# manager / human / contact handoff request
# "მენეჯერ" stem catches every form. Soft requests ("ვინმე დამეხმარება?",
# "ადამიანი მინდა") and explicit phone asks ("ნომერი მომწერეთ",
# "საკონტაქტო მომეცით") are all classified together — the router decides
# whether to give phone immediately or ask for the user's phone, based
# on whether ``lead.phone`` is already populated.
_MANAGER_STEMS: tuple[str, ...] = (
    "მენეჯერ",                # მენეჯერი / მენეჯერთან / მენეჯერის
    "მენიჯერ",                # common typo
    "ადამიანს მინდა",         # human request
    "ადამიანი მინდა",
    "ადამიანი დამეხმარ",
    "ვინმე დამეხმარ",         # "ვინმე დამეხმარება?"
    "ვინმე დამიკავშირდ",
    "დამირეკოს",              # "დამირეკოს ვინმემ"
    "კონტაქტი მო",            # "კონტაქტი მომეცით / მომწერეთ"
    "კონტაქტი მი",            # "კონტაქტი მინდა"
    "საკონტაქტო",             # almost always a contact-info request
    "ნომერი მო",              # "ნომერი მომწერეთ / მომეცით"
    "ნომერი მი",              # "ნომერი მინდა"
    "ნომერი მინდა",
    "დამიკავშირდე",           # "მენეჯერი დამიკავშირდეს" / "დამიკავშირდეთ"
    "დაგვიკავშირდე",
)


# identity question — who/what is the bot
# Must be specific enough not to catch "ვინ წარვადგინო" or "ვინ მოვა
# კონსულტაციაზე" (those mean different things).
_IDENTITY_STEMS: tuple[str, ...] = (
    "შენ ვინ ხარ",
    "ვინ ხართ",
    "ვინ ხარ",                # "ვინ ხარ?" without "შენ"
    "რა ხართ",
    "რა ხარ",                 # "რა ხარ?"
    "ბოტი ხარ",
    "ბოტი ხართ",
    "ხარ ბოტი",
    "ხართ ბოტი",
    "ბოტთან ვსაუბრობ",
    "სიტყვის აკადემიის ვინ",
    "ვინ ლაპარაკობს",
    "შენ ვისი",
)


# price / payment
_PRICE_STEMS: tuple[str, ...] = (
    "ფასი",
    "ღირს",
    "ღირებულება",
    "ღირებულებას",
    "გადახდა",
    "გადახდი",                # "გადახდის პირობები"
    "თანხა",
    "საფასური",
    "გადასახდელი",
    "ფასდაკლება",
    "გადანაწილება",
    "რამდენი ღირს",
    "რა ღირს",
    "რა ფასი",
)


# dates / when
_DATES_STEMS: tuple[str, ...] = (
    "თარიღი",
    "თარიღები",
    "თარიღს",
    "ნაკადი",
    "ნაკადებ",                # ნაკადები / ნაკადებზე
    "როდის",                  # "როდის არის?"
    "რომელ თვე",
    "რომელ რიცხვ",
    "რა დღე",
    "რა თარიღ",
)


# location / where
_LOCATION_STEMS: tuple[str, ...] = (
    "სად ტარდება",
    "სად ჩატარდება",
    "სად არის",
    "სად მდებარეობ",
    "ლოკაცი",                 # ლოკაცია / ლოკაციაზე
    "მისამართ",               # მისამართი
    "ქალაქი",                 # ხელშეუხებელია — could be ambiguous; OK
    "ადგილმდებარეობა",
)


# conditions / what's included
_CONDITIONS_STEMS: tuple[str, ...] = (
    "პირობებ",                # პირობები / პირობებზე
    "რა შედის",
    "შედის ფასში",
    "მოიცავს",
    "მოიცავ",
    "ტრანსპორტ",              # ტრანსპორტი / ტრანსპორტში
    "კვება",                  # კვება / კვებაზე
    "განთავსებ",
    "რა აქტივობ",
    "რა აქტი",
    "აქტივობებ",
    "რა ხდება ბანაკში",
    "რას სწავლობ",
)


# registration / link
_REGISTRATION_STEMS: tuple[str, ...] = (
    "რეგისტრაცი",             # რეგისტრაცია / რეგისტრაციის
    "ლინკი",
    "ბმული",
    "ფორმა",                  # "რეგისტრაციის ფორმა"
    "გადავიდე",               # "გადასასვლელი ლინკი"
    "სად ვწერო",
    "სად მოვაწერო",
)


# no-concern / "just want camp" patterns. P2 PART 5. These are
# multi-word patterns to avoid false positives from bare "არაფერი" (which
# can mean "nothing" in many unrelated contexts).
_NO_CONCERN_STEMS: tuple[str, ...] = (
    "უბრალოდ ბანაკი",
    "უბრალოდ გაშვება",
    "უბრალოდ მინდა ბავშვმა",
    "უბრალოდ მინდა შვილმა",
    "უბრალოდ მინდა გაატაროს",
    "სამეგობრო წრე",
    "ახალი მეგობრები",
    "ზაფხული საინტერესოდ",
    "საინტერესოდ გაატაროს",
    "ბავშვმა დაისვენოს",
    "შვილმა დაისვენოს",
    "არაფერი არ აწუხებს",
    "არაფერი არ უჭირს",
    "არაფერი არ აქვს",
    "არაფერი უბრალოდ",
    "პრობლემა არ აქვს",
    "არანაირი პრობლემა",
)


# -- detector --------------------------------------------------------------


_INTENT_STEMS: tuple[tuple[str, tuple[str, ...], float], ...] = (
    # (intent, stems, default confidence). The order here MUST match
    # INTENT_PRIORITY — the detector walks this tuple top-to-bottom.
    (INTENT_BOOKING_REQUEST,       _BOOKING_STEMS,       0.95),
    (INTENT_MANAGER_REQUEST,       _MANAGER_STEMS,       0.95),
    (INTENT_IDENTITY_QUESTION,     _IDENTITY_STEMS,      0.95),
    (INTENT_PRICE_QUESTION,        _PRICE_STEMS,         0.92),
    (INTENT_DATES_QUESTION,        _DATES_STEMS,         0.92),
    (INTENT_LOCATION_QUESTION,     _LOCATION_STEMS,      0.92),
    (INTENT_CONDITIONS_QUESTION,   _CONDITIONS_STEMS,    0.90),
    (INTENT_REGISTRATION_QUESTION, _REGISTRATION_STEMS,  0.92),
    (INTENT_NO_CONCERN,            _NO_CONCERN_STEMS,    0.88),
)


def _has_any_stem(text: str, stems: tuple[str, ...]) -> bool:
    return any(stem in text for stem in stems)


# -- light entity extraction (date_text / time_text / phone / name) -------
#
# These are best-effort hints for the router — never authoritative. The
# phone extracted here is NEVER used as ``lead.phone`` directly; it is
# meant to flag "user mentioned a phone-shaped string" for downstream
# processing. The canonical phone parser is parent_flow._parse_name_phone,
# and it always runs on the actual message text.


_TIME_HM_PATTERN = re.compile(r"\b(\d{1,2}):(\d{2})\b")
_TIME_HOUR_PATTERN = re.compile(r"\b(\d{1,2})\s*(?:საათ|სთ-ზე|სთ)\b")
_PHONE_DIGITS_PATTERN = re.compile(r"\+?995?[\s\-]?\d[\d\s\-\(\)]{7,}")
_GEORGIAN_DAY_MONTH_PATTERN = re.compile(r"\b(\d{1,2})\s+([ა-ჰ]+ს?)\b")
_RELATIVE_DAY_TOKENS = ("ხვალ", "ზეგ", "დღეს", "შაბათ", "კვირას")
# Child age — "8 წლის", "12 წლის არის". Only matched when followed by "წლის"
# (genitive of "year") so we don't grab unrelated numbers.
_AGE_PATTERN = re.compile(r"\b(\d{1,2})\s+წლის")


def _extract_entities(message: str) -> dict[str, str]:
    """Return a best-effort entity bag — purely advisory.

    Nothing here is treated as authoritative downstream:
      * ``date_text`` and ``time_text`` are passed back to the router so
        it can decide whether the user *named* a slot at all; the actual
        parsing for booking is done by `parent_flow._parse_custom_datetime`
        or the new router-level parser.
      * ``phone`` flags "user typed a phone-shaped string"; the canonical
        validator is `parent_flow._parse_name_phone`.
      * ``child_age`` is captured when the user wrote "N წლის" anywhere
        in a multi-intent message ("8 წლის არის, ფასი მაინტერესებს"),
        so we don't lose the age when the message is also a fact-question.
      * ``name`` is NOT extracted here — a generic name parser would
        produce too many false positives in Georgian sentences. The
        existing ASK_NAME state owns name capture.
    """
    text = message or ""
    lowered = text.lower()
    entities: dict[str, str] = {
        "date_text": "",
        "time_text": "",
        "phone": "",
        "name": "",
        "child_age": "",
    }

    # time
    hm = _TIME_HM_PATTERN.search(text)
    if hm:
        entities["time_text"] = hm.group(0)
    else:
        hour = _TIME_HOUR_PATTERN.search(lowered)
        if hour:
            entities["time_text"] = hour.group(0)

    # date — Georgian "22 მაისს" or "ხვალ" etc.
    date_match = _GEORGIAN_DAY_MONTH_PATTERN.search(lowered)
    if date_match:
        entities["date_text"] = date_match.group(0)
    else:
        for token in _RELATIVE_DAY_TOKENS:
            if token in lowered:
                entities["date_text"] = token
                break

    # phone — flag only
    phone_match = _PHONE_DIGITS_PATTERN.search(text)
    if phone_match:
        entities["phone"] = phone_match.group(0).strip()

    # age — "N წლის" form
    age_match = _AGE_PATTERN.search(text)
    if age_match:
        entities["child_age"] = age_match.group(1)

    return entities


def detect_parent_interrupt_intent(message: str) -> dict[str, Any] | None:
    """Deterministic intent classifier.

    Walks the priority list and returns the *first* intent whose stems
    match a substring of ``message`` (case-insensitive). Stops at the
    first match — never stacks intents.

    Returns ``None`` when no interrupt stem matches — the caller should
    treat this as "let the LLM analyzer decide, or fall through to the
    state machine".
    """
    if not message:
        return None
    text = message.lower()

    for intent, stems, confidence in _INTENT_STEMS:
        if _has_any_stem(text, stems):
            return {
                "intent": intent,
                "confidence": confidence,
                "entities": _extract_entities(message),
                "source": "deterministic",
            }
    return None
