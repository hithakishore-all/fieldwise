"""Server-rendered screens. Every form posts to a /ui route that calls the same services as the JSON API."""
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models as m
from .db import get_session
from .services import cases as cs
from .services import ops
from .services import pathways as pw
from .services.core import Actor, AppError, load_actor, scoped

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
SAMPLE_MANIFEST = (Path(__file__).resolve().parent.parent / "samples" / "import_manifest.json")
PERSONA = {"agent": "ana", "technician": "teo", "author": "ari", "reviewer": "ren"}


def now():
    return datetime.now(timezone.utc)


def current(request: Request, s: Session) -> Actor | None:
    try:
        return load_actor(s, request.session.get("user_id"))
    except AppError:
        return None


def render(request: Request, s: Session, name: str, actor: Actor | None, status_code=200, **ctx):
    flash = request.session.pop("flash", None)
    return templates.TemplateResponse(request, name, {"actor": actor, "flash": flash, "persona": PERSONA, **ctx},
                                      status_code=status_code)


def back(request: Request, url: str, kind: str = "ok", text: str | None = None):
    if text:
        request.session["flash"] = {"kind": kind, "text": text}
    return RedirectResponse(url, status_code=303)


def need(request: Request, s: Session) -> Actor:
    a = current(request, s)
    if not a:
        raise AppError(401, "unauthenticated", "Pick a demo identity first.")
    return a


def attempt(request: Request, s: Session, url: str, fn, ok_text=None):
    """Run a service call; on a rule failure, show the reason instead of crashing."""
    try:
        result = fn()
        s.commit()
        text = ok_text(result) if callable(ok_text) else ok_text
        return back(request, url, "ok", text)
    except AppError as e:
        s.rollback()
        detail = "; ".join(e.extra.get("errors", [])) if e.extra.get("errors") else ""
        return back(request, url, "bad", f"{e.status} · {e.message}" + (f" {detail}" if detail else ""))


# ---------- identity ----------

@router.get("/login", response_class=HTMLResponse)
def login(request: Request, s: Session = Depends(get_session)):
    rows = s.execute(select(m.User, m.Membership).join(m.Membership, m.Membership.user_id == m.User.id)
                     .order_by(m.Membership.tenant_id, m.User.id)).all()
    return render(request, s, "login.html", current(request, s), people=rows, next=request.query_params.get("next", "/"))


@router.post("/demo/login")
def demo_login(request: Request, user_id: str = Form(...), next: str = Form("/"), s: Session = Depends(get_session)):
    load_actor(s, user_id)
    request.session.clear()
    request.session["user_id"] = user_id
    return RedirectResponse(next if next.startswith("/") else "/", status_code=303)


@router.get("/demo/logout")
def demo_logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


@router.get("/")
def home(request: Request, s: Session = Depends(get_session)):
    a = current(request, s)
    if not a:
        return RedirectResponse("/login", status_code=303)
    if a.role == "technician":
        return RedirectResponse("/runs", status_code=303)
    if a.role == "author":
        return RedirectResponse("/knowledge", status_code=303)
    if a.role == "reviewer":
        return RedirectResponse("/review", status_code=303)
    first = s.scalar(select(m.Case).where(m.Case.tenant_id == a.tenant_id).order_by(m.Case.key))
    return RedirectResponse(f"/host/{first.key}" if first else "/login", status_code=303)


# ---------- case workspace ----------

def workspace_ctx(s: Session, a: Actor, key: str) -> dict:
    case = cs.get_case(s, a, key)
    cases = s.scalars(select(m.Case).where(m.Case.tenant_id == a.tenant_id).order_by(m.Case.key)).all()
    msgs = s.scalars(select(m.Message).where(m.Message.case_id == case.id).order_by(m.Message.id)).all()
    infs = s.scalars(select(m.Inference).where(m.Inference.case_id == case.id)).all()
    obs = s.scalars(select(m.Observation).where(m.Observation.case_id == case.id).order_by(m.Observation.id)).all()
    run = cs.latest_run(s, case)
    techs = s.execute(select(m.User).join(m.Membership, m.Membership.user_id == m.User.id)
                      .where(m.Membership.tenant_id == a.tenant_id, m.Membership.role == "technician")).scalars().all()
    elig = pw.eligible(s, a.tenant_id, case.model, case.revision, cs.detect_codes(s, a.tenant_id, case.intake_text)) \
        if case.model and case.revision else []
    outcome = cs.latest_outcome(s, case)
    delivery = s.scalar(select(m.Delivery).where(m.Delivery.outcome_id == outcome.id)) if outcome else None
    summary = ops.host_summary(s, case, outcome) if outcome else None
    return dict(case=case, cases=cases, msgs=msgs, infs=infs, obs=obs, run=run, techs=techs, elig=elig,
                outcome=outcome, delivery=delivery, summary=summary,
                fail_next=ops.get_setting(s, "host_fail_next") == "1")


