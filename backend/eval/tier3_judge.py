"""Tier 3 - rubric scoring for the subjective stages (LLM-as-judge).

Root-cause plausibility, recommendation actionability, and report usefulness
have no formula. Score them 1-5 against a rubric (see rubrics/), by an LLM judge
using a DIFFERENT / stronger model than the one that produced the output - this
mitigates self-enhancement bias (the judge favouring its own generations).

Configure the judge separately from the pipeline model:
    JUDGE_MODEL   (defaults to a model different from OPENAI_MODEL)

Run:  python -m eval.tier3_judge <dump_dir>

Kept small - informs the demo writeup, not CI.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys

from dotenv import load_dotenv
from openai import OpenAI

from eval.common import LoadedDump, load_dump

logger = logging.getLogger(__name__)

load_dotenv()

# One rubric markdown per subjective target. Loaded at runtime.
RUBRICS = {
    "root_cause_plausibility": "eval/rubrics/root_cause_plausibility.md",
    "recommendation_actionability": "eval/rubrics/recommendation_actionability.md",
    "report_usefulness": "eval/rubrics/report_usefulness.md",
}

# Falls back to a model distinct from the default pipeline model
# (gemini-2.5-flash) so an unset JUDGE_MODEL doesn't silently self-judge.
# `gemini-pro-latest` is the current stronger pro-tier alias; the older
# `gemini-2.5-pro`/`gemini-3-pro-preview` ids now 404 for new accounts.
_DEFAULT_JUDGE_MODEL = "gemini-pro-latest"

_JUDGE_SYSTEM_PROMPT = """\
You are an impartial evaluator scoring the output of a different AI system \
against a fixed rubric. Read the rubric and the target JSON, then return ONLY \
a JSON object: {{"score": <integer 1-5>, "justification": "<1-3 sentences>"}}.

Rubric:
{rubric}

Target output to score:
{target}"""


def judge_model() -> str:
    """Return the judge model id; must differ from the pipeline's OPENAI_MODEL."""
    model = os.getenv("JUDGE_MODEL", "").strip()
    pipeline_model = os.getenv("OPENAI_MODEL", "gemini-2.5-flash").strip()

    if not model:
        model = _DEFAULT_JUDGE_MODEL
        if model == pipeline_model:
            logger.warning(
                "JUDGE_MODEL not set and the default judge model matches OPENAI_MODEL "
                "(%s) - set JUDGE_MODEL to a different/stronger model to avoid "
                "self-enhancement bias.",
                pipeline_model,
            )
    elif model == pipeline_model:
        logger.warning(
            "JUDGE_MODEL (%s) is the same as OPENAI_MODEL - the judge is scoring its "
            "own model family, which risks self-enhancement bias.",
            model,
        )
    return model


def _client() -> OpenAI:
    return OpenAI(api_key=os.getenv("OPENAI_API_KEY"), base_url=os.getenv("OPENAI_BASE_URL"))


def _extract_score(raw: str) -> dict:
    """Parse {"score": int, "justification": str} out of the judge's reply.

    Falls back to regex extraction of the first 1-5 digit if the reply isn't
    strict JSON (some OpenAI-compatible endpoints ignore response_format for
    unfamiliar models).
    """
    try:
        parsed = json.loads(raw)
        score = int(parsed["score"])
        justification = str(parsed.get("justification", ""))
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        match = re.search(r"\b([1-5])\b", raw)
        if not match:
            raise ValueError(f"could not parse a 1-5 score from judge reply: {raw!r}")
        score = int(match.group(1))
        justification = raw.strip()

    if not 1 <= score <= 5:
        raise ValueError(f"judge score out of range 1-5: {score}")
    return {"score": score, "justification": justification}


def score_with_rubric(rubric_path: str, target_json: dict) -> dict:
    """Send rubric + target output to the judge model, parse {score, justification}."""
    with open(rubric_path, "r", encoding="utf-8") as fh:
        rubric_text = fh.read()

    prompt = _JUDGE_SYSTEM_PROMPT.format(rubric=rubric_text, target=json.dumps(target_json, indent=2))

    resp = _client().chat.completions.create(
        model=judge_model(),
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
        response_format={"type": "json_object"},
    )
    raw = resp.choices[0].message.content
    return _extract_score(raw)


def _score_root_causes(dump: LoadedDump) -> list[dict]:
    root_causes = (dump.reasoning or {}).get("root_causes") or []
    scored = []
    for rc in root_causes:
        result = score_with_rubric(RUBRICS["root_cause_plausibility"], rc)
        scored.append({"target": rc, **result})
    return scored


def _score_recommendations(dump: LoadedDump) -> list[dict]:
    recommendations = (dump.strategy or {}).get("recommendations") or []
    scored = []
    for rec in recommendations:
        result = score_with_rubric(RUBRICS["recommendation_actionability"], rec)
        scored.append({"target": rec, **result})
    return scored


def _score_report(dump: LoadedDump) -> dict | None:
    if dump.report is None:
        return None
    return score_with_rubric(RUBRICS["report_usefulness"], dump.report)


def _mean(scores: list[dict]) -> float | None:
    if not scores:
        return None
    return sum(s["score"] for s in scores) / len(scores)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python -m eval.tier3_judge <dump_dir>")
        return 2

    dump_dir = argv[1]
    try:
        dump = load_dump(dump_dir)
    except FileNotFoundError as exc:
        print(f"error: {exc}")
        return 1

    model = judge_model()
    pipeline_model = os.getenv("OPENAI_MODEL", "gemini-2.5-flash")
    print(f"Judge model: {model} (pipeline model: {pipeline_model})")
    if model == pipeline_model:
        print("WARNING: judge model matches the pipeline model - scores may be biased. Set JUDGE_MODEL.")

    if not os.getenv("OPENAI_API_KEY"):
        print("OPENAI_API_KEY is not set - the judge needs it to run.")
        return 1

    root_cause_scores = _score_root_causes(dump) if dump.reasoning is not None else []
    recommendation_scores = _score_recommendations(dump) if dump.strategy is not None else []
    report_score = _score_report(dump)

    print("\n=== Tier 3: rubric scores (1-5) ===")
    print(f"Root-cause plausibility     : mean={_mean(root_cause_scores)} (n={len(root_cause_scores)})")
    for s in root_cause_scores:
        print(f"  [{s['score']}] {s['target'].get('cause', '')[:60]} - {s['justification'][:80]}")

    print(f"Recommendation actionability: mean={_mean(recommendation_scores)} (n={len(recommendation_scores)})")
    for s in recommendation_scores:
        print(f"  [{s['score']}] {s['target'].get('action', '')[:60]} - {s['justification'][:80]}")

    if report_score is not None:
        print(f"Report usefulness           : {report_score['score']} - {report_score['justification']}")
    else:
        print("Report usefulness           : N/A (report stage skipped/absent)")

    out = {
        "judge_model": model,
        "pipeline_model": pipeline_model,
        "root_cause_plausibility": root_cause_scores,
        "recommendation_actionability": recommendation_scores,
        "report_usefulness": report_score,
        "means": {
            "root_cause_plausibility": _mean(root_cause_scores),
            "recommendation_actionability": _mean(recommendation_scores),
            "report_usefulness": report_score["score"] if report_score else None,
        },
    }
    out_path = os.path.join(dump_dir, "tier3_scores.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2)
    print(f"\nwrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
