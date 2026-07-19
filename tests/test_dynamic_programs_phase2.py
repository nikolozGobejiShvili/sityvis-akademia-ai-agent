from app.reasoning.dynamic_program_match import match_dynamic_program, _AMBIGUOUS_TAG_STEMS

_ROBOTICS = {"id": "robotics_club", "name": "რობოტიკის კლუბი", "type": "kids_program",
             "status": "active", "hashtags": ["რობოტიკა", "robotics"]}
_ADULT = {"id": "adult_events", "name": "ზრდასრულთა ღონისძიება", "type": "adult_events",
          "status": "active", "hashtags": ["ღონისძიება", "საღამო"]}
_CAMP = {"id": "summer_camp", "name": "საზაფხულო ბანაკი", "type": "camp",
         "status": "active", "hashtags": ["ბანაკი", "camp"]}

def test_matches_inflected_program_name():
    assert match_dynamic_program("რობოტიკის კლუბი რა ღირს?", [_ROBOTICS, _ADULT, _CAMP]) \
        == {"program_id": "robotics_club", "type": "kids_program"}

def test_no_latin_substring_false_positive():
    assert match_dynamic_program("this is a campaign about prevention", [_CAMP]) is None

def test_bare_ambiguous_hashtag_does_not_hijack_to_adult():
    m = match_dynamic_program("ბანაკში საღამოს რა ხდება?", [_ADULT, _CAMP])
    assert m is None or m["program_id"] == "summer_camp"   # never adult via bare "საღამო"

def test_empty_and_no_match():
    assert match_dynamic_program("", [_ROBOTICS]) is None
    assert match_dynamic_program("ამინდი როგორია დღეს", [_ROBOTICS]) is None

def test_ambiguous_stems_cover_classifier_keywords():
    # Drift guard: every camp/adult/price keyword the router already owns must be
    # reflected in the matcher's ambiguous set, so a hashtag equal to one of them
    # can never trigger a dynamic override. Fails if someone adds a keyword to
    # conversation_service without updating _AMBIGUOUS_TAG_STEMS.
    from app.services.conversation_service import (
        CAMP_KEYWORDS, ADULT_KEYWORDS, PRICE_KEYWORDS,
    )
    amb = tuple(_AMBIGUOUS_TAG_STEMS)
    for kw in (*CAMP_KEYWORDS, *ADULT_KEYWORDS, *PRICE_KEYWORDS):
        k = kw.lower()
        assert any(k.startswith(a) or a.startswith(k) for a in amb), \
            f"classifier keyword {kw!r} not covered by _AMBIGUOUS_TAG_STEMS"

def test_ambiguous_word_in_name_does_not_hijack():
    poetry = {"id": "poetry", "name": "პოეზიის საღამო", "type": "adult_events",
              "status": "active", "hashtags": []}
    # A bare ambiguous word ("საღამო") appearing in the message must NOT match
    # the program via its NAME token, same as the hashtag-gating rule.
    assert match_dynamic_program("დღეს საღამოს რა ხდება?", [poetry]) is None
    # But a program with a specific (non-ambiguous) name token is still matched
    # by that specific word.
    assert match_dynamic_program("რობოტიკის კლუბი რა ღირს?", [_ROBOTICS, poetry]) \
        == {"program_id": "robotics_club", "type": "kids_program"}

def test_inactive_section_not_matched():
    inactive_robotics = dict(_ROBOTICS, status="inactive")
    assert match_dynamic_program("რობოტიკის კლუბი რა ღირს?", [inactive_robotics]) is None


# Task 2 — routing delegates to the precise matcher (gate 1).

def test_routing_prefers_dynamic_then_classifier(monkeypatch):
    import dataclasses
    from app import config
    from app.services import conversation_service as cs, admin_config_service
    monkeypatch.setattr(admin_config_service, "get_active_sections",
                        lambda: [_ADULT, _CAMP, _ROBOTICS])
    monkeypatch.setattr(cs, "settings", dataclasses.replace(config.settings, USE_DYNAMIC_PROGRAMS=True))
    # a genuine dynamic program routes PARENT via the matcher
    assert cs._match_active_program_segment("რობოტიკის კლუბი რა ღირს?") == "PARENT"
    # a camp-context message is NOT force-routed to ADULT by a bare adult hashtag
    assert cs._match_active_program_segment("ბანაკში საღამოს რა ხდება?") in ("PARENT", None)
    # flag off ⇒ None
    monkeypatch.setattr(cs, "settings", dataclasses.replace(config.settings, USE_DYNAMIC_PROGRAMS=False))
    assert cs._match_active_program_segment("რობოტიკის კლუბი რა ღირს?") is None