@router.get("/cases/{key}", response_class=HTMLResponse)
def workspace(key: str, request: Request, s: Session = Depends(get_session)):
    a = need(request, s)
    return render(request, s, "workspace.html", a, embed=False, **workspace_ctx(s, a, key))


@router.get("/embed/cases/{key}", response_class=HTMLResponse)
def embed(key: str, request: Request, s: Session = Depends(get_session)):
    a = need(request, s)
    return render(request, s, "workspace.html", a, embed=True, **workspace_ctx(s, a, key))


@router.get("/host/{key}", response_class=HTMLResponse)
def host(key: str, request: Request, s: Session = Depends(get_session)):
    a = need(request, s)
    case = cs.get_case(s, a, key)
    cases = s.scalars(select(m.Case).where(m.Case.tenant_id == a.tenant_id).order_by(m.Case.key)).all()
    records = s.scalars(select(m.HostRecord).where(m.HostRecord.tenant_id == a.tenant_id).order_by(m.HostRecord.id)).all()
    return render(request, s, "host.html", a, case=case, cases=cases, records=records)


def case_url(request: Request, key: str):
    ref = request.headers.get("referer", "")
    return f"/embed/cases/{key}" if "/embed/" in ref else f"/cases/{key}"


@router.post("/ui/cases/{key}/ask")
def ui_ask(key: str, request: Request, question: str = Form(""), version: int = Form(None), s: Session = Depends(get_session)):
    a = need(request, s)
    return attempt(request, s, case_url(request, key) + "#chat", lambda: cs.ask(s, a, key, question, version))


@router.post("/ui/cases/{key}/confirm")
def ui_confirm(key: str, request: Request, model: str = Form(""), revision: str = Form(""), version: int = Form(None),
               s: Session = Depends(get_session)):
    a = need(request, s)
    return attempt(request, s, case_url(request, key), lambda: cs.confirm(s, a, key, model, revision, version),
                   f"Confirmed Model {model.upper()} rev {revision}. Saved as your observation.")


@router.post("/ui/cases/{key}/start")
def ui_start(key: str, request: Request, pathway: str = Form(""), technician: str = Form(""), version: int = Form(None),
             s: Session = Depends(get_session)):
    a = need(request, s)
    return attempt(request, s, case_url(request, key), lambda: cs.start_run(s, a, key, pathway, technician, version),
                   lambda r: f"Started {r.key} on {pathway} and assigned {technician.title()}.")


@router.post("/ui/cases/{key}/approve")
def ui_approve(key: str, request: Request, s: Session = Depends(get_session)):
    a = need(request, s)
    return attempt(request, s, case_url(request, key), lambda: ops.approve(s, a, key),
                   lambda d: f"Approved. Queued once as {d.delivery_key}.")


@router.post("/ui/deliveries/{dkey}/send")
def ui_send(dkey: str, request: Request, next: str = Form("/"), s: Session = Depends(get_session)):
    a = need(request, s)

    def msg(d):
        if d.status == "delivered":
            return f"Delivered. Receipt {d.receipt} (attempt {d.attempts})."
        return f"Host unavailable: {d.last_error}. Kept in the outbox; retry when ready."
    return attempt(request, s, next if next.startswith("/") else "/", lambda: ops.send(s, a, dkey), msg)


@router.post("/ui/host/failure")
def ui_failure(request: Request, fail: str = Form("0"), next: str = Form("/"), s: Session = Depends(get_session)):
    a = need(request, s)
    if a.role != "agent":
        return back(request, next, "bad", "403 · Only agents control the host simulation.")
    ops.set_setting(s, "host_fail_next", "1" if fail == "1" else "0")
    s.commit()
    return back(request, next if next.startswith("/") else "/", "ok",
                "The next send will fail (simulated outage)." if fail == "1" else "Host simulation back to normal.")


# ---------- technician ----------

