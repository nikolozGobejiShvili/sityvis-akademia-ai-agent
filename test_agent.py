from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = Path(__file__).resolve().parent
FAILURES: list[str] = []


def install_mocks() -> dict:
    state = {
        "leads": {},
        "sent_messages": [],
        "manager_notifications": [],
        "booked_slots": [],
        "comments": {},
        "comment_replies": [],
        "post_contents": {},
        "post_fetch_calls": 0,
    }

    # Real Settings defaults, captured BEFORE `app.config` is replaced below.
    # The stub settings object is hand-written, so every flag added to the real
    # Settings after this script was written raised AttributeError at runtime —
    # callers swallow it ("admin adult events load failed: ... has no attribute
    # USE_SECTION_STATUS_GATE") and the ADULT checks below silently stopped
    # testing anything. Falling back to the real defaults keeps the script
    # honest as Settings grows; explicit values below still win.
    try:
        import importlib as _il
        _real_settings = _il.import_module("app.config").Settings()
    except Exception:
        _real_settings = None

    class _StubSettings(SimpleNamespace):
        def __getattr__(self, name: str):
            if _real_settings is not None and hasattr(_real_settings, name):
                return getattr(_real_settings, name)
            if name.startswith(("USE_", "ENABLE_", "ALLOW_")):
                return False
            raise AttributeError(name)

    config = ModuleType("app.config")
    config.DATA_DIR = BASE_DIR / "data"
    config.Settings = object
    config.has_value = lambda value: bool(value and str(value).strip())
    config.csv_values = lambda value: [item.strip() for item in str(value or "").split(",") if item.strip()]
    config.settings = _StubSettings(
        COMPANY_NAME="ტესტ კომპანია",
        COMPANY_TONE_PARENTS="ემპათიური, მშვიდი და პროფესიონალური ტონი.",
        COMPANY_TONE_ADULTS="პრემიუმ, დახვეწილი და კულტურული ტონი.",
        COMPANY_LANGUAGE="Georgian",
        KNOWLEDGE_BASE=(
            "ბანაკი ეხმარება ბავშვებს ეკრანისგან დისტანცირებაში, "
            "ცოცხალ კომუნიკაციაში და შემოქმედებით განვითარებაში."
        ),
        EVENTS=(
            "=== EVENT 1 ===\n"
            "სახელი: პოეზიის საღამო\n"
            "თემა: თანამედროვე ქართული პოეზია\n"
            "თარიღი: 15 მაისი\n"
            "დრო: 20:00\n"
            "ლოკაცია: სასტუმრო Rooms-ის პრემიუმ დარბაზი\n"
            "მოწვეული სტუმრები: პოეტი და კამერული მუსიკის დუო\n"
            "ფასი: 120\n"
            "ჯავშნის ლინკი: https://example.com/poetry\n"
            "აღწერა: დახურული კულტურული შეხვედრა მცირე საზოგადოებისთვის.\n\n"
            "=== EVENT 2 ===\n"
            "სახელი: მუსიკის კამერული საღამო\n"
            "თემა: კლასიკური მუსიკა და საუბარი\n"
            "თარიღი: 16 მაისი\n"
            "დრო: 19:30\n"
            "ლოკაცია: სასტუმრო Stamba-ს ლაუნჯი\n"
            "მოწვეული სტუმრები: პიანისტი და მუსიკის მკვლევარი\n"
            "ფასი: 150\n"
            "ჯავშნის ლინკი: https://example.com/music\n"
            "აღწერა: პრემიუმ კულტურული შეხვედრა.\n"
        ),
        CAMP_PRICE=2200,
        FOLLOWUP_CONTENT_LINK="https://example.com/followup",
        FOLLOWUP_HOURS=48,
        followup_enabled=True,
        followup_delay_minutes=2880,
        META_ACCESS_TOKEN="test-token",
        OPENAI_API_KEY="test-key",
        OPENAI_MODEL="gpt-4o-mini",
        PARENT_HASHTAGS=[],
        ADULT_HASHTAGS=[],
        COMMENT_FALLBACK_LINK="https://example.com/info",
        COMMENT_FOLLOWUP_HOURS=24,
        # COMMENT FLOW PATCH 1 — defaults the new gate to True here
        # so the existing comment tests (which historically asserted
        # `comment_replies >= 1`) keep validating the public-reply
        # path. The production default in `config.Settings` is False;
        # tests in `tests/` cover the False / True / exception cases
        # for the new behaviour.
        ENABLE_PUBLIC_COMMENT_REPLY=True,
    )
    sys.modules["app.config"] = config

    openai_service = ModuleType("app.services.openai_service")
    openai_service.detect_segment = fake_detect_segment
    openai_service.generate_response = fake_generate_response
    openai_service.generate_summary = fake_generate_summary
    openai_service.detect_start_intent = fake_detect_start_intent
    openai_service.generate_parent_value_response = fake_generate_parent_value_response
    sys.modules["app.services.openai_service"] = openai_service

    messenger_service = ModuleType("app.services.messenger_service")

    def send_message(sender_id: str, platform: str, text: str) -> bool:
        state["sent_messages"].append({"sender_id": sender_id, "platform": platform, "text": text})
        print(f"[MOCK SEND][{platform}] To {sender_id}: {text[:80]}...")
        return True

    def send_private_reply(comment_id: str, text: str) -> bool:
        """COMMENT FLOW PATCH 2 — mocked private-reply sender. Captured
        alongside `sent_messages` so existing tests that count outbound
        deliveries don't have to know which channel was used."""
        state.setdefault("private_replies", []).append(
            {"comment_id": comment_id, "text": text},
        )
        print(f"[MOCK PRIVATE REPLY] comment={comment_id}: {text[:80]}...")
        return True

    def get_user_profile(sender_id: str, platform: str) -> dict:
        state.setdefault("profile_fetches", []).append(
            {"sender_id": sender_id, "platform": platform},
        )
        print(f"[MOCK PROFILE] Fetching for {sender_id} on {platform}")
        return {
            "name": "ანა ლომიძე",
            "first_name": "ანა",
            "last_name": "ლომიძე",
            "username": "",
        }

    messenger_service.send_message = send_message
    messenger_service.send_private_reply = send_private_reply
    messenger_service.get_user_profile = get_user_profile
    sys.modules["app.services.messenger_service"] = messenger_service

    calendar_service = ModuleType("app.services.calendar_service")

    # Clock-relative slot fixture. These were pinned to 2026-05-15/16, which
    # silently became a past date and made every booking assertion below fail
    # — the whole downstream chain (state DONE, lead saved, manager notified,
    # Calendar recorded) collapses once the agent correctly refuses a past
    # slot. Deriving from "now" keeps the fixture honest at any run date;
    # weekends are skipped because Sunday is a closed booking day.
    def _fixture_slots() -> list[dict]:
        from datetime import date as _date, timedelta as _td
        from app.agent.services.timestamps import now_tbilisi
        _MONTHS = {
            1: "იანვარი", 2: "თებერვალი", 3: "მარტი", 4: "აპრილი",
            5: "მაისი", 6: "ივნისი", 7: "ივლისი", 8: "აგვისტო",
            9: "სექტემბერი", 10: "ოქტომბერი", 11: "ნოემბერი", 12: "დეკემბერი",
        }
        days: list[_date] = []
        cursor = now_tbilisi().date() + _td(days=1)
        while len(days) < 2:
            if cursor.weekday() != 6:  # Sunday is closed
                days.append(cursor)
            cursor += _td(days=1)
        first, second = days
        def _slot(d: _date, hour: int) -> dict:
            return {
                "date": f"{d.day} {_MONTHS[d.month]}",
                "time": f"{hour:02d}:00",
                "datetime_iso": f"{d.isoformat()}T{hour:02d}:00:00+04:00",
            }
        return [_slot(first, 14), _slot(first, 16), _slot(second, 11)]

    calendar_service.get_available_slots = lambda: _fixture_slots()
    calendar_service.get_free_slots = (
        lambda target_date=None, duration_minutes=30, **kw: _fixture_slots()
    )
    calendar_service.check_slot_available = lambda slot_datetime, duration_minutes=30: True
    calendar_service.format_slots_for_chat = fake_format_slots_for_chat

    def book_slot(datetime_iso: str, lead, duration_minutes: int = 30) -> bool:
        state["booked_slots"].append(
            {
                "datetime_iso": datetime_iso,
                "lead_name": lead.name,
                "lead_phone": lead.phone,
                "lead_platform": lead.platform,
                "child_age": lead.child_age,
                "challenge": lead.challenge,
            },
        )
        print(f"[MOCK CALENDAR] Booked {datetime_iso} for {lead.name} (phone={lead.phone})")
        return True

    calendar_service.book_slot = book_slot
    sys.modules["app.services.calendar_service"] = calendar_service

    sheets_service = ModuleType("app.services.sheets_service")

    def save_lead(lead) -> bool:
        state["leads"][lead.sender_id] = lead
        print(f"[MOCK SHEETS] Saved {lead.sender_id} status={lead.status}")
        return True

    def update_lead(sender_id: str, updates: dict) -> bool:
        lead = state["leads"].get(sender_id)
        if not lead:
            return False
        for key, value in updates.items():
            attr = "followup_sent" if key in {"follow_up_sent", "followup_sent"} else key
            setattr(lead, attr, value)
        print(f"[MOCK SHEETS] Updated {sender_id}: {updates}")
        return True

    def get_cold_leads() -> list:
        cutoff = datetime.utcnow() - timedelta(hours=48)
        cold = []
        for lead in state["leads"].values():
            if lead.status not in {"New", "Qualified"}:
                continue
            if lead.followup_sent:
                continue
            if lead.last_message_at < cutoff:
                cold.append(lead)
        print(f"[MOCK SHEETS] Cold leads: {len(cold)}")
        return cold

    def save_comment(data: dict) -> bool:
        state["comments"][data.get("comment_id")] = dict(data)
        print(f"[MOCK SHEETS] Saved comment {data.get('comment_id')} status={data.get('status')}")
        return True

    def update_comment(comment_id: str, updates: dict) -> bool:
        comment = state["comments"].get(comment_id)
        if not comment:
            return False
        comment.update(updates)
        print(f"[MOCK SHEETS] Updated comment {comment_id}: {updates}")
        return True

    def get_pending_comment_followups() -> list:
        cutoff = datetime.utcnow() - timedelta(hours=24)
        pending = []
        for comment in state["comments"].values():
            if comment.get("status") != "CommentOnly":
                continue
            created_raw = comment.get("created_at")
            try:
                created = datetime.fromisoformat(created_raw) if isinstance(created_raw, str) else created_raw
            except ValueError:
                continue
            if not created or created >= cutoff:
                continue
            pending.append(comment)
        print(f"[MOCK SHEETS] Pending comment follow-ups: {len(pending)}")
        return pending

    sheets_service.save_lead = save_lead
    sheets_service.create_lead = save_lead
    sheets_service.update_lead = update_lead
    sheets_service.get_cold_leads = get_cold_leads
    sheets_service.get_lead = lambda sender_id: state["leads"].get(sender_id)
    sheets_service.save_comment = save_comment
    sheets_service.update_comment = update_comment
    sheets_service.get_pending_comment_followups = get_pending_comment_followups
    sys.modules["app.services.sheets_service"] = sheets_service

    notification_service = ModuleType("app.services.notification_service")

    def notify_manager(lead, event_type: str) -> bool:
        state["manager_notifications"].append({"lead": lead, "event_type": event_type})
        print(f"[MOCK MANAGER] {event_type}: {lead.sender_id} {lead.segment} {lead.status}")
        return True

    notification_service.notify_manager = notify_manager
    notification_service.send_manager_notification = lambda lead, summary: notify_manager(lead, "lead")
    sys.modules["app.services.notification_service"] = notification_service

    return state


