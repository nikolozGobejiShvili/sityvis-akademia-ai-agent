"""The agent invented a limitation on itself (2026-09-06).

Live, answering a question whose first word was mistyped:

    in ='პიროვები რომ მომწეროთ შეგიძლიათ?'      („პირობები" — the terms)
    out='სამწუხაროდ, პირველად მე ვერ დავწერ — ეს არის ჩეთბოტი და შეტყობინებები
         მხოლოდ შემომავალია.

         თუმცა, თუ გსურთ ჩვენი მენეჯერი დაგიკავშირდეთ პირადად, დამიტოვეთ
         თქვენი ნომერი და სიამოვნებით მოგწერენ!'

Three things are wrong. It answered a question nobody asked; it stated a
limitation that does not exist — the agent sends the first DM after a public
comment, and it sends the scheduled follow-ups; and it contradicted itself one
sentence later.

The prompt already forbids the word („AI აგენტი ვარ" — არა „ჩატ-ბოტი"), and the
model wrote „ჩეთბოტი" — a different spelling, so the ban did not apply. Adding
that spelling to the ban would invite the next one. The word was never the
problem: the model had no fact about its own messaging, so it invented one, the
same way it once invented business hours („10:00–17:00") before the real window
travelled with the turn.

So the fix supplies the missing FACT and adds no rule about wording. These tests
pin the fact, not any phrasing of the reply.
"""
import pytest

from app.agent.llm import parent_llm_engine as eng
from app.models.conversation import Conversation
from app.models.lead import Lead

_KEY = "agent_can_message_first="


def _context(platform="messenger"):
    conv = Conversation(sender_id="s", platform=platform, segment="PARENT")
    lead = Lead(sender_id="s", platform=platform, segment="PARENT")
    return eng._build_context_message(conv, lead, "პიროვები რომ მომწეროთ შეგიძლიათ?")


def test_the_turn_states_that_the_agent_can_message_first():
    out = _context()
    assert _KEY in out
    assert f"{_KEY}yes" in out


@pytest.mark.parametrize("platform", ["messenger", "instagram", "whatsapp"])
def test_the_fact_holds_on_every_channel(platform):
    """It is a property of the product, not of one inbox."""
    assert f"{_KEY}yes" in _context(platform)


def test_it_names_what_the_agent_actually_does():
    """A bare „yes" is a claim; the two things it names are real features, so
    the model can reason from them instead of guessing."""
    out = _context()
    line = next(c for c in out.split("; ") if c.startswith(_KEY))
    assert "comment" in line
    assert "follow-up" in line


def test_it_travels_beside_the_other_channel_facts():
    """It belongs with `reply_channel` / `reply_rendering` — the same class of
    fact, added for the same reason (the model had to guess the medium and got
    it wrong)."""
    out = _context()
    parts = out.split("; ")
    idx = [i for i, c in enumerate(parts) if c.startswith("reply_rendering=")]
    assert idx, "reply_rendering must still travel"
    assert parts[idx[0] + 1].startswith(_KEY)


def test_no_banned_wording_was_added():
    """The correction is a fact, not a prohibition. The sanitiser table and the
    prompt's forbidden list must be untouched by this change — a banned string
    is what failed here, since „ჩატ-ბოტი" was already banned and „ჩეთბოტი" was
    written anyway."""
    import io
    from pathlib import Path
    prompt = io.open(
        Path(eng.__file__).resolve().parents[1] / "prompts" / "system_parent_v2.md",
        encoding="utf-8",
    ).read()
    assert "ჩეთბოტი" not in prompt
    assert "ჩეთბოტი" not in str(eng.FORBIDDEN_PHRASE_REPLACEMENTS)
