"""COMMENT FLOW PATCH 3 — rich DM transcript replay.

Five scenarios verify the patch:

  * A: PARENT INTERESTED → rich DM with camp facts (location, price,
       stream dates, registration URL) loaded from camp_2026.yaml.
  * B: ADULT INTERESTED + events configured → rich DM listing
       event name / date / location / price with 📅 📍 💰 markers.
  * C: ADULT INTERESTED + no events configured → no-events fallback.
  * D: camp_2026.yaml load failure → safe PARENT fallback text,
       no crash.
  * E: ENABLE_PUBLIC_COMMENT_REPLY=true + PARENT → public reply
       sent with the uniform PATCH 3 text AND rich DM still
       delivered through the private-reply channel.

Run::

    python tools/manual_simulation_comment_rich_dm.py
"""

from __future__ import annotations

import asyncio
import dataclasses
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import app.config as config_module  # noqa: E402
from app.routes import webhook  # noqa: E402
from app.services import (  # noqa: E402
    comment_service,
    conversation_service,
    sheets_service,
)


def _swap_settings(**overrides):
    """Patch the live settings + every imported copy."""
    swapped = dataclasses.replace(config_module.settings, **overrides)
    config_module.settings = swapped
    comment_service.settings = swapped
    webhook.settings = swapped
    return swapped


class _FakeResp:
    def __init__(self, *, payload=None, is_success=True, status_code=200, text=""):
        self.is_success = is_success
        self.status_code = status_code
        self.text = text
        self._payload = payload or {}

    def json(self):
        return self._payload


class _Client:
    def __init__(self, *, get_payload=None, post_response=None):
        self.posts: list[tuple[str, dict[str, Any]]] = []
        self.gets: list[tuple[str, dict[str, Any]]] = []
        self._get = _FakeResp(payload=get_payload or {"caption": ""})
        self._post = post_response or _FakeResp()

    def __call__(self, *args, **kwargs):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def post(self, url, headers=None, json=None):
        self.posts.append((url, json or {}))
        return self._post

    async def get(self, url, params=None):
        self.gets.append((url, params or {}))
        return self._get


def _wire(*, caption: str, post_payload: dict | None = None,
          private_reply_success: bool = True):
    """Set up mocks for one scenario. Returns (client, sent, sheets)."""
    conversation_service.conversations.clear()
    comment_service.post_content_cache.clear()

    async def _intent(_text):
        return "INTERESTED"

    comment_service.detect_comment_intent = _intent

    payload = post_payload or {"caption": caption, "message": caption}
    client = _Client(get_payload=payload)
    comment_service.httpx = SimpleNamespace(AsyncClient=client)

    sent: list[dict[str, Any]] = []
    saved: list[dict[str, Any]] = []

    def send_message(sender_id, platform, text):
        sent.append({
            "channel": "send_message",
            "sender_id": sender_id,
            "platform": platform,
            "text": text,
        })
        return True

    def send_private_reply(comment_id, text):
        sent.append({
            "channel": "private_reply",
            "comment_id": comment_id,
            "text": text,
        })
        return bool(private_reply_success)

    comment_service.messenger_service = SimpleNamespace(
        send_message=send_message,
        send_private_reply=send_private_reply,
    )
    sheets_service.save_comment = lambda row: saved.append(dict(row)) or True
    webhook.sheets_service = SimpleNamespace(save_comment=sheets_service.save_comment)
    return client, sent, saved


def fail(label, msg):
    print(f"❌ {label}: {msg}")
    raise SystemExit(1)


def ok(label):
    print(f"✅ {label}")


def run_handle_comment(*, comment_id, platform, caption,
                       private_reply_success: bool = True,
                       hashtags_segment="PARENT"):
    if hashtags_segment == "PARENT":
        _swap_settings(
            PARENT_HASHTAGS=["banaki"],
            ADULT_HASHTAGS=[],
            ENABLE_PUBLIC_COMMENT_REPLY=False,
        )
    else:
        _swap_settings(
            PARENT_HASHTAGS=[],
            ADULT_HASHTAGS=["ღონისძიება"],
            ENABLE_PUBLIC_COMMENT_REPLY=False,
        )
    client, sent, saved = _wire(
        caption=caption, private_reply_success=private_reply_success,
    )
    asyncio.run(
        webhook.handle_comment(
            comment_id=comment_id, post_id="p1", sender_id="user_sim",
            user_name="ნინო", comment_text="მაინტერესებს",
            platform=platform,
        ),
    )
    return client, sent, saved


# =========================================================================
# A — PARENT INTERESTED → rich DM with camp facts
# =========================================================================


print("\n################ A — PARENT rich DM with camp facts ################")
client, sent, _saved = run_handle_comment(
    comment_id="cA", platform="facebook", caption="#banaki",
    hashtags_segment="PARENT",
)
if len(sent) != 1:
    fail("A", f"expected 1 outbound message, got {len(sent)}")
if sent[0]["channel"] != "private_reply":
    fail("A", f"expected private_reply channel, got {sent[0]['channel']!r}")

text = sent[0]["text"]
print("---\nBOT (private reply):")
print(text)
print("---")

for needle, label in (
    ("ამბასადორ კაჭრეთ", "location (locative)"),
    ("2150", "price"),
    ("ლარი", "currency suffix"),
    ("https://", "registration URL"),
    ("ნაკადები:", "stream list header"),
):
    if needle not in text:
        fail("A", f"missing {label}: {needle!r}")
