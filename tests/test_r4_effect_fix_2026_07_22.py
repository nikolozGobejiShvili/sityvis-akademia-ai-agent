"""Task 2 (Phase 3.0): R4 must require the EFFECT (the switch tool actually ran),
not a TEXT mention. 3.0b found a reply that merely said „ზრდასრულ" scored 3/3 while
`switch_to_adult_flow` never ran and the segment never switched. These tests pin the
fix and would fail if the check reverts to the old `OR` on a text mention."""
import types

from evals import cases


class _FakeH:
    """Minimal harness stand-in: controls the reply text and the tool calls a
    case sees, so the check can be exercised without a real engine turn."""
    def __init__(self, out, tools):
        self._out = out
        self.last_tool_calls = [(t, {}) for t in tools]
        self.llm_enabled = True

    def seed(self, **k):
        return types.SimpleNamespace(**k)

    def process(self, conv, msg):
        return self._out


def test_r4_fails_on_mention_without_tool():
    # Reply mentions the adult word but NO tool ran → must FAIL.
    # Under the old `OR` this scored as a pass (the false 3/3).
    h = _FakeH("ზრდასრულთა ღონისძიებები გაინტერესებთ?", tools=[])
    out = cases._r4_overage_adult_switch(h)
    assert all(not c.passed for c in out.checks)


def test_r4_passes_when_switch_tool_actually_ran():
    h = _FakeH("გადავრთე ზრდასრულთა ფლოუზე", tools=["switch_to_adult_flow"])
    out = cases._r4_overage_adult_switch(h)
    assert any(c.passed for c in out.checks)


def test_r4_fails_when_only_an_unrelated_tool_ran():
    # A tool ran, but not the switch → still a fail (effect must be the RIGHT effect).
    h = _FakeH("ზრდასრულ ღონისძიებები", tools=["get_camp_info"])
    out = cases._r4_overage_adult_switch(h)
    assert all(not c.passed for c in out.checks)