# Task 3 — interceptor bypass placed BEFORE the deterministic chain (gate 2).

def test_is_dynamic_program_turn(monkeypatch):
    import dataclasses
    from app import config
    from app.flows import parent_flow as pf
    from app.services import admin_config_service
    monkeypatch.setattr(admin_config_service, "get_active_sections",
                        lambda: [_ROBOTICS, _CAMP, _ADULT])
    monkeypatch.setattr(pf, "settings", dataclasses.replace(config.settings, USE_DYNAMIC_PROGRAMS=True))
    assert pf._is_dynamic_program_turn("რობოტიკის კლუბი რა ღირს?") is True
    assert pf._is_dynamic_program_turn("ბანაკი რა ღირს?") is False       # camp (hardcoded)
    assert pf._is_dynamic_program_turn("მადლობა, არ მინდა") is False     # names no program
    monkeypatch.setattr(pf, "settings", dataclasses.replace(config.settings, USE_DYNAMIC_PROGRAMS=False))
    assert pf._is_dynamic_program_turn("რობოტიკის კლუბი რა ღირს?") is False


def _dyn_engine_conv(monkeypatch, msg_program_only=True):
    import dataclasses
    from app import config
    from app.flows import parent_flow as pf
    from app.services import admin_config_service
    from app.models.conversation import Conversation
    monkeypatch.setattr(admin_config_service, "get_active_sections", lambda: [_ROBOTICS])
    monkeypatch.setattr(pf, "settings", dataclasses.replace(
        config.settings, USE_DYNAMIC_PROGRAMS=True, USE_PARENT_LLM_ENGINE=True))
    monkeypatch.setattr(pf, "_run_llm_engine_safely", lambda *a, **k: "ENGINE_ANSWER")
    # Pin camp registration OPEN. `_maybe_handle_final_camp_public_policy`
    # (parent_flow.py:304, called ~line 1003 — BEFORE the `engine_flag` gate
    # and thus structurally outside this guard's reach) treats ANY generic
    # price question ("ღირს"/"ფასი"/...) as a CAMP price question once
    # registration is CLOSED, because its camp-intent check
    # (`_is_camp_price_intent` / `_CAMP_PRICE_MARKERS`) has no camp-keyword
    # requirement and only excludes Sunday-School/adult-event vocabulary —
    # not other dynamic programs. That is a genuine pre-gate hijack outside
    # Task 3's scope (see p2-task-3-report.md); pinning registration OPEN
    # here isolates this test suite to the gate-2 guard under test.
    monkeypatch.setattr(pf, "_is_camp_registration_open", lambda: True)
    # sentinels: NO camp-content interceptor may answer a dynamic-program turn
    # (bound via a default arg so each sentinel reports its OWN name, not the
    # last value of the loop variable via late-binding closure).
    for name in ("_maybe_handle_repeat_camp_price", "_maybe_handle_out_of_range_age",
                 "_maybe_handle_camp_intro", "_maybe_handle_camp_topic_facts"):
        monkeypatch.setattr(pf, name, lambda *a, _n=name, **k: f"CAMP:{_n}")
    return pf, Conversation(sender_id="t", platform="facebook", segment="PARENT")


def test_dynamic_price_reaches_engine(monkeypatch):
    pf, conv = _dyn_engine_conv(monkeypatch)
    out = pf._handle_core(conv, "რობოტიკის კლუბი რა ღირს?")
    assert out == "ENGINE_ANSWER" and "CAMP" not in out


def test_dynamic_age_bearing_not_hijacked_by_camp_eligibility(monkeypatch):
    # the v1 guard (below out_of_range_age) would have failed this. The message
    # is NOT the conversation's first turn (a bot turn is seeded) so the
    # topic-agnostic first-turn brand welcome (`_maybe_static_welcome`, which
    # fires on ANY first message regardless of topic — see
    # p2-task-3-report.md "pre-gate handler" note) does not interfere with
    # this gate-2 regression guard.
    pf, conv = _dyn_engine_conv(monkeypatch)
    conv.history = [{"role": "assistant", "content": "თქვენი შვილი რამდენი წლისაა?"}]
    out = pf._handle_core(conv, "ჩემი 5 წლის ბავშვისთვის რობოტიკის კლუბი?")
    assert out == "ENGINE_ANSWER" and "CAMP" not in out


