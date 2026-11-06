"""Acceptance 5: publish v2 while v1 runs, withdraw v1 mid-run, withdraw evidence MB2."""
import copy

from app.seed import PB2_V1


def publish_v2(as_):
    d = copy.deepcopy(PB2_V1)
    d["nodes"]["K1"]["prompt"] = "Read indicator B in the simulator and note the colour."
    r = as_("ari").post("/pathways/PB2/drafts", json={"definition": d})
    assert r.status_code == 200 and r.json()["valid"] and r.json()["version"] == 2
    r = as_("ren").post("/pathways/PB2/versions/2/publish")
    assert r.status_code == 200, r.text


def second_run(as_, flow):
    v = flow.case("C105")["version"]
    as_("ana").post("/cases/C105/confirmations", json={"model": "B", "revision": "2", "expectedVersion": v})
    return flow.start(cid="C105")


def test_existing_runs_stay_pinned_new_runs_use_v2(as_, flow):
    run1 = flow.ready_run()
    flow.answer(run1, "green")
    publish_v2(as_)
    assert flow.run(run1)["pathwayVersion"] == 1
    assert flow.answer(run1, "pass").status_code == 200  # v1 keeps running on its own frozen nodes
    run2 = second_run(as_, flow)
    assert run2["pathwayVersion"] == 2
    assert run2["currentStep"]["prompt"] == "Read indicator B in the simulator and note the colour."


def test_withdraw_v1_pauses_before_the_next_step(as_, flow):
    run1 = flow.ready_run()
    flow.answer(run1, "green")
    publish_v2(as_)
    run2 = second_run(as_, flow)["runId"]
    assert as_("ren").post("/pathways/PB2/versions/1/withdraw").status_code == 200
    st = flow.run(run1)
    assert st["status"] == "paused" and "withdrawn" in st["pauseReason"]
    r = flow.answer(run1, "pass", version=st["version"])
    assert r.status_code == 409 and r.json()["runStatus"] == "paused"
    assert flow.run(run1)["currentStepId"] == "K2"
    assert flow.run(run2)["status"] == "active"  # v2 run unaffected
    # an old tab still showing v1 is rejected too
    old_tab = flow.answer(run1, "pass", version=2)
    assert old_tab.status_code == 409


def test_withdrawn_versions_block_new_runs(as_, flow):
    flow.confirm()
    as_("ren").post("/pathways/PB2/versions/1/withdraw")
    v = flow.case()["version"]
    r = as_("ana").post("/cases/C104/runs", json={"pathwayId": "PB2", "technicianId": "teo", "expectedVersion": v})
    assert r.status_code == 409


def test_withdraw_mb2_removes_guidance_and_blocks_execution(as_, flow):
    run1 = flow.ready_run()
    r = as_("ren").post("/sources/MB2/withdraw")
    assert r.status_code == 200 and r.json()["pausedRuns"] == [run1]
    ans = as_("ana").post("/cases/C104/questions", json={"question": "D17"}).json()
    assert all(c["sourceId"] != "MB2" for c in ans["citations"])
    assert ans["eligiblePathways"] == [] and ans["kind"] == "escalate"
    assert as_("ana").get("/search", params={"q": "indicator B"}).json()["results"] == []
    st = flow.run(run1)
    assert st["status"] == "paused"
    assert flow.answer(run1, "green", version=st["version"]).status_code == 409
    # history is preserved
    trace = as_("ren").get("/api/cases/C104/trace").json()
    assert "run.started" in [e["action"] for e in trace["events"]]
    assert "run.paused" in [e["action"] for e in trace["events"]]


def test_applicability_correction_pauses_run_and_needs_a_fresh_one(as_, flow):
    run1 = flow.ready_run()
    flow.confirm("B", "1")
    st = flow.run(run1)
    assert st["status"] == "paused" and "corrected" in st["pauseReason"]
    assert flow.answer(run1, "green", version=st["version"]).status_code == 409
    flow.confirm("B", "2")
    run2 = flow.start()
    assert run2["runId"] != run1 and run2["currentStepId"] == "K1"