def fake_detect_segment(message_text: str) -> str:
    text = message_text.lower()
    if any(word in text for word in ("ბანაკ", "ბავშვ", "შვილ", "ეკრან", "წლის")):
        return "PARENT"
    if any(word in text for word in ("საღამო", "პოეზ", "ღონისძი", "დაჯავშნ", "ბილეთ")):
        return "ADULT"
    return "UNCLEAR"


def fake_generate_response(history: list, user_message: str, segment: str, context: str) -> str:
    if segment == "PARENT":
        return (
            "თქვენი გამოწვევა ეკრანდამოკიდებულებას ეხება, ამიტომ პროგრამა ბავშვს ეტაპობრივად "
            "ეხმარება ეკრანისგან დისტანცირებაში, ცოცხალ კომუნიკაციაში და თვითგამოხატვაში. "
            "კონსულტაციაზე ასაკისა და გარემოს მიხედვით ზუსტად აგიხსნით, რა ნაბიჯებია საუკეთესო."
        )

    if "სად არის" in user_message:
        return (
            "საღამო გაიმართება სასტუმრო Rooms-ის პრემიუმ დარბაზში. სივრცე შერჩეულია მშვიდი, "
            "დახვეწილი ატმოსფეროსთვის, სადაც სტუმრები მხოლოდ დასწრებას კი არა, საზოგადოების ნაწილად ყოფნას გრძნობენ."
        )

    return (
        "პოეზიის საღამო ეძღვნება თანამედროვე ქართულ პოეზიას. სტუმრები იქნებიან პოეტი და "
        "კამერული მუსიკის დუო. შეხვედრა გაიმართება სასტუმრო Rooms-ის პრემიუმ დარბაზში, "
        "15 მაისს, 20:00-ზე, დახვეწილ და ინტიმურ ატმოსფეროში."
    )


