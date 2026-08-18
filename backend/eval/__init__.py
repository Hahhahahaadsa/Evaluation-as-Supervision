"""Three-tier evaluation harness for the multi-agent review pipeline.

Tier 1  deterministic checks (no labels, no API) .... tier1_checks.py
Tier 1b pipeline harness (latency / repro / degrade)  harness.py
Tier 2  analysis-agent gold set (accuracy + macro-F1)  tier2_analysis.py
Tier 3  rubric LLM-as-judge (subjective stages) ....  tier3_judge.py

All tiers consume the per-stage JSON written by
``python run_pipeline.py --dump-stages <dir>`` so a pipeline run and its
scoring stay decoupled. See README.md in this directory and README section 14.

STATUS: scaffold only. Function bodies are TODO stubs.
"""
