"""One programme reader for the booking — operator goals G3, G6, G7 (2026-10-05).

Measured on the deployed b9f1e64:

* A consultation nobody had tagged was judged by the ENDED summer camp's gate
  and refused as ``camp_registration_closed`` (31 of 31 live refusals,
  2026-09-20…29). The booking resolver read the current message and the tag,
  and then fell to "" — which meant the summer camp.
* With two programmes on sale it never asked; it refused.
* The programme the AGENT had been talking about was invisible to it.
* „საზაფხულო ბანაკი" — the ended camp's own name — was read as Paris.
* A held slot with every detail known booked on whatever came next, „არა"
  included (W1).

The booking now reads ``parent_llm_engine.resolve_programme``: the message, the
tag, the chat (the parent's turns and any agent reply that names exactly one
programme on sale), then the panel — one programme on sale owns the turn, two
or more and the agent is told to ask. Nothing here knows a programme by id: the
panels below are synthetic and every rule reads them.

The conversation tests run through ``conversation_service.process_message``
with the production flags; only the LLM's HTTP transport is scripted.
Calendar, Sheets, mail and Meta are in-memory fakes. No network.
"""
from __future__ import annotations

import dataclasses
import re
import socket
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml
from gspread.exceptions import WorksheetNotFound

import app.config as config_module
from app.agent.llm import parent_llm_engine
from app.agent.tools import parent_tool_executor as pte
from app.flows import parent_flow
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.services import admin_config_service as acs
from app.services import anthropic_service, calendar_service, sheets_service
from app.services import conversation_service as cs
from app.services import messenger_service, notification_service

# ── panels (synthetic) ──────────────────────────────────────────────────────
_CAMP = {
    "id": "summer_camp", "name": "საზაფხულო ბანაკი", "type": "camp",
    "status": "active", "registration_status": "open",
    "hashtags": ["bavshvebi", "camp"],
    "age_min": 9, "age_max": 17, "price_text": "2150", "price_gel": 2150,
    "manager_contact": "500 00 00 01",
}
_SCHOOL = {
    "id": "sunday_school", "name": "საკვირაო სკოლა", "type": "kids_program",
    "status": "active", "registration_status": "open",
    "hashtags": ["საკვირაოსკოლა", "sunday_school"],
    "age_min": 7, "age_max": 17, "price_text": "595 ლარი",
    "manager_contact": "500 00 00 02",
}
_ADULT = {
    "id": "adult_events", "name": "ზრდასრულთა ღონისძიებები", "type": "adult_events",
    "status": "hidden", "hashtags": ["ღონისძიება", "event"], "age_min": 13, "events": [],
}
_PARIS = {
    "id": "paris_camp", "name": "პარიზის ბანაკი", "type": "kids_program",
    "status": "active", "registration_status": "open",
    "hashtags": ["პარიზი", "paris"], "age_min": 9, "age_max": 17,
    "manager_contact": "500 00 00 03",
}


def _sections(panel: str) -> list[dict]:
    camp, school, adult, paris = dict(_CAMP), dict(_SCHOOL), dict(_ADULT), dict(_PARIS)
    if panel == "CAMP_ONLY":   # the camp running, nothing else on sale
        school.update(status="coming_soon", registration_status="")
        return [camp, school, adult]
    camp.update(status="ended", registration_status="closed")
    if panel == "SS":          # today: the camp over, Sunday School alone
        return [camp, school, adult]
    if panel == "SS_BLANK":    # Sunday School saved before the status field existed
        school.pop("registration_status")
        return [camp, school, adult]
    if panel == "SS_PARIS":    # Monday: Sunday School and Paris on sale
        return [camp, school, adult, paris]
    raise KeyError(panel)


_PROD = dict(
    USE_ADULT_LLM_ENGINE=True, USE_PARENT_LLM_ENGINE=True, USE_LLM_TURN_ANALYZER=True,
    USE_DYNAMIC_PROGRAMS=True, USE_DYNAMIC_WELCOME=True, USE_DYNAMIC_CONTACT_CAPTURE=True,
    USE_PER_PRODUCT_BOOKING=True, USE_PROGRAM_ISOLATION=True, USE_PROGRAM_AUDIENCE=True,
    USE_PROGRAM_FOLLOWUP=True, USE_SECTION_STATUS_GATE=True, USE_CAMP_OFF_GATE=True,
    USE_FUZZY_PROGRAM_MATCH=True, USE_CONSULTATION_PROGRAM_NAME=True,
    USE_RESERVED_PROGRAMS_DYNAMIC=True, USE_SKILLS=True, USE_SAFETY_SPINE=True,
    USE_CONVERSATION_PLANNER=False, USE_LLM_COMPOSER=False, USE_SLIM_PROMPTS=False,
    CONVERSATION_PLANNER_AUTHORITATIVE=False, CONVERSATION_TRACE_DEBUG=False,
    LLM_PROVIDER="anthropic", ANTHROPIC_AUTH_TOKEN="sk-ant-test-placeholder",
    ANTHROPIC_MODEL="claude-sonnet-4-6", ANTHROPIC_FALLBACK_TO_OPENAI=False,
    REDIS_ENABLED=False, REDIS_URL="", ALLOW_LIVE_WHATSAPP=False,
    FOLLOWUP_TEST_MODE=False, FOLLOWUP_FIRST_DELAY_SECONDS=0, AGENT_ENABLED=True,
    MANAGER_EMAIL="manager@example.invalid",
)

_TB = timezone(timedelta(hours=4))


def _slot_day():
    d = datetime.now(_TB).date() + timedelta(days=3)
    while d.weekday() == 6:  # Sunday is closed for bookings
        d += timedelta(days=1)
    return d


_DAY = _slot_day()
_ISO12 = f"{_DAY.isoformat()}T12:00:00+04:00"
_PHONE = "591234567"
_ASK_CONTACT = "მომწერეთ თქვენი სახელი და საკონტაქტო ნომერი."
_SS_OFFER = "საკვირაო სკოლის ფასი 595 ლარია. გსურთ კონსულტაციაზე ჩაწერა? რამდენი წლისაა ბავშვი?"
_BOTH = "გვაქვს საკვირაო სკოლა და პარიზის ბანაკი. რომელი გაინტერესებთ?"
_CHECK12 = ("tool", "check_consultation_slot", {"datetime_iso": _ISO12})
_FREE12 = ("say", "12:00 თავისუფალია. " + _ASK_CONTACT)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    attempts: list[str] = []
    loopback = {"127.0.0.1", "::1", "localhost"}

    def _host(addr):
        try:
            return str(addr[0])
        except Exception:  # noqa: BLE001
            return str(addr)

    def _guard(host):
        if host not in loopback:
            attempts.append(host)
            raise ConnectionRefusedError(f"network blocked in test: {host}")

    orig_connect, orig_gai = socket.socket.connect, socket.getaddrinfo
    monkeypatch.setattr(socket.socket, "connect",
                        lambda self, a: (_guard(_host(a)), orig_connect(self, a))[1])
    monkeypatch.setattr(socket, "getaddrinfo",
                        lambda h, *a, **k: (_guard(str(h)), orig_gai(h, *a, **k))[1])
    yield
    assert attempts == [], f"outbound network attempted: {attempts}"


class _World:
    def __init__(self):
        self.script: list = []
        self.mails: list[dict] = []
        self.rows: list[dict] = []
        self.calendar: list[str] = []
        self.tools: list[dict] = []
        self.sender = ""
        self.n = 0

    def post(self, *, messages, max_tokens, temperature, tools=None, tool_choice=None):
        names = [((t or {}).get("function") or {}).get("name") for t in (tools or [])]
        if "book_consultation" in names:
            action = self.script.pop(0) if self.script else ("say", "გასაგებია.")
        elif names:
            action = ("say", "გასაგებია.")
        else:
            blob = " ".join(str(m.get("content") or "") for m in messages)
            action = ("say", "{}" if "JSON" in blob else "მშობელს აინტერესებს კონსულტაცია.")
        if action[0] == "tool":
            self.n += 1
            return {"content": [{"type": "tool_use", "id": f"toolu_a{self.n}",
                                 "name": action[1], "input": action[2]}],
                    "stop_reason": "tool_use", "model": "claude-sonnet-4-6"}
        return {"content": [{"type": "text", "text": action[1]}],
                "stop_reason": "end_turn", "model": "claude-sonnet-4-6"}

    def say(self, text: str, *script) -> str:
        self.script = list(script)
        return cs.process_message(sender_id=self.sender, message_text=text,
                                  platform="messenger", page_id="") or ""

    @property
    def conversation(self) -> Conversation:
        return cs.conversations.get(cs._conversation_session_key(self.sender, "messenger", ""))

    @property
    def lead(self) -> Lead:
        return self.conversation.lead


