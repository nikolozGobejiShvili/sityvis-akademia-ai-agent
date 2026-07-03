"""PRE-STAGING FIX BATCH (2026-06-12) — deterministic red-team fixes.

Covers the four cheap deterministic findings from
`docs/REDTEAM_FULL_SYSTEM_AUDIT.md`:

  * FIX 1 (A-1/A-2) — adult subscription delivery-question handler too
    narrow (3/10 phrasings); „შეტყობინება სად მომივა?" hit the FORBIDDEN
    „ამ კითხვაზე ვერ დაგეხმარებით" redirect.
  * FIX 2 (B-1) — dative child-relation forms („ჩემ შვილს", „ბავშვს")
    not captured by `_maybe_capture_adult_target`.
  * FIX 3 (F-D4) — bare-phone capture armed only on exact contact-ask
    markers („9-ნიშნა" / „საკონტაქტო ნომერ").
  * FIX 4 (F-D6) — explicit consultation intent + inline phone ignored
    the phone.

All deterministic; no OpenAI / network / Calendar / Sheets / email /
Meta / broadcast. `LIVE_BROADCAST_ENABLED` stays False.
"""

from __future__ import annotations

import pytest

from app.models.conversation import Conversation
from app.models.lead import Lead


# ===========================================================================
# FIX 1 — A-1/A-2 — adult delivery-question handler (broadened)
# ===========================================================================

from app.agent.llm import adult_llm_engine as _ae
from app.agent.llm.adult_llm_engine import (
    _maybe_handle_notification_delivery_question as _delivery,
    _maybe_adult_offtopic_reply as _offtopic,
)


# The 10 realistic phrasings the audit required to be answered as in-scope
# delivery-channel questions (Section A inputs 1–10).
_DELIVERY_INPUTS = [
    "შეტყობინება სად მომივა?",
    "შეტყობინება სად მოვა?",
    "მესენჯერში მომივა შეტყობინება?",
    "ლინკებზე სად მოდის შეტყობინება?",
    "დეტალებს სად გამომიგზავნით?",
    "როცა ახალი ღონისძიება დაემატება, სად შემატყობინებთ?",
    "თუ ახალი ღონისძიება დაემატება, სად გავიგებ?",
    "აქ მომწერთ?",
    "მეილზე მოდის თუ აქ?",
    "სად ვნახავ შეტყობინებას?",
]

_FORBIDDEN = "ამ კითხვაზე ვერ დაგეხმარებით"


@pytest.mark.parametrize("msg", _DELIVERY_INPUTS)
def test_fix1_all_ten_variants_get_delivery_answer(msg):
    """Req 1 + 5 — every variant returns a Messenger delivery-channel
    answer mentioning the current chat / Messenger."""
    out = _delivery(msg, "messenger")
    assert out is not None, f"no delivery answer for: {msg!r}"
    assert "Messenger" in out
    assert "ბილეთის ბმულს" in out  # the canonical delivery answer body


@pytest.mark.parametrize("msg", _DELIVERY_INPUTS)
def test_fix1_no_variant_gets_forbidden_redirect(msg):
    """Req 2 — neither the delivery handler nor (on its fallthrough) the
    off-topic guard ever emits the forbidden redirect for these inputs."""
    out = _delivery(msg, "messenger")
    assert out is not None and _FORBIDDEN not in out
    # Defence-in-depth: even if the delivery handler were bypassed, the
    # off-topic guard must not redirect (notification stems are in-scope).
    conv = Conversation(sender_id="s", platform="messenger", segment="ADULT")
    guard = _offtopic(msg, conv)
    assert guard is None or _FORBIDDEN not in guard


def test_fix1_a1_reversed_order_no_longer_redirected():
    """A-1 regression — the exact reversed-order input that produced the
    forbidden redirect now gets a delivery answer."""
    conv = Conversation(sender_id="s", platform="messenger", segment="ADULT")
    msg = "შეტყობინება სად მომივა?"
    assert _delivery(msg, "messenger") is not None
    # off-topic guard must not fire on it either (in-scope stem present).
    assert _offtopic(msg, conv) is None


