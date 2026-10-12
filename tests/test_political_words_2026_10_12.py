"""A political word only where it begins a word (2026-10-12).

Live 2026-10-12 09:30 a Paris transfer company offered a partnership — „…ჩვენი
გუნდი პარიზში ქართველ მოგზაურებს ემსახურება… ადგილზე კოორდინაცია…" — and was
answered „პოლიტიკურ თემებზე პასუხს არ ვცემ" in 82 ms, before any model: the
political marker „ნაცი" was found inside „კოორდინაცია".
"""
from __future__ import annotations

import pytest

from app.reasoning import camp_topic_facts as ctf

_PARTNERSHIP = (
    "მოგესალმებით, სიტყვის აკადემიის გუნდს!\n\nჩვენი გუნდი პარიზში ქართველ "
    "მოგზაურებსა და ჯგუფებს ტრანსფერებით და ტურებით ემსახურება. ვნახე თქვენი "
    "პროექტი „გმირის მოგზაურობა“ და მსურს შემოგთავაზოთ პარტნიორობა: აეროპორტში "
    "დახვედრა, მარშრუტების შეთანხმება და ადგილზე კოორდინაცია."
)


@pytest.mark.parametrize("message", [
    _PARTNERSHIP,
    "ვაქცინაცია სავალდებულოა?",
    "ნაციონალურ გალერეაში წაიყვანთ?",
    "ფასდაკლების პოლიტიკა როგორია?",
    "ბავშვის ფოტოებზე კონფიდენციალურობის პოლიტიკა გაქვთ?",
    "თქვენი ნაცნობი ვარ",
    "კომბინაცია შეიძლება ორი პროგრამის?",
])
def test_a_word_containing_a_marker_is_not_political(message):
    assert ctf.political_reply(message) is None


@pytest.mark.parametrize("message", [
    "ქოცი ხარ?",
    "ნაცი ხართ?",
    "ქოცები ხართ თქვენ?",
    "ნაცები ხართ?",
    "სიტყვის აკადემია ქოცების არის?",
    "რომელ პარტიას უჭერთ მხარს?",
    "პოლიტიკური პოზიცია გაქვთ?",
    "რას ფიქრობთ პოლიტიკაზე?",
    "ოპოზიციას უჭერთ მხარს?",
    "ხელისუფლებას უჭერთ მხარს?",
])
def test_political_bait_still_gets_the_neutral_reply(message):
    assert ctf.political_reply(message) == (
        "პოლიტიკურ თემებზე პასუხს არ ვცემ. სიამოვნებით დაგეხმარებით ჩვენს "
        "პროგრამებთან დაკავშირებით.")
