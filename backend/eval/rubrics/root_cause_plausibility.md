# Rubric: Root-Cause Plausibility (Tier 3)

_Reviewed 2026-07-14. Treat root causes as hypotheses, not verified causation._

Scores each `RootCause` in `reasoning.json` for how believable and well-supported
the causal claim is, given the patterns and evidence. Judge with a model
different from the one that produced the output.

Score 1-5:

- **5 - Highly plausible.** Cause follows directly from the pattern; a domain
  reader would agree it is the most likely explanation; confidence is calibrated.
- **4 - Plausible.** Reasonable cause, minor alternative explanations ignored.
- **3 - Partly plausible.** Cause is possible but generic or weakly tied to the
  pattern; confidence over/under-stated.
- **2 - Weak.** Cause is speculative or only loosely related to the pattern.
- **1 - Implausible.** Cause contradicts the evidence, or is unrelated / invented.

Return: `{"score": <1-5>, "justification": "<one or two sentences>"}`.
