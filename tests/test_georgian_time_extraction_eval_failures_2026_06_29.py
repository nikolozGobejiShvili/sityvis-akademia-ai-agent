"""Deterministic Georgian time/date extraction — Batch A eval fixes (E7/E8/E9).

Parser-only coverage for `app/agent/services/timestamps.py`:
  * E7 — abbreviated colloquial time („5ს" → 17:00) + half-hour forms.
  * E8 — spelled-out Georgian hours („რვა საათზე" → 20:00).
  * E9 — Georgian weekday-relative dates („მომავალი კვირის სამშაბათს").

Conventions exercised (single source of truth = `_normalize_pm_hour`):
  * unqualified single-digit 1–9 → +12 (8 → 20:00); 10/11/12 literal.
  * explicit „დილ…" → literal morning; „საღამო…" 1–11 → +12.
  * half-hour „ნახ" forms → HH:30 where HH is the explicit digit (PM-normalised);
    „ნახევარი 8" is read as 8:30 (eight-thirty), NOT 7:30 (documented choice).
  * weekday phrases resolve to a FUTURE date in Asia/Tbilisi; bare weekday → next
    upcoming occurrence (same-day allowed if today IS that weekday); past only via
    an explicit „გუშინ".
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.agent.services import timestamps as ts
from app.agent.services.timestamps import (
    extract_colloquial_hour as H,
    resolve_relative_datetime as R,
)

TBILISI = ZoneInfo("Asia/Tbilisi")
# Frozen "now" matches the eval harness (`evals/cases.py::_NOW`).
_NOW = datetime(2026, 6, 29, 10, 0, tzinfo=TBILISI)  # Monday


# =====================================================================
# E7 — abbreviated colloquial time
# =====================================================================
def test_1_abbrev_5s_to_17():
    assert H("5ს") == (17, 0)


def test_2_abbrev_5_space_s_to_17():
    assert H("5 ს") == (17, 0)


def test_3_half_hour_7nakh_is_half_hour():
    out = H("7ნახ")
    assert out is not None and out[1] == 30


def test_4_half_hour_nakhevari_8_is_half_hour():
    out = H("ნახევარი 8")
    assert out is not None and out[1] == 30


def test_3b_half_hour_7_nakhevarze_is_half_hour():
    out = H("7 ნახევარზე")
    assert out is not None and out[1] == 30


# =====================================================================
# E8 — spelled-out Georgian hours
# =====================================================================
def test_5_spelled_rva_to_20():
    assert H("რვა საათზე") == (20, 0)


def test_6_spelled_khut_to_17():
    assert H("ხუთ საათზე") == (17, 0)


def test_7_spelled_dilis_at_to_10():
    assert H("დილის ათ საათზე") == (10, 0)


def test_8_spelled_saghamos_rva_to_20():
    assert H("საღამოს რვა საათზე") == (20, 0)


def test_8b_spelled_tskhra_to_21():
    assert H("ცხრა საათზე") == (21, 0)


def test_8c_spelled_ati_to_10():
    # Unqualified „ათი" (10) is literal (10/11/12 never PM-shifted).
    assert H("ათი საათზე") == (10, 0)


# =====================================================================
# Existing numeric regressions (must NOT break)
# =====================================================================
def test_9_numeric_8_saatze_to_20():
    assert H("8 საათზე") == (20, 0)


def test_10_numeric_8_ze_to_20():
    assert H("8-ზე") == (20, 0)


def test_11_numeric_saghamos_9_to_21():
    assert H("საღამოს 9 საათზე") == (21, 0)


def test_12_numeric_dilis_10_to_10():
    assert H("დილის 10 საათზე") == (10, 0)


def test_12b_explicit_hhmm_literal():
    assert H("19:30") == (19, 30)
    assert H("10:00") == (10, 0)


def test_12c_age_phrase_not_a_time():
    # „8 წლის" (8 years old) must NOT parse as a time.
    assert H("8 წლის") is None


# =====================================================================
# E9 — weekday-relative dates (frozen now = Mon 2026-06-29 10:00 Tbilisi)
# =====================================================================
def test_13_next_week_tuesday_is_future_tuesday():
    d = R("მომავალი კვირის სამშაბათს", now=_NOW)
    assert d is not None
    assert d.weekday() == 1          # Tuesday
    assert d.date() > _NOW.date()    # future
    assert d.date() == datetime(2026, 7, 7, tzinfo=TBILISI).date()  # next week's Tue


def test_14_shemdegi_week_tuesday_is_future_tuesday():
    d = R("შემდეგი კვირის სამშაბათს", now=_NOW)
    assert d is not None
    assert d.weekday() == 1
    assert d.date() == datetime(2026, 7, 7, tzinfo=TBILISI).date()


def test_15_shabats_is_next_saturday():
    d = R("შაბათს", now=_NOW)
    assert d is not None
    assert d.weekday() == 5          # Saturday
    assert d.date() >= _NOW.date()
    assert d.date() == datetime(2026, 7, 4, tzinfo=TBILISI).date()  # next upcoming Sat


def test_16_orshabats_today_or_future_monday_never_past():
    # Today (2026-06-29) IS Monday. Same-day future booking is allowed by the
    # project, so a bare „ორშაბათს" resolves to TODAY — never a past date.
    d = R("ორშაბათს", now=_NOW)
    assert d is not None
    assert d.weekday() == 0          # Monday
    assert d.date() >= _NOW.date()   # never in the past
    assert d.date() == _NOW.date()   # documented: same-day


def test_17_am_kviris_paraskevs_this_week_friday():
    d = R("ამ კვირის პარასკევს", now=_NOW)
    assert d is not None
    assert d.weekday() == 4          # Friday
    assert d.date() >= _NOW.date()
    assert d.date() == datetime(2026, 7, 3, tzinfo=TBILISI).date()  # this week's Fri


def test_18_gushin_past_allowed_only_with_explicit_past_word():
    # „გუშინ 11 საათზე" — a PAST date is allowed ONLY because of the explicit
    # „გუშინ" (existing behaviour, must remain).
    d = R("გუშინ 11 საათზე", now=_NOW)
    assert d is not None
    assert d.date() == datetime(2026, 6, 28, tzinfo=TBILISI).date()  # yesterday
    assert (d.hour, d.minute) == (11, 0)


def test_18b_plain_message_without_day_word_returns_none():
    # No relative-day word and no weekday name → not a relative-date expression.
    assert R("გამარჯობა, მინდა კონსულტაცია", now=_NOW) is None


# =====================================================================
# Guard: weekday stem ordering (compound „-შაბათ" never mis-read as Saturday)
# =====================================================================
@pytest.mark.parametrize(
    "phrase,expected_wd",
    [
        ("ორშაბათს", 0),
        ("სამშაბათს", 1),
        ("ოთხშაბათს", 2),
        ("ხუთშაბათს", 3),
        ("პარასკევს", 4),
        ("შაბათს", 5),
    ],
)
def test_weekday_stem_disambiguation(phrase, expected_wd):
    d = R(phrase, now=_NOW)
    assert d is not None and d.weekday() == expected_wd


# =====================================================================
# Guard: the new „ს" abbreviation does not fire inside Georgian words
# =====================================================================
def test_bare_s_abbrev_not_false_positive_inside_words():
    # „5 სხვა" (5 others) — „ს" is followed by „ხ" → must NOT parse as a time.
    assert H("5 სხვა ბავშვი") is None
    # „სთ" still wins over the bare „ს" abbreviation.
    assert H("5სთ") == (17, 0)