@router.get("/runs", response_class=HTMLResponse)
def my_runs(request: Request, s: Session = Depends(get_session)):
    a = need(request, s)
    rows = s.execute(select(m.Run, m.Case).join(m.Case, m.Run.case_id == m.Case.id)
                     .where(m.Run.tenant_id == a.tenant_id).order_by(m.Run.id.desc())).all()
    if a.role == "technician":
        rows = [(r, c) for r, c in rows if c.assigned_tech_id == a.id]
    return render(request, s, "runs.html", a, rows=rows)


@router.get("/runs/{key}", response_class=HTMLResponse)
def run_page(key: str, request: Request, s: Session = Depends(get_session)):
    a = need(request, s)
    run = scoped(s, m.Run, a, key)
    node = cs.node_of(run)
    src = passage = None
    if node.citation_source:
        src = s.scalar(select(m.Source).where(m.Source.tenant_id == a.tenant_id, m.Source.key == node.citation_source))
        passage = next((p for p in src.passages if p.locator == node.citation_locator), None) if src else None
    msgs = s.scalars(select(m.Message).where(m.Message.case_id == run.case_id).order_by(m.Message.id.desc()).limit(2)).all()
    outcome = cs.latest_outcome(s, run.case)
    steps = cs.attempted_steps(s, run)
    order = [k for k in run.pathway_version.definition["nodes"] if run.pathway_version.definition["nodes"][k]["kind"] == "step"]
    infs = s.scalars(select(m.Inference).where(m.Inference.case_id == run.case_id)).all()
    return render(request, s, "run.html", a, run=run, case=run.case, node=node, src=src, passage=passage,
                  retry_key=uuid.uuid4().hex, msgs=list(reversed(msgs)), outcome=outcome, steps=steps, order=order, infs=infs)


@router.post("/ui/runs/{key}/respond")
def ui_respond(key: str, request: Request, step: str = Form(""), answer: str = Form(""), version: int = Form(None),
               retry: str = Form(""), s: Session = Depends(get_session)):
    a = need(request, s)
    return attempt(request, s, f"/runs/{key}", lambda: cs.respond(s, a, key, step, answer, version, retry),
                   lambda r: f"Saved {step} = {answer}. Run version {r['version']}, next {r['nextStepId']}.")


@router.post("/ui/runs/{key}/ask")
def ui_run_ask(key: str, request: Request, question: str = Form(""), s: Session = Depends(get_session)):
    a = need(request, s)
    run = scoped(s, m.Run, a, key)
    return attempt(request, s, f"/runs/{key}#ask", lambda: cs.ask(s, a, run.case.key, question))


@router.post("/ui/runs/{key}/outcome")
def ui_outcome(key: str, request: Request, verification: str = Form(""), action: str = Form(""), version: int = Form(None),
               helpful: str = Form(""), s: Session = Depends(get_session)):
    a = need(request, s)
    run = scoped(s, m.Run, a, key)

    def go():
        o = cs.record_outcome(s, a, run.case.key, verification, action, version)
        if helpful in ("yes", "no"):
            cs.feedback(s, a, key, run.pathway_version.definition["start"], helpful == "yes", None)
        return o
    return attempt(request, s, f"/runs/{key}", go, "Outcome recorded. The agent reviews the host update next.")


@router.post("/ui/runs/{key}/feedback")
def ui_feedback(key: str, request: Request, step: str = Form(""), helpful: str = Form("yes"), comment: str = Form(""),
                s: Session = Depends(get_session)):
    a = need(request, s)
    return attempt(request, s, f"/runs/{key}", lambda: cs.feedback(s, a, key, step, helpful == "yes", comment or None),
                   "Thanks. Feedback saved for the reviewer.")


# ---------- evidence ----------

@router.get("/evidence/{source}/{locator}", response_class=HTMLResponse)
def evidence(source: str, locator: str, request: Request, s: Session = Depends(get_session)):
    a = need(request, s)
    src = scoped(s, m.Source, a, source)
    p = next((x for x in src.passages if x.locator == locator), None)
    if not p:
        raise AppError(404, "not_found", "Not found")
    return render(request, s, "evidence.html", a, src=src, p=p)


@router.get("/history/{key}", response_class=HTMLResponse)
def history(key: str, request: Request, s: Session = Depends(get_session)):
    a = need(request, s)
    return render(request, s, "history.html", a, h=scoped(s, m.HistoricalCase, a, key))