class _X:
    def __init__(self, fn):
        self.fn = fn

    def execute(self):
        return self.fn()


class _Calendar:
    def __init__(self, world):
        self.world = world

    def events(self):
        world = self.world

        class _Events:
            def insert(self, calendarId=None, body=None, **k):
                def run():
                    world.calendar.append((body or {}).get("start", {}).get("dateTime"))
                    return {"id": f"evt{len(world.calendar)}"}
                return _X(run)

            def delete(self, calendarId=None, eventId=None, **k):
                return _X(lambda: {})

            def list(self, **k):
                return _X(lambda: {"items": []})
        return _Events()

    def freebusy(self):
        class _FB:
            def query(self, body=None, **k):
                ids = [i.get("id") for i in (body or {}).get("items", [])]
                return _X(lambda: {"calendars": {i: {"busy": []} for i in ids}})
        return _FB()


_RANGE_RE = re.compile(r"([A-Z]+)(\d+)")


class _Sheet:
    def __init__(self, title, world):
        self.title, self.world, self.rows, self.col_count = title, world, [], 26

    def _cell(self, r, c, v):
        while len(self.rows) < r:
            self.rows.append([])
        row = self.rows[r - 1]
        while len(row) < c:
            row.append("")
        row[c - 1] = v

    def _log(self, r):
        if r > 1 and self.rows:
            head = self.rows[0]
            self.world.rows.append({"tab": self.title, **{
                (head[i] if i < len(head) else f"c{i}"): v
                for i, v in enumerate(self.rows[r - 1])}})

    def row_values(self, i):
        return list(self.rows[i - 1]) if i <= len(self.rows) else []

    def col_values(self, c):
        return [(r[c - 1] if c - 1 < len(r) else "") for r in self.rows]

    def get_all_values(self):
        return [list(r) for r in self.rows]

    def get_all_records(self, **k):
        if not self.rows:
            return []
        h = self.rows[0]
        return [dict(zip(h, list(r) + [""] * (len(h) - len(r)))) for r in self.rows[1:]]

    def update(self, *args, **kw):
        rng = kw.get("range_name", args[0] if args else "A1")
        values = kw.get("values", args[1] if len(args) > 1 else [[]])
        m = _RANGE_RE.match(rng)
        letters, r0 = m.group(1), int(m.group(2))
        c0 = 0
        for ch in letters:
            c0 = c0 * 26 + (ord(ch) - 64)
        for dr, rowvals in enumerate(values):
            for dc, v in enumerate(rowvals):
                self._cell(r0 + dr, c0 + dc, v)
            self._log(r0 + dr)
        return {}

    def update_cell(self, r, c, v):
        self._cell(r, c, v)
        return {}

    def append_row(self, row, **kw):
        self.rows.append(list(row))
        self._log(len(self.rows))
        return {}

    def resize(self, rows=None, cols=None):
        return None


class _Book:
    def __init__(self, world):
        self.world, self.tabs = world, {}

    def worksheet(self, title):
        if title not in self.tabs:
            raise WorksheetNotFound(title)
        return self.tabs[title]

    def add_worksheet(self, title, rows=1000, cols=26, **k):
        self.tabs[title] = _Sheet(title, self.world)
        return self.tabs[title]


@pytest.fixture
def world(monkeypatch, tmp_path, request):
    w = _World()
    w.sender = "r4a-" + re.sub(r"[^a-z0-9]+", "-", request.node.name.lower())[:60]

    live = dataclasses.replace(config_module.settings, **_PROD)
    for mod in list(sys.modules.values()):
        name = getattr(mod, "__name__", "") or ""
        if (name == "app.config" or name.startswith("app.")) and isinstance(
            getattr(mod, "settings", None), config_module.Settings,
        ):
            monkeypatch.setattr(mod, "settings", live)

    monkeypatch.setattr(anthropic_service, "_post", w.post)
    monkeypatch.setattr(calendar_service, "_calendar_service", lambda: _Calendar(w))
    book = _Book(w)
    monkeypatch.setattr(sheets_service, "_sheets_client",
                        lambda: type("GC", (), {"open_by_key": lambda self, k: book})())
    monkeypatch.setattr(notification_service, "_send_email", lambda *a, **k: (w.mails.append({
        "subject": k.get("subject", a[0] if a else ""),
        "body": k.get("body", a[1] if len(a) > 1 else "")}), True)[1])
    monkeypatch.setattr(notification_service, "_send_manager_whatsapp",
                        lambda *a, **k: False, raising=False)
    monkeypatch.setattr(messenger_service, "send_message", lambda *a, **k: True)
    monkeypatch.setattr(messenger_service, "send_private_reply", lambda *a, **k: True,
                        raising=False)
    monkeypatch.setattr(messenger_service, "get_user_profile", lambda *a, **k: {})
    monkeypatch.setattr(pte, "manager_notified_for_conversation", {})
    monkeypatch.setattr(pte, "book_consultation_success_for_conversation", {})
    monkeypatch.setattr(parent_flow, "_sunday_school_notified_senders", set())

    original_execute = pte.ParentToolExecutor.execute

    def _execute(self, name, args):
        result = original_execute(self, name, args)
        w.tools.append({"tool": name, **{k: result.get(k) for k in
                                          ("success", "reason", "available",
                                           "candidate_programs")}})
        return result
    monkeypatch.setattr(pte.ParentToolExecutor, "execute", _execute)

    def _panel(name):
        path = tmp_path / f"sections_{name}.yaml"
        path.write_text(yaml.safe_dump({"sections": _sections(name)}, allow_unicode=True,
                                       sort_keys=False), encoding="utf-8")
        monkeypatch.setattr(acs, "SECTIONS_PATH", Path(path))
    w.panel = _panel
    yield w
    cs.conversations.pop(cs._conversation_session_key(w.sender, "messenger", ""), None)


def _booked(w, iso):
    return iso in w.calendar and any(
        r.get("tab") == "Leads" and r.get("Phone") == _PHONE for r in w.rows)


def _program_on_the_booking(w):
    return [r.get("Program") for r in w.rows if r.get("tab") == "Leads"]


def _refused_by_the_camp(w):
    return [t for t in w.tools if t.get("reason") == "camp_registration_closed"]


def _conversation(turns, lead=None) -> Conversation:
    conv = Conversation(sender_id="r4a-unit", platform="messenger")
    conv.history = [{"role": r, "content": t} for r, t in turns]
    conv.lead = lead or Lead(sender_id="r4a-unit", platform="messenger", segment="PARENT")
    return conv


def _executor(conv: Conversation, message: str) -> pte.ParentToolExecutor:
    return pte.ParentToolExecutor(conversation=conv, lead=conv.lead,
                                  sender_id=conv.sender_id, platform="messenger",
                                  user_message=message)


# ═══ the booking is the programme's, not the ended camp's ═════════════════

def test_the_only_programme_on_sale_books_without_being_named(world):
    """BUG 1 as it ran live: nobody typed „საკვირაო სკოლა", nothing tagged the
    lead, and the ended camp's gate refused the booking."""
    world.panel("SS")
    world.say("ფასი რა არის?", ("say", _SS_OFFER))
    world.say("10 წლისაა", ("say", "რომელი დღე და დრო გირჩევნიათ?"))
    world.say("კი, 12 საათი მაწყობს", _CHECK12, _FREE12)
    assert not _refused_by_the_camp(world), world.tools
    world.say(f"ნინო {_PHONE}")
    assert _booked(world, _ISO12), (world.calendar, world.rows, world.tools)
    assert _program_on_the_booking(world) == ["საკვირაო სკოლა"]


def test_a_programme_saved_without_a_registration_status_is_not_closed_by_the_camp(world):
    """A programme whose status the operator never set used to inherit the ended
    camp's gate. The operator's rule: a closed programme never gates another."""
    world.panel("SS_BLANK")
    assert pte._booking_registration_open("sunday_school") is True
    world.say("ფასი რა არის?", ("say", _SS_OFFER))
    world.say("10 წლისაა", ("say", "რომელი დღე და დრო გირჩევნიათ?"))
    world.say("კი, 12 საათი მაწყობს", _CHECK12, _FREE12)
    world.say(f"ნინო {_PHONE}")
    assert not _refused_by_the_camp(world), world.tools
    assert _booked(world, _ISO12), (world.calendar, world.rows, world.tools)