# At least one stream date.
if not any(m in text for m in ("ივნისი", "ივლისი")):
    fail("A", "expected at least one stream date")
ok("A: PARENT rich DM contains location / price / streams / URL")


# =========================================================================
# B — ADULT INTERESTED + events configured → rich DM with events
# =========================================================================


print("\n################ B — ADULT rich DM with events ################")
events = (
    "=== EVENT 1 ===\n"
    "სახელი: კამერული მუსიკის საღამო\n"
    "თარიღი: 20 ივნისი\n"
    "დრო: 19:30\n"
    "ლოკაცია: Stamba Lounge\n"
    "ფასი: 150\n"
)
_swap_settings(EVENTS=events)
client, sent, _saved = run_handle_comment(
    comment_id="cB", platform="facebook", caption="#ღონისძიება",
    hashtags_segment="ADULT",
)
# `_wire` resets `_swap_settings` to defaults for the segment — reapply.
_swap_settings(EVENTS=events)
# Re-run because the previous run might have used empty EVENTS already
# settled at the helper call. Cleaner: just inspect the second-pass.
client, sent, _saved = run_handle_comment(
    comment_id="cB", platform="facebook", caption="#ღონისძიება",
    hashtags_segment="ADULT",
)

text = sent[0]["text"]
print("---\nBOT (private reply):")
print(text)
print("---")
for needle in ("კამერული მუსიკის საღამო", "20 ივნისი", "Stamba Lounge", "150"):
    if needle not in text:
        fail("B", f"missing event fact {needle!r}")
for marker in ("📅", "📍", "💰"):
    if marker not in text:
        fail("B", f"missing emoji marker {marker!r}")
ok("B: ADULT rich DM lists event with date / location / price markers")


# =========================================================================
# C — ADULT INTERESTED + no events → fallback
# =========================================================================


print("\n################ C — ADULT no events fallback ################")
_swap_settings(EVENTS="")
client, sent, _saved = run_handle_comment(
    comment_id="cC", platform="facebook", caption="#ღონისძიება",
    hashtags_segment="ADULT",
)
text = sent[0]["text"]
print("---\nBOT (private reply):")
print(text)
print("---")
if text != comment_service.ADULT_NO_EVENTS_DM:
    fail("C", f"expected fallback text, got: {text!r}")
ok("C: ADULT no-events fallback used")


# =========================================================================
# D — camp_2026.yaml load failure → safe PARENT fallback
# =========================================================================


print("\n################ D — PARENT YAML load failure → fallback ################")
real_loader = comment_service.load_knowledge


def _boom(_name):
    raise RuntimeError("simulated yaml load failure")


try:
    comment_service.load_knowledge = _boom
    client, sent, _saved = run_handle_comment(
        comment_id="cD", platform="facebook", caption="#banaki",
        hashtags_segment="PARENT",
    )
    text = sent[0]["text"]
    print("---\nBOT (private reply):")
    print(text)
    print("---")
    if text != comment_service.PARENT_FIRST_CONTACT_DM:
        fail("D", f"expected fallback, got: {text!r}")
finally:
    comment_service.load_knowledge = real_loader
ok("D: YAML load failure produced PARENT_FIRST_CONTACT_DM safe fallback (no crash)")


# =========================================================================
# E — public reply enabled + PARENT → both channels fire
# =========================================================================


print("\n################ E — public reply + PARENT rich DM together ################")
_swap_settings(
    PARENT_HASHTAGS=["banaki"],
    ADULT_HASHTAGS=[],
    ENABLE_PUBLIC_COMMENT_REPLY=True,
)
client, sent, _saved = _wire(caption="#banaki")
asyncio.run(
    webhook.handle_comment(
        comment_id="cE", post_id="p1", sender_id="user_E",
        user_name="ანი", comment_text="მაინტერესებს",
        platform="facebook",
    ),
)

# Public reply: exactly one POST to /replies with the uniform PATCH 3 text.
public_post = next((p for p in client.posts if "/replies" in p[0]), None)
if public_post is None:
    fail("E", "public reply POST not found")
public_text = (public_post[1] or {}).get("message", "")
expected_public = "გამარჯობა 🌿 დეტალები პირად შეტყობინებაში გამოგიგზავნეთ."
print(f"PUBLIC REPLY: {public_text!r}")
if public_text != expected_public:
    fail("E", f"public reply text mismatch: {public_text!r}")

# Rich DM (private reply): camp facts present.
if len(sent) != 1:
    fail("E", f"expected 1 DM, got {len(sent)}")
if sent[0]["channel"] != "private_reply":
    fail("E", f"DM channel wrong: {sent[0]['channel']!r}")
if "2150" not in sent[0]["text"]:
    fail("E", "rich DM missing price")
print(f"DM text (head): {sent[0]['text'][:100]!r}")
ok("E: public reply + rich private reply both delivered correctly")


print("\n=== PATCH 3 simulation summary ===")
print("A: PARENT rich DM with camp facts:        PASS")
print("B: ADULT rich DM with events:             PASS")
print("C: ADULT no-events fallback:              PASS")
print("D: YAML load failure → safe fallback:     PASS")
print("E: public reply + rich DM both delivered: PASS")
print("✅ All COMMENT FLOW PATCH 3 simulation checks passed")
