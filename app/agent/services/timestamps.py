"""Shared timestamp helpers — single source for "what timezone does this
datetime mean when we write it out".

P2 task:

  * Internal Python timestamps from `datetime.utcnow()` are *naive UTC*
    by convention (the value is correct in UTC, but `tzinfo` is None).
  * Calendar events are already TZ-aware in Asia/Tbilisi — handled by
    `calendar_service`. They MUST stay as-is.
  * Google Sheets reads ISO strings as local time of the user's
    spreadsheet. If we ship a naive UTC string ("2026-05-22T14:48:51")
    the sheet displays 14:48 (4 hours off). If we ship an explicit-offset
    string ("2026-05-22T18:48:51+04:00") the sheet stores the local
    Tbilisi time correctly.

This module is the canonical place to convert internal naive UTC (or any
TZ-aware) datetime into an Asia/Tbilisi ISO string for persistence /
display.

Chosen format: ISO-8601 with explicit offset, e.g.

    2026-05-22T18:48:51+04:00

Reasons over the space-separated form:
  * Unambiguous (no "did 18:48 mean UTC or local?" question).
  * Round-trips through ``datetime.fromisoformat``.
  * Same shape Calendar / OpenAI / most APIs accept.
"""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

TBILISI_TZ_NAME = "Asia/Tbilisi"
TBILISI_TZ = ZoneInfo(TBILISI_TZ_NAME)


# Booking Date Parse Patch (2026-06-04) — Georgian relative-date phrases.
# Stems cover declension: "ხვალ"/"ხვალე"/"ხვალისთვის" all start with "ხვალ".
# Order matters: more specific stems first (e.g. "ზეგ" before "გუშინ" is
# irrelevant but "ხვალინდ" before "ხვალ" would matter if both were used).
_RELATIVE_DAY_STEMS: tuple[tuple[str, int], ...] = (
    ("გუშინწინ", -2),
    ("გუშინ", -1),
    ("ხვალინდელ", 1),
    ("ხვალ", 1),
    ("ზეგ", 2),
    ("მაზეგ", 3),
    ("დღეს", 0),
    ("დღევანდელ", 0),
)

# "11 საათზე" / "11:00" / "11-ზე" — capture the hour. Cases:
#   * "11:00" / "11:30" → hh:mm
#   * "11 საათზე" / "11 სთ-ზე" / "11-ზე"
_TIME_HHMM_RE = re.compile(r"(?<!\d)(\d{1,2}):(\d{2})(?!\d)")
_TIME_HOUR_KA_RE = re.compile(
    r"(?<!\d)(\d{1,2})\s*"
    r"(?:საათ(?:ზე|ისთვის|ისკენ|ი)?|სთ(?:-ზე|ზე)?|-ზე)"
)


def _extract_time(text: str) -> tuple[int, int] | None:
    """Return ``(hour, minute)`` parsed from the first Georgian time
    expression in ``text``, or ``None`` if none is found.

    Accepts the canonical forms used in live traffic:
      * "11:00" / "9:30"
      * "11 საათზე" / "11 სთ-ზე"
      * "11-ზე" (bare hour with locative suffix)
    """
    if not text:
        return None
    m = _TIME_HHMM_RE.search(text)
    if m:
        hour, minute = int(m.group(1)), int(m.group(2))
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return hour, minute
    m = _TIME_HOUR_KA_RE.search(text)
    if m:
        hour = int(m.group(1))
        if 0 <= hour <= 23:
            return hour, 0
    return None


# ---------------------------------------------------------------------------
# Colloquial Georgian hour normalization (PARENT booking context).
#
# Live bug (2026-06-10): the same colloquial hour was interpreted
# inconsistently across conversations. "8 საათზე" / "8 სათზე" (typo) in a
# consultation context means 20:00, but the LLM sometimes read it as
# 08:00 (outside working hours). The deterministic rule below is the
# single source of truth, applied by the executor BEFORE every
# availability check / booking and by the legacy router parser.
#
# Rule (PARENT booking, business hours 10:00–21:00):
#   * unqualified single-digit hour 1–9  → +12  (13:00 … 21:00)
#   * 10 / 11 / 12 unqualified            → literal (10:00 / 11:00 / 12:00)
#   * explicit „დილ…" (morning)           → literal (08:00 / 09:00 …)
#   * explicit „საღამო…" (evening) 1–11   → +12  (საღამოს 8 → 20:00,
#                                            საღამოს 10 → 22:00)
#   * explicit „HH:MM"                     → taken literally, never remapped
# ---------------------------------------------------------------------------

