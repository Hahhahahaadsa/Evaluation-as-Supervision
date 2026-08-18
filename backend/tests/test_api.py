import json

import pandas as pd
from fastapi.testclient import TestClient

from app import main


client = TestClient(main.app)


def _reviews():
    return pd.DataFrame([
        {"review_id": "r1", "business_id": "b1", "stars": 5, "text": "Great", "date": "2026-01-01"},
        {"review_id": "r2", "business_id": "b1", "stars": 2, "text": "Slow", "date": "2026-01-02"},
    ])


def _pipeline_state():
    return {
        "pipeline_status": "complete",
        "analysis_results": [
            {"review_id": "r1", "sentiment": "positive", "aspects": [], "status": "success", "error_detail": None},
            {"review_id": "r2", "sentiment": "negative", "aspects": [], "status": "success", "error_detail": None},
        ],
        "reasoning_output": {"patterns": []},
        "report_output": {
            "title": "Restaurant Review Analysis Report",
            "business_name": "Wrong",
            "sample_size": 999,
            "executive_summary": "Summary",
            "key_findings": [],
            "root_causes": [],
            "recommendations": [],
            "limitations": [],
            "status": "success",
            "error_detail": None,
        },
    }


def test_report_endpoint_returns_trusted_metadata(monkeypatch):
    monkeypatch.setattr(main, "load_reviews", lambda business_id, sample_size: _reviews())
    monkeypatch.setattr(main, "preprocess", lambda reviews: reviews)
    monkeypatch.setattr(main, "run_pipeline", lambda *args: _pipeline_state())

    response = client.post("/api/reports", json={
        "restaurant_name": "Trusted Name",
        "business_id": "b1",
        "sample_size": 2,
    })

    assert response.status_code == 200
    assert response.json()["business_name"] == "Trusted Name"
    assert response.json()["sample_size"] == 2


def test_stream_endpoint_emits_progress_and_trusted_report(monkeypatch):
    class FakeGraph:
        def stream(self, state, config=None, stream_mode=None):
            final = _pipeline_state()
            for stage in main._AGENT_SEQUENCE:
                yield {stage: final}

    monkeypatch.setattr(main, "load_reviews", lambda business_id, sample_size: _reviews())
    monkeypatch.setattr(main, "preprocess", lambda reviews: reviews)
    monkeypatch.setattr(main, "build_pipeline", FakeGraph)

    response = client.get(
        "/api/reports/stream",
        params={"restaurant_name": "Trusted Name", "business_id": "b1", "sample_size": 2},
    )
    events = [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert events[0] == {"type": "stage_start", "stage": "search_business"}
    assert events[-1]["type"] == "done"
    assert events[-1]["report"]["business_name"] == "Trusted Name"
    assert events[-1]["report"]["sample_size"] == 2
