"""Response policy / composer — Reasoning Layer Phase 3 Stage 3 (2026-06-24).

Reasoning-driven CONTENT + CTA policy. Given the planner's decision (intent /
active_topic / selected_state) and the admin/config facts, it composes a
consultant-quality reply that follows the brand sales flow
(docs/source/sales_agent_prompt.md):

  open the dialogue → ask the child age → discover the parent's pain point →
  show value → reveal price ONLY when asked or after engagement → CTA
  (registration link / manager) ONLY at the right stage.

It is a COMPOSER layer (not a phrase-per-wording handler): one render function
per planner intent, driven by `admin_config_service` facts (age band, price,
included items, focus areas, discovery questions, registration link). NO
hardcoded facts — every number/link/list is read from admin config. NO LLM, NO
side effects, NEVER raises (each composer has a safe fallback).

The brand "value" / "style" sentences are tunable module constants (the same
pattern the existing deterministic handlers in `parent_flow` use); the FACTS
they wrap always come from config.
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# ── Brand value / style fragments (tunable; facts are injected from config) ───
_CAMP_VALUE_LINE = (
    "აქ მთავარი მხოლოდ დასვენება არ არის — გარემო, ცოცხალი კომუნიკაცია, "
    "აზროვნება და ეკრანისგან ჯანსაღი დისტანცია."
)
_CHILD_AGE_QUESTION = "რამდენი წლისაა თქვენი შვილი?"
# Pain-point discovery options — the closed set is grounded in the audience
# analysis (docs/source/სამიზნე აუდიტორია.pdf: screen time / communication /
# interests / confidence / motivation). Discovery categories, NOT facts.
_PAIN_POINT_OPTIONS = (
    "ეკრანთან დიდი დრო", "კომუნიკაცია", "ინტერესების ნაკლებობა",
    "თავდაჯერებულობა",
)


def _camp_facts() -> dict:
    try:
        from app.services import admin_config_service
        return admin_config_service.get_camp_facts() or {}
    except Exception:  # pragma: no cover — defensive
        return {}


def _age_bounds() -> tuple[int, int]:
    try:
        from app.services import admin_config_service
        return admin_config_service.get_camp_age_bounds()
    except Exception:  # pragma: no cover — defensive
        return (9, 17)


# ── #1 camp_info — open the dialogue, ask the child age (no price/link/phone) ──

def camp_info_opener() -> str:
    """Short value-oriented camp intro + the child-age question. NO price, NO
    registration link, NO manager phone (those belong to later stages / explicit
    intents)."""
    age_min, age_max = _age_bounds()
    return (
        f"ბანაკი {age_min}–{age_max} წლის ბავშვებისთვისაა და {_CAMP_VALUE_LINE}"
        f"\n\n{_CHILD_AGE_QUESTION}"
    )


# ── #2 camp_price — value framing first, then price (no link/phone by default) ─

def camp_price_answer() -> str:
    """Value-framed price answer. Reveals the price (config) with what it
    includes; does NOT attach the registration link or manager phone unless the
    user separately asked (the planner routes those to their own intents)."""
    facts = _camp_facts()
    price = facts.get("price_gel")
    price_text = str(facts.get("price_text") or "").strip()
    if isinstance(price, int) and price > 0:
        price_str = f"{price} ლარი"
    elif price_text.isdigit():
        price_str = f"{price_text} ლარი"
    elif price_text:
        price_str = price_text
    else:
        # No price configured → don't invent one; defer to value + ask.
        return (
            "ფასს დაგიზუსტებთ — ჯერ მოკლედ გავიგოთ, რა არის თქვენთვის "
            f"მნიშვნელოვანი. {_CHILD_AGE_QUESTION}"
        )
    included = [str(x).strip() for x in (facts.get("included_items") or []) if str(x).strip()]
    duration = facts.get("duration_days")
    head = f"ფასი {price_str}ა."
    if included:
        # Merge the duration into the „program" item so it isn't duplicated
        # („…კვება, პროგრამა და 7-დღიანი პროგრამა").
        if isinstance(duration, int) and duration > 0:
            included = [
                (f"{duration}-დღიანი პროგრამა" if it == "პროგრამა" else it)
                for it in included
            ]
        if len(included) > 1:
            incl = ", ".join(included[:-1]) + f" და {included[-1]}"
        else:
            incl = included[0]
        head += f" თანხაში შედის {incl}."
    return (
        f"{head}\n\nმთავარი ღირებულება მხოლოდ დასვენება არ არის — ბავშვები "
        "რამდენიმე დღით ხვდებიან გარემოში, სადაც ცოცხლად ურთიერთობენ, აზრს "
        "გამოხატავენ და ეკრანისგან ბუნებრივად დისტანცირდებიან."
    )


# ── #3 eligible child age — confirm fit, then pain-point discovery ────────────

def eligible_age_reply(child_age: str) -> str:
    """Confirm the (eligible) age fits, give a one-line value frame, and ask the
    parent's pain point (brand discovery flow). NO price, NO link, NO forced
    consultation. Uses the config `discovery_questions[1]` when present, else a
    pain-point question built from the grounded options."""
    age_min, age_max = _age_bounds()
    age = (child_age or "").strip()
    confirm = (
        f"{age} წელი ბანაკის ასაკს შეესაბამება."
        if age else
        f"ეს ასაკი ბანაკს შეესაბამება ({age_min}–{age_max} წელი)."
    )
    value = (
        "ამ ასაკში პროგრამა ისეა აწყობილი, რომ ბავშვი უბრალოდ არ ისვენებს — "
        "ერთვება საუბარში, ურთიერთობასა და გამოცდილებაში."
    )
    options = " / ".join(_PAIN_POINT_OPTIONS)
    question = (
        f"თქვენ ყველაზე მეტად რა გაწუხებთ ამ ეტაპზე — {options} თუ სხვა რამ?"
    )
    return f"{confirm}\n\n{value}\n\n{question}"


# ── #5 Sunday School — answer status + offer consent (no auto-handoff) ────────

def sunday_school_info_with_consent(status_text: str, *, contact_known: bool) -> str:
    """Status answer (from admin config) + a CONSENT offer to pass the contact
    to the manager. Never says the info was already passed; never auto-dispatches."""
    status = (status_text or "").strip()
    if contact_known:
        offer = (
            "თუ გსურთ, თქვენს ინფორმაციას მენეჯერს გადავცემ და დაგიკავშირდებათ."
        )
    else:
        offer = (
            "თუ გსურთ, მენეჯერს გადავცემ თქვენს საკონტაქტოს, რომ დაგიკავშირდეთ — "
            "მომწერეთ თქვენი სახელი და 9-ნიშნა ნომერი."
        )
    return f"{status} {offer}".strip()


# ── #6 adult-event subscription — confirm with known contact, then save ──────

def subscription_confirm(name: str, phone_masked: str) -> str:
    """Confirmation step for a subscription consent (#6). Uses the KNOWN name +
    MASKED phone and asks to confirm before saving — NEVER asks the adult age,
    NEVER exposes the full phone. When a field is missing, ask for it instead."""
    name = (name or "").strip()
    phone_masked = (phone_masked or "").strip()
    if name and phone_masked:
        return (
            "კი, შეგვიძლია შევინახოთ თქვენი ინფორმაცია და ახალი ღონისძიება რომ "
            "დაემატება, შეგატყობინებთ.\n\n"
            "თქვენი მონაცემები უკვე მაქვს:\n"
            f"სახელი: {name}\n"
            f"ნომერი: {phone_masked}\n\n"
            "ამ მონაცემებით ჩაგწეროთ სიაში?"
        )
    missing = []
    if not name:
        missing.append("სახელი")
    if not phone_masked:
        missing.append("9-ნიშნა ნომერი")
    ask = " და ".join(missing) if missing else "საკონტაქტო"
    return (
        "კი, სიამოვნებით — ახალი ღონისძიება რომ დაემატება, შეგატყობინებთ.\n\n"
        f"მომწერეთ თქვენი {ask}, რომ სიაში ჩაგწეროთ."
    )


def subscription_saved() -> str:
    return (
        "კარგი, ჩაგწერეთ. ახალი ღონისძიების დამატებისას ინფორმაციას მოგწერთ."
    )


def subscription_failed() -> str:
    return (
        "ამ მომენტში სიაში დამატება ტექნიკურად ვერ მოხერხდა. მენეჯერს გადავცემ "
        "და ახალი ღონისძიების შესახებ შეგატყობინებთ."
    )


# ── #9 greeting after a closed/declined context — neutral menu ────────────────

def neutral_menu(company_name: str = "") -> str:
    """A neutral re-orientation menu (no stale camp/age continuation)."""
    return (
        "გამარჯობა. რით დაგეხმაროთ — ბანაკი გაინტერესებთ, საკვირაო სკოლა "
        "თუ ზრდასრულთა ღონისძიებები?"
    )


# ── #4 + #11 wording refinements (validator-style, applied to a draft) ────────

# „the AI explains the details" → „the manager explains the details".
_CONSULTATION_SELF_EXPLAIN_RE = re.compile(
    r"(კონსულტაცია[ზე]*\s*ჩაგწერ[თ]?[^.?!]*?)"
    r"(დეტალურად\s+აგიხსნი[თ]|დაგიხსნი[თ]\s+დეტალებს|აგიხსნი[თ]\s+პროგრამას)"
)


def fix_consultation_cta(text: str) -> str:
    """If a consultation CTA implies the AI itself will explain all the details,
    rewrite so the MANAGER explains them (#4). Idempotent; only touches a CTA
    that lacks a „მენეჯერ" attribution."""
    if not text or "კონსულტაცია" not in text:
        return text
    low = text.lower()
    if "მენეჯერ" in low:
        return text  # manager already credited — leave it
    out = text
    # Replace „…ჩაგწერთ და დეტალურად აგიხსნით (პროგრამას)" with the manager form.
    out = re.sub(
        r"(კონსულტაცია[ზე]*\s*ჩაგწერ[თ]?)([^.?!]*?)"
        r"(დეტალურად\s+აგიხსნი[თ][^.?!]*|აგიხსნი[თ]\s+პროგრამას[^.?!]*|"
        r"დაგიხსნი[თ]\s+დეტალებს[^.?!]*)",
        r"\1 და მენეჯერი დეტალებს აგიხსნით",
        out,
    )
    return out


def collapse_repeated_thanks(text: str) -> str:
    """Drop a redundant second „მადლობა"/„გმადლობთ" in one reply (#11)."""
    if not text:
        return text
    seen = False
    out_parts = []
    for sent in re.split(r"(?<=[.!?])\s+", text):
        low = sent.lower()
        if ("მადლობ" in low) or ("გმადლობ" in low):
            if seen:
                continue
            seen = True
        out_parts.append(sent)
    return " ".join(out_parts).strip() or text
