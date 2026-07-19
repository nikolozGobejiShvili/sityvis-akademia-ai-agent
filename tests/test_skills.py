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
