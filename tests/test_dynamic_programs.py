def test_dynamic_programs_flag_defaults_false():
    from app.config import Settings
    assert Settings().USE_DYNAMIC_PROGRAMS is False


def test_dynamic_programs_flag_parses_env(monkeypatch):
    monkeypatch.setenv("USE_DYNAMIC_PROGRAMS", "true")
    from app.config import Settings
    assert Settings.from_env().USE_DYNAMIC_PROGRAMS is True
