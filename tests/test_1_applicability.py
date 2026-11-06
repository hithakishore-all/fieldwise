"""Acceptance 1: ambiguous D17 clarifies with no repair action; confirmed B rev 2 gets cited, scoped guidance."""
import pytest


def ask(as_, q, who="ana", cid="C104"):
    r = as_(who).post(f"/cases/{cid}/questions", json={"question": q})
    assert r.status_code == 200, r.text
    return r.json()


def test_ambiguous_d17_clarifies_with_zero_steps(as_):
    r = ask(as_, "doors keep reopening, D17")
    assert r["kind"] == "clarify"
    assert r["missingFields"] == ["model", "revision"]
    assert r["citations"] == [] and r["eligiblePathways"] == []
    # asking never infers the model from the serial or the asset ID
    case = as_("ana").get("/api/cases/C104").json()
    assert case["applicability"] == {"model": None, "revision": None}


@pytest.mark.parametrize("phrase", ["What does D17 mean here?", "what about d-17?"])
def test_confirmed_b2_returns_mb2_p14_pb2_and_history(as_, flow, phrase):
    flow.confirm("B", "2")
    r = ask(as_, phrase)
    assert r["kind"] == "answer"
    cites = [(c["sourceId"], c["revision"], c["locator"]) for c in r["citations"]]
    assert cites[0] == ("MB2", "2", "p14")
    assert all(src not in ("MA1", "MB1") for src, _, _ in cites)
    assert r["eligiblePathways"] == [{"pathwayId": "PB2", "version": 1, "name": "D17 door reopen · Model B rev 2"}]
    assert r["history"]["label"] == "1 verified recovery in 2 matching cases"
    assert [h["id"] for h in r["history"]["cases"]] == ["H1", "H2"]


def test_only_one_missing_field_is_asked_for(as_):
    # confirm without a revision is rejected, so the case still needs both
    r = as_("ana").post("/cases/C104/confirmations", json={"model": "B", "revision": "", "expectedVersion": 1})
    assert r.status_code == 422


def test_citation_opens_exact_passage(as_, flow):
    flow.confirm()
    c = ask(as_, "D17")["citations"][0]
    p = as_("ana").get(f"/api/evidence/{c['sourceId']}/{c['locator']}").json()
    assert p["text"] == "Read indicator B in the simulator. Record green, amber or unreadable."
    assert (p["revision"], p["locator"], p["page"], p["status"]) == ("2", "p14", 14, "current")


def test_unknown_question_returns_insufficient_evidence(as_, flow):
    flow.confirm()
    r = ask(as_, "What is the warranty on the paint?")
    assert r["kind"] == "escalate" and "Insufficient evidence" in r["text"]


def test_only_obsolete_guidance_explains_why_unavailable(as_, flow):
    flow.confirm("B", "1")  # only superseded MB1 covers B rev 1
    r = ask(as_, "D17")
    assert r["kind"] == "escalate"
    assert "MB1" in r["text"] and "superseded" in r["text"]
    assert r["citations"] == [] and r["eligiblePathways"] == []


def test_model_a_gets_only_ma1(as_, flow):
    flow.confirm("A", "1")
    r = ask(as_, "D17")
    assert [c["sourceId"] for c in r["citations"]] == ["MA1"]
    assert [p["pathwayId"] for p in r["eligiblePathways"]] == ["PA1"]


def test_confirmation_is_attributed_and_links_the_asset(as_, flow):
    flow.confirm()
    tree = as_("ana").get("/api/hierarchy").json()
    car2 = next(a for site in tree["assets"] for a in site["assets"] if a["key"] == "B002")
    assert car2["product"] == "Model B › rev 2"
    trace = as_("ren").get("/api/cases/C104/trace").json()
    ev = next(e for e in trace["events"] if e["action"] == "case.applicability_confirmed")
    assert ev["actor"] == "ana" and ev["detail"]["model"] == "B"
