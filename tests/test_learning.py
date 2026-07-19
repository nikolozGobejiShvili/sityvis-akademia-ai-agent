def test_use_learning_flag_defaults_false():
    from app.config import Settings
    assert Settings().USE_LEARNING is False


def test_use_learning_flag_parses_env(monkeypatch):
    monkeypatch.setenv("USE_LEARNING", "true")
    from app.config import Settings
    assert Settings.from_env().USE_LEARNING is True


# -- Task 2: outcome classifier (pure) + PII-masked capped log store -------

def _conv(**kw):
    from app.models.conversation import Conversation
    return Conversation(sender_id="s", platform="facebook", **kw)


def _lead(**kw):
    from app.models.lead import Lead
    return Lead(sender_id="s", platform="facebook", segment="PARENT", **kw)


def test_classify_outcome_empty_response():
    from app.reasoning.outcome_classifier import classify_outcome
    conv = _conv(segment="PARENT")
    lead = _lead()
    assert classify_outcome(conv, lead, "") == "empty"
    assert classify_outcome(conv, lead, "   ") == "empty"
    assert classify_outcome(conv, lead, None) == "empty"


def test_classify_outcome_booked_via_calendly_flag():
    from app.reasoning.outcome_classifier import classify_outcome
    conv = _conv(segment="PARENT")
    lead = _lead(calendly_booked=True)
    assert classify_outcome(conv, lead, "მადლობა.") == "booked"


def test_classify_outcome_booked_via_datetime_iso():
    from app.reasoning.outcome_classifier import classify_outcome
    conv = _conv(segment="PARENT")
    lead = _lead(booked_datetime_iso="2026-07-20T10:00:00")
    assert classify_outcome(conv, lead, "მადლობა.") == "booked"


def test_classify_outcome_handed_off():
    from app.reasoning.outcome_classifier import classify_outcome
    conv = _conv(segment="PARENT")
    lead = _lead()
    assert classify_outcome(conv, lead, "მენეჯერს გადავცემ.", manager_notified=True) == "handed_off"


def test_classify_outcome_unclear_segment():
    from app.reasoning.outcome_classifier import classify_outcome
    conv = _conv(segment="UNCLEAR")
    lead = _lead()
    assert classify_outcome(conv, lead, "დაზუსტება გთხოვთ.") == "unclear"


def test_classify_outcome_answered_default():
    from app.reasoning.outcome_classifier import classify_outcome
    conv = _conv(segment="PARENT")
    lead = _lead()
    assert classify_outcome(conv, lead, "ბანაკის ფასია 2150₾.") == "answered"


def test_classify_outcome_priority_booked_over_unclear():
    from app.reasoning.outcome_classifier import classify_outcome
    conv = _conv(segment="UNCLEAR")
    lead = _lead(calendly_booked=True)
    assert classify_outcome(conv, lead, "მადლობა.") == "booked"


def test_classify_outcome_never_raises_on_none_lead_and_conversation():
    from app.reasoning.outcome_classifier import classify_outcome
    assert classify_outcome(None, None, "პასუხი") == "answered"
    assert classify_outcome(None, None, "") == "empty"
    assert classify_outcome(None, None, "პასუხი", manager_notified=True) == "handed_off"


def _inmemory_learning_redis(monkeypatch):
    """Back redis_state_service with one in-memory dict for the learning log
    tests, mirroring the pattern used in tests/test_lead_memory.py."""
    from app.services import redis_state_service as rss
    store: dict = {}
    monkeypatch.setattr(rss, "is_enabled", lambda: True)
    monkeypatch.setattr(
        rss, "set_json",
        lambda k, v, ttl_seconds=None, **kw: (store.__setitem__(k, v), True)[1],
    )
    monkeypatch.setattr(rss, "get_json", lambda k: store.get(k))
    monkeypatch.setattr(rss, "delete", lambda k: (store.pop(k, None), True)[1])
    return store


