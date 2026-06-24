"""Camp fact source-of-truth migration 5A-3 (2026-06-22).

Finishes the LIVE camp-fact reader cleanup after the age-band migration:

  * parent_flow._facts_for_post_booking — migrated off the direct
    `camp_2026.yaml` read onto canonical `admin_config_service.get_camp_facts()`
    (admin-first, camp_2026 fallback inside; same shape; canonical phone).
  * comment_service._build_parent_rich_dm — VERIFIED already Admin-first
    (`build_section_dm` renders from the admin section; camp_2026 is only the
    step-2 fallback). Not refactored.

After this, parent_flow has ZERO direct camp_2026 reads; the only remaining
camp_2026 reads are intended fallbacks / legacy / boot-default / tests.

All offline / mocked — no real network.
"""
from __future__ import annotations

import inspect

import pytest

from app.flows import parent_flow
from app.models.lead import Lead
from app.services import admin_config_service, comment_service


def _booked_lead(name="ნიკა"):
    lead = Lead(sender_id="x", platform="instagram", segment="PARENT", name=name)
    lead.booked_datetime_iso = "2026-06-25T12:00:00"
    return lead


# ===========================================================================
# (1-4) post-booking facts follow canonical get_camp_facts()
# ===========================================================================


def test_post_booking_facts_use_admin_config(monkeypatch):
    monkeypatch.setattr(admin_config_service, "get_camp_facts", lambda: {
        "price_gel": 3000, "location": "ახალი ლოკაცია",
        "registration_url": "https://example.test/reg", "phone": "599 11 22 33",
        "duration_days": 5, "includes": ["ტრანსპორტი"], "streams": [],
    })
    f = parent_flow._facts_for_post_booking(_booked_lead())
    assert f["price_gel"] == 3000                       # (#1)
    assert f["location"] == "ახალი ლოკაცია"             # (#2)
    assert f["registration_url"] == "https://example.test/reg"  # (#3)
    assert f["phone"] == "599 11 22 33"                 # (#4) canonical phone via get_camp_facts


def test_post_booking_phone_is_canonical_manager_phone():
    # With shipped config the post-booking phone equals the canonical helper.
    f = parent_flow._facts_for_post_booking(_booked_lead())
    assert f["phone"] == admin_config_service.get_manager_phone()


# ===========================================================================
# (5,6) safe fallback + default unchanged
# ===========================================================================


def test_post_booking_safe_when_camp_facts_raises(monkeypatch):
    def _boom():
        raise RuntimeError("config down")
    monkeypatch.setattr(admin_config_service, "get_camp_facts", _boom)
    f = parent_flow._facts_for_post_booking(_booked_lead())
    # no camp facts → no camp keys, but the booked date/time + name survive
    assert "price_gel" not in f
    assert f.get("lead_name") == "ნიკა"
    assert f.get("booked_date") and f.get("booked_time")


def test_post_booking_default_config_unchanged():
    f = parent_flow._facts_for_post_booking(_booked_lead())
    assert f["price_gel"] == 2150
    assert "კაჭრეთ" in f["location"]
    assert sorted(k for k in f if k not in {"booked_date", "booked_time", "lead_name"}) == [
        "duration_days", "includes", "location", "phone", "price_gel",
        "registration_url", "streams",
    ]


# ===========================================================================
# (7-10) comment rich DM is Admin-first (verification, not refactor)
# ===========================================================================


def test_build_section_dm_renders_from_admin_section_fields(monkeypatch):
    monkeypatch.setattr(
        admin_config_service, "render_template",
        lambda tid, ctx: f"price={ctx.get('price_gel')} loc={ctx.get('location')} streams={ctx.get('stream_dates')}",
    )
    section = {
        "id": "summer_camp", "type": "camp", "auto_dm_template_id": "t",
        "price_gel": 3000, "location": "ტესტ-ლოკაცია",
        "streams": [{"name": "I", "dates_text": "1-7 აგვისტო", "status": "active"}],
    }
    out = admin_config_service.build_section_dm(section)
    assert "3000" in out and "ტესტ-ლოკაცია" in out and "1-7 აგვისტო" in out


def test_comment_rich_dm_admin_first(monkeypatch):
    monkeypatch.setattr(
        admin_config_service, "get_section",
        lambda sid: {
            "id": "summer_camp", "type": "camp", "auto_dm_template_id": "t",
            "price_gel": 3000, "location": "ტესტ-ლოკაცია",
        } if sid == "summer_camp" else None,
    )
    monkeypatch.setattr(
        admin_config_service, "render_template",
        lambda tid, ctx: f"ADMIN price={ctx.get('price_gel')} loc={ctx.get('location')}",
    )
    out = comment_service._build_parent_rich_dm()
    assert "3000" in out and "ტესტ-ლოკაცია" in out   # admin facts won


def test_comment_rich_dm_falls_back_when_no_admin(monkeypatch):
    # No admin section → build_section_dm returns "" → camp_2026 canonical build.
    monkeypatch.setattr(admin_config_service, "get_section", lambda sid: None)
    out = comment_service._build_parent_rich_dm()
    assert out and isinstance(out, str)
    assert ("2150" in out) or ("კაჭრეთ" in out)        # camp_2026 fallback facts


# ===========================================================================
# Source guards
# ===========================================================================


def test_facts_for_post_booking_no_longer_reads_camp_2026():
    src = inspect.getsource(parent_flow._facts_for_post_booking)
    assert 'load_knowledge("camp_2026")' not in src
    assert "get_camp_facts" in src


def test_parent_flow_has_zero_direct_camp_2026_reads():
    assert inspect.getsource(parent_flow).count('load_knowledge("camp_2026")') == 0


def test_comment_camp_2026_is_only_the_fallback():
    # exactly one camp_2026 read in comment_service — the step-2 legacy fallback.
    assert inspect.getsource(comment_service).count('load_knowledge("camp_2026")') == 1
