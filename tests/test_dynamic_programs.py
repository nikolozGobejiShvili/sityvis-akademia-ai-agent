def test_dynamic_programs_flag_defaults_false():
    from app.config import Settings
    assert Settings().USE_DYNAMIC_PROGRAMS is False


def test_dynamic_programs_flag_parses_env(monkeypatch):
    monkeypatch.setenv("USE_DYNAMIC_PROGRAMS", "true")
    from app.config import Settings
    assert Settings.from_env().USE_DYNAMIC_PROGRAMS is True


def test_dynamic_program_tools_wellformed_and_not_in_base():
    from app.agent.tools import parent_tools as pt
    names = {t["function"]["name"] for t in pt.DYNAMIC_PROGRAM_TOOLS}
    assert names == {"list_programs", "get_program_info"}
    assert {"list_programs", "get_program_info"} <= pt.ALLOWED_TOOL_NAMES
    assert "get_program_info" not in {t["function"]["name"] for t in pt.PARENT_TOOLS}
    gpi = next(t for t in pt.DYNAMIC_PROGRAM_TOOLS if t["function"]["name"] == "get_program_info")
    assert gpi["function"]["parameters"]["required"] == ["program_id"]


# Task 3 — guarded executor handlers (_list_programs / _get_program_info).

def _fake_sections():
    return [
        {"id": "robotics_club", "name": "რობოტიკის კლუბი", "type": "kids_program",
         "status": "active", "price_text": "300 ლარი", "age_min": 8, "age_max": 14,
         "description_full": "ბავშვები ისწავლიან რობოტების აწყობას და პროგრამირებას.",
         "registration_url": "https://x/y", "registration_status": "closed",
         "auto_dm_template_id": "robo_dm", "hashtags": ["რობოტიკა", "robotics"]},
        {"id": "old", "name": "ძველი", "type": "kids_program", "status": "hidden"},
    ]


def _make_executor():
    from app.agent.tools.parent_tool_executor import ParentToolExecutor
    from app.models.lead import Lead
    from app.models.conversation import Conversation
    conv = Conversation(sender_id="t", platform="facebook")
    # ParentToolExecutor is a dataclass: conversation, lead, sender_id, platform, user_message=""
    # Lead requires sender_id/platform/segment (no bare Lead()); minimal
    # valid values only — the asserted behavior does not depend on them.
    lead = Lead(sender_id="t", platform="facebook", segment="PARENT")
    return ParentToolExecutor(conversation=conv, lead=lead, sender_id="t", platform="facebook")


def test_list_programs_active_only(monkeypatch):
    from app.services import admin_config_service
    monkeypatch.setattr(admin_config_service, "get_active_sections",
                        lambda: [s for s in _fake_sections() if s["status"] == "active"])
    out = _make_executor().execute("list_programs", {})
    assert out["success"] and {p["program_id"] for p in out["programs"]} == {"robotics_club"}


def test_get_program_info_guards_and_facts(monkeypatch):
    from app.services import admin_config_service
    monkeypatch.setattr(admin_config_service, "get_section",
                        lambda pid: next((s for s in _fake_sections() if s["id"] == pid), None))
    out = _make_executor().execute("get_program_info", {"program_id": "robotics_club", "topic": "price"})
    assert out["success"] is True
    assert out["facts"]["price_text"] == "300 ლარი"
    assert "პროგრამირებას" in out["facts"]["description_full"]
    # registration_status is closed → the URL must NOT leak
    assert "registration_url" not in out["facts"]
    # operator-internal keys never exposed
    assert "auto_dm_template_id" not in out["facts"] and "hashtags" not in out["facts"]


def test_get_program_info_unknown_and_inactive(monkeypatch):
    from app.services import admin_config_service
    monkeypatch.setattr(admin_config_service, "get_section",
                        lambda pid: next((s for s in _fake_sections() if s["id"] == pid), None))
    ex = _make_executor()
    assert ex.execute("get_program_info", {"program_id": "nope"})["reason"] == "unknown_program"
    assert ex.execute("get_program_info", {"program_id": "old"})["reason"] == "program_not_active"


