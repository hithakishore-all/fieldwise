"""Acceptance 4 and the build prompt's worked example: replays, conflicting writes, retry-key reuse, restart."""
import os
import threading

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app import db, models
from app.main import create_app


def count_responses():
    with db.SessionLocal() as s:
        return s.scalar(select(func.count()).select_from(models.Response))


def test_worked_example_and_restart(as_, flow, db_url):
    run_id = flow.ready_run()
    payload = {"stepId": "K1", "answer": "green", "expectedVersion": 1, "retryKey": "demo-1"}
    r1 = as_("teo").post(f"/runs/{run_id}/responses", json=payload)
    assert r1.status_code == 200
    assert r1.json() == {"runId": run_id, "version": 2, "status": "active", "nextStepId": "K2"}
    r2 = as_("teo").post(f"/runs/{run_id}/responses", json=payload)
    assert r2.status_code == 200 and r2.json() == r1.json()
    assert count_responses() == 1
    r3 = as_("teo").post(f"/runs/{run_id}/responses", json={**payload, "retryKey": "demo-2"})
    assert r3.status_code == 409
    # "restart the process": drop every connection and build a fresh app on the same database
    db.engine.dispose()
    db.configure(db_url)
    fresh = TestClient(create_app())
    fresh.post("/demo/login", data={"user_id": "teo"})
    st = fresh.get(f"/api/runs/{run_id}").json()
    assert (st["currentStepId"], st["version"], st["pathwayVersion"]) == ("K2", 2, 1)


def test_retry_key_reused_with_different_input_is_409(as_, flow):
    run_id = flow.ready_run()
    as_("teo").post(f"/runs/{run_id}/responses", json={"stepId": "K1", "answer": "green", "expectedVersion": 1, "retryKey": "k"})
    r = as_("teo").post(f"/runs/{run_id}/responses", json={"stepId": "K1", "answer": "amber", "expectedVersion": 1, "retryKey": "k"})
    assert r.status_code == 409
    assert flow.run(run_id)["currentStepId"] == "K2"


def test_two_conflicting_writes_one_commits(as_, flow):
    run_id = flow.ready_run()
    a = as_("teo").post(f"/runs/{run_id}/responses", json={"stepId": "K1", "answer": "green", "expectedVersion": 1, "retryKey": "tab-a"})
    b = as_("teo").post(f"/runs/{run_id}/responses", json={"stepId": "K1", "answer": "amber", "expectedVersion": 1, "retryKey": "tab-b"})
    assert sorted([a.status_code, b.status_code]) == [200, 409]
    assert count_responses() == 1
    assert flow.run(run_id)["currentStepId"] == "K2"


@pytest.mark.skipif(not os.environ.get("FIELDWISE_TEST_DATABASE_URL"), reason="true parallel writes need PostgreSQL")
def test_parallel_writes_on_postgres(app, as_, flow):
    run_id = flow.ready_run()
    barrier, codes = threading.Barrier(2), []

    def go(answer, k):
        c = TestClient(app)
        c.post("/demo/login", data={"user_id": "teo"})
        barrier.wait()
        codes.append(c.post(f"/runs/{run_id}/responses", json={"stepId": "K1", "answer": answer, "expectedVersion": 1, "retryKey": k}).status_code)

    ts = [threading.Thread(target=go, args=("green", "p1")), threading.Thread(target=go, args=("amber", "p2"))]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert sorted(codes) == [200, 409]
    assert count_responses() == 1


def test_stale_case_version_is_409(as_, flow):
    flow.confirm()
    r = as_("ana").post("/cases/C104/confirmations", json={"model": "B", "revision": "2", "expectedVersion": 1})
    assert r.status_code == 409 and r.json()["currentVersion"] == 2