# Typo-tolerant Georgian hour token. Covers:
#   საათზე / საათი / საათისთვის / საათისკენ
#   სათზე / სათი            (common typo — a single „ა")
#   სთ / სთ-ზე / სთზე
#   8-ზე / 8ზე              (bare hour + locative, hyphen optional, no space)
#   5ს / 5 ს                (E7: „ს" abbreviation of „საათზე" — matched LAST so
#                            „სთ"/„საათ" still win; the negative lookahead keeps
#                            it from firing inside „სხვა"/„საათ"/any Georgian word)
_COLLOQUIAL_HOUR_RE = re.compile(
    r"(?<!\d)(\d{1,2})\s*"
    r"(?:"
    r"საათ(?:ზე|ისთვის|ისკენ|ი)?"
    r"|სათ(?:ზე|ისთვის|ისკენ|ი)?"
    r"|სთ(?:\s*-?\s*ზე)?"
    r"|-?ზე"
    r"|ს(?![ა-ჰ])"
    r")"
)

# Morning / evening qualifier stems (substring match on lower-cased text).
_MORNING_MARKERS: tuple[str, ...] = ("დილ",)            # დილის / დილით / დილა…
_EVENING_MARKERS: tuple[str, ...] = ("საღამო", "ღამის", "ღამე")


def _normalize_pm_hour(hour: int, morning: bool, evening: bool) -> int:
    """Apply the project's PARENT-context colloquial PM convention to a bare
    hour. Single source of truth shared by the numeric, spelled-out and
    half-hour parsers so they stay in lock-step:
      * explicit „დილ…" (morning)  → literal (8 → 08:00)
      * explicit „საღამო…" (evening) 1–11 → +12 (8 → 20:00), 12 → literal
      * unqualified 1–9            → +12 (8 → 20:00)
      * 10 / 11 / 12 (and 0 / 13–23) → literal
    """
    if morning:
        return hour
    if evening:
        return hour + 12 if 1 <= hour <= 11 else hour
    if 1 <= hour <= 9:
        return hour + 12
    return hour


# E7 — half-hour colloquial forms („7ნახ" / „7 ნახ" / „7 ნახევარზე" → 7:30;
# „ნახევარი 8" → 8:30). DOCUMENTED CONVENTION: the explicit digit is the hour
# (PM-normalised by `_normalize_pm_hour`) and the minute is fixed at 30 — i.e.
# „ნახევარი 8" is read as „eight-thirty", NOT the „half-to-eight" (7:30)
# interpretation. The two forms (digit-before-„ნახ" and „ნახევარი"-before-digit)
# both resolve to HH:30 for consistency.
_HALF_HOUR_AFTER_RE = re.compile(r"(?<!\d)(\d{1,2})\s*ნახ")
_HALF_HOUR_BEFORE_RE = re.compile(r"ნახევარ\w*\s*(\d{1,2})(?!\s*წ)")


def _extract_half_hour(
    low: str, morning: bool, evening: bool,
) -> tuple[int, int] | None:
    m = _HALF_HOUR_AFTER_RE.search(low) or _HALF_HOUR_BEFORE_RE.search(low)
    if not m:
        return None
    hour = int(m.group(1))
    if not (0 <= hour <= 23):
        return None
    return _normalize_pm_hour(hour, morning, evening), 30


# E8 — spelled-out Georgian hours. Stems are declension-tolerant (matched with a
# trailing „[ა-ჰ]*" so „ხუთ"/„ხუთი"/„ათ"/„ათი" all hit) and REQUIRE a following
# „საათ"/„სთ" time word, so a number word elsewhere („ერთი შვილი") never parses
# as a time and the „ათ" in „საათ" itself is never mis-read. Longest / compound
# stems first so „თერთმეტ" wins over „ერთ" and „თორმეტ" over „ორ".
_SPELLED_HOURS: tuple[tuple[str, int], ...] = (
    ("თერთმეტ", 11),
    ("თორმეტ", 12),
    ("ცხრა", 9),
    ("ექვს", 6),
    ("ხუთ", 5),
    ("ოთხ", 4),
    ("შვიდ", 7),
    ("რვა", 8),
    ("სამ", 3),
    ("ორ", 2),
    ("ერთ", 1),
    ("ათ", 10),
)


def _extract_spelled_hour(
    low: str, morning: bool, evening: bool,
) -> tuple[int, int] | None:
    for stem, value in _SPELLED_HOURS:
        if re.search(r"(?<![ა-ჰ])" + stem + r"[ა-ჰ]*\s+(?:საათ|სთ)", low):
            return _normalize_pm_hour(value, morning, evening), 0
    return None


