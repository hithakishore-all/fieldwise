"""Acceptance 6: idempotent imports, malformed records, graph validation, no self-approval, templates."""
import copy
import json
from pathlib import Path

from app.seed import PB2_V1

SAMPLE = json.loads((Path(__file__).resolve().parent.parent / "samples" / "import_manifest.json").read_text())


def sources(as_):
    return as_("ari").get("/api/sources").json()


def test_import_twice_is_stable_and_malformed_record_is_rejected(as_):
    before = len(sources(as_))
    r1 = as_("ari").post("/imports", json=SAMPLE).json()
    assert (r1["acceptedCount"], r1["rejectedCount"]) == (2, 1)
    bad = r1["rejected"][0]
    assert bad["record"] == "MB2-X" and any("locator" in x for x in bad["reasons"])
    after = sources(as_)
    assert len(after) == before + 2
    r2 = as_("ari").post("/imports", json=SAMPLE).json()
    assert r2["repeated"] and r2["jobId"] == r1["jobId"]
    assert len(sources(as_)) == len(after)
    job = as_("ari").get(f"/imports/{r1['jobId']}").json()
    assert job["acceptedCount"] == 2


def test_imported_aliases_are_normalized(as_):
    as_("ari").post("/imports", json=SAMPLE)
    hits = as_("ari").get("/search", params={"q": "D-17"}).json()["results"]
    assert any(h["sourceId"] == "MC1" for h in hits)


def test_tenant_comes_from_uploader(as_):
    as_("sol").post("/imports", json=SAMPLE)  # technician cannot import
    assert as_("sol").post("/imports", json=SAMPLE).status_code == 403
    as_("ari").post("/imports", json=SAMPLE)
    assert all(x["sourceId"] != "MC1" for x in as_("sol").get("/api/sources").json())


def test_changed_content_under_same_external_id_is_rejected(as_):
    as_("ari").post("/imports", json=SAMPLE)
    changed = copy.deepcopy(SAMPLE)
    changed["records"][0]["passages"][0]["text"] = "Different words"
    r = as_("ari").post("/imports", json=changed).json()
    assert any(x["record"] == "MC1" for x in r["rejected"])


def test_unreachable_node_and_missing_step_are_rejected(as_):
    d = copy.deepcopy(PB2_V1)
    d["nodes"]["K3"] = {"kind": "step", "prompt": "Orphan step", "inputs": ["ok"], "edges": {"ok": "R"}}
    d["nodes"]["V1"]["inputs"].append("retry")
    d["nodes"]["V1"]["edges"]["retry"] = "K9"
    r = as_("ari").post("/pathways/PB2/drafts", json={"definition": d}).json()
    assert not r["valid"]
    assert any("routes to missing step K9" in e for e in r["errors"])
    pub = as_("ren").post(f"/pathways/PB2/versions/{r['version']}/publish")
    assert pub.status_code == 422  # failed publication
    assert any("K9" in e for e in pub.json()["errors"])
    d2 = copy.deepcopy(PB2_V1)
    d2["nodes"]["K3"] = {"kind": "step", "prompt": "Orphan step", "inputs": ["ok"], "edges": {"ok": "R"}}
    r2 = as_("ari").post("/pathways/PB2/drafts", json={"definition": d2}).json()
    assert any("K3 is unreachable" in e for e in r2["errors"])
    versions = as_("ari").get("/api/pathways").json()
    pb2 = next(p for p in versions if p["pathwayId"] == "PB2")
    assert [v["status"] for v in pb2["versions"]] == ["published", "draft"]


def test_other_graph_rules(as_):
    d = copy.deepcopy(PB2_V1)
    d["nodes"]["V1"]["edges"]["unknown"] = "K1"  # cycle
    d["nodes"]["K2"]["inputs"].append("maybe")  # input without an edge
    d["nodes"]["E1"].pop("openQuestion")  # escalation without question
    d["nodes"]["K1"]["citation"] = {"source": "MA1", "locator": "p8"}  # wrong model
    errs = as_("ari").post("/pathways/PB2/drafts", json={"definition": d}).json()["errors"]
    text = " ".join(errs)
    assert "cycles are not allowed" in text and "'maybe' has no edge" in text
    assert "needs an open question" in text and "does not apply to Model B rev 2" in text


def test_author_cannot_self_approve_and_replacement_publishes(as_):
    d = copy.deepcopy(PB2_V1)
    d["nodes"]["K1"]["prompt"] = "Replacement wording for indicator B."
    r = as_("ari").post("/pathways/PB2/drafts", json={"definition": d}).json()
    assert r["valid"]
    # Ari is an author, not a reviewer; even a reviewer cannot publish their own draft
    assert as_("ari").post("/pathways/PB2/versions/2/publish").status_code == 403
    v = as_("ren").post("/pathways/PB2/drafts", json={"definition": d})
    assert v.status_code == 403  # reviewers don't author here
    assert as_("ren").post("/pathways/PB2/versions/2/publish").json()["status"] == "published"
    # published versions are immutable
    assert as_("ren").post("/pathways/PB2/versions/2/publish").status_code == 409


def test_template_binds_per_revision_and_cannot_invent_evidence(as_):
    ok = as_("ari").post("/templates/T-IND/apply", json={"revisionNode": "ELEV-B-2"})
    assert ok.status_code == 200 and ok.json()["valid"]
    assert [(b["slot"], b["source"], b["locator"]) for b in ok.json()["bound"]] == [("K1", "MB2", "p14"), ("K2", "MB2", "p15")]
    blocked = as_("ari").post("/templates/T-IND/apply", json={"revisionNode": "ELEV-A-1"})
    assert blocked.status_code == 422
    assert any("Slot K2 (self-test)" in e for e in blocked.json()["errors"])