# ---------- knowledge (author) ----------

@router.get("/knowledge", response_class=HTMLResponse)
def knowledge(request: Request, s: Session = Depends(get_session)):
    a = need(request, s)
    jobs = s.scalars(select(m.ImportJob).where(m.ImportJob.tenant_id == a.tenant_id).order_by(m.ImportJob.id.desc()).limit(5)).all()
    paths = s.scalars(select(m.Pathway).where(m.Pathway.tenant_id == a.tenant_id).order_by(m.Pathway.key)).all()
    srcs = s.scalars(select(m.Source).where(m.Source.tenant_id == a.tenant_id).order_by(m.Source.key)).all()
    tpls = s.scalars(select(m.Template).where(m.Template.tenant_id == a.tenant_id)).all()
    revs = s.scalars(select(m.ProductNode).where(m.ProductNode.tenant_id == a.tenant_id, m.ProductNode.kind == "revision")
                     .order_by(m.ProductNode.key)).all()
    edit_key = request.query_params.get("edit", "PB2")
    edit = next((p for p in paths if p.key == edit_key), None)
    draft_def = None
    errors = []
    if edit:
        d = next((v for v in edit.versions if v.status == "draft"), None) or (edit.versions[-1] if edit.versions else None)
        draft_def = json.dumps(d.definition if d else {}, indent=2)
        if d and d.status == "draft":
            errors = pw.validate(s, a.tenant_id, edit, d.definition)
    q = request.query_params.get("q", "")
    results = ops.search(s, a, q) if q else []
    sample = SAMPLE_MANIFEST.read_text() if SAMPLE_MANIFEST.exists() else '{"records": []}'
    return render(request, s, "knowledge.html", a, jobs=jobs, paths=paths, srcs=srcs, tpls=tpls, revs=revs, edit=edit,
                  draft_def=draft_def, errors=errors, sample=sample, q=q, results=results)


@router.post("/ui/imports")
def ui_import(request: Request, manifest: str = Form(""), s: Session = Depends(get_session)):
    a = need(request, s)
    try:
        data = json.loads(manifest)
    except json.JSONDecodeError as e:
        return back(request, "/knowledge#import", "bad", f"422 · That is not valid JSON ({e.msg}, line {e.lineno}).")

    def msg(res):
        job, repeated = res
        return (f"Same file as job {job.id}: nothing new imported. " if repeated else f"Import job {job.id}: ") + \
            f"{len(job.accepted)} accepted, {len(job.rejected)} rejected."
    return attempt(request, s, "/knowledge#import", lambda: ops.run_import(s, a, data), msg)


@router.post("/ui/pathways/{key}/draft")
def ui_draft(key: str, request: Request, definition: str = Form(""), s: Session = Depends(get_session)):
    a = need(request, s)
    try:
        data = json.loads(definition)
    except json.JSONDecodeError as e:
        return back(request, f"/knowledge?edit={key}#editor", "bad", f"422 · That is not valid JSON ({e.msg}, line {e.lineno}).")

    def msg(res):
        v, errors = res
        return f"Saved {key} v{v.version} draft. " + ("Valid: ready for review." if not errors else f"{len(errors)} validation errors.")
    return attempt(request, s, f"/knowledge?edit={key}#editor", lambda: pw.save_draft(s, a, key, data), msg)


@router.post("/ui/templates/{key}/apply")
def ui_apply(key: str, request: Request, node: str = Form(""), s: Session = Depends(get_session)):
    a = need(request, s)
    return attempt(request, s, "/knowledge#templates", lambda: pw.apply_template(s, a, key, node),
                   lambda r: f"Applied {key} to {node}: draft {r[0].key} v{r[1].version} with {len(r[2])} cited slots.")


# ---------- review ----------

@router.get("/review", response_class=HTMLResponse)
def review(request: Request, s: Session = Depends(get_session)):
    a = need(request, s)
    paths = s.scalars(select(m.Pathway).where(m.Pathway.tenant_id == a.tenant_id).order_by(m.Pathway.key)).all()
    srcs = s.scalars(select(m.Source).where(m.Source.tenant_id == a.tenant_id).order_by(m.Source.key)).all()
    fb = s.execute(select(m.Feedback, m.Run).join(m.Run, m.Feedback.run_id == m.Run.id)
                   .where(m.Feedback.tenant_id == a.tenant_id).order_by(m.Feedback.id.desc())).all()
    cases = s.scalars(select(m.Case).where(m.Case.tenant_id == a.tenant_id).order_by(m.Case.key)).all()
    checks = {(p.key, v.version): pw.validate(s, a.tenant_id, p, v.definition) for p in paths for v in p.versions if v.status == "draft"}
    runs = s.scalars(select(m.Run).where(m.Run.tenant_id == a.tenant_id)).all()
    return render(request, s, "review.html", a, paths=paths, srcs=srcs, fb=fb, cases=cases, checks=checks, runs=runs)


