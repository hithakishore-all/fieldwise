"""Acceptance 2: every edge from K1, K2 and V1 follows the seed definition; terminals, reloads, premature closure, ordered trace."""
import pytest

from app.seed import PB2_V1

PATHS = [  # answers in order -> (terminal, run status)
    (["green", "pass", "yes"], "R", "awaiting_outcome"),
    (["green", "pass", "no"], "E3", "escalated"),
    (["green", "pass", "unknown"], "E3", "escalated"),
    (["green", "fail"], "E1", "escalated"),
    (["green", "unknown"], "E2", "escalated"),
    (["amber"], "E1", "escalated"),
    (["unreadable"], "E2", "escalated"),
]


def test_every_seed_edge_is_covered():
    covered = set()
    for answers, _, _ in PATHS:
        node = PB2_V1["start"]
        for a in answers:
            covered.add((node, a))
            node = PB2_V1["nodes"][node]["edges"][a]
    expected = {(k, a) for k, n in PB2_V1["nodes"].items() if n["kind"] == "step" for a in n["edges"]}
    assert covered == expected


@pytest.mark.parametrize("answers,terminal,status", PATHS)
def test_path(as_, flow, answers, terminal, status):
    run_id = flow.ready_run()
    node = "K1"
    for i, a in enumerate(answers):
        r = flow.answer(run_id, a)
        assert r.status_code == 200, r.text
        nxt = PB2_V1["nodes"][node]["edges"][a]
        assert r.json()["nextStepId"] == nxt and r.json()["version"] == i + 2
        # reload after each step: same run, same pinned version, same step
        st = flow.run(run_id)
        assert (st["runId"], st["pathwayVersion"], st["currentStepId"]) == (run_id, 1, nxt)
        node = nxt
    st = flow.run(run_id)
    assert st["currentStepId"] == terminal and st["status"] == status
    case = flow.case()
    if status == "escalated":
        assert case["status"] == "escalated"
        trace = as_("ren").get("/api/cases/C104/trace").json()
        out = trace["outcomes"][-1]
        assert out["terminal"] == terminal and out["openQuestion"]
        assert [s["answer"] for s in out["attemptedSteps"]] == answers
    else:
        assert case["status"] == "open"


def test_premature_closure_is_refused(as_, flow):
    run_id = flow.ready_run()
    flow.answer(run_id, "green")
    r = as_("teo").post("/cases/C104/outcomes", json={"verification": "looks fine", "expectedVersion": 2})
    assert r.status_code == 409
    assert flow.case()["status"] == "open"


def test_resolved_needs_a_verification_note(as_, flow):
    run_id = flow.ready_run()
    for a in ("green", "pass", "yes"):
        flow.answer(run_id, a)
    v = flow.run(run_id)["version"]
    assert as_("teo").post("/cases/C104/outcomes", json={"verification": " ", "expectedVersion": v}).status_code == 422
    r = as_("teo").post("/cases/C104/outcomes", json={"verification": "Cycled 10 times", "actionTaken": "Per PB2", "expectedVersion": v})
    assert r.status_code == 200 and r.json()["kind"] == "resolved"
    assert flow.case()["status"] == "resolved"


def test_ordered_audit_trace(as_, flow):
    run_id = flow.ready_run()
    for a in ("green", "pass", "yes"):
        flow.answer(run_id, a)
    v = flow.run(run_id)["version"]
    as_("teo").post("/cases/C104/outcomes", json={"verification": "ok", "expectedVersion": v})
    trace = as_("ren").get("/api/cases/C104/trace").json()
    actions = [e["action"] for e in trace["events"]]
    expected = ["case.opened", "case.applicability_confirmed", "case.assigned", "run.started",
                "run.step_answered", "run.step_answered", "run.step_answered", "case.resolved"]
    assert actions == expected
    assert [e["seq"] for e in trace["events"]] == sorted(e["seq"] for e in trace["events"])
    steps = [(e["detail"]["step"], e["detail"]["answer"]) for e in trace["events"] if e["action"] == "run.step_answered"]
    assert steps == [("K1", "green"), ("K2", "pass"), ("V1", "yes")]


def test_invalid_choice_is_422(flow):
    run_id = flow.ready_run()
    r = flow.answer(run_id, "purple")
    assert r.status_code == 422 and r.json()["allowed"] == ["green", "amber", "unreadable"]
    assert flow.run(run_id)["currentStepId"] == "K1"
