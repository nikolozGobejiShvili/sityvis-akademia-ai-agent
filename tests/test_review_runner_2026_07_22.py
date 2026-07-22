"""Unit tests for tools/review_topic_capability.py (Capability #1 review
runner). Offline only.

* The YAML shape test just parses the review question set.
* The baseline drive test proves a SINGLE question is captured + written to
  JSON with the engine NOT involved (baseline is deterministic/free) — a
  "straight" bucket question whose trigger stem the camp-topic interceptor
  matches directly, so `run_parent_llm_turn` must never be called.
* The compare test exercises `--compare`'s markdown builder on two tiny fake
  JSONs (never touches the real tools/reports/*.json files).
* The capability (PAID, real OpenAI) path is never exercised with a real
  API key — the one test that pokes at it monkeypatches
  `parent_llm_engine.run_parent_llm_turn` to a fake, per the task brief.
"""
from __future__ import annotations

import dataclasses
import json

import app.config as config_module
import app.agent.llm.parent_llm_engine as ple
from app.flows import parent_flow
from app.services import conversation_service

import tools.review_topic_capability as runner


# ---------------------------------------------------------------------------
# YAML shape
# ---------------------------------------------------------------------------
def test_review_questions_yaml_has_20_questions_with_required_keys():
    questions = runner.load_questions()
    assert len(questions) == 20
    required = {"id", "topic", "bucket", "source", "q"}
    seen_ids = set()
    for q in questions:
        assert required.issubset(q.keys()), q
        assert q["id"] and q["id"] not in seen_ids
        seen_ids.add(q["id"])
        assert q["q"].strip()
        assert q["bucket"] in {"straight", "varied"}
        assert q["source"] in {"real", "crafted"}


# ---------------------------------------------------------------------------
# baseline single-question drive (offline, engine NOT involved)
# ---------------------------------------------------------------------------
def _pin_baseline_settings(monkeypatch):
    """Mirrors runner.set_env_for_config("baseline") at the settings-object
    level (pytest already imported app.config before this test runs, so the
    env-var trick alone would not take effect — the codebase's own idiom for
    this, per tests/conftest.py + tests/test_program_topic_tool_2026_07_22.py,
    is `dataclasses.replace` + `monkeypatch.setattr` on the modules' own
    `settings` bindings)."""
    swapped = dataclasses.replace(
        config_module.settings, USE_PARENT_LLM_ENGINE=True, USE_PROGRAM_TOPICS=False,
    )
    monkeypatch.setattr(parent_flow, "settings", swapped)
    monkeypatch.setattr(conversation_service, "settings", swapped)
    # Dead-season guard: reopen registration for the run (mirrors
    # reopen_camp_registration_for_run, but via monkeypatch so it auto-reverts
    # instead of leaking into other tests via a raw module-attribute patch).
    monkeypatch.setattr(
        "app.services.admin_config_service.get_camp_registration_status",
        lambda: "open",
    )


def test_drive_question_baseline_engine_not_involved(monkeypatch, tmp_path):
    _pin_baseline_settings(monkeypatch)

    def _boom(*_a, **_k):
        raise AssertionError(
            "run_parent_llm_turn must NOT be called for a 'straight' bucket "
            "question in baseline config — the deterministic interceptor "
            "must answer it directly.",
        )
    monkeypatch.setattr(ple, "run_parent_llm_turn", _boom)

    questions = runner.load_questions()
    straight_question = next(q for q in questions if q["bucket"] == "straight")

    reply = runner.drive_question(straight_question, "baseline")
    assert reply and reply.strip()

    result = runner._result_row(straight_question, reply)
    assert result["id"] == straight_question["id"]
    assert result["reply"] == reply

    # write_results_json writes into tools/reports/ — redirect it to a scratch
    # dir so the test never touches the real report file.
    monkeypatch.setattr(runner, "REPORTS_DIR", tmp_path)
    out_path = runner.write_results_json("baseline", [result])

    assert out_path.exists()
    assert out_path == tmp_path / "topic_review_baseline.json"
    written = json.loads(out_path.read_text(encoding="utf-8"))
    assert written == [result]
    assert written[0]["reply"].strip()


