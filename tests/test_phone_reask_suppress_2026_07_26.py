"""BUG-1 fix (2026-07-26 live test): the dynamic booking path confirmed a slot and
then RE-asked for the phone the user had already given. `_suppress_redundant_phone_question`
strips the redundant phone ask when lead.phone is known (mirrors the age anti-repeat guard).
Gated by USE_DYNAMIC_CONTACT_CAPTURE ⇒ OFF is byte-identical. Logic fix (checks lead.phone),
not a blanket ban.
"""
import dataclasses

from app import config
from app.agent.llm import parent_llm_engine as ple
from app.models.conversation import Conversation
from app.models.lead import Lead


def _conv():
    return Conversation(sender_id="s", platform="facebook")


def _lead(phone=""):
    return Lead(sender_id="s", platform="facebook", segment="PARENT", phone=phone)


def _pin(monkeypatch, flag):
    monkeypatch.setattr(
        ple, "settings",
        dataclasses.replace(config.settings, USE_DYNAMIC_CONTACT_CAPTURE=flag),
    )


_SLOT_THEN_PHONE = (
    "27 ივლისს, 17:00 თავისუფალია. მომწერეთ თქვენი საკონტაქტო ნომერი, "
    "რომ კონსულტაცია ჩავნიშნოთ."
)


# --- detector ---

def test_detector_matches_phone_ask():
    assert ple._sentence_is_phone_ask("მომწერეთ თქვენი საკონტაქტო ნომერი")


def test_detector_ignores_confirmation():
    assert not ple._sentence_is_phone_ask("ნომერი მივიღე.")


def test_detector_ignores_manager_callback_mention():
    assert not ple._sentence_is_phone_ask("მენეჯერი დაგიკავშირდებათ თქვენს ნომერზე.")


# --- suppress ---

def test_off_is_byte_identical(monkeypatch):
    _pin(monkeypatch, False)
    out = ple._suppress_redundant_phone_question(_SLOT_THEN_PHONE, _lead("595999733"), _conv())
    assert out == _SLOT_THEN_PHONE


def test_strips_redundant_ask_when_phone_known(monkeypatch):
    _pin(monkeypatch, True)
    out = ple._suppress_redundant_phone_question(_SLOT_THEN_PHONE, _lead("595999733"), _conv())
    assert "თავისუფალია" in out           # slot confirmation kept
    assert "მომწერეთ" not in out           # redundant phone ask gone
    assert "ნომერი" not in out


def test_untouched_when_phone_unknown(monkeypatch):
    _pin(monkeypatch, True)
    out = ple._suppress_redundant_phone_question(_SLOT_THEN_PHONE, _lead(""), _conv())
    assert out == _SLOT_THEN_PHONE         # asking IS correct when phone missing


def test_untouched_when_no_phone_ask(monkeypatch):
    _pin(monkeypatch, True)
    txt = "27 ივლისს, 17:00 თავისუფალია. გთხოვთ, მომწერეთ თქვენი შვილის ასაკი."
    out = ple._suppress_redundant_phone_question(txt, _lead("595999733"), _conv())
    assert out == txt                      # no phone ask → nothing to strip


def test_phone_only_reply_falls_back_to_next_step(monkeypatch):
    _pin(monkeypatch, True)
    out = ple._suppress_redundant_phone_question(
        "მომწერეთ თქვენი საკონტაქტო ნომერი.", _lead("595999733"), _conv(),
    )
    assert out and "მომწერეთ" not in out or "ასაკ" in out or "დღე" in out
