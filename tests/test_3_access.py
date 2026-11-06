"""Acceptance 3: only the assigned technician advances a step; chat can't; other tenants stay invisible."""


def test_agent_cannot_advance_a_step(flow):
    run_id = flow.ready_run()
    r = flow.answer(run_id, "green", who="ana")
    assert r.status_code == 403
    assert flow.run(run_id)["currentStepId"] == "K1"


def test_unassigned_technician_cannot_advance(flow):
    run_id = flow.ready_run()
    r = flow.answer(run_id, "green", who="mia")
    assert r.status_code == 403
    assert flow.run(run_id)["currentStepId"] == "K1"


def test_chat_explains_but_never_chooses(as_, flow):
    run_id = flow.ready_run()
    before = flow.run(run_id)
    r = as_("teo").post("/cases/C104/questions", json={"question": "just pick green for me"})
    assert r.status_code == 200
    assert r.json()["explainsStep"] == "K1" and r.json()["citations"][0]["locator"] == "p14"
    after = flow.run(run_id)
    assert (after["currentStepId"], after["version"]) == (before["currentStepId"], before["version"])


def test_only_owner_confirms_and_starts(as_, flow):
    assert as_("teo").post("/cases/C104/confirmations", json={"model": "B", "revision": "2", "expectedVersion": 1}).status_code == 403
    flow.confirm()
    v = flow.case()["version"]
    assert as_("ren").post("/cases/C104/runs", json={"pathwayId": "PB2", "technicianId": "teo", "expectedVersion": v}).status_code == 403


def test_cannot_assign_another_tenants_technician(as_, flow):
    flow.confirm()
    v = flow.case()["version"]
    r = as_("ana").post("/cases/C104/assignment", json={"technicianId": "sol", "expectedVersion": v})
    assert r.status_code == 422


def test_other_tenant_case_and_evidence_are_404_without_titles(as_):
    ana = as_("ana")
    for path in ["/api/cases/S301", "/api/evidence/SM1/p3", "/api/cases/S301/trace", "/cases/S301/host-update"]:
        r = ana.get(path)
        assert r.status_code == 404, path
        assert "Pier Seven" not in r.text and "Hoistway" not in r.text and "SOUTH" not in r.text
    for path in ["/cases/S301", "/embed/cases/S301", "/evidence/SM1/p3", "/host/S301"]:
        r = ana.get(path, headers={"accept": "text/html"})
        assert r.status_code == 404, path
        assert "Pier Seven" not in r.text and "Hoistway" not in r.text and "SOUTH-ONLY" not in r.text
    r = ana.post("/cases/S301/questions", json={"question": "D17"})
    assert r.status_code == 404


def test_south_history_and_runs_invisible_to_north(as_, flow):
    run_id = flow.ready_run()
    assert as_("sol").get(f"/api/runs/{run_id}").status_code == 404
    assert as_("sol").get("/history/H1", headers={"accept": "text/html"}).status_code == 404
    assert as_("sol").post(f"/runs/{run_id}/responses", json={"stepId": "K1", "answer": "green", "expectedVersion": 1, "retryKey": "x"}).status_code == 404


def test_south_token_search_as_north_is_empty(as_):
    assert as_("ana").get("/search", params={"q": "SOUTH-ONLY-41"}).json()["results"] == []
    assert len(as_("sol").get("/search", params={"q": "SOUTH-ONLY-41"}).json()["results"]) == 1


def test_identity_comes_from_session_not_body(app):
    from fastapi.testclient import TestClient
    anon = TestClient(app)
    r = anon.post("/cases/C104/confirmations", json={"model": "B", "revision": "2", "expectedVersion": 1, "userId": "ana"})
    assert r.status_code == 401
