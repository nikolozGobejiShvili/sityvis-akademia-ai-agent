def test_use_lead_memory_flag_defaults_false():
    from app.config import Settings
    assert Settings().USE_LEAD_MEMORY is False


def test_use_lead_memory_flag_parses_env(monkeypatch):
    monkeypatch.setenv("USE_LEAD_MEMORY", "true")
    from app.config import Settings
    assert Settings.from_env().USE_LEAD_MEMORY is True
