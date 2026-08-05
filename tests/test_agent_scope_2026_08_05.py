"""Railway live test, 2026-08-05 10:10 and 10:12 — one root, two symptoms.

10:10 — „მუსფასა და სიმბა მამაშვილი იყვნენ ?"
        No tool call at all. Answered from memory, and the answer carried an
        invented word: „ის იყო სიამბის მეფე". Fluent, and wrong.

10:12 — „საფრანგეთში როგორ ამინდი იქნება ?"
        Opened with „ამინდის პროგნოზი ჩემთვის ხელმიუწვდომელი ინფორმაციაა",
        then returned to the French weather later in the same reply.

Both follow from the same implicit rule: the agent decided by „do I remember
it?" instead of „is it my job?". Mufasa it remembered, so it answered — and got
it wrong. The weather it could not know, so it hedged. The prompt now states
the decision rule itself, rather than listing topics to refuse: a banned-topic
list is what made this agent sound robotic before, and it can never cover the
next unforeseen question anyway.
"""

from __future__ import annotations


def _live_parent_prompt() -> str:
    from app.agent.llm.prompt_loader import load_prompt, reset_cache

    reset_cache()
    return load_prompt("system_parent_v2")


def test_prompt_states_the_scope_decision_rule():
    """Choose by „is it my field?", not by „do I remember it?"."""
    prompt = _live_parent_prompt()

    assert "ჩემი სფეროა?" in prompt
    assert "მახსოვს?" in prompt


def test_prompt_warns_that_a_remembered_detail_can_be_wrong():
    """The Mufasa answer was fluent AND wrong. Unless the prompt names that
    risk, recall keeps looking like knowledge."""
    prompt = _live_parent_prompt()

    assert "მეხსიერებიდან" in prompt
    assert "არასწორი" in prompt


def test_scope_rule_is_stated_positively_not_as_a_topic_ban():
    """The rule must not degrade into a banned-topic list — that is the shape
    that produced the old robotic agent."""
    prompt = _live_parent_prompt()
    block = prompt[: prompt.index("თქვენი მიზანი არ არის FAQ-ბოტი")]

    assert "თქვენი სფერო" in block
    assert "დაუბრუნდით" in block


def test_scope_rule_carries_no_bold_markers():
    """Live prompts stay free of „**" — the model imitates what it reads, and
    Messenger renders the asterisks literally."""
    prompt = _live_parent_prompt()
    block = prompt[: prompt.index("თქვენი მიზანი არ არის FAQ-ბოტი")]

    assert "**" not in block