def test_fix1_messenger_answer_mentions_current_chat():
    """Req 5 — Messenger answer says it arrives here, in this chat."""
    out = _delivery("შეტყობინება სად მომივა?", "messenger")
    assert "Messenger" in out
    assert "ამავე ჩატში" in out


def test_fix1_instagram_answer_is_instagram_direct():
    """Req 6 — Instagram answer says Instagram Direct (პირად შეტყობინებაში)."""
    out = _delivery("შეტყობინება სად მომივა?", "instagram")
    assert "Instagram" in out
    assert "Messenger" not in out
    assert "პირად შეტყობინებაში" in out  # = Instagram Direct (ka)


def test_fix1_does_not_hijack_price_location_or_consent():
    """Narrowness guard — price / location / subscription-consent messages
    must NOT be intercepted as delivery questions."""
    for msg in (
        "ბილეთის ფასი რა არის?",       # price → tools/LLM
        "სად ტარდება ღონისძიება?",      # location → tools/LLM
        "ბილეთი სად ვიყიდო?",           # purchase location
        "კი გამომიგზავნეთ",             # subscription consent
        "შემატყობინეთ",                 # subscription consent (imperative)
        "კი მინდა",                     # bare consent
    ):
        assert _delivery(msg, "messenger") is None, f"hijacked: {msg!r}"


def _run_turn(conv, msg, monkeypatch, *, platform="messenger"):
    """Drive run_adult_llm_turn with the LLM, subscription write, and
    broadcast all guarded so we can prove they are NOT reached."""
    from app.services import (
        adult_subscription_service,
        openai_service,
    )
    import app.services.adult_event_broadcast_service as broadcast_service

    calls = {"llm": False, "subscribe": False, "broadcast": False}

    def _boom_llm(*a, **k):
        calls["llm"] = True
        raise AssertionError("LLM must not be reached for a delivery question")

    monkeypatch.setattr(openai_service, "chat_with_tools", _boom_llm)
    monkeypatch.setattr(
        adult_subscription_service, "subscribe",
        lambda **k: calls.__setitem__("subscribe", True) or {"success": True},
    )
    monkeypatch.setattr(
        broadcast_service, "broadcast_event",
        lambda *a, **k: calls.__setitem__("broadcast", True) or {"dry_run": True},
    )
    out = _ae.run_adult_llm_turn(
        user_message=msg, conversation=conv, lead=conv.lead,
        sender_id=conv.sender_id, platform=platform,
    )
    return out, calls


def test_fix1_already_subscribed_no_duplicate_no_broadcast(monkeypatch):
    """Req 3 + 4 + 7 — for an already-subscribed user, a pure delivery
    question answers deterministically: no duplicate subscribe write, no
    broadcast, LLM never reached."""
    conv = Conversation(sender_id="s_sub", platform="messenger", segment="ADULT")
    conv.lead = Lead(sender_id="s_sub", platform="messenger", segment="ADULT")
    conv.adult_subscription_status = "subscribed"
    out, calls = _run_turn(conv, "შეტყობინება სად მომივა?", monkeypatch)
    assert "Messenger" in out
    assert _FORBIDDEN not in out
    assert calls["subscribe"] is False
    assert calls["broadcast"] is False
    assert calls["llm"] is False


def test_fix1_unsubscribed_delivery_question_no_write(monkeypatch):
    """Req 4 — a delivery question never triggers the subscription write
    path even when the user is not yet subscribed."""
    conv = Conversation(sender_id="s_new", platform="messenger", segment="ADULT")
    conv.lead = Lead(sender_id="s_new", platform="messenger", segment="ADULT")
    out, calls = _run_turn(conv, "სად ვნახავ შეტყობინებას?", monkeypatch)
    assert "Messenger" in out
    assert calls["subscribe"] is False
    assert calls["broadcast"] is False


