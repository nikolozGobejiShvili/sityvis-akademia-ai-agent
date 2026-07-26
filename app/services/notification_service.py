import logging
import re
import smtplib
from email.message import EmailMessage
from typing import Callable

import httpx

from app.config import Settings, has_value, settings
from app.models.lead import Lead
from app.services import messenger_service
from data.prompts import (
    ADULT_FOLLOWUP,
    BOOKING_TEXT_NO,
    BOOKING_TEXT_YES,
    ERROR_MESSAGE,
    MANAGER_DETAILS_ADULT,
    MANAGER_DETAILS_PARENT,
    MANAGER_EMAIL_BODY,
    MANAGER_EMAIL_SUBJECT,
    MANAGER_SHORT_ADULT,
    MANAGER_SHORT_PARENT,
    MANAGER_SMS_BODY,
    MANAGER_WHATSAPP_BODY,
    PARENT_FOLLOWUP,
)

logger = logging.getLogger(__name__)

GRAPH_API_BASE_URL = "https://graph.facebook.com/v18.0"


class ExternalEmailDeliveryBlocked(BaseException):
    """Raised by test-side guards when real SMTP delivery is attempted.

    This intentionally derives from ``BaseException`` so broad production
    ``except Exception`` blocks used around notification side effects cannot
    turn a forbidden test delivery into a silent false success.
    """


EmailTransport = Callable[[EmailMessage, str, int, str, str], None]


def _smtp_email_transport(
    email: EmailMessage,
    smtp_host: str,
    smtp_port: int,
    smtp_user: str,
    smtp_password: str,
) -> None:
    """Production SMTP transport. Tests replace ``_email_transport``."""
    with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as smtp:
        smtp.starttls()
        smtp.login(smtp_user, smtp_password)
        smtp.send_message(email)


_email_transport: EmailTransport = _smtp_email_transport


def _dispatch_manager_channels(lead: Lead, event_type: str) -> tuple[bool, bool]:
    """Send the manager WhatsApp + email (+ best-effort SMS) and return
    ``(email_ok, whatsapp_ok)``. Single dispatch point so callers can pick
    their OWN success contract (e.g. email-only). The behaviour of each
    transport is byte-identical to the previous inline body — this is a pure
    extraction (no change to the WhatsApp / email / SMS send logic)."""
    logger.info("[notification] manager notification start sender=%s", lead.sender_id)

    whatsapp_configured = settings.is_whatsapp_configured()
    logger.info(
        "[notification] sending WhatsApp manager notification configured=%s",
        whatsapp_configured,
    )
    try:
        whatsapp_body = _manager_whatsapp_body(lead, event_type)
        whatsapp_ok = _send_manager_whatsapp(whatsapp_body)
    except Exception as exc:
        logger.error(
            "[notification] webhook/WhatsApp failed: %s", exc, exc_info=True,
        )
        whatsapp_ok = False
    logger.info("[notification] webhook/WhatsApp result=%s", whatsapp_ok)

    logger.info(
        "[notification] sending email to=%s",
        settings.MANAGER_EMAIL or "(missing)",
    )
    try:
        email_body = _manager_email_body(lead)
        email_ok = _send_email(
            subject=_build_email_subject(lead),
            body=email_body,
        )
    except Exception as exc:
        logger.error("[notification] email failed: %s", exc, exc_info=True)
        email_ok = False
    logger.info("[notification] email result=%s", email_ok)

    if _twilio_configured():
        try:
            sms_body = MANAGER_SMS_BODY.format(
                segment=lead.segment,
                platform=lead.platform,
                status=lead.status,
            )
            _send_sms(sms_body)
        except Exception as exc:
            logger.error("[notification] SMS failed: %s", exc, exc_info=True)

    logger.info(
        "[notification] manager notification done sender=%s email_ok=%s whatsapp_ok=%s",
        lead.sender_id, email_ok, whatsapp_ok,
    )
    return email_ok, whatsapp_ok


def notify_manager(lead: Lead, event_type: str) -> bool:
    """Send manager notifications. Email + WhatsApp results are independent.

    Returns True only if BOTH channels succeed (back-compat). Either
    channel failing is logged but does NOT raise and does NOT roll back
    the booking — the caller in parent_flow / parent_tool_executor wraps
    this in its own try/except and proceeds regardless.
    """
    email_ok, whatsapp_ok = _dispatch_manager_channels(lead, event_type)
    return email_ok and whatsapp_ok


