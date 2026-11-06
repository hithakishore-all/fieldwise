"""JSON API. Identity always comes from the server-side session, never from the request body."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models as m
from .db import get_session
from .services import cases as cs
from .services import ops
from .services import pathways as pw
from .services.core import Actor, AppError, load_actor, require_role, scoped

router = APIRouter()


def actor_dep(request: Request, s: Session = Depends(get_session)) -> Actor:
    return load_actor(s, request.session.get("user_id"))


async def body(request: Request) -> dict:
    try:
        data = await request.json()
    except Exception:
        raise AppError(422, "invalid_json", "Send a JSON object.")
    if not isinstance(data, dict):
        raise AppError(422, "invalid_json", "Send a JSON object.")
    return data


def commit(s: Session):
    s.commit()


def now():
    return datetime.now(timezone.utc)


@router.get("/api/health")
def health(s: Session = Depends(get_session)):
    s.execute(select(1))
    return {"ok": True, "database": s.bind.dialect.name}


@router.get("/api/me")
def me(actor: Actor = Depends(actor_dep)):
    return actor.__dict__


# ---------- cases ----------

def case_view(s: Session, case: m.Case) -> dict:
    run = cs.latest_run(s, case)
    return {"id": case.key, "title": case.title, "owner": case.owner_id, "assignedTechnician": case.assigned_tech_id,
            "status": case.status, "version": case.version, "callerWords": case.intake_text,
            "asset": {"id": case.asset.key, "serial": case.asset.serial, "site": case.asset.site},
            "applicability": {"model": case.model, "revision": case.revision},
            "run": {"runId": run.key, "status": run.status, "currentStep": run.current_node, "version": run.version,
                    "pathway": run.pathway_version.pathway.key, "pathwayVersion": run.pathway_version.version} if run else None}


@router.get("/api/cases")
def list_cases(actor: Actor = Depends(actor_dep), s: Session = Depends(get_session)):
    rows = s.scalars(select(m.Case).where(m.Case.tenant_id == actor.tenant_id).order_by(m.Case.key)).all()
    return [case_view(s, c) for c in rows]


@router.get("/api/cases/{key}")
def read_case(key: str, actor: Actor = Depends(actor_dep), s: Session = Depends(get_session)):
    return case_view(s, cs.get_case(s, actor, key))


@router.post("/cases/{key}/questions")
async def questions(key: str, request: Request, actor: Actor = Depends(actor_dep), s: Session = Depends(get_session)):
    b = await body(request)
    result = cs.ask(s, actor, key, b.get("question", ""), b.get("expectedVersion"))
    commit(s)
    return result


@router.post("/cases/{key}/confirmations")
async def confirmations(key: str, request: Request, actor: Actor = Depends(actor_dep), s: Session = Depends(get_session)):
    b = await body(request)
    case = cs.confirm(s, actor, key, b.get("model"), b.get("revision"), b.get("expectedVersion"))
    commit(s)
    return case_view(s, case)


@router.post("/cases/{key}/assignment")
async def assignment(key: str, request: Request, actor: Actor = Depends(actor_dep), s: Session = Depends(get_session)):
    b = await body(request)
    case = cs.assign(s, actor, key, b.get("technicianId"), b.get("expectedVersion"))
    commit(s)
    return case_view(s, case)


@router.post("/cases/{key}/runs")
async def start_run(key: str, request: Request, actor: Actor = Depends(actor_dep), s: Session = Depends(get_session)):
    b = await body(request)
    run = cs.start_run(s, actor, key, b.get("pathwayId"), b.get("technicianId"), b.get("expectedVersion"))
    commit(s)
    return run_view(s, run)


@router.post("/cases/{key}/outcomes")
async def outcomes(key: str, request: Request, actor: Actor = Depends(actor_dep), s: Session = Depends(get_session)):
    b = await body(request)
    o = cs.record_outcome(s, actor, key, b.get("verification"), b.get("actionTaken"), b.get("expectedVersion"))
    commit(s)
    return {"kind": o.kind, "terminal": o.terminal, "verification": o.verification, "attemptedSteps": o.attempted_steps}


@router.get("/cases/{key}/host-update")
def host_update(key: str, actor: Actor = Depends(actor_dep), s: Session = Depends(get_session)):
    return ops.preview(s, actor, key)


@router.post("/cases/{key}/host-update/approve")
def approve(key: str, actor: Actor = Depends(actor_dep), s: Session = Depends(get_session)):
    d = ops.approve(s, actor, key)
    commit(s)
    return ops.delivery_view(d)


@router.post("/deliveries/{key}/send")
def send(key: str, actor: Actor = Depends(actor_dep), s: Session = Depends(get_session)):
    d = ops.send(s, actor, key)
    commit(s)
    return ops.delivery_view(d)


@router.post("/host/failure")
async def host_failure(request: Request, actor: Actor = Depends(actor_dep), s: Session = Depends(get_session)):
    require_role(actor, "agent")
    b = await body(request)
    ops.set_setting(s, "host_fail_next", "1" if b.get("failNext") else "0")
    commit(s)
    return {"failNext": bool(b.get("failNext"))}


@router.get("/api/host/records")
def host_records(actor: Actor = Depends(actor_dep), s: Session = Depends(get_session)):
    rows = s.scalars(select(m.HostRecord).where(m.HostRecord.tenant_id == actor.tenant_id).order_by(m.HostRecord.id)).all()
    return [{"deliveryKey": r.delivery_key, "case": r.case_key, "receipt": r.receipt, "payload": r.payload} for r in rows]


@router.get("/api/cases/{key}/trace")
def case_trace(key: str, actor: Actor = Depends(actor_dep), s: Session = Depends(get_session)):
    return ops.trace(s, actor, key)


# ---------- runs ----------

def run_view(s: Session, run: m.Run) -> dict:
    n = cs.node_of(run)
    return {"runId": run.key, "case": run.case.key, "pathway": run.pathway_version.pathway.key,
            "version": run.version, "pathwayVersion": run.pathway_version.version, "status": run.status,
            "pauseReason": run.pause_reason, "currentStepId": run.current_node,
            "currentStep": {"prompt": n.prompt, "kind": n.kind, "allowedAnswers": list(n.edges),
                            "citation": {"sourceId": n.citation_source, "locator": n.citation_locator} if n.citation_source else None}}


@router.get("/api/runs/{key}")
def read_run(key: str, actor: Actor = Depends(actor_dep), s: Session = Depends(get_session)):
    return run_view(s, scoped(s, m.Run, actor, key))


@router.post("/runs/{key}/responses")
async def responses(key: str, request: Request, actor: Actor = Depends(actor_dep), s: Session = Depends(get_session)):
    b = await body(request)
    result = cs.respond(s, actor, key, b.get("stepId"), b.get("answer"), b.get("expectedVersion"), b.get("retryKey"))
    commit(s)
    return result


@router.post("/runs/{key}/feedback")
async def run_feedback(key: str, request: Request, actor: Actor = Depends(actor_dep), s: Session = Depends(get_session)):
    b = await body(request)
    cs.feedback(s, actor, key, b.get("stepId"), b.get("helpful"), b.get("comment"))
    commit(s)
    return {"ok": True}


# ---------- knowledge ----------

@router.post("/imports")
async def imports(request: Request, actor: Actor = Depends(actor_dep), s: Session = Depends(get_session)):
    b = await body(request)
    job, repeated = ops.run_import(s, actor, b)
    commit(s)
    return ops.job_view(job, repeated)


@router.get("/imports/{job_id}")
def read_import(job_id: int, actor: Actor = Depends(actor_dep), s: Session = Depends(get_session)):
    job = s.scalar(select(m.ImportJob).where(m.ImportJob.id == job_id, m.ImportJob.tenant_id == actor.tenant_id))
    if not job:
        raise AppError(404, "not_found", "Not found")
    return ops.job_view(job)


@router.get("/api/sources")
def sources(actor: Actor = Depends(actor_dep), s: Session = Depends(get_session)):
    rows = s.scalars(select(m.Source).where(m.Source.tenant_id == actor.tenant_id).order_by(m.Source.key)).all()
    return [{"sourceId": x.key, "model": x.model, "revision": x.revision, "status": x.status,
             "passages": [p.locator for p in x.passages]} for x in rows]


@router.get("/api/evidence/{source}/{locator}")
def evidence(source: str, locator: str, actor: Actor = Depends(actor_dep), s: Session = Depends(get_session)):
    src = scoped(s, m.Source, actor, source)
    p = next((x for x in src.passages if x.locator == locator), None)
    if not p:
        raise AppError(404, "not_found", "Not found")
    return cs.citation(src, p) | {"status": src.status}


@router.get("/search")
def search(q: str = "", actor: Actor = Depends(actor_dep), s: Session = Depends(get_session)):
    return {"query": q, "results": ops.search(s, actor, q)}


@router.get("/api/pathways")
def pathways(actor: Actor = Depends(actor_dep), s: Session = Depends(get_session)):
    rows = s.scalars(select(m.Pathway).where(m.Pathway.tenant_id == actor.tenant_id).order_by(m.Pathway.key)).all()
    return [{"pathwayId": p.key, "model": p.model, "revision": p.revision,
             "versions": [{"version": v.version, "status": v.status, "author": v.author_id, "reviewer": v.reviewer_id}
                          for v in p.versions]} for p in rows]


@router.post("/pathways/{key}/drafts")
async def drafts(key: str, request: Request, actor: Actor = Depends(actor_dep), s: Session = Depends(get_session)):
    b = await body(request)
    v, errors = pw.save_draft(s, actor, key, b.get("definition"))
    commit(s)
    return {"pathwayId": key, "version": v.version, "status": v.status, "valid": not errors, "errors": errors}


@router.post("/pathways/{key}/versions/{version}/publish")
def publish(key: str, version: int, actor: Actor = Depends(actor_dep), s: Session = Depends(get_session)):
    v = pw.publish(s, actor, key, version, now())
    commit(s)
    return {"pathwayId": key, "version": v.version, "status": v.status}


@router.post("/pathways/{key}/versions/{version}/withdraw")
def withdraw(key: str, version: int, actor: Actor = Depends(actor_dep), s: Session = Depends(get_session)):
    v = pw.withdraw(s, actor, key, version, now())
    commit(s)
    return {"pathwayId": key, "version": v.version, "status": v.status}


@router.post("/sources/{key}/withdraw")
def withdraw_source(key: str, actor: Actor = Depends(actor_dep), s: Session = Depends(get_session)):
    src, paused = pw.withdraw_source(s, actor, key)
    commit(s)
    return {"sourceId": src.key, "status": src.status, "pausedRuns": [r.key for r in paused]}


@router.post("/templates/{key}/apply")
async def apply_template(key: str, request: Request, actor: Actor = Depends(actor_dep), s: Session = Depends(get_session)):
    b = await body(request)
    p, draft, bound, errors = pw.apply_template(s, actor, key, b.get("revisionNode"))
    commit(s)
    return {"pathwayId": p.key, "version": draft.version, "status": draft.status, "bound": bound, "valid": not errors,
            "errors": errors}


@router.get("/api/hierarchy")
def hierarchy(actor: Actor = Depends(actor_dep), s: Session = Depends(get_session)):
    from .ui import product_tree, asset_tree
    return {"products": product_tree(s, actor), "assets": asset_tree(s, actor)}
