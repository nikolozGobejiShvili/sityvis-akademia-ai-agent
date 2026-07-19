# Phase 0b — Admin-Config Persistence on Railway (overlay model) Implementation Plan (v2, critique-hardened)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Make operator admin-panel edits (programs/sections, templates, business hours, manager contacts, approved-answers) SURVIVE a Railway redeploy. Today they are written to `data/admin_config/*.yaml` on the container's ephemeral filesystem and are **CONFIRMED wiped on every redeploy** (proven live 2026-07-20: an added program "ფორმულა1" vanished after a code deploy; restarts preserve it, redeploys don't).

**Architecture (OVERLAY model — critique-hardened, replaces the seed model of v1):** Point the admin-config WRITE directory at an operator-mounted **Railway persistent volume** via an `ADMIN_CONFIG_DIR` env override. **Reads overlay: read the volume file if it exists, ELSE fall back to the repo-default file** (baked into the image). **Writes always go to the volume.** No boot-seed/copy. When the env is unset (local dev, and production before the operator mounts the volume) behavior is **identical to today**.

**Why overlay, not seed (the v1 critique):** the seed model (copy defaults into the volume once, then never overwrite) had two flaws the overlay removes for free — **C1:** a misconfigured/empty volume with a silent seed failure would leave the agent with EMPTY config (losing even the 3 built-in programs); **H2:** once seeded, repo-side updates to the built-in sections would never reach production. The overlay's read-fallback means a fresh/broken volume ALWAYS falls back to the repo defaults (never empty), and un-edited files always read the CURRENT repo default (no drift).

**Tech Stack:** Python 3.10 / FastAPI, `os`, pytest. No new dependency.

## Global Constraints

- **Env-unset ⇒ byte-identical.** When `ADMIN_CONFIG_DIR` env is NOT set, `ADMIN_CONFIG_DIR == _DEFAULT_ADMIN_CONFIG_DIR`, `_config_read_path` returns its argument unchanged, and every read/write path is exactly today's. The full existing suite (~5009 passing) must stay green.
- **Never-empty-config (C1, load-bearing).** If the volume file is missing (fresh/misconfigured volume), reads MUST fall back to the repo default file. The agent must never boot with empty config because of a volume problem — the 3 built-in programs are always readable from the image defaults.
- **Operator edit wins.** Once the operator saves a file (write → volume), that volume file exists and reads return it (not the default). Un-edited files read the current repo default.
- **Writes always to the volume.** Every write goes to `ADMIN_CONFIG_DIR / name` (the volume when the env is set) so it persists. Verify NO write path re-resolves to the repo default.
- **Never breaks boot / never raises on read.** The read-fallback is defensive; a fallback failure degrades to today's behavior, never crashes.
- **No new dependency; no secrets logged.** **Do NOT commit `data/admin_config/sections.yaml`** or `evals/`. **Interpreter:** `.venv/Scripts/python.exe`. **LOCAL-only** branch `feat/dynamic-programs`; a push to `feat/camp-topic-facts` auto-deploys → push only with explicit operator consent. **No haiku.**
- **Expected pre-existing failure:** `tests/test_approved_copy_service_2026_07_11.py::test_parent_flow_start_book_intent_uses_fast_track_and_advances_state`. Any OTHER failure is in scope.

---

## File Structure

**Modify:**
- `app/services/admin_config_service.py` — add `_DEFAULT_ADMIN_CONFIG_DIR`, `_resolve_admin_config_dir()` (env override), make `ADMIN_CONFIG_DIR` use it; add `_config_read_path()` and apply it at the top of `_safe_load_yaml` (the read chokepoint).
- `app/main.py` — boot-log the resolved `ADMIN_CONFIG_DIR` (observability). NO seed call.

**Test:**
- `tests/test_admin_config_persistence.py`.

**Operator (infra, not code):** Railway volume + `ADMIN_CONFIG_DIR` env — see the runbook.

---

## Task 1: Env-override config-dir resolution

**Files:** Modify `app/services/admin_config_service.py` (lines 37-64); Test `tests/test_admin_config_persistence.py`.

**Interfaces:** Produces `_DEFAULT_ADMIN_CONFIG_DIR: Path` (repo default, the read-fallback source); `_resolve_admin_config_dir() -> Path` (env override when `ADMIN_CONFIG_DIR` set, else default); `ADMIN_CONFIG_DIR == _resolve_admin_config_dir()`. `SECTIONS_PATH`/`TEMPLATES_PATH`/`BUSINESS_HOURS_PATH`/`MANAGER_CONTACTS_PATH` derive from `ADMIN_CONFIG_DIR` unchanged (these are the WRITE paths).

- [ ] **Step 1: Confirm `os` is imported** at the top of `admin_config_service.py`; add `import os` if missing.