def test_an_explicit_closed_status_still_closes(world):
    world.panel("SS")
    sections = _sections("SS")
    for s in sections:
        if s["id"] == "sunday_school":
            s["registration_status"] = "closed"
    path = Path(acs.SECTIONS_PATH)
    path.write_text(yaml.safe_dump({"sections": sections}, allow_unicode=True,
                                   sort_keys=False), encoding="utf-8")
    assert pte._booking_registration_open("sunday_school") is False


# ═══ two programmes on sale: never guess, ask ═════════════════════════════

def test_an_unnamed_opener_with_two_programmes_on_sale_is_asked_which(world):
    """With two programmes on sale, a first message that names neither gets the
    programme menu — the parent is asked, nothing is guessed."""
    world.panel("SS_PARIS")
    reply = world.say("ფასი რა არის?", ("say", "გასაგებია."))
    assert "საკვირაო სკოლა" in reply and "პარიზის ბანაკი" in reply, reply


def test_the_menu_is_sent_once_and_the_reply_to_it_is_kept(world):
    """Measured 2026-10-05 on Sunday School + Paris: „ფასი რა არის?",
    „ნინო 591234567", „ორივე მაინტერესებს", „10 წლისაა" — four identical menus,
    and the parent's number never kept. The menu asks once; the reply to it goes
    to the flow both programmes belong to."""
    world.panel("SS_PARIS")
    first = world.say("ფასი რა არის?")
    assert "საკვირაო სკოლა" in first and "პარიზის ბანაკი" in first, first
    second = world.say(f"ნინო {_PHONE}", ("say", "რომელი პროგრამა გაინტერესებთ?"))
    assert second != first, "the same menu was sent again"
    assert world.lead.phone == _PHONE


def test_two_programmes_and_nothing_named_asks_instead_of_refusing(world):
    """G3/G6: Sunday School and Paris on sale and nothing in the chat that picks
    one — the slot check tells the model to ask, with the panel's names, and
    neither books nor refuses as the camp."""
    world.panel("SS_PARIS")
    conv = _conversation([("user", "ფასი რა არის?"), ("assistant", _BOTH),
                          ("user", "10 წლისაა"),
                          ("assistant", "რომელი დღე და დრო გირჩევნიათ?")])
    result = _executor(conv, "12 საათი მაწყობს").execute(
        "check_consultation_slot", {"datetime_iso": _ISO12})
    assert result["reason"] == "program_unresolved", result
    assert result["next_action"] == "ask_which_program"
    assert sorted(result["candidate_programs"]) == ["პარიზის ბანაკი", "საკვირაო სკოლა"]
    assert world.calendar == []
    booked = _executor(conv, "კი").execute(
        "book_consultation", {"name": "ნინო", "phone": _PHONE, "datetime_iso": _ISO12,
                              "child_age": "10", "user_confirmed_datetime": True})
    assert booked["reason"] == "program_unresolved", booked
    assert world.calendar == []


def test_the_parents_answer_to_which_one_completes_the_booking(world):
    world.panel("SS_PARIS")
    conv = _conversation([("user", "ფასი რა არის?"), ("assistant", _BOTH),
                          ("user", "10 წლისაა"),
                          ("assistant", "რომელი დღე და დრო გირჩევნიათ?"),
                          ("user", "12 საათი მაწყობს"),
                          ("assistant", "რომელი პროგრამისთვის?")])
    checked = _executor(conv, "საკვირაო სკოლა").execute(
        "check_consultation_slot", {"datetime_iso": _ISO12})
    assert checked.get("available") is True, checked
    conv.history.append({"role": "user", "content": "საკვირაო სკოლა"})
    conv.history.append({"role": "assistant", "content": "12:00 თავისუფალია. " + _ASK_CONTACT})
    booked = _executor(conv, f"ნინო {_PHONE}").execute(
        "book_consultation", {"name": "ნინო", "phone": _PHONE, "datetime_iso": _ISO12,
                              "child_age": "10", "user_confirmed_datetime": True})
    assert booked.get("success") is True, booked
    assert _ISO12 in world.calendar
    assert conv.lead.consultation_program_name == "საკვირაო სკოლა"


def test_the_programme_the_agent_offered_is_the_consultations_programme(world):
    """G7: the parent never named it, but the agent's last reply was about
    Sunday School alone — that is what the consultation is for."""
    world.panel("SS_PARIS")
    world.say("ფასი რა არის?", ("say", _BOTH))
    world.say("ბავშვებისთვის რა გაქვთ კვირაობით?", ("say", _SS_OFFER))
    world.say("10 წლისაა, 12 საათი მაწყობს", _CHECK12, _FREE12)
    assert not [t for t in world.tools if t.get("reason") == "program_unresolved"], world.tools
    world.say(f"ნინო {_PHONE}")
    assert _booked(world, _ISO12), (world.calendar, world.rows, world.tools)
    assert _program_on_the_booking(world) == ["საკვირაო სკოლა"]


def test_paris_named_by_the_parent_books_for_paris(world):
    world.panel("SS_PARIS")
    world.say("პარიზის ბანაკი მაინტერესებს", ("say", "პარიზის ბანაკი 9-17 წლისთვისაა."))
    world.say("10 წლისაა", ("say", "რომელი დღე და დრო გირჩევნიათ?"))
    world.say("12 საათი მაწყობს", _CHECK12, _FREE12)
    world.say(f"ნინო {_PHONE}")
    assert _booked(world, _ISO12), (world.calendar, world.rows, world.tools)
    assert _program_on_the_booking(world) == ["პარიზის ბანაკი"]


def test_a_reply_that_lists_both_programmes_attributes_nothing():
    """The welcome menu and every „we have X and Y" name several programmes and
    say nothing about the parent's choice."""
    conv = _conversation([("user", "ფასი რა არის?"), ("assistant", _BOTH)])
    with _panel_only("SS_PARIS"):
        result = parent_llm_engine.resolve_programme(conv, "კი", conv.lead)
    assert result.state == "ambiguous"
    assert sorted(c["id"] for c in result.candidates) == ["paris_camp", "sunday_school"]


# ═══ the ended summer camp is never another programme, and never the default ═

def test_the_ended_camps_own_name_is_not_read_as_paris():
    """Reverse leak (2026-10-05 review): „საზაფხულო ბანაკი" is made of generic
    words, „ბანაკი" had one active owner, so the ended camp's name was Paris."""
    with _panel_only("SS_PARIS"):
        assert parent_flow._program_id_for_turn("საზაფხულო ბანაკი მაინტერესებს") == ""
        assert parent_flow._msg_names_the_camp("საზაფხულო ბანაკი მაინტერესებს") is True
        conv = _conversation([])
        closed = parent_llm_engine.resolve_programme(
            conv, "საზაფხულო ბანაკზე მინდა ჩაწერა", conv.lead)
        assert closed.state == "closed" and closed.program_id == "summer_camp"


def test_a_bare_camp_word_means_the_one_camp_on_sale():
    with _panel_only("SS_PARIS"):
        assert parent_flow._program_id_for_turn("ბანაკი რა ღირს?") == "paris_camp"
        conv = _conversation([])
        found = parent_llm_engine.resolve_programme(conv, "ბანაკი რა ღირს?", conv.lead)
        assert found.state == "open" and found.program_id == "paris_camp"


def test_booking_the_ended_camp_by_name_is_refused_and_drops_the_held_slot(world):
    """The parent named the ended camp in the booking turn: refused as closed —
    and the slot held for the earlier choice does not wait to book later
    (Screenshot_50)."""
    world.panel("SS_PARIS")
    conv = _conversation([("user", "ფასი რა არის?"), ("assistant", _SS_OFFER)])
    conv.lead.name, conv.lead.phone, conv.lead.child_age = "ნინო", _PHONE, "10"
    conv.pending_booking = {"requested_datetime_iso": _ISO12, "user_confirmed_datetime": True}
    result = _executor(conv, "საზაფხულო ბანაკზე მინდა ჩაწერა").execute(
        "book_consultation", {"name": "ნინო", "phone": _PHONE, "datetime_iso": _ISO12,
                              "child_age": "10", "user_confirmed_datetime": True})
    assert result.get("reason") == "camp_registration_closed"
    assert conv.pending_booking is None
    assert world.calendar == []