def test_log_turn_roundtrip(monkeypatch):
    from app.services import learning_log_service as lls
    store = _inmemory_learning_redis(monkeypatch)
    lls.log_turn({
        "ts": "2026-07-19T10:00:00Z",
        "session_key": "facebook:P:s",
        "segment": "PARENT",
        "program_id": "camp_2026",
        "outcome": "answered",
        "question": "ფასი რამდენია?",
        "answer_preview": "2150₾-ია.",
    })
    records = lls.recent(50)
    assert len(records) == 1
    assert records[0]["outcome"] == "answered"
    assert records[0]["segment"] == "PARENT"
    assert lls.LOG_KEY in store


def test_log_turn_masks_phone_in_question_and_answer(monkeypatch):
    from app.services import learning_log_service as lls
    _inmemory_learning_redis(monkeypatch)
    lls.log_turn({
        "ts": "2026-07-19T10:00:00Z",
        "session_key": "facebook:P:s",
        "segment": "PARENT",
        "program_id": "",
        "outcome": "answered",
        "question": "ჩემი ნომერია 555123456",
        "answer_preview": "მადლობა, ნომერი 555123456 მივიღეთ.",
    })
    records = lls.recent(50)
    assert len(records) == 1
    stored = records[0]
    assert "555123456" not in stored["question"]
    assert "555123456" not in stored["answer_preview"]
    assert "[ტელეფონი]" in stored["question"]
    assert "[ტელეფონი]" in stored["answer_preview"]


def test_log_turn_cap_enforced(monkeypatch):
    from app.services import learning_log_service as lls
    _inmemory_learning_redis(monkeypatch)
    for i in range(600):
        lls.log_turn({
            "ts": "2026-07-19T10:00:00Z",
            "session_key": f"facebook:P:s{i}",
            "segment": "PARENT",
            "program_id": "",
            "outcome": "answered",
            "question": f"question {i}",
            "answer_preview": f"answer {i}",
        })
    records = lls.recent(1000)
    assert len(records) <= lls.MAX_RECORDS
    # the most recent record must be the last one written (nothing wrapped
    # around / reordered)
    assert records[-1]["session_key"] == "facebook:P:s599"


def test_log_turn_redis_off_is_graceful(monkeypatch):
    from app.services import learning_log_service as lls, redis_state_service as rss
    monkeypatch.setattr(rss, "is_enabled", lambda: False)
    lls.log_turn({"question": "test", "answer_preview": "test"})
    assert lls.recent() == []


def test_log_turn_never_raises_on_bad_records(monkeypatch):
    from app.services import learning_log_service as lls
    _inmemory_learning_redis(monkeypatch)
    # empty dict — missing keys must not raise
    lls.log_turn({})
    # non-dict "record" — must not raise, must not be stored
    lls.log_turn(None)
    lls.log_turn("not a dict")
    lls.log_turn(["not", "a", "dict"])
    records = lls.recent(50)
    assert len(records) == 1  # only the empty dict was a valid record
    assert records[0] == {}


def test_reset_clears_log(monkeypatch):
    from app.services import learning_log_service as lls
    store = _inmemory_learning_redis(monkeypatch)
    lls.log_turn({"question": "q", "answer_preview": "a"})
    assert lls.LOG_KEY in store
    lls.reset()
    assert lls.LOG_KEY not in store


# -- PII mask boundary/form coverage (review fix: >=6-digit runs, not >=7) --

def test_log_turn_masks_bare_six_digit_number(monkeypatch):
    from app.services import learning_log_service as lls
    _inmemory_learning_redis(monkeypatch)
    lls.log_turn({
        "ts": "2026-07-19T10:00:00Z",
        "session_key": "facebook:P:s",
        "segment": "PARENT",
        "program_id": "",
        "outcome": "answered",
        "question": "კოდი 123456 დაიმახსოვრე",
        "answer_preview": "მადლობა.",
    })
    records = lls.recent(50)
    assert len(records) == 1
    stored = records[0]
    assert "123456" not in stored["question"]
    assert "[ტელეფონი]" in stored["question"]


