"""Admin Panel MVP — read/write the admin_config YAML files via Jinja2.

Routes:

    GET  /admin                        — dashboard
    GET  /admin/programs               — section list
    GET  /admin/programs/new           — new-section form
    POST /admin/programs/new           — create section
    GET  /admin/programs/{section_id}  — edit form
    POST /admin/programs/{section_id}  — save edits
    POST /admin/programs/{section_id}/delete  — remove section
    GET  /admin/templates              — template list + per-template edit
    POST /admin/templates/{tid}        — save template body
    GET  /admin/settings               — business-hours / manager mirror

Auth: every endpoint depends on ``_require_admin`` which (1) refuses
to serve when ``ADMIN_PANEL_ENABLED=false``, (2) returns 503 if no
``ADMIN_PASSWORD`` is set even with enabled=true, and (3) otherwise
gates on HTTP Basic Auth. Passwords are never logged.
"""

from __future__ import annotations

import logging
import secrets
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates

from app.config import BASE_DIR, settings
from app.services import admin_config_service, redis_state_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])

_security = HTTPBasic()

# Jinja2 lookup root. The directory lives next to `app/` at the project
# root so it's easy to find and edit.
TEMPLATES_DIR: Path = Path(BASE_DIR) / "templates"
_jinja = Jinja2Templates(directory=str(TEMPLATES_DIR))


# -- auth ------------------------------------------------------------------


def _require_admin(
    credentials: HTTPBasicCredentials = Depends(_security),
) -> str:
    """Gate every admin route. Returns the verified username on success."""
    if not settings.ADMIN_PANEL_ENABLED:
        raise HTTPException(status_code=404, detail="Not Found")

    expected_password = (settings.ADMIN_PASSWORD or "").strip()
    if not expected_password:
        logger.warning(
            "[admin] ADMIN_PANEL_ENABLED=true but ADMIN_PASSWORD empty — refusing access",
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin Panel: ADMIN_PASSWORD not set",
        )

    expected_username = (settings.ADMIN_USERNAME or "admin").strip()
    # Constant-time comparison — defends against timing oracles.
    ok_user = secrets.compare_digest(
        credentials.username.encode("utf-8"),
        expected_username.encode("utf-8"),
    )
    ok_pass = secrets.compare_digest(
        credentials.password.encode("utf-8"),
        expected_password.encode("utf-8"),
    )
    if not (ok_user and ok_pass):
        # Tell the browser to re-prompt — without this, the user can't
        # retry from the same tab.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


# -- dashboard -------------------------------------------------------------


@router.get("", response_class=HTMLResponse)
def admin_dashboard(
    request: Request,
    _user: str = Depends(_require_admin),
):
    sections = admin_config_service.load_sections()
    active = [s for s in sections if s.get("status") == "active"]
    return _jinja.TemplateResponse(
        request,
        "admin/dashboard.html",
        {
            "section_count": len(sections),
            "active_count": len(active),
            "sections": sections,
            "redis_enabled": redis_state_service.is_enabled(),
            "email_enabled": bool(settings.ENABLE_EMAIL_NOTIFICATIONS),
            "manager_email": settings.MANAGER_EMAIL or "(not set)",
            "public_reply_enabled": bool(settings.ENABLE_PUBLIC_COMMENT_REPLY),
            "company_name": settings.COMPANY_NAME,
            "agent_enabled": bool(getattr(settings, "AGENT_ENABLED", True)),
        },
    )


@router.get("/", response_class=HTMLResponse)
def admin_dashboard_slash(
    request: Request,
    _user: str = Depends(_require_admin),
):
    return admin_dashboard(request, _user)


# -- programs / sections ---------------------------------------------------


@router.get("/programs", response_class=HTMLResponse)
def list_programs(
    request: Request,
    _user: str = Depends(_require_admin),
):
    sections = admin_config_service.load_sections()
    return _jinja.TemplateResponse(
        request,
        "admin/programs.html",
        {"sections": sections},
    )


