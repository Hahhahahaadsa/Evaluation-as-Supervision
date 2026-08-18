# Rubric: Report Usefulness (Tier 3)

_Reviewed 2026-07-14. Score against the stage dump, not the report in isolation._

Scores the final `report.json` as a whole for usefulness to a restaurant owner.
Best scored by a human for the final demo; an LLM judge (different model) may
pre-screen.

Score 1-5:

- **5 - Very useful.** Executive summary is accurate and specific; findings,
  root causes, and recommendations cohere and would genuinely inform a decision;
  limitations are honest.
- **4 - Useful.** Solid and coherent, minor gaps or generic passages.
- **3 - Moderately useful.** Readable but partly generic; some sections thin.
- **2 - Weak.** Vague, repetitive, or loosely connected to the underlying data.
- **1 - Not useful.** Inaccurate, empty, or self-contradictory.

Note: whether the report introduces claims NOT present upstream is checked
deterministically in Tier 1 (report-subset check), not here.

Return: `{"score": <1-5>, "justification": "<two or three sentences>"}`.