def test_fix1_live_broadcast_disabled_default():
    """Req 7 (config) — the broadcast master switch stays off."""
    from app.config import settings
    assert getattr(settings, "LIVE_BROADCAST_ENABLED", False) is False


# ===========================================================================
# FIX 2 — B-1 — dative child-relation capture („ჩემ შვილს", „ბავშვს")
# ===========================================================================

from app.agent.llm.adult_llm_engine import _maybe_capture_adult_target
from app.services import admin_config_service


def _adult_lead(*, sender_id="s_adult", platform="messenger", child_age=""):
    lead = Lead(sender_id=sender_id, platform=platform, segment="ADULT")
    lead.child_age = child_age
    return lead


def test_fix2_dative_shvils_reuses_known_age_15():
    """Req 1 — child_age=15 + „ჩემ შვილს უნდა" → relation + reuse 15."""
    lead = _adult_lead(child_age="15")
    _maybe_capture_adult_target("ჩემ შვილს უნდა", lead)
    assert lead.adult_target_relation == "შვილი"
    assert lead.adult_target_age == "15"
    assert lead.child_age == "15"  # untouched


def test_fix2_dative_bavshvs_reuses_known_age_17():
    """Req 2 — child_age=17 + „ბავშვს უნდა" → relation + reuse 17."""
    lead = _adult_lead(child_age="17")
    _maybe_capture_adult_target("ბავშვს უნდა", lead)
    assert lead.adult_target_relation == "ბავშვი"
    assert lead.adult_target_age == "17"


def test_fix2_dative_age_12_hides_ineligible_events():
    """Req 3 — child_age=12 + dative → target_age=12 → no 13+ events
    surface (the executor's age filter uses adult_target_age)."""
    lead = _adult_lead(child_age="12")
    _maybe_capture_adult_target("ჩემ შვილს უნდა", lead)
    assert lead.adult_target_age == "12"
    events = admin_config_service.get_active_adult_events(
        int(lead.adult_target_age)
    )
    # No event the 12-year-old is too young for may be returned.
    for e in events:
        assert int(e.get("min_age") or 0) <= 12


def test_fix2_dative_unknown_age_does_not_invent_age():
    """Req 4 — child_age unknown + „ბავშვს უნდა" → relation captured but
    target_age stays empty so the flow asks for the age."""
    lead = _adult_lead(child_age="")
    _maybe_capture_adult_target("ბავშვს უნდა", lead)
    assert lead.adult_target_relation == "ბავშვი"
    assert (lead.adult_target_age or "") == ""


def test_fix2_inline_age_genitive_still_captured():
    """Req 5 — „ჩემი 17 წლის შვილისთვის" → target_age=17 (inline wins,
    even over a stale stored child_age)."""
    lead = _adult_lead(child_age="12")
    _maybe_capture_adult_target("ჩემი 17 წლის შვილისთვის", lead)
    assert lead.adult_target_relation == "შვილი"
    assert lead.adult_target_age == "17"


def test_fix2_inline_age_dative_overrides_stored():
    """Dative + inline age: „ჩემ 14 წლის შვილს უნდა" → target_age=14."""
    lead = _adult_lead(child_age="9")
    _maybe_capture_adult_target("ჩემ 14 წლის შვილს უნდა", lead)
    assert lead.adult_target_relation == "შვილი"
    assert lead.adult_target_age == "14"


def test_fix2_dative_does_not_overwrite_parent_child_age():
    """The dative capture copies into adult_target_age; child_age and
    adult_age are never mutated."""
    lead = _adult_lead(child_age="15")
    lead.adult_age = "40"
    _maybe_capture_adult_target("ჩემ შვილს უნდა", lead)
    assert lead.child_age == "15"
    assert lead.adult_age == "40"
    assert lead.adult_target_age == "15"