@router.get("/programs/new", response_class=HTMLResponse)
def new_program_form(
    request: Request,
    _user: str = Depends(_require_admin),
):
    return _jinja.TemplateResponse(
        request,
        "admin/program_form.html",
        {
            "section": {
                "id": "",
                "name": "",
                "type": "",
                "status": "coming_soon",
                "hashtags": [],
                "auto_dm_template_id": "generic_section_comment_dm",
                "public_reply_template_id": "default_public_reply",
            },
            "is_new": True,
            "errors": [],
            "templates": list(admin_config_service.load_templates().keys()),
            "valid_statuses": admin_config_service.VALID_STATUSES,
        },
    )


@router.post("/programs/new", response_class=HTMLResponse)
def create_program(
    request: Request,
    _user: str = Depends(_require_admin),
    id: str = Form(""),
    name: str = Form(""),
    type: str = Form(""),
    status_field: str = Form("coming_soon", alias="status"),
    hashtags: str = Form(""),
    age_min: str = Form(""),
    age_max: str = Form(""),
    location: str = Form(""),
    duration_text: str = Form(""),
    price_text: str = Form(""),
    payment_terms: str = Form(""),
    description_short: str = Form(""),
    description_full: str = Form(""),
    registration_url: str = Form(""),
    manager_contact: str = Form(""),
    auto_dm_template_id: str = Form(""),
    public_reply_template_id: str = Form("default_public_reply"),
    cta_text: str = Form(""),
    streams_text: str = Form(""),
    included_items_text: str = Form(""),
    discounts_text: str = Form(""),
):
    section = _form_to_section_dict(
        id=id, name=name, type=type, status=status_field,
        hashtags=hashtags, age_min=age_min, age_max=age_max,
        location=location, duration_text=duration_text,
        price_text=price_text, payment_terms=payment_terms,
        description_short=description_short, description_full=description_full,
        registration_url=registration_url, manager_contact=manager_contact,
        auto_dm_template_id=auto_dm_template_id,
        public_reply_template_id=public_reply_template_id,
        cta_text=cta_text,
        streams_text=streams_text,
        included_items_text=included_items_text,
        discounts_text=discounts_text,
    )
    stream_errors = section.pop("_stream_errors", [])
    if stream_errors:
        section["_form_streams_text"] = streams_text
        section["_form_included_items_text"] = included_items_text
        section["_form_discounts_text"] = discounts_text
        return _jinja.TemplateResponse(
            request,
            "admin/program_form.html",
            {
                "section": section,
                "is_new": True,
                "errors": stream_errors,
                "templates": list(admin_config_service.load_templates().keys()),
                "valid_statuses": admin_config_service.VALID_STATUSES,
            },
            status_code=400,
        )
    errors = admin_config_service.save_section(section)
    if errors:
        section["_form_streams_text"] = streams_text
        section["_form_included_items_text"] = included_items_text
        section["_form_discounts_text"] = discounts_text
        return _jinja.TemplateResponse(
            request,
            "admin/program_form.html",
            {
                "section": section,
                "is_new": True,
                "errors": errors,
                "templates": list(admin_config_service.load_templates().keys()),
                "valid_statuses": admin_config_service.VALID_STATUSES,
            },
            status_code=400,
        )
    return RedirectResponse(url="/admin/programs", status_code=303)


@router.get("/programs/{section_id}", response_class=HTMLResponse)
def edit_program_form(
    section_id: str,
    request: Request,
    _user: str = Depends(_require_admin),
):
    section = admin_config_service.get_section(section_id)
    if section is None:
        raise HTTPException(status_code=404, detail="section not found")
    return _jinja.TemplateResponse(
        request,
        "admin/program_form.html",
        {
            "section": section,
            "is_new": False,
            "errors": [],
            "templates": list(admin_config_service.load_templates().keys()),
            "valid_statuses": admin_config_service.VALID_STATUSES,
        },
    )