def notify_sunday_school_handoff(lead: Lead) -> bool:
    """EMAIL-ONLY manager handoff for a Sunday-School lead (planned July).

    Sunday School is NOT a camp consultation: no Calendar, no WhatsApp, no
    Sheets here — just an email to the manager. Returns the REAL email
    dispatch result so the caller only confirms „გადავეცი" on a true send.
    Deliberately does NOT touch ``notify_manager`` / ``notify_manager_handoff``
    so existing flows + WhatsApp notification logic stay unchanged."""
    name = (lead.name or "").strip() or "—"
    phone = (lead.phone or "").strip() or "—"
    body = "\n".join([
        "საკვირაო სკოლის ახალი მოთხოვნა (ბანაკის კონსულტაცია არ დაჯავშნილა).",
        "",
        f"სახელი: {name}",
        f"ტელეფონი: {phone}",
        "ტიპი: საკვირაო სკოლა (sunday_school)",
        "",
        f"პლატფორმა: {lead.platform}",
        f"სეგმენტი: {lead.segment}",
    ])
    subject = f"საკვირაო სკოლა — ახალი მოთხოვნა — {name}"
    try:
        return _send_email(subject=subject, body=body)
    except Exception as exc:
        logger.exception("[notification] sunday-school email failed: %s", exc)
        return False


def send_followup_message(lead: Lead) -> bool:
    text = _followup_text(lead)
    sent = messenger_service.send_message(
        sender_id=lead.sender_id,
        platform=lead.platform,
        text=text,
    )
    if sent:
        logger.info("[NOTIFICATION] Follow-up sent: sender_id=%s", lead.sender_id)
    else:
        logger.error("[NOTIFICATION] Follow-up failed: sender_id=%s", lead.sender_id)
    return sent


def send_manager_notification(lead: Lead, summary: str) -> bool:
    """Manager lead notification. Sends the SAME email + WhatsApp as before
    (WhatsApp send logic unchanged), but the boolean is now EMAIL-GATED:
    returns True iff the manager EMAIL actually dispatched.

    False-success fix (2026-06-22): the old contract returned
    ``email AND whatsapp`` — and since WhatsApp is intentionally unconfigured
    in production, that was False on every real email-only send. Callers that
    gate on this (the manager-callback executor) must treat an email-only send
    as success, so the boolean reflects the email channel. Fire-and-forget
    callers (booking, adult, follow-up) ignore the return and are unaffected;
    WhatsApp is still attempted exactly as before."""
    if summary:
        lead.conversation_summary = summary
    email_ok, _whatsapp_ok = _dispatch_manager_channels(lead, "lead")
    return email_ok


def notify_manager_handoff(lead: Lead, reason: str) -> bool:
    """Message-only operator handoff notification — NO Sheets / Calendar.

    Used for a non-booking handoff (e.g. an under-age child whose parent
    asked to be connected to a manager): there is no consultation, so
    NOTHING is written to Calendar or Sheets — only an operator message is
    dispatched with the lead's name + phone + the handoff reason.

    Dispatches through the EXISTING transports (`_send_email` +
    `_send_manager_whatsapp`) — transport / credentials are unchanged.
    Returns True when AT LEAST ONE channel actually dispatched, so the
    caller only ever claims success on a real send. (NB: `notify_manager`
    returns email AND whatsapp; here we need OR, because in production the
    WhatsApp channel is intentionally unconfigured and email alone is a
    valid, real dispatch.)
    """
    name = (lead.name or "").strip() or "—"
    phone = (lead.phone or "").strip() or "—"
    reason = (reason or "").strip()

    body_lines = [
        "ხელით გადასაცემი მოთხოვნა (კონსულტაცია არ დაჯავშნილა).",
        "",
        f"სახელი: {name}",
        f"ტელეფონი: {phone}",
    ]
    if reason:
        body_lines.append(f"მიზეზი: {reason}")
    body_lines += [
        "",
        f"პლატფორმა: {lead.platform}",
        f"სეგმენტი: {lead.segment}",
    ]
    body = "\n".join(body_lines)
    subject = f"მენეჯერთან გადასაცემი მოთხოვნა — {name}"

    email_ok = False
    whatsapp_ok = False
    try:
        email_ok = _send_email(subject=subject, body=body)
    except Exception as exc:  # pragma: no cover — defensive
        logger.error("[notification] handoff email failed: %s", exc)
    try:
        whatsapp_ok = _send_manager_whatsapp(body)
    except Exception as exc:  # pragma: no cover — defensive
        logger.error("[notification] handoff whatsapp failed: %s", exc)

    dispatched = bool(email_ok or whatsapp_ok)
    logger.info(
        "[notification] manager handoff dispatched=%s (email=%s whatsapp=%s) sender=%s",
        dispatched, email_ok, whatsapp_ok, lead.sender_id,
    )
    return dispatched


class NotificationService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def configured(self) -> bool:
        return has_value(self.settings.MANAGER_EMAIL) and has_value(self.settings.MANAGER_WHATSAPP_NUMBER)

    def send_lead_notification(self, lead: Lead, reply: str) -> bool:
        return notify_manager(lead, "lead")


_EMPTY_MARKERS: frozenset[str] = frozenset({
    "", "—", "-", "n/a", "N/A", "null", "None", "none",
})