def test_log_turn_does_not_mask_five_digit_price(monkeypatch):
    from app.services import learning_log_service as lls
    _inmemory_learning_redis(monkeypatch)
    lls.log_turn({
        "ts": "2026-07-19T10:00:00Z",
        "session_key": "facebook:P:s",
        "segment": "PARENT",
        "program_id": "",
        "outcome": "answered",
        "question": "ფასი 21500",
        "answer_preview": "დიახ.",
    })
    records = lls.recent(50)
    assert len(records) == 1
    stored = records[0]
    assert "21500" in stored["question"]
    assert "[ტელეფონი]" not in stored["question"]


def test_log_turn_masks_spaced_phone_form(monkeypatch):
    from app.services import learning_log_service as lls
    _inmemory_learning_redis(monkeypatch)
    lls.log_turn({
        "ts": "2026-07-19T10:00:00Z",
        "session_key": "facebook:P:s",
        "segment": "PARENT",
        "program_id": "",
        "outcome": "answered",
        "question": "დამირეკეთ 555 12 34 56",
        "answer_preview": "კარგი.",
    })
    records = lls.recent(50)
    assert len(records) == 1
    stored = records[0]
    assert "555 12 34 56" not in stored["question"]
    assert "[ტელეფონი]" in stored["question"]


def test_log_turn_masks_dashed_phone_form(monkeypatch):
    from app.services import learning_log_service as lls
    _inmemory_learning_redis(monkeypatch)
    lls.log_turn({
        "ts": "2026-07-19T10:00:00Z",
        "session_key": "facebook:P:s",
        "segment": "PARENT",
        "program_id": "",
        "outcome": "answered",
        "question": "დამირეკეთ 555-12-34-56",
        "answer_preview": "კარგი.",
    })
    records = lls.recent(50)
    assert len(records) == 1
    stored = records[0]
    assert "555-12-34-56" not in stored["question"]
    assert "[ტელეფონი]" in stored["question"]


# -- classify_outcome priority coverage --------------------------------

def test_classify_outcome_empty_beats_booked():
    from app.reasoning.outcome_classifier import classify_outcome
    conv = _conv(segment="PARENT")
    booked_lead = _lead(calendly_booked=True)
    assert classify_outcome(conv, booked_lead, "") == "empty"


def test_classify_outcome_booked_beats_handed_off():
    from app.reasoning.outcome_classifier import classify_outcome
    conv = _conv(segment="PARENT")
    lead = _lead(calendly_booked=True)
    assert classify_outcome(conv, lead, "მადლობა.", manager_notified=True) == "booked"


# -- Task 3: wire outcome logging into the conversation chokepoint ---------
#
# Mirrors the Phase-4 lead-memory e2e save-hook idiom in
# tests/test_lead_memory.py (`test_e2e_returning_lead_child_age_remembered_
# across_conversations`): pre-create the Conversation via
# `_get_or_create_conversation`, pin its segment so routing is deterministic,
# stub `parent_flow.handle` so no OpenAI call is made, back
# `redis_state_service` with one in-memory dict, and drive the REAL
# `conversation_service.process_message` entry point so the actual
# `_process_message_impl` post-response hook under test runs unstubbed.


def _inmemory_learning_log_redis(monkeypatch):
    from app.services import redis_state_service as rss
    store: dict = {}
    monkeypatch.setattr(rss, "is_enabled", lambda: True)
    monkeypatch.setattr(
        rss, "set_json",
        lambda k, v, ttl_seconds=None, **kw: (store.__setitem__(k, v), True)[1],
    )
    monkeypatch.setattr(rss, "get_json", lambda k: store.get(k))
    monkeypatch.setattr(rss, "delete", lambda k: (store.pop(k, None), True)[1])
    return store