@router.post("/programs/{section_id}", response_class=HTMLResponse)
def save_program(
    section_id: str,
    request: Request,
    _user: str = Depends(_require_admin),
    name: str = Form(""),
    type: str = Form(""),
    status_field: str = Form("coming_soon", alias="status"),
    hashtags: str = Form(""),
    age_min: str = Form(""),
    age_max: str = Form(""),
    location: str = Form(""),
    duration_text: str = Form(""),
    price_text: str = Form(""),
    payment_terms: str = Form(""),
    description_short: str = Form(""),
    description_full: str = Form(""),
    registration_url: str = Form(""),
    manager_contact: str = Form(""),
    auto_dm_template_id: str = Form(""),
    public_reply_template_id: str = Form("default_public_reply"),
    cta_text: str = Form(""),
    streams_text: str = Form(""),
    included_items_text: str = Form(""),
    discounts_text: str = Form(""),
):
    section = _form_to_section_dict(
        id=section_id, name=name, type=type, status=status_field,
        hashtags=hashtags, age_min=age_min, age_max=age_max,
        location=location, duration_text=duration_text,
        price_text=price_text, payment_terms=payment_terms,
        description_short=description_short, description_full=description_full,
        registration_url=registration_url, manager_contact=manager_contact,
        auto_dm_template_id=auto_dm_template_id,
        public_reply_template_id=public_reply_template_id,
        cta_text=cta_text,
        streams_text=streams_text,
        included_items_text=included_items_text,
        discounts_text=discounts_text,
    )
    stream_errors = section.pop("_stream_errors", [])
    if stream_errors:
        section["_form_streams_text"] = streams_text
        section["_form_included_items_text"] = included_items_text
        section["_form_discounts_text"] = discounts_text
        return _jinja.TemplateResponse(
            request,
            "admin/program_form.html",
            {
                "section": section,
                "is_new": False,
                "errors": stream_errors,
                "templates": list(admin_config_service.load_templates().keys()),
                "valid_statuses": admin_config_service.VALID_STATUSES,
            },
            status_code=400,
        )
    # Preserve EVERY existing field the section form does NOT surface, so
    # operator-only / future config is never silently dropped on a metadata
    # save — e.g. the Sunday-School fields `availability_text` /
    # `details_text` / `handoff_enabled` / `lead_type` (Task 2, 2026-06-22),
    # the non-form `discovery_questions` / `duration_days` / `schedule_text`,
    # the separately-managed `events` list (Live QA Patch 2026-06-05, Bug 1B),
    # and any custom key.
    #
    # EXCEPTION — the form-managed LIST fields below are intentionally NOT
    # resurrected: when the operator blanks their textarea they must clear
    # (this is what preserves the stale-2150 / stale-stream guard). `price_gel`
    # / `price_text` are always present in `section`, so the form always wins
    # for price regardless of this loop.
    _FORM_MANAGED_LIST_FIELDS = ("streams", "included_items", "discounts")
    existing = admin_config_service.get_section(section_id) or {}
    for keep_key, keep_val in existing.items():
        if keep_key in section or keep_key in _FORM_MANAGED_LIST_FIELDS:
            continue
        section[keep_key] = keep_val
    errors = admin_config_service.save_section(section)
    if errors:
        section["_form_streams_text"] = streams_text
        section["_form_included_items_text"] = included_items_text
        section["_form_discounts_text"] = discounts_text
        return _jinja.TemplateResponse(
            request,
            "admin/program_form.html",
            {
                "section": section,
                "is_new": False,
                "errors": errors,
                "templates": list(admin_config_service.load_templates().keys()),
                "valid_statuses": admin_config_service.VALID_STATUSES,
            },
            status_code=400,
        )
    return RedirectResponse(
        url=f"/admin/programs/{section_id}", status_code=303,
    )


@router.post("/programs/{section_id}/delete")
def delete_program(
    section_id: str,
    _user: str = Depends(_require_admin),
):
    admin_config_service.delete_section(section_id)
    return RedirectResponse(url="/admin/programs", status_code=303)


# -- adult events CRUD (Live QA Patch 2026-06-05 — Bug 1B) -----------------
#
# Minimal events[] editor scoped to the adult_events section. Lists,
# adds, edits, and deactivates individual cultural-evening entries
# without touching the rest of the section metadata. Backed by
# `admin_config_service.save_adult_event` / `delete_adult_event`.