- [ ] **Step 2: Write the failing tests** (`tests/test_admin_config_persistence.py`):

```python
def test_resolve_admin_config_dir_default_when_env_unset(monkeypatch):
    monkeypatch.delenv("ADMIN_CONFIG_DIR", raising=False)
    from app.services import admin_config_service as acs
    assert acs._resolve_admin_config_dir() == acs._DEFAULT_ADMIN_CONFIG_DIR


def test_resolve_admin_config_dir_uses_env_override(monkeypatch, tmp_path):
    from pathlib import Path
    monkeypatch.setenv("ADMIN_CONFIG_DIR", str(tmp_path / "vol"))
    from app.services import admin_config_service as acs
    assert acs._resolve_admin_config_dir() == Path(str(tmp_path / "vol"))
```

- [ ] **Step 3: Run to verify fail** — `.venv/Scripts/python.exe -m pytest tests/test_admin_config_persistence.py -q` → FAIL (`_resolve_admin_config_dir` missing).

- [ ] **Step 4: Implement** — replace the `ADMIN_CONFIG_DIR` block (lines 59-64) with:

```python
# Config files live under <project>/data/admin_config/ by default. On Railway the
# container FS is ephemeral (admin edits wiped on every redeploy), so an operator
# mounts a persistent volume and points ADMIN_CONFIG_DIR at it. Writes go to that
# dir; reads overlay volume-then-default (see _config_read_path). Env unset ⇒
# identical to before.
_DEFAULT_ADMIN_CONFIG_DIR: Path = _resolve_base_dir() / "data" / "admin_config"


def _resolve_admin_config_dir() -> Path:
    override = os.environ.get("ADMIN_CONFIG_DIR", "").strip()
    if override:
        return Path(override)
    return _DEFAULT_ADMIN_CONFIG_DIR


ADMIN_CONFIG_DIR: Path = _resolve_admin_config_dir()
SECTIONS_PATH: Path = ADMIN_CONFIG_DIR / "sections.yaml"
TEMPLATES_PATH: Path = ADMIN_CONFIG_DIR / "templates.yaml"
BUSINESS_HOURS_PATH: Path = ADMIN_CONFIG_DIR / "business_hours.yaml"
MANAGER_CONTACTS_PATH: Path = ADMIN_CONFIG_DIR / "manager_contacts.yaml"
```

- [ ] **Step 5: Run to verify pass** — `.venv/Scripts/python.exe -m pytest tests/test_admin_config_persistence.py -q` → PASS.

- [ ] **Step 6: Commit** — `git add app/services/admin_config_service.py tests/test_admin_config_persistence.py` → `git commit -m "feat(admin-config): ADMIN_CONFIG_DIR env override for a persistent volume (Phase 0b)"`

---

## Task 2: Read-overlay fallback (volume-then-default) — the C1/H2 fix

**Files:** Modify `app/services/admin_config_service.py`; Test `tests/test_admin_config_persistence.py`.

**Interfaces:** Produces `_config_read_path(path: Path) -> Path` — returns `path` if it exists; else, when `ADMIN_CONFIG_DIR != _DEFAULT_ADMIN_CONFIG_DIR`, returns `_DEFAULT_ADMIN_CONFIG_DIR / path.name` if THAT exists; else returns `path` unchanged (caller handles a genuinely-missing file). Applied at the top of `_safe_load_yaml` so every config READ overlays volume-then-default. Never raises.

- [ ] **Step 1: Verify the read chokepoint.** Grep to confirm the config readers (`load_sections`, template loader, business-hours loader, manager-contacts loader) all go through `_safe_load_yaml`. Run:
  `.venv/Scripts/python.exe -c "import re,pathlib; src=pathlib.Path('app/services/admin_config_service.py').read_text(encoding='utf-8'); print('_safe_load_yaml calls:', src.count('_safe_load_yaml('))"`
  and grep for any reader that reads a `*_PATH` constant WITHOUT `_safe_load_yaml` (e.g. `SECTIONS_PATH.read_text`/`open(SECTIONS_PATH`). If any bypass exists, route it through `_safe_load_yaml`/`_config_read_path` too. Note findings in the report.

- [ ] **Step 2: Write the failing tests** (append):