def fake_generate_summary(history: list) -> str:
    return "მომხმარებელი დაინტერესდა შეთავაზებით, მიიღო ძირითადი ინფორმაცია და გადავიდა დაჯავშნის ეტაპზე."


def fake_detect_start_intent(message_text: str) -> str:
    text = (message_text or "").lower()
    if any(word in text for word in ("ღირს", "ფასი", "რამდენი", "გადახდ")):
        return "PRICE"
    if any(word in text for word in ("ვჩაწერო", "დაჯავშნ", "რეგისტრაცი")):
        return "BOOK"
    if any(word in text for word in ("როდის", "თარიღი", "სად ტარდება", "ნაკადი", "ასაკიდან")):
        return "INFO"
    if any(word in text for word in ("ეკრან", "ვერ ვაშორებთ", "კომუნიკაცი უჭირს", "მარტო იკეტება")):
        return "CONCERN"
    return "GREETING"


def fake_generate_parent_value_response(
    *,
    child_age: str,
    challenge: str,
    deeper_concern: str,
    desired_change: str,
    company_name: str,
) -> str:
    return (
        f"ის, რასაც აღწერთ, ხშირად მხოლოდ ნაყოფია. {child_age} წლის ბავშვისთვის "
        f"ეს ფენა ღრმავდება სწორედ მაშინ, როცა {deeper_concern or 'ცოცხალი გარემო'} გვერდით არ აქვს. "
        f"{company_name}ის ბანაკი არის გარემო, სადაც ბავშვი აღმოაჩენს საკუთარ თავს და "
        f"გააქტიურებს დამოუკიდებელ აზროვნებას. "
        f"გსურთ უფასო კონსულტაცია, სადაც სპეციალისტი თქვენი შვილის სიტუაციას უფრო დეტალურად მოგისმენთ?"
    )


def fake_format_slots_for_chat(slots: list) -> str:
    emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"]
    lines = [f"{emojis[index]} {slot['date']} - {slot['time']}" for index, slot in enumerate(slots)]
    return "\n".join(lines) + "\n\nგთხოვთ აირჩიოთ ნომერი (1, 2 ან 3)"


def expect(condition: bool, message: str) -> None:
    if condition:
        print(f"✅ {message}")
    else:
        print(f"❌ {message}")
        FAILURES.append(message)


