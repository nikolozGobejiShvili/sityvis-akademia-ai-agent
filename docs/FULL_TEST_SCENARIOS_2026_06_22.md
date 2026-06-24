# 🧪 სრული სატესტო სცენარები — სიტყვის აკადემია AI Sales Agent (ხარვეზების გადაფარვა + verification matrix)

**გაშვების თარიღი: 2026-06-22 (ცოცხალი, Asia/Tbilisi). კანონიკური ფაქტები:** ფასი 2150 ლარი · ბავშვის ასაკი 9–17 · ლოკაცია „ამბასადორი კაჭრეთი" · მენეჯერი 558 67 47 33 · რეგისტრაცია https://tinyurl.com/36jcae8z · ნაკადები I 23-29 ივნისი / II 5-11 ივლისი / III 14-20 ივლისი · მოდელი gpt-4.1-mini · PARENT engine ON (`USE_PARENT_LLM_ENGINE=true`) · ADULT engine ON (`USE_ADULT_LLM_ENGINE=true`). დღეს (06-22) I ნაკადი ჯერ კიდევ ჩანს (`today < start`); 06-23-დან იმალება. ჯავშნის დღეები ორშ–შაბ; კვირა დახურულია (`CLOSED_WEEKDAYS={6}`); საათები 10:00–21:00, ბოლო დაწყება 20:00, 60-წთ სლოტი, 2სთ ბუფერი მხოლოდ დღეს.

### როგორ გავუშვათ ეს დოკუმენტი
1. **FLUSHALL Redis** დაწყებამდე და ყოველი ცალკეული სცენარის წინ — ერთი სცენარი = ერთი ახალი საუბარი (წინააღმდეგ შემთხვევაში ძველი სახელი/ასაკი/ტელეფონი/ჯავშანი გაჟონავს და ფანტომურ ბაგებს დაედევნებით).
2. შეტყობინებები გააგზავნე **თითო turn-ზე თითო**, ნაჩვენები რიგით, და დაელოდე ბოტის პასუხს შემდეგის გაგზავნამდე.
3. engine ON უნდა იყოს ორივე flow-ზე (PARENT + ADULT).
4. **✅ PASS** = ბოტი აკეთებს „✅ მოსალოდნელ" ქცევას, ბუნებრივ ქართულზე, ინგლისურის გარეშე, წესების/tool-სახელების გაჟონვის გარეშე, მენიუს ხელახალი გადმოყრის გარეშე, უკვე მოცემული ფაქტის ხელახალი კითხვის გარეშე.
5. **🔴 RED FLAG** = იგონებს ფასს/თარიღს/ბმულს, ცრუ ჯავშანს ადასტურებს, კარგავს ლიდს, აჟონებს ინსტრუქციებს, ან არღვევს კონკრეტული guard-ის კონტრაქტს. ჩაინიშნე სცენარის ID + screenshot.
6. **ტიპები:** 🟢 **MUST PASS** = დეტერმინისტული guard-ი, ცოცხლად უნდა დაიჭიროს — ჩავარდნა რეგრესიაა; 🟡 **PROBE** = LLM-ზე/prompt-ზე დამოკიდებული, შეიძლება ლეგიტიმურად ჩავარდეს — ჩავარდნა მოსალოდნელია, არა რეგრესია.

> **ℹ️ ეს დოკუმენტი აფართოებს `docs/LIVE_TEST_CHECKLIST_2026_06_22.md`-ს.** დეტალური PARENT-flow სკრიპტი (H1–H8, CM/GI/BK/LC/IC/MP კატეგორიები) იქ ცხოვრობს — აქ მათ ID-ით ვუთითებთ და არ ვიმეორებთ. ეს დოკუმენტი ფარავს იმ ქვესისტემებს, რომელსაც PARENT checklist-ი ვერ ფარავს (ADULT flow, comment→DM funnel, PARENT↔ADULT გადართვა, camp-stream date filter, notifications & side-effects, kill switch & admin) + master verification matrix-ს.

---

## ნაწილი 0 — სუსტი წერტილების ვერიფიკაციის მატრიცა (MASTER)

ეს მატრიცა აერთიანებს PARENT flow-ის ყველა სუსტ წერტილს. **🟢-ის და 🟡-ის გასხვავება კრიტიკულია:** 🟢 რიგებში ჩავარდნა = რეგრესია, ესკალაცია; 🟡 რიგებში ჩავარდნა = მოსალოდნელი LLM-ხარვეზი, არა გატეხილი guard.