def test_camp_price_still_uses_camp_interceptor(monkeypatch):
    import dataclasses
    from app import config
    from app.flows import parent_flow as pf
    from app.services import admin_config_service
    from app.models.conversation import Conversation
    monkeypatch.setattr(admin_config_service, "get_active_sections", lambda: [_CAMP])
    monkeypatch.setattr(pf, "settings", dataclasses.replace(
        config.settings, USE_DYNAMIC_PROGRAMS=True, USE_PARENT_LLM_ENGINE=True))
    monkeypatch.setattr(pf, "_maybe_handle_repeat_camp_price", lambda *a, **k: "CAMP_PRICE")
    conv = Conversation(sender_id="t", platform="facebook", segment="PARENT")
    assert pf._handle_core(conv, "ბანაკი რა ღირს?") == "CAMP_PRICE"   # guard False for camp


# Task 3b — close the confirmed PRE-GATE hijack: `_maybe_handle_final_camp_public_policy`
# (parent_flow.py:304, called ~line 1037 — BEFORE the `engine_flag` gate and thus
# structurally outside the Task-3 guard's reach) classified a dynamic-program price
# question ("რობოტიკის კლუბი რა ღირს?") as a CAMP price question once camp
# registration is CLOSED, because `_msg_has_camp_intent` → `_is_camp_price_intent`
# matches generic price words ("ღირს") with no camp-keyword requirement. The fix adds
# a flag-safe `_is_dynamic_program_turn` pass-through as the FIRST statement of the
# handler, so a dynamic-program turn returns None from it and reaches the engine gate.

def test_dynamic_price_not_hijacked_when_registration_closed(monkeypatch):
    pf, conv = _dyn_engine_conv(monkeypatch)
    # Force registration CLOSED (the live state that exposed the hijack).
    # `_maybe_handle_final_camp_public_policy` reads registration via
    # `parent_flow._is_camp_registration_open`, which wraps
    # `admin_config_service.is_camp_registration_open` — patch the same accessor
    # `_dyn_engine_conv` already uses (it pins it OPEN by default).
    monkeypatch.setattr(pf, "_is_camp_registration_open", lambda: False)
    # Seed one prior turn to sidestep the first-turn brand welcome (as the
    # Task-3 age test does).
    conv.history = [{"role": "assistant", "content": "თქვენი შვილი რამდენი წლისაა?"}]
    out = pf._handle_core(conv, "რობოტიკის კლუბი რა ღირს?")
    assert out == "ENGINE_ANSWER"
    assert "CAMP" not in out
    assert "2150" not in out


def test_camp_price_policy_unchanged_when_dynamic_off(monkeypatch):
    """Same registration-CLOSED setup, but the message IS a genuine camp price
    question. `_is_dynamic_program_turn` is False for "ბანაკი" (a hardcoded
    ProgramId — see test_is_dynamic_program_turn), so the Task 3b pass-through
    never fires and `_maybe_handle_final_camp_public_policy` still classifies +
    answers the turn (non-None) — proving the fix does not regress camp policy."""
    import dataclasses
    from app import config
    from app.flows import parent_flow as pf
    from app.models.conversation import Conversation

    monkeypatch.setattr(
        pf, "settings", dataclasses.replace(config.settings, USE_DYNAMIC_PROGRAMS=True),
    )
    monkeypatch.setattr(pf, "_is_camp_registration_open", lambda: False)
    conv = Conversation(sender_id="t2", platform="facebook", segment="PARENT")
    result = pf._maybe_handle_final_camp_public_policy(conv, "ბანაკი რა ღირს?")
    assert result is not None


# Task 4 — `get_program_info` denylist -> allowlist + hardcoded-id refusal (gate 3).

def _make_executor():
    from app.agent.tools.parent_tool_executor import ParentToolExecutor
    from app.models.lead import Lead
    from app.models.conversation import Conversation
    conv = Conversation(sender_id="t", platform="facebook", segment="PARENT")
    return ParentToolExecutor(conversation=conv,
                              lead=Lead(sender_id="t", platform="facebook", segment="PARENT"),
                              sender_id="t", platform="facebook")


def test_get_program_info_allowlist_excludes_internal(monkeypatch):
    from app.services import admin_config_service
    sec = {"id": "robotics_club", "name": "რობოტიკის კლუბი", "type": "kids_program",
           "status": "active", "price_text": "300 ლარი", "description_full": "აღწერა",
           "discovery_questions": ["შიდა?"], "events": [{"reservation_url": "https://secret"}],
           "cta_text": "შიდა"}
    monkeypatch.setattr(admin_config_service, "get_section",
                        lambda pid: sec if pid == "robotics_club" else None)
    out = _make_executor().execute("get_program_info", {"program_id": "robotics_club"})
    assert out["success"] and out["facts"]["price_text"] == "300 ლარი"
    for k in ("discovery_questions", "events", "cta_text"):
        assert k not in out["facts"]


