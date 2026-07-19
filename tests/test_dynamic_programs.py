def test_dynamic_programs_flag_defaults_false():
    from app.config import Settings
    assert Settings().USE_DYNAMIC_PROGRAMS is False


def test_dynamic_programs_flag_parses_env(monkeypatch):
    monkeypatch.setenv("USE_DYNAMIC_PROGRAMS", "true")
    from app.config import Settings
    assert Settings.from_env().USE_DYNAMIC_PROGRAMS is True


def test_dynamic_program_tools_wellformed_and_not_in_base():
    from app.agent.tools import parent_tools as pt
    names = {t["function"]["name"] for t in pt.DYNAMIC_PROGRAM_TOOLS}
    assert names == {"list_programs", "get_program_info"}
    assert {"list_programs", "get_program_info"} <= pt.ALLOWED_TOOL_NAMES
    assert "get_program_info" not in {t["function"]["name"] for t in pt.PARENT_TOOLS}
    gpi = next(t for t in pt.DYNAMIC_PROGRAM_TOOLS if t["function"]["name"] == "get_program_info")
    assert gpi["function"]["parameters"]["required"] == ["program_id"]


# Task 3 — guarded executor handlers (_list_programs / _get_program_info).

def _fake_sections():
    return [
        {"id": "robotics_club", "name": "რობოტიკის კლუბი", "type": "kids_program",
         "status": "active", "price_text": "300 ლარი", "age_min": 8, "age_max": 14,
         "description_full": "ბავშვები ისწავლიან რობოტების აწყობას და პროგრამირებას.",
         "registration_url": "https://x/y", "registration_status": "closed",
         "auto_dm_template_id": "robo_dm", "hashtags": ["რობოტიკა", "robotics"]},
        {"id": "old", "name": "ძველი", "type": "kids_program", "status": "hidden"},
    ]


def _make_executor():
    from app.agent.tools.parent_tool_executor import ParentToolExecutor
    from app.models.lead import Lead
    from app.models.conversation import Conversation
    conv = Conversation(sender_id="t", platform="facebook")
    # ParentToolExecutor is a dataclass: conversation, lead, sender_id, platform, user_message=""
    # Lead requires sender_id/platform/segment (no bare Lead()); minimal
    # valid values only — the asserted behavior does not depend on them.
    lead = Lead(sender_id="t", platform="facebook", segment="PARENT")
    return ParentToolExecutor(conversation=conv, lead=lead, sender_id="t", platform="facebook")


def test_list_programs_active_only(monkeypatch):
    from app.services import admin_config_service
    monkeypatch.setattr(admin_config_service, "get_active_sections",
                        lambda: [s for s in _fake_sections() if s["status"] == "active"])
    out = _make_executor().execute("list_programs", {})
    assert out["success"] and {p["program_id"] for p in out["programs"]} == {"robotics_club"}


def test_get_program_info_guards_and_facts(monkeypatch):
    from app.services import admin_config_service
    monkeypatch.setattr(admin_config_service, "get_section",
                        lambda pid: next((s for s in _fake_sections() if s["id"] == pid), None))
    out = _make_executor().execute("get_program_info", {"program_id": "robotics_club", "topic": "price"})
    assert out["success"] is True
    assert out["facts"]["price_text"] == "300 ლარი"
    assert "პროგრამირებას" in out["facts"]["description_full"]
    # registration_status is closed → the URL must NOT leak
    assert "registration_url" not in out["facts"]
    # operator-internal keys never exposed
    assert "auto_dm_template_id" not in out["facts"] and "hashtags" not in out["facts"]


def test_get_program_info_unknown_and_inactive(monkeypatch):
    from app.services import admin_config_service
    monkeypatch.setattr(admin_config_service, "get_section",
                        lambda pid: next((s for s in _fake_sections() if s["id"] == pid), None))
    ex = _make_executor()
    assert ex.execute("get_program_info", {"program_id": "nope"})["reason"] == "unknown_program"
    assert ex.execute("get_program_info", {"program_id": "old"})["reason"] == "program_not_active"


