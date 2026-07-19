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


# -- Task 2: SKILL.md parser + registry loader -----------------------------

def test_parse_skill_md_frontmatter_and_body():
    from app.services.skills_service import _parse_skill_md
    meta, body = _parse_skill_md(
        "---\nid: x\nsegment: PARENT\ntriggers:\n  - ძვირ\n---\nსხეული აქ.\n"
    )
    assert meta["id"] == "x"
    assert meta["segment"] == "PARENT"
    assert meta["triggers"] == ["ძვირ"]
    assert body.strip() == "სხეული აქ."


def test_parse_skill_md_no_frontmatter_is_tolerant():
    from app.services.skills_service import _parse_skill_md
    meta, body = _parse_skill_md("plain body, no fence")
    assert meta == {}
    assert body == "plain body, no fence"


def test_parse_skill_md_malformed_never_raises():
    from app.services.skills_service import _parse_skill_md
    # unterminated fence + non-string
    assert _parse_skill_md("---\nnot closed") == ({}, "---\nnot closed")
    assert _parse_skill_md(None) == ({}, "")


def test_parse_skill_md_body_starting_with_dash_preserved():
    # critique M1: a body that starts with a markdown rule / bullet must survive
    from app.services.skills_service import _parse_skill_md
    meta, body = _parse_skill_md("---\nid: x\n---\n- პირველი პუნქტი\n- მეორე\n")
    assert meta["id"] == "x"
    assert body.startswith("- პირველი პუნქტი")


def test_load_skills_reads_seed_packs():
    from app.services import skills_service
    skills = skills_service.load_skills()
    ids = {s["id"] for s in skills}
    assert "objection-handling" in ids
    assert "new-program-onboarding" in ids
    # README.md is never loaded as a skill
    assert "README" not in ids
    # shape
    oh = next(s for s in skills if s["id"] == "objection-handling")
    assert oh["segment"] == "PARENT"
    assert oh["status"] == "active"
    assert isinstance(oh["priority"], int)
    assert "ძვირ" in oh["triggers"]
    assert oh["body"].strip()


def test_load_skills_missing_dir_is_graceful(monkeypatch, tmp_path):
    from app.services import skills_service
    monkeypatch.setattr(skills_service, "SKILLS_DIR", tmp_path / "nope")
    assert skills_service.load_skills() == []


def test_load_skills_malformed_file_skipped(monkeypatch, tmp_path):
    from app.services import skills_service
    d = tmp_path / "skills"
    d.mkdir()
    (d / "good.md").write_text(
        "---\nid: good\nsegment: any\ntriggers:\n  - აბ\n---\nსხეული", encoding="utf-8"
    )
    (d / "bad.md").write_text("\x00\x01 not yaml frontmatter", encoding="utf-8")
    monkeypatch.setattr(skills_service, "SKILLS_DIR", d)
    ids = {s["id"] for s in skills_service.load_skills()}
    assert "good" in ids  # the bad file must not crash the whole load


# -- Task 3: select_skills matcher -----------------------------------------

def _mk_skill(**kw):
    base = {"id": "s", "name": "S", "segment": "PARENT", "status": "active",
            "priority": 0, "triggers": ["ძვირ"], "body": "ტანი"}
    base.update(kw)
    return base


def test_select_skills_trigger_and_segment_hit(monkeypatch):
    from app.services import skills_service as ss
    monkeypatch.setattr(ss, "load_skills", lambda: [_mk_skill(id="a", triggers=["ძვირ"])])
    got = ss.select_skills("ეს ძვირია ცოტა", "PARENT")
    assert [s["id"] for s in got] == ["a"]


def test_select_skills_no_hit_returns_empty(monkeypatch):
    from app.services import skills_service as ss
    monkeypatch.setattr(ss, "load_skills", lambda: [_mk_skill(triggers=["ძვირ"])])
    assert ss.select_skills("გამარჯობა", "PARENT") == []


def test_select_skills_hidden_never_selected(monkeypatch):
    from app.services import skills_service as ss
    monkeypatch.setattr(ss, "load_skills", lambda: [_mk_skill(status="hidden", triggers=["ძვირ"])])
    assert ss.select_skills("ძვირია", "PARENT") == []


def test_select_skills_segment_mismatch_and_any(monkeypatch):
    from app.services import skills_service as ss
    monkeypatch.setattr(ss, "load_skills", lambda: [
        _mk_skill(id="p", segment="PARENT", triggers=["ძვირ"]),
        _mk_skill(id="a", segment="any", triggers=["ძვირ"]),
        _mk_skill(id="d", segment="ADULT", triggers=["ძვირ"]),
    ])
    ids = {s["id"] for s in ss.select_skills("ძვირია", "PARENT")}
    assert ids == {"p", "a"}  # ADULT-only excluded; "any" matches


