"""Phase 3 knowledge migration verification.

Asserts that:
  * each knowledge YAML loads
  * camp.price_gel == 2150 (authoritative customer-facing price)
  * camp.location == "ამბასადორი კაჭრეთი" (exact)
  * the incorrect phrase "ამბასადორი კაჭრეთის აკადემია" does NOT appear in
    ANY knowledge file (recursive content scan)
  * customer-facing templates and prompts do NOT contain the incorrect phrase
  * Settings.CAMP_PRICE is sourced from knowledge (i.e. equals knowledge
    value when the env var is unset — i.e. no independent 2200 default)
  * camp.phone, camp.registration_url, camp.streams (3 entries) are present
    and non-empty
  * all required keys exist; no required value is empty
  * adult_defaults / company / business_hours / i18n.ka_months load and
    expose their documented top-level keys
Exits non-zero on any failure.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

from app.agent.services.knowledge_loader import (  # noqa: E402
    KNOWLEDGE_DIR,
    KnowledgeNotFound,
    load_knowledge,
    reset_cache,
)

AUTHORITATIVE_PRICE = 2150
AUTHORITATIVE_LOCATION = "ამბასადორი კაჭრეთი"
INCORRECT_LOCATION_FRAGMENT = "ამბასადორი კაჭრეთის აკადემია"


def _ok(msg: str) -> None:
    print(f"[ok] {msg}")


def _fail(msg: str) -> str:
    return f"[FAIL] {msg}"


def _check_camp(failures: list[str]) -> None:
    try:
        camp_doc = load_knowledge("camp_2026")
    except KnowledgeNotFound as exc:
        failures.append(_fail(f"camp_2026 load: {exc}"))
        return
    camp = camp_doc.get("camp") or {}

    # required scalars
    required = {
        "year": int,
        "name": str,
        "location": str,
        "age_min": int,
        "age_max": int,
        "duration_days": int,
        "price_gel": int,
        "registration_url": str,
        "phone": str,
    }
    for key, typ in required.items():
        val = camp.get(key)
        if val is None or val == "":
            failures.append(_fail(f"camp_2026: camp.{key} missing or empty"))
        elif not isinstance(val, typ):
            failures.append(
                _fail(f"camp_2026: camp.{key} expected {typ.__name__}, "
                      f"got {type(val).__name__} ({val!r})")
            )

    if camp.get("price_gel") != AUTHORITATIVE_PRICE:
        failures.append(
            _fail(f"camp.price_gel != authoritative "
                  f"({camp.get('price_gel')!r} vs {AUTHORITATIVE_PRICE})")
        )
    else:
        _ok(f"camp.price_gel == {AUTHORITATIVE_PRICE}")

    if camp.get("location") != AUTHORITATIVE_LOCATION:
        failures.append(
            _fail(f"camp.location != authoritative "
                  f"({camp.get('location')!r} vs {AUTHORITATIVE_LOCATION!r})")
        )
    else:
        _ok(f"camp.location == {AUTHORITATIVE_LOCATION!r}")

    streams = camp.get("streams") or []
    if len(streams) != 3:
        failures.append(_fail(f"camp.streams: expected 3, got {len(streams)}"))
    else:
        _ok("camp.streams count == 3")
    for i, s in enumerate(streams):
        if not isinstance(s, dict):
            failures.append(_fail(f"camp.streams[{i}] not a mapping"))
            continue
        if not s.get("name") or not s.get("dates_text"):
            failures.append(_fail(f"camp.streams[{i}] missing name/dates_text"))


def _check_other_knowledge(failures: list[str]) -> None:
    cases = [
        ("company", ["company", "name"]),
        ("company", ["company", "phone"]),
        ("business_hours", ["business", "timezone"]),
        ("business_hours", ["business", "work_hours", "start"]),
        ("business_hours", ["business", "work_hours", "end"]),
        ("business_hours", ["business", "business_hours", "start"]),
        ("business_hours", ["business", "business_hours", "end"]),
        ("business_hours", ["business", "slot", "duration_minutes"]),
        ("business_hours", ["business", "slot", "buffer_minutes"]),
        ("adult_defaults", ["adult_defaults", "event_placeholder"]),
        ("adult_defaults", ["adult_defaults", "event_name_placeholder"]),
        ("adult_defaults", ["adult_defaults", "atmosphere"]),
        ("adult_defaults", ["adult_defaults", "event", "name"]),
        ("i18n/ka_months", ["months_nominative"]),
        ("i18n/ka_months", ["month_stems"]),
    ]
    for name, path in cases:
        try:
            doc = load_knowledge(name)
        except KnowledgeNotFound as exc:
            failures.append(_fail(f"{name} load: {exc}"))
            continue
        node: object = doc
        for segment in path:
            if not isinstance(node, dict) or segment not in node:
                failures.append(
                    _fail(f"{name}: required key path "
                          f"{'.'.join(path)!r} missing")
                )
                node = None
                break
            node = node[segment]
        if node in (None, "", [], {}):
            failures.append(
                _fail(f"{name}: required value at "
                      f"{'.'.join(path)!r} is empty")
            )
        else:
            _ok(f"{name}: {'.'.join(path)} present")

    # i18n month integrity
    try:
        m = load_knowledge("i18n/ka_months")
        if len(m["months_nominative"]) != 12:
            failures.append(
                _fail(f"i18n.months_nominative count != 12 "
                      f"({len(m['months_nominative'])})")
            )
        if len(m["month_stems"]) != 12:
            failures.append(
                _fail(f"i18n.month_stems count != 12 "
                      f"({len(m['month_stems'])})")
            )
    except Exception as exc:
        failures.append(_fail(f"i18n/ka_months integrity: {exc}"))


def _check_incorrect_location_absent(failures: list[str]) -> None:
    # 1) No knowledge file contains the incorrect phrase.
    knowledge_hits: list[str] = []
    for path in KNOWLEDGE_DIR.rglob("*.yaml"):
        try:
            text = path.read_text(encoding="utf-8")
        except Exception as exc:
            failures.append(_fail(f"could not read {path}: {exc}"))
            continue
        if INCORRECT_LOCATION_FRAGMENT in text:
            knowledge_hits.append(str(path.relative_to(REPO_ROOT)))
    if knowledge_hits:
        failures.append(
            _fail(f"incorrect location phrase found in knowledge: "
                  f"{knowledge_hits}")
        )
    else:
        _ok(f"incorrect location phrase absent from "
            f"all {KNOWLEDGE_DIR.name}/*.yaml")

    # 2) No customer-facing template / prompt should contain the incorrect
    # phrase. Scan app/agent/templates and app/agent/prompts.
    customer_dirs = [
        REPO_ROOT / "app" / "agent" / "templates",
        REPO_ROOT / "app" / "agent" / "prompts",
    ]
    facing_hits: list[str] = []
    for d in customer_dirs:
        for path in d.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix not in {".yaml", ".md"}:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except Exception:
                continue
            if INCORRECT_LOCATION_FRAGMENT in text:
                facing_hits.append(str(path.relative_to(REPO_ROOT)))
    if facing_hits:
        failures.append(
            _fail(f"incorrect location phrase found in customer-facing "
                  f"files: {facing_hits}")
        )
    else:
        _ok("incorrect location phrase absent from "
            "templates/ + prompts/")


def _check_settings_camp_price(failures: list[str]) -> None:
    # Settings.CAMP_PRICE must source from knowledge when CAMP_PRICE env
    # var is unset. We unset CAMP_PRICE for this check.
    saved = os.environ.pop("CAMP_PRICE", None)
    try:
        # Force re-evaluation by importing fresh.
        from app.config import Settings
        s = Settings.from_env()
        if s.CAMP_PRICE != AUTHORITATIVE_PRICE:
            failures.append(
                _fail(f"Settings.CAMP_PRICE != authoritative "
                      f"({s.CAMP_PRICE!r} vs {AUTHORITATIVE_PRICE}); "
                      f"config may be holding an independent default")
            )
        else:
            _ok(f"Settings.CAMP_PRICE sourced from knowledge "
                f"== {AUTHORITATIVE_PRICE}")
    finally:
        if saved is not None:
            os.environ["CAMP_PRICE"] = saved


def main() -> int:
    reset_cache()
    failures: list[str] = []
    _check_camp(failures)
    _check_other_knowledge(failures)
    _check_incorrect_location_absent(failures)
    _check_settings_camp_price(failures)

    print()
    if failures:
        print(f"=== {len(failures)} failure(s) ===")
        for f in failures:
            print(f)
        return 1
    print("Knowledge migration verification: ALL CHECKS PASSED.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