def test_get_program_info_surfaces_registration_url_when_open(monkeypatch):
    # Positive counterpart to test_get_program_info_guards_and_facts: when
    # registration_status is "open" the URL must be PRESENT in facts, not
    # dropped. Self-contained section dict — does not touch _fake_sections
    # so the closed-status guard test above is unaffected.
    open_section = {
        "id": "chess_club", "name": "ჭადრაკის კლუბი", "type": "kids_program",
        "status": "active", "price_text": "200 ლარი",
        "registration_url": "https://x/open-reg", "registration_status": "open",
    }
    from app.services import admin_config_service
    monkeypatch.setattr(admin_config_service, "get_section",
                        lambda pid: open_section if pid == "chess_club" else None)
    out = _make_executor().execute("get_program_info", {"program_id": "chess_club"})
    assert out["success"] is True
    assert out["registration_open"] is True
    assert out["facts"]["registration_url"] == "https://x/open-reg"


# Task 4 — wire the generic program tools into the LLM loop (flag-gated).

def test_build_active_tools_respects_flag():
    from app.agent.llm.parent_llm_engine import build_active_tools
    from app.agent.tools.parent_tools import PARENT_TOOLS, DYNAMIC_PROGRAM_TOOLS
    off = [t["function"]["name"] for t in build_active_tools(False)]
    assert off == [t["function"]["name"] for t in PARENT_TOOLS]
    on = {t["function"]["name"] for t in build_active_tools(True)}
    assert {"list_programs", "get_program_info"} <= on
    assert len(build_active_tools(True)) == len(PARENT_TOOLS) + len(DYNAMIC_PROGRAM_TOOLS)


# Task 4 review fix — dedicated coverage for _dynamic_programs_prompt_suffix().
# `app.config.Settings` is a FROZEN dataclass, so a plain
# `monkeypatch.setattr(settings_instance, "USE_DYNAMIC_PROGRAMS", ...)` raises
# `FrozenInstanceError`. Both tests instead replace the MODULE-level `settings`
# binding that `parent_llm_engine` reads (`dataclasses.replace(...)` + module
# monkeypatch) — the same mechanism `tests/conftest.py`'s autouse
# `_force_parent_llm_engine_off` fixture already uses for this module.

def test_dynamic_programs_prompt_suffix_empty_when_flag_off(monkeypatch):
    import dataclasses
    from app.agent.llm import parent_llm_engine

    off_settings = dataclasses.replace(parent_llm_engine.settings, USE_DYNAMIC_PROGRAMS=False)
    monkeypatch.setattr(parent_llm_engine, "settings", off_settings)

    assert parent_llm_engine._dynamic_programs_prompt_suffix() == ""


def test_dynamic_programs_prompt_suffix_lists_non_camp_when_on(monkeypatch):
    import dataclasses
    from app.agent.llm import parent_llm_engine
    from app.services import admin_config_service

    on_settings = dataclasses.replace(parent_llm_engine.settings, USE_DYNAMIC_PROGRAMS=True)
    monkeypatch.setattr(parent_llm_engine, "settings", on_settings)
    monkeypatch.setattr(
        admin_config_service, "get_active_sections",
        lambda: [
            {"id": "summer_camp", "name": "საზაფხულო ბანაკი", "status": "active"},
            {"id": "robotics_club", "name": "რობოტიკის კლუბი", "status": "active"},
        ],
    )

    suffix = parent_llm_engine._dynamic_programs_prompt_suffix()

    assert suffix != ""
    assert "robotics_club" in suffix or "რობოტიკის კლუბი" in suffix
    assert "summer_camp" not in suffix
    assert "საზაფხულო ბანაკი" not in suffix
    assert "list_programs" in suffix
    assert "get_program_info" in suffix


