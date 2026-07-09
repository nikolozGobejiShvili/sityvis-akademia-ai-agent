import asyncio
import logging
import re
from datetime import datetime, timedelta

import httpx
from openai import OpenAI

from app.agent.services.knowledge_loader import load_knowledge
from app.config import settings
from app.services import (
    admin_config_service,
    conversation_service,
    kill_switch,
    messenger_service,
    sheets_service,
)
from data.prompts import (
    ADULT_WELCOME,
    COMMENT_FOLLOWUP_REPLY,
    COMMENT_INTENT_PROMPT,
    COMMENT_REPLY_DM_SENT,
    COMMENT_REPLY_FALLBACK,
    PARENT_WELCOME,
    UNCLEAR_ROUTING,
)

logger = logging.getLogger(__name__)

def _graph_base_url() -> str:
    base = getattr(settings, "META_GRAPH_API_BASE_URL", "https://graph.facebook.com")
    version = getattr(settings, "META_GRAPH_API_VERSION", "v19.0")
    return f"{base}/{version}"

HASHTAG_PATTERN = re.compile(r"#([a-zA-Z0-9_Ⴀ-ჿ]+)")
POST_CACHE_TTL = timedelta(hours=1)
post_content_cache: dict[str, tuple[str, datetime]] = {}


# COMMENT FLOW PATCH 3 — first-contact DM constants.
#
# `PARENT_FIRST_CONTACT_DM` is the SAFE fallback used when
# `_build_parent_rich_dm()` cannot load `camp_2026.yaml`. The rich
# variant is constructed at send time from camp facts so the DM stays
# in sync with the canonical knowledge base.
#
# `ADULT_NO_EVENTS_DM` is the shared admin-config no-active-events copy
# used by ADULT comment runtime paths when there are no active admin events.
PARENT_FIRST_CONTACT_DM = (
    "გამარჯობა. მოხარულები ვართ, რომ დაინტერესდით ბანაკით.\n"
    "დეტალებისთვის მომწერეთ."
)
ADULT_NO_EVENTS_DM = admin_config_service.ADULT_NO_ACTIVE_EVENTS_REPLY


def _normalize_hashtag(tag: str) -> str:
    """Return a hashtag in canonical comparison form.

    Strips the leading '#' if present, trims whitespace (incl. unusual
    NBSP / zero-width characters via .strip()), and case-folds. Safe
    no-op for Georgian Mkhedruli (it has no case). Used on BOTH sides
    of every hashtag match (env value AND extracted from post caption)
    so the comparison can never drift through case / whitespace /
    leading-'#' differences.
    """
    if not tag:
        return ""
    return tag.strip().lstrip("#").strip().casefold()


def _has_adult_events_configured() -> bool:
    """True when settings.EVENTS contains at least one real event block.

    Stricter than just looking for a `სახელი:` line — also requires a
    non-empty value after that label, so a placeholder block like
    "სახელი: " (label only) is correctly classified as "no events yet".
    """
    return len(_parse_events_blocks()) > 0