```python
def test_read_overlay_uses_volume_when_present(monkeypatch, tmp_path):
    from app.services import admin_config_service as acs
    src = tmp_path / "defaults"; src.mkdir()
    (src / "sections.yaml").write_text("sections: [DEFAULT]\n", encoding="utf-8")
    vol = tmp_path / "vol"; vol.mkdir()
    (vol / "sections.yaml").write_text("sections: [VOLUME]\n", encoding="utf-8")
    monkeypatch.setattr(acs, "_DEFAULT_ADMIN_CONFIG_DIR", src)
    monkeypatch.setattr(acs, "ADMIN_CONFIG_DIR", vol)
    assert acs._config_read_path(vol / "sections.yaml") == vol / "sections.yaml"


def test_read_overlay_falls_back_to_default_when_volume_missing(monkeypatch, tmp_path):
    # C1: a fresh/empty volume must fall back to the repo default (never empty)
    from app.services import admin_config_service as acs
    src = tmp_path / "defaults"; src.mkdir()
    (src / "sections.yaml").write_text("sections: [DEFAULT]\n", encoding="utf-8")
    vol = tmp_path / "vol"; vol.mkdir()  # empty volume
    monkeypatch.setattr(acs, "_DEFAULT_ADMIN_CONFIG_DIR", src)
    monkeypatch.setattr(acs, "ADMIN_CONFIG_DIR", vol)
    assert acs._config_read_path(vol / "sections.yaml") == src / "sections.yaml"


def test_read_overlay_noop_when_env_unset(monkeypatch, tmp_path):
    from app.services import admin_config_service as acs
    d = tmp_path / "same"; d.mkdir()
    p = d / "sections.yaml"  # missing
    monkeypatch.setattr(acs, "_DEFAULT_ADMIN_CONFIG_DIR", d)
    monkeypatch.setattr(acs, "ADMIN_CONFIG_DIR", d)  # == default → no overlay
    assert acs._config_read_path(p) == p


def test_load_sections_falls_back_to_default_on_empty_volume(monkeypatch, tmp_path):
    # integration: load_sections must return the 3 built-ins via the read-fallback
    from app.services import admin_config_service as acs
    src = tmp_path / "defaults"; src.mkdir()
    (src / "sections.yaml").write_text(
        "sections:\n  - id: summer_camp\n    status: active\n", encoding="utf-8")
    vol = tmp_path / "vol"; vol.mkdir()  # empty
    monkeypatch.setattr(acs, "_DEFAULT_ADMIN_CONFIG_DIR", src)
    monkeypatch.setattr(acs, "ADMIN_CONFIG_DIR", vol)
    monkeypatch.setattr(acs, "SECTIONS_PATH", vol / "sections.yaml")
    ids = {s.get("id") for s in acs.load_sections()}
    assert "summer_camp" in ids  # never empty despite the empty volume
```

- [ ] **Step 3: Run to verify fail** — FAIL (`_config_read_path` missing).

- [ ] **Step 4: Implement** — add `_config_read_path` (near `_resolve_admin_config_dir`), then apply it at the very top of `_safe_load_yaml` (around line 138):

```python
def _config_read_path(path: Path) -> Path:
    """Overlay read (Phase 0b): return `path` if it exists; otherwise, when using a
    volume override, fall back to the same-named repo-default file so a fresh or
    misconfigured volume never yields empty config. Never raises."""
    try:
        if path.exists():
            return path
        if ADMIN_CONFIG_DIR != _DEFAULT_ADMIN_CONFIG_DIR:
            default = _DEFAULT_ADMIN_CONFIG_DIR / path.name
            if default.exists():
                return default
    except Exception:  # pragma: no cover - defensive
        pass
    return path
```
Then, at the TOP of `_safe_load_yaml(path: Path)` (before it opens the file), insert:
```python
    path = _config_read_path(path)
```
This makes EVERY `_safe_load_yaml`-based read overlay volume-then-default. Writes are untouched (they use the `*_PATH` constants = volume).

- [ ] **Step 5: Run to verify pass** — `.venv/Scripts/python.exe -m pytest tests/test_admin_config_persistence.py -q` → PASS.

- [ ] **Step 6: Commit** — `git add app/services/admin_config_service.py tests/test_admin_config_persistence.py` → `git commit -m "feat(admin-config): read-overlay volume-then-default so a fresh volume never yields empty config (Phase 0b)"`

---

## Task 3: Boot-log + full verification gate

**Files:** Modify `app/main.py`; verification only otherwise.

- [ ] **Step 1: Boot-log the config dir** — in `app/main.py` startup (near the flag prints), add:
```python
    from app.services import admin_config_service as _acs
    print(f"⚙️ ADMIN_CONFIG_DIR={_acs.ADMIN_CONFIG_DIR}")
```
Gives operators a boot signal of WHERE config is read/written (repo path vs volume). Commit with the gate.