# Task 5 — data-driven segment routing so a new admin program REACHES the
# parent LLM engine (the BLOCKER fix). `_match_active_program_segment` consults
# the ACTIVE admin sections at the fresh-classification line so a message naming
# a program routes by that program's `type`, overriding incidental keyword
# collisions (e.g. "რობოტიკის კლუბი" would otherwise match the adult stem
# "კლუბ" → ADULT).
#
# FROZEN-SETTINGS PATTERN: `app.config.Settings` is a frozen dataclass, so
# `monkeypatch.setattr(cs.settings, "USE_DYNAMIC_PROGRAMS", ...)` raises
# `FrozenInstanceError`. We instead swap the MODULE-level `conversation_service`
# `settings` binding (the one the routing helper reads) via
# `dataclasses.replace(...)` — the same mechanism `tests/conftest.py`'s autouse
# fixture uses. `conversation_service.settings` is a SEPARATE reference from
# `parent_flow.settings`, so it must be swapped specifically here.

def test_match_active_program_segment(monkeypatch):
    import dataclasses
    from app.services import conversation_service as cs, admin_config_service

    monkeypatch.setattr(admin_config_service, "get_active_sections", lambda: [
        {"id": "robotics_club", "name": "რობოტიკის კლუბი", "type": "kids_program",
         "status": "active", "hashtags": ["რობოტიკა", "robotics"]},
    ])

    # flag off → None (no behavior change; flag-off routing stays byte-identical)
    off = dataclasses.replace(cs.settings, USE_DYNAMIC_PROGRAMS=False)
    monkeypatch.setattr(cs, "settings", off)
    assert cs._match_active_program_segment("რობოტიკა რა ღირს?") is None

    # flag on → matched by hashtag/name → PARENT (overrides incidental "კლუბ"→ADULT)
    on = dataclasses.replace(cs.settings, USE_DYNAMIC_PROGRAMS=True)
    monkeypatch.setattr(cs, "settings", on)
    assert cs._match_active_program_segment("რობოტიკის კლუბი მაინტერესებს") == "PARENT"
    assert cs._match_active_program_segment("ამინდი როგორია") is None


def test_existing_programs_unchanged_routing(monkeypatch):
    import dataclasses
    from app.services import conversation_service as cs, admin_config_service

    monkeypatch.setattr(admin_config_service, "get_active_sections", lambda: [
        {"id": "summer_camp", "name": "საზაფხულო ბანაკი", "type": "camp",
         "status": "active", "hashtags": ["ბანაკი", "camp"]},
        {"id": "adult_events", "name": "ზრდასრულთა ღონისძიება", "type": "adult_events",
         "status": "active", "hashtags": ["ღონისძიება"]},
    ])
    on = dataclasses.replace(cs.settings, USE_DYNAMIC_PROGRAMS=True)
    monkeypatch.setattr(cs, "settings", on)
    # v2: the matcher no longer owns the generic-named programs; the composed
    # routing (matcher or _classify_segment) still yields the same segment.
    assert (cs._match_active_program_segment("ბანაკი მაინტერესებს")
            or cs._classify_segment("ბანაკი მაინტერესებს")) == "PARENT"
    assert (cs._match_active_program_segment("ღონისძიება როდისაა")
            or cs._classify_segment("ღონისძიება როდისაა")) == "ADULT"