def _georgian_genitive(name: str) -> str:
    """Return the Georgian genitive of a company / brand name.

    Examples:
        "სიტყვის აკადემია" → "სიტყვის აკადემიის"
        "კოლეჯი"           → "კოლეჯის"
        "ცენტრი"           → "ცენტრის"
        "სკოლა"            → "სკოლის"

    Rule (simplified Mkhedruli morphology — covers the noun endings the
    brand actually uses):
      * words ending in `ა`, `ე`, or `ი` drop the final vowel before
        the `-ის` suffix;
      * other endings get `-ის` appended verbatim.

    Operates on the LAST whitespace-separated token only, so multi-word
    names like "სიტყვის აკადემია" keep the preceding "სიტყვის"
    untouched and only inflect "აკადემია" → "აკადემიის".
    """
    if not name:
        return ""
    name = name.strip()
    if not name:
        return ""
    words = name.split()
    last = words[-1]
    if last and last[-1] in ("ა", "ე", "ი"):
        last = last[:-1] + "ის"
    else:
        last = last + "ის"
    words[-1] = last
    return " ".join(words)


def _has_meaningful_value(value: str | None) -> bool:
    """True only when the field carries non-placeholder content."""
    if value is None:
        return False
    cleaned = str(value).strip()
    return bool(cleaned) and cleaned.lower() not in {
        m.lower() for m in _EMPTY_MARKERS
    }


def _normalize_for_dup_check(value: str | None) -> str:
    """Lowercase + strip + collapse whitespace, for duplicate detection."""
    if not value:
        return ""
    return " ".join(str(value).strip().lower().split())


def _format_booked_datetime_georgian(iso: str | None) -> str:
    """Format `2026-05-27T10:00:00+04:00` → `27 მაისი, 10:00`.

    Returns "" on any parse failure so the caller can omit the line.
    """
    if not iso:
        return ""
    try:
        from datetime import datetime as _dt
        text = iso.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = _dt.fromisoformat(text)
    except (ValueError, TypeError):
        return ""
    # Reuse the existing Georgian month table from parent_flow if it's
    # available; fall back to a local copy so this helper has no hard
    # import cycle requirement.
    try:
        from app.flows.parent_flow import GEORGIAN_MONTHS_NOM
        month = GEORGIAN_MONTHS_NOM[dt.month]
    except Exception:
        _fallback = (
            "", "იანვარი", "თებერვალი", "მარტი", "აპრილი", "მაისი",
            "ივნისი", "ივლისი", "აგვისტო", "სექტემბერი", "ოქტომბერი",
            "ნოემბერი", "დეკემბერი",
        )
        month = _fallback[dt.month] if 1 <= dt.month <= 12 else dt.strftime("%B")
    return f"{dt.day} {month}, {dt.strftime('%H:%M')}"


def _program_interest_phrase(lead: Lead) -> str:
    """The program the lead is interested in, for the manager summary. A non-camp
    per-product booking tags ``lead.program_id``; when USE_PER_PRODUCT_BOOKING is on,
    name the REAL program (e.g. „დისნეილენდი") instead of always „ბანაკი", so the
    manager email is correct. Empty program_id OR flag off → „ბანაკით" (byte-identical).
    Never raises."""
    pid = (getattr(lead, "program_id", "") or "").strip()
    if not pid or not getattr(settings, "USE_PER_PRODUCT_BOOKING", False):
        return "ბანაკით"
    try:
        from app.services import admin_config_service
        section = admin_config_service.get_section(pid) or {}
        name = str(section.get("name") or "").strip()
        if name:
            return f'პროგრამით „{name}"'
    except Exception:  # pragma: no cover - defensive
        pass
    return "ბანაკით"


def _build_parent_summary(lead: Lead) -> str:
    """Short fixed Georgian summary keyed on booking state.

    The full LLM-generated `lead.conversation_summary` is kept on the
    Lead for CRM / Sheets, but the email no longer prints it: the
    narrative tends to re-state the structured fields and reads as
    duplication. This summary is one or two short sentences.

    Live QA Session 7 Patch (2026-06-06) — Bug 4: the summary now
    concretely names the parent's interest when ``lead.challenge`` is
    populated (so the manager sees the topic, not just „ბანაკით
    დაინტერესებულია"). The challenge text itself is deduped against
    repeated phrases before it is woven in.
    """
    # Email Content Cleanup (2026-06-10): the summary weaves in the
    # cleaned goals (filler + factual questions removed), never the raw
    # chat text — so „მოკლე რეზიუმე" stays a clean manager summary and
    # never duplicates raw user phrasing already shown above.
    challenge_clean = _clean_challenge_for_email(lead.challenge).strip()
    interest = _program_interest_phrase(lead)
    if lead.calendly_booked:
        when = _format_booked_datetime_georgian(lead.booked_datetime_iso)
        if challenge_clean and when:
            return (
                f"მშობელი დაინტერესებულია {interest} — "
                f"მთავარი ფოკუსი: {challenge_clean}. "
                f"კონსულტაცია ჩანიშნულია {when} საათზე."
            )
        if when:
            return (
                f"ლიდი დაინტერესებულია {interest}. "
                f"კონსულტაცია ჩანიშნულია {when} საათზე."
            )
        return f"ლიდი დაინტერესებულია {interest}. კონსულტაცია უკვე ჩანიშნულია."
    if challenge_clean:
        return (
            f"მშობელი დაინტერესებულია {interest} — მთავარი ფოკუსი: "
            f"{challenge_clean}. საჭიროებს მენეჯერის დაკავშირებას."
        )
    return (
        f"ლიდი დაინტერესებულია {interest} და საჭიროებს მენეჯერის დაკავშირებას."
    )