def test_an_earlier_question_about_the_ended_camp_does_not_own_later_turns():
    with _panel_only("SS"):
        conv = _conversation([("user", "საზაფხულო ბანაკი როდისაა?"),
                              ("assistant", "საზაფხულო ბანაკი დასრულდა.")])
        found = parent_llm_engine.resolve_programme(conv, "ფასი რა არის?", conv.lead)
        assert found.state == "open" and found.program_id == "sunday_school"


def test_a_camp_info_fetch_does_not_wipe_the_programme_while_the_camp_is_ended(world):
    world.panel("SS_PARIS")
    conv = _conversation([("user", "პარიზის ბანაკი მაინტერესებს")])
    conv.lead.program_id = "paris_camp"
    _executor(conv, "რა შედის ფასში?").execute("get_camp_info", {"topic": "price"})
    assert conv.lead.program_id == "paris_camp"


def test_a_camp_info_fetch_still_clears_the_tag_while_the_camp_is_on_sale(world):
    world.panel("CAMP_ONLY")
    conv = _conversation([])
    conv.lead.program_id = "some_other_programme"
    _executor(conv, "ბანაკი").execute("get_camp_info", {"topic": "price"})
    assert conv.lead.program_id == ""


# ═══ W1 — a held slot books only on a turn that completes or confirms it ═══

def _hold_a_slot_with_everything_known(world):
    world.say("ფასი რა არის?", ("say", _SS_OFFER))
    world.conversation.lead.name = "ნინო"
    world.conversation.lead.phone = _PHONE
    world.conversation.lead.child_age = "10"
    world.conversation.pending_booking = {
        "requested_datetime_iso": _ISO12, "user_confirmed_datetime": True,
        "missing_fields": [],
    }


# CAMP_ONLY is where the old code shows W1 directly: its gate was open, so a
# held slot booked on „არა". With the camp ended the old gate refused every
# booking, which hid the defect — the operator approved changing the camp's own
# behaviour here on 2026-10-03.
@pytest.mark.parametrize("panel", ["SS", "CAMP_ONLY"])
@pytest.mark.parametrize("reply", ["არა", "სხვა დრო მინდა", "ფასი რა არის?", "გამარჯობა"])
def test_a_held_slot_does_not_book_on_a_message_that_adds_nothing(world, panel, reply):
    world.panel(panel)
    _hold_a_slot_with_everything_known(world)
    world.say(reply, ("say", "კარგით."))
    assert world.calendar == [], (reply, world.tools)


@pytest.mark.parametrize("panel", ["SS", "CAMP_ONLY"])
@pytest.mark.parametrize("reply", ["კი", "კი ჩანიშნეთ", "დიახ, ჩამწერეთ", "მაწყობს"])
def test_a_held_slot_books_on_a_yes(world, panel, reply):
    world.panel(panel)
    _hold_a_slot_with_everything_known(world)
    world.say(reply)
    assert _booked(world, _ISO12), (reply, world.calendar, world.rows, world.tools)


def test_a_held_slot_books_on_the_turn_that_brings_the_last_detail(world):
    world.panel("SS")
    world.say("ფასი რა არის?", ("say", _SS_OFFER))
    world.say("10 წლისაა", ("say", "რომელი დღე და დრო გირჩევნიათ?"))
    world.say("კი, 12 საათი მაწყობს", _CHECK12, _FREE12)
    world.say(f"ნინო {_PHONE}")
    assert _booked(world, _ISO12), (world.calendar, world.rows, world.tools)


# ═══ the camp alone in the panel behaves as it always did ═════════════════

def test_the_running_camp_alone_still_books_under_its_own_gate(world):
    world.panel("CAMP_ONLY")
    world.say("ფასი რა არის?", ("say", "ბანაკის ფასი 2150 ლარია. რამდენი წლისაა ბავშვი?"))
    world.say("10 წლისაა", ("say", "რომელი დღე და დრო გირჩევნიათ?"))
    world.say("კი, 12 საათი მაწყობს", _CHECK12, _FREE12)
    world.say(f"ნინო {_PHONE}")
    assert _booked(world, _ISO12), (world.calendar, world.rows, world.tools)


# ── helpers for the unit tests ───────────────────────────────────────────────
class _panel_only:
    """Point the panel at a synthetic file for a block, with the production
    flags the reader consults. Used by the tests that need no conversation."""

    def __init__(self, panel: str):
        self.panel = panel

    def __enter__(self):
        import tempfile
        self._mp = pytest.MonkeyPatch()
        tmp = Path(tempfile.mkdtemp(prefix="r4a-"))
        path = tmp / "sections.yaml"
        path.write_text(yaml.safe_dump({"sections": _sections(self.panel)},
                                       allow_unicode=True, sort_keys=False), encoding="utf-8")
        self._mp.setattr(acs, "SECTIONS_PATH", path)
        live = dataclasses.replace(config_module.settings, **_PROD)
        for mod in list(sys.modules.values()):
            name = getattr(mod, "__name__", "") or ""
            if (name == "app.config" or name.startswith("app.")) and isinstance(
                getattr(mod, "settings", None), config_module.Settings,
            ):
                self._mp.setattr(mod, "settings", live)
        return self

    def __exit__(self, *exc):
        self._mp.undo()
        return False


# ═══ the same reader, everywhere else the programme matters ═══════════════
#
# The follow-up, the manager's number, the hand-off mail and the comment DM —
# each used to fall to the summer camp when nothing named a programme.

from app.services import comment_service  # noqa: E402
from app.services import followup_service  # noqa: E402


def _due_followup_conv(turns, program_id: str = "") -> Conversation:
    conv = _conversation(turns)
    conv.segment = "PARENT"
    conv.lead.segment = "PARENT"
    conv.lead.program_id = program_id
    conv.followup_stage = ""
    conv.last_bot_message_at = (datetime.utcnow() - timedelta(hours=25)).isoformat()
    return conv


def test_an_untagged_lead_who_asked_about_paris_gets_a_paris_follow_up():
    """Every follow-up tick 2026-10-04…05 logged sent=0: a lead nobody had
    tagged was a CAMP lead, and the ended camp's gate silenced it."""
    with _panel_only("SS_PARIS"):
        conv = _due_followup_conv([("user", "პარიზის ბანაკი რა ღირს?")])
        eligible, name, is_dynamic, _ = followup_service._followup_program_eligibility(conv)
    assert (eligible, name, is_dynamic) == (True, "პარიზის ბანაკი", True)


def test_sunday_school_alone_an_untagged_lead_gets_its_follow_up():
    with _panel_only("SS"):
        conv = _due_followup_conv([("user", "ფასი რა არის?")])
        eligible, name, is_dynamic, _ = followup_service._followup_program_eligibility(conv)
    assert (eligible, name, is_dynamic) == (True, "საკვირაო სკოლა", True)


def test_two_programmes_and_no_choice_send_no_follow_up():
    """No follow-up names a programme the parent did not pick (G3)."""
    with _panel_only("SS_PARIS"):
        conv = _due_followup_conv([("user", "ფასი რა არის?"), ("assistant", _BOTH)])
        eligible, *_ = followup_service._followup_program_eligibility(conv)
    assert eligible is False


def test_another_programmes_follow_up_never_falls_back_to_the_camps_template():
    """A panel without the `followup_program_*` templates sent a Paris lead the
    summer camp's own follow-up („გუშინ ბანაკის შესახებ მოგწერეთ…")."""
    sent: list[dict] = []
    with _panel_only("SS_PARIS") as p:
        p._mp.setattr(
            acs, "render_template",
            lambda tid, ctx=None, *a, **k: "CAMP_TEMPLATE_24H" if tid == "followup_24h" else "")
        p._mp.setattr(followup_service, "messenger_service", type("M", (), {
            "send_message": staticmethod(lambda **kw: sent.append(kw) or True)})())
        p._mp.setattr(followup_service, "_save_conversation_to_redis", lambda c: None)
        conv = _due_followup_conv([("user", "პარიზის ბანაკი რა ღირს?")], "paris_camp")
        result = followup_service._maybe_send_followup_for_conversation(
            conv, followup_service.now_tbilisi())
    assert result == "sent", sent
    assert "CAMP_TEMPLATE_24H" not in sent[0]["text"]
    assert "პარიზის ბანაკი" in sent[0]["text"]


