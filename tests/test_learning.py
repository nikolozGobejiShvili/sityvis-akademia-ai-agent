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