def _build_adult_summary(lead: Lead) -> str:
    if lead.calendly_booked:
        return "ლიდი დაინტერესებულია ღონისძიებით. ბილეთი დაჯავშნილია."
    return (
        "ლიდი დაინტერესებულია ღონისძიებით და საჭიროებს მენეჯერის "
        "დაკავშირებას."
    )


def _manager_email_body(lead: Lead) -> str:
    """Compose the manager-notification email body.

    Programmatic build (NOT YAML format-string) so we can:
      * inflect the company name into the correct Georgian genitive
        ("სიტყვის აკადემიის", not "სიტყვის აკადემიაის");
      * skip empty / duplicate fields (no more "ღრმა ფესვი: —");
      * keep `lead.conversation_summary` for CRM but render a short,
        non-duplicating summary in the email itself.

    Live QA Session 7 Patch (2026-06-06) — Bug 4: headline now matches
    the subject (booked → „ახალი კონსულტაცია", otherwise „ახალი
    ლიდი") so a manager skim-reading the inbox sees the same framing.
    Challenge / interest text is deduped before printing.
    """
    lines: list[str] = []
    company_genitive = _georgian_genitive(settings.COMPANY_NAME)
    headline = (
        "ახალი კონსულტაცია ჩაინიშნა"
        if bool(getattr(lead, "calendly_booked", False))
        else "ახალი ლიდი"
    )
    lines.append(f"{headline} {company_genitive} AI Agent-იდან")
    lines.append("")
    lines.append(f"პლატფორმა: {lead.platform}")
    lines.append(f"სეგმენტი: {lead.segment}")
    lines.append(f"სტატუსი: {lead.status}")
    lines.append("")

    lines.extend(_segment_detail_lines(lead))

    contact_lines = _contact_info_lines(lead)
    if contact_lines:
        lines.append("")
        lines.extend(contact_lines)

    summary = _email_summary_for(lead)
    if summary:
        lines.append("")
        lines.append("მოკლე რეზიუმე:")
        lines.append(summary)

    return "\n".join(lines).strip()


def _segment_detail_lines(lead: Lead) -> list[str]:
    """Build the structured-details block as a list of lines.

    Each line is only added when its value is meaningful (non-empty,
    not a "—" placeholder). Duplicate-detection ensures the same
    sentence isn't printed twice under different labels.
    """
    if lead.segment == "PARENT":
        return _parent_detail_lines(lead)
    if lead.segment == "ADULT":
        return _adult_detail_lines(lead)
    return []


def _parent_detail_lines(lead: Lead) -> list[str]:
    seen: set[str] = set()

    def _add_if_new(label: str, value: str | None) -> str:
        if not _has_meaningful_value(value):
            return ""
        # Live QA Session 7 Patch (2026-06-06) — Bug 4: dedupe a
        # repeated-phrase pattern in `challenge` BEFORE the duplicate
        # detector compares it against other fields. Live observation:
        # the LLM produced "კომუნიკაცია განვითარება კომუნიკაცია
        # განვითარება" which the old code printed as-is.
        cleaned = _dedupe_repeated_phrase(str(value).strip())
        if not cleaned:
            return ""
        key = _normalize_for_dup_check(cleaned)
        if key in seen:
            return ""
        seen.add(key)
        return f"{label}: {cleaned}"

    out: list[str] = []
    if _has_meaningful_value(lead.child_age):
        out.append(f"ბავშვის ასაკი: {str(lead.child_age).strip()}")

    # Email Content Cleanup (2026-06-10) — render only the cleaned goals
    # under „ინტერესი / გამოწვევა" (filler + factual questions removed).
    # When nothing meaningful remains, surface the explicit
    # „არ არის მითითებული" placeholder (rule 7) instead of omitting the
    # line. `lead.challenge` is left untouched (Sheets/CRM unaffected).
    cleaned_challenge = (
        _clean_challenge_for_email(lead.challenge)
        if _has_meaningful_value(lead.challenge)
        else ""
    )
    if cleaned_challenge:
        key = _normalize_for_dup_check(cleaned_challenge)
        if key not in seen:
            seen.add(key)
            out.append(f"ინტერესი / გამოწვევა: {cleaned_challenge}")
    else:
        out.append(f"ინტერესი / გამოწვევა: {_EMAIL_CHALLENGE_UNKNOWN}")

    # Optional: surface a factual question separately so it is never
    # mixed into the goals field (rule 4).
    additional_question = _extract_additional_question(lead.challenge)
    if additional_question:
        out.append(f"დამატებითი კითხვა: {additional_question}")

    desired_line = _add_if_new("სასურველი ცვლილება", lead.desired_change)
    if desired_line:
        out.append(desired_line)

    deeper_line = _add_if_new(
        "მშობლის დამატებითი დაკვირვება", lead.deeper_concern,
    )
    if deeper_line:
        out.append(deeper_line)

    # Booking line — show the formatted date if booked, otherwise the
    # binary yes/no.
    if lead.calendly_booked:
        when = _format_booked_datetime_georgian(lead.booked_datetime_iso)
        if when:
            out.append(f"კონსულტაცია: {when}")
        else:
            out.append(f"კონსულტაცია: {_booking_text(True)}")
    else:
        out.append(f"კონსულტაცია: {_booking_text(False)}")
    return out