def test_process_message_logs_outcome_when_flag_on(monkeypatch):
    import dataclasses
    from app import config
    from app.services import conversation_service as cs
    from app.services import learning_log_service as lls
    from app.flows import parent_flow as pf

    _inmemory_learning_log_redis(monkeypatch)
    monkeypatch.setattr(
        cs, "settings", dataclasses.replace(config.settings, USE_LEARNING=True),
    )
    cs.conversations.clear()

    conv = cs._get_or_create_conversation("u1", "facebook", "P1")
    conv.segment = "PARENT"
    monkeypatch.setattr(pf, "handle", lambda conversation, message: "მადლობა.")

    response = cs.process_message(
        sender_id="u1", message_text="გამარჯობა",
        platform="facebook", page_id="P1",
    )
    assert response == "მადლობა."

    records = lls.recent(50)
    assert len(records) >= 1
    assert records[-1]["outcome"] == "answered"
    assert records[-1]["segment"] == "PARENT"
    assert records[-1]["session_key"] == "facebook:P1:u1"
    # ts is spec-mandated (record shape {ts, session_key, segment, ...}); the
    # caller is the sole source since log_turn does not stamp it.
    assert records[-1]["ts"]


def test_process_message_no_log_when_flag_off(monkeypatch):
    import dataclasses
    from app import config
    from app.services import conversation_service as cs
    from app.services import learning_log_service as lls
    from app.flows import parent_flow as pf

    _inmemory_learning_log_redis(monkeypatch)
    monkeypatch.setattr(
        cs, "settings", dataclasses.replace(config.settings, USE_LEARNING=False),
    )
    cs.conversations.clear()

    conv = cs._get_or_create_conversation("u1", "facebook", "P1")
    conv.segment = "PARENT"
    monkeypatch.setattr(pf, "handle", lambda conversation, message: "მადლობა.")

    cs.process_message(
        sender_id="u1", message_text="გამარჯობა",
        platform="facebook", page_id="P1",
    )

    assert lls.recent(50) == []


# -- Task 4: operator-editable approved-answers store + matcher ------------
#
# Mirrors camp_topic_facts._score / detect_camp_topic (trigger-substring
# scoring, strictly-greater tie-break, best_score > 0 gate) and
# admin_config_service._safe_load_yaml (tolerant fresh read, never raises).
# Tests inject the answer list via monkeypatching load_answers — never write
# test data into the tracked seed YAML.


def _answer(id_, triggers, answer, segment="any", status="active"):
    return {
        "id": id_,
        "triggers": triggers,
        "answer": answer,
        "segment": segment,
        "status": status,
    }


def test_load_answers_reads_seed_yaml_returns_list():
    from app.services import approved_answers_service as aas
    result = aas.load_answers()
    assert isinstance(result, list)


def test_find_approved_answer_triggers_and_segment_hit(monkeypatch):
    from app.services import approved_answers_service as aas
    answers = [_answer("a1", ["ალერგია", "დიეტა"], "ალერგიის შემთხვევაში მენეჯერი დაგეხმარებათ.", segment="PARENT")]
    monkeypatch.setattr(aas, "load_answers", lambda: answers)
    result = aas.find_approved_answer("შვილს აქვს ალერგია", "PARENT")
    assert result == {"id": "a1", "answer": "ალერგიის შემთხვევაში მენეჯერი დაგეხმარებათ."}


def test_find_approved_answer_no_match_returns_none(monkeypatch):
    from app.services import approved_answers_service as aas
    answers = [_answer("a1", ["ალერგია"], "პასუხი", segment="PARENT")]
    monkeypatch.setattr(aas, "load_answers", lambda: answers)
    assert aas.find_approved_answer("სულ სხვა კითხვაა", "PARENT") is None


def test_find_approved_answer_hidden_never_returned(monkeypatch):
    from app.services import approved_answers_service as aas
    answers = [_answer("a1", ["ალერგია"], "პასუხი", segment="PARENT", status="hidden")]
    monkeypatch.setattr(aas, "load_answers", lambda: answers)
    assert aas.find_approved_answer("აქვს ალერგია", "PARENT") is None


def test_find_approved_answer_segment_mismatch_returns_none(monkeypatch):
    from app.services import approved_answers_service as aas
    answers = [_answer("a1", ["ალერგია"], "პასუხი", segment="ADULT")]
    monkeypatch.setattr(aas, "load_answers", lambda: answers)
    assert aas.find_approved_answer("აქვს ალერგია", "PARENT") is None


