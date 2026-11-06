"""Acceptance 7: verified closure, one simulated host failure, restart, retry, exactly one summary at the host."""
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app import db, models
from app.main import create_app


def resolve(as_, flow):
    run_id = flow.ready_run()
    for a in ("green", "pass", "yes"):
        assert flow.answer(run_id, a).status_code == 200
    v = flow.run(run_id)["version"]
    r = as_("teo").post("/cases/C104/outcomes", json={"verification": "Cycled 10 times; D17 cleared", "actionTaken": "Per PB2", "expectedVersion": v})
    assert r.status_code == 200
    as_("teo").post(f"/runs/{run_id}/feedback", json={"stepId": "K1", "helpful": True, "comment": "Clear"})
    return run_id


def host_count():
    with db.SessionLocal() as s:
        return s.scalar(select(func.count()).select_from(models.HostRecord))


def test_close_fail_restart_retry_delivers_exactly_once(as_, flow, db_url):
    resolve(as_, flow)
    prev = as_("ana").get("/cases/C104/host-update").json()
    assert prev["summary"]["outcome"] == "resolved" and prev["delivery"] is None
    assert [s["step"] for s in prev["summary"]["attemptedSteps"]] == ["K1", "K2", "V1"]
    d1 = as_("ana").post("/cases/C104/host-update/approve").json()
    d2 = as_("ana").post("/cases/C104/host-update/approve").json()
    assert d1["deliveryKey"] == d2["deliveryKey"]  # enqueued once
    as_("ana").post("/host/failure", json={"failNext": True})
    failed = as_("ana").post(f"/deliveries/{d1['deliveryKey']}/send").json()
    assert failed["status"] == "failed" and host_count() == 0
    # restart
    db.engine.dispose()
    db.configure(db_url)
    fresh = TestClient(create_app())
    fresh.post("/demo/login", data={"user_id": "ana"})
    ok = fresh.post(f"/deliveries/{d1['deliveryKey']}/send").json()
    assert ok["status"] == "delivered" and ok["receipt"]
    again = fresh.post(f"/deliveries/{d1['deliveryKey']}/send").json()
    assert again["receipt"] == ok["receipt"]
    assert host_count() == 1
    rec = fresh.get("/api/host/records").json()
    assert len(rec) == 1 and rec[0]["payload"]["verification"] == "Cycled 10 times; D17 cleared"


def test_only_owner_approves(as_, flow):
    resolve(as_, flow)
    assert as_("teo").post("/cases/C104/host-update/approve").status_code == 403


def test_unresolved_case_carries_attempted_steps_and_open_question(as_, flow):
    run_id = flow.ready_run()
    flow.answer(run_id, "green")
    flow.answer(run_id, "fail")
    s = as_("ana").get("/cases/C104/host-update").json()["summary"]
    assert s["outcome"] == "escalated"
    assert s["openQuestion"] == "What is causing the simulated indicator anomaly on this unit?"
    assert [(a["step"], a["answer"]) for a in s["attemptedSteps"]] == [("K1", "green"), ("K2", "fail")]
    d = as_("ana").post("/cases/C104/host-update/approve").json()
    assert as_("ana").post(f"/deliveries/{d['deliveryKey']}/send").json()["status"] == "delivered"


def test_c105_keeps_its_own_history(as_, flow):
    as_("ana").post("/cases/C104/questions", json={"question": "D17"})
    resolve(as_, flow)
    with db.SessionLocal() as s:
        c105 = s.scalar(select(models.Case).where(models.Case.key == "C105"))
        assert s.scalar(select(func.count()).select_from(models.Message).where(models.Message.case_id == c105.id)) == 0
        assert s.scalar(select(func.count()).select_from(models.Observation).where(models.Observation.case_id == c105.id)) == 0
    page = as_("ana").get("/embed/cases/C105", headers={"accept": "text/html"}).text
    assert "What does D17" not in page.split("Assistant")[1].split("<form")[0]
    assert flow.case("C105")["status"] == "open" and flow.case("C105")["run"] is None


def test_reviewer_sees_evidence_steps_feedback_outcome_in_order(as_, flow):
    resolve(as_, flow)
    t = as_("ren").get("/api/cases/C104/trace").json()
    assert t["runs"][0]["attemptedSteps"][0]["citation"] == "MB2 p14"
    assert t["feedback"] == [{"step": "K1", "helpful": True, "comment": "Clear", "by": "teo"}]
    assert t["outcomes"][0]["kind"] == "resolved"
    actions = [e["action"] for e in t["events"]]
    assert actions.index("run.started") < actions.index("run.step_answered") < actions.index("case.resolved") < actions.index("run.feedback")