# Task 6 — END-TO-END acceptance: a NEW admin program is answered THROUGH
# `conversation_service.process_message` (routing → generic tool → reply), with
# the LLM mocked. This is the real proof that Tasks 1-5 compose on the live path.
#
# MOCK SHAPE — the `_tool_call_response` / `_final_text_response` helpers build
# minimal objects shaped EXACTLY like the OpenAI response `parent_llm_engine`
# reads: `response.choices[0].message` with `.content` (final text) and
# `.tool_calls[i]` carrying `.id` + `.function.name` + `.function.arguments`.
# Copied from the `chat_with_tools` stub `_mk_response` in
# `tests/test_adult_llm_engine.py` — the parent engine's response helpers
# (`_first_choice` / `_choice_message` / `_tool_calls` / `_message_content` /
# `_tool_name` / `_tool_args` / `_tool_call_id`) consume that same shape via
# `getattr`, so `types.SimpleNamespace` satisfies them.
#
# TWO-TURN, on purpose: the brand opens every PARENT conversation with the
# two-option static-welcome menu, which owns the FIRST turn regardless of the
# message (identical behaviour for the camp), so the engine is never consulted on
# turn 1. A message NAMING the new program on the next turn is the realistic path
# a user takes and is what routes into the engine. See the Task-6 report for the
# separate, genuine Phase-1 gap this surfaced: a program PRICE question
# („რობოტიკის კლუბი რა ღირს?") is caught by the deterministic camp-price
# interceptor and answered with the CAMP price before it can reach the engine —
# so this e2e uses an INFO question, which does reach the generic tool.
#
# FROZEN-SETTINGS PATTERN (see the Task-5 tests above): `app.config.Settings` is
# a frozen dataclass, so the module-level `settings` binding each module reads is
# swapped via `dataclasses.replace(...)`. Both flags must be enabled on EVERY
# module that reads them on this path: `conversation_service` (routing),
# `parent_flow` (the `USE_PARENT_LLM_ENGINE` engine gate) and `parent_llm_engine`
# (`build_active_tools` + the prompt suffix). `app.config` is swapped too so any
# direct singleton read agrees.


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


def test_e2e_new_program_answered_end_to_end(monkeypatch):
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

    # Enable BOTH flags on every module that reads them on this path.
    for mod in (cs, parent_llm_engine, parent_flow, app_config):
        swapped = dataclasses.replace(
            mod.settings, USE_DYNAMIC_PROGRAMS=True, USE_PARENT_LLM_ENGINE=True,
        )
        monkeypatch.setattr(mod, "settings", swapped)

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
        # `_get_program_info` Task-3 output, serialized via `serialize_result`
        # into this `role=="tool"` message's `content`) — NOT a canned
        # string. A regression that drops/empties `price_text`, or returns
        # `success: False`, fails HERE with a clear message, instead of the
        # test silently proving only that the tool-loop plumbing ran.
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
        sender_id="u1", message_text="გამარჯობა", platform="facebook", page_id="p1",
    )
    assert menu, "the brand welcome must produce a reply"
    assert captured["calls"] == 0, "the LLM engine must NOT be consulted on turn 1"

    # Turn 2 — a message naming the NEW admin program flows all the way through:
    #   Task 5 routing → PARENT (overrides the incidental „კლუბ"→ADULT stem)
    #   Task 4 tools   → the engine offers list_programs + get_program_info
    #   Task 3 executor→ get_program_info fetches the section (get_section call)
    #   Task 2/1       → schemas + flag gate everything above
    reply = cs.process_message(
        sender_id="u1",
        message_text="რობოტიკის კლუბის შესახებ მინდა ვიცოდე",
        platform="facebook", page_id="p1",
    )

    # The message REACHED the LLM engine (routing did not divert it, no
    # deterministic interceptor swallowed it).
    assert captured["calls"] >= 1, "the program message must reach the LLM engine"
    # The GENERIC program tool was actually offered to the LLM (Task 4).
    assert {"list_programs", "get_program_info"} <= captured["tool_names"]
    # The generic tool actually RAN — the guarded executor fetched the program
    # (Task 3), not merely offered the schema.
    assert "robotics_club" in fetched_ids, "get_program_info must fetch the section"
    # The reply carries the PROGRAM's own fact — not the camp default.
    assert "300" in reply, "reply must answer from the program's data"
    assert "2150" not in reply, "must not fall back to the camp price"
