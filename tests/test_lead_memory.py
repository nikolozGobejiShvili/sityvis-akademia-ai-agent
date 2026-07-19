def test_use_lead_memory_flag_defaults_false():
    from app.config import Settings
    assert Settings().USE_LEAD_MEMORY is False


def test_use_lead_memory_flag_parses_env(monkeypatch):
    monkeypatch.setenv("USE_LEAD_MEMORY", "true")
    from app.config import Settings
    assert Settings.from_env().USE_LEAD_MEMORY is True


def _lead(**kw):
    from app.models.lead import Lead
    return Lead(sender_id="s", platform="facebook", segment="PARENT", **kw)


def test_save_and_load_roundtrip(monkeypatch):
    from app.services import lead_memory_service as lm, redis_state_service as rss
    store = {}
    monkeypatch.setattr(rss, "is_enabled", lambda: True)
    monkeypatch.setattr(rss, "set_json", lambda k, v, ttl=None, **kw: store.__setitem__(k, v) or True)
    monkeypatch.setattr(rss, "get_json", lambda k: store.get(k))
    lm.save("facebook:P:s", _lead(child_age="10", name="ნინო"))
    mem = lm.load("facebook:P:s")
    assert mem["child_age"] == "10" and mem["name"] == "ნინო" and "updated_ts" in mem


def test_seed_only_fills_empty_fields():
    from app.services import lead_memory_service as lm
    lead = _lead(child_age="")
    lm.seed_lead(lead, {"child_age": "12", "name": "გია"})
    assert lead.child_age == "12" and lead.name == "გია"
    lead2 = _lead(child_age="7")
    lm.seed_lead(lead2, {"child_age": "12"})   # must NOT overwrite a known fact
    assert lead2.child_age == "7"


def test_seed_never_cross_assigns():
    from app.services import lead_memory_service as lm
    lead = _lead(child_age="", adult_age="")
    lm.seed_lead(lead, {"child_age": "10", "adult_age": "30"})
    assert lead.child_age == "10" and lead.adult_age == "30"   # each to its own field


def test_redis_disabled_is_graceful(monkeypatch):
    from app.services import lead_memory_service as lm, redis_state_service as rss
    monkeypatch.setattr(rss, "is_enabled", lambda: False)
    lm.save("facebook:P:s", _lead(child_age="10"))
    assert lm.load("facebook:P:s") is None


def test_booking_fields_not_persisted():
    from app.services import lead_memory_service as lm
    for f in ("booked_datetime_iso", "calendar_event_id", "calendly_booked"):
        assert f not in lm.DURABLE_FIELDS


def test_maybe_seed_new_lead_flag_off_is_noop(monkeypatch):
    import dataclasses
    from app import config
    from app.services import lead_memory_service as lm
    from app.models.conversation import Conversation
    monkeypatch.setattr(lm, "settings", dataclasses.replace(config.settings, USE_LEAD_MEMORY=False))
    conv = Conversation(sender_id="s", platform="facebook", page_id="P")
    conv.lead = _lead(child_age="")
    called = {"load": 0}
    monkeypatch.setattr(lm, "load", lambda k: called.__setitem__("load", called["load"] + 1))
    lm.maybe_seed_new_lead(conv)
    assert called["load"] == 0 and conv.lead.child_age == ""


def test_maybe_seed_new_lead_flag_on_seeds(monkeypatch):
    import dataclasses
    from app import config
    from app.services import lead_memory_service as lm
    from app.models.conversation import Conversation
    monkeypatch.setattr(lm, "settings", dataclasses.replace(config.settings, USE_LEAD_MEMORY=True))
    monkeypatch.setattr(lm, "load", lambda k: {"child_age": "9"})
    conv = Conversation(sender_id="s", platform="facebook", page_id="P")
    conv.lead = _lead(child_age="")
    lm.maybe_seed_new_lead(conv)
    assert conv.lead.child_age == "9"


def test_seed_lead_non_dict_memory_is_noop():
    from app.services import lead_memory_service as lm
    lead = _lead(child_age="")
    lm.seed_lead(lead, ["not", "a", "dict"])
    assert lead.child_age == ""
    lm.seed_lead(lead, None)
    assert lead.child_age == ""


def test_memory_key_coerces_non_str():
    from app.services import lead_memory_service as lm
    assert lm.memory_key(123) == "leadmem:123"


# -- Task 3: seed on lead creation (both flows) + persist after save --------

def test_parent_ensure_lead_seeds_on_create(monkeypatch):
    import dataclasses
    from app import config
    from app.flows import parent_flow as pf
    from app.services import lead_memory_service as lm
    from app.models.conversation import Conversation
    monkeypatch.setattr(lm, "settings", dataclasses.replace(config.settings, USE_LEAD_MEMORY=True))
    monkeypatch.setattr(lm, "load", lambda k: {"child_age": "8", "name": "ანა"})
    conv = Conversation(sender_id="s", platform="facebook", page_id="P")
    lead = pf._ensure_lead(conv)         # first creation → seeded
    assert lead.child_age == "8" and lead.name == "ანა" and lead.segment == "PARENT"


def test_adult_ensure_lead_seeds_on_create(monkeypatch):
    import dataclasses
    from app import config
    from app.flows import adult_flow as af
    from app.services import lead_memory_service as lm
    from app.models.conversation import Conversation
    monkeypatch.setattr(lm, "settings", dataclasses.replace(config.settings, USE_LEAD_MEMORY=True))
    monkeypatch.setattr(lm, "load", lambda k: {"adult_age": "34"})
    conv = Conversation(sender_id="s", platform="facebook", page_id="P")
    lead = af._ensure_lead(conv)
    assert lead.adult_age == "34" and lead.segment == "ADULT"


