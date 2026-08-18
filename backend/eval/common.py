"""Shared helpers for the eval tiers: load a ``--dump-stages`` directory.

A dump directory (produced by ``run_pipeline.py --dump-stages <dir>``) contains:

    _summary.json   {business_name, business_id, run_config, pipeline_status,
                     skipped_agents, failed_agent, errors, retry_counts}
                    run_config = {provider, base_url, primary_model, fallback_model}
    analysis.json   list[AnalysisOutput]        (or null if the stage was skipped)
    reasoning.json  ReasoningOutput             (or null)
    strategy.json   StrategyOutput              (or null)
    report.json     ReportOutput                (or null)
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

# from app.schemas.contracts import (
#     AnalysisOutput, ReasoningOutput, StrategyOutput, ReportOutput,
# )

_STAGE_FILES = ("analysis", "reasoning", "strategy", "report")


@dataclass
class LoadedDump:
    """Raw dicts loaded from a dump directory (before Pydantic validation)."""

    summary: dict[str, Any]
    analysis: list[dict] | None
    reasoning: dict | None
    strategy: dict | None
    report: dict | None


def _read_json_or_none(path: str) -> Any:
    """Read a JSON file, treating a missing file the same as a literal ``null``.

    ``run_pipeline.py --dump-stages`` always writes one file per stage (even a
    skipped/failed one, as ``null``), but a dump produced by hand or an older
    version of the runner might simply omit the file — both mean "no output for
    this stage", so they must resolve to the same ``None``.
    """
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def load_dump(dump_dir: str) -> LoadedDump:
    """Read the five JSON files from ``dump_dir`` into a LoadedDump.

    Deliberately does NOT validate against the Pydantic contracts here —
    Tier 1's schema-validity check needs the raw dicts so it can *report*
    validation failures rather than crash on them.
    """
    if not os.path.isdir(dump_dir):
        raise FileNotFoundError(f"dump dir not found: {dump_dir}")

    summary = _read_json_or_none(os.path.join(dump_dir, "_summary.json")) or {}

    stages: dict[str, Any] = {}
    for name in _STAGE_FILES:
        stages[name] = _read_json_or_none(os.path.join(dump_dir, f"{name}.json"))

    return LoadedDump(
        summary=summary,
        analysis=stages["analysis"],
        reasoning=stages["reasoning"],
        strategy=stages["strategy"],
        report=stages["report"],
    )


@dataclass
class CheckResult:
    """One check outcome, aggregated into the per-tier scorecard."""

    name: str
    passed: bool
    score: float | None  # None for pass/fail checks; 0..1 for rates
    detail: str


def print_scorecard(results: list[CheckResult]) -> None:
    """Pretty-print a list of CheckResult as a table, plus a pass/fail summary."""
    if not results:
        print("(no checks ran)")
        return

    name_w = max(len(r.name) for r in results) + 2
    header = f"{'CHECK':<{name_w}}{'RESULT':<8}{'SCORE':<8}DETAIL"
    print(header)
    print("-" * len(header))

    for r in results:
        result_str = "PASS" if r.passed else "FAIL"
        score_str = f"{r.score:.2f}" if r.score is not None else "-"
        detail = r.detail if len(r.detail) <= 80 else r.detail[:77] + "..."
        print(f"{r.name:<{name_w}}{result_str:<8}{score_str:<8}{detail}")

    total = len(results)
    passed = sum(1 for r in results if r.passed)
    print("-" * len(header))
    print(f"{passed}/{total} checks passed")