def test_two_programmes_with_their_own_numbers_ask_which_then_give_each_by_name():
    """Operator, 2026-10-04: two programmes on sale and none named → ask which
    one; if they share a number, give it. Until 2026-10-05 the summer camp's
    number was handed over."""
    with _panel_only("SS_PARIS"):
        conv = _conversation([("user", "გამარჯობა")])
        first = parent_flow._render_manager_number_answer(conv.lead, conversation=conv)
        conv.history.append({"role": "assistant", "content": first})
        second = parent_flow._render_manager_number_answer(conv.lead, conversation=conv)
    assert "500 00 00" not in first, first
    assert "საკვირაო სკოლა" in first and "პარიზის ბანაკი" in first, first
    assert "500 00 00 02" in second and "500 00 00 03" in second, second
    assert "500 00 00 01" not in first + second


def test_two_programmes_sharing_one_number_give_it_without_asking():
    with _panel_only("SS_PARIS") as p:
        shared = [dict(s, manager_contact="500 00 00 02") if s["id"] == "paris_camp" else s
                  for s in _sections("SS_PARIS")]
        p._mp.setattr(acs, "load_sections", lambda: [dict(s) for s in shared])
        conv = _conversation([("user", "გამარჯობა")])
        answer = parent_flow._render_manager_number_answer(conv.lead, conversation=conv)
    assert "500 00 00 02" in answer, answer
    assert "500 00 00 01" not in answer


def test_the_programme_the_chat_named_hands_over_its_own_number():
    with _panel_only("SS_PARIS"):
        conv = _conversation([("user", "პარიზის ბანაკი მაინტერესებს")])
        answer = parent_flow._render_manager_number_answer(conv.lead, conversation=conv)
    assert "500 00 00 03" in answer and "500 00 00 02" not in answer, answer


def test_the_hand_off_mail_names_no_programme_when_the_parent_never_chose_one():
    """With two programmes on sale the mail used to say „საკვირაო სკოლა" for a
    parent who may have been asking about Paris (G5: name the right one, or
    none — never a wrong one)."""
    mails: list[dict] = []
    with _panel_only("SS_PARIS") as p:
        p._mp.setattr(notification_service, "_send_email",
                      lambda subject="", body="", **k: mails.append(
                          {"subject": subject, "body": body}) or True)
        lead = Lead(sender_id="r4a-mail", platform="messenger", segment="PARENT")
        lead.name, lead.phone = "ნინო", _PHONE
        assert notification_service.notify_sunday_school_handoff(lead) is True
    assert mails[0]["subject"] == "ახალი მოთხოვნა — ნინო", mails
    assert "საკვირაო" not in mails[0]["subject"] + mails[0]["body"]


_PARIS_OFFER = ("პარიზის ბანაკის დეტალებს მენეჯერი გაგაცნობთ. "
                "გსურთ, რომ დაგიკავშირდეთ? მომწერეთ სახელი და ნომერი.")


def _callback(world, turns, message):
    conv = _conversation(turns)
    result = _executor(conv, message).execute(
        "request_manager_callback", {"name": "ნინო", "phone": _PHONE})
    assert result.get("success") is True, result
    return conv, world.mails[-1]


def test_the_callback_mail_names_the_programme_the_agent_was_talking_about(world):
    """G5 + G7 on the „call me" path: the parent never typed „პარიზი" — the
    agent offered Paris and the parent answered with a name and a number.
    Until 2026-10-05 this mail read „ჩვენი პროგრამით" with two programmes on
    sale: the callback tool never read the chat."""
    world.panel("SS_PARIS")
    conv, mail = _callback(world, [("user", "ფასი რა არის?"), ("assistant", _BOTH),
                                   ("user", "ორივეზე მითხარით"),
                                   ("assistant", _PARIS_OFFER)],
                           f"ნინო {_PHONE}")
    assert "პარიზის ბანაკი" in mail["body"], mail
    assert "საკვირაო" not in mail["subject"] + mail["body"], mail
    assert conv.lead.consultation_program_name == "პარიზის ბანაკი"


def test_the_callback_mail_names_no_programme_when_none_was_chosen(world):
    world.panel("SS_PARIS")
    _conv, mail = _callback(world, [("user", "ფასი რა არის?"), ("assistant", _BOTH)],
                            f"ნინო {_PHONE}")
    assert "პარიზის" not in mail["body"] and "საკვირაო" not in mail["body"], mail
    assert "ბანაკით" not in mail["body"], mail


def _model_down(*a, **k):
    raise RuntimeError("provider unavailable (test)")


def test_when_the_model_cannot_answer_the_ended_camp_is_never_sent(world, monkeypatch):
    """Measured 2026-10-05: with the model down, a Sunday-School parent's
    „ფასი რა არის?" got the ended camp's 2150 block and „10 წლისაა" the camp's
    introduction (the legacy flow). Operator 2026-10-06: ask for the contact;
    the manager calls back."""
    world.panel("SS")
    monkeypatch.setattr(anthropic_service, "_post", _model_down)
    for message in ("ფასი რა არის?", "10 წლისაა"):
        reply = world.say(message)
        assert "2150" not in reply and "ბანაკ" not in reply, reply
        assert reply == parent_flow._OUTAGE_ASK_CONTACT, reply
    reply = world.say(f"ნინო {_PHONE}")
    assert reply == parent_flow._SUNDAY_SCHOOL_SUCCESS, reply
    assert world.mails and "ნინო" in world.mails[-1]["body"], world.mails


def test_when_the_model_cannot_answer_a_paris_parent_is_handed_over_as_paris(world, monkeypatch):
    """The named-programme path returned "" — the parent got no reply at all."""
    world.panel("SS_PARIS")
    monkeypatch.setattr(anthropic_service, "_post", _model_down)
    reply = world.say("პარიზის ბანაკი მაინტერესებს")
    assert reply == parent_flow._OUTAGE_ASK_CONTACT, reply
    reply = world.say(f"ნინო {_PHONE}")
    assert reply == parent_flow._SUNDAY_SCHOOL_SUCCESS, reply
    assert "პარიზის ბანაკი" in world.mails[-1]["body"], world.mails
    assert "საკვირაო" not in world.mails[-1]["subject"] + world.mails[-1]["body"]
    assert not [r for r in world.rows if r.get("tab") == "SundaySchoolLeads"], world.rows


def test_the_hand_off_mail_with_sunday_school_alone_is_unchanged():
    mails: list[dict] = []
    with _panel_only("SS") as p:
        p._mp.setattr(notification_service, "_send_email",
                      lambda subject="", body="", **k: mails.append(
                          {"subject": subject, "body": body}) or True)
        lead = Lead(sender_id="r4a-mail", platform="messenger", segment="PARENT")
        lead.name, lead.phone = "ნინო", _PHONE
        notification_service.notify_sunday_school_handoff(lead)
    assert mails[0]["subject"] == "საკვირაო სკოლა — ახალი მოთხოვნა — ნინო"
    assert "ტიპი: საკვირაო სკოლა (sunday_school)" in mails[0]["body"]


def _comment_dm(panel: str, caption: str, comment: str) -> str:
    """The DM a comment gets, end to end from the post's caption."""
    box: dict = {}
    with _panel_only(panel) as p:
        async def _caption(post_id, platform):
            return caption
        p._mp.setattr(comment_service, "fetch_post_content", _caption)
        # Production's env list carries the camp's words (Railway, 2026-10-04).
        p._mp.setattr(comment_service, "settings", dataclasses.replace(
            comment_service.settings, PARENT_HASHTAGS=["camp", "ბანაკი"]))
        def _reply(comment_id, text):
            box["text"] = text
            return True
        p._mp.setattr(comment_service.messenger_service, "send_private_reply", _reply)
        import asyncio
        asyncio.run(comment_service.send_dm_from_comment(
            "r4a-comment", "facebook", "post-1", None,
            comment_id="c-1", comment_text=comment))
        cs.conversations.pop("r4a-comment", None)
    return box.get("text", "")


def test_a_comment_under_the_ended_camps_post_gets_the_menu_not_its_price():
    """The ended camp keeps its hashtags in the panel; „#camp" still sent its
    price block (G2). It now reads as a post with no programme's hashtag, and
    gets the general greeting (operator, 2026-10-05: „გამარჯობა, რით შემიძლია
    დაგეხმაროთ")."""
    text = _comment_dm("SS", "საზაფხულო ბანაკი #camp", "ფასი რა არის?")
    assert text, "no DM at all"
    assert "2150" not in text, text
    assert "ბანაკ" not in text, text
    assert "რით შემიძლია დაგეხმაროთ" in text, text