def test_ensure_lead_flag_off_not_seeded(monkeypatch):
    import dataclasses
    from app import config
    from app.flows import parent_flow as pf
    from app.services import lead_memory_service as lm
    from app.models.conversation import Conversation
    monkeypatch.setattr(lm, "settings", dataclasses.replace(config.settings, USE_LEAD_MEMORY=False))
    monkeypatch.setattr(lm, "load", lambda k: {"child_age": "8"})
    conv = Conversation(sender_id="s", platform="facebook", page_id="P")
    assert pf._ensure_lead(conv).child_age == ""     # flag off ⇒ blank


def test_ensure_lead_does_not_reseed_existing(monkeypatch):
    import dataclasses
    from app import config
    from app.flows import parent_flow as pf
    from app.services import lead_memory_service as lm
    from app.models.conversation import Conversation
    monkeypatch.setattr(lm, "settings", dataclasses.replace(config.settings, USE_LEAD_MEMORY=True))
    calls = {"n": 0}
    monkeypatch.setattr(lm, "load", lambda k: calls.__setitem__("n", calls["n"] + 1) or {"child_age": "8"})
    conv = Conversation(sender_id="s", platform="facebook", page_id="P")
    pf._ensure_lead(conv); pf._ensure_lead(conv); pf._ensure_lead(conv)
    assert calls["n"] == 1                            # seed only on first creation


# -- Task 4: END-TO-END acceptance — a returning lead's child age is
# remembered across TWO conversations. Proves the whole round-trip on the live
# path: the REAL per-turn save hook in
# `conversation_service._process_message_impl` writes a durable `leadmem:`
# record (directly covering the persist side a reviewer flagged as untested),
# and after the 8-day conversation TTL lapses a fresh conversation's
# `parent_flow._ensure_lead` seeds the new lead from that record so
# `parent_llm_engine._build_context_message` tells the model the age (the
# "don't re-ask" precondition).
#
# A SINGLE in-memory dict backs `redis_state_service.get_json/set_json/delete/
# is_enabled`, so BOTH the `conversation:*` write-through and the `leadmem:*`
# store live in it — the real save + real load run against the same backing.
# `USE_LEAD_MEMORY=True` is frozen on every module the path reads the flag
# (`conversation_service`, `parent_flow`, `lead_memory_service`) via
# `dataclasses.replace` + a module monkeypatch, mirroring the frozen-settings
# idiom in `tests/test_dynamic_programs_phase2.py`.


def _inmemory_redis(monkeypatch):
    """Back redis_state_service with ONE dict (conversation:* + leadmem:*
    both live here). Returns the store so the test can inspect / expire keys."""
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


def _freeze_lead_memory_on(monkeypatch):
    """Enable USE_LEAD_MEMORY on every module on the round-trip path."""
    import dataclasses
    from app import config
    from app.services import conversation_service as cs, lead_memory_service as lm
    from app.flows import parent_flow as pf
    swapped = dataclasses.replace(config.settings, USE_LEAD_MEMORY=True)
    for mod in (cs, pf, lm):
        monkeypatch.setattr(mod, "settings", swapped)


def test_e2e_returning_lead_child_age_remembered_across_conversations(monkeypatch):
    from app.services import conversation_service as cs
    from app.flows import parent_flow as pf
    from app.agent.llm import parent_llm_engine as ple

    store = _inmemory_redis(monkeypatch)
    _freeze_lead_memory_on(monkeypatch)
    cs.conversations.clear()

    # -- Conversation A — exercise the REAL save hook ----------------------
    # A real turn runs through `conversation_service.process_message`. The
    # PARENT flow handler is stubbed to a fixed reply so the turn is
    # deterministic (no OpenAI) and never mutates the lead — the SAVE HOOK
    # under test lives in `_process_message_impl` DOWNSTREAM of the flow and
    # is NOT stubbed. `child_age="10"` is arranged on the lead before the turn.
    conv_a = cs._get_or_create_conversation("u1", "facebook", "P1")
    conv_a.segment = "PARENT"
    conv_a.lead = _lead(child_age="10")
    monkeypatch.setattr(pf, "handle", lambda conversation, message: "მადლობა.")

    cs.process_message(
        sender_id="u1", message_text="გამარჯობა",
        platform="facebook", page_id="P1",
    )

    # The real per-turn save hook wrote a durable leadmem: record THROUGH
    # conversation_service (not a direct lead_memory_service.save call).
    mem_keys = [k for k in store if k.startswith("leadmem:")]
    assert mem_keys, "the per-turn save hook must write a leadmem: key"
    assert store["leadmem:facebook:P1:u1"]["child_age"] == "10"

    # -- Simulate the 8-day conversation TTL expiry ------------------------
    # Drop the conversation:* write-through AND the in-memory cache, but KEEP
    # the durable leadmem:* record — exactly the state after the rolling
    # 8-day conversation window lapses while lead memory (~1y TTL) survives.
    for k in [k for k in store if k.startswith("conversation:")]:
        del store[k]
    cs.conversations.clear()
    assert [k for k in store if k.startswith("leadmem:")], \
        "durable lead memory must survive the conversation-TTL expiry"

    # -- Conversation B — same sender, genuinely fresh conversation --------
    conv_b = cs._get_or_create_conversation("u1", "facebook", "P1")
    assert conv_b.lead is None, "expiry must yield a fresh conversation (no restore)"

    lead_b = pf._ensure_lead(conv_b)      # first creation → seeded from memory
    assert lead_b.child_age == "10", \
        "returning lead's child age must be seeded from durable memory"

    # The model is TOLD the age → it will not re-ask it.
    context = ple._build_context_message(conv_b, conv_b.lead, "ისევ მოვედი")
    assert "child_age=10" in context and "10" in context
