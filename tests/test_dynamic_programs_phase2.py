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