def test_get_program_info_refuses_hardcoded(monkeypatch):
    out = _make_executor().execute("get_program_info", {"program_id": "summer_camp"})
    assert out["success"] is False and out["reason"] == "use_specific_tool"


# Task 5 — END-TO-END: a dynamic-program PRICE question is answered from the
# program's OWN data THROUGH `conversation_service.process_message`, with camp
# registration CLOSED (the live state). This is the exact question Phase 1 could
# NOT answer (the Phase-1 e2e, `test_dynamic_programs.py::
# test_e2e_new_program_answered_end_to_end`, had to use an INFO question because
# the deterministic camp-price interceptor swallowed the PRICE question with the
# camp price before it could reach the engine). It validates the whole Phase-2
# stack composing on the live path: routing (Task 2) → the Task-3b pre-gate
# camp-price bypass (registration CLOSED) → the gate-2 engine bypass (Task 3) →
# the generic `get_program_info` tool → the Task-4 allowlist → a reply built
# from the program's own price.
#
# MOCK SHAPE — copied VERBATIM from the Phase-1 e2e. `_tool_call_response` /
# `_final_text_response` build objects shaped EXACTLY like the OpenAI response
# `parent_llm_engine` reads: `response.choices[0].message` with `.content`
# (final text) and `.tool_calls[i]` carrying `.id` + `.function.name` +
# `.function.arguments`. The parent engine's response helpers consume that shape
# via `getattr`, so `types.SimpleNamespace` satisfies them.
#
# TWO-TURN, on purpose — mirrors the Phase-1 e2e: the brand two-option
# static-welcome menu owns the FIRST turn, so the engine is never consulted on
# turn 1. A message NAMING the program on the next turn is the realistic path
# that routes into the engine.
#
# FROZEN-SETTINGS PATTERN — both flags enabled on EVERY module that reads them
# on this path (`conversation_service` routing, `parent_flow` engine gate +
# registration accessor, `parent_llm_engine` tools + prompt suffix, `app.config`
# singleton) via `dataclasses.replace(...)` + a module monkeypatch, the same
# mechanism the autouse conftest fixture uses.


