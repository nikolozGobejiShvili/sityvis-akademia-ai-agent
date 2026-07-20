"""Phase 2 — reasoning loop (analyze→ground→answer→reflect), USE_REASONING_PASS.

Flag OFF ⇒ engine path byte-identical. Every step fails safe. REFLECT is the
conservative money/fact reliability guard (judges only grounded fact-classes).
"""


# -- Task 1: USE_REASONING_PASS flag ---------------------------------------

def test_use_reasoning_pass_defaults_false():
    from app.config import Settings
    assert Settings().USE_REASONING_PASS is False


def test_use_reasoning_pass_parses_env(monkeypatch):
    monkeypatch.setenv("USE_REASONING_PASS", "true")
    from app.config import Settings
    assert Settings.from_env().USE_REASONING_PASS is True


def test_use_reasoning_pass_pinned_off_on_engine_module():
    # conftest autouse pin must reach the engine module's own settings copy
    from app.agent.llm import parent_llm_engine as ple
    assert ple.settings.USE_REASONING_PASS is False
