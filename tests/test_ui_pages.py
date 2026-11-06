"""Every screen renders, and the author and reviewer forms work end to end through the HTML routes."""
import copy
import json
from pathlib import Path

from app.seed import PB2_V1

HTML = {"accept": "text/html"}
SAMPLE = (Path(__file__).resolve().parent.parent / "samples" / "import_manifest.json").read_text()


def test_pages_render_for_each_role(as_, flow):
    run_id = flow.ready_run()
    pages = {"ana": ["/login", "/host/C104", "/cases/C104", "/embed/cases/C105", "/hierarchy", "/evidence/MB2/p14", "/history/H1"],
             "teo": ["/runs", f"/runs/{run_id}"],
             "ari": ["/knowledge", "/knowledge?edit=PA1", "/knowledge?q=indicator"],
             "ren": ["/review", "/review/cases/C104"]}
    for who, paths in pages.items():
        for p in paths:
            r = as_(who).get(p, headers=HTML)
            assert r.status_code == 200, (who, p, r.status_code)
            assert "Demo identity" in r.text or "embedded" in r.text


def test_unauthenticated_html_redirects_to_login(app):
    from fastapi.testclient import TestClient
    r = TestClient(app).get("/cases/C104", headers=HTML, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/login")


def test_author_import_and_draft_then_reviewer_publish_via_forms(as_):
    ari, ren = as_("ari"), as_("ren")
    r = ari.post("/ui/imports", data={"manifest": SAMPLE})
    assert "2 accepted, 1 rejected" in r.text
    r = ari.post("/ui/imports", data={"manifest": SAMPLE})
    assert "nothing new imported" in r.text
    assert "That is not valid JSON" in ari.post("/ui/imports", data={"manifest": "{oops"}).text
    d = copy.deepcopy(PB2_V1)
    d["nodes"]["K1"]["prompt"] = "Read indicator B and note its colour."
    r = ari.post("/ui/pathways/PB2/draft", data={"definition": json.dumps(d)})
    assert "Valid: ready for review" in r.text
    assert "403" in ari.post("/ui/pathways/PB2/2/publish").text
    r = ren.post("/ui/pathways/PB2/2/publish")
    assert "Published PB2 v2" in r.text
    r = ren.post("/ui/pathways/PB2/1/withdraw")
    assert "Withdrew PB2 v1" in r.text
    r = ari.post("/ui/templates/T-IND/apply", data={"node": "ELEV-A-1"})
    assert "cannot invent evidence" in r.text


def test_technician_screens_and_blocked_agent(as_, flow):
    run_id = flow.ready_run()
    page = as_("ana").get(f"/runs/{run_id}", headers=HTML).text
    assert "Only the assigned technician" in page and "disabled" in page
    teo = as_("teo")
    r = teo.post(f"/ui/runs/{run_id}/respond", data={"step": "K1", "answer": "green", "version": 1, "retry": "r1"})
    assert "Saved K1 = green" in r.text and "Step K2" in r.text
    r = teo.post(f"/ui/runs/{run_id}/ask", data={"question": "which colour is fine?"})
    assert "only a submitted answer moves the procedure" in r.text
    assert flow.run(run_id)["currentStepId"] == "K2"