- [ ] **Step 2: Env-unset byte-identity** — `.venv/Scripts/python.exe -m pytest -q` (ADMIN_CONFIG_DIR unset). EXPECTED: no NEW failures — only the pre-existing `fast_track`. Record the line.
- [ ] **Step 3: Focused admin suite** — `.venv/Scripts/python.exe -m pytest tests/test_admin_config_persistence.py tests/test_admin_config.py tests/test_admin_panel.py tests/test_admin_form_field_completion.py -q` → green (existing admin read/write tests still pass through the overlay).
- [ ] **Step 4: Eval gate — READ-ONLY** — `cp evals/baseline.json <scratchpad>/ref` → `.venv/Scripts/python.exe -m evals.run_evals` → `diff` byte-identical; restore if changed. 0 external writes.
- [ ] **Step 5: Commit** — `git add app/main.py` → `git commit -m "chore(admin-config): boot-log resolved ADMIN_CONFIG_DIR (Phase 0b)"`

---

## Operator Runbook — Railway volume (infra, at enablement)

1. Railway → your service → **Volumes** → **New Volume**. Mount path: **`/data/admin_config`** (any stable path OUTSIDE the repo tree; it does NOT need to match the repo path — reads fall back to the image defaults automatically).
2. Service → **Variables** → `ADMIN_CONFIG_DIR=/data/admin_config` (matching the mount).
3. Redeploy. Boot log should print `⚙️ ADMIN_CONFIG_DIR=/data/admin_config`. With an empty volume, the agent still shows the 3 built-in programs (read-fallback to image defaults) — verify a normal camp question still works.
4. **RE-ADD your live programs** (e.g. ფორმულა1) via `/admin/programs` — the first volume mount starts empty (your prior ephemeral edits are not carried over). Saved programs now write to the volume.
5. **ACCEPTANCE TEST (the real gate, H3):** redeploy AGAIN and confirm the re-added program **SURVIVES** the redeploy (present in `/admin/programs` and answerable). Unit tests prove the logic; only this redeploy-survival test proves persistence on Railway.
6. Rollback: remove the `ADMIN_CONFIG_DIR` variable → reverts to the ephemeral repo path (today's behavior); volume data retained but unused.

> Notes: (a) persists ALL admin-panel-editable config (sections, templates, business hours, manager contacts, approved-answers). `app/agent/skills/*.md` are git-committed → already survive deploys. (b) DRIFT: once you SAVE `sections.yaml` (a whole-file write), later repo-side changes to the built-in defaults won't apply to that file (your saved version is authoritative) — expected. Un-edited files always read the current repo default. (c) `.bak` files accumulate in the volume on each save (harmless).

---

## Self-Review

**Spec coverage:** confirmed live bug (admin edits wiped on redeploy) → Task 1 (env-override write dir) + Task 2 (read-overlay) + runbook (volume). Load-bearing property = **never-empty-config**: a fresh/misconfigured volume falls back to the repo defaults (`test_read_overlay_falls_back_to_default_when_volume_missing` + `test_load_sections_falls_back_to_default_on_empty_volume`). ✅

**Placeholder scan:** every step has real code + exact commands. ✅

**Type/name consistency:** `_DEFAULT_ADMIN_CONFIG_DIR` (Task 1) is the read-fallback source consumed by `_config_read_path` (Task 2); `ADMIN_CONFIG_DIR` = resolved write dir; `SECTIONS_PATH` etc. derive from it (writes) and pass through `_config_read_path` on read (via `_safe_load_yaml`). ✅

**Env-unset invariant:** env unset ⇒ `ADMIN_CONFIG_DIR == _DEFAULT_ADMIN_CONFIG_DIR` ⇒ `_config_read_path` returns its arg unchanged AND writes use the same repo dir ⇒ zero behavior change; full suite (env unset in CI) green. Task 3 Step 2 verifies. ✅

---

## Appendix — Critique → Fix (v1 seed → v2 overlay)

| v1 finding | Sev | Resolution in v2 |
|---|---|---|
| **C1 — silent empty config on volume misconfig (seed swallows error)** | 🔴 | OVERLAY read-fallback: a missing volume file always falls back to the repo default → agent never boots empty. No seed to fail. |
| **H2 — seed drift (frozen built-ins)** | 🟠 | Un-edited files always read the CURRENT repo default (no volume copy exists) → repo updates apply automatically. (Drift only after the operator saves a whole-file, which is correct — their version wins.) |
| **H1 — first-mount loses live edits** | 🟠 | Runbook step 4: explicit "re-add your programs after the first mount." Built-ins never lost (read-fallback). |
| **H3 — unit tests don't prove Railway persistence** | 🟠 | Runbook step 5: the redeploy-survival test is the named ACCEPTANCE gate. |
| **M1 — some write may bypass the volume** | 🟡 | Task 2 Step 1 verifies all readers go through `_safe_load_yaml`; writes use the `*_PATH` constants (= volume). |
| **M2 — `.bak` accumulation on the volume** | 🟡 | Documented (runbook note c); harmless, accepted. |
| **M3 — env/constant name collision** | 🟡 | Documented; `ADMIN_CONFIG_DIR` is the env AND the resolved constant by design (read via `os.environ`, exposed as the resolved `Path`). |