def test_a_coming_soon_programmes_hashtag_still_gets_its_own_dm():
    """Only an ENDED programme stops matching — a coming-soon one still
    answers for its own posts."""
    with _panel_only("CAMP_ONLY"):
        section = acs.find_section_from_post_hashtags(["საკვირაოსკოლა"])
    assert section is not None and section["id"] == "sunday_school"


def test_a_paris_post_gets_paris_not_the_camp():
    text = _comment_dm("SS_PARIS", "პარიზის ბანაკი #პარიზი", "ფასი რა არის?")
    assert text and "2150" not in text, text


# ═══ round 4b — what the adversarial review of 2026-10-06 found ═══════════
#
# Nine skeptics read the code against the production flags and panel and tried
# to break each claim. Every scenario below is one they found; each was RED on
# the code it was found in.

_REAL_PARIS = "„გმირის მოგზაურობა\" პარიზში - საგანმანათლებლო ბანაკი"


def test_the_menu_is_sent_once_after_a_greeting_opener(world, monkeypatch):
    """The most common opener: „გამარჯობა". The greeting policy stores the menu
    as „გამარჯობა 💙…", and the exact comparison missed it — the menu went out
    twice and the number in between was lost."""
    monkeypatch.setattr(parent_flow, "_CLIENT_EMOJI_ENABLED", True)
    world.panel("SS_PARIS")
    first = world.say("გამარჯობა")
    assert "პარიზის ბანაკი" in first, first
    second = world.say(f"ნინო {_PHONE}", ("say", "რომელი პროგრამა გაინტერესებთ?"))
    assert second != first, "the same menu was sent again"
    assert world.lead.phone == _PHONE


def test_a_message_naming_both_programmes_leaves_no_tag(world):
    """The first match in panel order used to be tagged and own every later
    turn, so a parent interested in both was booked into Sunday School."""
    world.panel("SS_PARIS")
    conv = _conversation([])
    conv.lead.program_id = "sunday_school"
    parent_flow._tag_per_product_booking(
        conv, "საკვირაო სკოლაც და პარიზის ბანაკიც მაინტერესებს")
    assert conv.lead.program_id == ""
    conv.history = [
        {"role": "user", "content": "საკვირაო სკოლაც და პარიზის ბანაკიც მაინტერესებს"},
        {"role": "assistant", "content": _BOTH},
    ]
    found = parent_llm_engine.resolve_programme(conv, "10 წლისაა", conv.lead)
    assert found.state == "ambiguous", found


def test_two_programmes_fetched_in_one_turn_leave_no_tag(world):
    """„ორივეს ფასი" — the model fetched both; the tag kept the last one and the
    booking was filed under it without a choice."""
    world.panel("SS_PARIS")
    conv = _conversation([("user", "ორივეს ფასი მითხარით")])
    executor = _executor(conv, "ორივეს ფასი მითხარით")
    executor.execute("get_program_info", {"program_id": "sunday_school"})
    assert conv.lead.program_id == "sunday_school"
    executor.execute("get_program_info", {"program_id": "paris_camp"})
    assert conv.lead.program_id == ""


def test_the_chat_outranks_an_older_tag():
    """A Sunday-School tag kept a chat that had moved on to Paris (the agent's
    newest reply named only Paris) filed as Sunday School."""
    with _panel_only("SS_PARIS"):
        conv = _conversation([
            ("user", "საკვირაო სკოლა რა ღირს?"), ("assistant", _SS_OFFER),
            ("user", "ბანაკზეც მინდა ინფორმაცია"),
            ("assistant", "პარიზის ბანაკი 9–17 წლის ბავშვებისთვისაა."),
        ])
        conv.lead.program_id = "sunday_school"
        found = parent_llm_engine.resolve_programme(conv, "კარგი, ჩამწერეთ", conv.lead)
    assert found.state == "open" and found.program_id == "paris_camp", found


@pytest.mark.parametrize("reply", ["არა", "ფასი რა არის?"])
def test_a_tagged_paris_lead_does_not_book_the_held_slot_on_a_no(world, reply):
    """W1 on the hoisted path: a Paris-tagged lead never reaches the commit
    helper, so „არა" booked whenever the model called book_consultation."""
    world.panel("SS_PARIS")
    world.say("პარიზის ბანაკი რა ღირს?", ("say", "პარიზის ბანაკის დეტალებს გეტყვით."))
    # A lead tagged to Paris (get_program_info or a later naming turn tags it),
    # so every turn takes the hoisted engine path.
    world.lead.program_id = "paris_camp"
    world.lead.name, world.lead.phone, world.lead.child_age = "ნინო", _PHONE, "10"
    world.conversation.pending_booking = {
        "requested_datetime_iso": _ISO12, "user_confirmed_datetime": True,
        "missing_fields": [],
    }
    book = ("tool", "book_consultation", {
        "name": "ნინო", "phone": _PHONE, "datetime_iso": _ISO12,
        "child_age": "10", "user_confirmed_datetime": True})
    world.say(reply, book, ("say", "კარგით."))
    assert world.calendar == [], (reply, world.tools)
    world.say("კი", book, ("say", "ჩაგინიშნეთ."))
    assert _booked(world, _ISO12), (world.calendar, world.tools)
    assert _program_on_the_booking(world) == ["პარიზის ბანაკი"]


def test_a_paris_contact_hand_off_is_not_filed_as_sunday_school(world):
    """„მენეჯერის ნომერი" then a name and number: the contact hand-off wrote the
    row to the SundaySchoolLeads tab as „sunday_school"."""
    world.panel("SS_PARIS")
    conv = _conversation([("user", "პარიზის ბანაკი მაინტერესებს"),
                          ("assistant", "პარიზის ბანაკის დეტალებს მენეჯერი გაგაცნობთ.")])
    conv.lead.name, conv.lead.phone = "ნინო", _PHONE
    reply = parent_flow._sunday_school_dispatch(conv, conv.lead, f"ნინო {_PHONE}")
    assert reply == parent_flow._SUNDAY_SCHOOL_SUCCESS, reply
    assert not [r for r in world.rows if r.get("tab") == "SundaySchoolLeads"], world.rows
    assert _program_on_the_booking(world) == ["პარიზის ბანაკი"], world.rows
    assert conv.followup_blocked_reason == "manager_handoff_completed"


def test_the_model_is_told_when_no_programme_is_chosen():
    """„ჩემი შვილისთვის ფასი რა არის?" goes to the model with no menu; it was
    left to guess which programme's price to give."""
    with _panel_only("SS_PARIS"):
        conv = _conversation([])
        context = parent_llm_engine._build_context_message(
            conv, conv.lead, "ჩემი შვილისთვის ფასი რა არის?")
    assert "programme_not_chosen=" in context, context
    assert "საკვირაო სკოლა" in context and "პარიზის ბანაკი" in context


def test_a_seven_year_old_is_judged_by_sunday_schools_own_band():
    """The sales context judged every child by the camp's 9–17 and told the
    model not to offer the booking — Sunday School takes 7-year-olds."""
    with _panel_only("SS_PARIS"):
        conv = _conversation([("user", "საკვირაო სკოლა მაინტერესებს")])
        conv.lead.child_age = "7"
        assert parent_llm_engine._age_status(conv.lead, conv) == "eligible"
        text = parent_llm_engine._build_sales_context(conv, conv.lead, "ფასი რა არის?")
    assert "დაჯავშნა" not in text, text


def test_the_camps_value_angles_travel_only_with_a_summer_camp_turn():
    """„…ეკრანისგან დისტანცია, … აზრიანი ზაფხული" went with every PARENT
    turn — Sunday School's and Paris's included."""
    with _panel_only("SS_PARIS"):
        conv = _conversation([("user", "საკვირაო სკოლა მაინტერესებს")])
        text = parent_llm_engine._build_sales_context(conv, conv.lead, "მეტი მითხარით")
    assert "აზრიანი ზაფხული" not in text, text
    with _panel_only("CAMP_ONLY"):
        conv = _conversation([("user", "საზაფხულო ბანაკი მაინტერესებს")])
        text = parent_llm_engine._build_sales_context(conv, conv.lead, "მეტი მითხარით")
    assert "აზრიანი ზაფხული" in text, text