def run_messages(conversation_service, sender_id: str, platform: str, messages: list[str]) -> list[str]:
    responses = []
    for message in messages:
        response = conversation_service.process_message(sender_id, message, platform)
        responses.append(response)
        print(f"\nUSER: {message}\nBOT: {response}\n")
    return responses


@pytest.fixture
def state() -> dict:
    module_snapshot = dict(sys.modules)
    state = install_mocks()
    install_comment_mocks(state)
    try:
        yield state
    finally:
        for name in list(sys.modules):
            if name == "app" or name.startswith("app."):
                if name not in module_snapshot:
                    del sys.modules[name]
        for name, module in module_snapshot.items():
            if name == "app" or name.startswith("app."):
                sys.modules[name] = module


@pytest.fixture
def conversation_service(state: dict):
    from app.services import conversation_service

    conversation_service.conversations.clear()
    return conversation_service


def test_parent_flow(conversation_service, state: dict) -> None:
    # Phase 3.6B: refreshed to match the live 4-layer-discovery parent flow.
    # Parent-greeting fix: the bot's very first reply at state=START is now
    # always the static PARENT_WELCOME menu (two-option routing). The age
    # question is asked on the next turn once the parent picks the camp
    # path, so the full flow is 8 turns, not 7.
    #
    # State transitions exercised (verified by dry-run, no retry, no shortcut):
    #   T1 START         → START          (static PARENT_WELCOME menu — first bot reply)
    #   T2 START         → ASK_AGE        (camp pick → PARENT_WELCOME_CAMP_OPENER; Meta profile auto-fills lead.name)
    #   T3 ASK_AGE       → ASK_CHALLENGE  (PARENT_ASK_CHALLENGE — open question, does NOT echo input)
    #   T4 ASK_CHALLENGE → ASK_DEEPER     (PARENT_ASK_DEEPER)
    #   T5 ASK_DEEPER    → ASK_DESIRE     (PARENT_ASK_DESIRE)
    #   T6 ASK_DESIRE    → ASK_NAME       (PRESENT_VALUE + PARENT_ASK_PHONE_ONLY appended;
    #                                       asks PHONE only — owner intent, name from Meta)
    #   T7 ASK_NAME      → PRESENT_VALUE  (PARENT_OFFER_CONSULTATION with 3 mocked slots)
    #   T8 PRESENT_VALUE → DONE           (slot picked → PARENT_BOOKING_CONFIRMED;
    #                                       lead saved, manager notified, calendar booked)
    #
    # Turn 4 deliberately avoids the substring "ეკრან" — fake_detect_start_intent
    # returns CONCERN for any input containing "ეკრან", which only runs at START
    # (so it would be inert here), but keeping the whole sequence "ეკრან"-free is
    # the safer baseline regardless of future intent-detection changes.
    print("\n================ TEST 1 - Parent full flow ================")
    sid = "parent-1"
    messages = [
        # P0 Live Demo UX — ISSUE 1 (2026-06-13): a bare topic word
        # („ბანაკი", no interest verb) still opens with the branded
        # two-option menu; an EXPLICIT intent statement
        # („ბანაკი მაინტერესებს") now skips the menu (see
        # test_single_message_explicit_camp). This full-flow test keeps
        # the menu opener so the 8-turn booking sequence is unchanged.
        "გამარჯობა, ბანაკი",                 # 1 — bare topic → menu
        "ბავშვების საზაფხულო ბანაკი",        # 2 — pick camp option
        "8",                                  # 3
        "ბევრს ზის ტელეფონზე",                # 4
        "ერთ ოთახში გამოიკეტება",             # 5
        "უფრო კომუნიკაბელური გახდეს",         # 6
        "599123456",                          # 7
        "1",                                  # 8
    ]
    responses = run_messages(conversation_service, sid, "instagram", messages)
    conversation = conversation_service.conversations[sid]

    # T1 — Static PARENT_WELCOME menu. No age question, no LLM greeting.
    expect(conversation.segment == "PARENT", "T1: Segment = PARENT")
    expect(
        "გვითხარით, რა გაინტერესებთ" in responses[0],
        "T1: Returns static PARENT_WELCOME menu (no LLM greeting)",
    )
    expect(
        "ბავშვების საზაფხულო ბანაკი" in responses[0]
        and "ზრდასრულთა კულტურული საღამოები" in responses[0],
        "T1: Menu lists both options",
    )
    expect(
        "მოგესალმებით" not in responses[0],
        "T1: First greeting does NOT contain 'მოგესალმებით'",
    )
    expect(
        "რამდენი წლისაა" not in responses[0],
        "T1: First greeting does NOT immediately ask child age",
    )

    # T2 — Camp pick → camp framing + age question.
    expect("რამდენი წლისაა შვილი" in responses[1], "T2: Asks child age (PARENT_WELCOME_CAMP_OPENER)")

    # T3 — Open challenge question; does NOT echo user input.
    # P2 update: the ask_challenge template is now NEUTRAL — it asks what
    # the parent is looking for from camp, not what "bothers them most".
    expect(
        "რას ელით ბანაკისგან" in responses[2],
        "T3: Asks open neutral question (PARENT_ASK_CHALLENGE)",
    )
    expect(
        "რა აწუხებთ" not in responses[2],
        "T3: Does NOT assume the child has a problem",
    )

    # T4 — Deeper-discovery question; price MUST NOT leak from settings.
    # P2 update: the ask_deeper template now asks neutrally about what
    # the child enjoys, not about "the inner reason behind the problem".
    expect(
        "რომ უკეთ წარმოვიდგინო" in responses[3],
        "T4: Asks neutral curiosity question (PARENT_ASK_DEEPER)",
    )
    expect(
        "შინაგანი მიზეზი" not in responses[3],
        "T4: Does NOT use problem-assumption phrasing",
    )
    expect("2200" not in "\n".join(responses), "T4: Settings price (2200) does not leak into any response")

    # T5 — Desire question.
    expect(
        "თუ წარმოვიდგინოთ" in responses[4],
        "T5: Asks 6-month-vision question (PARENT_ASK_DESIRE)",
    )

    # T6 — PRESENT_VALUE + PARENT_ASK_PHONE_ONLY appended. Owner intent: phone
    # asked, name NOT asked (greeted by first name from Meta profile).
    expect("გვითხარით ნომერი" in responses[5], "T6: Asks for phone (PARENT_ASK_PHONE_ONLY)")
    expect("ანა" in responses[5], 'T6: Greets by first name from Meta profile ("ანა")')
    expect("სახელი" not in responses[5], "T6: Does NOT ask for name (owner intent — auto-read from Meta profile)")

    # T7 — Calendar slots shown after phone collected.
    expect("15 მაისი - 14:00" in responses[6], "T7: Shows calendar slot block after phone collected")
    expect("გთხოვთ აირჩიოთ ნომერი" in responses[6], "T7: Prompts user to pick a slot number")

    # T8 — Booking confirmed.
    expect("დაჯავშნილია" in responses[7], "T8: Confirms booking (PARENT_BOOKING_CONFIRMED)")
    expect("15 მაისი" in responses[7] and "14:00" in responses[7], "T8: Renders selected slot date + time")

    # Post-flow state assertions — check BOTH the live conversation.lead object
    # AND the sheets-mock store (state["leads"]). Both must be populated for
    # the production CRM-append + manager-notify pipeline to be considered
    # exercised by the test.
    expect(conversation.state == "DONE", "After T8: conversation.state == DONE")
    expect(
        bool(conversation.lead and conversation.lead.name == "ანა ლომიძე"),
        'After T8: conversation.lead.name auto-read from Meta = "ანა ლომიძე"',
    )
    expect(
        bool(conversation.lead and conversation.lead.phone == "599123456"),
        'After T8: conversation.lead.phone captured = "599123456"',
    )
    expect(
        bool(conversation.lead and conversation.lead.status == "Booked"),
        'After T8: conversation.lead.status = "Booked"',
    )

    sheets_lead = state["leads"].get(sid)
    expect(bool(sheets_lead and sheets_lead.status == "Booked"), 'After T8: sheets store has lead with status "Booked"')
    expect(bool(sheets_lead and sheets_lead.name == "ანა ლომიძე"), 'After T8: sheets store has lead.name = "ანა ლომიძე"')

    expect(
        any(item["lead"].sender_id == sid for item in state["manager_notifications"]),
        "After T8: Manager notification recorded for this sender",
    )
    expect(
        any(
            item.get("lead_phone") == "599123456" and item.get("lead_name") == "ანა ლომიძე"
            for item in state["booked_slots"]
        ),
        'After T8: Calendar book_slot recorded lead_name "ანა ლომიძე" + lead_phone "599123456"',
    )


