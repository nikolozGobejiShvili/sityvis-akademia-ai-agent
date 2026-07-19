"""Admin Panel MVP — section / template loader & writer.

This module is the single source of truth for admin-editable program
config. Files live under ``data/admin_config/``:

  * sections.yaml          — program registry (summer_camp, sunday_school,
                              adult_events, …)
  * templates.yaml         — DM / public-reply / followup wording
  * business_hours.yaml    — operator-visible mirror of canonical hours
  * manager_contacts.yaml  — non-secret operator-facing placeholders

Safety guarantees:

  * Reads tolerate missing / malformed YAML — every loader returns a
    safe default (empty list / empty dict) and logs a warning.
  * Writes use a small ``.bak`` rotation so a malformed save never
    destroys the previous good config.
  * Hashtag matching is case-folded and "#"-stripped on BOTH sides so
    Latin and Georgian tags compare reliably.
  * Template rendering uses a forgiving ``str.format_map`` subclass —
    missing placeholders become empty strings instead of raising.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


def _resolve_base_dir() -> Path:
    """Resolve the project root defensively.

    Tries `app.config.BASE_DIR` first (the canonical source). Falls
    back to walking up from this file's location so the loader still
    works when ``app.config`` is a test mock that doesn't expose
    BASE_DIR (see test_agent.py top-of-file module stubbing).
    """
    try:
        from app.config import BASE_DIR as _base
        return Path(_base)
    except Exception:
        pass
    try:
        from app.config import DATA_DIR as _data_dir
        return Path(_data_dir).parent
    except Exception:
        pass
    # Last resort: walk up from this file. app/services/x.py → project root
    return Path(__file__).resolve().parent.parent.parent


# Config files live under <project>/data/admin_config/ by default. On Railway the
# container FS is ephemeral (admin edits wiped on every redeploy), so an operator
# mounts a persistent volume and points ADMIN_CONFIG_DIR at it. Writes go to that
# dir; reads overlay volume-then-default (see _config_read_path). Env unset ⇒
# identical to before.
_DEFAULT_ADMIN_CONFIG_DIR: Path = _resolve_base_dir() / "data" / "admin_config"


def _resolve_admin_config_dir() -> Path:
    override = os.environ.get("ADMIN_CONFIG_DIR", "").strip()
    if override:
        return Path(override)
    return _DEFAULT_ADMIN_CONFIG_DIR


ADMIN_CONFIG_DIR: Path = _resolve_admin_config_dir()
SECTIONS_PATH: Path = ADMIN_CONFIG_DIR / "sections.yaml"
TEMPLATES_PATH: Path = ADMIN_CONFIG_DIR / "templates.yaml"
BUSINESS_HOURS_PATH: Path = ADMIN_CONFIG_DIR / "business_hours.yaml"
MANAGER_CONTACTS_PATH: Path = ADMIN_CONFIG_DIR / "manager_contacts.yaml"


VALID_STATUSES = ("active", "hidden", "full", "coming_soon", "ended")
# Camp (summer_camp) status values the live agent understands. "ended" (2026-07-01)
# lets the operator turn the camp off after the last stream without a code change.
CAMP_STATUSES = ("active", "hidden", "full", "coming_soon", "ended")
_CAMP_REGISTRATION_OPEN_VALUES = ("open", "active", "enabled", "on", "true", "1", "yes")
_CAMP_REGISTRATION_CLOSED_VALUES = (
    "closed", "inactive", "disabled", "off", "false", "0", "no",
)
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_]*$")
ADULT_NO_ACTIVE_EVENTS_REPLY = "ამ ეტაპზე აქტიური ღონისძიება სიაში არ მაქვს. თუ გსურთ, მენეჯერთან დაგაკავშირებთ."


def parse_price_gel(price_text: str | None) -> int | None:
    """Extract the leading integer from a free-form Georgian price string.

    Examples:
        "2200"           → 2200
        "2200 ლარი"      → 2200
        "2,200 ლარი"     → 2200
        "ფასი ზუსტდება"  → None
        ""               → None

    The match is anchored on the FIRST integer in the string so a
    trailing year or month doesn't get picked up by accident. Commas
    and spaces inside the number are tolerated so "2,200" works the
    same as "2200".
    """
    if not price_text:
        return None
    cleaned = str(price_text).strip()
    if not cleaned:
        return None
    # Strip thousands-separator commas BEFORE the digit-only sweep so
    # "2,200" reads as a single 2200, not two numbers.
    cleaned = cleaned.replace(",", "")
    digits = ""
    started = False
    for ch in cleaned:
        if ch.isdigit():
            digits += ch
            started = True
        elif started:
            # First non-digit AFTER we started — stop. This means
            # "2200 ლარი 2026 წელი" parses to 2200, not 22002026.
            break
    if not digits:
        return None
    try:
        n = int(digits)
    except ValueError:
        return None
    if n <= 0 or n > 10**9:
        return None
    return n


# -- public read API -------------------------------------------------------


def normalize_hashtag(tag: str) -> str:
    """Return a hashtag in canonical comparison form.

    Mirrors `comment_service._normalize_hashtag`: strip whitespace,
    drop a leading '#', casefold. Safe no-op for Georgian Mkhedruli
    (no case); correct for Latin.
    """
    if not tag:
        return ""
    return tag.strip().lstrip("#").strip().casefold()


def _safe_load_yaml(path: Path) -> Any:
    """Load YAML safely. Missing/malformed → None (caller decides default).

    Live QA Patch (2026-06-05) — Bug 4 contract: this loader reads the
    file fresh on EVERY call (no module-level cache). When the
    operator saves a new value via the Admin Panel, the next
    `get_section` / `get_adult_events` call returns the updated value
    *without* needing a server restart. The mtime check below is a
    belt-and-braces log line so an operator can confirm the right
    file version is being read.
    """
    if not path.exists():
        logger.info("[admin_config] %s not present — using defaults", path.name)
        return None
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = 0
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        logger.debug(
            "[admin_config] %s loaded mtime=%s", path.name, mtime,
        )
        return data
    except yaml.YAMLError as exc:
        logger.warning(
            "[admin_config] %s YAML parse failed — using defaults: %s",
            path.name, exc,
        )
        return None
    except Exception as exc:
        logger.warning(
            "[admin_config] %s read failed — using defaults: %s",
            path.name, exc,
        )
        return None


def load_sections() -> list[dict[str, Any]]:
    """Return the full sections list from sections.yaml.

    Returns an empty list on missing/malformed file. Each entry is a
    dict; callers must tolerate missing optional keys.
    """
    raw = _safe_load_yaml(SECTIONS_PATH)
    if not isinstance(raw, dict):
        return []
    sections = raw.get("sections")
    if not isinstance(sections, list):
        return []
    return [dict(s) for s in sections if isinstance(s, dict) and s.get("id")]


def get_section(section_id: str) -> dict[str, Any] | None:
    if not section_id:
        return None
    for section in load_sections():
        if section.get("id") == section_id:
            return section
    return None


def get_active_sections() -> list[dict[str, Any]]:
    """Return sections whose ``status`` is "active", whitespace/case-insensitive.

    Phase 0a hardening (2026-07-20): an admin-saved status of ``"Active"`` or
    ``" active "`` was silently excluded by the previous exact-match compare.
    Shipped `sections.yaml` uses lowercase `active`/`coming_soon`, so behavior
    for existing data is byte-identical — only case/whitespace VARIANTS of
    "active" are newly included. Missing/empty status is NOT defaulted to
    active (still excluded), matching the previous contract.
    """
    return [
        s for s in load_sections()
        if str(s.get("status") or "").strip().casefold() == "active"
    ]


def get_camp_status() -> str:
    """Return the operator-configured ``summer_camp.status``, normalised to
    lower-case and validated against :data:`CAMP_STATUSES`.

    Defaults to ``"active"`` when the field is missing, empty, unknown/invalid,
    or unreadable — so a bad/absent value can NEVER accidentally turn the camp
    off. Never raises. This is the single source of truth the live agent reads
    to decide whether the camp is being sold (see
    ``parent_flow._maybe_handle_camp_status``)."""
    try:
        section = get_section("summer_camp") or {}
        raw = (section.get("status") or "").strip().lower()
    except Exception:  # pragma: no cover - defensive: never disable camp on error
        return "active"
    return raw if raw in CAMP_STATUSES else "active"


def is_camp_active() -> bool:
    """True when the camp is being sold (status ``active``); False for
    ``hidden`` / ``full`` / ``coming_soon`` / ``ended``. Missing/invalid â†’ True."""
    return get_camp_status() == "active"


def get_camp_registration_status() -> str:
    """Return the independent camp registration gate.

    Missing/empty ``registration_status`` defaults to ``open`` for backward
    compatibility. An explicitly malformed value fails closed so a typo cannot
    leak registration URLs or booking entry points during a closed-registration
    operating period.
    """
    try:
        section = get_section("summer_camp") or {}
        raw = section.get("registration_status")
    except Exception:  # pragma: no cover - registration actions fail closed
        return "closed"
    if raw is None:
        return "open"
    value = str(raw).strip().lower()
    if not value:
        return "open"
    if value in _CAMP_REGISTRATION_OPEN_VALUES:
        return "open"
    if value in _CAMP_REGISTRATION_CLOSED_VALUES:
        return "closed"
    return "closed"


def is_camp_registration_open() -> bool:
    """True when camp registration/booking CTAs may be shown."""
    return get_camp_registration_status() == "open"


def is_camp_registration_closed() -> bool:
    """True when camp registration/booking CTAs must be suppressed."""
    return not is_camp_registration_open()


def get_sunday_school_status() -> dict[str, Any]:
    """Operator-editable Sunday-School status from the ``sunday_school`` section
    of ``sections.yaml`` — so the launch month / details are NOT hardcoded in
    the deterministic handler. Returns safe defaults (no invented month) when a
    field or the whole section is missing. Never raises.

    Keys: ``availability_text`` (e.g. „საკვირაო სკოლა ივლისში დაემატება.";
    empty when unset — caller uses a no-date fallback), ``details_text``
    (e.g. „დეტალები ზუსტდება"; may be empty), ``status`` (default
    ``coming_soon``), ``handoff_enabled`` (default True), ``lead_type``
    (default ``sunday_school``)."""
    try:
        section = get_section("sunday_school") or {}
    except Exception:  # pragma: no cover - defensive
        section = {}

    def _txt(key: str) -> str:
        v = section.get(key)
        return v.strip() if isinstance(v, str) else ""

    handoff = section.get("handoff_enabled")
    return {
        "availability_text": _txt("availability_text"),
        "details_text": _txt("details_text"),
        "status": _txt("status") or "coming_soon",
        "handoff_enabled": True if handoff is None else bool(handoff),
        "lead_type": _txt("lead_type") or "sunday_school",
    }


def find_section_by_hashtag(tag: str) -> dict[str, Any] | None:
    """Return the first section whose hashtag list contains ``tag``."""
    normalized = normalize_hashtag(tag)
    if not normalized:
        return None
    for section in load_sections():
        for cand in section.get("hashtags") or []:
            if normalize_hashtag(cand) == normalized:
                return section
    return None


def find_section_from_post_hashtags(
    post_hashtags: list[str],
) -> dict[str, Any] | None:
    """Primary routing path — caption hashtags drive section selection.

    First match wins; sections appear in the order they're listed in
    sections.yaml, so the operator controls priority by ordering.
    """
    if not post_hashtags:
        return None
    normalized_post = {normalize_hashtag(t) for t in post_hashtags}
    normalized_post.discard("")
    if not normalized_post:
        return None
    for section in load_sections():
        section_tags = {
            normalize_hashtag(t) for t in (section.get("hashtags") or [])
        }
        if section_tags & normalized_post:
            return section
    return None


def find_section_from_comment_text(comment_text: str) -> dict[str, Any] | None:
    """Secondary fallback — only consulted when the post caption had no
    configured hashtag."""
    if not comment_text:
        return None
    tags = re.findall(r"#([a-zA-Z0-9_Ⴀ-ჿ]+)", comment_text)
    return find_section_from_post_hashtags(tags)


# ── Section-level post_id → section mapping (2026-07-04, ADDITIVE) ───────────
# Deterministic fallback so a comment under a Camp / Sunday-School / Adult post
# routes to the right section even when the Meta caption fetch fails or the
# caption carries no literal „#" hashtag. This NEVER touches, reads, or
# overwrites section `hashtags` — hashtag routing (`find_section_from_post_hashtags`)
# is completely unchanged and still works with no post_id mapping present.
#
# Canonical operator field: ``facebook_post_ids`` (a YAML list of post ids).
# The singular ``facebook_post_id`` and the ``post_ids`` / ``post_id`` aliases
# are also accepted so an operator can use whichever is convenient. First
# matching section wins (sections.yaml order).
_SECTION_POST_ID_FIELDS: tuple[str, ...] = (
    "facebook_post_ids", "post_ids", "facebook_post_id", "post_id",
)


def _section_post_ids(section: dict[str, Any]) -> set[str]:
    """Collect the post ids mapped onto a section from any accepted field
    (list or scalar). Returns an empty set when none are configured — so an
    unmapped section is simply skipped, never matched."""
    ids: set[str] = set()
    if not isinstance(section, dict):
        return ids
    for field in _SECTION_POST_ID_FIELDS:
        val = section.get(field)
        if not val:
            continue
        if isinstance(val, (list, tuple, set)):
            ids.update(str(v).strip() for v in val if str(v).strip())
        else:
            s = str(val).strip()
            if s:
                ids.add(s)
    return ids


def find_section_from_post_id(post_id: str) -> dict[str, Any] | None:
    """Return the section explicitly mapped to ``post_id`` via a section-level
    post-id field, or ``None`` when no section maps it.

    Additive fallback to :func:`find_section_from_post_hashtags`: consulted
    BEFORE the caption fetch by the comment router, but it NEVER affects hashtag
    routing and NEVER mutates any section data (read-only). First match wins.
    """
    pid = (post_id or "").strip()
    if not pid:
        return None
    for section in load_sections():
        if pid in _section_post_ids(section):
            return section
    return None


# -- templates -------------------------------------------------------------


def load_templates() -> dict[str, str]:
    """Return all templates as {template_id: template_string}."""
    raw = _safe_load_yaml(TEMPLATES_PATH)
    if not isinstance(raw, dict):
        return {}
    templates = raw.get("templates")
    if not isinstance(templates, dict):
        return {}
    return {str(k): str(v) for k, v in templates.items()}


def get_template(template_id: str) -> str | None:
    if not template_id:
        return None
    return load_templates().get(template_id)


class _SafeDict(dict):
    """A dict that returns "" for missing keys when used with format_map.

    Keeps the template-rendering path crash-free even when a section is
    missing optional fields.
    """

    def __missing__(self, key: str) -> str:
        return ""


def render_template(template_id: str, context: dict[str, Any]) -> str:
    """Render a template with a forgiving placeholder substitution.

    Returns an empty string when the template is missing — callers must
    keep their existing fallback (e.g. the rich-DM builder constants).
    A KeyError from `.format_map` is impossible because `_SafeDict`
    substitutes missing keys with "".
    """
    template = get_template(template_id)
    if not template:
        logger.info(
            "[admin_config] render_template: template_id=%r missing",
            template_id,
        )
        return ""
    safe_ctx = _SafeDict({k: ("" if v is None else v) for k, v in (context or {}).items()})
    try:
        return template.format_map(safe_ctx).strip()
    except Exception as exc:
        # Format spec errors (e.g. `{foo:bad}`) or other surprises.
        logger.warning(
            "[admin_config] render_template %s failed — returning empty: %s",
            template_id, exc,
        )
        return ""


# -- validation ------------------------------------------------------------


def validate_section(data: dict[str, Any]) -> list[str]:
    """Return a list of human-readable error messages (empty when valid)."""
    errors: list[str] = []

    section_id = (data.get("id") or "").strip()
    if not section_id:
        errors.append("id is required")
    elif not SLUG_RE.match(section_id):
        errors.append("id must be slug-like (a-z, 0-9, underscore; start with letter/digit)")

    if not (data.get("name") or "").strip():
        errors.append("name is required")

    if not (data.get("type") or "").strip():
        errors.append("type is required")

    status = (data.get("status") or "").strip()
    if status not in VALID_STATUSES:
        errors.append(f"status must be one of {VALID_STATUSES}")

    hashtags = data.get("hashtags") or []
    if not isinstance(hashtags, list) or not hashtags:
        errors.append("hashtags list must not be empty")

    template_id = (data.get("auto_dm_template_id") or "").strip()
    if not template_id:
        errors.append("auto_dm_template_id is required")

    # Cross-check: duplicate id / duplicate active hashtags vs existing.
    existing = load_sections()
    existing_ids = {s.get("id") for s in existing if s.get("id") != section_id}
    if section_id in existing_ids:
        errors.append(f"section id {section_id!r} already exists")

    if hashtags and isinstance(hashtags, list):
        normalized_new = {normalize_hashtag(t) for t in hashtags}
        normalized_new.discard("")
        for other in existing:
            if other.get("id") == section_id:
                continue
            if (other.get("status") or "") != "active":
                continue
            other_tags = {
                normalize_hashtag(t) for t in (other.get("hashtags") or [])
            }
            collision = normalized_new & other_tags
            if collision:
                errors.append(
                    f"hashtag(s) {sorted(collision)!r} already used by "
                    f"active section {other.get('id')!r}",
                )

    return errors


# -- write API -------------------------------------------------------------


def _ensure_admin_config_dir() -> None:
    ADMIN_CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def _backup(path: Path) -> None:
    """Move existing file to .bak before overwriting (best-effort)."""
    if not path.exists():
        return
    try:
        shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
    except Exception as exc:
        logger.warning("[admin_config] backup of %s failed: %s", path.name, exc)


def _dump_yaml(path: Path, data: Any) -> None:
    text = yaml.safe_dump(
        data, allow_unicode=True, sort_keys=False, default_flow_style=False,
    )
    _ensure_admin_config_dir()
    _backup(path)
    path.write_text(text, encoding="utf-8")


def save_sections(sections: list[dict[str, Any]]) -> None:
    _dump_yaml(SECTIONS_PATH, {"sections": sections})


def save_section(section: dict[str, Any]) -> list[str]:
    """Insert OR update a section by id. Returns validation errors (empty on success)."""
    errors = validate_section(section)
    if errors:
        return errors
    sections = load_sections()
    section_id = section["id"]
    updated = False
    for i, existing in enumerate(sections):
        if existing.get("id") == section_id:
            sections[i] = section
            updated = True
            break
    if not updated:
        sections.append(section)
    save_sections(sections)
    return []


def update_section(section_id: str, patch: dict[str, Any]) -> list[str]:
    """Apply a partial update to an existing section. Returns errors."""
    current = get_section(section_id)
    if current is None:
        return [f"section {section_id!r} not found"]
    merged = {**current, **patch, "id": section_id}
    return save_section(merged)


def delete_section(section_id: str) -> bool:
    sections = load_sections()
    new_list = [s for s in sections if s.get("id") != section_id]
    if len(new_list) == len(sections):
        return False
    save_sections(new_list)
    return True


def save_template(template_id: str, text: str) -> None:
    templates = load_templates()
    templates[template_id] = text
    _dump_yaml(TEMPLATES_PATH, {"templates": templates})


# -- section-aware comment DM rendering ------------------------------------


def _locative_location(location: str) -> str:
    """Duplicate of comment_service._locative_location to avoid cycles."""
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


def build_section_dm(section: dict[str, Any]) -> str:
    """Render a section's comment-DM using its `auto_dm_template_id`.

    Returns "" on any failure so the caller can keep its existing
    rich-DM fallback. The summer_camp path enriches the context with a
    locative location and a comma-joined stream string so the
    canonical template stays readable.
    """
    if not section:
        return ""

    template_id = section.get("auto_dm_template_id") or ""
    if not template_id:
        return ""

    context = dict(section)

    # summer_camp needs a couple of derived fields the template expects.
    location = section.get("location") or ""
    context["location_locative"] = _locative_location(location)

    streams = section.get("streams") or []
    # Camp Stream Date Filter — for a camp section, drop streams whose start
    # date has already arrived so a started stream is never advertised in the
    # first-contact DM. Non-camp sections (e.g. adult_events) keep their
    # streams untouched — the rule is camp-specific.
    if (section.get("type") or "").strip().lower() == "camp":
        streams = get_visible_camp_streams(streams, year=section.get("year"))
    stream_dates = ", ".join(
        (s.get("dates_text") or "").strip()
        for s in streams
        if isinstance(s, dict) and (s.get("dates_text") or "").strip()
    )
    context["stream_dates"] = stream_dates

    # Surface event-list placeholder for the adult template — populated
    # by the comment handler when it has the parsed events on hand.
    context.setdefault("events_list", "")

    return render_template(template_id, context)


# -- business hours / manager mirrors --------------------------------------


def get_camp_facts() -> dict[str, Any]:
    """Return the canonical summer-camp facts dict — admin-first.

    Resolution order, per field:
      1. ``summer_camp`` entry in ``data/admin_config/sections.yaml``
         (operator-editable, primary source).
      2. ``camp`` block in ``app/agent/knowledge/camp_2026.yaml``
         (legacy canonical YAML — kept as fallback so a brand-new
         deployment without admin_config still works).

    Returned shape mirrors ``camp_2026.yaml``'s ``camp`` block so every
    existing call site (``parent_tool_executor._get_camp_info``,
    ``parent_turn_router``, ``parent_reply_composer``,
    ``parent_turn_analyzer`` …) can swap in this helper without
    additional adapters. Missing fields are simply absent — the
    consumer code is already defensive (``camp.get(...)``).

    Price normalisation:
      * If the admin section has ``price_text`` set, it wins for the
        user-facing display string.
      * ``price_gel`` is parsed from ``price_text`` if it's an integer
        string (e.g. "2200" → 2200) so the legacy code path that reads
        ``camp.get("price_gel")`` for integer arithmetic keeps working.

    Stream normalisation:
      * Admin sections store ``streams`` as a list of dicts with
        ``name`` + ``dates_text`` (matching camp_2026.yaml shape) OR
        ``start``/``end``/``status``. We pass them through unchanged
        when the dates_text variant is present; otherwise we fold
        start/end into a ``"start - end"`` string.

    Never raises — falls back to ``{}`` on any error.
    """
    fallback: dict[str, Any] = {}
    try:
        from app.agent.services.knowledge_loader import load_knowledge

        fallback = dict(load_knowledge("camp_2026").get("camp") or {})
    except Exception as exc:
        logger.warning(
            "[admin_config] get_camp_facts: camp_2026 fallback unavailable: %s",
            exc,
        )

    admin_section: dict[str, Any] | None = None
    try:
        admin_section = get_section("summer_camp")
    except Exception as exc:
        logger.warning(
            "[admin_config] get_camp_facts: admin_config load failed: %s",
            exc,
        )

    if not isinstance(admin_section, dict):
        return fallback

    merged: dict[str, Any] = dict(fallback)

    # Simple scalar fields — admin wins when truthy / non-empty.
    for key in (
        "name", "year", "location", "duration_days", "registration_url",
        "phone", "manager_contact",
    ):
        admin_val = admin_section.get(key)
        if admin_val not in (None, ""):
            merged[key] = admin_val

    # age_min / age_max — admin wins when integers; if admin set them
    # to null we keep the fallback.
    for key in ("age_min", "age_max"):
        admin_val = admin_section.get(key)
        if isinstance(admin_val, int):
            merged[key] = admin_val

    # Price — operator-edited price_text is the user-facing display
    # value AND the source of truth for price_gel. If both fields are
    # set but disagree (live QA bug: form updated price_text=2200 while
    # price_gel kept its stale 2150), the integer parsed from price_text
    # wins so the LLM never serves a stale number.
    price_text = (admin_section.get("price_text") or "").strip()
    raw_price_gel = admin_section.get("price_gel")
    parsed_from_text = parse_price_gel(price_text) if price_text else None

    if parsed_from_text is not None:
        # Always prefer the number derived from the operator's most
        # recent display string. Catches a stale price_gel that was
        # left behind by an older save.
        merged["price_gel"] = parsed_from_text
    elif isinstance(raw_price_gel, int):
        merged["price_gel"] = raw_price_gel

    if price_text:
        merged["price_text"] = price_text

    # Streams — admin_config stores either {name, dates_text, status}
    # or {name, start, end, status}. Normalise both into the
    # dates_text form the rest of the codebase expects.
    raw_streams = admin_section.get("streams")
    if isinstance(raw_streams, list) and raw_streams:
        normalised_streams: list[dict[str, Any]] = []
        for s in raw_streams:
            if not isinstance(s, dict):
                continue
            name = (s.get("name") or "").strip()
            dates_text = (s.get("dates_text") or "").strip()
            if not dates_text:
                start = (s.get("start") or "").strip()
                end = (s.get("end") or "").strip()
                if start and end:
                    dates_text = f"{start} - {end}"
                elif start:
                    dates_text = start
            entry: dict[str, Any] = {"name": name, "dates_text": dates_text}
            status = (s.get("status") or "").strip()
            if status:
                entry["status"] = status
            normalised_streams.append(entry)
        if normalised_streams:
            merged["streams"] = normalised_streams

    # Pass-through list fields — admin wins when non-empty.
    for key in ("included_items", "discounts", "discovery_questions"):
        admin_val = admin_section.get(key)
        if isinstance(admin_val, list) and admin_val:
            # camp_2026.yaml uses "includes"; admin uses "included_items"
            # → keep BOTH so consumers reading either name keep working.
            if key == "included_items":
                merged["includes"] = list(admin_val)
                merged["included_items"] = list(admin_val)
            else:
                merged[key] = list(admin_val)

    # Payment terms — admin gives a free-form sentence; we expose it
    # alongside the legacy structured ``payment`` dict.
    payment_terms = (admin_section.get("payment_terms") or "").strip()
    if payment_terms:
        merged["payment_terms"] = payment_terms

    # Manager-phone source-of-truth unification: camp-info `phone` is exposed
    # only from the canonical Admin Config manager-contact accessor. Never fall
    # back to legacy knowledge, environment, or user/callback data.
    canonical_phone = (get_manager_phone() or "").strip()
    if canonical_phone:
        merged["phone"] = canonical_phone
    else:
        merged.pop("phone", None)
    return merged


def get_camp_age_bounds() -> tuple[int, int]:
    """Canonical camp age band ``(age_min, age_max)`` from Admin Config
    (`get_camp_facts()` → ``sections.yaml`` summer_camp over ``camp_2026.yaml``).

    Returns the safe default ``(9, 17)`` when a value is missing or malformed,
    so an operator age-range edit in the Admin Panel reaches every consumer
    instead of leaving eligibility/under-age/prompt paths on a stale 9–17.
    Reads camp facts ONLY through ``get_camp_facts()`` (never camp_2026.yaml
    directly), never mutates config, and never raises."""
    default = (9, 17)
    try:
        camp = get_camp_facts() or {}
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning(
            "[admin_config] get_camp_age_bounds: get_camp_facts failed: %s", exc,
        )
        return default

    def _bound(key: str, fallback: int) -> int:
        raw = camp.get(key)
        if raw in (None, ""):
            return fallback
        try:
            return int(raw)
        except (TypeError, ValueError):
            logger.warning(
                "[admin_config] get_camp_age_bounds: malformed %s=%r — using %d",
                key, raw, fallback,
            )
            return fallback

    return (_bound("age_min", default[0]), _bound("age_max", default[1]))


# -- adult events ---------------------------------------------------------


# Default min_age when an adult event entry omits the field.
# Lowered from 18 → 13 by the ADULT Off-Topic Guard + Default Min-Age
# Fix patch (2026-06-02). Live operator request: adult cultural
# evenings open to teens 13+ unless an individual event is explicitly
# restricted higher. Per-event ``min_age`` STILL overrides — an event
# with `min_age: 18` continues to filter out under-18 users.
ADULT_EVENT_DEFAULT_MIN_AGE: int = 13


def _coerce_int(value: Any, default: int | None = None) -> int | None:
    """Best-effort cast to int. Returns default on failure."""
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return default
        try:
            return int(stripped)
        except ValueError:
            return default
    return default


def _normalize_adult_event(
    raw: dict[str, Any], idx: int | None = None,
) -> dict[str, Any]:
    """Return a fully populated adult-event dict with every field the
    LLM tool surface expects, applying safe defaults for missing keys.

    The ``min_age`` field is required for age-filtering — when the
    operator omits it, default to ``ADULT_EVENT_DEFAULT_MIN_AGE`` (13).

    Live QA Patch (2026-06-05) — Bug 3: 13 is the GLOBAL FLOOR.
    Per-event ``min_age`` can override UPWARD only. An event with
    ``min_age: 10`` (or 0 / negative / missing) is treated as 13. An
    event with ``min_age: 18`` keeps 18. This codifies the business
    rule „კულტურული საღამოები 13 წლიდან" and prevents operator typos
    from accidentally opening events to younger audiences.

    Multi-event Patch (2026-06-08): also preserves the optional
    ``description``, ``facebook_post_id``, ``tags``, ``price_gel`` and
    ``payment_terms`` fields so they round-trip through the editor and
    surface in the LLM tool layer when present. ``idx`` is used to
    auto-derive a stable id when one is missing (``event_<idx>``).
    """
    event_id = str(raw.get("id") or "").strip()
    if not event_id and idx is not None:
        event_id = f"event_{idx}"
    title = str(raw.get("title") or raw.get("name") or "").strip()
    status_raw = (raw.get("status") or "").strip().lower()
    # Default to "active" when missing so a freshly added event surfaces;
    # otherwise preserve the literal value (operator may save "hidden" /
    # "coming_soon" — those still count as NOT active for the agent).
    status = status_raw or "active"
    min_age = _coerce_int(raw.get("min_age"), ADULT_EVENT_DEFAULT_MIN_AGE)
    if min_age is None:
        min_age = ADULT_EVENT_DEFAULT_MIN_AGE
    # Apply the global floor — see docstring above.
    min_age = max(int(min_age), ADULT_EVENT_DEFAULT_MIN_AGE)
    seats = _coerce_int(raw.get("seats_available"), 0) or 0
    price_gel = _coerce_int(raw.get("price_gel"), None)

    description = str(raw.get("description") or "").strip()
    theme = str(raw.get("theme") or description or "").strip()

    # sold_out is a STRICT operator flag — never inferred from
    # `seats_available`. `status: sold_out` is treated as a shortcut.
    raw_sold_out = raw.get("sold_out")
    status_raw_lower = status_raw or ""
    if isinstance(raw_sold_out, bool):
        sold_out = raw_sold_out
    elif isinstance(raw_sold_out, str):
        sold_out = raw_sold_out.strip().lower() in {"true", "yes", "1"}
    else:
        sold_out = False
    if status_raw_lower == "sold_out":
        sold_out = True

    raw_tags = raw.get("tags")
    if isinstance(raw_tags, list):
        tags = [str(t).strip() for t in raw_tags if str(t).strip()]
    elif isinstance(raw_tags, str) and raw_tags.strip():
        tags = [
            t.strip() for t in raw_tags.split(",") if t.strip()
        ]
    else:
        tags = []

    return {
        "id": event_id,
        "title": title,
        "status": status,
        "min_age": int(min_age),
        "date_text": str(raw.get("date_text") or raw.get("date") or "").strip(),
        "location": str(raw.get("location") or "").strip(),
        "description": description,
        "theme": theme,
        "guest": str(raw.get("guest") or "").strip(),
        "format": str(raw.get("format") or "").strip(),
        "price_text": str(raw.get("price_text") or "").strip(),
        "price_gel": price_gel if isinstance(price_gel, int) else None,
        "reservation_url": str(
            raw.get("reservation_url") or raw.get("payment_url") or "",
        ).strip(),
        "payment_terms": str(raw.get("payment_terms") or "").strip(),
        "facebook_post_id": str(raw.get("facebook_post_id") or "").strip(),
        "tags": tags,
        "seats_available": int(seats),
        "sold_out": bool(sold_out),
        "active": status == "active",
    }


def normalize_adult_event(
    event: dict[str, Any], idx: int | None = None,
) -> dict[str, Any]:
    """Public wrapper around ``_normalize_adult_event``.

    Use this from outside the module (tests, agent code) when you need
    a stable normalised view of an event dict — the LLM tool layer
    already uses the private helper internally.
    """
    return _normalize_adult_event(event, idx=idx)


def _build_fallback_event_from_section(
    section: dict[str, Any],
) -> dict[str, Any] | None:
    """Live QA Patch (2026-06-05) — Bug 1A.

    When the Admin Panel saves an adult event by writing into the
    section-level fields (no `events[]` sub-list yet — the current
    Admin Panel UI predates the multi-event editor), derive one
    fallback event from those section-level fields so the LLM tool
    layer surfaces SOMETHING rather than the misleading „no active
    events" reply.

    Triggers only when:
      * the section status is `active`;
      * at least one event-like field is populated on the section
        (description_short, price_text, price_gel, location, streams,
        payment_terms).

    Returns the synthesised event dict, or None when no fallback
    should fire.
    """
    if not isinstance(section, dict):
        return None
    status = (section.get("status") or "").strip().lower()
    if status != "active":
        return None

    description_short = (section.get("description_short") or "").strip()
    price_text = (section.get("price_text") or "").strip()
    price_gel_raw = section.get("price_gel")
    location = (section.get("location") or "").strip()
    streams = section.get("streams") or []
    payment_terms = (section.get("payment_terms") or "").strip()

    has_event_like = (
        bool(description_short)
        or bool(price_text)
        or price_gel_raw is not None
        or bool(location)
        or bool(streams)
        or bool(payment_terms)
    )
    if not has_event_like:
        return None

    title = description_short or (section.get("name") or "").strip()
    if not title:
        return None

    date_text = ""
    if isinstance(streams, list) and streams:
        first = streams[0] if isinstance(streams[0], dict) else {}
        s_name = (first.get("name") or "").strip()
        s_dates = (first.get("dates_text") or "").strip()
        if s_name and s_dates:
            date_text = f"{s_name} — {s_dates}"
        else:
            date_text = s_name or s_dates

    raw_min_age = _coerce_int(
        section.get("age_min"), ADULT_EVENT_DEFAULT_MIN_AGE,
    )
    if raw_min_age is None:
        raw_min_age = ADULT_EVENT_DEFAULT_MIN_AGE
    effective_min_age = max(int(raw_min_age), ADULT_EVENT_DEFAULT_MIN_AGE)

    reservation_url = (
        (section.get("reservation_url") or "").strip()
        or payment_terms
    )

    fallback_id = (
        (section.get("id") or "adult_events").strip() + "_default"
    )

    return {
        "id": fallback_id,
        "title": title,
        "status": "active",
        "min_age": effective_min_age,
        "date_text": date_text,
        "location": location,
        "theme": description_short,
        "guest": "",
        "format": "",
        "price_text": price_text,
        "reservation_url": reservation_url,
        "seats_available": 0,
        "active": True,
    }


def get_adult_events() -> list[dict[str, Any]]:
    """Return the normalised list of adult events from admin_config.

    Reads ``adult_events.events`` (a list of dicts) in
    ``data/admin_config/sections.yaml``. Each entry is normalised so the
    LLM tool layer sees a stable shape with safe defaults — in
    particular every event gets a numeric ``min_age`` (defaulting to
    ``ADULT_EVENT_DEFAULT_MIN_AGE`` when omitted).

    Live QA Patch (2026-06-05) — Bug 1A: when ``events[]`` is empty or
    missing AND the section itself carries event-like fields
    (description_short, price_text, streams, location, payment_terms),
    a SINGLE fallback event is synthesised from the section so an
    operator who saved data via the current Admin Panel UI (which
    edits section-level fields, not events[]) still sees their event
    appear in the adult flow.

    Missing section, malformed YAML, AND no fallback triggers → empty
    list (the engine surfaces "no active events" upstream).
    """
    section = get_section("adult_events")
    if not isinstance(section, dict):
        logger.info(
            "[admin_config] adult_events_loaded source=%s raw=0 fallback=0 "
            "active=0 titles=[] reason=missing_section",
            str(SECTIONS_PATH),
        )
        return []

    raw_events = section.get("events")
    out: list[dict[str, Any]] = []
    raw_count = 0
    if isinstance(raw_events, list):
        for idx, raw in enumerate(raw_events):
            if not isinstance(raw, dict):
                continue
            raw_count += 1
            normalised = _normalize_adult_event(raw, idx=idx)
            # Live QA Patch (2026-06-05) — Bug 4: an Admin-Panel-saved
            # event that has a title but no explicit `id` is still a
            # VALID event. Auto-derive a stable id from the index so
            # the event still surfaces. Title is required (a row with
            # neither id nor title is noise — drop quietly).
            if not normalised["title"]:
                continue
            out.append(normalised)

    # Live QA Patch (2026-06-05) — Bug 1A: section-level fallback.
    # Hardened (2026-07-07): the fallback fires ONLY when the operator has NOT
    # provided an explicit ``events`` key. An explicit ``events: []`` (or any
    # ``events`` value) means the operator intentionally manages the events list
    # — NEVER fabricate an ``adult_events_default`` from section-level fields in
    # that case. Previously ``events: []`` still synthesised a fallback, which
    # let a DELETED event reappear via section-level fields with a future date.
    # Legacy configs edited only through the old section-level form (no
    # ``events`` key at all) keep the fallback so their event still surfaces.
    fallback_count = 0
    events_key_present = "events" in section
    if not out and not events_key_present:
        fallback = _build_fallback_event_from_section(section)
        if fallback is not None:
            out.append(fallback)
            fallback_count = 1

    active = [e for e in out if e.get("active")]
    titles = [e.get("title", "") for e in active]
    logger.info(
        "[admin_config] adult_events_loaded source=%s raw=%d fallback=%d "
        "active=%d titles=%r",
        str(SECTIONS_PATH), raw_count, fallback_count, len(active), titles,
    )
    return out


# ---------------------------------------------------------------------------
# Adult Event Date Filter (2026-06-10).
#
# Business rule: a PAST adult event must NEVER be offered to a user as
# available/current — even when ``active=True`` in the Admin Panel. The
# operator-entered ``date_text`` (free-form Georgian, e.g. „25 ივნისი
# 20:00" / „26 ივნისი") is parsed against Asia/Tbilisi „now":
#   * date + time → past when datetime < now;
#   * date only   → past once the calendar day has ended (date < today);
#   * empty date  → NOT past (operator chose to omit; show);
#   * non-empty but UNPARSEABLE → hidden from public lists (rule 6) but
#     NOT reported as „ended" (we can't prove it ended).
# Year is assumed to be the current Tbilisi year, rolling to next year
# only when the candidate would be > 180 days in the past (handles a
# December → January event without mis-hiding it).
# ---------------------------------------------------------------------------

_ADULT_EVENT_MONTH_STEMS: dict[str, int] | None = None


def _adult_event_month_stems() -> dict[str, int]:
    global _ADULT_EVENT_MONTH_STEMS
    if _ADULT_EVENT_MONTH_STEMS is None:
        try:
            from app.agent.services.knowledge_loader import load_knowledge
            raw = load_knowledge("i18n/ka_months").get("month_stems") or {}
            _ADULT_EVENT_MONTH_STEMS = {
                str(k): int(v) for k, v in raw.items()
            }
        except Exception as exc:
            logger.warning(
                "[admin_config] month stems load failed (date filter "
                "degraded): %s", exc,
            )
            _ADULT_EVENT_MONTH_STEMS = {}
    return _ADULT_EVENT_MONTH_STEMS


def _now_tbilisi():
    from app.agent.services.timestamps import now_tbilisi, TBILISI_TZ
    return now_tbilisi(), TBILISI_TZ


def _find_month(text: str) -> int | None:
    """Return the month number for the first Georgian month stem in
    ``text`` (longest-stem-first to avoid partial collisions)."""
    stems = _adult_event_month_stems()
    # Match a month word and stem-check it (handles declension / typos
    # like „ივნისიი" → June, „ივლისს" → July).
    for word in re.findall(r"[ა-ჰ]+", text):
        for stem, num in stems.items():
            if word.startswith(stem):
                return num
    return None


def _parse_adult_event_datetime(date_text: str, *, now=None):
    """Parse a Georgian adult-event ``date_text`` into a comparable point.

    Returns ``(datetime_aware, granularity)`` or ``None`` when no month
    can be extracted at all. ``granularity`` is one of:

      * ``"time"``  — „DD <month> HH:MM"  (compare full datetime);
      * ``"date"``  — „DD <month>"         (compare calendar date);
      * ``"month"`` — „<month>" / „2026 წლის ივლისი" (no day — compare
                       year+month; the event spans the whole month).

    Year resolution: an explicit 4-digit year (e.g. „2026") is honoured;
    otherwise the current Tbilisi year is assumed, rolling +1 only when
    the candidate would be > 180 days in the past (so a January event
    viewed in December is read as next year, not last).
    """
    if not date_text:
        return None
    from datetime import datetime as _dt
    now_dt, tz = _now_tbilisi()
    if now is not None:
        now_dt = now
    tzinfo = now_dt.tzinfo or tz
    text = str(date_text).strip().lower()

    month = _find_month(text)
    if month is None:
        return None

    # Explicit 4-digit year, if the operator wrote one („2026 წლის ივლისი").
    year_m = re.search(r"\b(20\d{2})\b", text)
    explicit_year = int(year_m.group(1)) if year_m else None

    # Day must be a 1–2 digit number that is NOT part of a 4-digit year.
    day = None
    day_m = re.search(r"(?<!\d)(\d{1,2})\s+[ა-ჰ]+", text)
    if day_m:
        day = int(day_m.group(1))

    # Optional HH:MM.
    hh = mm = 0
    has_time = False
    tm = re.search(r"(?<!\d)(\d{1,2}):(\d{2})(?!\d)", text)
    if tm:
        h, mi = int(tm.group(1)), int(tm.group(2))
        if 0 <= h <= 23 and 0 <= mi <= 59:
            hh, mm, has_time = h, mi, True

    year = explicit_year if explicit_year is not None else now_dt.year
    use_day = day if (day is not None and 1 <= day <= 31) else 1
    granularity = "month" if day is None else ("time" if has_time else "date")
    try:
        candidate = _dt(year, month, use_day, hh, mm, tzinfo=tzinfo)
    except ValueError:
        return None
    # Year rollover only when the year was NOT explicit and the candidate
    # is far in the past (handles December → January).
    if explicit_year is None and (now_dt - candidate).days > 180:
        try:
            candidate = _dt(year + 1, month, use_day, hh, mm, tzinfo=tzinfo)
        except ValueError:
            pass
    return candidate, granularity


def is_adult_event_past(event: dict[str, Any], *, now=None) -> bool:
    """True ONLY when the event's ``date_text`` is present, parseable AND
    strictly in the past. Empty or unparseable date → ``False`` (we never
    claim an event „ended" without a provably-past date).

    Granularity-aware: a date+time is past once the moment passes; a
    date-only event is past once the day ends; a month-only event is past
    once the whole month ends."""
    if not isinstance(event, dict):
        return False
    parsed = _parse_adult_event_datetime(event.get("date_text") or "", now=now)
    if parsed is None:
        return False
    dt, granularity = parsed
    now_dt = now if now is not None else _now_tbilisi()[0]
    if granularity == "time":
        return dt < now_dt
    if granularity == "date":
        return dt.date() < now_dt.date()
    # month-only — past once the event's month is strictly before now's.
    return (dt.year, dt.month) < (now_dt.year, now_dt.month)


def _adult_event_visible_to_public(event: dict[str, Any], *, now=None) -> bool:
    """List-visibility decision for user-facing adult event surfaces.

    Hides inactive events (existing rule), PAST events, AND non-empty but
    UNPARSEABLE-date events (rule 6 — never offer a date we can't verify
    as current). An EMPTY ``date_text`` is shown (operator omitted a date
    deliberately; the section-level fallback event can be dateless)."""
    if not bool(event.get("active")):
        return False
    date_text = (event.get("date_text") or "").strip()
    if not date_text:
        return True
    parsed = _parse_adult_event_datetime(date_text, now=now)
    if parsed is None:
        logger.warning(
            "[admin_config] adult event id=%r has unparseable date_text=%r "
            "— hidden from public list",
            event.get("id"), date_text,
        )
        return False
    dt, granularity = parsed
    now_dt = now if now is not None else _now_tbilisi()[0]
    if granularity == "time":
        return dt >= now_dt
    if granularity == "date":
        return dt.date() >= now_dt.date()
    # month-only — visible while its month is the current month or later.
    return (dt.year, dt.month) >= (now_dt.year, now_dt.month)


# ---------------------------------------------------------------------------
# Camp Stream Date Filter (2026-06-20).
#
# Business rule: once a camp stream's START date arrives, that stream must
# stop being shown to users — even while it is still marked „active" in
# Admin/config. (Operators keep the stream in config for reporting; we just
# stop advertising a stream people can no longer join from its first day.)
#
#   active stream AND today <  start_date  → visible
#   active stream AND today >= start_date  → hidden   (hidden ON the start day)
#   inactive stream                        → hidden   (regardless of date)
#
# Camp streams are written as a Georgian day-range „DD-DD <month>" (e.g.
# „23-29 ივნისი"); the FIRST number is the start day. „today" is Asia/Tbilisi,
# via the same `_now_tbilisi()` seam the adult-event filter uses. This is a
# display / eligibility filter ONLY — it never mutates config or KB data.
# ---------------------------------------------------------------------------


def _parse_camp_stream_start_date(dates_text: str, *, now=None, year=None):
    """Return the START ``date`` of a camp stream's date range, or ``None``.

    „23-29 ივნისი" → ``date(year, 6, 23)`` — the first number is the start
    day, the Georgian word is the month. Year resolution: an explicit
    4-digit year written in the text wins; else the caller-supplied camp
    ``year``; else the current Tbilisi year. Returns ``None`` when no month
    can be found (the caller decides how to treat an unparseable range)."""
    from datetime import date as _date

    if not dates_text:
        return None
    now_dt = now if now is not None else _now_tbilisi()[0]
    text = str(dates_text).strip().lower()

    month = _find_month(text)
    if month is None:
        return None

    year_m = re.search(r"\b(20\d{2})\b", text)
    if year_m:
        resolved_year = int(year_m.group(1))
    elif isinstance(year, int):
        resolved_year = year
    else:
        resolved_year = now_dt.year

    # First 1–2 digit day of the range, ignoring any 4-digit year token.
    text_wo_year = re.sub(r"\b20\d{2}\b", " ", text)
    day_m = re.search(r"(?<!\d)(\d{1,2})(?!\d)", text_wo_year)
    if not day_m:
        return None
    day = int(day_m.group(1))
    if not (1 <= day <= 31):
        return None
    try:
        return _date(resolved_year, month, day)
    except ValueError:
        return None


def is_camp_stream_visible(stream: dict[str, Any], *, now=None, year=None) -> bool:
    """True when a camp stream should still be shown to users.

    Visible = the stream is active AND its start date has NOT yet arrived
    (today < start). An inactive stream is never visible. A non-empty but
    UNPARSEABLE date range is hidden (we never advertise a date we cannot
    verify is still upcoming); an EMPTY ``dates_text`` is shown (operator
    deliberately omitted dates). Mirrors the adult-event visibility stance.
    """
    if not isinstance(stream, dict):
        return False
    # Active/inactive rule (preserved). Streams from camp_2026.yaml carry no
    # status → treated as active; admin streams carry status="active".
    status = (stream.get("status") or "").strip().lower()
    if status and status != "active":
        return False
    if stream.get("active") is False:
        return False

    now_dt = now if now is not None else _now_tbilisi()[0]
    dates_text = (stream.get("dates_text") or "").strip()
    if not dates_text:
        return True
    start = _parse_camp_stream_start_date(dates_text, now=now_dt, year=year)
    if start is None:
        logger.warning(
            "[admin_config] camp stream %r has unparseable dates_text=%r "
            "— hidden from user-facing lists",
            stream.get("name"), dates_text,
        )
        return False
    today = now_dt.date() if hasattr(now_dt, "date") else now_dt
    return today < start


def get_visible_camp_streams(
    streams: list | None = None, *, now=None, year=None,
) -> list[dict[str, Any]]:
    """Filter camp streams down to the ones still shown to users.

    A stream survives when it is active AND its start date has not yet
    arrived (see :func:`is_camp_stream_visible`). When ``streams`` is
    ``None`` the canonical list from :func:`get_camp_facts` is used and the
    camp ``year`` is inferred from it. Returns a NEW list; never mutates the
    input or any config / KB data. An empty result is meaningful — the
    caller must NOT invent dates, and should offer the manager instead."""
    if streams is None:
        camp = get_camp_facts()
        streams = camp.get("streams") or []
        if year is None:
            year = camp.get("year")
    visible: list[dict[str, Any]] = []
    for s in streams or []:
        if isinstance(s, dict) and is_camp_stream_visible(s, now=now, year=year):
            visible.append(s)
    return visible


def get_active_adult_events(
    user_age: int | None = None,
    *,
    include_past: bool = False,
    now=None,
) -> list[dict[str, Any]]:
    """Return only events with ``active=True`` and, when ``user_age`` is
    provided, only events whose ``min_age`` is ≤ ``user_age``.

    ``user_age`` is ignored when None (the engine asks for the age before
    consulting this helper). Age filtering uses ``>=`` comparison so an
    event with ``min_age=18`` is shown to an 18-year-old.

    Adult Event Date Filter (2026-06-10): by default PAST events (and
    non-empty-but-unparseable-date events) are EXCLUDED — `active=True`
    alone is no longer enough to surface an event to a user. Pass
    ``include_past=True`` to get the active pool without the date filter
    (used by the comment specific-event resolver so it can still DETECT a
    past-event tag and answer „this event has ended" rather than silently
    miss). ``now`` is injectable for deterministic tests.
    """
    events = [e for e in get_adult_events() if e.get("active")]
    if not include_past:
        events = [
            e for e in events if _adult_event_visible_to_public(e, now=now)
        ]
    if user_age is None:
        return events
    try:
        threshold = int(user_age)
    except (TypeError, ValueError):
        return events
    return [e for e in events if int(e.get("min_age") or 0) <= threshold]


def _slugify_for_id(title: str) -> str:
    """Generate a stable, file-safe id from a Georgian/Latin title.

    Lowercases Latin characters, strips non-alphanumeric, falls back
    to ``adult_event`` when nothing useful remains.
    """
    if not title:
        return "adult_event"
    cleaned: list[str] = []
    for ch in title.strip().lower():
        if ch.isalnum():
            cleaned.append(ch)
        elif ch in (" ", "-", "_"):
            cleaned.append("_")
    joined = "".join(cleaned).strip("_") or "adult_event"
    return joined[:60]


def _load_adult_events_raw() -> list[dict[str, Any]]:
    """Return the raw `events` list from sections.yaml without
    normalisation. Used by the events CRUD admin routes."""
    section = get_section("adult_events")
    if not isinstance(section, dict):
        return []
    raw = section.get("events")
    if not isinstance(raw, list):
        return []
    return [dict(e) for e in raw if isinstance(e, dict)]


def _save_adult_events_list(events: list[dict[str, Any]]) -> list[str]:
    """Write the `events` list back to the `adult_events` section.

    Live QA Patch (2026-06-05) — Bug 1B Admin Panel events[] editor.

    Returns validation error strings (empty list on success). The
    section MUST already exist; this helper does not create it.

    Does NOT re-validate the whole section — the events sub-list is
    orthogonal to the section-level fields. Re-running
    `validate_section` here would force every adult_events section to
    carry `auto_dm_template_id` even when the operator is only
    managing the events list.
    """
    sections = load_sections()
    for s in sections:
        if s.get("id") == "adult_events":
            s["events"] = events
            save_sections(sections)
            return []
    return ["section adult_events not found"]


def save_adult_event(event: dict[str, Any]) -> list[str]:
    """Insert OR update an event under adult_events.events[] by id.

    Returns validation error strings (empty list on success).

    Preserves the operator-supplied fields verbatim — only ``id``,
    ``status`` and ``min_age`` are coerced to the canonical shape so
    the YAML round-trip is stable. Optional fields (``description``,
    ``reservation_url``, ``facebook_post_id``, ``tags``, ``price_gel``,
    ``payment_terms``) survive untouched when present.
    """
    title = (event.get("title") or "").strip()
    if not title:
        return ["title is required"]

    event_id = (event.get("id") or "").strip() or _slugify_for_id(title)
    event["id"] = event_id

    status = (event.get("status") or "active").strip().lower()
    if status not in {"active", "inactive"}:
        return [f"status must be 'active' or 'inactive', got {status!r}"]
    event["status"] = status

    raw_min_age = event.get("min_age")
    if raw_min_age in (None, ""):
        event["min_age"] = ADULT_EVENT_DEFAULT_MIN_AGE
    else:
        try:
            event["min_age"] = max(int(raw_min_age), ADULT_EVENT_DEFAULT_MIN_AGE)
        except (TypeError, ValueError):
            return [f"min_age must be an integer, got {raw_min_age!r}"]

    # Tag normalisation — accept either a list or a CSV string;
    # persist as a YAML list so the editor round-trips cleanly. An
    # empty/whitespace-only value drops the field rather than writing
    # an empty list.
    raw_tags = event.get("tags")
    if isinstance(raw_tags, list):
        cleaned_tags = [str(t).strip() for t in raw_tags if str(t).strip()]
    elif isinstance(raw_tags, str):
        cleaned_tags = [t.strip() for t in raw_tags.split(",") if t.strip()]
    else:
        cleaned_tags = []
    if cleaned_tags:
        event["tags"] = cleaned_tags
    else:
        event.pop("tags", None)

    # Strip blank optional fields so the YAML stays clean.
    for opt_key in (
        "description", "reservation_url", "facebook_post_id",
        "payment_terms", "date_text", "location", "price_text",
    ):
        if opt_key in event:
            value = event.get(opt_key)
            if value is None:
                event.pop(opt_key, None)
            elif isinstance(value, str) and not value.strip():
                event.pop(opt_key, None)
            elif isinstance(value, str):
                event[opt_key] = value.strip()

    # price_gel — accept int, numeric string, or drop when blank/invalid.
    raw_price_gel = event.get("price_gel")
    if raw_price_gel in (None, ""):
        event.pop("price_gel", None)
    else:
        try:
            event["price_gel"] = int(raw_price_gel)
        except (TypeError, ValueError):
            event.pop("price_gel", None)

    events = _load_adult_events_raw()
    updated = False
    for idx, existing in enumerate(events):
        if existing.get("id") == event_id:
            # Preserve fields the operator did not touch this time —
            # e.g. an Admin Panel "edit description only" save should
            # not drop a previously-set facebook_post_id. Operator-
            # supplied keys win; unspecified ones inherit from the
            # existing entry.
            merged = dict(existing)
            merged.update(event)
            events[idx] = merged
            updated = True
            break
    if not updated:
        events.append(event)
    return _save_adult_events_list(events)


def update_adult_event(
    event_id: str, patch: dict[str, Any],
) -> list[str]:
    """Apply a partial update to an existing adult event.

    Returns validation errors (empty list on success). When the
    operator only wants to change a single field (e.g. price_text)
    this is the safer entrypoint than `save_adult_event` because it
    refuses to write when the event id is unknown.
    """
    eid = (event_id or "").strip()
    if not eid:
        return ["event id is required"]
    events = _load_adult_events_raw()
    current = None
    for existing in events:
        if existing.get("id") == eid:
            current = existing
            break
    if current is None:
        return [f"adult event {eid!r} not found"]

    merged = {**current, **(patch or {}), "id": eid}
    return save_adult_event(merged)


def _set_adult_event_status(event_id: str, status: str) -> bool:
    """Internal: flip the ``status`` of an event by id. Returns True
    when the event was found and updated."""
    eid = (event_id or "").strip()
    if not eid:
        return False
    events = _load_adult_events_raw()
    touched = False
    for entry in events:
        if entry.get("id") == eid:
            entry["status"] = status
            touched = True
            break
    if not touched:
        return False
    errors = _save_adult_events_list(events)
    return not errors


def deactivate_adult_event(event_id: str) -> bool:
    """Soft-disable an event by setting ``status="inactive"``. The
    event row stays in YAML so the operator can re-activate later —
    only ``delete_adult_event`` hard-removes."""
    return _set_adult_event_status(event_id, "inactive")


def activate_adult_event(event_id: str) -> bool:
    """Re-enable a previously deactivated event."""
    return _set_adult_event_status(event_id, "active")


def delete_adult_event(event_id: str) -> bool:
    """Remove an event by id. Returns True when something was removed."""
    eid = (event_id or "").strip()
    if not eid:
        return False
    events = _load_adult_events_raw()
    new_list = [e for e in events if e.get("id") != eid]
    if len(new_list) == len(events):
        return False
    _save_adult_events_list(new_list)
    return True


# Live QA Patch (2026-06-08 — adult event selection): Georgian case
# suffixes used for crude stem-aware title matching. Longest first so
# the strip is deterministic ("ისკენ" before "ის"). These are NOT a
# full Georgian morphological analyser — they cover the noun cases that
# show up in cultural-event titles + user paraphrases.
_GEORGIAN_NOUN_SUFFIXES: tuple[str, ...] = (
    "ისთვის", "ისკენ", "ისგან", "ისთა",
    "ისა", "თან", "ში", "ის", "ად", "ით", "თა", "ზე",
    "ი", "ა", "ე", "ო", "უ",
)


def _stem_token_for_match(token: str) -> str:
    """Return a stem-form for a single Georgian / Latin word.

    Lowercases (casefold for Latin), strips surrounding punctuation,
    drops the longest matching Georgian noun-case suffix. A token that
    becomes shorter than 3 characters after stripping is returned
    untouched — Georgian roots can be 3-character. Latin tokens are
    casefolded only; we never strip Latin endings.
    """
    if not token:
        return ""
    cleaned = token.strip(",.!?;:()[]{}\"'„""«»").casefold()
    if not cleaned:
        return ""
    # Skip suffix-stripping for Latin / mixed tokens — Georgian
    # suffixes are byte-distinct, so this check is cheap.
    has_georgian = any(0x10A0 <= ord(ch) <= 0x10FF for ch in cleaned)
    if not has_georgian:
        return cleaned
    for suf in _GEORGIAN_NOUN_SUFFIXES:
        if cleaned.endswith(suf) and len(cleaned) - len(suf) >= 3:
            return cleaned[: -len(suf)]
    return cleaned


def _tokenize_for_match(text: str) -> list[str]:
    if not text:
        return []
    out: list[str] = []
    for token in str(text).split():
        stem = _stem_token_for_match(token)
        if stem:
            out.append(stem)
    return out


def _token_matches(needle_stem: str, title_stem: str) -> bool:
    """Stem-vs-stem comparison. A prefix match in either direction
    counts so that minor suffix mismatches („პოეზი" vs „პოეზიი") still
    align. Both sides must be at least 3 chars to avoid over-matching."""
    if not needle_stem or not title_stem:
        return False
    if needle_stem == title_stem:
        return True
    if len(needle_stem) < 3 or len(title_stem) < 3:
        return False
    return needle_stem.startswith(title_stem) or title_stem.startswith(needle_stem)


def find_adult_events_matching(
    needle: str,
    *,
    include_inactive: bool = False,
) -> list[dict[str, Any]]:
    """Return every adult event whose id / title matches ``needle``.

    Resolution order, first non-empty wins:
      1. Exact id match → single-element list.
      2. Exact (casefolded) title match → all titles equal needle.
      3. Substring (casefolded) match — handles Latin titles like
         „Maroon 5" without stemming.
      4. Stem-aware token-overlap — every needle stem must align with
         at least one title stem. Catches „ქართული პოეზია" ↔
         „ქართული პოეზიის საღამო".

    ``include_inactive=False`` (the default) drops inactive events
    from the candidate pool so the user-facing selector never picks an
    archived event. Pass True only when the caller wants to detect a
    deliberate query against a known-inactive event.
    """
    text = (needle or "").strip()
    if not text:
        return []

    all_events = get_adult_events()
    pool = [
        e for e in all_events if include_inactive or e.get("active")
    ]
    if not pool:
        return []

    lowered = text.casefold()

    # 1. exact id
    by_id = [e for e in pool if e.get("id") == text]
    if by_id:
        return by_id

    # 2. exact title
    by_title_exact = [
        e for e in pool
        if (e.get("title") or "").casefold() == lowered
    ]
    if by_title_exact:
        return by_title_exact

    # 3. casefolded substring (Latin-friendly). Min-length guard so a
    # 1-char Georgian noun-ending isn't a substring of every title.
    if len(lowered) >= 3:
        by_substring = [
            e for e in pool
            if lowered in (e.get("title") or "").casefold()
        ]
        if by_substring:
            return by_substring

    # 4. stem-aware token overlap
    needle_stems = [s for s in _tokenize_for_match(text) if len(s) >= 3]
    if not needle_stems:
        return []
    candidates: list[dict[str, Any]] = []
    for event in pool:
        title_stems = _tokenize_for_match(event.get("title") or "")
        if not title_stems:
            continue
        if all(
            any(_token_matches(ns, ts) for ts in title_stems)
            for ns in needle_stems
        ):
            candidates.append(event)
    return candidates


def find_adult_event(event_id_or_title: str) -> dict[str, Any] | None:
    """Look an event up by id (exact) or title (stem-aware, partial).

    Returns the unique match when exactly one candidate is found,
    ``None`` when zero or multiple candidates match. Callers that need
    the full candidate list (e.g. to ask the user to disambiguate)
    must call ``find_adult_events_matching`` directly.
    """
    matches = find_adult_events_matching(event_id_or_title)
    if len(matches) == 1:
        return matches[0]
    return None


# -- event-reference search (P0 Live Demo UX — ISSUE 5, 2026-06-13) -------
#
# The user references an active event by GUEST name / TITLE / DESCRIPTION /
# TAG („გია მურღულია იქნებოდა") or by DATE („16-ში რომ ღონისძიებაა").
# ``find_adult_events_matching`` (above) only searches id/title and requires
# EVERY needle token to align — too strict for a free-text guest mention.
# The helpers below search the wider event text leniently (ANY significant
# token aligns) and by calendar day, so the conversation layer can answer
# from event data when present and fall back to the active-events list when
# not — WITHOUT inventing an event.

# Words that must not, on their own, drive a name/title match — generic
# event vocabulary, greetings, and the question scaffolding around a
# reference („… ვგულისხმობ", „… იქნებოდა", „… ამაზე ვკითხულობ").
_EVENT_QUERY_STOPWORDS: frozenset[str] = frozenset({
    "ღონისძიება", "ღონისძიებაა", "ღონისძიების", "ღონისძიებაზე",
    "ღონისძიებები", "საღამო", "საღამოს", "ფასი", "ფასის", "ღირს",
    "რა", "არის", "ვგულისხმობ", "ვგულისხმობდი", "იქნებოდა", "იყო",
    "ამაზე", "ვკითხულობ", "ვკითხ", "რომ", "მინდა", "ის", "ეს", "თუ",
    "და", "მე", "შესახებ", "გაინტერესებთ", "მაინტერესებს", "გამარჯობა",
    "კი", "ხო", "რიცხვ", "რიცხვში", "თარიღ", "თარიღზე", "გინდა", "ვის",
})


def _event_search_haystack(event: dict[str, Any]) -> str:
    """Every operator-supplied string an event can be matched on, joined
    and casefolded — title, description, guest, theme, location, tags."""
    parts: list[str] = [
        str(event.get("title") or ""),
        str(event.get("description") or ""),
        str(event.get("guest") or ""),
        str(event.get("theme") or ""),
        str(event.get("location") or ""),
    ]
    tags = event.get("tags")
    if isinstance(tags, list):
        parts.extend(str(t) for t in tags)
    elif isinstance(tags, str):
        parts.append(tags)
    # Strip „#" so a hashtag alias („#გიამურღულიასთან") tokenises to a
    # plain word a user reference can align with.
    return " ".join(parts).casefold().replace("#", " ")


def _event_query_tokens(message: str) -> list[str]:
    """Significant (≥3-char, non-stopword) stemmed tokens from a user
    message — the candidate name/title fragments to search events with."""
    text = (message or "").casefold()
    if not text:
        return []
    out: list[str] = []
    for raw in re.split(r"[\s,.!?;:()\[\]{}\"'„""«»#/-]+", text):
        raw = raw.strip()
        if not raw or raw in _EVENT_QUERY_STOPWORDS:
            continue
        stem = _stem_token_for_match(raw)
        if len(stem) >= 3 and stem not in _EVENT_QUERY_STOPWORDS:
            out.append(stem)
    return out


def find_events_by_reference(
    message: str, *, now=None, include_past: bool = False,
) -> list[dict[str, Any]]:
    """Return events whose title / description / guest / theme / location /
    tags contain a significant token from ``message``.

    Lenient (ANY token aligns), stem-aware. With ``include_past=False``
    (default) only future/active events are searched. With
    ``include_past=True`` the pool also includes active-status events whose
    date is already in the past — used by the caller to tell a user that a
    named event they ask about has ALREADY taken place (BUG B, 2026-06-15),
    instead of silently falling through to a target/age question."""
    tokens = _event_query_tokens(message)
    if not tokens:
        return []
    pool = get_active_adult_events(now=now, include_past=include_past)
    if not pool:
        return []
    matches: list[dict[str, Any]] = []
    for event in pool:
        hay_stems = _tokenize_for_match(_event_search_haystack(event))
        if not hay_stems:
            continue
        if any(
            any(_token_matches(tok, hs) for hs in hay_stems)
            for tok in tokens
        ):
            matches.append(event)
    return matches


def find_active_events_by_reference(
    message: str, *, now=None,
) -> list[dict[str, Any]]:
    """Return ACTIVE (future) events whose title / description / guest /
    theme / location / tags contain a significant token from ``message``.

    Lenient (ANY token aligns), stem-aware. Used to resolve a free-text
    guest / title reference („გია მურღულია იქნებოდა" → the
    „… შეხვედრა გია მურღულიასთან" event). Returns [] when nothing matches
    so the caller can list the active events instead of inventing one.
    Thin wrapper over ``find_events_by_reference`` (future-only)."""
    return find_events_by_reference(message, now=now, include_past=False)


def find_active_events_on_day(day: int, *, now=None) -> list[dict[str, Any]]:
    """Return active events whose ``date_text`` resolves to calendar day
    ``day`` (1–31). Used to answer „16-ში რომ ღონისძიებაა" — if the list
    is empty the caller says there is no active event on that date and
    lists the available ones."""
    try:
        target = int(day)
    except (TypeError, ValueError):
        return []
    if not (1 <= target <= 31):
        return []
    out: list[dict[str, Any]] = []
    for event in get_active_adult_events(now=now):
        parsed = _parse_adult_event_datetime(event.get("date_text") or "", now=now)
        if parsed is None:
            continue
        dt, granularity = parsed
        if granularity in ("time", "date") and dt.day == target:
            out.append(event)
    return out


# -- manager phone resolution ---------------------------------------------


def _manager_phone_from_section(section_id: str) -> str:
    try:
        section = get_section(section_id)
    except Exception:
        section = None
    if not isinstance(section, dict):
        return ""
    return (section.get("manager_contact") or "").strip()


def get_manager_phone() -> str:
    """Return the manager phone from Admin Config only.

    ``summer_camp.manager_contact`` is the canonical runtime owner for the
    operator-facing manager contact. The optional manager_contacts mirror is
    still accepted as an Admin Config override, but user/lead/callback phones,
    environment values, prompt examples, and legacy knowledge fallbacks must
    never become ``manager_phone``.

    Returns "" when Admin Config has no manager contact; callers must use their
    approved no-phone fallback instead of substituting another phone.
    """
    section_phone = _manager_phone_from_section("summer_camp")
    if section_phone:
        return section_phone

    try:
        mirror = load_manager_contacts_mirror()
    except Exception:
        mirror = {}
    if isinstance(mirror, dict):
        for key in ("manager_phone", "phone", "MANAGER_PHONE", "MANAGER_PHONE_NUMBER"):
            value = mirror.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        manager_block = mirror.get("manager")
        if isinstance(manager_block, dict):
            for key in ("manager_phone", "phone"):
                value = manager_block.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()

    adult_phone = _manager_phone_from_section("adult_events")
    if adult_phone:
        return adult_phone
    return ""

def load_business_hours_mirror() -> dict[str, Any]:
    raw = _safe_load_yaml(BUSINESS_HOURS_PATH)
    if not isinstance(raw, dict):
        return {}
    return raw


def load_manager_contacts_mirror() -> dict[str, Any]:
    raw = _safe_load_yaml(MANAGER_CONTACTS_PATH)
    if not isinstance(raw, dict):
        return {}
    return raw
