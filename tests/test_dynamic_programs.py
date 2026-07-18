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