def test_find_approved_answer_segment_any_matches_both(monkeypatch):
    from app.services import approved_answers_service as aas
    answers = [_answer("a1", ["ალერგია"], "პასუხი", segment="any")]
    monkeypatch.setattr(aas, "load_answers", lambda: answers)
    assert aas.find_approved_answer("აქვს ალერგია", "PARENT") == {"id": "a1", "answer": "პასუხი"}
    assert aas.find_approved_answer("აქვს ალერგია", "ADULT") == {"id": "a1", "answer": "პასუხი"}


def test_find_approved_answer_malformed_yaml_graceful(monkeypatch):
    from app.services import approved_answers_service as aas

    def _boom():
        raise ValueError("malformed yaml")

    monkeypatch.setattr(aas, "load_answers", _boom)
    assert aas.find_approved_answer("აქვს ალერგია", "PARENT") is None


def test_load_answers_missing_file_returns_empty(monkeypatch, tmp_path):
    from app.services import approved_answers_service as aas
    monkeypatch.setattr(aas, "ANSWERS_PATH", tmp_path / "does_not_exist.yaml")
    assert aas.load_answers() == []


def test_load_answers_malformed_yaml_returns_empty(monkeypatch, tmp_path):
    from app.services import approved_answers_service as aas
    bad = tmp_path / "approved_answers.yaml"
    bad.write_text("answers: [this is not: valid: yaml: [", encoding="utf-8")
    monkeypatch.setattr(aas, "ANSWERS_PATH", bad)
    assert aas.load_answers() == []


def test_load_answers_wrong_shape_returns_empty(monkeypatch, tmp_path):
    from app.services import approved_answers_service as aas
    wrong = tmp_path / "approved_answers.yaml"
    wrong.write_text("answers: 'not a list'", encoding="utf-8")
    monkeypatch.setattr(aas, "ANSWERS_PATH", wrong)
    assert aas.load_answers() == []


def test_find_approved_answer_short_trigger_never_matches_alone(monkeypatch):
    from app.services import approved_answers_service as aas
    answers = [_answer("a1", ["ია"], "პასუხი", segment="any")]
    monkeypatch.setattr(aas, "load_answers", lambda: answers)
    assert aas.find_approved_answer("რაღაც ტექსტი აქ ია", "PARENT") is None


def test_find_approved_answer_highest_score_wins(monkeypatch):
    from app.services import approved_answers_service as aas
    answers = [
        _answer("a1", ["ალერგია"], "მოკლე პასუხი", segment="any"),
        _answer("a2", ["ალერგია", "დიეტა", "საკვები"], "სრული პასუხი", segment="any"),
    ]
    monkeypatch.setattr(aas, "load_answers", lambda: answers)
    result = aas.find_approved_answer("აქვს ალერგია და დიეტა საკვები", "PARENT")
    assert result == {"id": "a2", "answer": "სრული პასუხი"}


def test_find_approved_answer_tie_break_earliest_wins(monkeypatch):
    from app.services import approved_answers_service as aas
    answers = [
        _answer("a1", ["ალერგია"], "პირველი", segment="any"),
        _answer("a2", ["ალერგია"], "მეორე", segment="any"),
    ]
    monkeypatch.setattr(aas, "load_answers", lambda: answers)
    result = aas.find_approved_answer("აქვს ალერგია", "PARENT")
    assert result == {"id": "a1", "answer": "პირველი"}


def test_find_approved_answer_never_raises_on_non_dict_rows(monkeypatch):
    from app.services import approved_answers_service as aas
    monkeypatch.setattr(aas, "load_answers", lambda: ["not a dict", None, 123])
    assert aas.find_approved_answer("აქვს ალერგია", "PARENT") is None


def test_find_approved_answer_never_raises_on_missing_keys(monkeypatch):
    from app.services import approved_answers_service as aas
    monkeypatch.setattr(aas, "load_answers", lambda: [{"id": "a1"}])
    assert aas.find_approved_answer("აქვს ალერგია", "PARENT") is None


