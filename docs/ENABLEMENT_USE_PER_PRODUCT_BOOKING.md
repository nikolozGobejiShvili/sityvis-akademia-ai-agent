# Enablement — `USE_PER_PRODUCT_BOOKING` (per-product consultation booking + lead, R1)

**Status (2026-07-22):** built, flag default **OFF**, LOCAL on `feat/dynamic-programs`. Live booking UNCHANGED until enabled. This is the **booking guardrail zone** (money/commitment) — enable only on the test Page first.

## What it does

Today only the **camp** can take a consultation booking. A non-camp admin product (e.g. a "Disneyland tour") can be described (via `USE_DYNAMIC_PROGRAMS` + `get_program_info`) but a parent cannot **book a consultation** for it — `book_consultation` always used camp's age band + camp's registration and never tagged the lead with the product.

With `USE_PER_PRODUCT_BOOKING` ON, `book_consultation` resolves the admin product for the turn and swaps **only** two sources to that product's `sections.yaml` entry:

1. **age-band source** — eligibility uses the product's `age_min`/`age_max` (e.g. Disneyland 7–16) instead of camp's 9–17;
2. **registration source** — the product's `registration_status` gates the booking instead of camp's;

plus it **tags the lead** with `program_id` (written to a new Sheets **Program** column) and sources **post-booking facts** (price/location/…) from the product's section. So a new admin product gets the **same booking+lead function as camp**.

### How the product is resolved (fail-CLOSED to camp)

Booking is multi-turn — the confirmation turn („კი" / „16:00") does not re-name the product — so resolution is **sticky**:

- `get_program_info(<dynamic product>)` **tags** the lead with that product (the natural "we're discussing product X" signal);
- a booking turn whose message **names** a dynamic product tags it too;
- `get_camp_info` (any turn) **clears** the tag (a pivot to camp reverts to the camp band — this is what prevents a stale product tag from ever widening the camp age gate);
- explicit camp intent on the booking turn also clears it;
- **any doubt → camp** (the known-good band + registration).

## Flag-OFF guarantee (the default)

`USE_PER_PRODUCT_BOOKING=false` ⇒ **byte-identical** to today: camp age band, camp registration, the 17-column A–Q lead row (**no Program column written**), camp post-booking facts. Proven by the full suite green (only the pre-existing `fast_track` failure) + the flag-off tests in `tests/test_per_product_booking_2026_07_22.py`.

**Every booking validation gate is preserved** (verified by running the camp guardrail tests with the flag ON): the `user_confirmed_datetime` gate, the verification-phrase guard, the slot-availability fail-CLOSED re-check, the empty-`event_id` rollback, the slot-mismatch rollback, and the per-turn success flag. The flag can ONLY change *which product's* band + registration are consulted — never *whether* a gate runs.

**Fail-CLOSED:** a product with missing/blank/invalid `age_min`/`age_max` falls back to the **camp band** (never a disabled check); a product with missing/closed `registration_status` is treated as **closed**.

## The new Sheets "Program" column (forward-only)

Enabling the flag adds a trailing **Program** column to the Leads tab (A–R instead of A–Q). This is an operator-visible, **forward-only** schema change:

- The code writes 18-column rows and, on the next sheet access, `_ensure_headers` **appends the `Program` header** (existing columns A–Q never shift; old rows simply have an empty Program cell).
- **Verify on the test/staging sheet first.** If you prefer, add the `Program` header to column R of the live Leads tab manually before enabling.
- A camp/legacy lead written with the flag ON has an **empty** Program cell (still 18-wide).

## How to enable (operator)

1. Railway env: set **`USE_PER_PRODUCT_BOOKING=true`** (keep **`USE_DYNAMIC_PROGRAMS=true`** — the product must be reachable).
2. Full restart (settings are `@lru_cache`d).
3. In `/admin/programs`, the product needs `status: active`, an integer `age_min`/`age_max`, and `registration_status: open` to be bookable.

## Rollback

Set `USE_PER_PRODUCT_BOOKING=false` (or remove the line) + restart → camp band, camp registration, 17-column lead row, camp facts. No data change. (An already-added `Program` header on the sheet is harmless; the code just stops writing to it.)

## Staging acceptance test (test Page)

With `USE_PER_PRODUCT_BOOKING=true` + `USE_DYNAMIC_PROGRAMS=true`:

1. Seed **Disneyland** in `/admin/programs`: `status: active`, `age_min: 7`, `age_max: 16`, `registration_status: open`, a price + location.
2. Ask about Disneyland (so the agent calls `get_program_info` → tags the lead), then book a consultation for a **7-year-old** → **succeeds** (camp would have rejected 7 as under-9). A Google Calendar event is created; the manager is notified.
3. The Leads row for that booking has `disneyland_tour` in the **Program** column; the post-booking answer uses **Disneyland** price/location, not camp.
4. **Camp still works:** a camp consultation for a 14-year-old still books on the camp band with an empty Program cell. (Camp registration is currently closed/over — reopen a camp stream to test camp booking.)
5. **Guardrails unchanged:** a booking without a confirmed datetime, a „ნამდვილად თავისუფალია?" verification question, and a busy slot all behave exactly as for camp.

## Scope / known limitation

- **Reserved products (Sunday School)** are OUT of scope — they still return canned text and are NOT bookable via this path (that needs `PROGRAM_REGISTRY` un-gating = R3). Disneyland is a non-reserved dynamic product and does not need it.
- **Single-product-conversation assumption:** the product context is sticky per conversation and is kept accurate by the camp-clear signals above. A conversation that browses a dynamic product and then books camp will use the camp band as long as camp is discussed (`get_camp_info`) or named before the booking — which is the normal flow. Validate the single-product Disneyland flow first.
- Per-product **follow-up cadence** and the **adult** flow are not in scope here.