def extract_colloquial_hour(text: str) -> tuple[int, int] | None:
    """Return ``(hour_24, minute)`` for a Georgian time expression in
    ``text``, applying the PARENT-context PM heuristic for unqualified
    single-digit hours. Returns ``None`` when no time is found.

    Explicit ``HH:MM`` is always taken literally. A bare colloquial hour
    is normalised per the rule documented above.
    """
    if not text:
        return None
    low = text.lower()
    # Explicit HH:MM wins literally (never remapped).
    m = _TIME_HHMM_RE.search(low)
    if m:
        hour, minute = int(m.group(1)), int(m.group(2))
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return hour, minute
    morning = any(mk in low for mk in _MORNING_MARKERS)
    evening = any(mk in low for mk in _EVENING_MARKERS)
    # E7 — half-hour colloquial („7ნახ" / „ნახევარი 8") → HH:30. Checked before
    # the bare-hour regex so „7 ნახევარზე" is not mis-read as a whole hour.
    half = _extract_half_hour(low, morning, evening)
    if half is not None:
        return half
    m = _COLLOQUIAL_HOUR_RE.search(low)
    if not m:
        # E8 — spelled-out Georgian hour („რვა საათზე" → 20:00). Only when the
        # numeric regex found nothing (spelled forms carry no digit).
        spelled = _extract_spelled_hour(low, morning, evening)
        if spelled is not None:
            return spelled
        # Bare hour with NO time suffix is only trusted when an explicit
        # „დილ…"/„საღამო…" qualifier is present („საღამოს 8" → 20:00).
        # Guard against age phrases („8 წლის") by rejecting a number
        # immediately followed by „წ".
        if morning or evening:
            bare = re.search(r"(?<!\d)(\d{1,2})(?!\s*წ)", low)
            if bare:
                hour = int(bare.group(1))
                if 0 <= hour <= 23:
                    if morning:
                        return hour, 0
                    if 1 <= hour <= 11:
                        return hour + 12, 0
                    return hour, 0
        return None
    hour = int(m.group(1))
    if not (0 <= hour <= 23):
        return None
    minute = 0
    if morning:
        return hour, minute  # keep literal — e.g. დილის 8 → 08:00
    if evening:
        if 1 <= hour <= 11:
            return hour + 12, minute  # საღამოს 8 → 20:00, საღამოს 10 → 22:00
        return hour, minute
    # Unqualified.
    if 1 <= hour <= 9:
        return hour + 12, minute  # 8 → 20:00
    return hour, minute  # 10 / 11 / 12 literal


def apply_colloquial_time_to_iso(iso: str, text: str) -> str:
    """Override the time portion of ``iso`` with the PM-normalised
    colloquial hour found in ``text``, preserving the date.

    Returns ``iso`` unchanged when ``text`` has no detectable time or
    ``iso`` is unparseable. Never throws.
    """
    if not iso or not text:
        return iso
    parsed = extract_colloquial_hour(text)
    if parsed is None:
        return iso
    try:
        base = datetime.fromisoformat(iso)
    except (ValueError, TypeError):
        return iso
    if base.tzinfo is None:
        base = base.replace(tzinfo=TBILISI_TZ)
    base = base.astimezone(TBILISI_TZ)
    hh, mm = parsed
    try:
        return base.replace(
            hour=hh, minute=mm, second=0, microsecond=0,
        ).isoformat()
    except ValueError:
        return iso


def _extract_relative_day_offset(text: str) -> int | None:
    """Return the day offset for a Georgian relative-day phrase in
    ``text`` (``-1`` for „გუშინ", ``0`` for „დღეს", ``+1`` for „ხვალ",
    ``+2`` for „ზეგ", etc.), or ``None`` if none is found.

    Stem matching is plain substring on a lower-cased copy. The first
    stem that hits wins; more specific stems are listed first.
    """
    if not text:
        return None
    lowered = text.lower()
    for stem, offset in _RELATIVE_DAY_STEMS:
        if stem in lowered:
            return offset
    return None


# E9 — Georgian weekday names (dative „on <weekday>" forms). Stems are
# declension-tolerant; the compound „-შაბათ" weekdays are listed BEFORE bare
# „შაბათ" (Saturday) because each contains „შაბათ" as a substring (ორ-შაბათ,
# სამ-შაბათ, …) — first match wins, so order is load-bearing.
_WEEKDAY_STEMS: tuple[tuple[str, int], ...] = (
    ("ოთხშაბათ", 2),   # Wednesday
    ("ხუთშაბათ", 3),   # Thursday
    ("ორშაბათ", 0),    # Monday
    ("სამშაბათ", 1),   # Tuesday
    ("პარასკევ", 4),   # Friday
    ("შაბათ", 5),      # Saturday
    ("კვირას", 6),     # Sunday — the dative „კვირას" only (NOT „კვირის" = week)
)


