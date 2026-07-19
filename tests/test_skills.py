"""Phase 3 — Skills Registry (USE_SKILLS) tests.

Operator-editable SKILL.md capability packs are selected by situation and
injected into the PARENT system prompt. Flag OFF ⇒ no selection, suffix "",
system prompt byte-identical.
"""


# -- Task 1: USE_SKILLS flag ----------------------------------------------

def test_use_skills_flag_defaults_false():
    from app.config import Settings
    assert Settings().USE_SKILLS is False


def test_use_skills_flag_parses_env(monkeypatch):
    monkeypatch.setenv("USE_SKILLS", "true")
    from app.config import Settings
    assert Settings.from_env().USE_SKILLS is True
