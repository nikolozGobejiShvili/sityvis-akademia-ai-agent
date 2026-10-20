"""Instagram, before the Page's Instagram account is subscribed (2026-10-20).

Two facts from Meta's Instagram Messaging documentation that the Messenger
path never had to meet:

* The `messages` webhook field also reports every message the business sends,
  marked `"is_echo": true` (sender = the business account). Messenger only does
  this when `message_echoes` is subscribed, and this app does not subscribe it,
  so the webhook never had to tell the two apart. Read as a parent's message, an
  echo would run a turn for the business account itself.
* „Message text must be UTF-8 and be 1,000 bytes or less." A Georgian letter is
  three bytes in UTF-8, so the 950-character cut let through replies three times
  over the limit, and Meta rejects such a message whole.
"""
from __future__ import annotations

import dataclasses

import app.config as config_module
from app.routes import webhook
from app.services import messenger_service as ms

_SENTENCE = ("საკვირაო სკოლა არის სამთვიანი საგანმანათლებლო პროგრამა, რომელიც "
             "აერთიანებს ლიტერატურისა და ფსიქოლოგიის ინტერაქციულ შეხვედრებს.")


def _georgian(paragraphs: int) -> str:
    return "\n\n".join(f"{i}. {_SENTENCE}" for i in range(paragraphs))


def _payload(obj: str, message: dict, sender: str = "igsid-parent") -> dict:
    return {
        "object": obj,
        "entry": [{
            "id": "17841467177068479",
            "time": 1,
            "messaging": [{
                "sender": {"id": sender},
                "recipient": {"id": "17841467177068479"},
                "timestamp": 1,
                "message": message,
            }],
        }],
    }


# -- echoes ------------------------------------------------------------------

def test_an_instagram_echo_of_the_business_reply_is_not_a_parent_message():
    payload = _payload("instagram", {
        "mid": "m-echo", "text": "მენეჯერი: 599 00 11 20", "is_echo": True,
    }, sender="17841467177068479")
    assert webhook._extract_messages(payload) == []


def test_a_parent_message_on_instagram_still_reaches_the_agent():
    payload = _payload("instagram", {"mid": "m-1", "text": "გამარჯობა"})
    assert webhook._extract_messages(payload) == [{
        "sender_id": "igsid-parent",
        "message_text": "გამარჯობა",
        "platform": "instagram",
        "page_id": "17841467177068479",
        "mid": "m-1",
    }]


def test_a_messenger_message_is_read_as_before():
    payload = _payload("page", {"mid": "m-2", "text": "გამარჯობა"}, sender="psid-1")
    [message] = webhook._extract_messages(payload)
    assert (message["platform"], message["sender_id"], message["message_text"]) == (
        "messenger", "psid-1", "გამარჯობა")


# -- the byte limit ----------------------------------------------------------

def test_instagram_parts_stay_within_a_thousand_bytes_and_lose_nothing():
    text = _georgian(6)
    assert len(text) < 950 < len(text.encode("utf-8"))  # passed the old cut
    parts = ms.split_for_channel(text, 950, max_bytes=ms._BYTE_LIMITS["instagram"])
    assert len(parts) >= 2
    assert all(len(p.encode("utf-8")) <= 1000 for p in parts)
    assert "\n\n".join(parts) == text


def test_no_word_is_cut_when_a_georgian_reply_has_no_paragraphs():
    text = " ".join([_SENTENCE] * 12)
    parts = ms.split_for_channel(text, 950, max_bytes=ms._BYTE_LIMITS["instagram"])
    assert all(len(p.encode("utf-8")) <= 1000 for p in parts)
    assert " ".join(parts).split() == text.split()


def test_a_short_reply_is_one_message_on_instagram():
    assert ms.split_for_channel(_SENTENCE, 950,
                                max_bytes=ms._BYTE_LIMITS["instagram"]) == [_SENTENCE]


def _channel(monkeypatch) -> list[str]:
    sent: list[str] = []

    class _Response:
        is_success = True
        status_code = 200
        text = ""

    def _post(url, headers=None, json=None, timeout=None):
        sent.append(json["message"]["text"])
        return _Response()

    monkeypatch.setattr(ms, "settings", dataclasses.replace(
        config_module.settings, MESSENGER_PAGE_ACCESS_TOKEN="test-page-token"))
    monkeypatch.setattr(ms.httpx, "post", _post)
    monkeypatch.setattr(ms, "sleep", lambda *_: None)
    return sent


def test_an_instagram_reply_goes_out_in_parts_meta_accepts(monkeypatch):
    sent = _channel(monkeypatch)
    text = _georgian(6)
    assert ms.send_message("igsid-parent", "instagram", text) is True
    assert len(sent) >= 2
    assert all(len(p.encode("utf-8")) <= 1000 for p in sent)
    assert "\n\n".join(sent) == text


def test_the_same_reply_is_still_one_message_on_messenger(monkeypatch):
    sent = _channel(monkeypatch)
    text = _georgian(6)
    assert ms.send_message("psid-1", "messenger", text) is True
    assert sent == [text]