def test_fix2_genitive_forms_still_work():
    """Regression — the existing genitive captures are unaffected by the
    dative additions (the dative needles never shadow them)."""
    for msg, rel in (
        ("ჩემი შვილისთვის", "შვილი"),
        ("ბავშვისთვის მინდა", "ბავშვი"),
        ("შვილისთვის მაინტერესებს", "შვილი"),
    ):
        lead = _adult_lead(child_age="13")
        _maybe_capture_adult_target(msg, lead)
        assert lead.adult_target_relation == rel
        assert lead.adult_target_age == "13"


def test_fix2_other_child_dative_not_reused():
    """„სხვა შვილს" (a DIFFERENT child) must NOT reuse the stored age —
    the new child's age has to be asked."""
    lead = _adult_lead(child_age="12")
    _maybe_capture_adult_target("სხვა შვილს უნდა", lead)
    assert (lead.adult_target_age or "") == ""


def test_fix2_cross_sender_platform_isolation():
    """Req 6 — separate sender_id / platform leads capture independently;
    no leak between them."""
    a = _adult_lead(sender_id="A", platform="messenger", child_age="15")
    b = _adult_lead(sender_id="B", platform="instagram", child_age="9")
    c = _adult_lead(sender_id="C", platform="messenger", child_age="")
    _maybe_capture_adult_target("ჩემ შვილს უნდა", a)
    _maybe_capture_adult_target("ბავშვს უნდა", b)
    _maybe_capture_adult_target("ბავშვს უნდა", c)
    assert a.adult_target_age == "15"
    assert b.adult_target_age == "9"
    assert (c.adult_target_age or "") == ""


# ===========================================================================
# FIX 3 — F-D4 — bare-phone capture no longer brand-marker-only
# ===========================================================================

from app.flows.parent_flow import (
    _maybe_handle_contact_collection,
    _bot_recently_asked_for_contact,
)


def _parent_conv(bot_text, *, name="ნინო", child_age="14", phone=""):
    conv = Conversation(sender_id="p_sender", platform="instagram")
    conv.segment = "PARENT"
    conv.state = "ASK_NAME"
    conv.history = [{"role": "assistant", "content": bot_text}]
    lead = Lead(sender_id="p_sender", platform="instagram", segment="PARENT")
    lead.name = name
    lead.child_age = child_age
    lead.phone = phone
    conv.lead = lead
    return conv, lead


def test_fix3_non_brand_marker_momwere_nomeri_captures():
    """Req 1 — bot asked „მომწერეთ ნომერი" (no brand marker) + bare phone
    → phone captured deterministically."""
    conv, lead = _parent_conv("მომწერეთ ნომერი", phone="")
    assert _bot_recently_asked_for_contact(conv) is True
    reply = _maybe_handle_contact_collection(conv, "595999733")
    assert lead.phone == "595999733"
    assert reply is not None and "ნომერი მივიღე" in reply


def test_fix3_non_brand_marker_how_to_reach_you_captures():
    """Req 2 — bot asked „როგორ დაგიკავშირდეთ?" + bare phone → captured."""
    conv, lead = _parent_conv("როგორ დაგიკავშირდეთ?", phone="")
    assert _bot_recently_asked_for_contact(conv) is True
    reply = _maybe_handle_contact_collection(conv, "595999733")
    assert lead.phone == "595999733"
    assert reply is not None


def test_fix3_telephone_and_contact_info_wordings_capture():
    """Other non-brand contact-ask wordings also arm the capture."""
    for bot in ("მომწერეთ თქვენი ტელეფონი", "გთხოვთ საკონტაქტო ინფორმაცია"):
        conv, lead = _parent_conv(bot, phone="")
        reply = _maybe_handle_contact_collection(conv, "595999733")
        assert lead.phone == "595999733", bot
        assert reply is not None, bot


