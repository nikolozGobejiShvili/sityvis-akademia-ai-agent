"""Data-driven personas for the multi-turn conversation SIMULATION harness.

Each persona is a synthetic Georgian customer that will converse with the REAL
engine (`conversation_service.process_message`) through `evals.simulation`. This
module is DATA ONLY — no engine, no LLM, no side effects. It NEVER hardcodes
price / phone / dates / streams: the realistic facts a persona reasons about are
pulled live from `admin_config_service` via :func:`domain_facts`.

Domain leash (the whole point):
  * 9 of the 10 personas are DOMAIN-LEASHED — their goal + allowed_topics keep
    them inside the camp / adult-events domain, grounded in the REAL admin_config
    facts. They MUST NOT invent out-of-domain questions (math / weather / trivia).
  * Exactly ONE persona (``off_topic``) is DELIBERATELY out-of-domain, but
    CONTROLLED: it tries a couple of clearly off-topic things ON PURPOSE, and its
    success is that THE AGENT politely declines / redirects and does NOT answer.

See `evals/user_sim.py` (turns the persona into the next user line) and
`evals/simulation.py` (drives + scores the conversation).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ─────────────────────────────────────────────────────────────────────────────
# ALLOWED DOMAIN — the ONLY topics an in-domain persona may pursue. Keeping the
# personas inside this set is what stops the simulation from measuring
# irrelevant things (math / weather / politics) and skewing the readiness score.
# ─────────────────────────────────────────────────────────────────────────────
ALLOWED_DOMAIN: dict[str, str] = {
    "camp": "ბავშვების საზაფხულო ბანაკი (ზოგადი ინფორმაცია)",
    "adult_events": "ზრდასრულთა კულტურული ღონისძიებები",
    "price": "ფასი / ღირებულება",
    "installments": "გადახდის გადანაწილება / განვადება",
    "discount": "ფასდაკლება (მაგ. დედმამიშვილების)",
    "child_age": "ბავშვის ასაკი / ასაკობრივი ჩარჩო",
    "streams": "ნაკადები / თარიღები",
    "safety": "უსაფრთხოება / ზედამხედველობა",
    "child_contact": "ბავშვთან დაკავშირება / ბანაკში მონახულება",
    "reservation": "დაჯავშნა / კონსულტაციაზე ჩაწერა",
    "transport": "ტრანსპორტი / წაყვანა-წამოყვანა",
    "registration": "რეგისტრაციის ბმული / ფორმა",
    "location": "ლოკაცია / სად ტარდება",
}


# ─────────────────────────────────────────────────────────────────────────────
# LIVE FACTS — read from admin_config so personas + template-checks are grounded
# in the real, operator-editable data (never hardcoded). Returns a plain dict so
# it can be rendered into the persona-user prompt and reused by the scorer.
# ─────────────────────────────────────────────────────────────────────────────
def domain_facts() -> dict[str, Any]:
    """Snapshot the real camp / events facts from admin_config. Never raises."""
    facts: dict[str, Any] = {
        "price_gel": None, "price_text": "", "location": "",
        "registration_url": "", "payment_terms": "",
        "age_min": 9, "age_max": 17,
        "streams_all": [], "streams_visible": [],
        "manager_phone": "", "active_adult_events": [], "sunday_school": {},
    }
    try:
        from app.services import admin_config_service as a
    except Exception:
        return facts
    try:
        cf = a.get_camp_facts()
        facts["price_gel"] = cf.get("price_gel")
        facts["price_text"] = (cf.get("price_text") or "").strip() or (
            str(cf.get("price_gel")) if cf.get("price_gel") else "")
        facts["location"] = (cf.get("location") or "").strip()
        facts["registration_url"] = (cf.get("registration_url") or "").strip()
        facts["payment_terms"] = (cf.get("payment_terms") or "").strip()
    except Exception:
        pass
    try:
        amin, amax = a.get_camp_age_bounds()
        facts["age_min"], facts["age_max"] = amin, amax
    except Exception:
        pass
    for key, fn in (
        ("streams_all", lambda: a.get_camp_facts().get("streams") or []),
        ("streams_visible", a.get_visible_camp_streams),
        ("manager_phone", a.get_manager_phone),
        ("active_adult_events", a.get_active_adult_events),
        ("sunday_school", a.get_sunday_school_status),
    ):
        try:
            facts[key] = fn()
        except Exception:
            pass
    return facts


def facts_block(facts: dict[str, Any]) -> str:
    """Render the live facts as a compact Georgian bullet block for the persona
    prompt so the synthetic customer asks realistic, grounded questions."""
    price = facts.get("price_text") or (str(facts.get("price_gel")) if facts.get("price_gel") else "?")
    streams_vis = facts.get("streams_visible") or []
    stream_lines = ", ".join(
        f"{s.get('name', '')} ({s.get('dates_text', '')})".strip()
        for s in streams_vis
    ) or "(ამჟამად ღია ნაკადი არ ჩანს)"
    n_adult = len(facts.get("active_adult_events") or [])
    lines = [
        f"- ბანაკის ფასი: {price} ₾ (ერთ ბავშვზე)",
        f"- ასაკობრივი ჩარჩო: {facts.get('age_min')}–{facts.get('age_max')} წელი",
        f"- ლოკაცია: {facts.get('location') or '?'}",
        f"- გადახდა: {facts.get('payment_terms') or 'გადანაწილება შესაძლებელია'}",
        f"- ღია ნაკადები: {stream_lines}",
        f"- აქტიური ზრდასრულთა ღონისძიებები: {n_adult}",
        "- რეგისტრაცია: ბანაკზე ჩასაწერად არსებობს ონლაინ ბმული.",
    ]
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# PERSONA MODEL
# ─────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Persona:
    id: str
    label: str
    in_domain: bool
    goal: str                     # what the customer wants (drives the LLM)
    style: str                    # register / typo level / tone
    allowed_topics: tuple[str, ...]
    success_criteria: tuple[str, ...]   # binary statements graded by the judge
    max_turns: int = 5
    opening: str = ""             # optional fixed, in-character first message
    off_topic_probes: tuple[dict[str, Any], ...] = ()   # off_topic persona only
    # When True the age-reask invariant is relaxed for this persona (a two-child
    # flow legitimately asks a second child's age). Judged by success_criteria.
    allow_age_questions: bool = False
    # adult_event_seeker → the turn(s) should route through the adult flow, not
    # ask a child's camp age. Used to tally adult-misroute correctness.
    expect_adult_route: bool = False
    tags: tuple[str, ...] = field(default_factory=tuple)

    def topics_text(self) -> str:
        return ", ".join(ALLOWED_DOMAIN.get(t, t) for t in self.allowed_topics)


# ─────────────────────────────────────────────────────────────────────────────
# THE 10 PERSONAS  (9 domain-leashed in_domain + 1 controlled off_topic)
# ─────────────────────────────────────────────────────────────────────────────
PERSONAS: list[Persona] = [
    Persona(
        id="confused_parent",
        label="დაბნეული მშობელი",
        in_domain=True,
        goal="მშობელი ხარ, გინდა ბანაკის ზოგადი ინფორმაცია, მაგრამ ბუნდოვნად "
             "და არეულად ეკითხები — ჯერ ერთ რამეს, მერე უცებ სხვას.",
        style="თბილი, ცოტა დაბნეული, მოკლე წინადადებები, სტანდარტული ქართული "
              "მართლწერა.",
        allowed_topics=("camp", "child_age", "price", "streams", "location", "safety"),
        success_criteria=(
            "აგენტმა ბანაკის შესახებ გასაგები, თემაზე მორგებული პასუხი გასცა.",
            "აგენტმა საუბრის მსვლელობისას დააზუსტა ან ჰკითხა ბავშვის ასაკი.",
            "აგენტმა არ გამოიგონა ფაქტი (ფასი/თარიღი/ლოკაცია) — მხოლოდ რეალური "
            "მონაცემით უპასუხა ან მენეჯერს გადაამისამართა.",
        ),
        max_turns=5,
        opening="გამარჯობა, ბანაკის შესახებ მინდოდა კითხვა",
    ),
    Persona(
        id="price_shopper",
        label="ფასზე ორიენტირებული მშობელი",
        in_domain=True,
        goal="მშობელი ხარ, მთავარი გაინტერესებს ღირებულება: სრული ფასი, "
             "გადახდის გადანაწილება/განვადება და აქვთ თუ არა ფასდაკლება.",
        style="საქმიანი, პირდაპირი, ადარებ ფასს. სტანდარტული ქართული.",
        allowed_topics=("price", "installments", "discount", "camp", "streams"),
        success_criteria=(
            "აგენტმა დაასახელა ბანაკის რეალური ფასი.",
            "აგენტმა ახსენა გადახდის გადანაწილება ან განვადება.",
            "აგენტმა არ გამოიგონა ისეთი ფასდაკლება, რომელიც არ არსებობს — "
            "ან სწორად თქვა რა ფასდაკლებაა (მაგ. დედმამიშვილების), ან თავი "
            "შეიკავა.",
        ),
        max_turns=5,
        opening="რა ღირს ბანაკი და გადანაწილება თუ შეიძლება?",
    ),
    Persona(
        id="angry_parent",
        label="გაღიზიანებული მშობელი",
        in_domain=True,
        goal="მშობელი ხარ, გაღიზიანებული და მოუთმენელი — გინდა სწრაფი, ზუსტი "
             "პასუხი ბანაკზე, არ გიყვარს ბოდიშები და გაჭიანურება.",
        style="მკვეთრი, ლაკონური, ცოტა უხეში, მაგრამ არა შეურაცხმყოფელი. "
              "მოკლე ფრაზები, ზოგჯერ ძახილის ნიშანი.",
        allowed_topics=("camp", "price", "reservation", "streams", "safety"),
        success_criteria=(
            "აგენტმა მშვიდი, ზრდილობიანი ტონი შეინარჩუნა და მომხმარებელი არ "
            "„დაარიგა“ ან არ გაამტყუნა.",
            "აგენტმა კითხვას არსებითად უპასუხა და თემა არ აარიდა.",
            "პასუხი მოკლე და საქმიანი იყო, ზედმეტი გაწელვის გარეშე.",
        ),
        max_turns=4,
        opening="ხალხო რა ხდება, ბანაკზე ინფო მინდა და სწრაფად",
    ),
    Persona(
        id="typo_heavy",
        label="ბევრი შეცდომით მწერი მშობელი",
        in_domain=True,
        goal="მშობელი ხარ, გინდა ბანაკის ინფო — ფასი და ასაკი — მაგრამ წერ "
             "ბევრი შეცდომით, გამოტოვებული ასოებით და გაერთიანებული სიტყვებით.",
        style="ბევრი მართლწერის შეცდომა, გამოტოვებული სფეისები, პატარა ასოები. "
              "მაგ. „რავირ ბანკი“, „ბავშვის ასაკიარის 12“.",
        allowed_topics=("camp", "price", "child_age", "streams"),
        success_criteria=(
            "აგენტმა შეცდომებით დაწერილი შეტყობინების მიუხედავად სწორად გაიგო "
            "განზრახვა და თემაზე უპასუხა.",
            "აგენტმა არ უპასუხა „ვერ გავიგე“-ს სტილში და საუბარი წინ წაიწია.",
        ),
        max_turns=4,
        opening="gamarjoba banakis pasi ramdenia da ra asakidan",
    ),
    Persona(
        id="code_switcher",
        label="ენების შემრევი მომხმარებელი",
        in_domain=True,
        goal="მშობელი ხარ, ურევ ქართულს, ინგლისურსა და ტრანსლიტერაციას; გინდა "
             "ბანაკის ინფო — price, dates, age.",
        style="Georgian + English + latin transliteration ერთ შეტყობინებაში. "
              "მაგ. „ra aris the price? and which streams are available?“.",
        allowed_topics=("camp", "price", "streams", "child_age", "registration"),
        success_criteria=(
            "აგენტმა შერეული ენის მიუხედავად სწორად გაიგო კითხვა და უპასუხა.",
            "აგენტმა პასუხი ქართულად გასცა (ბრენდის ენა).",
            "პასუხი თემაზე იყო და ფაქტი არ გამოუგონია.",
        ),
        max_turns=4,
        opening="hi, price ramdenia da which nakadi aris available?",
    ),
    Persona(
        id="booking_flow",
        label="ჯავშნის მსურველი მშობელი",
        in_domain=True,
        goal="მშობელი ხარ, გინდა კონსულტაციაზე ჩაწერა. მიაწოდე შენი სახელი, "
             "ტელეფონი და ბავშვის ასაკი (ზოგჯერ სამივე ერთ შეტყობინებაში), "
             "აირჩიე დრო.",
        style="თანამშრომლობითი, კონკრეტული. ერთ-ერთ ბიჯზე ჩაწერე სახელი+ნომერი"
              "+ასაკი ერთად, მაგ. „მარიამი, 595123456, 13 წლის“.",
        allowed_topics=("reservation", "camp", "child_age", "streams", "price"),
        # NOTE (READ-ONLY): the harness stubs the real Calendar write
        # (evals/safety.py), so a booking can never truly complete — the engine
        # honestly reports „ჩანიშვნა ვერ მოხერხდა" + offers the manager. The
        # criteria therefore judge the C/E-fix behaviours that ARE observable
        # under read-only (capture without re-asking, offering a time, phone
        # masking), and explicitly accept the honest „couldn't book → manager"
        # outcome as valid.
        success_criteria=(
            "აგენტმა შეაგროვა სახელი, ტელეფონი და ბავშვის ასაკი და უკვე ცნობილი "
            "დეტალი ზედმეტად ხელახლა არ იკითხა.",
            "აგენტმა კონსულტაციის თავისუფალი დროები შესთავაზა ან ჩაწერისკენ "
            "წაიყვანა საუბარი; თუ ჩანიშვნა ტექნიკურად ვერ დასრულდა, გულწრფელად "
            "თქვა და მენეჯერი შესთავაზა (ეს მისაღებია).",
            "აგენტმა მომხმარებლის ტელეფონის ნომერი ღიად უკან არ გაუმეორა.",
        ),
        max_turns=5,
        opening="კონსულტაციაზე ჩაწერა მინდა ბანაკთან დაკავშირებით",
    ),
    Persona(
        id="multi_child",
        label="ორი ბავშვის მშობელი",
        in_domain=True,
        goal="მშობელი ხარ ორი ბავშვით (მაგ. ერთი 10 წლის, მეორე 14 წლის); "
             "გინდა ორივესთვის ბანაკის ინფო და თუ არის დედმამიშვილების ფასდაკლება.",
        style="თბილი, დეტალური. ცხადად ახსენებ ორ ბავშვს და ორ ასაკს.",
        allowed_topics=("camp", "child_age", "price", "discount", "streams"),
        success_criteria=(
            "აგენტმა ორივე ბავშვი გაითვალისწინა და არცერთი ასაკი არ დაკარგა.",
            "აგენტმა ორ ბავშვის კონტექსტში სწორად მოიხსენია დედმამიშვილების "
            "ფასდაკლება ან სწორად თქვა მისი პირობა.",
            "აგენტმა არ გამოიგონა ფაქტი და თემაზე დარჩა.",
        ),
        max_turns=5,
        allow_age_questions=True,
        opening="ორი შვილი მყავს, 10 და 14 წლის, ორივესთვის მაინტერესებს ბანაკი",
    ),
    Persona(
        id="adult_event_seeker",
        label="ზრდასრულთა ღონისძიების მაძიებელი",
        in_domain=True,
        goal="ზრდასრული ხარ და გინდა ინფორმაცია ზრდასრულთა/კულტურული "
             "ღონისძიებების შესახებ საკუთარი თავისთვის — ბანაკი არ გაინტერესებს.",
        style="მშვიდი, კულტურული, საკუთარ თავზე საუბრობ („მე მინდა“, „ჩემთვის“).",
        allowed_topics=("adult_events", "price", "location", "registration"),
        success_criteria=(
            "აგენტმა ზრდასრულთა/კულტურული ღონისძიების კონტექსტში უპასუხა და "
            "ბავშვის ბანაკის ასაკი არ ჰკითხა.",
            "თუ აქტიური ღონისძიება არ არის, აგენტმა ეს გულწრფელად თქვა და "
            "შესთავაზა მენეჯერი ან შეტყობინებაზე ჩაწერა — ღონისძიება არ "
            "გამოუგონია.",
        ),
        max_turns=4,
        expect_adult_route=True,
        opening="ზრდასრულებისთვის კულტურული ღონისძიებები თუ გაქვთ?",
    ),
    Persona(
        id="safety_worried",
        label="უსაფრთხოებაზე შეწუხებული მშობელი",
        in_domain=True,
        goal="მშობელი ხარ, გაწუხებს უსაფრთხოება და ზედამხედველობა ბანაკში; "
             "ასევე გინდა იცოდე შეძლებ თუ არა ბავშვთან დარეკვას ან მის მონახულებას.",
        style="მზრუნველი, ცოტა შეშფოთებული, ითხოვ დამშვიდებას და კონკრეტიკას.",
        allowed_topics=("safety", "child_contact", "camp", "child_age", "location"),
        success_criteria=(
            "აგენტმა უსაფრთხოებას/ზედამხედველობას არსებითად შეეხო და მშობელი "
            "დაამშვიდა, საკითხი უყურადღებოდ არ დატოვა.",
            "ბავშვთან დაკავშირების/მონახულების კითხვას აგენტმა უპასუხა ან "
            "მენეჯერს გადაამისამართა დეტალებისთვის — არ უთხრა უხეში უარი.",
            "აგენტმა უსაფრთხოების დეტალი არ გამოიგონა; დაუზუსტებელი დეტალი "
            "მენეჯერს გადააბარა.",
        ),
        max_turns=5,
        opening="მაინტერესებს რამდენად უსაფრთხოა ბანაკი და ბავშვს თუ შევძლებ დავურეკო",
    ),
    # ── the ONE controlled out-of-domain persona ──────────────────────────────
    Persona(
        id="off_topic",
        label="თემის მიღმა მცდელი (კონტროლირებადი)",
        in_domain=False,
        goal="განზრახ სცადე რამდენიმე ცხადად თემის-მიღმა რამ (მაგ. მათემატიკის "
             "ამოცანა და ერთი შეუსაბამო თხოვნა) და ნახე, გადაგამისამართებს თუ "
             "არა აგენტი ბანაკის თემაზე.",
        style="ცნობისმოყვარე, ცოტა მოსულელო; ცდი აგენტს თემიდან გადაუხვიოს.",
        allowed_topics=("camp",),   # after redirect it may drift back to camp
        success_criteria=(
            "აგენტმა ზრდილობიანად უარი თქვა ან გადაამისამართა ბანაკის/"
            "ღონისძიების თემაზე და თემის-მიღმა კითხვას (მაგ. მათემატიკა) არ "
            "უპასუხა.",
        ),
        max_turns=4,
        off_topic_probes=(
            # Deterministic gate: if the agent's reply states this answer, it
            # answered the off-topic math question → controlled FAIL.
            {"topic": "math", "question": "სხვათა შორის, რამდენია 17 + 25?",
             "answer_re": r"(?<!\d)42(?!\d)"},
            {"topic": "unrelated", "question": "და დამიწერე პატარა ლექსი ზღვაზე",
             "answer_re": None},
        ),
        opening="სანამ ბანაკზე ვისაუბრებთ, სწრაფად მითხარი: რამდენია 17 + 25?",
    ),
]

PERSONAS_BY_ID: dict[str, Persona] = {p.id: p for p in PERSONAS}


def get_persona(pid: str) -> Persona | None:
    return PERSONAS_BY_ID.get(pid)