def test_run_config_baseline_writes_all_questions_offline(monkeypatch, tmp_path):
    """Broader smoke: --config baseline (in-process) over the FULL review set
    is 100% offline (real httpx blocked) and produces one reply per
    question, all non-empty — proving baseline is free/deterministic even
    for 'varied' bucket questions the interceptor misses (they fall back to
    the free legacy state machine instead of the paid engine).

    `runner.run_config` calls `reopen_camp_registration_for_run` internally,
    which does a RAW module-attribute patch (by design — safe for a one-shot
    script process). Pre-registering the same target with pytest's
    `monkeypatch` here (BEFORE that raw patch runs) makes teardown restore
    the TRUE original afterward regardless, so this test can't leak state
    into any other test in the session.
    """
    monkeypatch.setattr(runner, "REPORTS_DIR", tmp_path)
    monkeypatch.setattr(
        "app.services.admin_config_service.get_camp_registration_status",
        lambda: "open",
    )

    out_path = runner.run_config("baseline")

    assert out_path == tmp_path / "topic_review_baseline.json"
    written = json.loads(out_path.read_text(encoding="utf-8"))
    assert len(written) == 20
    for row in written:
        assert row["reply"].strip(), row["id"]


# ---------------------------------------------------------------------------
# --compare
# ---------------------------------------------------------------------------
_FAKE_QUESTIONS = [
    {"id": "S1", "topic": "safety", "bucket": "straight", "source": "crafted",
     "question": "ბანაკში უსაფრთხოება როგორ არის?"},
    {"id": "V1", "topic": "safety", "bucket": "varied", "source": "crafted",
     "question": "ღამით ვინმე ეყოლება გვერდით?"},
]


def _fake_results(reply_prefix: str) -> list[dict]:
    return [
        {**q, "reply": f"{reply_prefix} reply for {q['id']}"} for q in _FAKE_QUESTIONS
    ]


def test_build_compare_markdown_has_row_per_question_and_verdict_column():
    baseline = _fake_results("baseline")
    capability = _fake_results("capability")

    markdown = runner.build_compare_markdown(baseline, capability)

    header = "| id | topic | bucket | question | baseline reply | capability reply | operator verdict |"
    assert header in markdown
    assert "baseline reply for S1" in markdown
    assert "capability reply for S1" in markdown
    assert "baseline reply for V1" in markdown
    assert "capability reply for V1" in markdown
    # one data row per question id, each ending with an EMPTY verdict cell
    # for the operator to fill in.
    for q in _FAKE_QUESTIONS:
        row = next(line for line in markdown.splitlines() if line.startswith(f"| {q['id']} |"))
        assert row.rstrip().endswith("|  |")


def test_run_compare_writes_markdown_file(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "REPORTS_DIR", tmp_path)
    (tmp_path / "topic_review_baseline.json").write_text(
        json.dumps(_fake_results("baseline"), ensure_ascii=False), encoding="utf-8",
    )
    (tmp_path / "topic_review_capability.json").write_text(
        json.dumps(_fake_results("capability"), ensure_ascii=False), encoding="utf-8",
    )

    rc = runner.run_compare()
    assert rc == 0

    out_path = tmp_path / "topic_review_compare.md"
    assert out_path.exists()
    content = out_path.read_text(encoding="utf-8")
    for q in _FAKE_QUESTIONS:
        assert q["id"] in content


def test_run_compare_reports_missing_reports(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "REPORTS_DIR", tmp_path)
    rc = runner.run_compare()
    assert rc == 1
    assert not (tmp_path / "topic_review_compare.md").exists()


# ---------------------------------------------------------------------------
# capability (PAID) path — only ever exercised with a fake engine, never real
# OpenAI, per the task brief.
# ---------------------------------------------------------------------------
def test_capability_config_requires_yes_gate():
    rc = runner.run_and_report("capability", yes=False)
    assert rc == 1


def test_drive_question_capability_uses_fake_engine(monkeypatch):
    """Capability config: the interceptor yields and the (fake) engine
    answers. Monkeypatches run_parent_llm_turn to a fake — NEVER calls real
    OpenAI."""
    swapped = dataclasses.replace(
        config_module.settings, USE_PARENT_LLM_ENGINE=True, USE_PROGRAM_TOPICS=True,
    )
    monkeypatch.setattr(parent_flow, "settings", swapped)
    monkeypatch.setattr(conversation_service, "settings", swapped)
    monkeypatch.setattr(
        "app.services.admin_config_service.get_camp_registration_status",
        lambda: "open",
    )
    monkeypatch.setattr(ple, "run_parent_llm_turn", lambda *a, **k: "FAKE_ENGINE_REPLY")

    questions = runner.load_questions()
    question = next(q for q in questions if q["bucket"] == "straight")

    reply = runner.drive_question(question, "capability")
    assert reply == "FAKE_ENGINE_REPLY"