def test_get_program_info_surfaces_registration_url_when_open(monkeypatch):
    # Positive counterpart to test_get_program_info_guards_and_facts: when
    # registration_status is "open" the URL must be PRESENT in facts, not
    # dropped. Self-contained section dict — does not touch _fake_sections
    # so the closed-status guard test above is unaffected.
    open_section = {
        "id": "chess_club", "name": "ჭადრაკის კლუბი", "type": "kids_program",
        "status": "active", "price_text": "200 ლარი",
        "registration_url": "https://x/open-reg", "registration_status": "open",
    }
    from app.services import admin_config_service
    monkeypatch.setattr(admin_config_service, "get_section",
                        lambda pid: open_section if pid == "chess_club" else None)
    out = _make_executor().execute("get_program_info", {"program_id": "chess_club"})
    assert out["success"] is True
    assert out["registration_open"] is True
    assert out["facts"]["registration_url"] == "https://x/open-reg"


# Task 4 — wire the generic program tools into the LLM loop (flag-gated).

def test_build_active_tools_respects_flag():
    from app.agent.llm.parent_llm_engine import build_active_tools
    from app.agent.tools.parent_tools import PARENT_TOOLS, DYNAMIC_PROGRAM_TOOLS
    off = [t["function"]["name"] for t in build_active_tools(False)]
    assert off == [t["function"]["name"] for t in PARENT_TOOLS]
    on = {t["function"]["name"] for t in build_active_tools(True)}
    assert {"list_programs", "get_program_info"} <= on
    assert len(build_active_tools(True)) == len(PARENT_TOOLS) + len(DYNAMIC_PROGRAM_TOOLS)


# Task 4 review fix — dedicated coverage for _dynamic_programs_prompt_suffix().
# `app.config.Settings` is a FROZEN dataclass, so a plain
# `monkeypatch.setattr(settings_instance, "USE_DYNAMIC_PROGRAMS", ...)` raises
# `FrozenInstanceError`. Both tests instead replace the MODULE-level `settings`
# binding that `parent_llm_engine` reads (`dataclasses.replace(...)` + module
# monkeypatch) — the same mechanism `tests/conftest.py`'s autouse
# `_force_parent_llm_engine_off` fixture already uses for this module.

def test_dynamic_programs_prompt_suffix_empty_when_flag_off(monkeypatch):
    import dataclasses
    from app.agent.llm import parent_llm_engine

    off_settings = dataclasses.replace(parent_llm_engine.settings, USE_DYNAMIC_PROGRAMS=False)
    monkeypatch.setattr(parent_llm_engine, "settings", off_settings)

    assert parent_llm_engine._dynamic_programs_prompt_suffix() == ""


def test_dynamic_programs_prompt_suffix_lists_non_camp_when_on(monkeypatch):
    import dataclasses
    from app.agent.llm import parent_llm_engine
    from app.services import admin_config_service

    on_settings = dataclasses.replace(parent_llm_engine.settings, USE_DYNAMIC_PROGRAMS=True)
    monkeypatch.setattr(parent_llm_engine, "settings", on_settings)
    monkeypatch.setattr(
        admin_config_service, "get_active_sections",
        lambda: [
            {"id": "summer_camp", "name": "საზაფხულო ბანაკი", "status": "active"},
            {"id": "robotics_club", "name": "რობოტიკის კლუბი", "status": "active"},
        ],
    )

    suffix = parent_llm_engine._dynamic_programs_prompt_suffix()

    assert suffix != ""
    assert "robotics_club" in suffix or "რობოტიკის კლუბი" in suffix
    assert "summer_camp" not in suffix
    assert "საზაფხულო ბანაკი" not in suffix
    assert "list_programs" in suffix
    assert "get_program_info" in suffix