@router.get("/programs/adult_events/events", response_class=HTMLResponse)
def list_adult_events_admin(
    request: Request,
    _user: str = Depends(_require_admin),
):
    section = admin_config_service.get_section("adult_events") or {}
    events = admin_config_service._load_adult_events_raw()
    return _jinja.TemplateResponse(
        request,
        "admin/adult_events.html",
        {
            "section": section,
            "events": events,
        },
    )


@router.get("/programs/adult_events/events/new", response_class=HTMLResponse)
def new_adult_event_form(
    request: Request,
    _user: str = Depends(_require_admin),
):
    return _jinja.TemplateResponse(
        request,
        "admin/adult_event_form.html",
        {
            "event": {
                "id": "",
                "title": "",
                "status": "active",
                "min_age": admin_config_service.ADULT_EVENT_DEFAULT_MIN_AGE,
                "date_text": "",
                "location": "",
                "price_text": "",
                "price_gel": "",
                "description": "",
                "reservation_url": "",
                "facebook_post_id": "",
                "tags": "",
            },
            "is_new": True,
            "errors": [],
        },
    )


@router.post("/programs/adult_events/events/new", response_class=HTMLResponse)
def create_adult_event(
    request: Request,
    _user: str = Depends(_require_admin),
    id: str = Form(""),
    title: str = Form(""),
    status_field: str = Form("active", alias="status"),
    min_age: str = Form(""),
    date_text: str = Form(""),
    location: str = Form(""),
    price_text: str = Form(""),
    price_gel: str = Form(""),
    description: str = Form(""),
    reservation_url: str = Form(""),
    facebook_post_id: str = Form(""),
    tags: str = Form(""),
    broadcast_after_save: str = Form(""),
):
    event = _form_to_event_dict(
        id=id, title=title, status=status_field, min_age=min_age,
        date_text=date_text, location=location,
        price_text=price_text, price_gel=price_gel,
        description=description, reservation_url=reservation_url,
        facebook_post_id=facebook_post_id, tags=tags,
    )
    errors = admin_config_service.save_adult_event(event)
    if errors:
        return _jinja.TemplateResponse(
            request,
            "admin/adult_event_form.html",
            {"event": event, "is_new": True, "errors": errors},
            status_code=400,
        )
    # Adult Event Subscription Patch (2026-06-08): optional auto-
    # broadcast after save. Default unchecked; only fires when operator
    # explicitly ticks the box AND the saved event is active AND has a
    # ticket link.
    if _form_checkbox_set(broadcast_after_save):
        _trigger_broadcast_after_save(event.get("id", ""))
    return RedirectResponse(
        url="/admin/programs/adult_events/events", status_code=303,
    )


@router.get(
    "/programs/adult_events/events/{event_id}", response_class=HTMLResponse,
)
def edit_adult_event_form(
    event_id: str,
    request: Request,
    _user: str = Depends(_require_admin),
):
    events = admin_config_service._load_adult_events_raw()
    for e in events:
        if e.get("id") == event_id:
            return _jinja.TemplateResponse(
                request,
                "admin/adult_event_form.html",
                {"event": e, "is_new": False, "errors": []},
            )
    raise HTTPException(status_code=404, detail="event not found")


@router.post(
    "/programs/adult_events/events/{event_id}", response_class=HTMLResponse,
)
def save_adult_event_route(
    event_id: str,
    request: Request,
    _user: str = Depends(_require_admin),
    title: str = Form(""),
    status_field: str = Form("active", alias="status"),
    min_age: str = Form(""),
    date_text: str = Form(""),
    location: str = Form(""),
    price_text: str = Form(""),
    price_gel: str = Form(""),
    description: str = Form(""),
    reservation_url: str = Form(""),
    facebook_post_id: str = Form(""),
    tags: str = Form(""),
    broadcast_after_save: str = Form(""),
):
    event = _form_to_event_dict(
        id=event_id, title=title, status=status_field, min_age=min_age,
        date_text=date_text, location=location,
        price_text=price_text, price_gel=price_gel,
        description=description, reservation_url=reservation_url,
        facebook_post_id=facebook_post_id, tags=tags,
    )
    errors = admin_config_service.save_adult_event(event)
    if errors:
        return _jinja.TemplateResponse(
            request,
            "admin/adult_event_form.html",
            {"event": event, "is_new": False, "errors": errors},
            status_code=400,
        )
    if _form_checkbox_set(broadcast_after_save):
        _trigger_broadcast_after_save(event_id)
    return RedirectResponse(
        url="/admin/programs/adult_events/events", status_code=303,
    )


