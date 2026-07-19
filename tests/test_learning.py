def test_use_learning_flag_defaults_false():
    from app.config import Settings
    assert Settings().USE_LEARNING is False


def test_use_learning_flag_parses_env(monkeypatch):
    monkeypatch.setenv("USE_LEARNING", "true")
    from app.config import Settings
    assert Settings.from_env().USE_LEARNING is True
