"""Inventory: which deterministic code can send CAMP- or ADULT-specific text
without the model ever seeing the turn.

Written after the live leak of 2026-09-12, where a parent nine turns into a
Sunday-School conversation asked about a 6-year-old and got the camp's age band
back — because a deterministic layer replaced the reply before the model was
consulted.

Emits a CSV with a verdict per function. Read-only; imports nothing from the app.

    python tools/inventory_hardcoded_program_text.py
    -> reports/hardcoded_program_text.csv
"""
from __future__ import annotations

import ast
import csv
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

TARGETS = [
    "app/flows/parent_flow.py",
    "app/services/conversation_service.py",
    "app/agent/llm/adult_llm_engine.py",
    "app/agent/llm/parent_llm_engine.py",
    "app/reasoning/camp_topic_facts.py",
    "app/reasoning/legacy_actions.py",
]

CAMP_STEMS = ("ბანაკ", "საზაფხულო", "ლაგერ", "ნაკად")
ADULT_STEMS = ("ღონისძიებ", "საღამო", "ბილეთ", "კულტურ", "ზრდასრულ", "პოეზი")

# A Georgian sentence long enough to be something a parent reads, rather than a
# stem used for matching.
def _is_user_facing(text: str) -> bool:
    ka = sum(1 for ch in text if "ა" <= ch <= "ჿ")
    return ka >= 20 and " " in text.strip()


def _stems_in(text: str) -> tuple[bool, bool]:
    return (any(s in text for s in CAMP_STEMS),
            any(s in text for s in ADULT_STEMS))


def _strings_of(node: ast.AST) -> list[str]:
    out = []
    for n in ast.walk(node):
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            out.append(n.value)
        elif isinstance(n, ast.JoinedStr):
            parts = [v.value for v in n.values
                     if isinstance(v, ast.Constant) and isinstance(v.value, str)]
            if parts:
                out.append("".join(parts))
    return out


def main() -> int:
    rows = []
    for rel in TARGETS:
        path = os.path.join(ROOT, rel)
        if not os.path.exists(path):
            continue
        src = io.open(path, encoding="utf-8-sig").read()
        tree = ast.parse(src)

        # module-level constants a function may reference
        consts: dict[str, str] = {}
        for node in tree.body:
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = (node.targets if isinstance(node, ast.Assign)
                           else [node.target])
                names = [t.id for t in targets if isinstance(t, ast.Name)]
                if not names or node.value is None:
                    continue
                joined = " ".join(_strings_of(node.value))
                if joined:
                    consts[names[0]] = joined

        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            own = _strings_of(node)
            referenced = [consts[n.id] for n in ast.walk(node)
                          if isinstance(n, ast.Name) and n.id in consts]
            pool = own + referenced
            facing = [t for t in pool if _is_user_facing(t)]
            if not facing:
                continue
            camp = adult = False
            for t in facing:
                c, a = _stems_in(t)
                camp = camp or c
                adult = adult or a
            if not (camp or adult):
                continue
            # does it name a programme, or read one from the panel?
            dumped = ast.dump(node)
            panel_aware = any(
                x in dumped
                for x in ("get_section", "load_sections", "get_active_sections",
                          "_program_id_for_turn", "match_dynamic_program",
                          "get_active_child_program_names",
                          "_active_program_section")
            )
            # does it step aside when the conversation is on another programme?
            guarded = any(
                x in dumped
                for x in ("_msg_names_other_program",
                          "_conversation_names_other_program",
                          "_program_id_for_turn", "_active_program_section",
                          "get_active_child_program_names")
            )
            kind = ("CAMP+ADULT" if camp and adult
                    else "CAMP" if camp else "ADULT")
            if panel_aware or guarded:
                verdict = ("reads the panel" if panel_aware
                           else "guarded — defers to another programme")
            else:
                verdict = "FIXED TEXT, NO GUARD"
            sample = next((t for t in facing if _stems_in(t)[0] or
                           _stems_in(t)[1]), "")
            rows.append({
                "file": rel,
                "function": node.name,
                "line": node.lineno,
                "mentions": kind,
                "verdict": verdict,
                "sample": " ".join(sample.split())[:110],
            })

    rows.sort(key=lambda r: (r["verdict"] != "FIXED TEXT, NO GUARD",
                             r["file"], r["line"]))
    out_dir = os.path.join(ROOT, "reports")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, "hardcoded_program_text.csv")
    with io.open(out, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()) if rows else
                           ["file", "function", "line", "mentions", "verdict",
                            "sample"])
        w.writeheader()
        w.writerows(rows)

    fixed = [r for r in rows if r["verdict"] == "FIXED TEXT, NO GUARD"]
    print("functions carrying programme-specific user text: %d" % len(rows))
    print("  FIXED TEXT with NO programme guard: %d" % len(fixed))
    print("wrote %s" % os.path.relpath(out, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