@router.post("/programs/adult_events/events/{event_id}/delete")
def delete_adult_event_route(
    event_id: str,
    _user: str = Depends(_require_admin),
):
    admin_config_service.delete_adult_event(event_id)
    return RedirectResponse(
        url="/admin/programs/adult_events/events", status_code=303,
    )


# Adult Event Subscription Patch (2026-06-08): manual broadcast button.


@router.post(
    "/programs/adult_events/events/{event_id}/broadcast",
    response_class=HTMLResponse,
)
def manual_broadcast_adult_event(
    event_id: str,
    request: Request,
    _user: str = Depends(_require_admin),
):
    """Trigger a one-off broadcast to subscribed users for this event.

    Renders a small results page (sent / skipped / failed counts) so
    the operator gets immediate feedback. Renders the same template
    when the broadcast fails (e.g. missing link / inactive event).
    """
    from app.services import adult_event_broadcast_service
    result = adult_event_broadcast_service.broadcast_event(
        event_id, source="admin_manual",
    )
    summary = _format_broadcast_summary(result)
    return _jinja.TemplateResponse(
        request,
        "admin/adult_event_broadcast_result.html",
        {"result": result, "summary": summary},
    )


def _form_checkbox_set(value: str | None) -> bool:
    """HTML checkboxes submit "on" (or the value attribute) when
    checked and the field is simply absent when unchecked. FastAPI's
    Form(default="") gives us an empty string for the unchecked case.
    Accept any truthy non-empty value as checked."""
    return bool((value or "").strip())


def _trigger_broadcast_after_save(event_id: str) -> None:
    """Best-effort broadcast after a save when the operator ticked the
    checkbox. Failure is logged but never blocks the redirect — the
    save itself already succeeded."""
    from app.services import adult_event_broadcast_service
    try:
        result = adult_event_broadcast_service.broadcast_event(
            event_id, source="after_save",
        )
        logger.info(
            "[admin] broadcast_after_save event=%s result=%r",
            event_id, result,
        )
    except Exception as exc:
        logger.warning(
            "[admin] broadcast_after_save raised event=%s: %s",
            event_id, exc,
        )


def _format_broadcast_summary(result: dict) -> str:
    """Render the broadcast result counts into a single Georgian
    sentence suitable for the operator confirmation page."""
    reason = result.get("reason") or ""
    if reason == "missing_link":
        return (
            "გაგზავნა ვერ მოხერხდა — ღონისძიებას ბილეთის ბმული "
            "არ აქვს მითითებული."
        )
    if reason == "missing_event":
        return (
            "გაგზავნა ვერ მოხერხდა — ღონისძიება ვერ მოიძებნა."
        )
    if reason == "inactive":
        return (
            "გაგზავნა ვერ მოხერხდა — ღონისძიება inactive-ია. "
            "ჯერ გააქტიურეთ, შემდეგ სცადეთ ხელახლა."
        )
    if reason == "event_past":
        return (
            "გაგზავნა ვერ მოხერხდა — ღონისძიების თარიღი უკვე გასულია. "
            "წარსული ღონისძიება მომხმარებლებს არ ეგზავნება."
        )
    if reason == "kill_switch_disabled":
        return (
            "გაგზავნა გამორთულია (AGENT_ENABLED=false)."
        )
    if reason == "subscriber_list_failed":
        return (
            "subscribed მომხმარებლების სია ვერ ჩაიტვირთა "
            "(Sheets-ის შეცდომა)."
        )
    if result.get("total_candidates", 0) == 0:
        return "subscribed მომხმარებლები ჯერ არ არიან."
    sent = result.get("sent", 0)
    skipped = (
        result.get("skipped_duplicate", 0)
        + result.get("skipped_platform", 0)
        + result.get("skipped_no_consent", 0)
    )
    failed = result.get("failed", 0)
    parts = [f"გაგზავნილია {sent} მომხმარებელთან"]
    if skipped:
        parts.append(f"გამოტოვებულია {skipped}")
    if failed:
        parts.append(f"ვერ მოხერხდა {failed}")
    return ". ".join(parts) + "."


