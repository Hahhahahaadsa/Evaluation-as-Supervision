# Rubric: Recommendation Actionability (Tier 3)

_Reviewed 2026-07-14. Use only after Tier 1 traceability checks pass._

Scores each `Recommendation` in `strategy.json` for how actionable it is for a
restaurant operator. Judge with a model different from the one that produced it.

Score 1-5:

- **5 - Directly actionable.** Concrete action, clear owner/mechanism, obviously
  tied to the issue; a manager could act on it this week.
- **4 - Actionable.** Clear action, some specifics left to the reader.
- **3 - Partly actionable.** Right direction but vague ("improve service") with
  no concrete step.
- **2 - Weak.** Generic advice not clearly tied to the identified issue.
- **1 - Not actionable.** Platitude, contradicts the issue, or unimplementable.

Also note whether `priority` ordering is sensible relative to issue frequency
(that ordering is separately checked deterministically in Tier 1).

Return: `{"score": <1-5>, "justification": "<one or two sentences>"}`.
