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


# -- Task 5: e2e — the skills loop end to end (USE_SKILLS) ------------------
#
# Task 1-4 proved each layer in isolation (flag / parser+loader / matcher /
# prompt injection, the last with `select_skills` MOCKED). This section
# proves the layers COMPOSE: Step 1 drops a real SKILL.md file on disk (no
# Python change — simulating an operator) and drives it through the REAL
# `load_skills()` -> `select_skills()` -> `_build_system_prompt()` pipeline.
# Step 2 drives a REAL `parent_flow.handle()` turn (mocked `chat_with_tools`
# only) to prove the selected pack's body reaches the engine's system
# message on an actual tool-calling turn — mirroring the `_mk_response` /
# two-call `_chat` idiom in tests/test_parent_llm_engine.py and the Phase-5
# reuse e2e in tests/test_learning.py
# (`test_approved_answer_reused_through_engine_tool_loop`).


def test_e2e_new_skill_pack_reaches_prompt_with_no_python_change(tmp_path, monkeypatch):
    """Step 1: an operator drops a brand-new SKILL.md file into SKILLS_DIR —
    zero Python/code change — and it flows through the REAL load_skills() ->
    select_skills() -> _build_system_prompt() pipeline (no mocking of
    select_skills, unlike the Task 4 tests above). Flag ON ⇒ the pack's name
    + body reach the prompt. Flag OFF ⇒ the pack is absent AND the prompt is
    byte-identical to the no-args call (mirrors
    test_build_system_prompt_byte_identical_when_flag_off)."""
    from app.services import skills_service

    d = tmp_path / "skills"
    d.mkdir()
    (d / "e2e-new-pack.md").write_text(
        "---\n"
        "id: e2e-new-pack\n"
        "name: E2E New Pack\n"
        "segment: PARENT\n"
        "status: active\n"
        "priority: 5\n"
        "triggers:\n"
        "  - ე2ე-ტრიგერი\n"
        "---\n"
        "E2E-NEW-PACK-BODY-MARKER: მიჰყევი ამ მიდგომას.\n",
        encoding="utf-8",
    )
    # Simulates the operator dropping a file into the real skills directory
    # — no `select_skills`/`load_skills` mock, no code edit.
    monkeypatch.setattr(skills_service, "SKILLS_DIR", d)

    trigger_message = "ეს არის ე2ე-ტრიგერი შეტყობინება"

    # Flag ON — the new pack reaches the prompt.
    ple = _swap_flag(monkeypatch, USE_SKILLS=True)
    prompt_on = ple._build_system_prompt(trigger_message, "PARENT")
    assert "E2E New Pack" in prompt_on
    assert "E2E-NEW-PACK-BODY-MARKER" in prompt_on

    # Flag OFF — pack absent, and the prompt is byte-identical to the
    # no-args call (same invariant as Task 4's byte-identical test).
    ple = _swap_flag(monkeypatch, USE_SKILLS=False)
    prompt_off = ple._build_system_prompt(trigger_message, "PARENT")
    assert "E2E New Pack" not in prompt_off
    assert "E2E-NEW-PACK-BODY-MARKER" not in prompt_off
    assert prompt_off == ple._build_system_prompt()


def _mk_skills_engine_response(*, content: str = "", tool_calls: list | None = None):
    """Minimal duck-typed OpenAI response object matching what
    `parent_llm_engine` reads off `openai_service.chat_with_tools(...)`.
    Replicates `tests/test_parent_llm_engine.py::_mk_response` (mirrors
    `tests/test_learning.py::_mk_learning_engine_response`) so this e2e test
    is self-contained in this file."""
    from types import SimpleNamespace

    tc_objs = []
    for tc in tool_calls or []:
        tc_objs.append(SimpleNamespace(
            id=tc["id"],
            function=SimpleNamespace(
                name=tc["name"], arguments=tc.get("arguments", "{}"),
            ),
        ))
    msg = SimpleNamespace(content=content or None, tool_calls=tc_objs or None)
    choice = SimpleNamespace(message=msg)
    return SimpleNamespace(choices=[choice])