@router.post("/programs/adult_events/events/{event_id}/deactivate")
def deactivate_adult_event_route(
    event_id: str,
    _user: str = Depends(_require_admin),
):
    """Soft-disable an event without removing it from sections.yaml."""
    admin_config_service.deactivate_adult_event(event_id)
    return RedirectResponse(
        url="/admin/programs/adult_events/events", status_code=303,
    )


@router.post("/programs/adult_events/events/{event_id}/activate")
def activate_adult_event_route(
    event_id: str,
    _user: str = Depends(_require_admin),
):
    """Re-enable a previously deactivated event."""
    admin_config_service.activate_adult_event(event_id)
    return RedirectResponse(
        url="/admin/programs/adult_events/events", status_code=303,
    )


def _form_to_event_dict(
    *,
    id: str,
    title: str,
    status: str,
    min_age: str,
    date_text: str,
    location: str,
    price_text: str,
    price_gel: str,
    description: str,
    reservation_url: str,
    facebook_post_id: str,
    tags: str,
) -> dict[str, Any]:
    """Translate the Admin Panel form fields into the YAML event dict."""
    cleaned: dict[str, Any] = {
        "id": id.strip(),
        "title": title.strip(),
        "status": (status or "active").strip().lower(),
        "date_text": date_text.strip(),
        "location": location.strip(),
        "price_text": price_text.strip(),
        "description": description.strip(),
        "reservation_url": reservation_url.strip(),
        "facebook_post_id": facebook_post_id.strip(),
        "tags": [
            t.strip() for t in tags.split(",")
            if t and t.strip()
        ],
    }
    raw_min = (min_age or "").strip()
    if raw_min:
        try:
            cleaned["min_age"] = int(raw_min)
        except ValueError:
            cleaned["min_age"] = raw_min  # let validator reject
    raw_price_gel = (price_gel or "").strip()
    if raw_price_gel:
        try:
            cleaned["price_gel"] = int(raw_price_gel)
        except ValueError:
            pass  # silently drop invalid value
    return cleaned


# -- templates -------------------------------------------------------------


@router.get("/templates", response_class=HTMLResponse)
def list_templates(
    request: Request,
    _user: str = Depends(_require_admin),
):
    templates = admin_config_service.load_templates()
    return _jinja.TemplateResponse(
        request,
        "admin/templates.html",
        {"templates": templates},
    )


@router.post("/templates/{template_id}")
def save_template(
    template_id: str,
    _user: str = Depends(_require_admin),
    body: str = Form(""),
):
    admin_config_service.save_template(template_id, body)
    return RedirectResponse(url="/admin/templates", status_code=303)


# -- settings page ---------------------------------------------------------


@router.get("/settings", response_class=HTMLResponse)
def settings_page(
    request: Request,
    _user: str = Depends(_require_admin),
):
    business = admin_config_service.load_business_hours_mirror()
    manager = admin_config_service.load_manager_contacts_mirror()
    return _jinja.TemplateResponse(
        request,
        "admin/settings.html",
        {
            "business": business,
            "manager": manager,
            "redis_enabled": redis_state_service.is_enabled(),
            "email_enabled": bool(settings.ENABLE_EMAIL_NOTIFICATIONS),
            "manager_email": settings.MANAGER_EMAIL,
            "public_reply_enabled": bool(settings.ENABLE_PUBLIC_COMMENT_REPLY),
        },
    )


# -- form parsing helper ---------------------------------------------------