def test_find_approved_answer_empty_message_returns_none(monkeypatch):
    from app.services import approved_answers_service as aas
    answers = [_answer("a1", ["ალერგია"], "პასუხი", segment="any")]
    monkeypatch.setattr(aas, "load_answers", lambda: answers)
    assert aas.find_approved_answer("", "PARENT") is None
    assert aas.find_approved_answer(None, "PARENT") is None


# -- Task 5: get_approved_answer tool + prompt hint (USE_LEARNING) ---------
#
# Mirrors the Phase-1 (P4-1 Task 2/3) dynamic-programs tool wiring pattern in
# tests/test_dynamic_programs.py: build_active_tools flag-composition tests,
# a guarded executor handler test, and a prompt-suffix flag-gate test using
# dataclasses.replace(...) + monkeypatch.setattr(parent_llm_engine, "settings", ...)
# because app.config.Settings is a frozen dataclass.


def test_build_active_tools_flag_off_matches_today():
    from app.agent.llm.parent_llm_engine import build_active_tools
    from app.agent.tools.parent_tools import PARENT_TOOLS
    names = [t["function"]["name"] for t in build_active_tools(False)]
    assert names == [t["function"]["name"] for t in PARENT_TOOLS]
    assert "get_approved_answer" not in names


def test_build_active_tools_learning_flag_adds_get_approved_answer():
    from app.agent.llm.parent_llm_engine import build_active_tools
    names = {t["function"]["name"] for t in build_active_tools(False, True)}
    assert "get_approved_answer" in names


def test_build_active_tools_both_flags_compose():
    from app.agent.llm.parent_llm_engine import build_active_tools
    names = {t["function"]["name"] for t in build_active_tools(True, True)}
    assert "list_programs" in names
    assert "get_approved_answer" in names


def _make_learning_executor(segment="PARENT"):
    from app.agent.tools.parent_tool_executor import ParentToolExecutor
    from app.models.lead import Lead
    from app.models.conversation import Conversation
    conv = Conversation(sender_id="t", platform="facebook", segment=segment)
    lead = Lead(sender_id="t", platform="facebook", segment=segment)
    return ParentToolExecutor(conversation=conv, lead=lead, sender_id="t", platform="facebook")


def test_executor_get_approved_answer_returns_match(monkeypatch):
    from app.services import approved_answers_service as aas
    executor = _make_learning_executor()
    monkeypatch.setattr(
        aas, "find_approved_answer",
        lambda question, segment: {"id": "a1", "answer": "ალერგიის შემთხვევაში მენეჯერი დაგეხმარებათ."},
    )
    result = executor._get_approved_answer({"question": "შვილს აქვს ალერგია"})
    assert result == {
        "success": True, "id": "a1",
        "answer": "ალერგიის შემთხვევაში მენეჯერი დაგეხმარებათ.",
    }


def test_executor_get_approved_answer_no_match(monkeypatch):
    from app.services import approved_answers_service as aas
    executor = _make_learning_executor()
    monkeypatch.setattr(aas, "find_approved_answer", lambda question, segment: None)
    result = executor._get_approved_answer({"question": "სულ სხვა კითხვაა"})
    assert result == {"success": False, "reason": "no_approved_answer"}


def test_executor_get_approved_answer_dispatched_via_execute(monkeypatch):
    from app.services import approved_answers_service as aas
    executor = _make_learning_executor()
    monkeypatch.setattr(
        aas, "find_approved_answer",
        lambda question, segment: {"id": "a1", "answer": "პასუხი"},
    )
    result = executor.execute("get_approved_answer", {"question": "ალერგია"})
    assert result["success"] is True
    assert result["id"] == "a1"
    assert result["answer"] == "პასუხი"


def test_approved_answer_prompt_suffix_empty_when_flag_off(monkeypatch):
    import dataclasses
    from app.agent.llm import parent_llm_engine

    off_settings = dataclasses.replace(parent_llm_engine.settings, USE_LEARNING=False)
    monkeypatch.setattr(parent_llm_engine, "settings", off_settings)

    assert parent_llm_engine._approved_answer_prompt_suffix() == ""