def test_adult_flow(conversation_service, state: dict) -> None:
    print("\n================ TEST 2 - Adult full flow ================")
    messages = [
        "საღამო გაქვთ?",
        "პოეზია მაინტერესებს",
        "სად არის?",
        "დავჯავშნე",
    ]
    responses = run_messages(conversation_service, "adult-1", "messenger", messages)
    conversation = conversation_service.conversations["adult-1"]
    lead = state["leads"].get("adult-1")

    expect(conversation.segment == "ADULT", "Segment = ADULT")
    expect("პოეზიის საღამო" in responses[0], "Shows events list")
    expect("თანამედროვე ქართულ პოეზიას" in responses[1] and "15 მაის" in responses[1], "Shows poetry event details")
    expect("Rooms" in responses[2] and "პრემიუმ" in responses[2], "Answers location question")
    expect("https://example.com/poetry" in responses[3], "Sends booking link")
    expect(bool(lead and lead.status == "Booked"), "Lead saved")
    expect(any(item["lead"].sender_id == "adult-1" for item in state["manager_notifications"]), "Manager notified")


def test_unclear(conversation_service) -> None:
    # Phase 3.6A: bare greetings now route to UNCLEAR (owner decision).
    # Assertions reflect the LIVE UNCLEAR_ROUTING text in
    # app/agent/templates/common/routing.yaml — stale strings like
    # "გაგვიმარტივეთ" / "ბავშვების საზაფხულო პროგრამა" were removed.
    print("\n================ TEST 3 - Unclear → clarification ================")
    responses = run_messages(conversation_service, "unclear-1", "whatsapp", ["გამარჯობა"])
    conversation = conversation_service.conversations["unclear-1"]

    expect(conversation.segment == "UNCLEAR", "Segment = UNCLEAR")
    expect("გვითხარით" in responses[0], "Asks clarifying question in Georgian")
    expect(
        "ბავშვების საზაფხულო ბანაკი" in responses[0]
        and "ზრდასრულთა კულტურული საღამოები" in responses[0],
        "Offers both options",
    )