def _form_to_section_dict(**form: Any) -> dict[str, Any]:
    """Translate the flat HTML form into the YAML section shape.

    Field-completion patch:
      * `price_gel` is auto-derived from the operator's `price_text`
        on every save so the two values can never drift.
      * `streams` is parsed from a textarea in `name | dates_text |
        status` line format. Malformed lines are flagged via a side-
        channel `_stream_errors` key the caller surfaces in the form.
      * `included_items` / `discounts` are parsed from textareas, one
        item per line.
    """
    hashtags_raw = (form.get("hashtags") or "").strip()
    hashtags = [
        item.strip().lstrip("#").strip()
        for item in hashtags_raw.replace("\n", ",").split(",")
        if item.strip()
    ]

    def _int_or_none(value: str) -> int | None:
        value = (value or "").strip()
        if not value:
            return None
        try:
            return int(value)
        except ValueError:
            return None

    price_text = (form.get("price_text") or "").strip()
    price_gel = admin_config_service.parse_price_gel(price_text)

    streams_raw = (form.get("streams_text") or "").strip()
    streams, stream_errors = _parse_streams_textarea(streams_raw)

    included_items_raw = (form.get("included_items_text") or "").strip()
    included_items = [
        line.strip() for line in included_items_raw.splitlines() if line.strip()
    ]

    discounts_raw = (form.get("discounts_text") or "").strip()
    discounts = [
        line.strip() for line in discounts_raw.splitlines() if line.strip()
    ]

    result: dict[str, Any] = {
        "id": (form.get("id") or "").strip(),
        "name": (form.get("name") or "").strip(),
        "type": (form.get("type") or "").strip(),
        "status": (form.get("status") or "coming_soon").strip(),
        "hashtags": hashtags,
        "age_min": _int_or_none(form.get("age_min")),
        "age_max": _int_or_none(form.get("age_max")),
        "location": (form.get("location") or "").strip(),
        "duration_text": (form.get("duration_text") or "").strip(),
        "price_text": price_text,
        "price_gel": price_gel,
        "payment_terms": (form.get("payment_terms") or "").strip(),
        "description_short": (form.get("description_short") or "").strip(),
        "description_full": (form.get("description_full") or "").strip(),
        "registration_url": (form.get("registration_url") or "").strip(),
        "manager_contact": (form.get("manager_contact") or "").strip(),
        "auto_dm_template_id":
            (form.get("auto_dm_template_id") or "").strip(),
        "public_reply_template_id":
            (form.get("public_reply_template_id") or "default_public_reply").strip(),
        "cta_text": (form.get("cta_text") or "").strip(),
    }
    # Only override existing values when the operator actually filled
    # the textarea — preserves embedded list fields when the form
    # doesn't surface them.
    if streams_raw:
        result["streams"] = streams
    if included_items_raw:
        result["included_items"] = included_items
    if discounts_raw:
        result["discounts"] = discounts
    if stream_errors:
        # Side-channel: the route layer reads this and re-renders the
        # form with the errors before writing YAML.
        result["_stream_errors"] = stream_errors
    return result


def _parse_streams_textarea(text: str) -> tuple[list[dict[str, Any]], list[str]]:
    """Parse the `name | dates_text | status` line format.

    Returns `(streams, errors)`. Empty input is OK — streams=[],
    errors=[]. Lines starting with ``#`` are skipped. A line with the
    wrong number of pipe-separated fields produces an error message
    referencing the line number.
    """
    streams: list[dict[str, Any]] = []
    errors: list[str] = []
    if not text:
        return streams, errors
    for idx, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 2:
            errors.append(
                f"Line {idx}: expected `name | dates_text | status` — got {line!r}"
            )
            continue
        name = parts[0]
        dates_text = parts[1]
        status = parts[2] if len(parts) >= 3 and parts[2] else "active"
        if not name or not dates_text:
            errors.append(f"Line {idx}: name and dates_text are required")
            continue
        if status not in admin_config_service.VALID_STATUSES:
            errors.append(
                f"Line {idx}: status must be one of "
                f"{admin_config_service.VALID_STATUSES} — got {status!r}"
            )
            continue
        streams.append({
            "name": name, "dates_text": dates_text, "status": status,
        })
    return streams, errors