# Live QA Session 7 Patch (2026-06-06) — Bug 4: helper that collapses a
# duplicated phrase pattern such as "X Y X Y" (or "X X") into a single
# instance. Used by the parent detail block and the email summary so
# the manager email never carries the LLM's word-doubling artefact.

def _dedupe_repeated_phrase(value: str) -> str:
    """Collapse a doubled phrase. Returns the input unchanged when no
    obvious doubling is detected.

    Conservative: only collapses when the entire string looks like
    "<phrase> <phrase>" or "<phrase>, <phrase>" (case-insensitive, with
    optional ", " or " — " separators). Multi-word phrases are
    preferred over single-word doublings so legitimate Georgian text
    like „კარგი კარგი დღე" isn't accidentally folded — but "კომუნიკაცია
    განვითარება კომუნიკაცია განვითარება" (two identical halves) is.
    """
    if not value:
        return value
    text = value.strip()
    if len(text) < 6:
        return text

    # 1. Try splitting in half — if the two halves are identical
    # (modulo whitespace and case), drop the second one.
    half = len(text) // 2
    # Search around the midpoint for a whitespace boundary so we
    # don't split inside a token.
    for offset in (0, 1, -1, 2, -2):
        idx = half + offset
        if idx <= 0 or idx >= len(text):
            continue
        if text[idx] not in (" ", ","):
            continue
        left = text[:idx].strip(" ,")
        right = text[idx:].strip(" ,")
        if left and right and left.casefold() == right.casefold():
            return left

    # 2. Fall back to a tokenwise "AB AB" check — A and B are single
    # tokens; only collapse when the four-token sequence reads
    # "A B A B".
    tokens = text.split()
    if len(tokens) == 4:
        if (
            tokens[0].casefold() == tokens[2].casefold()
            and tokens[1].casefold() == tokens[3].casefold()
        ):
            return f"{tokens[0]} {tokens[1]}"
    # 3. Token-by-token: a single repeated token "X X" → "X".
    if len(tokens) == 2 and tokens[0].casefold() == tokens[1].casefold():
        return tokens[0]
    return text


# Email Content Cleanup (2026-06-10).
#
# `lead.challenge` is captured from natural chat and frequently carries
# filler ("ასევე მაინტერესებს", "კი მინდა") and factual questions
# ("როდის ტარდება") mixed in with the real parent goals. The manager
# email must show only clean goals under „ინტერესი / გამოწვევა"; a
# factual question (if any) goes to an optional „დამატებითი კითხვა"
# line. `lead.challenge` itself is NOT mutated — the Sheets/CRM write is
# unaffected; only the email rendering is cleaned.
_EMAIL_CHALLENGE_FILLER: tuple[str, ...] = (
    # longest first so shorter substrings don't pre-empt the full phrase
    "კონსულტაციის ჩაწერა",
    "ასევე მაინტერესებს",
    "ბანაკის დეტალებში",
    "პირობებში რა იგულისხმება",
    "კონსულტაცია მინდა",
    "ჩაწერა მინდა",
    "კი მინდა",
    "მაინტერესებს",
    "დეტალებში",
    "დეტალები",
    "პირობებში",
    "მომწერეთ",
    "ასევე",
    "მინდა",
)

# A clause containing any of these is a factual question, not a goal.
_EMAIL_QUESTION_STEMS: tuple[str, ...] = (
    "როდის", "სად", "რამდენი", "ფასი", "ღირს", "საათზე",
    "რა იგულისხმება", "?",
)

_EMAIL_CHALLENGE_UNKNOWN = "არ არის მითითებული"


def _split_challenge_clauses(raw: str) -> list[str]:
    """Split a raw challenge string into clauses on commas / semicolons
    and the connector „ასევე"."""
    parts = re.split(r"[,;]|\bასევე\b", raw or "")
    return [p.strip(" .,-—\t") for p in parts if p.strip(" .,-—\t")]


