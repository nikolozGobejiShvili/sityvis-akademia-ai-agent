"""Agent-understanding eval harness (READ-ONLY).

Measures how well the agent UNDERSTANDS free-form Georgian and chooses the
right intent / segment / entity / response / follow-up decision. This is NOT a
unit-test suite for functions — it scores the agent's decision quality.

Every external side-effect (Calendar/Sheets/WhatsApp/email/outbound DM/
follow-up send) runs as a recording dry-run stub. See evals/safety.py.

Entry point: ``python -m evals.run_evals`` (deterministic, free) ·
``python -m evals.run_evals --llm --judge`` (full, real OpenAI + Claude judge).
"""
