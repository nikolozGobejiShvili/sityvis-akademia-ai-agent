"""Openclaw stack integration check (2026-07-26).

The full built-but-dormant stack — USE_SKILLS + USE_LEAD_MEMORY + USE_LEARNING +
USE_REASONING_PASS + USE_OBJECTION_ENGINE_ROUTING — enabled TOGETHER composes
end-to-end without breaking. FREE: every external dep (OpenAI, Redis) is mocked;
no live call. The per-flag suites already prove each subsystem ALONE; this file
proves they do not interfere when ALL are ON at once (the operator's paid
`--llm --judge` eval is what decides whether the stack is BETTER than canned —
that quality verdict is out of scope here).
"""
import dataclasses
from types import SimpleNamespace as NS

from app import config
from app.agent.llm import parent_llm_engine as ple
from app.flows import parent_flow
from app.services import openai_service, skills_service
from app.services import lead_memory_service as lm
from app.services import learning_log_service as ll
from app.services import redis_state_service as rss
from app.models.conversation import Conversation
from app.models.lead import Lead

_STACK = dict(
    USE_PARENT_LLM_ENGINE=True,
    USE_SKILLS=True,
    USE_LEAD_MEMORY=True,
    USE_LEARNING=True,
    USE_REASONING_PASS=True,
    USE_OBJECTION_ENGINE_ROUTING=True,
)

_VALID_PLAN = ('{"user_goal":"price","sentiment":"neutral","needed_facts":["price"],'
               '"missing_lead_fields":[],"suggested_tool":"get_camp_info",'
               '"should_greet":false,"plan":"answer the price"}')


def _engine_reply(content):
    return NS(choices=[NS(message=NS(content=content, tool_calls=None))])


def _skill(**kw):
    base = {"id": "pricing", "name": "Pricing", "segment": "PARENT", "status": "active",
            "priority": 0, "triggers": ["ფასი", "ძვირ"], "body": "value-first playbook"}
    base.update(kw)
    return base


def _inmemory_redis(monkeypatch):
    store = {}
    monkeypatch.setattr(rss, "is_enabled", lambda: True)
    monkeypatch.setattr(rss, "set_json", lambda k, v, ttl=None, **kw: store.__setitem__(k, v) or True)
    monkeypatch.setattr(rss, "get_json", lambda k: store.get(k))
    monkeypatch.setattr(rss, "delete", lambda k: (store.pop(k, None), True)[1])
    return store


def _enable_stack(monkeypatch):
    # Only modules with a module-level `settings` gate on it here. learning_log_service
    # has none — USE_LEARNING is checked by the CALLER (the engine, via ple.settings),
    # and log_turn itself is redis-gated only.
    swapped = dataclasses.replace(config.settings, **_STACK)
    for mod in (ple, lm, parent_flow):
        monkeypatch.setattr(mod, "settings", swapped)
    return swapped


def _parent_conv():
    return Conversation(sender_id="s", platform="facebook")


def _parent_lead(**kw):
    d = dict(sender_id="s", platform="facebook", segment="PARENT")
    d.update(kw)
    return Lead(**d)


# 1) the whole stack drives a full engine turn without crashing
def test_full_stack_engine_turn_returns_valid_reply(monkeypatch):
    _enable_stack(monkeypatch)
    _inmemory_redis(monkeypatch)
    monkeypatch.setattr(skills_service, "load_skills", lambda: [_skill()])
    calls = {"analyze": 0}

    def _analyze(*a, **k):
        calls["analyze"] += 1
        return _VALID_PLAN

    monkeypatch.setattr(openai_service, "analyze_parent_turn", _analyze)
    monkeypatch.setattr(openai_service, "chat_with_tools",
                        lambda **k: _engine_reply("ბანაკის ფასია 2150 ლარი."))
    out = ple.run_parent_llm_turn(
        user_message="რა ღირს ბანაკი?",
        conversation=_parent_conv(),
        lead=_parent_lead(),
        sender_id="s",
        platform="facebook",
    )
    assert isinstance(out, str) and out.strip()   # a real reply came back
    assert calls["analyze"] >= 1                   # the reasoning pass ran atop the stack


# 2) skills inject into the PARENT prompt with the full stack on
def test_skills_suffix_present_with_full_stack(monkeypatch):
    _enable_stack(monkeypatch)
    monkeypatch.setattr(skills_service, "load_skills", lambda: [_skill()])
    suffix = ple._skills_prompt_suffix("ფასი ძვირია", "PARENT")
    assert "value-first playbook" in suffix
    assert "სიტუაციური უნარები" in suffix


# 3) memory + learning FUNCTION (not just no-op) with the full stack on
def test_memory_and_learning_active_with_full_stack(monkeypatch):
    _enable_stack(monkeypatch)
    _inmemory_redis(monkeypatch)
    lm.save("facebook:P:s", _parent_lead(child_age="10", name="ანა"))
    loaded = lm.load("facebook:P:s")
    assert loaded and loaded.get("child_age") == "10"      # memory round-trips
    ll.log_turn({
        "ts": "2026-07-26T10:00:00Z",
        "session_key": "facebook:P:s",
        "segment": "PARENT",
        "program_id": "camp_2026",
        "outcome": "answered",
        "question": "ფასი რამდენია?",
        "answer_preview": "2150₾-ია.",
    })
    recs = ll.recent(10)
    assert isinstance(recs, list) and len(recs) == 1        # learning log writes + reads
    assert recs[0]["outcome"] == "answered"


# 4) objection deferral fires with the full stack on (biggest 3b INFORMATION domain)
def test_objection_defers_with_full_stack(monkeypatch):
    _enable_stack(monkeypatch)
    conv = _parent_conv()
    conv.history.append({"role": "assistant", "content": "_prior"})
    conv.lead = _parent_lead(child_age="14")
    # hesitation ("მოვიფიქრებ") + objection marker ("ძვირია") → DEFER to the engine
    assert parent_flow._maybe_handle_decline_engine(conv, "მოვიფიქრებ, ძვირია") is None


# 5) sanity: default (all flags OFF, conftest-pinned) is the byte-identical no-stack path
def test_stack_off_is_default_byte_identical():
    assert ple.settings.USE_REASONING_PASS is False
    assert ple.settings.USE_SKILLS is False
    assert ple.settings.USE_LEAD_MEMORY is False
    assert ple.settings.USE_LEARNING is False
    assert ple.settings.USE_OBJECTION_ENGINE_ROUTING is False
    assert ple._skills_prompt_suffix("ფასი", "PARENT") == ""   # no suffix when off