def test_fix3_no_contact_context_does_not_capture():
    """Req 3 — last bot turn was NOT a contact ask → a bare phone is NOT
    captured and no contact/booking flow starts (returns None)."""
    for bot in (
        "ბანაკი ტარდება კაჭრეთში, ფასი 2150 ლარია.",
        "თქვენი შვილი რამდენი წლისაა?",
        "გასაგებია, კარგი დღე გისურვებთ.",
    ):
        conv, lead = _parent_conv(bot, name="", child_age="14", phone="")
        assert _bot_recently_asked_for_contact(conv) is False, bot
        reply = _maybe_handle_contact_collection(conv, "595999733")
        assert reply is None, bot
        assert (lead.phone or "") == "", bot


def test_fix3_booking_confirmation_is_not_a_contact_ask():
    """A booking confirmation („მენეჯერი დაგიკავშირდებათ", -ებათ future
    form) must NOT be mistaken for a contact request — the broadened
    marker matches only the optative question form (-ეთ)."""
    conv, lead = _parent_conv(
        "კონსულტაცია ჩაგინიშნეთ. მენეჯერი დაგიკავშირდებათ.",
        name="ნინო", child_age="14", phone="",
    )
    assert _bot_recently_asked_for_contact(conv) is False
    reply = _maybe_handle_contact_collection(conv, "595999733")
    assert reply is None
    assert (lead.phone or "") == ""


def test_fix3_brand_marker_still_works():
    """Req 4 — the original brand-marker capture path stays intact."""
    conv, lead = _parent_conv(
        "მომწერეთ თქვენი სახელი და 9-ნიშნა საკონტაქტო ნომერი, "
        "რომ კონსულტაცია ჩავნიშნოთ.",
        name="ნინო", child_age="14", phone="",
    )
    reply = _maybe_handle_contact_collection(conv, "595999733")
    assert lead.phone == "595999733"
    assert reply is not None and "ნომერი მივიღე" in reply


def test_fix3_pending_booking_still_arms_without_marker():
    """An active pending_booking still arms contact capture even when the
    last bot turn carries no marker at all (the `in_contact_ctx` OR)."""
    conv, lead = _parent_conv("გასაგებია.", name="ნინო", child_age="14", phone="")
    conv.pending_booking = {"missing_fields": ["phone"]}
    reply = _maybe_handle_contact_collection(conv, "595999733")
    assert lead.phone == "595999733"
    assert reply is not None


# ===========================================================================
# FIX 4 — F-D6 — explicit consultation intent + inline phone
# ===========================================================================

from app.flows.parent_flow import (
    _maybe_request_full_contact_on_intent,
    _is_explicit_consultation_request,
    _parse_name_phone,
)


def _eligible_conv(*, name="", phone="", child_age="14"):
    conv = Conversation(sender_id="intent_sender", platform="instagram")
    conv.segment = "PARENT"
    conv.state = "ASK_NAME"
    lead = Lead(sender_id="intent_sender", platform="instagram", segment="PARENT")
    lead.name = name
    lead.phone = phone
    lead.child_age = child_age  # eligible (9–17)
    conv.lead = lead
    return conv, lead


_FIX4_INPUTS = [
    "კონსულტაცია მინდა 595999733",
    "ჩამწერეთ 595999733",
    "მინდა 😊 595999733 კონსულტაცია",
    "კი მინდა კონსულტაცია 595999733",
    "დამირეკეთ 595999733",
    "მინდა ჩაწერა 595999733",
]


@pytest.mark.parametrize("msg", _FIX4_INPUTS)
def test_fix4_inline_phone_captured_and_only_name_asked(msg):
    """Req 1/2/3 — the inline phone is captured and, with the name still
    missing, only the name is asked — the phone is NEVER re-requested."""
    conv, lead = _eligible_conv(name="", child_age="14")
    reply = _maybe_request_full_contact_on_intent(conv, msg)
    assert lead.phone == "595999733", msg
    assert reply is not None, msg
    assert "სახელი" in reply, msg               # asks for the name
    # never re-asks the phone (no „9-ნიშნა … ნომერი" request wording)
    assert "9-ნიშნა" not in reply, msg