def _locative_location(location: str) -> str:
    """Convert nominative Georgian location ("ამბასადორი კაჭრეთი") to
    locative ("ამბასადორ კაჭრეთში").

    Duplicated from `parent_turn_router._locative_location` to avoid a
    circular import — comment_service is imported during webhook
    routing which is unrelated to the parent turn router. Identical
    behaviour: drop the final "ი" from every word and append "ში" to
    the last word.
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


def _parse_events_blocks() -> list[dict[str, str]]:
    """Parse `settings.EVENTS` into a list of event dicts.

    Only events with a non-empty `name` are returned. The downstream
    rich-DM builder relies on this to skip empty placeholder blocks
    (`სახელი: ` with no value), so PATCH 3's "no events" fallback fires
    when the events file hasn't been populated yet.

    Each returned dict has: name, date, time, location, price (any
    field may be empty string).
    """
    text = (getattr(settings, "EVENTS", "") or "").strip()
    if not text:
        return []

    blocks: list[dict[str, str]] = []
    current: dict[str, str] | None = None

    def _flush() -> None:
        nonlocal current
        if current and (current.get("name") or "").strip():
            blocks.append(current)
        current = None

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("=== EVENT") and line.endswith("==="):
            _flush()
            current = {
                "name": "", "date": "", "time": "",
                "location": "", "price": "",
            }
            continue
        if not current or ":" not in line:
            continue
        key, _, value = line.partition(":")
        value = value.strip()
        kk = key.strip()
        if kk == "სახელი":
            current["name"] = value
        elif kk == "თარიღი":
            current["date"] = value
        elif kk == "დრო":
            current["time"] = value
        elif kk == "ლოკაცია":
            current["location"] = value
        elif kk == "ფასი":
            current["price"] = value
    _flush()
    return blocks


def _build_parent_rich_dm() -> str:
    """PATCH 3 — PARENT first-contact rich DM.

    Resolution order:
      1. Admin Panel template — `admin_config_service.build_section_dm`
         for the ``summer_camp`` section. Operator-editable, supports
         every placeholder the canonical template uses.
      2. Canonical legacy build — read facts from `camp_2026.yaml` and
         render inline. Preserves byte-identical output for the
         existing live-tested flow when the admin section is missing.
      3. SAFE fallback — `PARENT_FIRST_CONTACT_DM` constant.
    """
    logger.info("[COMMENT] Building rich DM segment=PARENT")
    # (1) Admin Panel template path.
    try:
        section = admin_config_service.get_section("summer_camp")
        if section and section.get("auto_dm_template_id"):
            admin_text = admin_config_service.build_section_dm(section)
            if admin_text:
                logger.info(
                    "[COMMENT] Rich DM rendered from admin_config "
                    "section=summer_camp len=%d", len(admin_text),
                )
                return admin_text
    except Exception as exc:
        logger.warning(
            "[COMMENT] admin_config render failed for summer_camp: %s",
            exc, exc_info=True,
        )
    # (2) Legacy canonical build.
    try:
        camp = load_knowledge("camp_2026")["camp"]
        location = (camp.get("location") or "").strip()
        duration = camp.get("duration_days")
        price = camp.get("price_gel")
        streams = camp.get("streams") or []
        url = (camp.get("registration_url") or "").strip()

        if not (location and duration and price):
            raise ValueError(
                "camp facts incomplete "
                f"(location={location!r} duration={duration!r} price={price!r})"
            )

        location_locative = _locative_location(location)
        # Camp Stream Date Filter — only list streams whose start date has not
        # yet arrived; a started stream is never advertised in the rich DM.
        stream_text = ", ".join(
            (s.get("dates_text") or "").strip()
            for s in admin_config_service.get_visible_camp_streams(
                streams, year=camp.get("year"),
            )
            if isinstance(s, dict) and (s.get("dates_text") or "").strip()
        )

        logger.info(
            "[COMMENT] Camp info loaded from YAML location=%s duration=%s "
            "price=%s streams=%d url=%s",
            location_locative, duration, price, len(streams), bool(url),
        )

        lines: list[str] = [
            "გამარჯობა. მოხარულები ვართ, რომ დაინტერესდით ბანაკით.",
            "",
            (
                f"ბანაკი ტარდება {location_locative}, {duration}-დღიანია. "
                f"ფასი: {price} ლარი."
            ),
        ]
        if stream_text:
            lines.append(f"ნაკადები: {stream_text}.")
        if url:
            lines.extend(["", f"რეგისტრაციის ბმული: {url}"])
        lines.extend([
            "",
            "თუ დამატებითი კითხვები გაქვთ — მომწერეთ და დაგეხმარებით.",
        ])

        message = "\n".join(lines)
        logger.info(
            "[COMMENT] Rich DM built segment=PARENT len=%d", len(message),
        )
        return message
    except Exception as exc:
        logger.warning(
            "[COMMENT] Using fallback DM reason=parent_yaml_load_failed: %s",
            exc, exc_info=True,
        )
        return PARENT_FIRST_CONTACT_DM


# ── Camp-post comment DM (2026-07-04) — comment-aware Summer-Camp reply ──────
# When a comment routes to the Summer-Camp section (via post_id map, caption
# hashtag, or legacy PARENT hashtags), answer the ACTUAL question briefly and
# bridge into the Camp flow with the approved child-age question — instead of
# the generic category-choice menu. Deterministic; reuses parent_flow's approved
# constants/builders (no new user-facing wording, no LLM). Never invents dates
# (date / location reuse the visible-stream-filtered rich DM).
_CAMP_COMMENT_DATE_MARKERS: tuple[str, ...] = ("როდის", "თარიღ", "რიცხვ")
_CAMP_COMMENT_LOCATION_MARKERS: tuple[str, ...] = (
    "სად", "ლოკაცი", "მისამართ", "ტარდება",
)
# An EXPLICIT „give me information / details" request → the approved Camp intro
# (which bridges into the flow with the child-age question). A bare interest
# marker („მაინტერესებს") is NOT here — it keeps the existing rich first-contact
# DM, so current behaviour / tests are preserved.
_CAMP_COMMENT_INFO_MARKERS: tuple[str, ...] = ("ინფორმაცი", "დეტალ")


def _build_camp_comment_dm(comment_text: str) -> str:
    """Return a comment-aware Summer-Camp first-contact DM.

      * price question        → approved price block + child-age bridge
      * date question         → visible-stream rich DM + child-age bridge (never invents)
      * location question     → rich DM (carries the camp location) + child-age bridge
      * explicit info request → approved Camp intro (ends with the child-age question)
      * everything else       → the existing rich first-contact DM (UNCHANGED)

    Falls back to the plain rich DM on any error. Reuses parent_flow's approved
    constants so no new user-facing Georgian wording is introduced here."""
    text = (comment_text or "").strip()
    low = text.lower()
    try:
        from app.flows import parent_flow as _pf
    except Exception:  # pragma: no cover — defensive
        return _build_parent_rich_dm()
    # The approved child-age question that bridges a comment into the Camp flow.
    try:
        bridge = _pf._CAMP_INTRO_TEXT.split("\n\n")[-1].strip()
    except Exception:  # pragma: no cover — defensive
        bridge = ""

    # 1) Price (not payment) → approved price block + bridge.
    try:
        if _pf._is_camp_price_intent(text) and not _pf._is_payment_question(text):
            block = _pf._camp_price_block()
            return f"{block}\n\n{bridge}" if bridge else block
    except Exception:  # pragma: no cover — defensive
        pass

    # 2) Date / 3) Location → rich DM (visible stream dates + location, never
    #    invents) + bridge into the Camp flow.
    if (
        any(m in low for m in _CAMP_COMMENT_DATE_MARKERS)
        or any(m in low for m in _CAMP_COMMENT_LOCATION_MARKERS)
    ):
        rich = _build_parent_rich_dm()
        if rich and rich.strip() and bridge:
            return f"{rich.rstrip()}\n\n{bridge}"
        return rich

    # 4) Explicit „ინფორმაცია / დეტალები" request → approved Camp intro.
    if any(m in low for m in _CAMP_COMMENT_INFO_MARKERS):
        try:
            return _pf._CAMP_INTRO_TEXT
        except Exception:  # pragma: no cover — defensive
            pass

    # 5) Default → the existing rich first-contact DM (behaviour preserved).
    return _build_parent_rich_dm()


def _build_adult_rich_dm() -> str:
    """Build an ADULT first-contact DM from admin-config active events only."""
    logger.info("[COMMENT] Building rich DM segment=ADULT source=admin_config")
    try:
        list_dm = _build_active_adult_events_list_dm()
        if list_dm:
            return list_dm
        return ADULT_NO_EVENTS_DM
    except Exception as exc:
        logger.warning(
            "[COMMENT] Using fallback DM reason=adult_admin_events_failed: %s",
            exc, exc_info=True,
        )
        return ADULT_NO_EVENTS_DM

# Comment → Specific Event Mapping Patch (2026-06-08).
#
# Live-bug fix: the LLM intent classifier was the ONLY interest signal.
# Short, obvious comments like „ფასი?" / „ბმული?" / „სად ტარდება?"
# went through a network round-trip and could be misclassified as
# NOT_INTERESTED on stochastic LLM days. The deterministic keyword
# check below short-circuits the LLM for the closed set of common
# Georgian + English interest / information-request phrases.
_INTEREST_KEYWORDS: tuple[str, ...] = (
    # --- Georgian — interest verbs / nouns
    "მაინტერესებს", "მინდა", "მომწერეთ", "გამოგზავნეთ", "დამილინკეთ",
    "დეტალები", "ინფორმაცია", "ინფო", "სრული ინფორმაცია",
    # --- Georgian — price questions
    "ფასი", "ღირს", "რამდენი ჯდება",
    # --- Georgian — location / time questions
    "სად ტარდება", "სად არის", "სად იქნება", "მისამართი", "ლოკაცია",
    "როდის არის", "როდის ტარდება", "როდის იქნება", "საათზე",
    # --- Georgian — link / registration / ticket questions
    "ბმული", "ლინკი", "რეგისტრაცია", "რეგისტრირდე",
    "ბილეთი", "ბილეთის",
    # --- Georgian — eligibility / conditions
    "ასაკი", "პირობები", "შეიძლება",
    # --- English / mixed — short interest words
    "info", "details", "price", "link", "where", "when",
    "interested", "register", "ticket", "address", "location",
)


def is_interest_intent(comment_text: str) -> bool:
    """Deterministic broad-interest intent check.

    Returns True when the comment text mentions ANY of the closed-set
    interest / information-request keywords in Georgian or English.
    Used by ``handle_comment`` as a pre-LLM shortcut so short obvious
    comments like „ფასი?" / „ბმული?" never need a network round-trip
    to be classified as INTERESTED.

    Conservative on the False side — when the keyword set does NOT
    match, the caller is expected to fall back to the existing LLM
    classifier rather than treat the comment as NOT_INTERESTED.
    """
    if not comment_text:
        return False
    lowered = comment_text.casefold()
    return any(kw in lowered for kw in _INTEREST_KEYWORDS)


def _normalize_for_tag_match(text: str) -> str:
    """Normalize text for adult-event-tag substring comparison.

    Lower-cases (case-fold is a no-op on Georgian), removes the
    leading '#' if present, replaces underscores with spaces so the
    hashtag form „ქართული_პოეზია" can match the comment form
    „ქართული პოეზია" (and vice versa).
    """
    if not text:
        return ""
    return text.replace("_", " ").casefold()


def _tag_matches_text(tag: str, text: str) -> bool:
    """Substring match an event tag against a comment / caption.

    Both sides are normalised via ``_normalize_for_tag_match``. Tags
    shorter than 3 characters are rejected so a single Georgian
    noun-ending can't accidentally match every event title.
    """
    needle = _normalize_for_tag_match(tag).strip().lstrip("#").strip()
    if len(needle) < 3:
        return False
    haystack = _normalize_for_tag_match(text)
    return bool(haystack) and needle in haystack


def _event_match_keys(event: dict) -> list[str]:
    """Return every operator-supplied string an event can be matched on.

    The operator-saved ``tags`` list is the primary signal. The
    ``title`` is folded in as an implicit tag so an event saved
    without explicit tags still surfaces when its full title appears
    in the comment / caption.
    """
    keys: list[str] = []
    raw_tags = event.get("tags") or []
    if isinstance(raw_tags, list):
        for t in raw_tags:
            if isinstance(t, str) and t.strip():
                keys.append(t.strip())
    title = (event.get("title") or "").strip()
    if title:
        keys.append(title)
    return keys


def _events_matching_text(
    events: list[dict], text: str,
) -> list[dict]:
    """Return every event with at least one match-key found in
    ``text``. Order is preserved (operator-saved order in
    sections.yaml). Dedupes by id."""
    seen: set[str] = set()
    matched: list[dict] = []
    for event in events:
        if event.get("id") in seen:
            continue
        for key in _event_match_keys(event):
            if _tag_matches_text(key, text):
                seen.add(event.get("id"))
                matched.append(event)
                break
    return matched


async def resolve_specific_adult_event(
    *,
    comment_text: str,
    post_id: str,
    platform: str,
) -> tuple[dict | None, list[dict], str]:
    """Resolve the specific active adult event a comment is about.

    Returns a 3-tuple ``(event, candidates, reason)``:

      * ``event`` is the chosen event dict when exactly one
        unambiguous match is found, ``None`` otherwise.
      * ``candidates`` is the full match list — useful when
        ``reason == "ambiguous"`` so the caller can ask the user to
        disambiguate, or for telemetry.
      * ``reason`` is one of:
          - ``"facebook_post_id"`` (Priority A — exact match on
            operator-saved ``facebook_post_id``);
          - ``"comment_tag"`` (Priority B — event tag found inside
            the comment text);
          - ``"caption_tag"`` (Priority C — event tag found inside
            the post caption);
          - ``"ambiguous"`` (Priority E — multiple events matched
            via Priority B or C);
          - ``"no_match"`` (Priority D — fall through to generic
            adult flow).

    Inactive events are excluded from every priority. The post-caption
    fetch fails softly: when Meta returns an error or the token is
    missing, ``reason`` falls through to ``"no_match"`` rather than
    raising.
    """
    from app.services import admin_config_service

    try:
        # Adult Event Date Filter (2026-06-10): match against the active
        # pool INCLUDING past events so a reference to a past event is
        # DETECTED (and answered with „this event has ended") rather than
        # silently missed. The `past_event` reason below tells the caller
        # to send the ended-message instead of the bookable specific DM.
        events = admin_config_service.get_active_adult_events(include_past=True)
    except Exception as exc:
        logger.warning(
            "[COMMENT] specific-event resolver: get_active_adult_events "
            "failed: %s", exc,
        )
        return None, [], "no_match"

    if not events:
        return None, [], "no_match"

    def _single(event: dict, matches: list[dict], reason: str):
        """Downgrade a single match to ``past_event`` when the matched
        event is in the past — never offer a finished event as bookable."""
        try:
            if admin_config_service.is_adult_event_past(event):
                return event, matches, "past_event"
        except Exception:
            pass
        return event, matches, reason

    # Priority A — facebook_post_id exact match.
    post_id_clean = (post_id or "").strip()
    if post_id_clean:
        fb_matches = [
            e for e in events
            if (e.get("facebook_post_id") or "").strip() == post_id_clean
        ]
        if fb_matches:
            # Exact id wins even when multiple events somehow share
            # the same post_id — operator misconfig, pick the first.
            return _single(fb_matches[0], fb_matches, "facebook_post_id")

    # Priority B — event tags inside the comment text.
    if comment_text:
        comment_matches = _events_matching_text(events, comment_text)
        if len(comment_matches) == 1:
            return _single(comment_matches[0], comment_matches, "comment_tag")
        if len(comment_matches) > 1:
            return None, comment_matches, "ambiguous"

    # Priority C — event tags inside the post caption.
    caption = ""
    if post_id_clean:
        try:
            caption = await fetch_post_content(post_id_clean, platform)
        except Exception as exc:
            # Soft-fail: caption fetch errors must NEVER block the DM.
            logger.warning(
                "[COMMENT] specific-event resolver: caption fetch failed "
                "post=%s: %s", post_id_clean, exc,
            )
            caption = ""
    if caption:
        caption_matches = _events_matching_text(events, caption)
        if len(caption_matches) == 1:
            return _single(caption_matches[0], caption_matches, "caption_tag")
        if len(caption_matches) > 1:
            return None, caption_matches, "ambiguous"

    # Priority D — no specific match.
    return None, [], "no_match"


def _format_event_price(event: dict) -> str:
    """Render an event's price as the user-facing string.

    Mirrors the ADULT system prompt's price rule:
      1. ``price_text`` non-blank → use as-is; numeric-only gets
         „ ლარი" appended.
      2. ``price_text`` blank but ``price_gel > 0`` → „{N} ლარი".
      3. Both blank → empty string (caller decides whether to render
         a missing-price line).
    """
    price_text = (event.get("price_text") or "").strip()
    if price_text:
        marker_present = (
            "ლარი" in price_text.casefold()
            or "gel" in price_text.casefold()
            or "$" in price_text
            or "€" in price_text
        )
        if marker_present:
            return price_text
        return f"{price_text} ლარი"
    price_gel = event.get("price_gel")
    if isinstance(price_gel, int) and price_gel > 0:
        return f"{price_gel} ლარი"
    return ""


def _build_specific_adult_event_dm(event: dict) -> str:
    """First-contact DM for a SPECIFIC adult event.

    Lays out the operator-saved fields the user is most likely to
    care about (date / location / price / description / link). The
    sold-out branch fires ONLY when the operator explicitly flagged
    ``sold_out: true`` or ``status: sold_out`` — no inferred sold-out
    copy from a blank seats_available. Missing link → manager handoff
    offer (no fabricated availability).

    Returns the assembled text. An event without a title returns ""
    so the caller can fall back to the generic ADULT rich DM.
    """
    title = (event.get("title") or "").strip()
    if not title:
        return ""

    lines: list[str] = [
        f'გამარჯობა. „{title}"-ის შესახებ ინფორმაცია:',
        "",
    ]

    date_text = (event.get("date_text") or "").strip()
    if date_text:
        lines.append(f"📅 თარიღი: {date_text}")
    location = (event.get("location") or "").strip()
    if location:
        lines.append(f"📍 ლოკაცია: {location}")
    price_render = _format_event_price(event)
    if price_render:
        lines.append(f"💰 ფასი: {price_render}")

    description = (event.get("description") or "").strip()
    if description:
        lines.append("")
        lines.append(f"აღწერა: {description}")

    reservation_url = (event.get("reservation_url") or "").strip()
    payment_terms = (event.get("payment_terms") or "").strip()
    link = reservation_url or payment_terms

    if event.get("sold_out"):
        lines.append("")
        lines.append(
            "ამ ღონისძიებაზე ადგილები ამ ეტაპზე ამოწურულია. "
            "თუ გსურთ, დაგაკავშირებთ მენეჯერთან.",
        )
    elif link:
        lines.append("")
        lines.append("ბილეთის ბმული:")
        lines.append(link)
    else:
        lines.append("")
        lines.append(
            "ბილეთის ბმული ამ ეტაპზე არ არის მითითებული. "
            "თუ გსურთ, დაგაკავშირებთ მენეჯერთან.",
        )

    return "\n".join(lines).strip()


def _build_ambiguous_adult_event_dm(candidates: list[dict]) -> str:
    """Multi-match clarification DM. Lists the candidate titles and
    asks the user to choose."""
    titles = [
        (c.get("title") or "").strip()
        for c in candidates
        if (c.get("title") or "").strip()
    ]
    if not titles:
        return ""
    if len(titles) == 1:
        # Shouldn't happen — single match should resolve to a real
        # event — but degrade gracefully.
        return ""
    quoted = ' ან „'.join(titles)
    return (
        "გამარჯობა. რამდენიმე მსგავსი ღონისძიება გვაქვს — "
        f'„{quoted}". რომელი გაინტერესებთ?'
    )


# Adult Event Date Filter (2026-06-10) — ended-event copy. Sent when a
# comment references a PAST adult event; never carries a ticket link.
# Appends the current future catalogue when one exists.
_PAST_EVENT_DM_BASE = (
    "ეს ღონისძიება უკვე დასრულებულია. შემიძლია მიმდინარე/მომდევნო "
    "ღონისძიებები გაგიზიაროთ."
)


def _build_past_event_dm() -> str:
    """Ended-event message. If active FUTURE events exist, append the
    catalogue so the user immediately sees current options."""
    base = _PAST_EVENT_DM_BASE
    try:
        future_list = _build_active_adult_events_list_dm()
    except Exception:
        future_list = ""
    if future_list:
        # Strip the generic greeting opener from the list so the ended
        # message leads; keep only the event lines + footer.
        return f"{base}\n\n{future_list}"
    return base


# Generic Adult Event Comment Patch (2026-06-09).
#
# When a comment is on a post tagged ONLY with the generic adult-event
# hashtag (#event, #ღონისძიება, …) and no specific event matches via
# Priority A (facebook_post_id) / B (tag in comment) / C (tag in
# caption), the previous behaviour fell through to
# ``_build_adult_rich_dm()`` which reads the legacy ``data/events.txt``.
# In production that file is empty and the agent sent the misleading
# „ახლო მომავალში ღონისძიებების განრიგს გამოვაქვეყნებთ…" copy even
# though Admin Panel had active adult events.
#
# The helpers below render the active-adult-events list straight from
# ``admin_config_service.get_active_adult_events()`` — the same source
# of truth the agent uses in the ADULT flow tool surface — and inject
# it into the operator-editable ``adult_events_comment_dm`` template
# via the ``{events_list}`` placeholder.
_ACTIVE_EVENT_LIST_MAX = 5


def _render_event_for_list(event: dict, index: int) -> str:
    """Render a single event entry for the active-events catalogue DM.

    Only operator-configured fields are surfaced — missing values are
    skipped (no „თარიღი: მითითებული არ არის" filler). Numeric
    ``price_text`` is rendered via the same ``_format_event_price``
    helper as the specific-event DM so the price rule stays consistent
    („150" → „150 ლარი"; ``price_gel`` fallback). Sold-out events are
    excluded by the caller (active-events filter already drops them
    when the operator flips status → ``sold_out`` / ``inactive``); a
    bare ``sold_out: true`` on an otherwise-active row still renders
    here, with a short locator line instead of a ticket link.
    """
    title = (event.get("title") or "").strip()
    if not title:
        return ""

    lines: list[str] = [f"{index}. {title}"]

    date_text = (event.get("date_text") or "").strip()
    if date_text:
        lines.append(f"   თარიღი: {date_text}")
    location = (event.get("location") or "").strip()
    if location:
        lines.append(f"   ლოკაცია: {location}")
    price_render = _format_event_price(event)
    if price_render:
        lines.append(f"   ფასი: {price_render}")

    reservation_url = (event.get("reservation_url") or "").strip()
    payment_terms = (event.get("payment_terms") or "").strip()
    link = reservation_url or payment_terms
    if event.get("sold_out"):
        lines.append("   ადგილები ამ ეტაპზე ამოწურულია.")
    elif link:
        lines.append(f"   ბილეთის ბმული: {link}")
    return "\n".join(lines)


def _build_active_events_list_block(events: list[dict]) -> str:
    """Render the active-events list as one multi-line string suitable
    for substitution into the ``{events_list}`` template placeholder.

    Returns "" when there are no titled events to render — the caller
    should fall through to the legacy „no schedule" fallback in that
    case.
    """
    rendered: list[str] = []
    for idx, event in enumerate(events[:_ACTIVE_EVENT_LIST_MAX], start=1):
        text = _render_event_for_list(event, idx)
        if text:
            rendered.append(text)
    return "\n\n".join(rendered)


def _build_active_adult_events_list_dm(
    events: list[dict] | None = None,
) -> str:
    """Build the generic-adult-event-comment DM listing every active
    adult/cultural event.

    Resolution order:
      1. Load the active events via ``admin_config_service`` when not
         supplied by the caller (lets tests inject a frozen list).
      2. Render each event with title / date / location / price / link
         via the per-event helper above.
      3. Try the operator-editable ``adult_events_comment_dm`` admin
         template and substitute ``{events_list}`` for the rendered
         block. If the template is missing OR somehow leaves the
         placeholder behind (no `{events_list}` token), fall back to a
         hard-coded Georgian frame so the DM is never empty.

    Returns "" when there are no active titled events — the caller is
    expected to fall through to the existing „no schedule" fallback in
    that branch (`ADULT_NO_EVENTS_DM`).
    """
    if events is None:
        try:
            events = admin_config_service.get_active_adult_events()
        except Exception as exc:
            logger.warning(
                "[COMMENT] generic-adult-list: get_active_adult_events "
                "failed: %s", exc,
            )
            return ""

    if not events:
        return ""

    events_block = _build_active_events_list_block(events)
    if not events_block:
        return ""

    rendered = ""
    try:
        rendered = admin_config_service.render_template(
            "adult_events_comment_dm",
            {"events_list": events_block},
        )
    except Exception as exc:
        logger.warning(
            "[COMMENT] generic-adult-list: render_template failed: %s",
            exc,
        )
        rendered = ""

    # Defensive guard: never let an unrendered placeholder reach the
    # user, and never let an operator-mangled template silently drop
    # the active-events list. If the template render returned empty,
    # was missing, left a literal "{events_list}" behind, OR somehow
    # produced output that does not contain the events block (e.g. the
    # operator removed the placeholder), fall back to the hard-coded
    # Georgian frame.
    if (
        not rendered
        or "{events_list}" in rendered
        or events_block not in rendered
    ):
        rendered = (
            "გამარჯობა. მოხარულები ვართ, რომ დაინტერესდით ჩვენი "
            "ღონისძიებებით.\n\n"
            "ამჟამად ხელმისაწვდომია:\n\n"
            f"{events_block}\n\n"
            "დამატებითი კითხვებისთვის — მომწერეთ."
        )

    logger.info(
        "[COMMENT] generic-adult-list DM built events_listed=%d len=%d",
        min(len(events), _ACTIVE_EVENT_LIST_MAX), len(rendered),
    )
    return rendered.strip()


def _openai_client() -> OpenAI:
    return OpenAI(api_key=settings.OPENAI_API_KEY)


async def detect_comment_intent(comment_text: str) -> str:
    prompt = COMMENT_INTENT_PROMPT.format(comment_text=comment_text)

    for attempt in range(3):
        try:
            response = await asyncio.to_thread(
                _openai_client().chat.completions.create,
                model=settings.OPENAI_MODEL,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=10,
                temperature=0,
            )
            content = (response.choices[0].message.content or "").strip().upper()
            if "INTERESTED" in content and "NOT" not in content:
                return "INTERESTED"
            if "NOT_INTERESTED" in content or "NOT INTERESTED" in content:
                return "NOT_INTERESTED"
            return "NOT_INTERESTED"
        except Exception as exc:
            logger.warning("[COMMENT] Intent detection attempt %s failed: %s", attempt + 1, exc)
            if attempt < 2:
                await asyncio.sleep(1)

    logger.error("[COMMENT] Intent detection failed after 3 attempts — defaulting to NOT_INTERESTED")
    return "NOT_INTERESTED"


async def reply_to_comment(
    comment_id: str,
    user_name: str,
    can_send_dm: bool,
) -> bool:
    # COMMENT FLOW PATCH 3 — the public reply text is now uniform for
    # both PARENT and ADULT segments and for senders with or without
    # DM history. The dm-sent template ("გამარჯობა 🌿 დეტალები
    # პირად შეტყობინებაში გამოგიგზავნეთ.") no longer has a `{name}`
    # placeholder, so .format(name=…) is a no-op. `user_name` and
    # `can_send_dm` are kept in the signature for caller backwards
    # compatibility — see webhook.handle_comment which still passes
    # them — but no longer affect the rendered text.
    _ = can_send_dm  # explicit acknowledgement that the flag is unused
    message = COMMENT_REPLY_DM_SENT.format(name=user_name).strip()

    url = f"{_graph_base_url()}/{comment_id}/replies"
    headers = {"Authorization": f"Bearer {settings.META_ACCESS_TOKEN}"}
    body = {"message": message}

    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.post(url, headers=headers, json=body)
            if response.is_success:
                logger.info("[COMMENT] Reply sent on %s: %s", comment_id, message[:60])
                print(f"[COMMENT REPLY] {comment_id}: {message[:60]}")
                return True
            logger.warning(
                "[COMMENT] Reply attempt %s failed (status %s): %s",
                attempt + 1,
                response.status_code,
                response.text[:200],
            )
        except Exception as exc:
            logger.warning("[COMMENT] Reply attempt %s exception: %s", attempt + 1, exc)

        if attempt < 2:
            await asyncio.sleep(2)

    logger.error("[COMMENT] Reply failed after 3 attempts on %s", comment_id)
    return False


def extract_hashtags(text: str) -> list[str]:
    """Return a list of hashtags from `text` in canonical comparison
    form (see `_normalize_hashtag`). The leading '#' is stripped by
    the regex's capture group; the helper additionally case-folds and
    trims any odd whitespace so the result matches the env list
    byte-for-byte."""
    if not text:
        return []
    return [_normalize_hashtag(tag) for tag in HASHTAG_PATTERN.findall(text)]


# ── Post-content fetch fields (2026-07-04) ──────────────────────────────────
# Platform-correct Graph fields for the caption/message fetch. Facebook Page
# posts carry the operator's caption (with the routing hashtags) in `message`;
# a small minority (shares / system stories) only have `story`. Instagram media
# carry it in `caption`. Requesting an Instagram-only field on a Facebook node
# (or vice-versa) is a hard „(#100) nonexisting field" 400 — so the field list
# is platform-specific, and the secondary field is tried ONLY when the primary
# request FAILS (never a combined `fields=message,story` list, which would 400
# the whole call when one field is invalid for the node type).
_POST_CONTENT_FIELDS: dict[str, tuple[str, ...]] = {
    "instagram": ("caption",),
    "facebook": ("message", "story"),
    "messenger": ("message", "story"),
}
_DEFAULT_POST_CONTENT_FIELDS: tuple[str, ...] = ("message", "story")

# Redact any `access_token=…` occurrence before a Meta error string is logged.
_ACCESS_TOKEN_RE = re.compile(r"access_token=[^&\s\"']+", re.IGNORECASE)


def _post_content_fields(platform: str) -> tuple[str, ...]:
    """Ordered Graph field candidates for the caption/message fetch, per
    platform. Unknown platforms default to the Facebook shape (`message` →
    `story`)."""
    return _POST_CONTENT_FIELDS.get(
        (platform or "").strip().lower(), _DEFAULT_POST_CONTENT_FIELDS,
    )


def _redact_access_token(text: str) -> str:
    """Strip any `access_token=<value>` substring before it is logged."""
    if not text:
        return ""
    return _ACCESS_TOKEN_RE.sub("access_token=<redacted>", text)


def _meta_error_summary(response) -> str:
    """Return a privacy-safe one-line summary of a Meta Graph error body.

    Surfaces the diagnostic fields (`error.code` / `error.error_subcode` /
    `error.type` / `error.fbtrace_id`) plus a token-scrubbed, truncated
    message so a production 400 is diagnosable (permission vs
    nonexisting-field vs invalid-token) — WITHOUT ever logging the access
    token or the raw request URL. Returns "" when the body is not a parseable
    Meta error (the raw text is NEVER logged, since Graph error payloads can
    echo the request URL, which carries the token)."""
    try:
        data = response.json()
    except Exception:
        return ""
    err = data.get("error") if isinstance(data, dict) else None
    if not isinstance(err, dict):
        return ""
    msg = str(err.get("message") or "")
    # Belt-and-braces: scrub both the `access_token=` pattern AND the literal
    # configured token value, so the token can never surface even if Meta ever
    # echoes it back verbatim.
    token = getattr(settings, "META_ACCESS_TOKEN", "") or ""
    if token:
        msg = msg.replace(token, "<redacted>")
    msg = _redact_access_token(msg)[:200]
    return (
        f"code={err.get('code')} subcode={err.get('error_subcode')} "
        f"type={err.get('type')!r} fbtrace_id={err.get('fbtrace_id')!r} "
        f"message={msg!r}"
    )


async def fetch_post_content(post_id: str, platform: str) -> str:
    """Fetch a post's caption / message text via the Meta Graph API.

    Uses platform-correct fields (Instagram → ``caption``; Facebook Page →
    ``message`` with a ``story`` safe fallback). When the primary field
    request FAILS (non-2xx / network error) the next candidate field is tried
    before giving up, so a single bad field request no longer collapses
    hashtag routing to UNCLEAR.

    Soft-fail contract (unchanged):
      * any failure → returns "" so the caller falls back to comment-text /
        post_id-map / generic routing. Never raises.
      * Never logs the access token, params dict, or raw response URL. Meta
        error bodies are surfaced ONLY through the token-scrubbed
        ``_meta_error_summary`` (code / subcode / type / fbtrace_id / message).

    Caching: a reachable-API result (2xx — even an empty caption) is cached so
    a genuinely caption-less post is not re-fetched every comment. A fully
    failed fetch (every field non-2xx / errored) is NOT cached, so hashtag
    routing recovers on the very next comment the moment a token / permission
    issue is fixed on the Meta side.
    """
    cached = post_content_cache.get(post_id)
    if cached:
        content, ts = cached
        if datetime.utcnow() - ts < POST_CACHE_TTL:
            return content

    url = f"{_graph_base_url()}/{post_id}"
    fields = _post_content_fields(platform)
    api_reachable = False

    for field_name in fields:
        params = {
            "fields": field_name,
            "access_token": settings.META_ACCESS_TOKEN,
        }
        for attempt in range(2):
            try:
                async with httpx.AsyncClient(timeout=15) as client:
                    response = await client.get(url, params=params)
            except Exception as exc:
                # Suppress exception args — httpx may carry the redacted URL
                # (with the token) in the message; log only the exception type.
                logger.warning(
                    "[COMMENT] fetch_post_content post=%s platform=%s field=%s "
                    "attempt=%s error_type=%s (soft-fail)",
                    post_id, platform, field_name, attempt + 1,
                    type(exc).__name__,
                )
                if attempt < 1:
                    await asyncio.sleep(1)
                continue

            if response.is_success:
                api_reachable = True
                try:
                    data = response.json()
                except Exception:
                    data = {}
                content = (
                    data.get(field_name) if isinstance(data, dict) else ""
                ) or ""
                if content:
                    post_content_cache[post_id] = (content, datetime.utcnow())
                    logger.info(
                        "[COMMENT] fetch_post_content ok post=%s platform=%s "
                        "field=%s len=%d",
                        post_id, platform, field_name, len(content),
                    )
                    return content
                # 2xx but this field is empty — no text here. Try the next
                # candidate field (if any) instead of retrying the same one.
                logger.info(
                    "[COMMENT] fetch_post_content empty post=%s platform=%s "
                    "field=%s (trying next field if any)",
                    post_id, platform, field_name,
                )
                break

            # Non-2xx — log a token-safe Meta error summary for diagnosis
            # (surfaces whether it is a permission / field / token error).
            logger.warning(
                "[COMMENT] fetch_post_content post=%s platform=%s field=%s "
                "attempt=%s status=%s error=%s (soft-fail)",
                post_id, platform, field_name, attempt + 1,
                response.status_code, _meta_error_summary(response),
            )
            if attempt < 1:
                await asyncio.sleep(1)

    # All candidate fields exhausted.
    if api_reachable:
        # API was reachable but no field carried text — cache the definitive
        # empty so a caption-less post is not re-fetched on every comment.
        post_content_cache[post_id] = ("", datetime.utcnow())
    else:
        # Every field request failed (permission / token / transient). Do NOT
        # cache, so routing recovers automatically on the next comment.
        logger.warning(
            "[COMMENT] fetch_post_content post=%s platform=%s ALL fields failed "
            "fields=%s — hashtag routing will fall back (post_id map / UNCLEAR)",
            post_id, platform, list(fields),
        )
    return ""


def _segment_from_section(section: dict | None) -> str:
    """Map an admin_config section.type onto the legacy PARENT/ADULT/UNCLEAR
    segment vocabulary the rest of the codebase uses for flow routing."""
    if not section:
        return "UNCLEAR"
    section_type = (section.get("type") or "").strip().lower()
    if section_type in {"camp", "kids_program"}:
        return "PARENT"
    if section_type in {"adult_events"}:
        return "ADULT"
    # Unknown new-section types fall through to UNCLEAR so the legacy
    # routing menu shows up; the comment DM still uses the section's
    # template because that path goes through resolve_section_from_post.
    return "UNCLEAR"


async def resolve_section_from_post(
    post_id: str, platform: str,
) -> dict | None:
    """Admin-Panel-aware section resolver — primary routing path.

    Reads the post caption, extracts hashtags, and matches against the
    admin_config sections list. Returns the matched section dict, or
    None when no configured tag is present. Comment-text fallback is
    NOT consulted here — callers route to the legacy
    `determine_segment_from_post` for that path.
    """
    # (2026-07-04, ADDITIVE) Section-level post_id → section mapping. Consulted
    # BEFORE the Meta caption fetch so a comment under a mapped Camp / SS / Adult
    # post routes correctly even when `fetch_post_content` fails or the caption
    # carries no literal „#" hashtag. Falls through to the UNCHANGED caption-
    # hashtag path below when no post_id mapping exists — hashtag routing is
    # untouched.
    try:
        mapped = admin_config_service.find_section_from_post_id(post_id)
    except Exception as exc:
        mapped = None
        logger.warning(
            "[COMMENT] find_section_from_post_id failed for post=%s: %s",
            post_id, exc,
        )
    if mapped is not None:
        logger.info(
            "[COMMENT] Post %s → admin_section=%s status=%s via post_id map",
            post_id, mapped.get("id"), mapped.get("status"),
        )
        return mapped

    content = await fetch_post_content(post_id, platform)
    hashtags = extract_hashtags(content)
    try:
        section = admin_config_service.find_section_from_post_hashtags(hashtags)
    except Exception as exc:
        logger.warning(
            "[HASHTAG] admin_config lookup failed for post=%s: %s",
            post_id, exc,
        )
        return None
    if section:
        logger.info(
            "[HASHTAG] Post %s hashtags=%s → admin_section=%s status=%s",
            post_id, hashtags, section.get("id"), section.get("status"),
        )
    return section


async def determine_segment_from_post(post_id: str, platform: str) -> str:
    """Return PARENT / ADULT / UNCLEAR based on POST hashtags.

    Resolution order:
      1. admin_config sections (operator-editable, primary).
      2. legacy `settings.PARENT_HASHTAGS` / `settings.ADULT_HASHTAGS`
         (preserved so deployments without admin_config still route
         correctly).
    """
    # (1) Admin Panel sections — primary, operator-editable.
    section = await resolve_section_from_post(post_id, platform)
    if section is not None:
        segment = _segment_from_section(section)
        if segment != "UNCLEAR":
            logger.info(
                "[HASHTAG] Post %s → admin_section=%s segment=%s",
                post_id, section.get("id"), segment,
            )
            return segment

    # (2) Legacy env-list fallback.
    content = await fetch_post_content(post_id, platform)
    hashtags = extract_hashtags(content)

    # Normalize BOTH sides identically — see `_normalize_hashtag`. The
    # env-loader already case-folds and trims; re-applying is cheap
    # and protects us against a `Settings` object built by something
    # other than `from_env()` (e.g. a test mock that passes raw
    # strings).
    parent_tags = {
        _normalize_hashtag(tag) for tag in (settings.PARENT_HASHTAGS or [])
    }
    adult_tags = {
        _normalize_hashtag(tag) for tag in (settings.ADULT_HASHTAGS or [])
    }

    found_parent = [tag for tag in hashtags if tag in parent_tags]
    found_adult = [tag for tag in hashtags if tag in adult_tags]

    if found_parent:
        segment = "PARENT"
    elif found_adult:
        segment = "ADULT"
    else:
        segment = "UNCLEAR"

    logger.info(
        "[HASHTAG] Post %s hashtags=%s parent_tags=%s adult_tags=%s "
        "matched_parent=%s matched_adult=%s → Segment: %s",
        post_id, hashtags, sorted(parent_tags), sorted(adult_tags),
        found_parent, found_adult, segment,
    )
    print(f"[HASHTAG] Post {post_id} hashtags: {hashtags} → Segment: {segment}")
    return segment


# ── Sunday School comment DM (2026-07-02) — Camp-DM leak fix ─────────────────
# A comment on a Sunday-School post must NEVER receive the Summer-Camp rich DM.
# SS sections carry `type=kids_program`, which previously fell into the shared
# camp/kids_program branch of `send_dm_from_comment` → `_build_parent_rich_dm()`
# (hardcoded summer_camp). These status-aware, SS-specific strings carry NO camp
# price / registration link / stream dates. Deterministic (mirrors the chat
# Sunday-School handoff wording in `parent_flow`); NOT sales copy.
_SS_COMMENT_COMING_SOON = (
    "საკვირაო სკოლის დეტალები ჯერ ზუსტდება. თუ გსურთ, მენეჯერთან დაგაკავშირებთ."
)
_SS_COMMENT_INACTIVE = (
    "საკვირაო სკოლა ამ ეტაპზე აქტიური არ არის. თუ გსურთ, მენეჯერთან დაგაკავშირებთ."
)
_SS_COMMENT_FULL = (
    "საკვირაო სკოლაზე ადგილები ამ ეტაპზე შევსებულია. თუ გსურთ, მენეჯერთან "
    "დაგაკავშირებთ."
)
_SS_COMMENT_ACTIVE_HANDOFF = (
    "საკვირაო სკოლით დაინტერესებისთვის მადლობა. დეტალებს მენეჯერი გაგაცნობთ — "
    "თუ გსურთ, დაგაკავშირებთ."
)


def _is_sunday_school_section(section: dict | None) -> bool:
    """True when the resolved comment section is the Sunday-School program.

    Detected by id / lead_type / auto_dm_template_id so it is independent of the
    shared ``kids_program`` type (which previously grouped Sunday School with the
    camp DM branch). Camp (`id=summer_camp`, `type=camp`) never matches.
    """
    if not section:
        return False
    sid = (section.get("id") or "").strip().lower()
    lead_type = (section.get("lead_type") or "").strip().lower()
    tmpl = (section.get("auto_dm_template_id") or "").strip().lower()
    return (
        sid == "sunday_school"
        or lead_type == "sunday_school"
        or "sunday_school" in tmpl
    )


def _build_ss_active_comment_dm(section: dict | None) -> str:
    """Active Sunday-School comment DM built ONLY from populated operator fields
    (never invented), always ending with a safe manager-handoff offer. Empty
    fields are skipped so no blank „ფასი: " labels appear. Never Camp content."""
    section = section or {}

    def _f(key: str) -> str:
        v = section.get(key)
        return v.strip() if isinstance(v, str) else ""

    parts: list[str] = []
    desc = _f("description_short")
    if desc:
        parts.append(desc)
    facts: list[str] = []
    if _f("price_text"):
        facts.append(f"ფასი: {_f('price_text')}")
    if _f("schedule_text"):
        facts.append(f"გრაფიკი: {_f('schedule_text')}")
    if _f("location"):
        facts.append(f"ლოკაცია: {_f('location')}")
    if facts:
        parts.append("\n".join(facts))
    if _f("registration_url"):
        parts.append(f"რეგისტრაციის ბმული: {_f('registration_url')}")
    parts.append(_SS_COMMENT_ACTIVE_HANDOFF)
    return "\n\n".join(parts)


def _build_sunday_school_comment_dm(section: dict | None) -> str:
    """Status-aware Sunday-School comment DM. NEVER returns Camp content.

    coming_soon → details-being-clarified + manager offer.
    hidden / ended → inactive + manager offer.
    full → seats-filled + manager offer.
    active → operator-provided SS fields (populated only) + safe handoff.
    any other / unknown / unreadable status → safe SS manager-handoff (fail-safe).
    """
    try:
        status = (
            (admin_config_service.get_sunday_school_status() or {}).get("status")
            or "coming_soon"
        )
    except Exception:  # pragma: no cover — defensive: never fall through to camp
        status = "coming_soon"
    status = str(status).strip().lower()
    if status == "coming_soon":
        return _SS_COMMENT_COMING_SOON
    if status in {"hidden", "ended"}:
        return _SS_COMMENT_INACTIVE
    if status == "full":
        return _SS_COMMENT_FULL
    if status == "active":
        return _build_ss_active_comment_dm(section)
    return _SS_COMMENT_ACTIVE_HANDOFF


async def send_dm_from_comment(
    sender_id: str,
    platform: str,
    post_id: str,
    segment: str | None = None,
    *,
    comment_id: str | None = None,
    comment_text: str = "",
) -> bool:
    """Send the first-contact DM in response to a public comment.

    COMMENT FLOW PATCH 2 — when the comment came from a Facebook /
    Instagram post (the only two surfaces we currently subscribe to)
    AND we have a comment_id, route the message through
    ``messenger_service.send_private_reply``. This is Meta's
    documented path for "DM after a public comment" and replaces the
    earlier broken ``send_message(platform="facebook", ...)`` call
    that hit the unsupported-platform branch.

    `comment_id` is keyword-only so existing callers (none in
    production today, but the test mocks call this directly) keep
    working with their old signature; they will exercise the legacy
    ``send_message`` path until they pass `comment_id=`.
    """
    if segment is None:
        segment = await determine_segment_from_post(post_id, platform)

    conversation = conversation_service.conversations.get(sender_id)
    if conversation is None:
        from app.models.conversation import Conversation

        conversation = Conversation(sender_id=sender_id, platform=platform)
        conversation_service.conversations[sender_id] = conversation

    conversation.segment = segment
    conversation.state = "START"
    conversation.last_activity = datetime.utcnow()

    # Admin Panel MVP — resolve the post-hashtag section first so an
    # arbitrary new section (e.g. "sunday_school") can ship its own
    # operator-edited DM template without touching Python. When the
    # section maps onto the legacy PARENT/ADULT segments we still
    # delegate to the existing rich-DM builders, which themselves now
    # try the admin_config template before their canonical-YAML path.
    admin_section = None
    try:
        admin_section = await resolve_section_from_post(post_id, platform)
    except Exception as exc:
        logger.warning(
            "[COMMENT] resolve_section_from_post failed: %s", exc,
            exc_info=True,
        )

    message: str = ""
    # Comment → Specific Event Mapping Patch (2026-06-08).
    # When the segment routes through ADULT, try to identify the
    # SPECIFIC event the comment is about before falling back to the
    # generic catalogue DM. Priority A (facebook_post_id) → B (event
    # tag in comment) → C (event tag in post caption) → D (none).
    # Priority E (ambiguous match) emits a short clarification DM
    # instead of silently picking one event.
    if segment == "ADULT":
        try:
            (specific, candidates, match_reason) = (
                await resolve_specific_adult_event(
                    comment_text=comment_text,
                    post_id=post_id,
                    platform=platform,
                )
            )
        except Exception as exc:
            logger.warning(
                "[COMMENT] specific-event resolver raised: %s", exc,
                exc_info=True,
            )
            specific, candidates, match_reason = None, [], "no_match"
        if match_reason == "past_event" and specific is not None:
            # Adult Event Date Filter (2026-06-10): the comment references
            # a PAST event. Never send its ticket link as if bookable —
            # send the ended-event message + the current future catalogue
            # when one exists.
            logger.info(
                "[COMMENT] specific-event PAST segment=ADULT event_id=%s",
                specific.get("id"),
            )
            message = _build_past_event_dm()
        elif specific is not None:
            specific_dm = _build_specific_adult_event_dm(specific)
            if specific_dm:
                logger.info(
                    "[COMMENT] specific-event DM segment=ADULT event_id=%s "
                    "reason=%s",
                    specific.get("id"), match_reason,
                )
                message = specific_dm
        elif match_reason == "ambiguous" and candidates:
            ambig_dm = _build_ambiguous_adult_event_dm(candidates)
            if ambig_dm:
                logger.info(
                    "[COMMENT] specific-event ambiguous segment=ADULT "
                    "candidate_count=%d", len(candidates),
                )
                message = ambig_dm

    if admin_section and not message:
        section_type = (admin_section.get("type") or "").strip().lower()
        if _is_sunday_school_section(admin_section):
            # Sunday School leak fix (2026-07-02): SS posts are `type=kids_program`
            # and previously fell into the camp/kids_program branch below, sending
            # the Summer-Camp rich DM. Route SS to its own status-aware DM builder
            # (never Camp content). Camp (`type=camp`) is unaffected.
            message = _build_sunday_school_comment_dm(admin_section)
        elif section_type in {"camp", "kids_program"} and segment == "PARENT":
            # Existing PARENT path covers summer_camp via admin_config. Send a
            # comment-aware Camp DM (price / dates / location / intro) that
            # bridges into the Camp flow, instead of the generic category menu
            # (2026-07-04). Sunday School (kids_program) is already handled by
            # the `_is_sunday_school_section` branch ABOVE, so this only reaches
            # the actual Summer-Camp section.
            message = _build_camp_comment_dm(comment_text)
        elif section_type == "adult_events" and segment == "ADULT":
            # Generic Adult Event Comment Patch (2026-06-09).
            # Adult-event runtime uses admin_config_service active events only.
            # If no active admin events exist, return the shared no-active copy.
            list_dm = _build_active_adult_events_list_dm()
            message = list_dm or ADULT_NO_EVENTS_DM
        else:
            # New / unknown section type → render the section's own
            # template directly. This is the operator-extension path.
            try:
                message = admin_config_service.build_section_dm(admin_section)
            except Exception as exc:
                logger.warning(
                    "[COMMENT] admin section build_section_dm failed for %s: %s",
                    admin_section.get("id"), exc, exc_info=True,
                )

    if not message:
        # COMMENT FLOW PATCH 3 fallback: PARENT uses canonical camp knowledge;
        # ADULT uses admin_config_service active events only. Both have safe
        # fallbacks (`PARENT_FIRST_CONTACT_DM` / `ADULT_NO_EVENTS_DM`). The
        # UNCLEAR path keeps the existing two-segment routing menu.
        if segment == "PARENT":
            # Comment-aware Camp DM for a PARENT comment resolved via the legacy
            # hashtag fallback (no admin section) — bridge into the Camp flow
            # instead of the category menu (2026-07-04).
            message = _build_camp_comment_dm(comment_text)
        elif segment == "ADULT":
            # Generic Adult Event Comment Patch (2026-06-09) — mirror
            # of the admin-section branch above so a generic `#event`
            # comment routed via the legacy hashtag fallback (no admin
            # section resolved) still surfaces the active-events list
            # when one exists.
            list_dm = _build_active_adult_events_list_dm()
            message = list_dm or ADULT_NO_EVENTS_DM
        else:
            message = UNCLEAR_ROUTING.format(company_name=settings.COMPANY_NAME).strip()

    # PATCH 2 — choose the outbound channel.
    use_private_reply = (
        bool(comment_id) and platform in {"facebook", "instagram"}
    )
    channel = "messenger_private_reply" if use_private_reply else f"send_message:{platform}"

    if use_private_reply:
        logger.info(
            "[COMMENT] Sending via messenger_private_reply comment_id=%s",
            comment_id,
        )
        send_callable = messenger_service.send_private_reply
        sent = await asyncio.to_thread(send_callable, comment_id, message)
    else:
        sent = await asyncio.to_thread(
            messenger_service.send_message, sender_id, platform, message,
        )

    if sent:
        conversation.history.append({"role": "assistant", "content": message})
        # Follow-up Test Mode Patch (2026-06-06) — Part 3/4. Stamp
        # `last_bot_message_at` so the follow-up scheduler treats this
        # comment-originated DM the same as any organic Messenger DM.
        # Without this stamp the scheduler's `_parse_last_bot_message_at`
        # returns None and the conversation is silently skipped. The
        # marker is private DM only — public comment replies never get
        # follow-up (the scheduler only sends via messenger_service).
        try:
            conversation.last_bot_message_at = datetime.utcnow().isoformat()
            # Privacy-safe log: mask sender, no message body.
            from app.services import sentry_service
            logger.info(
                "[FOLLOWUP] marker_created channel=comment_dm "
                "sender=%s stage=initial segment=%s",
                sentry_service.mask_sender(sender_id), segment,
            )
        except Exception as exc:
            logger.warning(
                "[FOLLOWUP] marker write-through failed (comment_dm) "
                "sender=%s: %s",
                sender_id, exc,
            )
        # Mirror the live-message path: write conversation through to
        # Redis so the scheduler picks it up after a restart.
        try:
            conversation_service._save_conversation_to_redis(conversation)
        except Exception as exc:
            logger.warning(
                "[FOLLOWUP] redis write-through (comment_dm) failed: %s",
                exc,
            )
        logger.info(
            "[COMMENT] DM/private reply sent comment_id=%s sender=%s "
            "channel=%s segment=%s text=%r",
            comment_id, sender_id, channel, segment, message[:80],
        )
        return True

    logger.error(
        "[COMMENT] DM/private reply FAILED comment_id=%s sender=%s "
        "channel=%s segment=%s",
        comment_id, sender_id, channel, segment,
    )
    return False


# Comment Follow-up Logic Fix (2026-05-31).
# Statuses written by THIS scheduler:
#   - "FollowupSent": Meta accepted the reply, row terminal.
#   - "Expired":      Meta returned HTTP 400 — comment deleted,
#                     permission missing, or any other non-retryable
#                     error. Row terminal; the processed-comment
#                     guard keeps the row out of subsequent ticks.
#
# DM-follow-up blocked reasons that mean "this sender already
# replied / asked to be left alone" — when an active Conversation
# is in one of these states, the comment scheduler skips and lets
# DM follow-up own the cadence.
_DM_FOLLOWUP_OWNED_REASONS: frozenset[str] = frozenset({
    "declined",
    "asked_no_more_messages",
    "manager_handoff_completed",
    "booked",
    "registered",
    "followup_exhausted",
})


def _has_active_conversation(sender_id: str) -> bool:
    """True iff the comment sender already has an in-memory
    Conversation. When true, DM follow-up is the right channel to
    own re-engagement — comment follow-up MUST stay silent so the
    user isn't pinged twice across two different surfaces.
    """
    if not sender_id:
        return False
    return sender_id in conversation_service.conversations


def _mark_comment_expired(comment_id: str) -> None:
    """Mark a comment_id as permanently expired so future scheduler
    ticks skip it. Reuses the duplicate-comment guard from the
    webhook (in-process LRU + Redis `processed_comment:<id>` key
    when Redis is enabled). No new persistence layer is introduced.
    """
    if not comment_id:
        return
    # Local in-process LRU — survives the current process; matches
    # the existing duplicate-webhook short-circuit in
    # webhook.handle_comment.
    try:
        from app.routes import webhook
        webhook._mark_comment_processed_local(comment_id)
    except Exception:
        # Webhook module might not be importable in odd test rigs;
        # never block the mark.
        pass
    # Redis — persistent across restart. Re-uses the same key
    # format the webhook duplicate guard writes (`processed_comment:`).
    try:
        from app.services import redis_state_service
        if redis_state_service.is_enabled():
            # Dedup guard — expire on the rolling session window (8-day
            # default). Positional TTL for mock-compat.
            redis_state_service.set_json(
                f"processed_comment:{comment_id}",
                {
                    "comment_id": comment_id,
                    "marked_by": "comment_followup_scheduler",
                    "reason": "expired_or_unrecoverable",
                },
                redis_state_service.conversation_ttl_seconds(),
            )
    except Exception as exc:
        logger.warning(
            "[COMMENT] expired-guard redis write failed comment_id=%s: %s",
            comment_id, exc,
        )


async def check_comment_followups() -> None:
    # Emergency Kill Switch — must skip the comment-followup tick when
    # the agent is disabled. Same canonical gate every other entry
    # point uses; no Sheets read, no public reply, no Sheets status
    # update fires when AGENT_ENABLED=false.
    if not kill_switch.is_agent_enabled():
        kill_switch.log_disabled_skip(context="comment_followup_scheduler")
        return

    pending = sheets_service.get_pending_comment_followups()
    logger.info("[COMMENT] Pending follow-ups: %s", len(pending))

    for item in pending:
        comment_id = item.get("comment_id")
        sender_id = item.get("sender_id") or ""
        user_name = item.get("user_name", "")

        # Sender already in DM → DM follow-up owns the cadence; the
        # comment scheduler must NOT also ping them.
        if _has_active_conversation(sender_id):
            conv = conversation_service.conversations.get(sender_id)
            blocked = getattr(conv, "followup_blocked_reason", "") or ""
            extra = ""
            if blocked in _DM_FOLLOWUP_OWNED_REASONS:
                extra = f" blocked_reason={blocked}"
            logger.info(
                "[COMMENT] follow-up skipped: sender has active conversation "
                "sender=%s comment_id=%s%s",
                kill_switch.mask_sender(sender_id), comment_id, extra,
            )
            continue

        message = COMMENT_FOLLOWUP_REPLY.format(
            name=user_name,
            fallback_link=settings.COMMENT_FALLBACK_LINK,
        ).strip()

        url = f"{_graph_base_url()}/{comment_id}/replies"
        headers = {"Authorization": f"Bearer {settings.META_ACCESS_TOKEN}"}
        body = {"message": message}

        success = False
        permanent_failure = False
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=15) as client:
                    response = await client.post(url, headers=headers, json=body)
                if response.is_success:
                    success = True
                    break
                status_code = response.status_code
                # Truncate body to avoid logging large payloads, and
                # the Meta error body never contains the Page token —
                # it's masked server-side. We log a short prefix only.
                raw_text = ""
                try:
                    raw_text = (response.text or "")[:200]
                except Exception:
                    raw_text = ""
                if status_code == 400:
                    # Comment Follow-up Logic Fix: HTTP 400 is
                    # non-retryable (deleted comment, missing
                    # permission, malformed body). Log ONCE, mark
                    # the row Expired, and prime the processed
                    # guard so the same id is skipped on the next
                    # scheduler tick.
                    logger.warning(
                        "[COMMENT] Follow-up permanently skipped (status 400) "
                        "comment_id=%s body=%r",
                        comment_id, raw_text,
                    )
                    permanent_failure = True
                    break
                # Anything else (429, 500, 502, 503, transient
                # network errors) keeps the existing 3-attempt retry
                # with 2-second backoff.
                logger.warning(
                    "[COMMENT] Follow-up attempt %s failed (status %s)",
                    attempt + 1,
                    status_code,
                )
            except Exception as exc:
                logger.warning("[COMMENT] Follow-up attempt %s exception: %s", attempt + 1, exc)

            if attempt < 2:
                await asyncio.sleep(2)

        if permanent_failure:
            sheets_service.update_comment(comment_id, {"status": "Expired"})
            _mark_comment_expired(comment_id)
            continue

        if not success:
            logger.error("[COMMENT] Follow-up failed on %s", comment_id)
            continue

        # Success — terminal status mapped by sheets_service.UPDATE
        # COLUMNS to the Status column.
        sheets_service.update_comment(comment_id, {"status": "FollowupSent"})
        logger.info(
            "[COMMENT] Follow-up sent comment_id=%s sender=%s",
            comment_id, kill_switch.mask_sender(sender_id),
        )


def _format_events_list(events_text: str) -> str:
    lines: list[str] = []
    counter = 0
    name: str | None = None
    date: str | None = None
    topic: str | None = None
    guests: str | None = None

    def flush() -> None:
        nonlocal counter, name, date, topic, guests
        if name:
            counter += 1
            parts = [f"{counter}. {name}"]
            if date:
                parts.append(f"თარიღი: {date}")
            if topic:
                parts.append(f"თემა: {topic}")
            if guests:
                parts.append(f"სტუმარი: {guests}")
            lines.append("\n".join(parts))
        name = date = topic = guests = None

    for raw_line in events_text.splitlines():
        line = raw_line.strip()
        if line.startswith("===") and line.endswith("==="):
            flush()
            continue
        if line.startswith("სახელი:"):
            name = line.split(":", 1)[1].strip()
        elif line.startswith("თემა:"):
            topic = line.split(":", 1)[1].strip()
        elif line.startswith("თარიღი:"):
            date = line.split(":", 1)[1].strip()
        elif line.startswith("მოწვეული სტუმრები:"):
            guests = line.split(":", 1)[1].strip()

    flush()
    return "\n\n".join(lines) if lines else events_text.strip()
