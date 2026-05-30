"""EHR Copilot — PHI-isolation layer (Plan -> Execute -> Narrate).

The model is a *planner/narrator*. It never receives raw patient values. In
Pass 1 it sees only the static metadata catalog + the clinician's question and
emits a structured QueryPlan (coded vocabulary only). A deterministic executor
validates the plan, runs it against the real record (DDB + FHIR + engines + ML),
and returns only structured outputs (flags / codes / scores / counts) plus a
slot map of real values that NEVER enters a model call. In Pass 2 the model sees
those structured outputs and composes an artifact tree (prose + interactive
blocks) bound to refs; a deterministic renderer hydrates it with real values.

See ``.start/ideas/2026-05-30-copilot-phi-isolation-layer.md`` for the design.
"""
from __future__ import annotations

from services.copilot.pipeline import answer_question, catch_me_up

__all__ = ["answer_question", "catch_me_up"]