def _resolve_weekday_date(text: str, base: datetime):
    """Resolve a Georgian weekday phrase to a future date (Asia/Tbilisi),
    or None when no weekday name is present.

      * „მომავალი/შემდეგი კვირის <weekday>" → that weekday in NEXT calendar week.
      * „ამ კვირის <weekday>"               → that weekday in THIS week (rolled
                                              forward 7 days if already past).
      * bare „<weekday>ს"                   → the next upcoming occurrence;
                                              same-day if today IS that weekday
                                              (same-day future booking is allowed
                                              — see the today-first availability
                                              feature). Never a past date.
    """
    low = (text or "").lower()
    target_wd = None
    for stem, wd in _WEEKDAY_STEMS:
        if stem in low:
            target_wd = wd
            break
    if target_wd is None:
        return None
    today = base.date()
    today_wd = today.weekday()
    this_monday = today - timedelta(days=today_wd)
    next_week = ("მომავალ" in low or "შემდეგ" in low) and "კვირ" in low
    this_week = ("ამ კვირ" in low) or ("ამავე კვირ" in low)
    if next_week:
        return this_monday + timedelta(days=7 + target_wd)
    if this_week:
        d = this_monday + timedelta(days=target_wd)
        if d < today:
            d += timedelta(days=7)
        return d
    # Bare weekday → next upcoming occurrence (today if today is that weekday).
    return today + timedelta(days=(target_wd - today_wd) % 7)


def resolve_relative_datetime(
    text: str,
    *,
    now: datetime | None = None,
) -> datetime | None:
    """Resolve a Georgian relative-date phrase (and optional time) in
    ``text`` to a Tbilisi-aware ``datetime``, or ``None`` if the text
    does not look like a relative-date expression.

    Examples (with ``now`` mocked to ``2026-06-04 09:00`` Tbilisi):
      * "ხვალ 11 საათზე"        → ``2026-06-05 11:00`` Tbilisi
      * "ხვალ მინდა 11 საათზე"  → ``2026-06-05 11:00`` Tbilisi
      * "ხვალ 11-ზე"             → ``2026-06-05 11:00`` Tbilisi
      * "ზეგ 14:00"              → ``2026-06-06 14:00`` Tbilisi
      * "დღეს 20:00"             → ``2026-06-04 20:00`` Tbilisi
      * "გუშინ 11 საათზე"        → ``2026-06-03 11:00`` Tbilisi (past)
      * "ხვალ"                    → ``2026-06-05 00:00`` Tbilisi (no time)
      * "11:00 saatze" / "მინდა" alone → ``None`` (no relative-day word)

    The function NEVER throws; bad input returns ``None``.
    """
    base = now or now_tbilisi()
    if base.tzinfo is None:
        base = base.replace(tzinfo=TBILISI_TZ)
    offset = _extract_relative_day_offset(text)
    if offset is not None:
        # Explicit relative-day word („დღეს"/„ხვალ"/„გუშინ"/…) — a past offset
        # („გუშინ") is intentional and allowed.
        target_date = (base + timedelta(days=offset)).date()
    else:
        # E9 — Georgian weekday name („შაბათს", „მომავალი კვირის სამშაბათს").
        target_date = _resolve_weekday_date(text, base)
        if target_date is None:
            return None
    parsed_time = _extract_time(text)
    hh, mm = parsed_time if parsed_time else (0, 0)
    return datetime.combine(target_date, time(hh, mm), tzinfo=TBILISI_TZ)


def to_tbilisi(dt: datetime) -> datetime:
    """Return a TZ-aware datetime in Asia/Tbilisi.

    Convention: a *naive* input is treated as UTC (matches
    ``datetime.utcnow()`` usage across the project). An aware input is
    converted to Tbilisi via ``astimezone``.
    """
    if dt.tzinfo is None:
        aware = dt.replace(tzinfo=timezone.utc)
    else:
        aware = dt
    return aware.astimezone(TBILISI_TZ)


def format_tbilisi_datetime(dt: datetime | None) -> str:
    """Format a datetime as an Asia/Tbilisi ISO-8601 string.

    Returns ``""`` for ``None``. Naive datetimes are treated as UTC.
    """
    if dt is None:
        return ""
    return to_tbilisi(dt).isoformat()


def now_tbilisi() -> datetime:
    """Current time as a TZ-aware datetime in Asia/Tbilisi."""
    return datetime.now(TBILISI_TZ)


def now_tbilisi_iso() -> str:
    """Current time as an Asia/Tbilisi ISO-8601 string."""
    return now_tbilisi().isoformat()