| სუსტი წერტილი | სცენარ(ებ)ი | ტიპი | მოსალოდნელი ქცევა | guard (file/function) |
|---|---|---|---|---|
| ფასის გასაჩივრება ≠ უარი (contrast marker) | WP-1, ext. H2 | 🟢 MUST PASS | „…არ მინდა, მაგრამ…" → აგრძელებს გაყიდვას + 6-თვიანი განვადება, არ ხურავს ლიდს | `parent_flow._maybe_handle_decline_engine` + `_DECLINE_OVERRIDE_INTEREST` (:3141/:3134) |
| ნამდვილი უარი (contrast-ის გარეშე) | WP-2 | 🟢 MUST PASS | მოკლე თბილი დახურვა; pending_booking იწმინდება | `_maybe_handle_decline_engine` is_decline branch (:3191) |
| ტელეფონის კორექცია | WP-3, ext. H1 | 🟢 MUST PASS | `lead.phone` ბოლო ვალიდურ ნომერზე გადაიწერება; Calendar/Sheets არ ეხება | `_maybe_handle_contact_correction` phone branch (:2551) |
| სახელის კორექცია | WP-4, ext. H5 | 🟢 MUST PASS | `lead.name` შესწორებულ სახელზე გადაიწერება | `_maybe_handle_contact_correction` name branch + `_extract_corrected_name` (:2575/:2519) |
| ასაკი+ტელეფონი ერთ მესიჯში (memory, no re-ask) | WP-5 | 🟢 MUST PASS | ორივე ინახება; ასაკი აღარ იკითხება | `_capture_turn_facts` + `maybe_capture_phone_fallback` + `_suppress_redundant_age_question` (parent_llm_engine.py:1742/288/1683) |
| ნაკლები ასაკის (8) handoff — REAL dispatch | WP-6, ext. MP-7 | 🟢 MUST PASS | კონტაქტზე რეალური notify_manager_handoff; Sheets/Calendar არ ეხება | `_ensure_ineligible_young_age_message` + `_maybe_handle_underage_manager_handoff` (:1942/:2098) |
| ცრუ/უფასო ჯავშანი ვერ დადასტურდება | WP-7, ext. BK-6 | 🟢 MUST PASS | tool-success-ის გარეშე „ჩაგინიშნე"/„დაჯავშნილია" → safe fallback | `_sanitise_booking_confirmation` tool-success gate (:503) |
| მენეჯერის ნომრის გაცემა (558 67 47 33) | WP-8, ext. CM-5 | 🟢 MUST PASS | ცხადად აცხადებს ნომერს + callback | `_maybe_handle_explicit_manager_request` + `_render_manager_number_answer` (:2467/:2438) |
| მენეჯერის ნომერი — phone ცნობილია → არ ხელახ. იკითხება | WP-9 | 🟢 MUST PASS | 558 67 47 33 + „მენეჯერი თავად დაგიკავშირდებათ", ნომერს არ ითხოვს | `_render_manager_number_answer` phone_known branch (:2447) |
| რეგისტრაციის ბმული დეტერმინისტულად (LLM bypass) | WP-10, ext. IC-6 | 🟢 MUST PASS | https://tinyurl.com/36jcae8z ასაკის კითხვის/მენიუს გარეშე | `_maybe_handle_camp_registration_link` + `_render_camp_registration_answer` (:2382/:2347) |
| „ინფორმაცია" არ ააქტიურებს ბმულს (ფორმა boundary) | WP-11, ext. IC-1 | 🟢 MUST PASS | ნორმალური info, არა ბმული | `_CAMP_FORM_TOKEN_RE` (?<![ა-ჰ])ფორმ(?!ატ) (:2314/:2344) |
| ცხადი camp intent ტოვებს მენიუს | WP-12 | 🟢 MUST PASS | აგრძელებს camp flow-ს (ეკითხება ასაკს) | `_has_explicit_georgian_camp_intent` + `_maybe_static_welcome` yield (:2593/:2660) |
| bare greeting/topic აჩვენებს ბრენდ-მენიუს | WP-13, ext. MP-5 | 🟢 MUST PASS | ორვარიანტიანი მენიუ bare „გამარჯობა"-ზე | `_maybe_static_welcome` conservative gate (:2593) |
| მეორე ბავშვი ჯავშნის შემდეგ → handoff, booked age დაცული (B5) | WP-14 | 🟢 MUST PASS | child_age უცვლელი; `_BOOKED_SECOND_CHILD_MANAGER` | `_maybe_requalify_child` + `_lead_has_active_booking` (:1013) |
| ნაკადი I ჯერ ჩანს დღეს (today<start) | WP-15, CS-1, IC-3 | 🟢 MUST PASS | I 23-29 ივნისი + II + III ჩანს 06-22-ზე | `admin_config_service.is_camp_stream_visible` (:1167) |
| ფასი = 2150 პირველ price ask-ზე | WP-16, ext. IC-4 | 🟢 MUST PASS | 2150 ლარი, admin-grounded | `get_camp_info` ← `get_camp_facts` (price = data) |
| underage handoff — comms-ზმნა/როლ-სიტყვა ≠ სახელი (live 2026-06-22) | WP-23 | 🟢 MUST PASS | „კი მომწერე" → ითხოვს სახელ+ნომერს, **არა** „სახელი მივიღე"; „მომწერე"/„მენეჯერ" არ ინახება სახელად | `_NAME_REJECT_STEMS` (+მომწერ/გამომიგზავ/მენეჯერ, :4966) + `_is_handoff_affirmative` lead+contact-verb (:2054) |
| underage handoff — მენეჯერის ნომრის მოთხოვნა (live 2026-06-22) | WP-24 | 🟢 MUST PASS | „მენეჯერის ნომერი მომწერე" → 558 67 47 33 (არ ხელახ. ითხოვს მომხმარებლის ნომერს); in-memory only | `_maybe_handle_underage_manager_handoff` early `_is_explicit_manager_number_request` → `_render_manager_number_answer` (:2151) |
| **დაჯავშნილი პირველი ბავშვის ასაკის გადაწერა „არა, 15" (B5×B1)** | **WP-17** | **🟡 PROBE** | **იდეალურად: ჩუმად არ გადაიწეროს, მენეჯერთან გადამისამართება. ❌ დეტერმინისტულად არ არის დაცული — operator-DEFERRED, VERIFIED 5/5 fail** | `maybe_capture_child_age_fallback` — NO booked guard (parent_llm_engine.py:1751/1860) |
| **ნაწილობრივი უარი/slot-ცვლა „ამ დღეს არ მინდა, ზეგ მინდა" (DEC-fp)** | **WP-18** | **🟡 PROBE** | **იდეალურად: reschedule. ❌ დეტერმინისტულად არ არის დაცული — სრული უარი ისვრის, pending_booking იწმინდება** | `_maybe_handle_decline_engine` — override-ს არ აქვს date markers (:3134/:3170) |
| **Off-topic deflection PARENT-ში („მუფასა ვინ არის")** | **WP-19, ext. GI-1** | **🟡 PROBE** | **იდეალურად: თავაზიანი deflect. ❌ არანაირი deterministic guard — მხოლოდ ADULT-ს აქვს** | NO guard — parent_llm_engine/parent_flow has no off-topic interceptor |
| **English / non-Georgian გაჟონვა** | **WP-20, ext. GI-4** | **🟡 PROBE** | **იდეალურად: ქართულად. ❌ მხოლოდ prompt — არანაირი language fallback** | NO language guard — `sanitise_response_wording` = fixed phrase list |
| **სახელის/ნომრის ხელახალი კითხვის სანდოობა** | **WP-21, ext. CM-1/CM-3** | **🟡 PROBE** | **იდეალურად: არ ხელახლა იკითხავს. phone capture deterministic, name re-ask prompt-ზეა** | phone: `maybe_capture_phone_fallback` (det.); name re-ask: prompt-reliant |
| **ფასის ხელახალი დადასტურება მანიპულაციის turn-ზე („გუშინ 1000 ლარი")** | **WP-22, ext. GI-2/IC-4** | **🟡 PROBE** | **იდეალურად: ცრუ 1000-ს არ იმეორებს AND 2150-ს ხელახ. ადასტურებს. re-state prompt-ზეა; უფასო ჯავშნის აკრძალვა კი deterministic** | price grounding (det. discount block); 2150 re-state = prompt-only |

> **🟡 PROBE რიგების მოკლე ჩამონათვალი (ოპერატორმა იცოდე, რომ აქ ჩავარდნა ≠ რეგრესია):** WP-17 (დაჯავშნილი პირველი ბავშვის ასაკის გადაწერა), WP-18 (ნაწილობრივი უარი/slot-ცვლა), WP-19 (off-topic deflection), WP-20 (English-leak), WP-21 (name re-ask), WP-22 (price re-state). ყველა დანარჩენი 🟢 — ცოცხლად უნდა დაიჭიროს.

---

## ADULT flow + engine

ADULT ქვესისტემა ამუშავებს ზრდასრულთა კულტურულ ღონისძიებებს (NOT camp). engine ON-ით ცნობს PRE-LLM დეტერმინისტული interceptor-ების ჯაჭვს (თითო OpenAI call-ამდე ბრუნდება). ცოცხალი მონაცემი დღეს (2026-06-22), წყარო `data/admin_config/sections.yaml` (admin_config_service-ით, **NOT** `data/events.txt` — ის ცარიელი template-ია): ერთადერთი აქტიური + მომავალი ღონისძიება არის „fromula 1" (28 აგვისტო, monaco, 5000 ლარი, min_age 13); Gia Murghulia (14 ივნისი) წარსულშია → იმალება. ADULT flow **არასოდეს** ეხება Google Calendar-ს.

**AD-1 — დასახელებული წარსული ღონისძიება → „უკვე გაიმართა" (Gia Murghulia, 14 ივნისი)** · ტიპი: 🟢 MUST PASS · სუსტი წერტილი: დეტერმინისტული named-event PAST branch უნდა უპასუხოს, რომ ღონისძიება უკვე გაიმართა + ჩამოთვალოს აქტიური, self/child target/ასაკის კითხვის და ბილეთის ბმულის/ფასის გამოგონების გარეშე.
1. გამარჯობა, კულტურული საღამოები გაინტერესებთ?
2. გია მურღულიასთან შეხვედრა მაინტერესებს, ეს ღონისძიება როდისაა?

✅ მოსალოდნელი: აგენტი დეტერმინისტულად პასუხობს, რომ ღონისძიება „შეხვედრა გია მურღულიასთან" უკვე გაიმართა — 14 ივნისი 20:00, შემდეგ ჩამოთვლის მიმდინარე აქტიურ ღონისძიებებს (fromula 1, 28 აგვისტო). არ ეკითხება „თქვენთვის თუ თქვენი შვილისთვის", არ აგზავნის ბილეთის ბმულს/ფასს ამ წარსულ ღონისძიებაზე.
🔴 RED FLAG: წარსულ ღონისძიებას აქტიურად აჩვენებს, აგზავნის reservation_url/ფასს, ან ჯერ ეკითხება self/child target/ასაკს ნაცვლად „უკვე გაიმართა"-სი.
🔧 guard: `_maybe_handle_named_adult_event` PAST branch / `_render_past_named_event` (adult_llm_engine.py:1899/1874)

**AD-2 — Off-topic ზოგად-ცოდნის „ვინაა X" რედირექტი** · ტიპი: 🟢 MUST PASS · სუსტი წერტილი: off-topic guard-მა უნდა გადაამისამართოს ზოგად-ცოდნის კითხვა, არ წავიდეს ChatGPT-mode-ში.
1. ვინაა ელტონ ჯონი?

✅ მოსალოდნელი: აგენტი აბრუნებს ფიქსირებულ რედირექტს: „ამ სახელით ღონისძიება ჩვენს მიმდინარე პროგრამაში არ ჩანს. თუ გსურთ, შემიძლია არსებული კულტურული შეხვედრები გაგაცნოთ." — არ აღწერს ვინ არის ელტონ ჯონი.
🔴 RED FLAG: ხსნის ვინ არის ელტონ ჯონი (ბიოგრაფია), ან ეკითხება „რომელ ღონისძიებასთან დაკავშირებით?".
🔧 guard: `_maybe_adult_offtopic_reply` WHO branch (adult_llm_engine.py:346)

**AD-3 — Off-topic fiction/topic რედირექტი (მუფასა relation question)** · ტიპი: 🟢 MUST PASS · სუსტი წერტილი: off-topic guard-მა უნდა დაიჭიროს ფიქტიური პერსონაჟის relation question topic-stem + relation branch-ით.
1. მუფასა სიმბას მამაა თუ დედა?

✅ მოსალოდნელი: აგენტი აბრუნებს „ამ კითხვაზე ვერ დაგეხმარებით.\nთუ ჩვენს ღონისძიებებზე გაქვთ კითხვა, სიამოვნებით გიპასუხებთ."
🔴 RED FLAG: პასუხობს რომ მუფასა სიმბას მამაა, ან რაიმე ფაქტობრივ ახსნას აძლევს.
🔧 guard: `_maybe_adult_offtopic_reply` topic-stem „მუფასა"/„სიმბ" + relation „მამა თუ" (adult_llm_engine.py:356/361)

**AD-4 — Self-vs-child capture შემდეგ B4 revert („ჩემთვის" → „შვილისთვის"-ის შემდეგ)** · ტიპი: 🟢 MUST PASS · სუსტი წერტილი: B4 self-revert-მა უნდა გაასუფთავოს წინ ჩაჭერილი child target, როცა მომხმარებელი თავის თავზე ასწორებს, relative cue-ის გარეშე.
1. ღონისძიება მაინტერესებს ჩემი შვილისთვის
2. არა, ჩემთვის მინდა

✅ მოსალოდნელი: პირველ turn-ზე target=შვილი იჭერა (ეკითხება ბავშვის ასაკს / რჩება ADULT-ში, არ გადადის ბანაკზე). მეორე turn-ზე target დეტერმინისტულად იწმინდება self-ზე — აგენტი აღარ ეპყრობა შვილისთვის შერჩევას, ეკითხება მომხმარებლის საკუთარ ასაკს ან აგრძელებს self კონტექსტში.
🔴 RED FLAG: მეორე turn-ის შემდეგ მაინც „თქვენი შვილისთვის" კონტექსტში აგრძელებს / ეკითხება ბავშვის ასაკს; ან „ჩემი შვილისთვის" პირველ turn-ზე ბანაკზე გადადის.
🔧 guard: `_maybe_capture_adult_target` B4 self-revert `_ADULT_SELF_REFERENCE_MARKERS` (adult_llm_engine.py:587/551)
🔍 შესამოწმებელი side-effect: in-memory lead mutation only; გადაამოწმე `lead.adult_target_relation` გასუფთავდა.

**AD-5 — Soft child cue + adult-event signal NOT switch PARENT-ზე** · ტიპი: 🟢 MUST PASS · სუსტი წერტილი: `_user_wants_parent_flow`-მ უნდა შეინარჩუნოს ADULT, როცა ბავშვის ხსენება დაწყვილებულია adult-event signal-თან hard camp word-ის გარეშე.
1. ჩემი შვილისთვის კულტურული საღამო მაინტერესებს

✅ მოსალოდნელი: საუბარი რჩება ADULT ფლოუში (ღონისძიება შვილისთვის). აგენტი ეკითხება შვილის ასაკს ან აგრძელებს ADULT-ში — არ ამბობს „გასაგებია, ბანაკის შესახებ დაგეხმარებით…".
🔴 RED FLAG: გადადის PARENT/ბანაკზე ან ბანაკის ფაქტებს (2150/9-17/ამბასადორი) ახსენებს.
🔧 guard: `_user_wants_parent_flow` soft-cue+adult-signal stays ADULT (adult_llm_engine.py:454/464)
🔍 შესამოწმებელი side-effect: გადაამოწმე `conversation.segment` რჩება ADULT.

**AD-6 — Hard camp keyword გადადის PARENT-ზე** · ტიპი: 🟢 MUST PASS · სუსტი წერტილი: `_user_wants_parent_flow`-მ უნდა გადავიდეს PARENT-ზე ცხად „ბანაკი"-ზე, ADULT საუბრის შუაშიც.
1. კულტურული საღამოები გაინტერესებთ
2. ჩემი შვილისთვის საზაფხულო ბანაკი მინდა

✅ მოსალოდნელი: მეორე turn-ზე აგენტი დეტერმინისტულად აბრუნებს „გასაგებია, ბანაკის შესახებ დაგეხმარებით. თქვენი შვილი რამდენი წლისაა?" და segment ხდება PARENT.
🔴 RED FLAG: რჩება ADULT-ში და ღონისძიებებზე საუბრობს „ბანაკი"-ს ცხადი ხსენების მიუხედავად.
🔧 guard: `_user_wants_parent_flow` HARD camp keyword (adult_llm_engine.py:459, wired :2021)
🔍 შესამოწმებელი side-effect: გადაამოწმე `conversation.segment` flips to PARENT.

**AD-7 — Calendar booking არასოდეს adult flow-ში** · ტიპი: 🟢 MUST PASS · სუსტი წერტილი: booking tool არ არსებობს; ცხადი slot/time request-მა არასოდეს უნდა შექმნას Calendar event ან დაადასტუროს დაჯავშნილი დრო.
1. fromula 1 ღონისძიება მაინტერესებს
2. კარგი, ჩამიწერეთ კონსულტაცია ხვალ 16 საათზე

✅ მოსალოდნელი: აგენტი არ ჯავშნის Calendar სლოტს და არ ადასტურებს კონკრეტულ საათს. რეგისტრაცია reservation_url-ით ან მენეჯერთან გადაცემით ხდება.
🔴 RED FLAG: ამბობს „ჩაგინიშნეთ 16:00" / ადასტურებს Calendar სლოტს / გთავაზობთ კონკრეტულ საათს მენეჯერთან საუბრისთვის.
🔧 guard: `ALLOWED_ADULT_TOOL_NAMES` has no booking tool; prompt ban (adult_tools.py:37; system_adult_v1.md:152)
🔍 შესამოწმებელი side-effect: Calendar: გადაამოწმე ZERO calendar event; Sheets: no Booked row.

**AD-8 — ცხადი unsubscribe დეტერმინისტული დადასტურება** · ტიპი: 🟢 MUST PASS · სუსტი წერტილი: unsubscribe ფრაზამ უნდა short-circuit-ი LLM-ამდე და დააბრუნოს ფიქსირებული დადასტურება.
1. აღარ გამომიგზავნოთ შეტყობინებები

✅ მოსალოდნელი: აგენტი აბრუნებს ფიქსირებულ „კარგი, მომავალ ღონისძიებებზე შეტყობინებებს აღარ გამოგიგზავნით." (ან not-subscribed soft message), LLM-ის გარეშე.
🔴 RED FLAG: ხელახლა სთავაზობს გამოწერას, ან ვერ აღიქვამს unsubscribe-ს და ღონისძიებებზე საუბრობს.
🔧 guard: `is_unsubscribe_phrase` short-circuit (adult_llm_engine.py:1995; adult_subscription_service.py:95)
🔍 შესამოწმებელი side-effect: Sheets events tab: subscriber row status → unsubscribed (ან not_subscribed branch თუ არასოდეს იყო გამოწერილი).

**AD-9 — „კი" შიგნით „კიდევ" NOT subscribe (word-boundary token)** · ტიპი: 🟢 MUST PASS · სუსტი წერტილი: subscription consent whole-token matching-ს იყენებს; „კი" substring „კიდევ"-ში არ უნდა ააქტიუროს Sheets write.
1. fromula 1 ღონისძიება მაინტერესებს
2. გსურთ, ახალ ღონისძიებებზე შეგატყობინოთ?
3. კიდევ ერთი კითხვა მაქვს — სად ტარდება?

✅ მოსალოდნელი: მესამე turn არ ითვლება გამოწერის თანხმობად — აგენტი არ ამბობს „ჩაგწერეთ სიაში" და პასუხობს ლოკაციის კითხვას.
🔴 RED FLAG: ამბობს „ჩაგწერეთ სიაში / დაგამატეთ სიაში" მხოლოდ იმის გამო, რომ შეტყობინებაში იყო „კიდევ".
🔧 guard: `_is_subscription_consent` `_tokenize_ka` whole-token (adult_llm_engine.py:1590/1509)
🔍 შესამოწმებელი side-effect: Sheets events tab: გადაამოწმე NO new subscriber row ამ turn-ზე.

**AD-10 — დეტერმინისტული subscription consent წერს მხოლოდ დადასტურებულ Sheets row-ზე** · ტიპი: 🟢 MUST PASS · სუსტი წერტილი: რეალური offer-ის შემდეგ „კი გამომიგზავნეთ"-მა უნდა შეასრულოს write და დაადასტუროს მხოლოდ row-ის არსებობის შემდეგ (ან ითხოვოს ნაკლული phone/name).
1. fromula 1 ღონისძიება მაინტერესებს
2. გსურთ, როცა ახალი ზრდასრულთა ღონისძიება დაემატება, დეტალები გამოგიგზავნოთ?
3. კი, გამომიგზავნეთ

✅ მოსალოდნელი: აგენტი ან წერს subscriber row-ს და ადასტურებს, ან ითხოვს დაკარგულ ნომერს/სახელს, ან honest failure („ტექნიკურად ვერ მოხერხდა. მენეჯერს გადავცემ…"). არასოდეს ცრუობს წარმატებაზე row-ის გარეშე.
🔴 RED FLAG: ამბობს „ჩაგწერეთ სიაში" მაგრამ events tab-ში row არ ჩაიწერა (false success).
🔧 guard: `_maybe_handle_subscription` → `_deterministic_subscribe` (adult_llm_engine.py:1703/1611); confirm only on result.success
🔍 შესამოწმებელი side-effect: Sheets events tab: row მხოლოდ confirmation-ზე; phone/name missing → NO row.

**AD-11 — Manager callback ითხოვს ტელეფონს (missing_phone gate)** · ტიპი: 🟢 MUST PASS · სუსტი წერტილი: `request_adult_manager_callback`-მა Sheets/email არ უნდა ისროლოს ვალიდური ნომრის გარეშე; LLM-მა უნდა ითხოვოს.
1. fromula 1 ღონისძიება მაინტერესებს
2. მენეჯერთან დამაკავშირეთ

✅ მოსალოდნელი: აგენტი ითხოვს სახელსა და საკონტაქტო ნომერს — მენეჯერის email/Sheets ამ turn-ზე არ ისვრება, რადგან ნომერი არ არის.
🔴 RED FLAG: ამბობს რომ მენეჯერს გადასცა / „დაგიკავშირდებათ" ნომრის გარეშე, ან მენეჯერის email იგზავნება ვალიდური ნომრის გარეშე.
🔧 guard: `_request_adult_manager_callback` missing_phone (adult_tool_executor.py:636)
🔍 შესამოწმებელი side-effect: Sheets/email: გადაამოწმე NO Leads row და NO manager email ამ turn-ზე.

**AD-12 — Manager callback idempotency (no double email)** · ტიპი: 🟢 MUST PASS · სუსტი წერტილი: მეორე manager-callback იმავე საუბარში უნდა აბრუნდეს already_notified-ით, email/Sheets-ის გაორმაგების გარეშე.
1. fromula 1 მაინტერესებს, მენეჯერთან დამაკავშირეთ
2. ჩემი ნომერია 595123456
3. ისევ გადაეცი მენეჯერს, დარწმუნებული ხარ?

✅ მოსალოდნელი: პირველი ვალიდურ-ნომრიანი handoff ერთხელ ისვრის Sheets+email-ს და აბრუნებს მენეჯერის ნომერს; განმეორებითი handoff turn-ზე email/Sheets ხელახლა არ ისვრება (already_notified).
🔴 RED FLAG: მენეჯერს ეგზავნება ორი email / ორი Leads row ერთსა და იმავე საუბარში.
🔧 guard: `_is_adult_manager_notified` idempotency + Redis adult_manager_notified:{sender_id} (adult_tool_executor.py:644/125)
🔍 შესამოწმებელი side-effect: Email: ზუსტად ONE manager email; Sheets: ერთი ADULT Leads row; Redis key adult_manager_notified:{sender} set.

**AD-13 — child_age leakage guard (camp ბავშვის ასაკი არ ფილტრავს adult events)** · ტიპი: 🟢 MUST PASS · სუსტი წერტილი: camp-დან გადმოტანილი child_age არ უნდა გახდეს adult eligibility age, თუ მომხმარებელმა არ თქვა რომ შვილისთვისაა.
1. ჩემი შვილი 12 წლისაა, საზაფხულო ბანაკი მაინტერესებს
2. აბა ღონისძიებებიც მაჩვენე

✅ მოსალოდნელი: მეორე turn-ზე (თუ ისევ ADULT-ში მოხვდა) backend არ ფილტრავს ღონისძიებებს child_age=12-ით; აგენტი ჯერ აზუსტებს ვისთვისაა. (პირველი turn ბანაკზე გადადის hard keyword-ით — child_age ინახება PARENT-ში.)
🔴 RED FLAG: ფილტრავს/ამბობს რომ „12 წლისთვის შესაბამისი ღონისძიება…" ან child_age-ს ADULT eligibility-ად იყენებს ვისთვის-კითხვის გარეშე.
🔧 guard: `_get_adult_events` child_age leakage block (adult_tool_executor.py:251)
🔍 შესამოწმებელი side-effect: გადაამოწმე `lead.child_age` არასოდეს კოპირდება `adult_target_age`-ში ცხადი child intent-ის გარეშე.

**AD-14 — Banned retail/pressure word sanitiser** · ტიპი: 🟡 PROBE · სუსტი წერტილი: sanitiser-მა უნდა მოაშოროს retail/pressure phrasing თუ LLM აწარმოებს — მაგრამ სუფთა copy-ის გენერაცია LLM-ზეა.
1. fromula 1 ღონისძიება მაინტერესებს, როგორ ვიყიდო ბილეთი?
2. ცოტა ვყოყმანობ ფასზე

✅ მოსალოდნელი: პასუხში არ ჩანს „ბილეთი შეიძინეთ", „იჩქარეთ", „ბოლო ადგილები", „სალაროში" — ტონი მშვიდი/პრემიუმია; reservation_url ან მენეჯერთან გადაცემაა შეთავაზებული.
🔴 RED FLAG: „ბილეთი შეიძინეთ ახლავე" / „იჩქარეთ" / „ბოლო ადგილები" / „სალარო" — ან ხელოვნური წნევა.
🔧 guard: `sanitise_adult_response` retail/pressure strips (adult_llm_engine.py:693-738) — strips IF present, clean copy LLM-dependent.

**AD-15 — Subscription/future-updates CTA არ over-fire-დება plain decline-ზე** · ტიპი: 🟡 PROBE · სუსტი წერტილი: decline-ზე აგენტმა subscription CTA არ უნდა აიძულოს; subscription question მხოლოდ event details-ის შემდეგ, ერთხელ.
1. fromula 1 ღონისძიება მაინტერესებს
2. დავფიქრდები, მადლობა

✅ მოსალოდნელი: მოკლე, თბილი დახურვა; არ ისვრის გამოწერის CTA-ს და არ აწექს ბილეთის ყიდვაზე.
🔴 RED FLAG: decline-ის შემდეგ მაინც სვამს გამოწერის კითხვას ან სხვა sales კითხვას.
🔧 guard: system_adult_v1.md decline rule + subscription rule (no deterministic over-fire guard) (:106/:172)

**AD-16 — დასახელებული NOT-FOUND ღონისძიება → „ვერ მოვძებნე" + active list (გამოგონების გარეშე)** · ტიპი: 🟢 MUST PASS · სუსტი წერტილი: მონაცემებში არარსებული კონკრეტული სახელი უნდა დააბრუნოს not-found პასუხი, არასოდეს გამოგონილი ღონისძიება.
1. გალაკტიონის საღამო გაქვთ?

✅ მოსალოდნელი: აგენტი დეტერმინისტულად აბრუნებს „ამ სახელით ღონისძიება ვერ მოვძებნე." + აქტიური ღონისძიებების სია (fromula 1) + „დეტალები მენეჯერთან შეგიძლიათ გადაამოწმოთ.".
🔴 RED FLAG: იგონებს „გალაკტიონის საღამოს" დეტალებს (თარიღი/ფასი/ბმული) ან ეკითხება self/child target.
🔧 guard: `_maybe_handle_named_adult_event` NOT-FOUND / `_render_unknown_named_event` (adult_llm_engine.py:1947/1889)

**AD-17 — Reservation link აქტიური ღონისძიებისთვის** · ტიპი: 🟡 PROBE · სუსტი წერტილი: LLM-ზეა: უნდა გასცეს კონფიგურირებული reservation_url fromula 1-ისთვის, არასოდეს გამოიგონოს.
1. fromula 1 ღონისძიება მაინტერესებს, რეგისტრაცია მინდა

✅ მოსალოდნელი: აგენტი გადასცემს კონფიგურირებულ ბმულს https://wordacademy.ge/courses/cart/ ბუნებრივად. (executor link_missing-ზე — მენეჯერთან გადაცემა; ბმულს არ იგონებს.)
🔴 RED FLAG: იგონებს რეგისტრაციის ბმულს, ან ცარიელი ბმულის შემთხვევაში ცრუ ლინკს აძლევს.
🔧 guard: `_provide_adult_reservation_link` link_missing guard (adult_tool_executor.py:709) — invention blocked, real URL share LLM-dependent.

**AD-18 — Notification-delivery question პასუხდება, არა off-topic-ად** · ტიპი: 🟢 MUST PASS · სუსტი წერტილი: „სად მომივა შეტყობინება?" delivery handler-ში უნდა მოხვდეს, არა off-topic redirect-ში.
1. fromula 1 მაინტერესებს
2. გსურთ ახალ ღონისძიებებზე შეგატყობინოთ?
3. კი
4. და სად მომივა შეტყობინება?

✅ მოსალოდნელი: აგენტი პლატფორმის შესაბამისად პასუხობს რომ შეტყობინება ამავე ჩატში (Messenger/Instagram/WhatsApp) მოვა — არ აბრუნებს „ამ კითხვაზე ვერ დაგეხმარებით" და ხელახლა არ ერთვება გამოწერაში.
🔴 RED FLAG: აბრუნებს off-topic რედირექტს delivery კითხვაზე, ან ხელახლა წერს subscriber row-ს.
🔧 guard: `_maybe_handle_notification_delivery_question` + off-topic exemption (adult_llm_engine.py:252/330)
🔍 შესამოწმებელი side-effect: Sheets events tab: გადაამოწმე NO duplicate subscriber row delivery-question turn-ზე.

**AD-19 — ასაკი ყველა min_age-ის ქვემოთ → თავაზიანი no-event + manager, camp facts-ის გარეშე** · ტიპი: 🟡 PROBE · სუსტი წერტილი: LLM-ზეა: როცა ცნობილი ასაკი ყველა active min_age-ის ქვემოთაა (13), აგენტმა უნდა თქვას no eligible event + manager, არასოდეს ბანაკი.
1. ღონისძიება მაინტერესებს ჩემთვის
2. 10 წლის ვარ

✅ მოსალოდნელი: აგენტი ნაზად აღნიშნავს რომ ამ ასაკისთვის (10 < min_age 13) შესაბამისი ღონისძიება არ არის და სთავაზობს მენეჯერთან კავშირს; არ ახსენებს ბანაკის ფაქტებს თუ მომხმარებელმა არ ითხოვა.
🔴 RED FLAG: აჩვენებს fromula 1-ს 10 წლის მომხმარებელს, ან ბანაკის ფაქტებზე გადადის თვითნებურად.
🔧 guard: min_age >= filter in `get_active_adult_events` (admin_config_service.py:1257) — filter deterministic, no-event message LLM-composed.

**AD-20 — Banned greeting/opener sanitiser (no „კეთილი იყოს თქვენი ვიზიტი")** · ტიპი: 🟡 PROBE · სუსტი წერტილი: sanitiser-მა უნდა მოაშოროს banned premium-opener თუ LLM იყენებს.
1. გამარჯობა, რა კულტურული ღონისძიებები გაქვთ?

✅ მოსალოდნელი: პასუხში არ ჩანს „კეთილი იყოს თქვენი ვიზიტი…" და არც „სიამოვნებით გაგაცნობთ ჩვენს კულტურულ საღამოებს" — გენიტივი სწორია („სიტყვის აკადემიის").
🔴 RED FLAG: იწყება „კეთილი იყოს თქვენი ვიზიტი სიტყვის აკადემიაის…" ან „სიამოვნებით გაგაცნობთ ჩვენს კულტურულ საღამოებს".
🔧 guard: `sanitise_adult_response` banned opener strips + genitive fix (adult_llm_engine.py:663-691) — strips IF present.

---

## Comment / DM / segment routing

comment→DM funnel აქცევს public Instagram/Facebook კომენტარს private first-contact DM-ად. **მნიშვნელოვანი test posture:** comment→DM flow (intent, segment, dedup, DM content, public-reply gating) ააქტიურდება **მხოლოდ რეალური Meta webhook POST-ით** და ოპერატორ-დაკვირვებადია Page DM/Redis/Sheets-ით — ჩატში აკრიფა მას ვერ ააქტიურებს. მხოლოდ registration-link clarification და segment-router behavior-ები ააქტიურდება DM-ში პირდაპირ. ქვემოთ `[OPERATOR-DRIVEN]` მონიშნული ნაბიჯები რეალურ კომენტარს/webhook-ს მოითხოვს.

**CF-1 — Parent/camp comment → INTERESTED (deterministic) → rich camp DM with real facts** · ტიპი: 🟢 MUST PASS · სუსტი წერტილი: `is_interest_intent`-მა უნდა short-circuit-ი LLM ცხად price comment-ზე, segment PARENT #ბანაკი post-დან, DM-ს კანონიკური 2150 / ამბასადორი კაჭრეთი / registration URL.
1. [OPERATOR-DRIVEN, არა chat] დადე კომენტარი „ფასი რა ღირს?" #ბანაკი post-ქვეშ ტესტ ანგარიშიდან

✅ მოსალოდნელი: Intent INTERESTED (deterministic); segment PARENT; private DM ამბობს „ბანაკი ტარდება ამბასადორ კაჭრეთში, 7-დღიანია. ფასი: 2150 ლარი", ჩამოთვლის ხილულ ნაკადებს და „რეგისტრაციის ბმული: https://tinyurl.com/36jcae8z". არანაირი 558 67 47 33 ან გამოგონილი ფაქტი.
🔴 RED FLAG: DM არ მოდის; არასწორი ფასი (მაგ. 2200), არასწორი ლოკაცია, გამოგონილი ნაკადის თარიღი, ნაკლული/placeholder registration link, ან bare PARENT_FIRST_CONTACT_DM fallback admin/YAML facts-ის არსებობისას.
🔧 guard: `is_interest_intent` + `determine_segment_from_post` + `_build_parent_rich_dm`
🔍 შესამოწმებელი side-effect: Private reply DM Page-ზე; Sheets comment row segment=PARENT intent=INTERESTED status=CommentOnly; Redis processed_comment:{comment_id} dm_sent=true; conversation last_bot_message_at stamped.

**CF-2 — Adult comment #ღონისძიება-ქვეშ → ADULT rich DM (active events list)** · ტიპი: 🟢 MUST PASS · სუსტი წერტილი: segment ADULT adult_events section hashtags-დან და DM active-events catalogue (არა camp DM, არა „no schedule" copy როცა active events არსებობს).
1. [OPERATOR-DRIVEN] დადე კომენტარი „ბილეთი როგორ ვიყიდო?" #ღონისძიება (ან #event/#საღამო) post-ქვეშ ტესტ ანგარიშიდან

✅ მოსალოდნელი: Intent INTERESTED; segment ADULT; DM იწყება „გამარჯობა. მოხარულები ვართ, რომ დაინტერესდით ჩვენი ღონისძიებებით" და ჩამოთვლის active adult events-ს title/date/price/link-ით sections.yaml-დან.
🔴 RED FLAG: Camp DM (2150 ლარი / ამბასადორ კაჭრეთში) ჟონავს adult comment-ში; DM ამბობს „ახლო მომავალში… გამოვაქვეყნებთ" active events-ის არსებობისას; literal {events_list} placeholder ჩანს.
🔧 guard: `determine_segment_from_post` + `_build_active_adult_events_list_dm`
🔍 შესამოწმებელი side-effect: Private reply DM; Sheets comment row segment=ADULT; Redis processed_comment:{id}; camp facts არ არის DM body-ში.

**CF-3 — NOT_INTERESTED comment → no DM, no Sheets row, not marked processed** · ტიპი: 🟡 PROBE · სუსტი წერტილი: სუფთა-კომპლიმენტი interest keyword-ის გარეშე LLM-მა NOT_INTERESTED-ად უნდა დააკლასიფიციროს და short-circuit save_comment/public reply/DM-ამდე.
1. [OPERATOR-DRIVEN] დადე კომენტარი „ლამაზია 😍" (interest keyword-ის გარეშე) ნებისმიერ tagged post-ქვეშ

✅ მოსალოდნელი: Log ამბობს „Ignored - not interested"; private DM არ იგზავნება; Sheets comment row არ იქმნება.
🔴 RED FLAG: DM იგზავნება სუფთა კომპლიმენტზე; Sheets row ჩნდება; comment_id-ს processed_comment Redis key მიენიჭება DM-ის გარეშე.
🔧 guard: `detect_comment_intent` (LLM) + NOT_INTERESTED short-circuit (webhook.py:521-524)
🔍 შესამოწმებელი side-effect: No DM; no Sheets row; no processed_comment:{id}. (LLM_ONLY: `is_interest_intent`-ის keyword set-მა შეიძლება ambiguous compliment INTERESTED-ად გადააქციოს — გადაამოწმე ფრაზაში keyword არ არის.)

**CF-4 — ჩაშენებული interest keyword რომელიც LLM-მა შეიძლება გამოტოვოს → deterministic INTERESTED მაინც fires** · ტიპი: 🟢 MUST PASS · სუსტი წერტილი: `is_interest_intent`-მა უნდა გადაარჩინოს ცხადი request რომელიც stochastic LLM-მა შეიძლება NOT_INTERESTED-ად მონიშნოს (ცოცხალი ბაგი მოკლე კომენტარებზე „ბმული?").
1. [OPERATOR-DRIVEN] დადე ერთსიტყვიანი კომენტარი „ბმული?" #ბანაკი post-ქვეშ

✅ მოსალოდნელი: Log ამბობს „Intent detected: INTERESTED (deterministic)" — LLM არასოდეს იძახება; camp DM registration URL-ით იგზავნება.
🔴 RED FLAG: NOT_INTERESTED-ად მოპყრობა (no DM); ან LLM round-trip closed-set keyword-ისთვის.
🔧 guard: `is_interest_intent` (comment_service.py:341)
🔍 შესამოწმებელი side-effect: Private reply DM https://tinyurl.com/36jcae8z-ით; Sheets row intent=INTERESTED.

**CF-5 — Duplicate webhook delivery → processed_comment dedup, no double DM** · ტიპი: 🟢 MUST PASS · სუსტი წერტილი: Meta ხელახლა აგზავნის იმავე comment webhook-ს; მეორე delivery in-process LRU-ით ან Redis processed_comment:{id}-ით უნდა short-circuit-დეს — ზუსტად ერთი DM.
1. [OPERATOR-DRIVEN] დადე ერთი INTERESTED კომენტარი #ბანაკი-ქვეშ, დააკვირდი ერთ DM-ს, შემდეგ ხელახლა გააგზავნე იდენტური webhook payload (ან Meta redelivery / იგივე comment_id replay)

✅ მოსალოდნელი: პირველი delivery აგზავნის DM-ს; მეორე ლოგავს „duplicate comment_id=… skipped (in-process LRU)" ან „(redis)" და არაფერს აგზავნის.
🔴 RED FLAG: ორი იდენტური DM ერთსა და იმავე მომხმარებელს ერთი კომენტარისთვის.
🔧 guard: Duplicate webhook guard (webhook.py:489-506)
🔍 შესამოწმებელი side-effect: ზუსტად ONE private reply DM; Redis processed_comment:{id} present პირველის შემდეგ; no second send log line.

**CF-6 — Public reply gating OFF → DM მაინც იგზავნება, no public /replies POST** · ტიპი: 🟢 MUST PASS · სუსტი წერტილი: ENABLE_PUBLIC_COMMENT_REPLY=false (ცოცხალი .env value)-ით handler-მა public reply უნდა გამოტოვოს და private DM მაინც გააგზავნოს.
1. [OPERATOR-DRIVEN] დარწმუნდი .env ENABLE_PUBLIC_COMMENT_REPLY=false; დადე INTERESTED კომენტარი #ბანაკი-ქვეშ

✅ მოსალოდნელი: Log ამბობს „Public reply disabled; skipping (comment_id=…)"; არანაირი POST /{comment_id}/replies-ზე; private DM მიდის.
🔴 RED FLAG: public reply იდება flag-off-ის მიუხედავად; ან DM გამოტოვებულია/დაბლოკილი public reply path-ის შეცდომის გამო.
🔧 guard: ENABLE_PUBLIC_COMMENT_REPLY gating (webhook.py:552-571)
🔍 შესამოწმებელი side-effect: No public comment post-ქვეშ; private DM delivered; Sheets row created.

**CF-7 — Public reply gating ON მაგრამ Meta რეჯექტავს /replies (HTTP 400) → DM not blocked** · ტიპი: 🟢 MUST PASS · სუსტი წერტილი: public reply-ის ჩავარდნისას (App Review არ არის granted → HTTP 400) ჩავარდნა უნდა ჩაიწეროს log-ში და private DM მაინც გავიდეს.
1. [OPERATOR-DRIVEN] დააყენე ENABLE_PUBLIC_COMMENT_REPLY=true (App Review NOT granted ასე /replies 400s); დადე INTERESTED კომენტარი #ბანაკი-ქვეშ

✅ მოსალოდნელი: Log ამბობს public reply attempt failed (status 400) AND „continuing to DM"; private DM მაინც წარმატებით მიდის.
🔴 RED FLAG: DM გამოტოვებულია public reply-ის ჩავარდნის გამო; exception reply_to_comment-ში აბორტავს მთლიან handler-ს send_dm_from_comment-ამდე.
🔧 guard: ENABLE_PUBLIC_COMMENT_REPLY gating + reply_to_comment failure isolation (webhook.py:552-571)
🔍 შესამოწმებელი side-effect: Private reply DM delivered; warning log „[COMMENT] Public reply failed; continuing to DM"; Sheets row created.

**CF-8 — First-contact DM, შემდეგ user პასუხობს Messenger-ში → normal PARENT flow აგრძელებს** · ტიპი: 🟢 MUST PASS · სუსტი წერტილი: comment DM stamps conversation (segment=PARENT, state=START, last_bot_message_at, Redis write-through), მომხმარებლის პირველმა DM-რეპლიმ უნდა გააგრძელოს camp flow (ეკითხება ასაკს), არ restart-დეს და არ ჩავარდეს UNCLEAR menu-ში.
1. [OPERATOR-DRIVEN seed: comment DM უკვე გაგზავნილია ამ user-თან]
2. გამარჯობა
3. 14 წლის შვილი მყავს, ბანაკი მაინტერესებს

✅ მოსალოდნელი: რეპლი აგრძელებს PARENT camp flow-ს — არ აგზავნის ხელახლა first-contact rich DM-ს და არ აჩვენებს generic ორვარიანტიან მენიუს; ჩაერთვება ბანაკზე (14-წლიანი, eligible ასაკი → კონსულტაცია/ასაკის მართვა).
🔴 RED FLAG: ხელახლა აგზავნის rich first-contact DM-ს; resets UNCLEAR/menu-ში; child_age 14 ხელახლა იკითხება/იკარგება; segment PARENT-დან გადადის.
🔧 guard: `send_dm_from_comment` conversation seeding (comment_service.py:1084-1093) + process_message booked/in-flow PARENT guard (conversation_service.py:472-478)
🔍 შესამოწმებელი side-effect: Redis conversation segment=PARENT + populated history; no duplicate first-contact DM Page thread-ში.

**CF-9 — ბუნდოვანი registration-link request (target-ის გარეშე) DM-ში → UNCLEAR clarification, არა guessed link** · ტიპი: 🟢 MUST PASS · სუსტი წერტილი: ახალი DM registration link-ისთვის camp/adult target-ის გარეშე უნდა ითხოვოს „ბანაკის თუ კონკრეტული ღონისძიების?" ნაცვლად camp link-ის გამოცნობისა ან generic menu-სი.
1. რეგისტრაციის ბმული მინდა

✅ მოსალოდნელი: პასუხი ზუსტად clarification: „რომელი მიმართულების რეგისტრაციის ლინკი გნებავთ — ბანაკის თუ კონკრეტული ღონისძიების?"
🔴 RED FLAG: აბრუნებს camp registration URL-ს კითხვის გარეშე; აბრუნებს adult reservation link-ს; ან აჩვენებს generic ორვარიანტიან welcome menu-ს.
🔧 guard: `_is_registration_link_request` + `_REGISTRATION_LINK_CLARIFICATION` (conversation_service.py:315/309, branch:506)

**CF-10 — Registration request რომელიც ასახელებს ბანაკს → camp link, no clarification** · ტიპი: 🟢 MUST PASS · სუსტი წერტილი: როცა registration request შეიცავს camp keyword-ს, segment classifier-მა PARENT-ი უნდა გაუშვას და camp flow-მა configured link დააბრუნოს — clarification არ უნდა fire-დეს (UNCLEAR-only).
1. ბანაკის რეგისტრაციის ბმული მომწერეთ

✅ მოსალოდნელი: segment PARENT; აგენტი აბრუნებს camp registration link https://tinyurl.com/36jcae8z (deterministic camp registration path), NOT camp-vs-event clarification.
🔴 RED FLAG: ეკითხება „ბანაკის თუ კონკრეტული ღონისძიების?" თუმცა user-მა თქვა „ბანაკის"; ან იგონებს სხვა link-ს.
🔧 guard: `_classify_segment` camp keyword (conversation_service.py:213/219) overrides UNCLEAR clarification branch
🔍 შესამოწმებელი side-effect: link reply-ისთვის none; გადაამოწმე link = Admin registration_url, არასოდეს hardcoded/invented URL.

**CF-11 — Information request „ინფორმაცია"-ით NOT trip „ფორმა" registration token** · ტიპი: 🟢 MUST PASS · სუსტი წერტილი: token-aware `_REGISTRATION_FORM_TOKEN_RE`-მ არ უნდა დაიჭიროს „ფორმ" substring „ინფორმაცია"-ში.
1. ინფორმაცია მომწერეთ

✅ მოსალოდნელი: პასუხი generic UNCLEAR routing/welcome menu (ან normal info handling) — NOT registration-link clarification.
🔴 RED FLAG: პასუხობს „რომელი მიმართულების რეგისტრაციის ლინკი გნებავთ — ბანაკის თუ კონკრეტული ღონისძიების?" plain information request-ზე.
🔧 guard: `_REGISTRATION_FORM_TOKEN_RE` (conversation_service.py:307) negative lookbehind on Georgian letters

**CF-12 — bare „ფორმა" registration-form request (target-ის გარეშე) → clarification fires** · ტიპი: 🟢 MUST PASS · სუსტი წერტილი: standalone „ფორმა" სიტყვა IS registration-form signal და target-ის გარეშე უნდა მიაღწიოს clarification-ს — ადასტურებს, რომ token ნამდვილ სიტყვას ემთხვევა, არა მხოლოდ look-alikes-ს რეჯექტავს.
1. სად ვიპოვი რეგისტრაციის ფორმას?

✅ მოსალოდნელი: პასუხი clarification „რომელი მიმართულების რეგისტრაციის ლინკი გნებავთ — ბანაკის თუ კონკრეტული ღონისძიების?"
🔴 RED FLAG: გამოიცნობს camp link-ს, ან აჩვენებს generic menu-ს, ნაცვლად მიმართულების კითხვისა.
🔧 guard: `_is_registration_link_request` markers + `_REGISTRATION_FORM_TOKEN_RE` (conversation_service.py:328-330)

**CF-13 — Comment post-ზე NO configured hashtag → UNCLEAR segment DM (routing menu), არა camp/adult facts** · ტიპი: 🟢 MUST PASS · სუსტი წერტილი: როცა post caption-ს არ აქვს admin/legacy hashtag, `determine_segment_from_post`-მა UNCLEAR უნდა დააბრუნოს და send_dm_from_comment-მა UNCLEAR_ROUTING menu — არასოდეს camp facts და არასოდეს adult catalogue.
1. [OPERATOR-DRIVEN] დადე INTERESTED კომენტარი „მაინტერესებს" post-ქვეშ რომელსაც NO configured hashtag აქვს caption-ში

✅ მოსალოდნელი: segment UNCLEAR; DM ორვარიანტიანი routing menu (ეკითხება camp vs adult cultural evenings), არა 2150-GEL camp DM და არა adult events list.
🔴 RED FLAG: Camp facts (2150 ლარი / ამბასადორ კაჭრეთში) ან adult-events list იგზავნება unhashtagged post-ისთვის; ან DM საერთოდ არ მოდის.
🔧 guard: `determine_segment_from_post` UNCLEAR path + send_dm_from_comment UNCLEAR branch (comment_service.py:1208-1209)
🔍 შესამოწმებელი side-effect: Private reply DM = routing menu; Sheets row segment=UNCLEAR; Redis processed_comment:{id}.

**CF-14 — Kill switch ON (AGENT_ENABLED=false) → comment სრულად იგნორირდება (no LLM, no DM, no Sheets)** · ტიპი: 🟢 MUST PASS · სუსტი წერტილი: როცა agent disabled, handle_comment-მა არ უნდა დააკლასიფიციროს intent, არ გააგზავნოს reply, არ ჩაწეროს Sheets row — dedup mark-იც არ უნდა ჩაიწეროს.
1. [OPERATOR-DRIVEN] დააყენე AGENT_ENABLED=false და restart; დადე INTERESTED კომენტარი #ბანაკი-ქვეშ

✅ მოსალოდნელი: Log ამბობს kill-switch disabled-skip context=comment; no DM, no public reply, no Sheets comment row, no OpenAI call.
🔴 RED FLAG: DM ან Sheets row (განსაკუთრებით dm_sent tagged) იქმნება disabled agent-ის დროს; OpenAI intent call fires.
🔧 guard: `kill_switch.is_agent_enabled()` gate (webhook.py:472-477)
🔍 შესამოწმებელი side-effect: No DM, no Sheets row, no processed_comment Redis key, no OpenAI usage ამ comment-ისთვის.

**CF-15 — დაწყებული camp stream (I ნაკადი, 06-23) ფილტრდება comment DM-დან start day-ზე/მის შემდეგ** · ტიპი: 🟢 MUST PASS · სუსტი წერტილი: `get_visible_camp_streams`-მა stream უნდა დამალოს `today >= start`-ისთანავე; comment rich DM-მა არ უნდა გაასაჯაროოს stream-ი რომელშიც ჩაწერა აღარ შეიძლება.
1. [OPERATOR-DRIVEN, requires clock at/after 2026-06-23] დადე INTERESTED კომენტარი #ბანაკი-ქვეშ

✅ მოსალოდნელი: 2026-06-22-ზე (დღეს) სამივე ნაკადი (23-29 ივნისი / 5-11 ივლისი / 14-20 ივლისი) ჩანს; 2026-06-23-ზე/შემდეგ I ნაკადი (23-29 ივნისი) აღარ ჩანს DM stream line-ში, რჩება მხოლოდ II და III.
🔴 RED FLAG: stream რომლის start date უკვე დადგა მაინც ჩამოთვლილია; ან ყველა stream ქრება და აგენტი იგონებს თარიღს მენეჯერის შეთავაზების ნაცვლად.
🔧 guard: `get_visible_camp_streams` / `is_camp_stream_visible` (admin_config_service.py:1167/1202) applied in build_section_dm and _build_parent_rich_dm
🔍 შესამოწმებელი side-effect: DM stream line ასახავს მხოლოდ ჯერ-არ-დაწყებულ ნაკადებს; no invented dates; registration URL still present.

---

## PARENT ↔ ADULT გადართვა + segment classifier

Segment routing ცხოვრობს `conversation_service._process_message_impl`-ში. **A-asym finding:** ADULT→PARENT გადართვა ორჯერ დეტერმინისტულად დაცულია; PARENT→ADULT გადართვას **არანაირი deterministic override არ აქვს** — sticky PARENT user-ი რომელსაც adult events უნდა რჩება PARENT, თუ stochastic LLM-მა age-gated `switch_to_adult_flow` tool არ გამოიძახა. ყველა first-message classification და ADULT→PARENT override = 🟢 MUST PASS; ყველა PARENT→ADULT გადართვა = 🟡 PROBE.

**CS-1 — First message ასახელებს camp-ს → PARENT** · ტიპი: 🟢 MUST PASS · სუსტი წერტილი: first-message classification: camp keyword დეტერმინისტულად PARENT-ზე (არა UNCLEAR menu).
1. გამარჯობა, საზაფხულო ბანაკი მაინტერესებს

✅ მოსალოდნელი: გადადის PARENT flow-ში — ეკითხება ბავშვის ასაკს („თქვენი შვილი რამდენი წლისაა?") ან აგრძელებს camp discovery-ს. NOT ორვარიანტიანი UNCLEAR menu, NOT adult-event content.
🔴 RED FLAG: აბრუნებს „ბანაკი თუ ღონისძიება?" UNCLEAR menu-ს, ან ეკითხება adult/self ასაკს, ან adult events-ზე საუბრობს.
🔧 guard: `_classify_segment` (conversation_service.py:197-228)

**CS-2 — First message ასახელებს adult event-ს → ADULT** · ტიპი: 🟢 MUST PASS · სუსტი წერტილი: first-message classification: adult-event keyword დეტერმინისტულად ADULT-ზე.
1. გამარჯობა, ზრდასრულთა კულტურული საღამო მაინტერესებს

✅ მოსალოდნელი: გადადის ADULT flow-ში — საუბრობს cultural evenings-ზე / ეკითხება ვისთვისაა ან adult-ის ასაკს. NOT camp/child content, NOT menu.
🔴 RED FLAG: ეკითხება ბავშვზე/camp-ზე, აბრუნებს camp price 2150, ან აჩვენებს UNCLEAR menu.
🔧 guard: `_classify_segment` (conversation_service.py:197-228)

**CS-3 — First message ახსენებს ორივეს — camp და adult → UNCLEAR tie-break** · ტიპი: 🟢 MUST PASS · სუსტი წერტილი: tie-break: camp AND adult stems ორივე → UNCLEAR, ხელახლა იკითხება, არასოდეს გამოიცნობს.
1. ბანაკიც მაინტერესებს და ზრდასრულთა ღონისძიებებიც

✅ მოსალოდნელი: აბრუნებს UNCLEAR routing menu-ს და სთხოვს მიმართულების არჩევას (children's camp vs adult cultural evenings). არ ირჩევს ჩუმად ერთს.
🔴 RED FLAG: ჩუმად შედის camp ან adult flow-ში მიმართულების კითხვის გარეშე.
🔧 guard: `_classify_segment` tie-break (conversation_service.py:217-218)

**CS-4 — bare price question პირველად → რჩება UNCLEAR** · ტიპი: 🟢 MUST PASS · სუსტი წერტილი: price-only message-ს არ აქვს camp/adult signal — უნდა დარჩეს UNCLEAR (adult events-საც აქვს ფასები).
1. ფასი რა ღირს?

✅ მოსალოდნელი: აბრუნებს UNCLEAR routing menu-ს (ეკითხება camp vs adult). NOT camp price 2150 GEL.
🔴 RED FLAG: პასუხობს 2150 GEL-ით ან ნებისმიერი camp/adult ფასით segment-ის დადგენამდე.
🔧 guard: `_classify_segment` (conversation_service.py:224-228)

**CS-5 — ADULT user ითხოვს camp consultation booking → deterministic flip PARENT-ზე** · ტიპი: 🟢 MUST PASS · სუსტი წერტილი: sticky ADULT segment-მა უნდა დაუთმოს ცხად consultation/reschedule intent-ს (ADULT→PARENT override).
1. ზრდასრულთა საღამო მაინტერესებს
2. ჩემი 14 წლის შვილისთვის ბანაკზე კონსულტაცია მინდა

✅ მოსალოდნელი: turn 2-ის შემდეგ flips PARENT-ზე — ამუშავებს camp consultation-ს (ეკითხება/იყენებს child age 14, მიდის booking-ისკენ). არ აგრძელებს adult-event content-ით.
🔴 RED FLAG: turn 2 მაინც პასუხობს adult-event dates/info-ით, ან იგნორირებს camp consultation request-ს.
🔧 guard: `_is_parent_consultation_intent` (conversation_service.py:257-265, applied 486-495)
🔍 შესამოწმებელი side-effect: Redis conversation segment ახლა PARENT (key conversation:<platform>:<sender_id>); no Calendar/Sheets write turn 2-ზე.

**CS-6 — ADULT user ამბობს hard camp keyword → pre-LLM switch PARENT-ზე** · ტიპი: 🟢 MUST PASS · სუსტი წერტილი: `adult_llm_engine._user_wants_parent_flow`-მ უნდა გადავიდეს hard camp keyword-ზე OpenAI call-ამდე.
1. კულტურული ღონისძიებები მაინტერესებს
2. არა, საზაფხულო ბანაკი მინდა ჩემი შვილისთვის

✅ მოსალოდნელი: turn 2 აბრუნებს deterministic camp handoff „გასაგებია, ბანაკის შესახებ დაგეხმარებით. თქვენი შვილი რამდენი წლისაა?" და segment ხდება PARENT.
🔴 RED FLAG: turn 2 რჩება adult flow-ში / ჩამოთვლის adult events / ეკითხება adult-self ასაკს ბავშვის ასაკის ნაცვლად.
🔧 guard: `_user_wants_parent_flow` (adult_llm_engine.py:431-473, applied 2021-2031)
🔍 შესამოწმებელი side-effect: segment flips PARENT, state reset START (Redis-ში persisted).

**CS-7 — ADULT user-ს უნდა adult event ბავშვისთვის → რჩება ADULT (no false switch)** · ტიპი: 🟢 MUST PASS · სუსტი წერტილი: child/relative cue adult-event signal-თან ერთად არ უნდა ააქტიუროს ADULT→PARENT switch.
1. ზრდასრულთა კულტურული საღამო მაინტერესებს ჩემი შვილისთვის

✅ მოსალოდნელი: რჩება ADULT flow-ში (იჭერს relative target / ეკითხება ბავშვის ასაკს ღონისძიებისთვის). არ გადადის camp flow-ში და არ საუბრობს summer camp-ზე.
🔴 RED FLAG: გადადის PARENT/camp flow-ში და ეკითხება camp-booking/camp-age, ან აბრუნებს camp handoff line-ს.
🔧 guard: `_ADULT_EVENT_SIGNALS` short-circuit (adult_llm_engine.py:454-466)
🔍 შესამოწმებელი side-effect: segment უნდა დარჩეს ADULT.

**CS-8 — ADULT user აძლევს bare in-range child age → NOT deterministically switch** · ტიპი: 🟡 PROBE · სუსტი წერტილი: area brief ვარაუდობდა child-age-in-range ააქტიურებს ADULT→PARENT switch-ს; კოდი ამას არ აკეთებს დეტერმინისტულად (`_user_wants_parent_flow` returns False on bare „N წლის ბავშვისთვის" camp keyword-ის გარეშე).
1. ღონისძიება მაინტერესებს
2. 14 წლის ბავშვისთვის მინდა

✅ მოსალოდნელი: deterministic camp switch არ fires; turn-ი ADULT engine-ით მუშავდება (უნდა დაიჭიროს relative target და ეკითხოს ღონისძიებაზე 14-წლიანისთვის, ან დააზუსტოს). ADULT-ში სენსიბურად დარჩენა LLM-driven-ია.
🔴 RED FLAG: ოპერატორმა იცოდე: აქ NO deterministic გარანტია. ჩავარდნა (confused routing ან forever re-asking age) = LLM-only gap, არა გატეხილი guard.
🔧 guard: `_user_wants_parent_flow` returns False (adult_llm_engine.py:468-473)
🔍 შესამოწმებელი side-effect: segment უნდა დარჩეს ADULT (no deterministic flip); გადაამოწმე child_age არ გამოიყენება adult eligibility-ად (executor ბლოკავს leakage-ს).

**CS-9 — PARENT user-ს ცხადად უნდა ღონისძიება საკუთარი თავისთვის → A-asym: LLM-only switch** · ტიპი: 🟡 PROBE · სუსტი წერტილი: carried-open A-asym: sticky PARENT user adult events-ით NO deterministic PARENT→ADULT override — მთლიანად LLM-ზე (`switch_to_adult_flow`).
1. ბანაკი მაინტერესებს
2. აა, ჩემთვის მინდა ღონისძიება, ზრდასრულთა საღამო

✅ მოსალოდნელი: იდეალურად LLM იძახებს `switch_to_adult_flow`-ს და turn 2 გადადის adult-event content-ზე. ეს NOT გარანტირებული.
🔴 RED FLAG: ოპერატორმა იცოდე LLM-only: turn 2-მ შეიძლება დარჩეს PARENT/camp-ში და ეკითხოს ბავშვის ასაკი / შესთავაზოს camp booking adult events-ის ნაცვლად — ლეგიტიმური LLM ჩავარდნა, no deterministic guard catches it.
🔧 guard: `switch_to_adult_flow` (parent_tool_executor.py:2004-2069) — LLM-invoked only; conversation_service.py:472 stickiness-ს არ აქვს PARENT→ADULT counterpart
🔍 შესამოწმებელი side-effect: შეამოწმე segment ნამდვილად flip-და ADULT-ზე Redis-ში. თუ ისევ PARENT — LLM-მა tool არ გამოიძახა (მოსალოდნელი შესაძლო ჩავარდნა).

**CS-10 — PARENT user ამბობს „ზრდასრულთა ღონისძიება" price/date-ის გარეშე → bare adult interest falls through LLM-ზე** · ტიპი: 🟡 PROBE · სუსტი წერტილი: `_maybe_handle_event_inquiry` განზრახ არ იჭერს bare adult interest-ს, ასე PARENT→ADULT გადაწყვეტა stochastic engine-ზე რჩება.
1. 14 წლის შვილი მყავს, ბანაკი მაინტერესებს
2. ზრდასრულთა ღონისძიება მაინტერესებს

✅ მოსალოდნელი: იდეალურად engine ცნობს adult-event intent-ს და იძახებს `switch_to_adult_flow`-ს (turn 2 → adult content). Not guaranteed.
🔴 RED FLAG: ოპერატორ-note: `_maybe_handle_event_inquiry` განზრახ ატარებს ამას (no price/date/specific-name), ასე no deterministic switch. camp flow-ში დარჩენა LLM-only miss, არა guard failure.
🔧 guard: `_maybe_handle_event_inquiry` bare-interest defer (parent_flow.py:2896-2898); switch_to_adult_flow LLM-only
🔍 შესამოწმებელი side-effect: დაადასტურე segment Redis-ში (PARENT vs ADULT) — LLM-მა switch გააკეთა თუ არა.

**CS-11 — PARENT user ეკითხება „ბანაკში რა ღონისძიებებია?" → NOT switch (camp keyword present)** · ტიპი: 🟢 MUST PASS · სუსტი წერტილი: event question რომელიც camp-ს ასახელებს არ უნდა მოიტაცოს adult flow-ში — `_maybe_handle_event_inquiry` ბაილს აკეთებს hard camp keyword-ზე.
1. საზაფხულო ბანაკი მაინტერესებს
2. ბანაკში რა ღონისძიებებია?

✅ მოსალოდნელი: რჩება PARENT/camp flow-ში (event-inquiry interceptor returns None on hard camp keywords, ასე camp engine პასუხობს). არ გადადის ADULT cultural-events flow-ში.
🔴 RED FLAG: გადადის ADULT flow-ში / ჩამოთვლის adult cultural evenings, ან აბრუნებს adult ticket links.
🔧 guard: `_maybe_handle_event_inquiry` hard-camp bail (parent_flow.py:2890-2892)
🔍 შესამოწმებელი side-effect: segment უნდა დარჩეს PARENT.

**CS-12 — bare greeting პირველად → UNCLEAR menu (არა auto-PARENT)** · ტიპი: 🟢 MUST PASS · სუსტი წერტილი: სუფთა greeting-მა UNCLEAR-ზე უნდა გადავიდეს (Phase 3.6A), არა ჩუმად რომელიმე flow-ში.
1. გამარჯობა

✅ მოსალოდნელი: აბრუნებს UNCLEAR routing menu-ს (ეკითხება camp vs adult cultural evenings). არ შედის camp ან adult flow-ში.
🔴 RED FLAG: დაუყოვნებლივ ეკითხება ბავშვის ასაკს / შედის camp flow-ში, ან იწყებს adult-event content-ს.
🔧 guard: `_is_pure_greeting` + `_classify_segment` (conversation_service.py:146-156, 209-210)

**CS-13 — Sticky PARENT ჯავშნის შემდეგ — adult-interest არ უნდა გააფუჭოს booking, switch ისევ LLM-only** · ტიპი: 🟡 PROBE · სუსტი წერტილი: booked PARENT lead force-kept PARENT (booked-state guard); adult-interest message-ს შემდეგ no deterministic switch და არ უნდა დააზიანოს booking.
1. 14 წლის შვილი, ბანაკზე კონსულტაცია მინდა
2. 595999733, ჯონი
3. კი, ხვალ 15 საათზე
4. ახლა ჩემთვის ზრდასრულთა საღამო მინდა

✅ მოსალოდნელი: booking turns 1-3-დან ხელუხლებელი რჩება; turn 4 ან გადადის ADULT-ზე LLM tool-ით ან თავაზიანად ამუშავებს adult interest-ს. booked child_age/booking უნდა შენარჩუნდეს (lead untouched by any switch).
🔴 RED FLAG: ოპერატორ-note: PARENT→ADULT turn 4-ზე LLM-only (may not switch). მძიმე ჩავარდნა = booked child_age-ის ან booking-ის დაკარგვა/გადაწერა — ეს რეალური დეფექტია, ესკალაცია.
🔧 guard: booked-state stickiness (conversation_service.py:472-478); switch_to_adult_flow preserves lead (parent_tool_executor.py:2008-2009)
🔍 შესამოწმებელი side-effect: გადაამოწმე Calendar event + Sheets row turns 1-3-დან NOT cancelled/altered turn 4-ით; child_age რჩება 14.

---

## Camp-stream date filter + admin-config facts

ეს ქვესისტემა მართავს (1) რომელი ნაკადი ჩანს მომხმარებლისთვის ცოცხალი Asia/Tbilisi თარიღით და (2) რომ ყველა camp ფაქტი (ფასი, ასაკი, ლოკაცია, მენეჯერის ნომერი, registration URL, ნაკადები) admin_config-დან მოდის (camp_2026.yaml fallback-ით) — არასოდეს კოდში გამოგონილი. **DATE-SENSITIVE სცენარები:** მათი მოსალოდნელი შედეგი დამოკიდებულია ცოცხალ run-თარიღზე 06-23/07-05/07-14-თან მიმართებაში — ოპერატორმა უნდა გაიყინოს/გაასიმულიროს საათი ან გაუშვას ზუსტ თარიღზე.

**DF-1 — დღეს 2026-06-22 edge — ნაკადი I (06-23) ჯერ ჩანს (today<start)** · ტიპი: 🟢 MUST PASS · სუსტი წერტილი: off-by-one start-day boundary-ზე: `is_camp_stream_visible`-მა ნაკადი I ხილული უნდა შეინარჩუნოს სანამ today (06-22) < start (06-23) და დამალოს 06-23-ზე.
1. გამარჯობა, ბანაკით ვარ დაინტერესებული
2. 12 წლის არის ჩემი შვილი
3. ბანაკი როდის ტარდება? რა ნაკადებია?

✅ მოსალოდნელი: DATE-SENSITIVE (გაუშვი 2026-06-22): აგენტი ჩამოთვლის სამივე რეალურ ნაკადს I 23-29 ივნისი, II 5-11 ივლისი, III 14-20 ივლისი (ნაკადი I ისევ მომავალი, today 06-22 < 06-23). No invented dates. ნაკადები ზუსტად როგორც კონფიგურირებული.
🔴 RED FLAG: ნაკადი I (23-29 ივნისი) ჩამოგდებულია 2026-06-22-ზე (off-by-one), ან config-ში არარსებული ნაკადი ჩნდება, ან თარიღები paraphrased/altered.
🔧 guard: `is_camp_stream_visible` / `_parse_camp_stream_start_date` / `_get_camp_info` dates topic

**DF-2 — 06-23-ზე/შემდეგ — ნაკადი I იმალება (today>=start), II & III ისევ ჩამოთვლილია** · ტიპი: 🟢 MUST PASS · სუსტი წერტილი: ნაკადი რომელმაც start day მიაღწია უნდა შეწყვიტოს გასაჯაროება status=active-ის მიუხედავად.
1. გამარჯობა
2. ბანაკი მაინტერესებს, ნაკადების თარიღები მინდა ვიცოდე
3. 13 წლის ბავშვი მყავს

✅ მოსალოდნელი: DATE-SENSITIVE (გაუშვი 2026-06-23+, 07-05-ამდე): აგენტი ჩამოთვლის მხოლოდ II 5-11 ივლისი და III 14-20 ივლისი. ნაკადი I (23-29 ივნისი) არ იხსენიება. No invented replacement date.
🔴 RED FLAG: ნაკადი I ისევ ჩამოთვლილია 06-23-ზე/შემდეგ; ან აგენტი იგონებს ახალ June stream-ს.
🔧 guard: `is_camp_stream_visible` (today>=start → hidden) / `_get_camp_info`

**DF-3 — 07-05-ზე/შემდეგ — მხოლოდ ნაკადი III (14-20 ივლისი) რჩება** · ტიპი: 🟢 MUST PASS · სუსტი წერტილი: sequential hiding: I და II ორივე უნდა დაიმალოს start days-ის გავლის შემდეგ.
1. გამარჯობა, რომელ ნაკადებზე ჯერ კიდევ შეიძლება ჩაწერა?
2. 11 წლის ბავშვისთვის

✅ მოსალოდნელი: DATE-SENSITIVE (გაუშვი 2026-07-05..07-13): აგენტი ჩამოთვლის მხოლოდ III 14-20 ივლისი. ნაკადები I და II გაქრა. No invented dates.
🔴 RED FLAG: ნაკადი I ან II ისევ ჩამოთვლილია start dates-ის შემდეგ; ან აგენტი ამბობს „all streams full" რეალური III-ის ჩამოთვლის ნაცვლად.
🔧 guard: `is_camp_stream_visible` / `get_visible_camp_streams`

**DF-4 — ყველა ნაკადი დამალულია (07-14-ზე/შემდეგ) — აგენტმა NOT invent dates, შესთავაზოს manager/registration** · ტიპი: 🟡 PROBE · სუსტი წერტილი: empty visible-stream list. DATE FILTER გარანტირებს []-ს; მაგრამ აგენტი თავს არიდებს თუ არა stream-ის ჰალუცინაციას და გთავაზობს manager/registration-ს PROMPT-only-ია.
1. გამარჯობა, ბანაკის თარიღები მაინტერესებს
2. 14 წლის შვილი მყავს
3. ცარიელი ნაკადი თუ დარჩა, რომელ რიცხვებში?

✅ მოსალოდნელი: DATE-SENSITIVE (გაუშვი 2026-07-14+): აგენტი NOT states any specific stream dates (tool returned no streams), და სთავაზობს მენეჯერს (558 67 47 33) და/ან registration link / ამბობს რომ შეამოწმებს — არასოდეს იგონებს თარიღს როგორც „21-27 ივლისი".
🔴 RED FLAG: იგონებს config-ში არარსებულ stream date-ს (fabricated late-July/August), ან თავდაჯერებულად ამბობს რომ streams არსებობს როცა get_visible_camp_streams returned [].
🔧 guard: `get_visible_camp_streams` (empty) + system_parent_v2.md no-invent rule (LLM_ONLY)
🔍 შესამოწმებელი side-effect: გადაამოწმე no fabricated date surfaces; request_manager_callback შეიძლება შესთავაზოს მაგრამ არ არის required ამ turn-ზე.

**DF-5 — Registration link Admin config-დან დეტერმინისტულად (no age question, no menu)** · ტიპი: 🟢 MUST PASS · სუსტი წერტილი: registration request-მა ზუსტი Admin registration_url engine-ამდე უნდა დააბრუნოს, არასოდეს გამოიგონოს და არ ჰკითხოს ბავშვის ასაკი ჯერ.
1. გამარჯობა, სად დავრეგისტრირდე ბანაკზე? ბმული მომწერეთ

✅ მოსალოდნელი: აგენტი აბრუნებს Admin registration link https://tinyurl.com/36jcae8z დეტერმინისტულად, NO „რამდენი წლისაა შვილი?" და NO ორვარიანტიანი menu.
🔴 RED FLAG: ეკითხება ბავშვის ასაკს ჯერ / აჩვენებს brand menu-ს / აბრუნებს განსხვავებულ ან გამოგონილ URL-ს / ამბობს „ბმულს მოგვიანებით გამოგიგზავნით".
🔧 guard: `_maybe_handle_camp_registration_link` / `_render_camp_registration_answer` (reads get_camp_facts().registration_url)

**DF-6 — „ინფორმაცია მინდა" NOT trigger registration link (ფორმა word-boundary)** · ტიპი: 🟢 MUST PASS · სუსტი წერტილი: raw-substring „ფორმა" „ინფორმაცია"-ში ადრე over-fire-ს აკეთებდა; `_CAMP_FORM_TOKEN_RE`-მ უნდა გამორიცხოს.
1. გამარჯობა, ბანაკის შესახებ ინფორმაცია მინდა

✅ მოსალოდნელი: აგენტი NOT dumps registration link-ს; აგრძელებს normal camp discovery-ს (ეკითხება ასაკს / აძლევს camp info). „ინფორმაცია" request info-დ მუშავდება, არა form request-ად.
🔴 RED FLAG: აბრუნებს https://tinyurl.com/36jcae8z როგორც registration-form answer information request-ზე (over-fire bug).
🔧 guard: `_CAMP_FORM_TOKEN_RE` (?<![ა-ჰ])ფორმ(?!ატ) / `_is_camp_registration_link_request`

**DF-7 — ფასი ყოველთვის admin config-დან (price_text='2150' → 2150 GEL)** · ტიპი: 🟢 MUST PASS · სუსტი წერტილი: ფასი admin price_text/price_gel-დან get_camp_facts-ით, არასოდეს hardcoded/invented.
1. გამარჯობა, ბანაკი მაინტერესებს
2. 13 წლის არის
3. ფასი რა ღირს?

✅ მოსალოდნელი: აგენტი ასახელებს 2150 ლარს (admin config price_text/price_gel-დან). ფასის ციფრი წარმოდგენილია.
🔴 RED FLAG: 2150-ისგან განსხვავებული ფასი (მაგ. 2200, ძველი stale value, invented), ან ფასის ციფრი საერთოდ აკლია.
🔧 guard: `get_camp_facts` (parse_price_gel(price_text) wins) / `_get_camp_info` price topic

**DF-8 — ლოკაცია ყოველთვის admin config-დან (ამბასადორი კაჭრეთი, no „აკადემია" appended)** · ტიპი: 🟢 MUST PASS · სუსტი წერტილი: ლოკაცია ზუსტი admin string; code/prompt კრძალავს „აკადემია"-ს დართვას „კაჭრეთი"-ს შემდეგ.
1. გამარჯობა
2. 12 წლის შვილი მყავს, ბანაკით დავინტერესდი
3. სად ტარდება ბანაკი?

✅ მოსალოდნელი: აგენტი ასახელებს ლოკაციას ამბასადორი კაჭრეთი (ზუსტი admin value). No invented venue.
🔴 RED FLAG: ლოკაცია altered/invented, ან „აკადემია" დართულია „კაჭრეთი"-ს შემდეგ, ან განსხვავებული ქალაქი/venue.
🔧 guard: `get_camp_facts` (admin location wins) / `_get_camp_info` location topic

**DF-9 — ასაკის დიაპაზონი ყოველთვის admin config-დან (9-17), '9-17' NOT quoted როგორც stream date** · ტიპი: 🟢 MUST PASS · სუსტი წერტილი: ასაკის დიაპაზონი admin age_min/age_max-დან; camp range არ უნდა აერიოს stream date-ში.
1. გამარჯობა, რა ასაკის ბავშვებს იღებთ ბანაკში?

✅ მოსალოდნელი: აგენტი ასახელებს ასაკის დიაპაზონს 9-17 წელი (admin age_min=9/age_max=17-დან). No mixing with stream dates.
🔴 RED FLAG: 9-17-ისგან განსხვავებული დიაპაზონი, ან '9-17' stream date-ად, ან invented age band.
🔧 guard: `get_camp_facts` (age_min/age_max admin int wins) / `_get_camp_info` age_range topic

**DF-10 — მენეჯერის ნომერი ყოველთვის admin manager_contact-დან (558 67 47 33)** · ტიპი: 🟢 MUST PASS · სუსტი წერტილი: მენეჯერის ტელეფონი get_manager_phone chain-დან / get_camp_facts manager_contact override-დან, არასოდეს hardcoded-divergent.
1. გამარჯობა
2. 8 წლის ბავშვი მყავს, ბანაკში ჩავწერდი

✅ მოსალოდნელი: რადგან ასაკი 8 < age_min 9, აგენტი უარს ამბობს camp enrollment-ზე ამ ასაკისთვის და სთავაზობს მენეჯერს — ნომერი, გაცემისას, არის 558 67 47 33 (admin config-დან). 9-17 range stated.
🔴 RED FLAG: 558 67 47 33-ისგან განსხვავებული ნომერი, ან აგენტი სთავაზობს camp enrollment-ს 8-წლიანისთვის, ან no manager/ineligible handling.
🔧 guard: `get_manager_phone` chain / `get_camp_facts` manager_contact override + `_ensure_ineligible_young_age_message`
🔍 შესამოწმებელი side-effect: none ამ disclosure turn-ზე; გადაამოწმე NO Calendar/Sheets booking ineligible ბავშვისთვის.

**DF-11 — Operator price edit propagates restart-ის გარეშე (admin-first, cache-free)** · ტიპი: 🟢 MUST PASS · სუსტი წერტილი: `_safe_load_yaml` cache-free-ია ასე Admin Panel edit price_text-ზე უნდა იყოს მომდევნო პასუხი; parsed price_text wins over stale price_gel.
1. [OPERATOR: edit summer_camp price_text to '2300' in /admin/programs/summer_camp and save]
2. გამარჯობა, ბანაკის ფასი რა არის?

✅ მოსალოდნელი: operator save-ის შემდეგ, ზუსტად მომდევნო პასუხი ასახელებს 2300 ლარს (ახალი price_text), ამტკიცებს რომ admin edit propagated get_camp_facts-ით server restart-ის გარეშე. parse_price_gel('2300')=2300 overrides stale price_gel.
🔴 RED FLAG: ისევ ძველ 2150-ს ასახელებს save-ის შემდეგ (stale cache / restart required), ან leftover price_gel რომელიც price_text-ს არ ემთხვევა.
🔧 guard: `_safe_load_yaml` (cache-free) / `get_camp_facts` (parsed price_text wins) / `_get_camp_info`
🔍 შესამოწმებელი side-effect: sections.yaml summer_camp.price_text updated + .bak rotation; **დააბრუნე edit-ი შემდეგ.**

**DF-12 — Operator stream date edit propagates და date filter ხელახლა აპლიცირდება new value-ზე** · ტიპი: 🟢 MUST PASS · სუსტი წერტილი: operator-edited stream dates_text get_camp_facts-ით get_visible_camp_streams-ში უნდა გავიდეს და იმავე today<start rule-ით ფილტრდეს/ჩანდეს.
1. [OPERATOR: edit summer_camp streams — change III to dates_text '21-27 ივლისი' and save]
2. გამარჯობა, ბანაკის ნაკადების თარიღები მინდა
3. 10 წლის შვილი მყავს

✅ მოსალოდნელი: DATE-SENSITIVE (გაუშვი 2026-07-21-ამდე): აგენტი ჩამოთვლის edited ნაკადს III როგორც 21-27 ივლისი (ახალი admin value), ისევ today<start filter-ის ქვეშ. ცვლილება restart-ის გარეშე და თარიღი verbatim, არა invented.
🔴 RED FLAG: ისევ ძველ 14-20 ივლისს აჩვენებს save-ის შემდეგ, ან stream date რომელიც არც ძველს და არც ახალ admin value-ს ემთხვევა.
🔧 guard: `get_camp_facts` (admin streams normalised) / `get_visible_camp_streams` / `_get_camp_info` dates topic
🔍 შესამოწმებელი side-effect: sections.yaml summer_camp.streams[III].dates_text updated + .bak rotation; **დააბრუნე edit-ი შემდეგ.**

**DF-13 — Inactive ნაკადი იმალება მომავალი თარიღის მიუხედავად** · ტიპი: 🟢 MUST PASS · სუსტი წერტილი: `is_camp_stream_visible`-მა stream-ი რომლის status!='active' (ან active=False) უნდა დამალოს მაშინაც როცა start date მომავალშია.
1. [OPERATOR: set stream II (5-11 ივლისი) status to 'hidden' / inactive in /admin and save]
2. გამარჯობა, რომელ ნაკადებზე შეიძლება ჩაწერა? თარიღები მინდა
3. 12 წლის ბავშვი

✅ მოსალოდნელი: DATE-SENSITIVE (გაუშვი 07-05-ამდე ასე II სხვა შემთხვევაში მომავალი იქნებოდა): აგენტი NOT lists stream II 5-11 ივლისი მისი მომავალი თარიღის მიუხედავად, რადგან inactive-ია. მხოლოდ active upcoming streams ჩანს.
🔴 RED FLAG: stream II (5-11 ივლისი) ისევ ჩამოთვლილია inactive-ად დაყენების შემდეგ (status guard ignored).
🔧 guard: `is_camp_stream_visible` (status!='active' → hidden)
🔍 შესამოწმებელი side-effect: sections.yaml summer_camp.streams[II].status changed; **დააბრუნე შემდეგ.**

**DF-14 — Registration link missing config-ში → აგენტი NOT invent, offers manager** · ტიპი: 🟢 MUST PASS · სუსტი წერტილი: როცა registration_url ცარიელია, `_render_camp_registration_answer` / get_camp_info('registration')-მა manager contact-ზე უნდა გადავიდეს, არასოდეს გამოიგონოს URL.
1. [OPERATOR: clear summer_camp registration_url (set to empty) in /admin and save]
2. გამარჯობა, ბანაკზე რეგისტრაციის ბმული მომწერეთ

✅ მოსალოდნელი: აგენტი ამბობს რომ registration link ამჟამად სისტემაში არ არის და სთავაზობს მენეჯერს (558 67 47 33) / ითხოვს name+phone — NOT outputs any URL.
🔴 RED FLAG: outputs ANY registration URL (ძველი tinyurl, ან invented link) როცა registration_url ცარიელია.
🔧 guard: `_render_camp_registration_answer` (empty-url fallback) / `_get_camp_info` registration topic (reason=registration_url_missing)
🔍 შესამოწმებელი side-effect: sections.yaml summer_camp.registration_url cleared; **დააბრუნე შემდეგ (restore https://tinyurl.com/36jcae8z).**

**DF-15 — Unparseable stream date იმალება (no garbage date offered)** · ტიპი: 🟢 MUST PASS · სუსტი წერტილი: non-empty მაგრამ unparseable dates_text უნდა დაიმალოს (hidden+warn), არა surface-დეს literal junk date-ად.
1. [OPERATOR: add a stream with dates_text 'მალე გამოვაცხადებთ' (no month) status active, save]
2. გამარჯობა, ბანაკის ყველა ნაკადის თარიღი მინდა ვიცოდე
3. 13 წლის ბავშვი

✅ მოსალოდნელი: აგენტი ჩამოთვლის მხოლოდ რეალურ parseable upcoming streams-ს და NOT surfaces unparseable 'მალე გამოვაცხადებთ' stream-ს როგორც date-ს. junk stream ჩუმად იმალება (warning logged server-side).
🔴 RED FLAG: ციტირებს 'მალე გამოვაცხადებთ'-ს stream date-ად, ან surface-ს unparseable entry-ს dates list-ში.
🔧 guard: `is_camp_stream_visible` (start is None → hidden + warning log) / `_parse_camp_stream_start_date` returns None
🔍 შესამოწმებელი side-effect: sections.yaml streams gains/loses test entry; server log carries '[admin_config] camp stream … unparseable dates_text … hidden'; **დააბრუნე შემდეგ.**

**DF-16 — „ბანაკის ნაკადი" question არასოდეს აბრუნებს camp-age-range/consultation slot-ს stream date-ად** · ტიპი: 🟡 PROBE · სუსტი წერტილი: აგენტმა consultation/booking dates და age band program stream dates-ისგან ცალკე უნდა შეინარჩუნოს; მხოლოდ get_visible_camp_streams values არის stream dates.
1. გამარჯობა, ბანაკი მაინტერესებს
2. 14 წლის შვილი მყავს
3. ბანაკის ნაკადები რომელ რიცხვებშია?

✅ მოსალოდნელი: DATE-SENSITIVE (2026-06-22): აგენტი ჩამოთვლის რეალურ ხილულ ნაკადებს (I/II/III 06-22-ზე) program dates-ად და NOT confuses consultation booking slots-თან ან 9-17 age band-თან.
🔴 RED FLAG: წარმოადგენს consultation slot date-ს ან age range '9-17'-ს camp stream-ად, ან merges booking availability stream list-ში.
🔧 guard: system_parent_v2.md 'კონსულტაცია vs ბანაკის ნაკადები' (LLM_ONLY) + `_get_camp_info` dates

---

## Notifications & side-effects

ეს ქვესისტემა ფლობს PARENT flow-ის ყველა შეუქცევად side-effect-ს. წარმატებული consultation booking ერთადერთი path-ია რომელიც სამივე side-effect-ს ერთად წერს: ONE Google Calendar event + ONE A-anchored Sheets row (A-Q, 17 cols) + manager notification (Gmail email + WhatsApp parallel). **ცოცხალი caveats:** WhatsApp prod-ში unconfigured-ია → booking-ის manager-notify პრაქტიკულად email-only; Sheets/Calendar failures swallowed (logged) და NOT roll back Calendar booking.

**SE-1 — წარმატებული booking წერს ზუსტად ONE Calendar event + ONE A-Q Sheets row + manager email** · ტიპი: 🟢 MUST PASS · სუსტი წერტილი: full happy-path side-effect fan-out: Calendar + Sheets(A-Q aligned) + manager notification სწორი name/phone/age/datetime-ით.
1. გამარჯობა, საზაფხულო ბანაკი მაინტერესებს
2. 14 წლის არის
3. კონსულტაციის ჩაწერა მინდა
4. ნიკა, 595123456
5. ხვალ 15 საათზე
6. კი, მაწყობს

✅ მოსალოდნელი: აგენტი ადასტურებს კონსულტაციას ერთხელ (თარიღი + საათი + „მენეჯერი დაგიკავშირდებათ"). Calendar-ში ზუსტად ერთი event ხვალ 15:00; Sheets-ში ერთი ახალი row, A-Q სწორად (Name=ნიკა, Phone=595123456, Child Age=14, Consultation Booked=TRUE, Status=Booked); მენეჯერს email სწორი სახელით/ნომრით/ასაკით/თარიღით.
🔴 RED FLAG: ორი Calendar event ან ორი Sheets row; row columns გადაწეული (Name სვეტში ტელეფონი); Consultation Booked=FALSE ჯავშნის მერე; „ჩაგინიშნეთ" Calendar event_id-ის გარეშე; თარიღი/საათი არ ემთხვევა.
🔧 guard: Successful booking side-effect chain; A-anchored Sheets row alignment
🔍 შესამოწმებელი side-effect: Calendar: ზუსტად ONE event ხვალ 15:00 (60 min). Sheets Leads: ONE new row, A-Q aligned, A=numeric ID, Name=ნიკა, Phone=595123456, Child Age=14, Consultation Booked=TRUE, Status=Booked, Created/Last-Activity Asia/Tbilisi +04:00. Manager email: ONE email, subject „ნიკა — ახალი კონსულტაცია AI Agent-იდან", body ასაკი 14 + ტელეფონი 595123456 + booked datetime Georgian-ად. WhatsApp: prod-ში (unconfigured) NO WhatsApp; გადაამოწმე log [NOTIFICATION][WHATSAPP] Skipped.

**SE-2 — Busy slot rejected with alternatives — NO Calendar/Sheets/email side effect** · ტიპი: 🟢 MUST PASS · სუსტი წერტილი: taken slot-მა fake confirmation ან რაიმე side effect არ უნდა წარმოქმნას.
1. გამარჯობა საზაფხულო ბანაკი
2. 13 წლისაა
3. კონსულტაცია მინდა
4. ლევანი 595777888
5. 16 საათზე მინდა (გამოიყენე datetime ცნობილი busy block-ით)
6. კი

✅ მოსალოდნელი: აგენტი ამბობს რომ 16:00 დაკავებულია/არ ინიშნება და სთავაზობს ალტერნატიულ საათებს. არანაირი Calendar event, არანაირი Sheets row, არანაირი მენეჯერის email ამ slot-ისთვის.
🔴 RED FLAG: ადასტურებს 16:00-ს; Calendar-ში event დაკავებულ დროზე; Sheets row Booked-ით; email გადის.
🔧 guard: Slot-unavailable / busy rejection
🔍 შესამოწმებელი side-effect: Calendar: NO new event busy datetime-ზე. Sheets: NO new Booked row. Manager email: NO booking email.

**SE-3 — ნაკლები ასაკის (7yo) handoff with contact — manager notification, NO Calendar, NO Sheets** · ტიპი: 🟢 MUST PASS · სუსტი წერტილი: under-age handoff message-only; უნდა გააგზავნოს operator message და NOT write Calendar/Sheets; success claimed only on real dispatch.
1. გამარჯობა, ბანაკი მაინტერესებს
2. 7 წლისაა ჩემი შვილი
3. კი, დამაკავშირეთ მენეჯერთან
4. მარიამი, 595444333

✅ მოსალოდნელი: აგენტი ჯერ ეუბნება რომ ბანაკი 9-17 წლისაა და სთავაზობს მენეჯერთან დაკავშირებას; კონტაქტის შემდეგ პასუხობს „ინფორმაცია მენეჯერს გადავეცი. მენეჯერი მალე დაგიკავშირდებათ" — და ეს მხოლოდ თუ რეალურად გაიგზავნა (email/whatsapp).
🔴 RED FLAG: ამბობს „მენეჯერს გადავეცი", მაგრამ არცერთი არხი არ გაგზავნა (false success); Calendar event; Sheets row 7-წლიანი ბავშვით; ხელახლა ეკითხება ასაკს.
🔧 guard: Under-age manager handoff (message-only, real-dispatch only); notify_manager_handoff OR-semantics + no Sheets/Calendar
🔍 შესამოწმებელი side-effect: Manager email: ONE email, subject „მენეჯერთან გადასაცემი მოთხოვნა — მარიამი", body „ხელით გადასაცემი მოთხოვნა (კონსულტაცია არ დაჯავშნილა)." + სახელი მარიამი + ტელეფონი 595444333 + მიზეზი. Calendar: NO event. Sheets Leads: NO new row. თუ email AND whatsapp ორივე ჩავარდა, აგენტმა NOT claim success (fallback contact 558 67 47 33).

**SE-4 — Under-age handoff idempotent — no double dispatch** · ტიპი: 🟢 MUST PASS · სუსტი წერტილი: კონტაქტის ხელახალი გაგზავნა დასრულებული handoff-ის შემდეგ არ უნდა ისროლოს მეორე manager notification.
1. 8 წლისაა შვილი, მენეჯერთან დამაკავშირეთ
2. გიორგი 595111222
3. კიდევ ერთხელ გადაეცი მენეჯერს, 595111222

✅ მოსალოდნელი: პირველი contact turn → „ინფორმაცია მენეჯერს გადავეცი". მეორე თხოვნა → „თქვენი მონაცემები მენეჯერს უკვე გადავეცი" (იდემპოტენტური, ხელახლა არ აგზავნის).
🔴 RED FLAG: მეორე email გადის იმავე ლიდისთვის; ან აგენტი თავიდან ამბობს „გადავეცი" თითქოს ახალი dispatch მოხდა.
🔧 guard: Under-age manager handoff (message-only, real-dispatch only)
🔍 შესამოწმებელი side-effect: Manager email: ზუსტად ONE handoff email ამ sender-ისთვის ორივე turn-ზე (მეორე turn-მა NOT add მეორე email).

**SE-5 — Under-age handoff ითხოვს მხოლოდ ნაკლულ ველს (no premature dispatch)** · ტიპი: 🟢 MUST PASS · სუსტი წერტილი: არასრულმა კონტაქტმა არ უნდა გააგზავნოს და არ უნდა თქვას რომ name/number გაიგზავნა.
1. 6 წლისაა, მენეჯერი მინდა
2. 595999000

✅ მოსალოდნელი: ასაკის ქვემოთ → სთავაზობს მენეჯერს და ითხოვს სახელ+ნომერს; როცა მხოლოდ ნომერი მოვა → „ნომერი მივიღე. მომწერეთ თქვენი სახელი, რომ მენეჯერს გადავცე" — არ აგზავნის, არ ამბობს „გადავეცი".
🔴 RED FLAG: ამბობს „მენეჯერს გადავეცი" მხოლოდ ნომრით (სახელის გარეშე); email გადის არასრული მონაცემებით.
🔧 guard: Under-age manager handoff (message-only, real-dispatch only)
🔍 შესამოწმებელი side-effect: Manager email: NO email (only phone known, name missing). Calendar/Sheets: none.

**SE-6 — Kill switch ON (AGENT_ENABLED=false) აბრუნებს disabled message-ს და არაფერს აკეთებს** · ტიპი: 🟢 MUST PASS · სუსტი წერტილი: disabled agent-ის დროს no OpenAI/Calendar/Sheets/email/Meta call.
1. გამარჯობა, კონსულტაცია მინდა ხვალ 15 საათზე, ნიკა 595123456, შვილი 14 წლისაა

✅ მოსალოდნელი: აგენტი აბრუნებს ზუსტად AGENT_DISABLED_MESSAGE-ს („ამ მომენტში ავტომატური ასისტენტი დროებით გათიშულია. მოგვწერეთ და მენეჯერი დაგიკავშირდებათ.") და არაფერს აკეთებს.
🔴 RED FLAG: ჩვეულებრივ პასუხობს/ჯავშნის; Calendar event; Sheets row; email; ლოგებში OpenAI call. ან აბრუნებს სხვა (არა-კანონიკურ) disabled-ფრაზას.
🔧 guard: Kill switch — AGENT_ENABLED gate; AGENT_DISABLED_MESSAGE canonical string
🔍 შესამოწმებელი side-effect: დააყენე AGENT_ENABLED=false .env-ში + restart. გადაამოწმე NO Calendar event, NO Sheets row, NO manager email, log [kill_switch] AGENT_ENABLED=false; skipped context=dm. **ხელახლა ჩართე შემდეგ.**

**SE-7 — Admin price edit ასახულია მომდევნო „ფასი?"-ზე restart-ის გარეშე** · ტიპი: 🟢 MUST PASS · სუსტი წერტილი: operator price edit get_camp_facts()-ით (cache-free) get_camp_info tool-ში; price_gel re-derived price_text-დან.
1. [operator: edit summer_camp price_text in /admin/programs/summer_camp to a new value, save]
2. ფასი რამდენია ბანაკის?

✅ მოსალოდნელი: აგენტი ასახელებს ახალ ფასს (operator-ის ახალი price_text), არა ძველ 2150-ს; restart საჭირო არ არის.
🔴 RED FLAG: ისევ ძველ ფასს (2150) ასახელებს; ან price_gel/price_text ერთმანეთს არ ემთხვევა (stale price_gel).
🔧 guard: Admin price edit -> price_gel re-derivation; get_camp_info reads admin-first, cache-free
🔍 შესამოწმებელი side-effect: sections.yaml: summer_camp price_text = new value AND price_gel re-derived (არა stale 2150). .bak rotated. **დააბრუნე edit-ი შემდეგ.**

**SE-8 — Manager-number request NOT re-ask parent's own number როცა known** · ტიპი: 🟢 MUST PASS · სუსტი წერტილი: context-aware manager-number disclosure: 558 67 47 33 და როცა phone უკვე lead-ზეა, არ ხელახლა იკითხება.
1. გამარჯობა, ბანაკი, 14 წლისაა, ჩემი ნომერია 595123456
2. მენეჯერის ნომერი მომეცით

✅ მოსალოდნელი: აგენტი ასახელებს მენეჯერის ნომერს 558 67 47 33 და ამბობს „მენეჯერი ასევე თავად დაგიკავშირდებათ" — ხელახლა არ ითხოვს მომხმარებლის ნომერს.
🔴 RED FLAG: უარს ამბობს ნომრის გაცემაზე; ან ხელახლა ითხოვს მომხმარებლის ნომერს; ან იგონებს სხვა ნომერს.
🔧 guard: Explicit manager-number disclosure (context-aware)

**SE-9 — Phone correction before commit განაახლებს lead-ს, no Calendar/Sheets touch** · ტიპი: 🟢 MUST PASS · სუსტი წერტილი: contact correction overwrites set lead.phone in-memory only; never write Calendar/Sheets/notifications.
1. გამარჯობა, ბანაკი, 13 წლისაა, კონსულტაცია მინდა
2. ლუკა 595000111
3. ნომერი შევცდი, სწორია 595000222

✅ მოსალოდნელი: აგენტი ადასტურებს შესწორებას („ნომერი შევასწორე — 595 000 222") და lead.phone ხდება 595000222; არანაირი Calendar/Sheets/email ამ turn-ზე.
🔴 RED FLAG: ნომერი არ განახლდა (ისევ 595000111); ან correction-მა Sheets/Calendar/email ჩაწერა გამოიწვია; ან „მენეჯერს გადავეცი" ცრუ წარმატება.
🔧 guard: Contact correction (phone/name) — in-memory only
🔍 შესამოწმებელი side-effect: Sheets/Calendar/email: NONE correction turn-ზე. გადაამოწმე ნებისმიერი მოგვიანებითი booking row ატარებს corrected 595000222-ს.

**SE-10 — Calendar-success მაგრამ Sheets-fail NOT roll back booking (operator data-integrity check)** · ტიპი: 🟡 PROBE · სუსტი წერტილი: Sheets/email failures swallowed და NOT roll back Calendar event — Calendar event შეიძლება არსებობდეს no CRM row-ით.
1. გამარჯობა საზაფხულო ბანაკი 12 წლისაა კონსულტაცია
2. ანა 595333222
3. ხვალ 11 საათზე
4. კი დამიდასტურე

✅ მოსალოდნელი: Calendar event იქმნება და აგენტი ადასტურებს; თუ Sheets append ჩავარდა (log '[parent_flow] Sheets append FAILED'), booking მაინც წარმატებულად რჩება — ეს by-design და ოპერატორმა ხელით უნდა შეავსოს CRM.
🔴 RED FLAG: აგენტი ცრუდ ამბობს „CRM-ში ჩაიწერა" Sheets-ის ჩავარდნისას; ან booking rollback-დება Sheets-ფეილზე ისე რომ Calendar event მაინც რჩება (orphan).
🔧 guard: Successful booking side-effect chain
🔍 შესამოწმებელი side-effect: თუ Sheets degraded, გადაამოწმე Calendar event STILL exists (booking not rolled back) და operator log carries Sheets-FAILED warning manual CRM backfill-ისთვის. ეს deliberate non-rollback, არა guard failure.

**SE-11 — LLM hallucinated confirmation real tool-success-ის გარეშე scrubbed** · ტიპი: 🟢 MUST PASS · სუსტი წერტილი: book_consultation_success_for_conversation flag gates final fake-booking sanitiser; confirmation phrase no Calendar write-ით უნდა stripped.
1. გამარჯობა ბანაკი 14 წლისაა
2. ფასი რა ღირს და კონსულტაცია როდის შეიძლება?
3. კარგად შეამოწმე, ხვალ 16:00 ნამდვილად თავისუფალია?

✅ მოსალოდნელი: availability-ის გადამოწმების კითხვაზე აგენტი ხელახლა ამოწმებს slot-ს (check_consultation_slot) და არ ამბობს „ჩაგინიშნეთ" წინასწარ; verification turn არ ქმნის Calendar event-ს.
🔴 RED FLAG: ამბობს „ჩაგინიშნეთ/დაჯავშნილია" tool-success-ის გარეშე (book_consultation_success flag False) და sanitiser-მა ვერ მოაცილა; ან verification turn-ზე იქმნება Calendar event.
🔧 guard: verification_requested gate; Empty-event_id fake-booking guard / rollback
🔍 შესამოწმებელი side-effect: Calendar/Sheets/email: NONE verification turn-ზე. Final reply must not contain booking confirmation.

**SE-12 — Reschedule წერს NEW შემდეგ აუქმებს OLD — ზუსტად ერთი active Booked row** · ტიპი: 🟢 MUST PASS · სუსტი წერტილი: მეორე დრო უკვე-booked lead-ზე უნდა reroute-დეს reschedule-ზე (book new → verify → cancel old), არა შექმნას მეორე Calendar event / მეორე Booked row.
1. [lead already booked tomorrow 15:00]
2. სხვა დროზე გადამიტანე, ზეგ 17 საათზე
3. კი, დაადასტურე

✅ მოსალოდნელი: აგენტი ქმნის ახალ event-ს ზეგ 17:00, შლის ძველ event-ს ხვალ 15:00, და Sheets-ში ძველი row → 'Rescheduled', ახალი/მიმდინარე 'Booked' — ერთი აქტიური Booked row.
🔴 RED FLAG: ორი აქტიური Calendar event; ორი Booked row ერთ sender-ზე; ძველი event არ წაიშალა.
🔧 guard: Successful booking side-effect chain (reschedule reroute parent_tool_executor.py:1054)
🔍 შესამოწმებელი side-effect: Calendar: old 15:00 deleted, new 17:00 present (ზუსტად ერთი active). Sheets: oldest Booked row → Rescheduled, ზუსტად ერთი Booked row sender-ისთვის.

---

## შემაჯამებელი — გაშვების რიგი

1. **დაიწყე ნაწილი 0-ის 🟢 MUST PASS რიგებით** (WP-1…WP-16 + WP-23/WP-24 — underage handoff name/manager-number, live-fixed 2026-06-22). ეს დეტერმინისტული floor-ია — ცოცხლად უნდა დაიჭიროს. ჩავარდნა = რეგრესია, ესკალაცია.
2. **შემდეგ deterministic ქვესისტემები 🟢-ით:**
   - **Kill switch + Admin** (SE-6, SE-7) — ერთხელ დააყენე და დააბრუნე env/admin, რომ დანარჩენი სცენარები სუფთა state-ით გაუშვა.
   - **Camp-stream date filter** (DF-1, DF-5…DF-15) — DATE-SENSITIVE: DF-1/DF-5…DF-11/DF-13/DF-14 დღეს (06-22) გაუშვი; DF-2/DF-3/DF-4 ცალკე, საათის გაყინვით.
   - **Notifications & side-effects** (SE-1…SE-5, SE-8, SE-9, SE-11, SE-12) — ამოწმე Calendar/Sheets/email side-effects.
   - **PARENT↔ADULT გადართვა** 🟢 (CS-1…CS-7, CS-11, CS-12) — first-message classification + ADULT→PARENT overrides.
   - **ADULT flow** 🟢 (AD-1…AD-13, AD-16, AD-18) — deterministic interceptors.
   - **Comment→DM** 🟢 (CF-1, CF-2, CF-4…CF-15) — ოპერატორ-driven, რეალური webhook/კომენტარი საჭიროა.
3. **ბოლოს 🟡 PROBE რიგები** (WP-17…WP-22, AD-14/AD-15/AD-17/AD-19/AD-20, CF-3, CS-8/CS-9/CS-10/CS-13, DF-4/DF-16, SE-10). აქ ჩავარდნა მოსალოდნელია — ჩაინიშნე, მაგრამ არ ჩათვალო რეგრესიად. **გამონაკლისი:** CS-13-ში და SE-10-ში booked booking-ის/child_age-ის დაკარგვა ან orphan Calendar event ცრუ CRM-confirmation-ით **რეალური დეფექტია** — ესკალაცია.

---

## დაკავშირებული
- `docs/LIVE_TEST_CHECKLIST_2026_06_22.md` — დეტალური PARENT-flow სკრიპტი (H1–H8 highest-risk + CM/GI/BK/LC/IC/MP). ეს დოკუმენტი მას აფართოებს.
- `docs/REDTEAM_CONVERSATIONS.md` — carried-open red-team findings (A-asym PARENT→ADULT :171-174 და სხვ.).
- `docs/HANDOFF.md` — ღია engineering tasks, operator-deferred items (B5×B1, off-topic guard NEXT-TASK), Railway/Meta App Review blockers.
