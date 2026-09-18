"""Two replies that any programme's parent can receive named the camp.

Found by sweeping 81 turns (10 multi-turn dialogues + 22 trigger-specific turns)
through the real flow with the camp ended and Sunday School the only programme
on sale — these were the only two deterministic replies left that said „ბანაკი":

  „ბოტივით ნუ მელაპარაკები"      → „…რა გაინტერესებთ — ბანაკის პირობები, ფასი,
                                     ასაკი თუ კონსულტაცია?"
  „ჩემზე რა ინფორმაცია გაქვთ?"   → „…თუ ბანაკთან დაკავშირებით კითხვა გაქვთ…"

Neither is a camp answer: one switches tone, the other reports what is stored.
The fix removes the programme word — no new rule, no forbidden phrase, nothing
added to the sanitiser.
"""
from __future__ import annotations

from app.flows import parent_flow

CAMP_WORDS = ("ბანაკ", "საზაფხულო", "ნაკად")


def test_the_tone_ack_names_no_programme():
    text = parent_flow._HUMAN_TONE_ACK
    assert text, "the ack must still exist"
    assert not [w for w in CAMP_WORDS if w in text], (
        "a tone request is not a camp question: " + text
    )
    # It must still invite the parent's question.
    assert "რა გაინტერესებთ" in text


def test_the_empty_memory_reply_names_no_programme():
    """Rendered by `_maybe_memory_info_reply` when nothing is stored yet."""
    from app.models.conversation import Conversation
    from app.models.lead import Lead

    conv = Conversation(sender_id="mem", platform="messenger")
    conv.segment = "PARENT"
    conv.lead = Lead(sender_id="mem", platform="messenger", segment="PARENT")
    reply = parent_flow._maybe_memory_info_reply(conv, "ჩემზე რა ინფორმაცია გაქვთ?")
    assert reply, "the memory question must still be answered"
    assert not [w for w in CAMP_WORDS if w in reply], (
        "what the agent has stored is not a camp fact: " + reply
    )
