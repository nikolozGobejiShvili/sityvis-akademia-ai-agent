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