def test_select_skills_short_trigger_never_matches_alone(monkeypatch):
    from app.services import skills_service as ss
    monkeypatch.setattr(ss, "load_skills", lambda: [_mk_skill(triggers=["აბ"])])  # 2-char
    assert ss.select_skills("აბგ დეფ", "PARENT") == []


def test_select_skills_bounded_and_ranked(monkeypatch):
    from app.services import skills_service as ss
    monkeypatch.setattr(ss, "load_skills", lambda: [
        _mk_skill(id="low", priority=1, triggers=["ძვირ"]),
        _mk_skill(id="hi", priority=99, triggers=["ძვირ"]),
        _mk_skill(id="two", priority=5, triggers=["ძვირ", "ფასი მაღალ"]),
    ])
    got = ss.select_skills("ძვირია და ფასი მაღალია", "PARENT", limit=2)
    # "two" scores 2 (both triggers) → first; then higher-priority of the score-1 pair
    assert [s["id"] for s in got] == ["two", "hi"]


def test_select_skills_never_raises(monkeypatch):
    from app.services import skills_service as ss
    monkeypatch.setattr(ss, "load_skills", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    assert ss.select_skills("ძვირია", "PARENT") == []
    assert ss.select_skills(None, None) == []


def test_select_skills_bad_triggers_does_not_drop_other_skills(monkeypatch):
    # review Important: a malformed `triggers` on ONE skill must not abort
    # scoring for the whole batch — other well-formed skills still match.
    from app.services import skills_service as ss
    monkeypatch.setattr(ss, "load_skills", lambda: [
        {"id": "bad", "name": "B", "segment": "any", "status": "active",
         "priority": 0, "triggers": 5, "body": "x"},
        _mk_skill(id="good", triggers=["ძვირ"]),
    ])
    assert [s["id"] for s in ss.select_skills("ძვირია", "PARENT")] == ["good"]


# -- Task 4: inject selected skills into _build_system_prompt --------------

def _swap_flag(monkeypatch, **flags):
    import dataclasses
    from app import config
    from app.agent.llm import parent_llm_engine as ple
    swapped = dataclasses.replace(config.settings, **flags)
    monkeypatch.setattr(ple, "settings", swapped)
    return ple


def test_skills_suffix_empty_when_flag_off(monkeypatch):
    ple = _swap_flag(monkeypatch, USE_SKILLS=False)
    assert ple._skills_prompt_suffix("ძვირია", "PARENT") == ""


def test_skills_suffix_empty_when_no_match(monkeypatch):
    ple = _swap_flag(monkeypatch, USE_SKILLS=True)
    from app.services import skills_service
    monkeypatch.setattr(skills_service, "select_skills", lambda m, s, **k: [])
    assert ple._skills_prompt_suffix("გამარჯობა", "PARENT") == ""


def test_skills_suffix_injects_selected_body(monkeypatch):
    ple = _swap_flag(monkeypatch, USE_SKILLS=True)
    from app.services import skills_service
    monkeypatch.setattr(
        skills_service, "select_skills",
        lambda m, s, **k: [{"id": "x", "name": "ტესტ-უნარი", "body": "გამოიყენე X მიდგომა."}],
    )
    out = ple._skills_prompt_suffix("ძვირია", "PARENT")
    assert "ტესტ-უნარი" in out
    assert "გამოიყენე X მიდგომა." in out


def test_build_system_prompt_byte_identical_when_flag_off(monkeypatch):
    # With USE_SKILLS off, adding the message/segment args must not change output.
    ple = _swap_flag(monkeypatch, USE_SKILLS=False)
    assert ple._build_system_prompt("ძვირია", "PARENT") == ple._build_system_prompt()


def test_build_system_prompt_appends_skill_when_on(monkeypatch):
    ple = _swap_flag(monkeypatch, USE_SKILLS=True)
    from app.services import skills_service
    monkeypatch.setattr(
        skills_service, "select_skills",
        lambda m, s, **k: [{"id": "x", "name": "N", "body": " B-guidance."}],
    )
    base = ple._build_system_prompt()  # no message → suffix "" (empty message)
    withskill = ple._build_system_prompt("ძვირია", "PARENT")
    assert "B-guidance." in withskill
    assert withskill.startswith(base)  # skills append at the end, base unchanged
