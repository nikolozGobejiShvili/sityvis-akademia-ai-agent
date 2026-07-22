# Enablement — `USE_DYNAMIC_WELCOME` (data-driven welcome menu, R2)

**Status (2026-07-22):** built, flag default **OFF**, LOCAL-only on `feat/dynamic-programs`. Live greeting UNCHANGED until enabled.

## What it does

The first-turn greeting is the brand's front door. Today it is a **hardcoded** two-option menu:

```
გამარჯობა.

გვითხარით, რა გაინტერესებთ:
— ბავშვების საზაფხულო ბანაკი
— ზრდასრულთა კულტურული საღამოები
```

With `USE_DYNAMIC_WELCOME` ON, the greeting is built from the programs **active in the admin panel**, one bullet per active program by its `name`:

```
გამარჯობა.

გვითხარით, რა გაინტერესებთ:
— ბავშვების საზაფხულო ბანაკი
— დისნეილენდის ტური
— ზრდასრულთა კულტურული საღამოები
```

So **adding a program in the panel makes it appear in the greeting**, and **marking one `ended`/`hidden` makes it drop** — automatically, for every program (camp included). This is the single `status` switch governing what the agent offers.

## Flag-OFF guarantee (the default)

`USE_DYNAMIC_WELCOME=false` ⇒ the greeting is the exact hardcoded `PARENT_WELCOME` two-option menu, byte-for-byte (proven by `test_flag_off_returns_static_menu_byte_identical` + the 103 existing welcome/menu tests). The greeting is the first thing every customer sees, so this guarantee matters most.

**Fail-safe:** if there are no active programs, or the lookup errors, the greeting falls back to the hardcoded menu — never an empty greeting.

**Unchanged in both states:** a clear first-turn camp/price/adult question still skips the menu and is answered directly (the specific-intent yields are untouched).

## How to enable (operator)

1. Railway env: set **`USE_DYNAMIC_WELCOME=true`**.
2. Full restart (settings are `@lru_cache`d).
3. A bare greeting („გამარჯობა") now lists the active programs by name.

## Rollback

Set `USE_DYNAMIC_WELCOME=false` (or remove the line) + restart → the hardcoded two-option menu. No data change.

## Staging acceptance test

On a test Page / staging, with `USE_DYNAMIC_WELCOME=true` + `USE_DYNAMIC_PROGRAMS=true`:
1. With camp + adult events + a seeded Disneyland program all `active` → send „გამარჯობა" → the greeting lists **all three by name**.
2. In `/admin/programs`, set camp `status: ended` → send „გამარჯობა" → **camp drops** from the greeting; a camp question returns the camp "streams ended" message.
3. Add a new program (active) in `/admin/programs` → send „გამარჯობა" on a fresh conversation → it **appears** in the greeting — no code change, no redeploy (admin edits persist on the volume).
4. A first-turn specific question („ფასი რა ღირს?" / „საზაფხულო ბანაკი მაინტერესებს") still skips the menu and is answered directly (unchanged).

## Note

The program `name` is what shows in the greeting — the operator should give each program a clear customer-facing name in the panel. Section order in `sections.yaml` is the menu order.