def test_paris_facts_keep_the_euro_price_and_the_link_whatever_the_description(monkeypatch):
    """The Paris brief: „€2690" (paid in lari) — the derived price_gel 2690 was
    handed to the model as a GEL figure; and a description pasted from the ~10k
    brief pushed the registration link past the 6000-character cut."""
    monkeypatch.setitem(_PARIS, "name", _REAL_PARIS)
    monkeypatch.setitem(_PARIS, "price_text", "€2690 (გადახდა ლარში, კურსით)")
    monkeypatch.setitem(_PARIS, "price_gel", 2690)
    monkeypatch.setitem(_PARIS, "registration_url", "https://wordacademy.ge/course/hero-journey/")
    monkeypatch.setitem(_PARIS, "description_full", "პროგრამა. " * 900)
    with _panel_only("SS_PARIS"):
        section = acs.get_section("paris_camp")
        facts = parent_llm_engine._active_program_facts(section)
        conv = _conversation([])
        tool = _executor(conv, "პარიზის ბანაკის ფასი?").execute(
            "get_program_info", {"program_id": "paris_camp"})
    assert "https://wordacademy.ge/course/hero-journey/" in facts
    assert "€2690" in facts
    assert "price_gel" not in facts, facts[:300]
    assert "price_gel" not in tool.get("facts", {}), tool


def _model_down_for(world, monkeypatch):
    monkeypatch.setattr(anthropic_service, "_post", _model_down)


def test_when_the_model_is_down_a_question_is_never_taken_for_a_name(world, monkeypatch):
    world.panel("SS")
    _model_down_for(world, monkeypatch)
    assert world.say("ფასი რა არის?") == parent_flow._OUTAGE_ASK_CONTACT
    assert world.say(_PHONE) == parent_flow._OUTAGE_ASK_NAME
    reply = world.say("ფასი რა არის?")
    assert (world.lead.name or "") == "", world.lead.name
    assert reply != parent_flow._SUNDAY_SCHOOL_SUCCESS, reply
    assert not world.mails, world.mails


def test_when_the_model_is_down_the_greeting_heart_does_not_lose_the_contact(world, monkeypatch):
    monkeypatch.setattr(parent_flow, "_CLIENT_EMOJI_ENABLED", True)
    world.panel("SS_PARIS")
    _model_down_for(world, monkeypatch)
    first = world.say("გამარჯობა, პარიზის ბანაკი მაინტერესებს")
    assert parent_flow._OUTAGE_ASK_CONTACT in first, first
    reply = world.say(f"ნინო {_PHONE}")
    assert reply == parent_flow._SUNDAY_SCHOOL_SUCCESS, reply
    assert "პარიზის ბანაკი" in world.mails[-1]["body"], world.mails


def test_when_the_model_is_down_name_and_number_may_come_separately(world, monkeypatch):
    world.panel("SS")
    _model_down_for(world, monkeypatch)
    assert world.say("ფასი რა არის?") == parent_flow._OUTAGE_ASK_CONTACT
    assert world.say("ნინო") == parent_flow._OUTAGE_ASK_PHONE
    assert world.say(_PHONE) == parent_flow._SUNDAY_SCHOOL_SUCCESS
    assert world.mails


@pytest.mark.parametrize("message", [
    "პარიზის ბანაკზე ტრანსპორტი შედის?", "პარიზის ბანაკის ფასი რა არის?",
])
def test_when_the_model_is_down_a_paris_turn_gets_no_summer_camp_fact(world, monkeypatch, message):
    """The hoisted programme path fell through to the summer camp's own
    transport / price / stream answers and its manager number."""
    world.panel("SS_PARIS")
    _model_down_for(world, monkeypatch)
    reply = world.say(message)
    assert reply == parent_flow._OUTAGE_ASK_CONTACT, reply


def test_no_follow_up_names_a_programme_the_parent_never_asked_about():
    """Sunday School alone on sale, the parent asked only about the ended camp:
    the follow-up named Sunday School."""
    with _panel_only("SS"):
        conv = _due_followup_conv([("user", "საზაფხულო ბანაკი როდის იქნება?")])
        eligible, *_ = followup_service._followup_program_eligibility(conv)
    assert eligible is False


def test_educational_is_not_the_paris_camps_word(monkeypatch):
    """„საგანმანათლებლო" is in the real Paris name and read as Paris alone."""
    monkeypatch.setitem(_PARIS, "name", _REAL_PARIS)
    with _panel_only("SS_PARIS"):
        conv = _conversation([])
        found = parent_llm_engine.resolve_programme(
            conv, "საგანმანათლებლო პროგრამები გაქვთ?", conv.lead)
        assert found.state == "ambiguous", found
        for message in ("პარიზის ბანაკი მაინტერესებს", "გმირის მოგზაურობა რა არის?",
                        "ბანაკი რა ღირს?"):
            found = parent_llm_engine.resolve_programme(conv, message, conv.lead)
            assert found.state == "open" and found.program_id == "paris_camp", (message, found)
        found = parent_llm_engine.resolve_programme(
            conv, "საზაფხულო ბანაკი მაინტერესებს", conv.lead)
        assert found.state == "closed" and found.program_id == "summer_camp", found


def test_the_ended_camps_hashtag_word_in_a_chat_is_not_the_camp():
    """„bavshvebi" — the ended camp's hashtag, Latin for „children" — made a
    parent's message the ended camp's, and the mail named „საზაფხულო ბანაკი"."""
    with _panel_only("SS_PARIS"):
        conv = _conversation([])
        found = parent_llm_engine.resolve_programme(
            conv, "chemi bavshvebi 10 wlisaa", conv.lead)
    assert not (found.state == "closed" and found.program_id == "summer_camp"), found


def test_a_paris_registration_question_does_not_get_the_camps_closure(world):
    world.panel("SS_PARIS")
    conv = _conversation([("user", "პარიზის ბანაკი მაინტერესებს")])
    result = _executor(conv, "როგორ დავრეგისტრირდე?").execute(
        "get_camp_info", {"topic": "registration"})
    assert result.get("reason") != "camp_registration_closed", result


def test_the_ended_camp_says_nothing_about_two_childrens_ages(world):
    world.panel("SS_PARIS")
    conv = _conversation([("user", "საზაფხულო ბანაკი როდის იქნება?"),
                          ("assistant", "საზაფხულო ბანაკი დასრულდა.")])
    assert parent_flow._maybe_handle_multi_child_age(
        conv, "10 და 13 წლის შვილები მყავს") is None


# ═══ round 4c — the regression hunt of 2026-10-06 ═════════════════════════
#
# Six reviewers compared the round-4b code with the deployed b9f1e64 and looked
# for anything that worked before and would not now. Each test below is one
# scenario they traced.

def test_a_reply_naming_both_programmes_ends_the_chat_and_the_newer_tag_decides():
    """Sunday School first, then the agent compared both and the model fetched
    Paris (tag paris). The comparison was skipped and the older Sunday-School
    reply won: Paris's parent got Sunday School's price, number and booking."""
    with _panel_only("SS_PARIS"):
        conv = _conversation([
            ("user", "საკვირაო სკოლა მაინტერესებს"), ("assistant", _SS_OFFER),
            ("user", "სხვა რა პროგრამები გაქვთ?"), ("assistant", _BOTH),
        ])
        conv.lead.program_id = "paris_camp"
        found = parent_llm_engine.resolve_programme(
            conv, "ეგ მეორე მაინტერესებს, რა ღირს?", conv.lead)
        assert found.state == "open" and found.program_id == "paris_camp", found
        conv.lead.program_id = ""
        found = parent_llm_engine.resolve_programme(
            conv, "ეგ მეორე მაინტერესებს, რა ღირს?", conv.lead)
        assert found.state == "ambiguous", found


@pytest.mark.parametrize("reply", [
    "თანახმა ვარ", "კი, თანახმა ვარ", "მზად ვარ", "არაუშავს", "პარასკევს 12-ზე",
    f"თამარა {_PHONE}", "12-ზე", "11:00", "იყოს", "კარგი, იყოს", "სწორია",
    "კი, მაწყობს ეს დრო, მენეჯერი რომელ საათამდე მუშაობს?", "დიახ, ჩამწერეთ. სად ტარდება?",
])
def test_an_ordinary_confirmation_does_not_stop_the_booking(reply):
    """„ვარ " holds „არ ", „პარასკევს" and „თამარა" hold „არა"; „12-ზე" has no
    date word — each was refused, and the prompt then asked for the day and
    time the parent had just given."""
    assert parent_flow._turn_allows_booking_the_held_slot(reply), reply