def _tool_call_response(name, arguments):
    """OpenAI-shaped response whose assistant message issues ONE tool call."""
    from types import SimpleNamespace

    tool_call = SimpleNamespace(
        id="call_1",
        function=SimpleNamespace(name=name, arguments=arguments),
    )
    message = SimpleNamespace(content=None, tool_calls=[tool_call])
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def _final_text_response(text):
    """OpenAI-shaped response whose assistant message is a plain final answer."""
    from types import SimpleNamespace

    message = SimpleNamespace(content=text, tool_calls=None)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def test_e2e_dynamic_program_price_answered_end_to_end(monkeypatch):
    import dataclasses
    from app.services import conversation_service as cs, admin_config_service
    from app.agent.llm import parent_llm_engine
    from app.flows import parent_flow
    from app import config as app_config

    synthetic = {
        "id": "robotics_club", "name": "რობოტიკის კლუბი", "type": "kids_program",
        "status": "active", "price_text": "300 ლარი",
        "description_full": "რობოტების აწყობა და პროგრამირება.",
        "registration_status": "closed",
        "hashtags": ["რობოტიკა", "robotics"],
    }

    # Active sections drive routing (`_match_active_program_segment`) + the prompt
    # suffix; `get_section` is what the guarded executor (`_get_program_info`)
    # calls, so recording its calls proves the generic tool actually RAN.
    monkeypatch.setattr(admin_config_service, "get_active_sections", lambda: [synthetic])
    fetched_ids: list[str] = []

    def _get_section(pid):
        fetched_ids.append(pid)
        return synthetic if pid == "robotics_club" else None

    monkeypatch.setattr(admin_config_service, "get_section", _get_section)

    # REGISTRATION CLOSED is the point. Force the SAME accessor the pre-gate camp
    # handler reads (`parent_flow._is_camp_registration_open`, which wraps
    # `admin_config_service.is_camp_registration_open`) to False, so the test
    # proves the Task-3b bypass on the real, live-state path — a generic price
    # word („რა ღირს") would otherwise be misclassified as a CAMP price question
    # by `_maybe_handle_final_camp_public_policy` once registration is CLOSED.
    monkeypatch.setattr(parent_flow, "_is_camp_registration_open", lambda: False)
    monkeypatch.setattr(admin_config_service, "is_camp_registration_open", lambda: False)

    # Enable BOTH flags on every module that reads them on this path.
    for mod in (cs, parent_llm_engine, parent_flow, app_config):
        swapped = dataclasses.replace(
            mod.settings, USE_DYNAMIC_PROGRAMS=True, USE_PARENT_LLM_ENGINE=True,
        )
        monkeypatch.setattr(mod, "settings", swapped)

    # Sentinel: if the deterministic camp-price interceptor answers this turn its
    # marker (never a real reply) surfaces in the output. Asserting the marker is
    # ABSENT proves the camp-price interceptor did NOT answer the
    # dynamic-program price question — the engine did.
    _CAMP_PRICE_SENTINEL = "CAMP_PRICE_INTERCEPTOR_FIRED"
    monkeypatch.setattr(
        parent_flow, "_maybe_handle_repeat_camp_price",
        lambda *a, **k: _CAMP_PRICE_SENTINEL,
    )

    captured = {"tool_names": None, "calls": 0}

    def fake_chat_with_tools(*, messages, tools, **kw):
        import json

        captured["calls"] += 1
        captured["tool_names"] = {t["function"]["name"] for t in tools}
        # First LLM round → ask for get_program_info; after the tool result is
        # appended (a `role == "tool"` message) → answer from it.
        tool_messages = [m for m in messages if m.get("role") == "tool"]
        if not tool_messages:
            return _tool_call_response(
                "get_program_info", '{"program_id": "robotics_club"}',
            )
        # Derive the reply FROM the executor's actual tool result (the real
        # `_get_program_info` Task-3 output, serialized into this `role=="tool"`
        # message's `content`) — NOT a canned string. A regression that
        # drops/empties `price_text`, or returns `success: False`, fails HERE
        # with a clear message.
        tool_result = json.loads(tool_messages[-1]["content"])
        assert tool_result.get("success") is True, (
            f"get_program_info tool result must be success:true, got {tool_result!r}"
        )
        facts = tool_result.get("facts") or {}
        assert facts.get("price_text") == synthetic["price_text"], (
            "get_program_info facts must carry the program's own "
            f"price_text={synthetic['price_text']!r}, got {facts.get('price_text')!r}"
        )
        return _final_text_response(f"რობოტიკის კლუბი ღირს {facts['price_text']}.")

    monkeypatch.setattr(
        "app.services.openai_service.chat_with_tools", fake_chat_with_tools,
    )

    # Turn 1 — the brand two-option menu owns the first turn; the engine is not
    # consulted yet (identical to the camp opening).
    menu = cs.process_message(
        sender_id="u_price_p2t5", message_text="გამარჯობა",
        platform="facebook", page_id="p1",
    )
    assert menu, "the brand welcome must produce a reply"
    assert captured["calls"] == 0, "the LLM engine must NOT be consulted on turn 1"

    # Turn 2 — the dynamic-program PRICE question, with camp registration CLOSED.
    #   Task 2 routing → PARENT (overrides the incidental „კლუბ"→ADULT stem)
    #   Task 3b pre-gate → the camp-price policy handler bypasses this turn
    #   Task 3 gate-2   → the engine bypass fires before every camp interceptor
    #   Task 4 tools    → the engine offers list_programs + get_program_info
    #   Task 3 executor → get_program_info fetches the section (get_section call)
    reply = cs.process_message(
        sender_id="u_price_p2t5",
        message_text="რობოტიკის კლუბი რა ღირს?",
        platform="facebook", page_id="p1",
    )

    # The price question REACHED the LLM engine — no deterministic camp
    # interceptor swallowed it, even with registration CLOSED.
    assert captured["calls"] >= 1, "the price question must reach the LLM engine"
    # The GENERIC program tool was actually offered to the LLM (Task 4).
    assert {"list_programs", "get_program_info"} <= captured["tool_names"]
    # The generic tool actually RAN — the guarded executor fetched the program
    # (Task 3), not merely offered the schema.
    assert "robotics_club" in fetched_ids, "get_program_info must fetch the section"
    # The reply carries the PROGRAM's OWN price (from the executor tool-result).
    assert "300" in reply, "reply must answer from the program's own price"
    # It must NOT fall back to the camp price, and the deterministic camp-price
    # interceptor must NOT have answered this turn.
    assert "2150" not in reply, "must not fall back to the camp price"
    assert _CAMP_PRICE_SENTINEL not in reply, (
        "the deterministic camp-price interceptor must not answer a "
        "dynamic-program price question"
    )
