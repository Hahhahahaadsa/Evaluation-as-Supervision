"""Tests for the Tier 1 deterministic evaluator (eval/tier1_checks.py).

Fully offline — no LLM calls, no API key. Runs against the committed fixture
at eval/fixtures/sample_dump/ (see eval/fixtures/README.md for its provenance)
plus a couple of dumps deliberately corrupted in a tmp dir, to prove each
check actually catches the bug it claims to catch (not just always-passing).
"""

import copy
import json
import os
import shutil

from eval.common import load_dump
from eval.tier1_checks import run_all

FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "..", "eval", "fixtures", "sample_dump")


def _copy_fixture(tmp_path) -> str:
    dst = str(tmp_path / "dump")
    shutil.copytree(FIXTURE_DIR, dst)
    return dst


def _load_json(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _write_json(path, payload):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)


# ── Healthy fixture: everything should pass ─────────────────────────────────


def test_healthy_fixture_all_checks_pass():
    results = run_all(FIXTURE_DIR)
    failed = [r for r in results if not r.passed]
    assert not failed, f"expected all checks to pass, but these failed: {[r.name for r in failed]}"
    assert len(results) >= 12  # sanity: the full check suite actually ran


def test_load_dump_reads_all_five_files():
    dump = load_dump(FIXTURE_DIR)
    assert dump.summary["pipeline_status"] == "complete"
    assert len(dump.analysis) == 12
    assert dump.reasoning["status"] == "success"
    assert dump.strategy["status"] == "success"
    assert dump.report["status"] == "success"


def test_load_dump_missing_file_is_none(tmp_path):
    dump_dir = _copy_fixture(tmp_path)
    os.remove(os.path.join(dump_dir, "strategy.json"))
    dump = load_dump(dump_dir)
    assert dump.strategy is None


# ── Corrupted variants: each check should catch its specific bug ────────────


def test_hallucinated_evidence_id_fails_groundedness(tmp_path):
    dump_dir = _copy_fixture(tmp_path)
    path = os.path.join(dump_dir, "reasoning.json")
    reasoning = _load_json(path)
    reasoning["patterns"][0]["evidence_review_ids"].append("NONEXISTENT_rev_9999")
    _write_json(path, reasoning)

    results = run_all(dump_dir)
    hit = [r for r in results if r.name.endswith(":evidence_exists") and not r.passed]
    assert hit, "expected the hallucinated evidence id to fail an evidence_exists check"


def test_wrong_frequency_fails_groundedness(tmp_path):
    dump_dir = _copy_fixture(tmp_path)
    path = os.path.join(dump_dir, "reasoning.json")
    reasoning = _load_json(path)
    reasoning["patterns"][0]["frequency"] = 0.99  # real value is 0.5
    _write_json(path, reasoning)

    results = run_all(dump_dir)
    hit = [r for r in results if r.name.endswith(":frequency") and not r.passed]
    assert hit, "expected the wrong frequency claim to fail a frequency check"


def test_fabricated_root_cause_fails_report_subset(tmp_path):
    dump_dir = _copy_fixture(tmp_path)
    path = os.path.join(dump_dir, "report.json")
    report = _load_json(path)
    report["root_causes"].append(
        {"pattern": "made up pattern", "cause": "fabricated cause not present upstream", "confidence": "high"}
    )
    _write_json(path, report)

    results = run_all(dump_dir)
    hit = [r for r in results if r.name == "report_subset:root_causes" and not r.passed]
    assert hit, "expected a fabricated root cause to fail the report-subset check"


def test_halted_status_fails_completion_check(tmp_path):
    dump_dir = _copy_fixture(tmp_path)
    path = os.path.join(dump_dir, "_summary.json")
    summary = _load_json(path)
    summary["pipeline_status"] = "halted"
    summary["failed_agent"] = "strategy_agent"
    _write_json(path, summary)

    results = run_all(dump_dir)
    completion = next(r for r in results if r.name == "completion_status")
    assert not completion.passed


def test_hallucinated_sentiment_fails_schema_validity(tmp_path):
    dump_dir = _copy_fixture(tmp_path)
    path = os.path.join(dump_dir, "analysis.json")
    analysis = _load_json(path)
    analysis[0] = copy.deepcopy(analysis[0])
    analysis[0]["sentiment"] = "ecstatic"  # not one of the allowed Literal values
    _write_json(path, analysis)

    results = run_all(dump_dir)
    schema = next(r for r in results if r.name == "schema_validity:analysis")
    assert not schema.passed


def test_skipped_stage_is_vacuously_grounded(tmp_path):
    """A None (skipped) stage should not be flagged as a groundedness/traceability
    failure - it has nothing to check, not something wrong to check."""
    dump_dir = _copy_fixture(tmp_path)
    os.remove(os.path.join(dump_dir, "reasoning.json"))

    results = run_all(dump_dir)
    groundedness = [r for r in results if r.name == "reasoning_groundedness"]
    assert groundedness and groundedness[0].passed