def _clause_is_question(clause: str) -> bool:
    low = (clause or "").casefold()
    return any(stem in low for stem in _EMAIL_QUESTION_STEMS)


def _strip_email_filler(clause: str) -> str:
    out = clause or ""
    for filler in _EMAIL_CHALLENGE_FILLER:
        out = re.sub(re.escape(filler), " ", out, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", out).strip(" .,-—\t")


def _canonicalise_goal(clause: str) -> str:
    """Normalise a few noisy goal variants. Unknown goals pass through
    untouched (we never invent or drop a legitimate goal)."""
    low = (clause or "").casefold()
    if "ეკრან" in low:
        return "ეკრანთან დროის შემცირება"
    return clause


def _clean_challenge_for_email(raw: str | None) -> str:
    """Return only the meaningful parent goals from a raw challenge
    string, with filler and factual questions removed and a few noisy
    variants normalised. Returns "" when nothing meaningful remains."""
    base = _dedupe_repeated_phrase((raw or "").strip()).strip()
    if not base:
        return ""
    kept: list[str] = []
    seen: set[str] = set()
    for clause in _split_challenge_clauses(base):
        if _clause_is_question(clause):
            continue
        cleaned = _strip_email_filler(clause)
        if not cleaned:
            continue
        cleaned = _canonicalise_goal(cleaned)
        key = cleaned.casefold()
        if key in seen:
            continue
        seen.add(key)
        kept.append(cleaned)
    return ", ".join(kept)


def _extract_additional_question(raw: str | None) -> str:
    """Return a cleaned factual question from the raw challenge, if any
    (filler removed, trailing „?" ensured). "" when there is none."""
    base = (raw or "").strip()
    if not base:
        return ""
    for clause in _split_challenge_clauses(base):
        if not _clause_is_question(clause):
            continue
        question = _strip_email_filler(clause).strip(" ?")
        if question:
            return f"{question}?"
    return ""


def _build_email_subject(lead: Lead) -> str:
    """Live QA Session 7 Patch (2026-06-06) — Bug 4.

    Subject lines:
      * Booked + name        → "<name> — ახალი კონსულტაცია AI Agent-იდან"
      * Booked + no name     → "ახალი კონსულტაცია AI Agent-იდან"
      * Not booked + name    → "<name> — ახალი ლიდი AI Agent-იდან"
      * Not booked + no name → "ახალი ლიდი AI Agent-იდან"

    The lead's segment is no longer in the subject — it's in the body.
    A booked status surfaces as „კონსულტაცია" so the manager can scan
    booked vs unbooked at a glance.
    """
    has_name = _has_meaningful_value(lead.name)
    headline = (
        "ახალი კონსულტაცია AI Agent-იდან"
        if bool(getattr(lead, "calendly_booked", False))
        else "ახალი ლიდი AI Agent-იდან"
    )
    if has_name:
        first_name = str(lead.name).strip().split()[0]
        return f"{first_name} — {headline}"
    return headline


def _adult_detail_lines(lead: Lead) -> list[str]:
    out: list[str] = []
    if _has_meaningful_value(lead.event_interest):
        out.append(f"ღონისძიება: {str(lead.event_interest).strip()}")
    out.append(f"ბილეთი: {_booking_text(lead.calendly_booked)}")
    return out


def _contact_info_lines(lead: Lead) -> list[str]:
    has_name = _has_meaningful_value(lead.name)
    has_phone = _has_meaningful_value(lead.phone)
    if not (has_name or has_phone):
        return []
    out = ["საკონტაქტო ინფორმაცია:"]
    if has_name:
        out.append(f"სახელი: {str(lead.name).strip()}")
    if has_phone:
        out.append(f"ტელეფონი: {str(lead.phone).strip()}")
    return out


def _email_summary_for(lead: Lead) -> str:
    if lead.segment == "PARENT":
        return _build_parent_summary(lead)
    if lead.segment == "ADULT":
        return _build_adult_summary(lead)
    return ""


def _segment_details(lead: Lead) -> str:
    """Back-compat shim — kept so any external caller / test that still
    invokes this function gets the new programmatic block. The email
    body builder no longer calls it; only the WhatsApp / SMS short
    bodies do (via the unchanged helpers below).
    """
    return "\n".join(_segment_detail_lines(lead))


def _short_details(lead: Lead) -> str:
    if lead.segment == "PARENT":
        return MANAGER_SHORT_PARENT.format(
            child_age=lead.child_age,
            challenge=lead.challenge,
        )
    if lead.segment == "ADULT":
        return MANAGER_SHORT_ADULT.format(event_interest=lead.event_interest)
    return ""


def _manager_short_body(lead: Lead, event_type: str) -> str:
    return MANAGER_WHATSAPP_BODY.format(
        company_name=settings.COMPANY_NAME,
        platform=lead.platform,
        segment=lead.segment,
        short_details=_short_details(lead),
        status=lead.status,
    ).strip()


def _manager_whatsapp_body(lead: Lead, event_type: str) -> str:
    """Programmatic WhatsApp manager-notification body (NO template / prompt
    file). Mirrors the email's core facts but short + readable for a phone:
    type (booking vs lead/handoff), name, phone, child age (PARENT) or event
    (ADULT), booked date/time, and the channel. Never includes tokens or
    internal ids (Manager WhatsApp Notification Fix, 2026-06-18)."""
    booked = bool(getattr(lead, "calendly_booked", False))
    header = (
        f"✅ ახალი კონსულტაცია — {settings.COMPANY_NAME}"
        if booked
        else f"🔔 ახალი ლიდი — {settings.COMPANY_NAME}"
    )
    lines = [header, ""]

    name = (lead.name or "").strip()
    phone = (lead.phone or "").strip()
    if name:
        lines.append(f"სახელი: {name}")
    if phone:
        lines.append(f"ტელეფონი: {phone}")

    if lead.segment == "PARENT" and _has_meaningful_value(lead.child_age):
        lines.append(f"ბავშვის ასაკი: {str(lead.child_age).strip()}")
    if lead.segment == "ADULT" and _has_meaningful_value(lead.event_interest):
        lines.append(f"ღონისძიება: {str(lead.event_interest).strip()}")

    if booked:
        when = _format_booked_datetime_georgian(lead.booked_datetime_iso)
        if when:
            lines.append(f"კონსულტაცია: {when}")

    lines.append(f"არხი: {lead.platform} / {lead.segment}")
    return "\n".join(lines).strip()


def _send_email(subject: str, body: str) -> bool:
    """Send the manager notification email.

    Gates (return False without raising):
      * ENABLE_EMAIL_NOTIFICATIONS=false → skip with warning.
      * MANAGER_EMAIL missing → skip with warning.
      * SMTP_HOST / SMTP_USER / SMTP_PASSWORD missing → skip with warning.

    On SMTP auth failure (common cause: regular Gmail password used
    instead of an App Password), log a specific instruction. The
    SMTP_PASSWORD is never logged in any branch.
    """
    if not settings.ENABLE_EMAIL_NOTIFICATIONS:
        logger.warning(
            "[NOTIFICATION][EMAIL] Skipped — ENABLE_EMAIL_NOTIFICATIONS=false",
        )
        return False

    if not has_value(settings.MANAGER_EMAIL):
        logger.warning(
            "[NOTIFICATION][EMAIL] Skipped — MANAGER_EMAIL missing in .env",
        )
        return False

    missing_smtp: list[str] = []
    if not has_value(settings.SMTP_HOST):
        missing_smtp.append("SMTP_HOST")
    if not has_value(settings.SMTP_USER):
        missing_smtp.append("SMTP_USERNAME")
    if not has_value(settings.SMTP_PASSWORD):
        missing_smtp.append("SMTP_PASSWORD")
    if missing_smtp:
        logger.warning(
            "[NOTIFICATION][EMAIL] Skipped — missing SMTP config: %s. "
            "For Gmail, set SMTP_HOST=smtp.gmail.com, SMTP_PORT=587, "
            "SMTP_USERNAME=<your-gmail>, SMTP_PASSWORD=<Gmail App Password>. "
            "Gmail App Password required (regular Gmail password will not work).",
            ", ".join(missing_smtp),
        )
        return False

    from_email = settings.SMTP_FROM_EMAIL or settings.SMTP_USER

    try:
        email = EmailMessage()
        email["From"] = from_email
        email["To"] = settings.MANAGER_EMAIL
        email["Subject"] = subject
        email.set_content(body)

        logger.info(
            "[NOTIFICATION][EMAIL] Connecting host=%s port=%s from=%s to=%s",
            settings.SMTP_HOST, settings.SMTP_PORT, from_email,
            settings.MANAGER_EMAIL,
        )

        _email_transport(
            email,
            settings.SMTP_HOST,
            settings.SMTP_PORT,
            settings.SMTP_USER,
            settings.SMTP_PASSWORD,
        )

        logger.info("[NOTIFICATION][EMAIL] Manager notified to=%s", settings.MANAGER_EMAIL)
        return True
    except ExternalEmailDeliveryBlocked:
        raise
    except smtplib.SMTPAuthenticationError as exc:
        logger.error(
            "[NOTIFICATION][EMAIL] SMTP authentication failed — "
            "Gmail App Password required (regular Gmail password will not work). "
            "Create one at: Google Account → Security → 2-Step Verification → "
            "App Passwords. SMTP error code=%s",
            getattr(exc, "smtp_code", "?"),
        )
        return False
    except (smtplib.SMTPConnectError, smtplib.SMTPServerDisconnected, OSError) as exc:
        logger.error(
            "[NOTIFICATION][EMAIL] SMTP connection failed host=%s port=%s: %s",
            settings.SMTP_HOST, settings.SMTP_PORT, exc,
        )
        return False
    except Exception as exc:
        logger.exception("[NOTIFICATION][EMAIL] Failed: %s", exc)
        return False


def _mask_recipient(number: str) -> str:
    """Return only the last 4 digits of a recipient for safe logging."""
    digits = "".join(ch for ch in str(number or "") if ch.isdigit())
    return f"****{digits[-4:]}" if len(digits) >= 4 else "****"


def _send_manager_whatsapp(text: str) -> bool:
    """Send the manager-notification WhatsApp message (WhatsApp Cloud API).

    Config is resolved through the centralised, alias-aware accessors
    (Manager WhatsApp Notification Fix, 2026-06-18):
      * token     ← `settings.get_whatsapp_access_token()`  (WHATSAPP_ACCESS_TOKEN / WHATSAPP_TOKEN)
      * phone id  ← `settings.get_whatsapp_phone_number_id()` (WHATSAPP_PHONE_NUMBER_ID)
      * recipient ← `settings.get_manager_whatsapp_number()` (MANAGER_WHATSAPP / MANAGER_WHATSAPP_NUMBER, E.164-normalised)

    WhatsApp credentials are OPTIONAL. When not fully configured the
    function short-circuits with a single clean log line — NO `httpx.post`
    (httpx rejects an "Authorization: Bearer " header with an empty token
    as an illegal header value), NO exception. Email notifications stay
    fully independent of this path. The token is NEVER logged; the
    recipient is logged masked (last 4 digits only).
    """
    if not settings.is_whatsapp_configured():
        logger.info(
            "[NOTIFICATION][WHATSAPP] Skipped: WhatsApp not configured "
            "(token / WHATSAPP_PHONE_NUMBER_ID / manager number)",
        )
        return False

    # Live-send guard (2026-06-23) — a REAL Meta POST happens ONLY when the
    # operator explicitly opts in via ALLOW_LIVE_WHATSAPP=true. When the flag is
    # false / missing the function NEVER reaches `httpx.post`; it logs a blocked
    # line and returns a safe failure, so tests / CI / dev with live credentials
    # in `.env` cannot accidentally message the manager.
    if not getattr(settings, "ALLOW_LIVE_WHATSAPP", False):
        logger.info(
            "[NOTIFICATION][WHATSAPP] Blocked: live send disabled "
            "(ALLOW_LIVE_WHATSAPP is not true) — no Meta POST",
        )
        return False

    token = settings.get_whatsapp_access_token()
    phone_number_id = settings.get_whatsapp_phone_number_id()
    recipient = settings.get_manager_whatsapp_number()

    try:
        response = httpx.post(
            f"{GRAPH_API_BASE_URL}/{phone_number_id}/messages",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "messaging_product": "whatsapp",
                "to": recipient,
                "type": "text",
                "text": {"body": text},
            },
            timeout=15,
        )
        if response.is_success:
            logger.info(
                "[NOTIFICATION][WHATSAPP] Manager notified (to=%s)",
                _mask_recipient(recipient),
            )
            return True

        logger.error(
            "[NOTIFICATION][WHATSAPP] Failed: status=%s body=%s",
            response.status_code,
            response.text,
        )
        return False
    except Exception as exc:
        logger.exception("[NOTIFICATION][WHATSAPP] Failed: %s", exc)
        return False