def test_approved_answer_prompt_suffix_nonempty_when_flag_on(monkeypatch):
    import dataclasses
    from app.agent.llm import parent_llm_engine

    on_settings = dataclasses.replace(parent_llm_engine.settings, USE_LEARNING=True)
    monkeypatch.setattr(parent_llm_engine, "settings", on_settings)

    suffix = parent_llm_engine._approved_answer_prompt_suffix()
    assert suffix != ""
    assert "get_approved_answer" in suffix


# -- Task 6: e2e — the whole Phase-5 loop composes end to end --------------
#
# (a) logging e2e with PII masking: mirrors
# `test_process_message_logs_outcome_when_flag_on` above, but drives an
# inbound message that CONTAINS a phone-like number and asserts the
# *logged* record is masked (not just the raw log_turn unit tests earlier
# in this file — this proves the real conversation_service chokepoint
# masks end to end).
#
# (b) approved-answer REUSE e2e through the engine tool-loop: mirrors the
# `_mk_response` / two-call `_chat` idiom in tests/test_parent_llm_engine.py
# (see its price-question test, ~line 289-312), replicated minimally here
# so this file is self-contained. Both `USE_PARENT_LLM_ENGINE` (read by
# `parent_flow.settings`) and `USE_LEARNING` (read by
# `parent_llm_engine.settings`) must be flipped on — they are two
# independent module-level `settings` references, exactly like the
# existing flag-swap idioms in this file and in test_parent_llm_engine.py.


def test_process_message_logs_outcome_masks_phone_number_in_question(monkeypatch):
    """RED-first sanity: before wiring, asserting `"555123456" not in
    question` against an UNMASKED record would fail. GREEN below drives the
    real (already-shipped) masking chokepoint end to end."""
    import dataclasses
    from app import config
    from app.services import conversation_service as cs
    from app.services import learning_log_service as lls
    from app.flows import parent_flow as pf

    _inmemory_learning_log_redis(monkeypatch)
    monkeypatch.setattr(
        cs, "settings", dataclasses.replace(config.settings, USE_LEARNING=True),
    )
    cs.conversations.clear()

    conv = cs._get_or_create_conversation("u2", "facebook", "P1")
    conv.segment = "PARENT"
    monkeypatch.setattr(pf, "handle", lambda conversation, message: "მადლობა.")

    response = cs.process_message(
        sender_id="u2", message_text="ჩემი ნომერია 555123456",
        platform="facebook", page_id="P1",
    )
    assert response == "მადლობა."

    records = lls.recent(50)
    assert len(records) >= 1
    last = records[-1]
    assert last["outcome"]
    assert last["session_key"] == "facebook:P1:u2"
    # PII mask must reach the STORED record via the real conversation_service
    # -> learning_log_service chokepoint (Task 3 wiring over Task 2 masking).
    assert "555123456" not in last["question"]
    assert "[ტელეფონი]" in last["question"]


def _mk_learning_engine_response(*, content: str = "", tool_calls: list | None = None):
    """Minimal duck-typed OpenAI response object matching what
    `parent_llm_engine` reads off `openai_service.chat_with_tools(...)`.
    Replicates `tests/test_parent_llm_engine.py::_mk_response` so this e2e
    test is self-contained in this file."""
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


def _fresh_learning_engine_conversation(sender_id: str):
    """Mirrors test_parent_llm_engine.py's `fresh_conversation` fixture: a
    Conversation with one pre-seeded assistant turn so the first-reply
    static-welcome bypass doesn't short-circuit engine routing."""
    from app.models.conversation import Conversation

    conv = Conversation(sender_id=sender_id, platform="instagram")
    conv.history.append({"role": "assistant", "content": "_test_prior_welcome"})
    return conv


def test_learning_flag_off_tool_not_offered_and_suffix_empty():
    """RED counterpart for part (b): flag off ⇒ get_approved_answer is not
    in the active tool set and the prompt suffix is empty."""
    from app.agent.llm.parent_llm_engine import (
        _approved_answer_prompt_suffix,
        build_active_tools,
    )
    from app.config import Settings

    off = Settings()
    assert off.USE_LEARNING is False
    names = {t["function"]["name"] for t in build_active_tools(off.USE_DYNAMIC_PROGRAMS, off.USE_LEARNING)}
    assert "get_approved_answer" not in names
    assert _approved_answer_prompt_suffix() == ""