def test_fix4_known_name_proceeds_to_time():
    """Req 4 — known name + „კონსულტაცია მინდა 595999733" → phone captured,
    proceeds to date/time selection (never re-asks the phone)."""
    conv, lead = _eligible_conv(name="გიორგი", child_age="14")
    reply = _maybe_request_full_contact_on_intent(
        conv, "კონსულტაცია მინდა 595999733",
    )
    assert lead.phone == "595999733"
    assert reply is not None
    assert "დრო" in reply                        # asks the preferred day/time
    assert "9-ნიშნა" not in reply                # phone not re-asked


def test_fix4_no_garbage_name_saved():
    """Req 6 — „დამირეკეთ" (a booking verb) is never stored as the name."""
    conv, lead = _eligible_conv(name="", child_age="14")
    _maybe_request_full_contact_on_intent(conv, "დამირეკეთ 595999733")
    assert lead.phone == "595999733"
    assert (lead.name or "") == ""
    # the parser itself rejects it as a name now
    name, phone = _parse_name_phone("დამირეკეთ 595999733")
    assert name == ""
    assert phone == "595999733"


def test_fix4_no_stale_or_random_booking():
    """Req 5 — the handler asks for contact/time; it never books or echoes
    a stale-booking confirmation, and the lead is not marked booked."""
    conv, lead = _eligible_conv(name="გიორგი", child_age="14")
    reply = _maybe_request_full_contact_on_intent(
        conv, "კონსულტაცია მინდა 595999733",
    )
    assert "ჩაგინიშნეთ" not in (reply or "")     # no booking confirmation
    assert "ძალიან ახლოს" not in (reply or "")    # no time-path rejection
    assert lead.calendly_booked is False
    assert (lead.booked_datetime_iso or "") == ""


def test_fix4_inline_name_and_phone_both_captured():
    """A clearly-disclosed inline name + phone are both captured; the reply
    thanks by name and asks for the time."""
    conv, lead = _eligible_conv(name="", child_age="14")
    reply = _maybe_request_full_contact_on_intent(conv, "ჩამწერეთ გიორგი 595999733")
    assert lead.phone == "595999733"
    assert lead.name == "გიორგი"
    assert reply is not None
    assert "გიორგი" in reply and "დრო" in reply


def test_fix4_two_numbers_ask_which_one():
    """Two distinct inline numbers → ask which one (never silently pick)."""
    conv, lead = _eligible_conv(name="გიორგი", child_age="14")
    reply = _maybe_request_full_contact_on_intent(
        conv, "კონსულტაცია მინდა 595999733 ან 595999734",
    )
    assert reply is not None
    assert "ორი ნომერი" in reply
    assert (lead.phone or "") == ""              # nothing saved yet


def test_fix4_no_phone_existing_complete_ask_unchanged():
    """Req 7 — the no-inline-phone path is unchanged: an explicit request
    with the contact missing asks for the COMPLETE name + phone."""
    conv, lead = _eligible_conv(name="", child_age="14")
    reply = _maybe_request_full_contact_on_intent(conv, "კი მინდა")
    assert reply == (
        "მომწერეთ თქვენი სახელი და საკონტაქტო ნომერი, "
        "რომ კონსულტაცია ჩავნიშნოთ."
    )


def test_fix4_negation_not_treated_as_request():
    """„კონსულტაცია არ მინდა" (decline) must NOT be an explicit request."""
    assert _is_explicit_consultation_request("კონსულტაცია არ მინდა") is False


def test_fix4_ineligible_age_defers():
    """Unknown/ineligible age still defers (qualification owns that turn);
    the inline-phone capture never overrides the eligibility gate."""
    conv, lead = _eligible_conv(name="", phone="", child_age="")  # age unknown
    reply = _maybe_request_full_contact_on_intent(
        conv, "კონსულტაცია მინდა 595999733",
    )
    assert reply is None
    assert (lead.phone or "") == ""              # no capture before qualifying