def _send_sms(text: str) -> bool:
    try:
        from twilio.rest import Client

        client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
        client.messages.create(
            body=text,
            from_=settings.TWILIO_FROM_NUMBER,
            to=settings.MANAGER_PHONE_NUMBER,
        )
        logger.info("[NOTIFICATION][SMS] Manager notified")
        return True
    except Exception as exc:
        logger.exception("[NOTIFICATION][SMS] Failed: %s", exc)
        return False


def _followup_text(lead: Lead) -> str:
    if lead.segment == "PARENT":
        return PARENT_FOLLOWUP.format(
            company_name=settings.COMPANY_NAME,
            followup_link=settings.FOLLOWUP_CONTENT_LINK,
        ).strip()

    if lead.segment == "ADULT":
        return ADULT_FOLLOWUP.format(
            company_name=settings.COMPANY_NAME,
            followup_link=settings.FOLLOWUP_CONTENT_LINK,
        ).strip()

    return ERROR_MESSAGE.format().strip()


def _twilio_configured() -> bool:
    return all(
        [
            has_value(settings.TWILIO_ACCOUNT_SID),
            has_value(settings.TWILIO_AUTH_TOKEN),
            has_value(settings.TWILIO_FROM_NUMBER),
            has_value(settings.MANAGER_PHONE_NUMBER),
        ],
    )


def _booking_text(value: bool) -> str:
    return BOOKING_TEXT_YES if value else BOOKING_TEXT_NO