def test_approved_answer_reused_through_engine_tool_loop(monkeypatch):
    """GREEN: with USE_PARENT_LLM_ENGINE + USE_LEARNING both on, a mocked
    LLM calls get_approved_answer, the executor surfaces an
    operator-injected match, and the model's final reply (also mocked, as
    the real LLM would do after seeing success:true) carries the vetted
    answer through parent_flow.handle end to end. Also proves the tool was
    OFFERED and the prompt suffix was PRESENT on the very call that made
    the tool available — not just unit-tested in isolation."""
    import dataclasses
    import json

    from app import config
    from app.agent.llm import parent_llm_engine
    from app.flows import parent_flow
    from app.services import approved_answers_service, messenger_service, openai_service

    monkeypatch.setattr(
        parent_flow, "settings",
        dataclasses.replace(config.settings, USE_PARENT_LLM_ENGINE=True),
    )
    monkeypatch.setattr(
        parent_llm_engine, "settings",
        dataclasses.replace(config.settings, USE_LEARNING=True),
    )
    monkeypatch.setattr(messenger_service, "get_user_profile", lambda sid, plat: {})
    # Mirrors test_parent_llm_engine.py's `camp_registration_open` fixture —
    # without it, a real-clock registration-closed date can pre-empt the
    # engine with a deterministic closed-registration answer before the
    # LLM (and its tool loop) ever runs.
    monkeypatch.setattr(
        "app.services.admin_config_service.get_camp_registration_status",
        lambda: "open",
    )

    # "more details please" is the exact driving message
    # test_parent_llm_engine.py::test_history_forwarded_to_llm and
    # test_tool_loop_caps_iterations use to reach the engine's
    # chat_with_tools call unconditionally (verified here by probing —
    # several Georgian phrasings, incl. a bare "ფასი?", are now intercepted
    # by a NEWER deterministic pre-engine price-copy handler
    # (`parent_flow._camp_price_full_block`, added after this file's
    # earlier price-question test was written) and never reach the LLM at
    # all). The LLM mock below decides the tool-call arguments and final
    # content — the actual routing intent doesn't matter here since we're
    # proving the tool-loop plumbing, not intent classification.
    question = "more details please"
    vetted_answer = "ფასი ინდივიდუალურად განისაზღვრება — დეტალებს მენეჯერი დაგიზუსტებთ."

    monkeypatch.setattr(
        approved_answers_service, "find_approved_answer",
        lambda q, seg: {"id": "a1", "answer": vetted_answer},
    )

    captured_calls: list[dict] = []

    def _chat(**kwargs):
        captured_calls.append(kwargs)
        if len(captured_calls) == 1:
            return _mk_learning_engine_response(tool_calls=[{
                "id": "call_1",
                "name": "get_approved_answer",
                "arguments": json.dumps({"question": question}),
            }])
        return _mk_learning_engine_response(content=vetted_answer)

    monkeypatch.setattr(openai_service, "chat_with_tools", _chat)

    conv = _fresh_learning_engine_conversation("learning_e2e_reuse")
    out = parent_flow.handle(conv, question)

    # (1) the final reply carries the vetted answer through.
    assert vetted_answer in out

    # The tool loop must have made exactly two chat_with_tools calls: the
    # tool-call turn, then the final-answer turn.
    assert len(captured_calls) == 2

    # (2) the tool WAS OFFERED on the call that produced the tool_call.
    first_tool_names = {
        t["function"]["name"] for t in captured_calls[0]["tools"]
    }
    assert "get_approved_answer" in first_tool_names

    # (3) the prompt suffix WAS PRESENT in the system messages sent on
    # that same call.
    system_texts = "\n".join(
        m.get("content", "") for m in captured_calls[0]["messages"]
        if m.get("role") == "system"
    )
    assert "დამტკიცებული პასუხ" in system_texts
    assert "get_approved_answer" in system_texts
