"""Off-topic intelligence — USE_OFFTOPIC_INTELLIGENCE (2026-07-25).

Live bug (operator test): „მუფასა ვინაა?" / „სიმბა?" got a canned „clarify" or a
political refusal that referenced ბანაკი (camp is over). Root cause: the system
prompt hard-codes two camp-specific off-topic scripts (system_parent_v2.md) — the
political refusal says „ბანაკთან", and the unclear-phrase rule makes the LLM blindly
repeat-clarify an off-topic name. The deterministic interceptors already DEFER these
to the engine; the behaviour comes from the prompt.

When USE_OFFTOPIC_INTELLIGENCE is ON, `_build_system_prompt` rewrites those two lines
to be PROGRAM-AGNOSTIC and logic-oriented (out-of-scope → briefly say so + offer the
active programs; never reference camp; clarify only a real typo). OFF ⇒ the loaded
prompt is byte-identical.
"""
import dataclasses

from app.agent.llm import parent_llm_engine as ple
from app.config import Settings


def _prompt(monkeypatch, flag):
    swapped = dataclasses.replace(
        ple.settings,
        USE_OFFTOPIC_INTELLIGENCE=flag,
        USE_SLIM_PROMPTS=False, USE_LEAN_PROMPT=False,
    )
    monkeypatch.setattr(ple, "settings", swapped)
    return ple._build_system_prompt("", "PARENT")


def test_flag_defaults_false():
    assert Settings().USE_OFFTOPIC_INTELLIGENCE is False


def test_flag_parses_env(monkeypatch):
    monkeypatch.setenv("USE_OFFTOPIC_INTELLIGENCE", "true")
    assert Settings.from_env().USE_OFFTOPIC_INTELLIGENCE is True


# --- helper (pure) ---

def test_helper_noop_when_off(monkeypatch):
    monkeypatch.setattr(ple, "settings", dataclasses.replace(ple.settings, USE_OFFTOPIC_INTELLIGENCE=False))
    txt = "x " + ple._OFFTOPIC_POLITICAL_OLD + " y"
    assert ple._apply_offtopic_intelligence(txt) == txt


def test_helper_rewrites_when_on(monkeypatch):
    monkeypatch.setattr(ple, "settings", dataclasses.replace(ple.settings, USE_OFFTOPIC_INTELLIGENCE=True))
    txt = ple._OFFTOPIC_POLITICAL_OLD + "\n" + ple._OFFTOPIC_UNCLEAR_OLD
    out = ple._apply_offtopic_intelligence(txt)
    assert ple._OFFTOPIC_POLITICAL_OLD not in out
    assert ple._OFFTOPIC_POLITICAL_NEW in out
    assert ple._OFFTOPIC_UNCLEAR_NEW in out


# --- built prompt ---

def test_prompt_byte_identical_when_off(monkeypatch):
    p = _prompt(monkeypatch, False)
    # the original camp-specific scripts are present unchanged
    assert "ბანაკთან დაკავშირებულ კითხვებზე დაგეხმარებით" in p
    assert "როცა მომხმარებლის ფრაზა გაუგებარია, ჰკითხე" in p


def test_prompt_rewritten_when_on(monkeypatch):
    p = _prompt(monkeypatch, True)
    # camp reference gone, program-agnostic + off-topic logic in
    assert "ბანაკთან დაკავშირებულ კითხვებზე დაგეხმარებით" not in p
    assert "ჩვენს პროგრამებთან დაკავშირებით" in p
    assert "ჩვენს პროგრამებს არ ეხება" in p


def test_on_differs_from_off(monkeypatch):
    assert _prompt(monkeypatch, True) != _prompt(monkeypatch, False)