@pytest.mark.parametrize("reply", [
    "არა", "არა, მადლობა", "არ მინდა", "ვერ მოვალ", "ფასი რა არის?", "სხვა საათზე მინდა",
    "კი, მაგრამ ჯერ ფასი რა არის?",
])
def test_a_no_a_question_or_another_time_still_stops_the_booking(reply):
    assert not parent_flow._turn_allows_booking_the_held_slot(reply), reply


@pytest.mark.parametrize("reply", ["მინდა სხვა დრო", "მინდა ვიფიქრო", "მინდა ვიცოდე ფასი"])
def test_an_opening_minda_is_not_a_yes_to_the_held_slot(reply):
    assert not parent_flow._says_yes_to_the_held_slot(reply), reply


def test_a_question_word_rules_out_the_name_not_the_message():
    message = f"ნინო {_PHONE} რა ღირს კონსულტაცია"
    assert parent_flow._is_storable_person_name("ნინო", message)
    assert not parent_flow._is_storable_person_name("რა ღირს", "რა ღირს")


def test_a_number_after_the_outage_ask_completes_a_held_slot(world, monkeypatch):
    """The outage intercept ran before the held-slot check: the number went to
    the manager as a callback and the slot the parent had chosen was dropped."""
    world.panel("SS")
    _hold_a_slot_with_everything_known(world)
    world.lead.phone = ""
    world.conversation.history.append(
        {"role": "assistant", "content": parent_flow._OUTAGE_ASK_CONTACT})
    monkeypatch.setattr(anthropic_service, "_post", _model_down)
    world.say(_PHONE)
    assert _booked(world, _ISO12), (world.calendar, world.rows, world.tools)


def test_when_the_model_is_down_a_number_with_a_question_keeps_only_the_number(
        world, monkeypatch):
    world.panel("SS")
    monkeypatch.setattr(anthropic_service, "_post", _model_down)
    assert world.say("ფასი რა არის?") == parent_flow._OUTAGE_ASK_CONTACT
    reply = world.say(f"{_PHONE}, რა ღირს")
    assert (world.lead.name or "") == "", world.lead.name
    assert world.lead.phone == _PHONE
    assert reply == parent_flow._OUTAGE_ASK_NAME, reply
    assert not world.mails, world.mails


def test_when_the_model_is_down_a_known_name_is_not_asked_again(world, monkeypatch):
    world.panel("SS")
    monkeypatch.setattr(anthropic_service, "_post", _model_down)
    assert world.say("ფასი რა არის?") == parent_flow._OUTAGE_ASK_CONTACT
    world.lead.name = "ნინო"
    assert world.say("ნინო") == parent_flow._OUTAGE_ASK_PHONE


def test_a_tagged_paris_lead_books_on_thanakhma_var(world):
    world.panel("SS_PARIS")
    world.say("პარიზის ბანაკი რა ღირს?", ("say", "პარიზის ბანაკის დეტალებს გეტყვით."))
    world.lead.program_id = "paris_camp"
    world.lead.name, world.lead.phone, world.lead.child_age = "ნინო", _PHONE, "10"
    world.conversation.pending_booking = {
        "requested_datetime_iso": _ISO12, "user_confirmed_datetime": True,
        "missing_fields": [],
    }
    book = ("tool", "book_consultation", {
        "name": "ნინო", "phone": _PHONE, "datetime_iso": _ISO12,
        "child_age": "10", "user_confirmed_datetime": True})
    world.say("თანახმა ვარ", book, ("say", "ჩაგინიშნეთ."))
    assert _booked(world, _ISO12), (world.calendar, world.tools)
    assert _program_on_the_booking(world) == ["პარიზის ბანაკი"]


@pytest.mark.parametrize("name_known", [False, True])
def test_after_an_outage_ask_a_working_model_answers_the_next_message(
        world, monkeypatch, name_known):
    """The outage ask caught the next short message even with the model back:
    „რა ღირს" was stored as the parent's name (or, with a name already known,
    the same ask came back) instead of the model answering it."""
    world.panel("SS")
    monkeypatch.setattr(anthropic_service, "_post", _model_down)
    assert world.say("ფასი რა არის?") == parent_flow._OUTAGE_ASK_CONTACT
    if name_known:
        world.lead.name = "ნინო"
    monkeypatch.setattr(anthropic_service, "_post", world.post)
    reply = world.say("რა ღირს", ("say", "საკვირაო სკოლის ფასი 595 ლარია."))
    assert "595" in reply, reply
    assert (world.lead.name or "") == ("ნინო" if name_known else ""), world.lead.name
    assert not world.mails, world.mails


def test_when_the_model_is_down_a_tagged_lead_still_books_the_held_slot_on_a_yes(
        world, monkeypatch):
    """The programme path answered every silent turn with the outage reply, so
    „კი" to a held slot gave the manager's number instead of the booking the
    chain below makes without the model."""
    world.panel("SS")
    _hold_a_slot_with_everything_known(world)
    world.lead.program_id = "sunday_school"
    monkeypatch.setattr(anthropic_service, "_post", _model_down)
    world.say("კი")
    assert _booked(world, _ISO12), (world.calendar, world.rows, world.tools)


def test_when_the_model_is_down_a_tagged_lead_still_gets_the_manager_number(
        world, monkeypatch):
    world.panel("SS")
    world.say("საკვირაო სკოლა მაინტერესებს", ("say", _SS_OFFER))
    world.lead.program_id = "sunday_school"
    monkeypatch.setattr(anthropic_service, "_post", _model_down)
    reply = world.say("მენეჯერის ნომერი მომწერეთ")
    assert "500 00 00 02" in reply, reply


def test_a_comment_only_conversation_is_not_a_programme_follow_up():
    """The private reply to a comment is a conversation the parent never wrote
    in; read by the programme reader it became eligible and a second follow-up
    went to parents who had booked in their DM conversation."""
    with _panel_only("SS"):
        conv = _due_followup_conv([("assistant", "საკვირაო სკოლის შესახებ გწერთ.")])
        eligible, name, is_dynamic, _tpl = followup_service._followup_program_eligibility(conv)
        dm = _due_followup_conv([("user", "საკვირაო სკოლა მაინტერესებს"),
                                 ("assistant", _SS_OFFER)])
        dm_result = followup_service._followup_program_eligibility(dm)
    assert (name, is_dynamic) == ("", False), (eligible, name, is_dynamic)
    assert dm_result[0] is True and dm_result[2] is True, dm_result


def test_a_failed_mail_for_another_programme_still_keeps_the_contact(world, monkeypatch):
    world.panel("SS_PARIS")
    monkeypatch.setattr(notification_service, "notify_sunday_school_handoff", lambda lead: False)
    conv = _conversation([("user", "პარიზის ბანაკი მაინტერესებს"),
                          ("assistant", "პარიზის ბანაკის დეტალებს მენეჯერი გაგაცნობთ.")])
    conv.lead.name, conv.lead.phone = "ნინო", _PHONE
    parent_flow._sunday_school_dispatch(conv, conv.lead, f"ნინო {_PHONE}")
    assert _program_on_the_booking(world) == ["პარიზის ბანაკი"], world.rows


def test_the_age_is_judged_by_the_programme_named_in_the_same_message():
    """„პარიზის ბანაკი, შვილი 8 წლისაა": the age was judged with the chat alone,
    found no programme and told the model „ასაკი დიაპაზონშია"."""
    message = "პარიზის ბანაკი მაინტერესებს, შვილი 8 წლისაა"
    with _panel_only("SS_PARIS"):
        conv = _conversation([])
        conv.lead.child_age = "8"
        assert parent_llm_engine._age_status(conv.lead, conv, message) == "ineligible"
        text = parent_llm_engine._build_sales_context(conv, conv.lead, message)
    assert "ასაკი დიაპაზონშია" not in text, text


def test_no_programme_chosen_is_not_told_the_age_is_in_range_or_asked_the_camps_goal():
    with _panel_only("SS_PARIS"):
        conv = _conversation([])
        conv.lead.child_age = "10"
        unchosen = parent_llm_engine._build_sales_context(conv, conv.lead, "ფასი რა არის?")
        school = _conversation([("user", "საკვირაო სკოლა მაინტერესებს")])
        school.lead.child_age = "10"
        sunday = parent_llm_engine._build_sales_context(school, school.lead, "მეტი მითხარით")
    assert "ასაკი დიაპაზონშია" not in unchosen, unchosen
    assert "ბანაკიდან" not in sunday, sunday