def _fresh_skills_engine_conversation(sender_id: str):
    """Mirrors `tests/test_parent_llm_engine.py`'s `fresh_conversation`
    fixture (and `tests/test_learning.py::_fresh_learning_engine_conversation`):
    a Conversation with one pre-seeded assistant turn so the bot's
    first-reply static-welcome bypass doesn't short-circuit engine
    routing."""
    from app.models.conversation import Conversation

    conv = Conversation(sender_id=sender_id, platform="instagram")
    conv.history.append({"role": "assistant", "content": "_test_prior_welcome"})
    return conv


def test_e2e_skill_pack_reaches_engine_system_message_through_real_turn(tmp_path, monkeypatch):
    """Step 2: with BOTH `USE_PARENT_LLM_ENGINE` (read by `parent_flow.settings`)
    and `USE_SKILLS` (read by `parent_llm_engine.settings`) on — two
    independent module-level `settings` references, exactly like the Phase-5
    reuse e2e — a REAL `parent_flow.handle()` turn drives the engine's
    tool-calling loop against a mocked `chat_with_tools`. The driving message
    is "more details please", the SAME neutral trigger phrase
    `tests/test_parent_llm_engine.py` (`test_history_is_forwarded`,
    `test_tool_loop_caps_iterations`) and the Phase-5 reuse e2e
    (`tests/test_learning.py::test_approved_answer_reused_through_engine_tool_loop`)
    use to reach the engine unintercepted by any deterministic pre-engine
    handler. Asserts (a) the selected pack's body + name are present in the
    concatenated system-message blocks sent on the tool-call turn, and (b)
    the mocked LLM was actually driven — so the test cannot pass vacuously."""
    import dataclasses
    import json

    from app import config
    from app.agent.llm import parent_llm_engine
    from app.agent.tools.parent_tools import TOOL_GET_CAMP_INFO
    from app.flows import parent_flow
    from app.services import messenger_service, openai_service, skills_service

    d = tmp_path / "skills"
    d.mkdir()
    (d / "e2e-turn-pack.md").write_text(
        "---\n"
        "id: e2e-turn-pack\n"
        "name: E2E Turn Pack\n"
        "segment: PARENT\n"
        "status: active\n"
        "priority: 5\n"
        "triggers:\n"
        "  - details\n"
        "---\n"
        "E2E-TURN-PACK-BODY-MARKER: use this situational approach.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(skills_service, "SKILLS_DIR", d)

    monkeypatch.setattr(
        parent_flow, "settings",
        dataclasses.replace(config.settings, USE_PARENT_LLM_ENGINE=True),
    )
    monkeypatch.setattr(
        parent_llm_engine, "settings",
        dataclasses.replace(config.settings, USE_SKILLS=True),
    )
    monkeypatch.setattr(messenger_service, "get_user_profile", lambda sid, plat: {})
    # Mirrors test_parent_llm_engine.py's `camp_registration_open` fixture /
    # the Phase-5 reuse e2e — without it a real-clock registration-closed
    # date can pre-empt the engine with a deterministic answer.
    monkeypatch.setattr(
        "app.services.admin_config_service.get_camp_registration_status",
        lambda: "open",
    )

    question = "more details please"
    final_reply = "დეტალებს გიზუსტებთ."

    captured_calls: list[dict] = []

    def _chat(**kwargs):
        captured_calls.append(kwargs)
        if len(captured_calls) == 1:
            return _mk_skills_engine_response(tool_calls=[{
                "id": "call_1",
                "name": TOOL_GET_CAMP_INFO,
                "arguments": json.dumps({"topic": "price"}),
            }])
        return _mk_skills_engine_response(content=final_reply)

    monkeypatch.setattr(openai_service, "chat_with_tools", _chat)

    conv = _fresh_skills_engine_conversation("skills_e2e_turn")
    out = parent_flow.handle(conv, question)

    assert out == final_reply

    # Non-vacuous: the mock was actually driven (the tool-call + final-answer
    # loop makes this 2, but the assertion only requires the "actually
    # driven" bar from the brief).
    assert len(captured_calls) >= 1

    system_texts = "\n".join(
        m.get("content", "") for m in captured_calls[0]["messages"]
        if m.get("role") == "system"
    )
    assert "E2E-TURN-PACK-BODY-MARKER" in system_texts
    assert "E2E Turn Pack" in system_texts