@router.post("/ui/pathways/{key}/{version}/publish")
def ui_publish(key: str, version: int, request: Request, s: Session = Depends(get_session)):
    a = need(request, s)
    return attempt(request, s, "/review", lambda: pw.publish(s, a, key, version, now()),
                   f"Published {key} v{version}. Running cases stay pinned to their version.")


@router.post("/ui/pathways/{key}/{version}/withdraw")
def ui_withdraw(key: str, version: int, request: Request, s: Session = Depends(get_session)):
    a = need(request, s)
    return attempt(request, s, "/review", lambda: pw.withdraw(s, a, key, version, now()),
                   f"Withdrew {key} v{version}. New runs are blocked and active runs are paused.")


@router.post("/ui/sources/{key}/withdraw")
def ui_withdraw_source(key: str, request: Request, s: Session = Depends(get_session)):
    a = need(request, s)
    return attempt(request, s, "/review", lambda: pw.withdraw_source(s, a, key),
                   lambda r: f"Withdrew {key}. Dependent guidance is gone; {len(r[1])} run(s) paused.")


@router.get("/review/cases/{key}", response_class=HTMLResponse)
def trace_page(key: str, request: Request, s: Session = Depends(get_session)):
    a = need(request, s)
    return render(request, s, "trace.html", a, t=ops.trace(s, a, key), case=cs.get_case(s, a, key))


# ---------- hierarchy ----------

def product_tree(s: Session, a: Actor) -> list[dict]:
    nodes = s.scalars(select(m.ProductNode).where(m.ProductNode.tenant_id == a.tenant_id).order_by(m.ProductNode.key)).all()
    srcs = s.scalars(select(m.Source).where(m.Source.tenant_id == a.tenant_id)).all()
    paths = s.scalars(select(m.Pathway).where(m.Pathway.tenant_id == a.tenant_id)).all()
    codes = s.scalars(select(m.FaultCode).where(m.FaultCode.tenant_id == a.tenant_id)).all()
    tpls = s.scalars(select(m.Template).where(m.Template.tenant_id == a.tenant_id)).all()

    def build(n):
        item = {"key": n.key, "kind": n.kind, "name": n.name, "children": [build(c) for c in nodes if c.parent_id == n.id]}
        if n.kind == "family":
            item["faultCodes"] = [{"code": c.code, "aliases": [x.alias for x in s.scalars(select(m.FaultAlias).where(m.FaultAlias.fault_code_id == c.id))]}
                                  for c in codes if c.family_id == n.id]
            item["templates"] = [t.key for t in tpls if t.family_id == n.id]
        if n.kind == "revision":
            item["sources"] = [{"key": x.key, "status": x.status} for x in srcs if (x.model, x.revision) == (n.model, n.revision)]
            item["pathways"] = [{"key": p.key, "versions": [f"v{v.version} {v.status}" for v in p.versions]}
                                for p in paths if p.product_node_id == n.id]
        return item
    return [build(n) for n in nodes if n.parent_id is None]


def asset_tree(s: Session, a: Actor) -> list[dict]:
    assets = s.scalars(select(m.Asset).where(m.Asset.tenant_id == a.tenant_id).order_by(m.Asset.key)).all()
    out = {}
    for x in assets:
        node = s.get(m.ProductNode, x.product_node_id) if x.product_node_id else None
        out.setdefault(x.site, []).append({"key": x.key, "serial": x.serial, "location": x.location,
                                           "product": f"Model {node.model} › rev {node.revision}" if node else None})
    return [{"site": k, "assets": v} for k, v in out.items()]


@router.get("/hierarchy", response_class=HTMLResponse)
def hierarchy(request: Request, s: Session = Depends(get_session)):
    a = need(request, s)
    return render(request, s, "hierarchy.html", a, products=product_tree(s, a), assets=asset_tree(s, a))
