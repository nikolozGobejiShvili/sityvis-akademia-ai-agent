"""Admin Panel MVP — manual end-to-end simulation.

Exercises the loader / hashtag-routing / template-rendering surface
exactly as the live FastAPI routes do, without spinning up a server.

Scenarios:

  A) Load default admin config (summer_camp + sunday_school + adult_events)
  B) Edit summer_camp price via update_section, verify reload
  C) Add a brand-new section, verify hashtag routing finds it
  D) Post/caption hashtag routing matrix (admin_config primary)
  E) Template fallback when an unknown template_id is referenced

Run with:

    PYTHONIOENCODING=utf-8 python tools/manual_simulation_admin_config.py
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.services import admin_config_service  # noqa: E402


def _backup_and_restore() -> tuple[Path, Path | None]:
    """Snapshot the live sections.yaml before mutating; return the
    backup path so the script can restore it at the end."""
    src = admin_config_service.SECTIONS_PATH
    backup = src.with_suffix(".sim_backup")
    if src.exists():
        shutil.copy2(src, backup)
        return src, backup
    return src, None


def _restore(src: Path, backup: Path | None) -> None:
    if backup and backup.exists():
        shutil.copy2(backup, src)
        backup.unlink(missing_ok=True)


def scenario_a_load_default() -> None:
    print("\n=== A — Load default admin config ===")
    ids = {s["id"] for s in admin_config_service.load_sections()}
    print(f"  sections found: {sorted(ids)}")
    assert "summer_camp" in ids
    assert "sunday_school" in ids
    assert "adult_events" in ids
    print("  ✅ all three canonical sections present.")


def scenario_b_edit_price() -> None:
    print("\n=== B — Edit summer_camp price ===")
    original = admin_config_service.get_section("summer_camp")["price_gel"]
    print(f"  original price_gel={original}")

    errors = admin_config_service.update_section("summer_camp", {
        "price_gel": 9999,
        # validator wants all required keys present
        "name": "საზაფხულო ბანაკი",
        "type": "camp",
        "status": "active",
        "hashtags": ["ბანაკი", "banaki", "bavshvebi", "camp"],
        "auto_dm_template_id": "summer_camp_comment_dm",
    })
    assert errors == [], f"validation errors: {errors}"

    refreshed = admin_config_service.get_section("summer_camp")
    print(f"  refreshed price_gel={refreshed['price_gel']}")
    assert refreshed["price_gel"] == 9999

    # Render the section DM and verify the new value flows through.
    out = admin_config_service.build_section_dm(refreshed)
    assert "9999 ლარი" in out
    print("  ✅ price edit reflected in rendered DM.")

    # Roll back so the next scenario sees clean data.
    admin_config_service.update_section("summer_camp", {
        "price_gel": original,
        "name": "საზაფხულო ბანაკი",
        "type": "camp",
        "status": "active",
        "hashtags": ["ბანაკი", "banaki", "bavshvebi", "camp"],
        "auto_dm_template_id": "summer_camp_comment_dm",
    })


def scenario_c_add_new_section() -> None:
    print("\n=== C — Add brand-new section (test_program) ===")
    new_section = {
        "id": "test_program",
        "name": "Test პროგრამა",
        "type": "kids_program",
        "status": "active",
        "hashtags": ["testtag", "tesT_PROGram"],
        "auto_dm_template_id": "generic_section_comment_dm",
        "public_reply_template_id": "default_public_reply",
        "description_short": "ეს არის სიმულაცია — ნამდვილი პროგრამა არ არის.",
    }
    errors = admin_config_service.save_section(new_section)
    print(f"  validation errors: {errors}")
    assert errors == []

    by_tag = admin_config_service.find_section_by_hashtag("#testtag")
    print(f"  find_by_hashtag('#testtag') → {by_tag['id'] if by_tag else None}")
    assert by_tag and by_tag["id"] == "test_program"

    by_caption = admin_config_service.find_section_from_post_hashtags(
        ["TESTTAG"],
    )
    print(f"  case-insensitive caption match → "
          f"{by_caption['id'] if by_caption else None}")
    assert by_caption and by_caption["id"] == "test_program"

    rendered = admin_config_service.build_section_dm(
        admin_config_service.get_section("test_program"),
    )
    print(f"  rendered DM (first 80 chars): {rendered[:80]!r}")
    assert "Test პროგრამა" in rendered
    assert "{" not in rendered

    admin_config_service.delete_section("test_program")
    assert admin_config_service.get_section("test_program") is None
    print("  ✅ added, rendered, removed cleanly.")


def scenario_d_post_caption_routing() -> None:
    print("\n=== D — Post/caption hashtag routing matrix ===")
    cases = [
        (["ბანაკი"], "summer_camp"),
        (["საკვირაოსკოლა"], "sunday_school"),
        (["საღამო"], "adult_events"),
        (["unknown_marketing_tag"], None),
    ]
    for tags, expected in cases:
        section = admin_config_service.find_section_from_post_hashtags(tags)
        got = section["id"] if section else None
        marker = "✅" if got == expected else "❌"
        print(f"  {marker} hashtags={tags!r} → section_id={got}")
        assert got == expected, f"hashtags={tags} expected={expected} got={got}"


def scenario_e_template_fallback() -> None:
    print("\n=== E — Template fallback when unknown template_id ===")
    fake = {
        "id": "ghost",
        "name": "Ghost",
        "auto_dm_template_id": "non_existent_template",
    }
    out = admin_config_service.build_section_dm(fake)
    print(f"  build_section_dm with unknown template → {out!r}")
    assert out == ""
    print("  ✅ unknown template returns empty string (caller uses fallback).")


def main() -> int:
    print("=" * 60)
    print("Admin Panel MVP — manual simulation")
    print("=" * 60)

    src, backup = _backup_and_restore()
    try:
        scenario_a_load_default()
        scenario_b_edit_price()
        scenario_c_add_new_section()
        scenario_d_post_caption_routing()
        scenario_e_template_fallback()
    except AssertionError as exc:
        print(f"\n❌ Assertion failed: {exc}")
        _restore(src, backup)
        return 1
    except Exception as exc:
        print(f"\n❌ Unexpected error: {exc!r}")
        _restore(src, backup)
        return 2
    finally:
        _restore(src, backup)

    print("\n" + "=" * 60)
    print("✅ All admin-config scenarios passed.")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