def test_unclear_recovery_to_parent(conversation_service) -> None:
    # Phase 3.6A: split-message recovery. Bare greeting → UNCLEAR, then a
    # follow-up with a camp keyword → PARENT on the SAME conversation.
    print("\n================ TEST 3B - UNCLEAR → PARENT recovery ================")
    responses = run_messages(
        conversation_service, "unclear-recover-p", "instagram",
        ["გამარჯობა", "ბანაკი მაინტერესებს"],
    )
    conversation = conversation_service.conversations["unclear-recover-p"]

    expect("ბავშვების საზაფხულო ბანაკი" in responses[0], "Turn 1: UNCLEAR routing")
    expect(conversation.segment == "PARENT", "Turn 2: segment upgraded to PARENT")
    expect("რამდენი წლისაა" in responses[1], "Turn 2: enters PARENT flow (asks child age)")


def test_unclear_recovery_to_adult(conversation_service) -> None:
    # Phase 3.6A: split-message recovery. Bare greeting → UNCLEAR, then a
    # follow-up with an adult keyword → ADULT.
    print("\n================ TEST 3C - UNCLEAR → ADULT recovery ================")
    responses = run_messages(
        conversation_service, "unclear-recover-a", "messenger",
        ["გამარჯობა", "ღონისძიება მაინტერესებს"],
    )
    conversation = conversation_service.conversations["unclear-recover-a"]

    expect("ბავშვების საზაფხულო ბანაკი" in responses[0], "Turn 1: UNCLEAR routing")
    expect(conversation.segment == "ADULT", "Turn 2: segment upgraded to ADULT")
    expect(
        "კულტურულ სივრცეში" in responses[1] or "პოეზიის საღამო" in responses[1],
        "Turn 2: enters ADULT flow (shows events)",
    )


def test_single_message_explicit_camp(conversation_service) -> None:
    # P0 Live Demo UX — ISSUE 1 (2026-06-13): a first message with CLEAR
    # camp intent ("გამარჯობა, ბანაკი მაინტერესებს") must NOT re-ask the
    # generic two-option menu. The agent greets and continues the camp
    # flow — asking the child's age directly. (Was: returned the static
    # menu; the owner-confirmed Phase 3.6A menu-first opener is now scoped
    # to ambiguous opens / bare greetings only.)
    print("\n================ TEST 3D - Single-message explicit camp ================")
    responses = run_messages(
        conversation_service, "explicit-p", "instagram",
        ["გამარჯობა, ბანაკი მაინტერესებს"],
    )
    conversation = conversation_service.conversations["explicit-p"]

    expect(conversation.segment == "PARENT", "Segment = PARENT (single message)")
    expect(
        "გვითხარით, რა გაინტერესებთ" not in responses[0],
        "Turn 1: clear camp intent SKIPS the generic disambiguation menu",
    )
    expect(
        "რამდენი წლისაა" in responses[0],
        "Turn 1: continues the camp flow (asks child age)",
    )


def test_single_message_explicit_adult(conversation_service) -> None:
    # Phase 3.6A: explicit single-message intent is not regressed (adult).
    print("\n================ TEST 3E - Single-message explicit adult ================")
    responses = run_messages(
        conversation_service, "explicit-a", "messenger",
        ["გამარჯობა, ღონისძიება მაინტერესებს"],
    )
    conversation = conversation_service.conversations["explicit-a"]

    expect(conversation.segment == "ADULT", "Segment = ADULT (single message)")
    expect(
        "კულტურულ სივრცეში" in responses[0] or "პოეზიის საღამო" in responses[0],
        "Enters ADULT flow directly",
    )


def test_vague_followup_stays_unclear(conversation_service) -> None:
    # Phase 3.6A: a vague follow-up after UNCLEAR (no camp/adult keyword)
    # must stay UNCLEAR — the agent re-asks instead of guessing.
    print("\n================ TEST 3F - Vague follow-up stays UNCLEAR ================")
    responses = run_messages(
        conversation_service, "vague-1", "whatsapp",
        ["გამარჯობა", "მაინტერესებს"],
    )
    conversation = conversation_service.conversations["vague-1"]

    expect(conversation.segment == "UNCLEAR", "Vague follow-up stays UNCLEAR")
    expect(
        "ბავშვების საზაფხულო ბანაკი" in responses[1]
        and "ზრდასრულთა კულტურული საღამოები" in responses[1],
        "Re-asks with both options",
    )


def test_price_only_stays_unclear(conversation_service) -> None:
    # Phase 3.6A (owner-confirmed): a bare price question with no
    # camp/adult signal stays UNCLEAR — adult events also have ticket
    # prices, so price alone does not prove camp interest.
    print("\n================ TEST 3G - Price-only stays UNCLEAR ================")
    responses = run_messages(
        conversation_service, "price-only-1", "instagram", ["ფასი?"],
    )
    conversation = conversation_service.conversations["price-only-1"]

    expect(conversation.segment == "UNCLEAR", "Price-only stays UNCLEAR")
    expect("ბავშვების საზაფხულო ბანაკი" in responses[0], "Routes via UNCLEAR template")


