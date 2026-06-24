"""Unit tests for app.agent.services.knowledge_loader and the knowledge YAML
files it backs.

Covers:
  * loads each knowledge YAML successfully
  * camp.price_gel == 2150 (authoritative)
  * camp.location == "ამბასადორი კაჭრეთი" exact
  * incorrect "ამბასადორი კაჭრეთის აკადემია" phrase absent everywhere
  * camp.streams count == 3
  * registration_url and phone non-empty
  * missing knowledge file raises KnowledgeNotFound (FileNotFoundError)
  * caching: same object returned on second call
  * Settings.CAMP_PRICE sourced from knowledge (no independent 2200)
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.agent.services import knowledge_loader as kl


@pytest.fixture(autouse=True)
def _clear_cache():
    kl.reset_cache()
    yield
    kl.reset_cache()


# -- camp_2026 --------------------------------------------------------------


def test_camp_loads() -> None:
    camp = kl.load_knowledge("camp_2026")
    assert "camp" in camp
    assert isinstance(camp["camp"], dict)


def test_camp_price_is_authoritative_2150() -> None:
    camp = kl.load_knowledge("camp_2026")["camp"]
    assert camp["price_gel"] == 2150


def test_camp_location_exact_string() -> None:
    camp = kl.load_knowledge("camp_2026")["camp"]
    assert camp["location"] == "ამბასადორი კაჭრეთი"


def test_camp_streams_count_three() -> None:
    streams = kl.load_knowledge("camp_2026")["camp"]["streams"]
    assert len(streams) == 3
    for s in streams:
        assert s.get("name")
        assert s.get("dates_text")


def test_camp_phone_and_registration_url_non_empty() -> None:
    camp = kl.load_knowledge("camp_2026")["camp"]
    assert camp["phone"].strip()
    assert camp["registration_url"].startswith("https://")


def test_camp_includes_and_discounts_present() -> None:
    camp = kl.load_knowledge("camp_2026")["camp"]
    assert len(camp["includes"]) >= 4
    assert len(camp["discounts"]) >= 1
    assert all("percent" in d for d in camp["discounts"])


# -- incorrect-location absence --------------------------------------------


INCORRECT = "ამბასადორი კაჭრეთის აკადემია"


def test_incorrect_location_phrase_absent_from_all_knowledge() -> None:
    hits = []
    for path in kl.KNOWLEDGE_DIR.rglob("*.yaml"):
        if INCORRECT in path.read_text(encoding="utf-8"):
            hits.append(str(path))
    assert hits == [], f"Incorrect phrase found in knowledge files: {hits}"


def test_incorrect_location_phrase_absent_from_customer_facing_files() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    hits = []
    for folder in [
        repo_root / "app" / "agent" / "templates",
        repo_root / "app" / "agent" / "prompts",
    ]:
        for path in folder.rglob("*"):
            if not path.is_file() or path.suffix not in {".yaml", ".md"}:
                continue
            if INCORRECT in path.read_text(encoding="utf-8"):
                hits.append(str(path))
    assert hits == [], f"Incorrect phrase found in customer-facing files: {hits}"


# -- other knowledge files --------------------------------------------------


def test_company_loads() -> None:
    company = kl.load_knowledge("company")["company"]
    assert company["name"] == "სიტყვის აკადემია"
    assert company["phone"]


def test_business_hours_loads_with_expected_shape() -> None:
    # Booking Availability Patch (2026-06-03) — consultation window
    # widened to 10:00–21:00 with 60-minute slots.
    b = kl.load_knowledge("business_hours")["business"]
    assert b["timezone"] == "Asia/Tbilisi"
    assert b["work_hours"]["start"] == "10:00"
    assert b["work_hours"]["end"] == "21:00"
    assert b["business_hours"]["start"] == "10:00"
    assert b["business_hours"]["end"] == "21:00"
    assert b["slot"]["duration_minutes"] == 60
    assert b["slot"]["buffer_minutes"] == 120


def test_adult_defaults_loads() -> None:
    d = kl.load_knowledge("adult_defaults")["adult_defaults"]
    assert d["event_placeholder"] == "დასაზუსტებელია"
    assert d["event_name_placeholder"] == "ღონისძიება"
    assert d["event"]["name"] == "კულტურული საღამო"


def test_i18n_ka_months_loads_with_12_entries() -> None:
    m = kl.load_knowledge("i18n/ka_months")
    assert len(m["months_nominative"]) == 12
    assert len(m["month_stems"]) == 12
    assert m["months_nominative"][5] == "მაისი"
    assert m["month_stems"]["მაის"] == 5
    assert m["month_stems"]["აგვისტო"] == 8  # nominative IS stem


# -- error path ------------------------------------------------------------


def test_missing_knowledge_file_raises_clear_error() -> None:
    with pytest.raises(kl.KnowledgeNotFound) as excinfo:
        kl.load_knowledge("does_not_exist")
    msg = str(excinfo.value)
    assert "does_not_exist" in msg
    assert ".yaml" in msg


def test_missing_knowledge_file_is_file_not_found_error() -> None:
    # KnowledgeNotFound subclasses FileNotFoundError so callers can catch
    # the standard exception.
    with pytest.raises(FileNotFoundError):
        kl.load_knowledge("definitely_missing")


def test_malformed_knowledge_file_fails_loudly(tmp_path: Path, monkeypatch) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("not: [valid yaml", encoding="utf-8")
    monkeypatch.setattr(kl, "KNOWLEDGE_DIR", tmp_path)
    kl.reset_cache()
    with pytest.raises(kl.KnowledgeNotFound) as excinfo:
        kl.load_knowledge("bad")
    assert "failed to parse" in str(excinfo.value)


def test_top_level_non_mapping_fails(tmp_path: Path, monkeypatch) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("- just\n- a\n- list\n", encoding="utf-8")
    monkeypatch.setattr(kl, "KNOWLEDGE_DIR", tmp_path)
    kl.reset_cache()
    with pytest.raises(kl.KnowledgeNotFound) as excinfo:
        kl.load_knowledge("bad")
    assert "mapping" in str(excinfo.value)


# -- caching ---------------------------------------------------------------


def test_repeated_lookups_return_cached_object() -> None:
    a = kl.load_knowledge("camp_2026")
    b = kl.load_knowledge("camp_2026")
    assert a is b


# -- Settings.CAMP_PRICE single source of truth -----------------------------


def test_settings_camp_price_sourced_from_knowledge_when_env_unset(
    monkeypatch,
) -> None:
    monkeypatch.delenv("CAMP_PRICE", raising=False)
    from app.config import Settings

    s = Settings.from_env()
    assert s.CAMP_PRICE == 2150, (
        "Settings.CAMP_PRICE should read knowledge value (2150), not the "
        "legacy independent default of 2200."
    )


def test_settings_camp_price_reads_env_file_default(monkeypatch) -> None:
    # config.py reads from dotenv_values(.env) captured at module-load, not
    # from os.environ. With .env having no CAMP_PRICE line, the default
    # path runs and must yield the knowledge value. Re-checks the "env
    # unset" path with the cache deliberately reset.
    from app.agent.services.knowledge_loader import reset_cache as kl_reset

    monkeypatch.delenv("CAMP_PRICE", raising=False)
    kl_reset()

    from app.config import Settings

    s = Settings.from_env()
    assert s.CAMP_PRICE == 2150
