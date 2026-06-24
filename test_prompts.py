from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path
from string import Formatter

from dotenv import load_dotenv
from openai import OpenAI

from data import prompts

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini").strip() or "gpt-4.1-mini"
REVIEW_OUTPUT_PATH = BASE_DIR / "prompts_review.txt"

TEST_VARIABLES = {
    "company_name": "ცისარტყელა",
    "age": "8",
    "calendar_slots": (
        "1️⃣ 15 მაისი - 14:00\n"
        "2️⃣ 15 მაისი - 16:00\n"
        "3️⃣ 16 მაისი - 11:00\n\n"
        "გთხოვთ აირჩიოთ ნომერი (1, 2 ან 3)"
    ),
    "date": "15 მაისი",
    "time": "14:00",
    "followup_link": "https://example.com/material",
    "events_list": (
        "1. პოეზიის საღამო\n"
        "   თარიღი: 15 მაისი\n"
        "   სტუმარი: პოეტი ნინო დარბაისელი\n\n"
        "2. მუსიკის კამერული საღამო\n"
        "   თარიღი: 16 მაისი\n"
        "   სტუმარი: პიანისტი გიორგი ცაგარელი"
    ),
    "event_name": "პოეზიის საღამო",
    "event_date": "15 მაისი, 20:00",
    "event_location": "სასტუმრო Rooms-ის პრემიუმ დარბაზი",
    "event_guests": "პოეტი ნინო დარბაისელი და კამერული მუსიკის დუო",
    "event_description": (
        "დახურული კულტურული შეხვედრა მცირე საზოგადოებისთვის, "
        "სადაც პოეზია ცოცხალ მუსიკას ერწყმის."
    ),
    "booking_link": "https://example.com/booking",
    "name": "ნინო",
    "fallback_link": "https://example.com/info",
    "segment": "PARENT",
    "platform": "instagram",
    "status": "Booked",
    "segment_details": (
        "ბავშვის ასაკი: 8 წელი\n"
        "გამოწვევა: ეკრანდამოკიდებულება\n"
        "კონსულტაცია: 15 მაისი 14:00"
    ),
    "summary": (
        "მომხმარებელი დაინტერესდა ბანაკით, მიიღო ძირითადი ინფორმაცია "
        "და დაჯავშნა უფასო კონსულტაცია."
    ),
    "short_details": "ბავშვი 8 წ. | ეკრანდამოკიდებულება | 15 მაისი 14:00",
}

USER_FACING_PROMPTS: list[tuple[str, str]] = [
    ("PARENT_WELCOME", prompts.PARENT_WELCOME),
    ("PARENT_ASK_CHALLENGE", prompts.PARENT_ASK_CHALLENGE),
    ("PARENT_OFFER_CONSULTATION", prompts.PARENT_OFFER_CONSULTATION),
    ("PARENT_BOOKING_CONFIRMED", prompts.PARENT_BOOKING_CONFIRMED),
    ("PARENT_FOLLOWUP", prompts.PARENT_FOLLOWUP),
    ("ADULT_WELCOME", prompts.ADULT_WELCOME),
    ("ADULT_EVENT_DETAILS", prompts.ADULT_EVENT_DETAILS),
    ("ADULT_SEND_BOOKING", prompts.ADULT_SEND_BOOKING),
    ("ADULT_FOLLOWUP", prompts.ADULT_FOLLOWUP),
    ("UNCLEAR_ROUTING", prompts.UNCLEAR_ROUTING),
    ("ERROR_MESSAGE", prompts.ERROR_MESSAGE),
    ("COMMENT_REPLY_DM_SENT", prompts.COMMENT_REPLY_DM_SENT),
    ("COMMENT_REPLY_FALLBACK", prompts.COMMENT_REPLY_FALLBACK),
    ("COMMENT_FOLLOWUP_REPLY", prompts.COMMENT_FOLLOWUP_REPLY),
]

REVIEW_INSTRUCTION = (
    "შემოწმე ეს ქართული ტექსტი:\n"
    "1. გრამატიკულად სწორია?\n"
    "2. ბუნებრივად ჟღერს?\n"
    "3. შესაბამისი ტონია გაყიდვების\n"
    "   კონსულტანტისთვის?\n"
    "4. შენიშვნები მქონდა?\n\n"
    "ტექსტი:\n{prompt_text}"
)

SEPARATOR_EQ = "=" * 60
SEPARATOR_DASH = "-" * 60


class _SafeFormatter(Formatter):
    def get_value(self, key, args, kwargs):
        if isinstance(key, str):
            return kwargs.get(key, "{" + key + "}")
        return super().get_value(key, args, kwargs)


_formatter = _SafeFormatter()


def safe_format(template: str) -> str:
    return _formatter.format(template, **TEST_VARIABLES).strip()


def review_block(name: str, formatted: str, review_text: str) -> str:
    lines = [
        SEPARATOR_EQ,
        f"PROMPT NAME: {name}",
        SEPARATOR_EQ,
        "FORMATTED TEXT:",
        formatted,
        "",
        "REVIEW:",
        review_text,
        "",
        SEPARATOR_DASH,
    ]
    return "\n".join(lines)


def review(client: OpenAI, name: str, template: str) -> str:
    formatted = safe_format(template)
    instruction = REVIEW_INSTRUCTION.format(prompt_text=formatted)

    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[{"role": "user", "content": instruction}],
            max_tokens=600,
            temperature=0.3,
        )
        review_text = (response.choices[0].message.content or "").strip()
    except Exception as exc:
        review_text = f"❌ შეფასება ვერ შესრულდა: {exc}"

    block = review_block(name, formatted, review_text)
    print("\n" + block)
    return block


def main() -> int:
    if not OPENAI_API_KEY:
        print("❌ OPENAI_API_KEY არ არის მითითებული .env ფაილში.")
        print("   ჩაამატე და კიდევ სცადე.")
        return 1

    client = OpenAI(api_key=OPENAI_API_KEY)
    total = len(USER_FACING_PROMPTS)
    timestamp = datetime.now().isoformat(timespec="seconds")

    header = (
        f"# Prompt review run — {timestamp}\n"
        f"# Model: {OPENAI_MODEL}\n"
        f"# Prompts reviewed: {total}\n"
    )
    print(header)

    blocks: list[str] = []
    for name, template in USER_FACING_PROMPTS:
        blocks.append(review(client, name, template))

    REVIEW_OUTPUT_PATH.write_text(
        header + "\n" + "\n".join(blocks) + "\n",
        encoding="utf-8",
    )
    print(f"\n✅ ყველა {total} პრომპტი შემოწმდა.")
    print(f"📝 შეფასების ფაილი შენახულია: {REVIEW_OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