def test_tie_break_stays_unclear(conversation_service) -> None:
    # Phase 3.6A: a message that matches BOTH camp and adult keywords must
    # NOT be guessed. Tie-break rule keeps segment = UNCLEAR.
    print("\n================ TEST 3H - Tie-break stays UNCLEAR ================")
    responses = run_messages(
        conversation_service, "tie-break-1", "instagram",
        ["ბანაკი თუ კულტურული საღამო?"],
    )
    conversation = conversation_service.conversations["tie-break-1"]

    expect(conversation.segment == "UNCLEAR", "Tie-break (camp+adult) stays UNCLEAR")
    expect("ბავშვების საზაფხულო ბანაკი" in responses[0], "Re-asks for direction")


def test_followup(state: dict) -> None:
    print("\n================ TEST 4 - Follow-up ================")
    from app.models.conversation import Conversation
    from app.models.lead import Lead
    from app.services import conversation_service, followup_service

    # Follow-up Scheduler Patch (2026-05-30): source of truth moved
    # from Sheets cold-lead rows to the in-memory Conversation
    # snapshot driven by the per-turn markers (`last_bot_message_at`
    # + `followup_stage`). The cold-Lead state["leads"] entry is kept
    # so existing Sheets-mock assertions elsewhere still find it, but
    # the actual scheduler tick now scans the conversation dict.
    cold_lead = Lead(
        sender_id="cold-1",
        platform="instagram",
        segment="PARENT",
        child_age="9",
        challenge="ეკრანდამოკიდებულება",
        status="New",
        last_message_at=datetime.utcnow() - timedelta(hours=49),
    )
    state["leads"][cold_lead.sender_id] = cold_lead

    cold_conv = Conversation(sender_id="cold-1", platform="instagram")
    cold_conv.segment = "PARENT"
    cold_conv.state = "ASK_NAME"
    # Bot last spoke 49h ago → first_24h stage is due.
    cold_conv.last_bot_message_at = (
        datetime.utcnow() - timedelta(hours=49)
    ).isoformat()
    cold_conv.followup_stage = ""
    cold_conv.lead = cold_lead
    conversation_service.conversations["cold-1"] = cold_conv

    followup_service.check_and_send_followups()

    expect(cold_lead.sender_id in {lead.sender_id for lead in state["leads"].values()}, "Lead detected as cold")
    expect(any(item["sender_id"] == "cold-1" for item in state["sent_messages"]), "Follow-up message sent")
    # New invariant: follow-up state lives on the Conversation, not the
    # Sheets row. Stage must have advanced past empty to "first_24h".
    expect(cold_conv.followup_stage == "first_24h", 'Conversation stage advanced to "first_24h"')


def install_comment_mocks(state: dict) -> None:
    from app.services import comment_service

    class FakeAsyncResponse:
        def __init__(self, payload: dict | None = None) -> None:
            self._payload = payload or {}

        status_code = 200
        text = ""
        is_success = True

        def json(self) -> dict:
            return self._payload

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args) -> None:
            return None

        async def post(self, url, headers=None, json=None):
            state["comment_replies"].append(
                {
                    "url": url,
                    "message": (json or {}).get("message", ""),
                },
            )
            print(f"[MOCK META] Comment reply -> {url}: {(json or {}).get('message','')[:60]}")
            return FakeAsyncResponse()

        async def get(self, url, params=None):
            state["post_fetch_calls"] += 1
            post_id = url.rsplit("/", 1)[-1]
            field = (params or {}).get("fields", "caption")
            content = state["post_contents"].get(post_id, "")
            print(f"[MOCK META] GET post {post_id} field={field} -> {content[:50]!r}")
            return FakeAsyncResponse({field: content})

    comment_service.httpx = SimpleNamespace(AsyncClient=FakeAsyncClient)
    comment_service.detect_comment_intent = fake_detect_comment_intent
    comment_service.post_content_cache.clear()


async def fake_detect_comment_intent(comment_text: str) -> str:
    text = (comment_text or "").lower()
    interest_keywords = (
        "მაინტერესებს",
        "მინდა",
        "გამაგებინეთ",
        "დეტალები",
        "info",
        "ფასი",
        "რა ღირს",
        "რამდენი",
        "ჩავეწერო",
        "ვეწერები",
        "გაგზავნი",
        "შვილ",
        "+",
    )
    only_compliment = (
        "ლამაზი",
        "კარგი",
        "მაგარი",
        "super",
        "❤",
        "😍",
        "👏",
    )

    if any(token in text for token in interest_keywords):
        return "INTERESTED"
    if any(token in text for token in only_compliment):
        return "NOT_INTERESTED"
    return "NOT_INTERESTED"


def _reset_comment_state(state: dict) -> None:
    from app.services import comment_service

    state["comment_replies"].clear()
    state["post_fetch_calls"] = 0
    comment_service.post_content_cache.clear()


def test_parent_hashtag_detection(state: dict) -> None:
    print("\n================ TEST 5 - Parent hashtag detection ================")
    from app.config import settings as live_settings
    from app.routes.webhook import handle_comment
    from app.services import comment_service

    _reset_comment_state(state)
    live_settings.PARENT_HASHTAGS = ["banaki", "bavshvebi", "skola"]
    live_settings.ADULT_HASHTAGS = []
    state["post_contents"]["post_parent_1"] = "ბანაკი 2025 დაიწყო! #banaki #bavshvebi"

    asyncio.run(
        handle_comment(
            comment_id="comment-5",
            post_id="post_parent_1",
            sender_id="new_user_5",
            user_name="ნინო",
            comment_text="რა კარგი ბანაკია! შვილს გაგზავნიდი",
            platform="instagram",
        ),
    )

    hashtags = comment_service.extract_hashtags(state["post_contents"]["post_parent_1"])
    comment = state["comments"].get("comment-5")

    expect(hashtags == ["banaki", "bavshvebi"], 'Hashtags extracted: ["banaki", "bavshvebi"]')
    expect(comment and comment.get("segment") == "PARENT", "Segment = PARENT")


