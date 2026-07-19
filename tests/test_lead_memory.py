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