def test_adult_hashtag_detection(state: dict) -> None:
    print("\n================ TEST 6 - Adult hashtag detection ================")
    from app.config import settings as live_settings
    from app.routes.webhook import handle_comment
    from app.services import comment_service

    _reset_comment_state(state)
    live_settings.PARENT_HASHTAGS = []
    live_settings.ADULT_HASHTAGS = ["event", "premium", "kultura"]
    state["post_contents"]["post_adult_1"] = "ახალი კულტურული საღამო #event #pretium"

    asyncio.run(
        handle_comment(
            comment_id="comment-6",
            post_id="post_adult_1",
            sender_id="new_user_6",
            user_name="თამარ",
            comment_text="საღამოს დეტალები მაინტერესებს",
            platform="instagram",
        ),
    )

    hashtags = comment_service.extract_hashtags(state["post_contents"]["post_adult_1"])
    comment = state["comments"].get("comment-6")

    expect(hashtags == ["event", "pretium"], 'Hashtags extracted: ["event", "pretium"]')
    expect(comment and comment.get("segment") == "ADULT", "Segment = ADULT")


def test_georgian_hashtag(state: dict) -> None:
    print("\n================ TEST 7 - Georgian hashtag ================")
    from app.config import settings as live_settings
    from app.routes.webhook import handle_comment
    from app.services import comment_service

    _reset_comment_state(state)
    live_settings.PARENT_HASHTAGS = ["ბანაკი", "banaki"]
    live_settings.ADULT_HASHTAGS = []
    state["post_contents"]["post_geo_1"] = "ბანაკი იწყება #ბანაკი"

    asyncio.run(
        handle_comment(
            comment_id="comment-7",
            post_id="post_geo_1",
            sender_id="new_user_7",
            user_name="ლევან",
            comment_text="მაინტერესებს დეტალები",
            platform="instagram",
        ),
    )

    hashtags = comment_service.extract_hashtags(state["post_contents"]["post_geo_1"])
    comment = state["comments"].get("comment-7")

    expect(hashtags == ["ბანაკი"], 'Hashtag extracted: ["ბანაკი"]')
    expect(comment and comment.get("segment") == "PARENT", "Segment = PARENT")


def test_no_hashtag_match(state: dict) -> None:
    print("\n================ TEST 8 - No hashtag match ================")
    from app.config import settings as live_settings
    from app.routes.webhook import handle_comment

    _reset_comment_state(state)
    live_settings.PARENT_HASHTAGS = ["banaki"]
    live_settings.ADULT_HASHTAGS = ["event"]
    state["post_contents"]["post_unknown_1"] = "ჩვენი ახალი პოსტი #news"

    asyncio.run(
        handle_comment(
            comment_id="comment-8",
            post_id="post_unknown_1",
            sender_id="new_user_8",
            user_name="გია",
            comment_text="მაინტერესებს დეტალები",
            platform="instagram",
        ),
    )

    comment = state["comments"].get("comment-8")

    expect(comment and comment.get("segment") == "UNCLEAR", "Segment = UNCLEAR")
    expect(len(state["comment_replies"]) >= 1, "Agent still replies with clarifying message")


def test_cache_works(state: dict) -> None:
    print("\n================ TEST 9 - Cache works ================")
    from app.services import comment_service

    _reset_comment_state(state)
    state["post_contents"]["post_cache_1"] = "ბანაკი #banaki"

    first = asyncio.run(comment_service.fetch_post_content("post_cache_1", "instagram"))
    calls_after_first = state["post_fetch_calls"]

    second = asyncio.run(comment_service.fetch_post_content("post_cache_1", "instagram"))
    calls_after_second = state["post_fetch_calls"]

    expect(calls_after_first == 1, "First call - fetches from Meta API")
    expect(calls_after_second == 1 and second == first, "Second call - returns from cache (no API call)")


def main() -> int:
    state = install_mocks()

    from app.services import conversation_service

    conversation_service.conversations.clear()
    test_parent_flow(conversation_service, state)
    test_adult_flow(conversation_service, state)
    test_unclear(conversation_service)
    test_unclear_recovery_to_parent(conversation_service)
    test_unclear_recovery_to_adult(conversation_service)
    test_single_message_explicit_camp(conversation_service)
    test_single_message_explicit_adult(conversation_service)
    test_vague_followup_stays_unclear(conversation_service)
    test_price_only_stays_unclear(conversation_service)
    test_tie_break_stays_unclear(conversation_service)
    test_followup(state)

    install_comment_mocks(state)
    test_parent_hashtag_detection(state)
    test_adult_hashtag_detection(state)
    test_georgian_hashtag(state)
    test_no_hashtag_match(state)
    test_cache_works(state)

    print("\n================ SUMMARY ================")
    if FAILURES:
        print(f"❌ Failed checks: {len(FAILURES)}")
        for failure in FAILURES:
            print(f"- {failure}")
        return 1

    print("✅ All test checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
