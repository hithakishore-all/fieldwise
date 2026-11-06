"""Imports, host delivery (transactional outbox + mock receiver), search and the review trace."""
import re
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from .cases import attempted_steps, get_case, latest_outcome, latest_run
from .core import Actor, AppError, audit, checksum, conflict, forbidden, normalize_code, require_role, scoped

LOCATOR = re.compile(r"^p\d{1,4}$")
STATUSES = {"current", "superseded"}


# ---------- imports ----------

def _check_record(r) -> list[str]:
    reasons = []
    if not isinstance(r, dict):
        return ["Record is not an object."]
    for f in ("sourceId", "externalId", "title", "model", "revision", "status"):
        if not str(r.get(f, "")).strip():
            reasons.append(f"Missing {f}.")
    if r.get("status") and r["status"] not in STATUSES:
        reasons.append(f"Status must be one of {sorted(STATUSES)}.")
    ps = r.get("passages")
    if not isinstance(ps, list) or not ps:
        reasons.append("Needs at least one passage.")
        return reasons
    seen = set()
    for i, p in enumerate(ps):
        loc = (p or {}).get("locator")
        if not loc:
            reasons.append(f"Passage {i + 1} is missing a page locator.")
        elif not LOCATOR.match(str(loc)):
            reasons.append(f"Passage {i + 1} locator {loc!r} must look like p14.")
        elif loc in seen:
            reasons.append(f"Locator {loc} appears twice.")
        seen.add(loc)
        if not isinstance((p or {}).get("page"), int) or p["page"] < 1:
            reasons.append(f"Passage {i + 1} needs a positive page number.")
        if not str((p or {}).get("text", "")).strip():
            reasons.append(f"Passage {i + 1} has no text.")
    return reasons


def run_import(s: Session, actor: Actor, manifest: dict) -> tuple[m.ImportJob, bool]:
    """Import a structured manifest. Identical input returns the same job; bad records are rejected, good ones kept."""
    require_role(actor, "author")
    if not isinstance(manifest, dict) or not isinstance(manifest.get("records"), list):
        raise AppError(422, "invalid_manifest", "Manifest must be an object with a \"records\" list.")
    digest = checksum(manifest)
    existing = s.scalar(select(m.ImportJob).where(m.ImportJob.tenant_id == actor.tenant_id, m.ImportJob.checksum == digest))
    if existing:
        audit(s, actor, "import.repeated", job=existing.id, checksum=digest[:12])
        return existing, True
    accepted, rejected = [], []
    for idx, r in enumerate(manifest["records"]):
        label = (r or {}).get("sourceId") or (r or {}).get("externalId") or f"record {idx + 1}"
        reasons = _check_record(r)
        if reasons:
            rejected.append({"record": label, "reasons": reasons})
            continue
        rsum = checksum(r)
        src = s.scalar(select(m.Source).where(m.Source.tenant_id == actor.tenant_id, m.Source.external_id == r["externalId"]))
        if src:
            if src.checksum == rsum:
                accepted.append({"record": label, "result": "unchanged", "passages": len(src.passages)})
            else:
                rejected.append({"record": label, "reasons": ["Already imported with different content; import a new revision under a new sourceId."]})
            continue
        if s.scalar(select(m.Source).where(m.Source.tenant_id == actor.tenant_id, m.Source.key == r["sourceId"])):
            rejected.append({"record": label, "reasons": [f"sourceId {r['sourceId']} is already used by another external ID."]})
            continue
        src = m.Source(tenant_id=actor.tenant_id, key=r["sourceId"], external_id=r["externalId"], title=r["title"],
                       model=str(r["model"]).upper(), revision=str(r["revision"]), status=r["status"], checksum=rsum)
        s.add(src)
        s.flush()
        for p in r["passages"]:
            s.add(m.Passage(tenant_id=actor.tenant_id, source_id=src.id, locator=p["locator"], page=p["page"], text=p["text"],
                            fault_codes=[normalize_code(c) for c in p.get("faultCodes", [])], topic=p.get("topic")))
        accepted.append({"record": label, "result": "created", "passages": len(r["passages"])})
    job = m.ImportJob(tenant_id=actor.tenant_id, uploader_id=actor.id, checksum=digest, status="completed",
                      accepted=accepted, rejected=rejected)
    s.add(job)
    s.flush()
    audit(s, actor, "import.completed", job=job.id, accepted=len(accepted), rejected=len(rejected))
    return job, False


def job_view(job: m.ImportJob, repeated=False) -> dict:
    return {"jobId": job.id, "status": job.status, "checksum": job.checksum, "repeated": repeated,
            "acceptedCount": len(job.accepted), "rejectedCount": len(job.rejected),
            "accepted": job.accepted, "rejected": job.rejected}


# ---------- host update + outbox ----------

def host_summary(s: Session, case: m.Case, outcome: m.Outcome) -> dict:
    run = s.get(m.Run, outcome.run_id)
    v = run.pathway_version
    return {"case": case.key, "asset": case.asset.key, "applicability": f"Model {case.model} rev {case.revision} (confirmed)",
            "callerWords": case.intake_text, "procedure": f"{v.pathway.key} v{v.version}", "run": run.key,
            "attemptedSteps": [{"step": a["step"], "answer": a["answer"], "citation": a["citation"]} for a in outcome.attempted_steps],
            "outcome": outcome.kind, "reason": outcome.reason, "actionTaken": outcome.action_taken,
            "verification": outcome.verification, "openQuestion": outcome.open_question}


def preview(s: Session, actor: Actor, case_key: str) -> dict:
    case = get_case(s, actor, case_key)
    o = latest_outcome(s, case)
    if not o:
        raise conflict("Nothing to send yet: the case has no recorded outcome.")
    d = s.scalar(select(m.Delivery).where(m.Delivery.outcome_id == o.id))
    return {"summary": host_summary(s, case, o), "delivery": delivery_view(d) if d else None}


def approve(s: Session, actor: Actor, case_key: str) -> m.Delivery:
    """Agent approval writes exactly one outbox row in the same transaction as its audit event."""
    require_role(actor, "agent")
    case = get_case(s, actor, case_key)
    if case.owner_id != actor.id:
        raise forbidden("Only the case owner approves the host update.")
    o = latest_outcome(s, case)
    if not o:
        raise conflict("Nothing to approve: the case has no recorded outcome.")
    d = s.scalar(select(m.Delivery).where(m.Delivery.outcome_id == o.id))
    if d:
        return d
    d = m.Delivery(tenant_id=actor.tenant_id, case_id=case.id, outcome_id=o.id, delivery_key=f"DLV-{case.key}-{o.id}",
                   payload=host_summary(s, case, o), status="pending", approved_by=actor.id)
    s.add(d)
    audit(s, actor, "host_update.approved", case=case, delivery=d.delivery_key)
    return d


def _receive(s: Session, tenant_id: str, d: m.Delivery) -> str:
    """The mock host. Deduplicates by delivery key and returns the same receipt for repeats."""
    rec = s.scalar(select(m.HostRecord).where(m.HostRecord.delivery_key == d.delivery_key))
    if rec:
        return rec.receipt
    rec = m.HostRecord(tenant_id=tenant_id, delivery_key=d.delivery_key, case_key=d.payload["case"],
                       receipt=f"RCPT-{uuid.uuid4().hex[:8].upper()}", payload=d.payload)
    s.add(rec)
    s.flush()
    return rec.receipt


def get_setting(s: Session, key: str, default="0") -> str:
    row = s.get(m.Setting, key)
    return row.value if row else default


def set_setting(s: Session, key: str, value: str):
    row = s.get(m.Setting, key)
    if row:
        row.value = value
    else:
        s.add(m.Setting(key=key, value=value))


def send(s: Session, actor: Actor, delivery_key: str) -> m.Delivery:
    require_role(actor, "agent")
    d = s.scalar(select(m.Delivery).where(m.Delivery.tenant_id == actor.tenant_id, m.Delivery.delivery_key == delivery_key))
    if not d:
        raise AppError(404, "not_found", "Not found")
    d.attempts += 1
    case = s.get(m.Case, d.case_id)
    if d.status == "delivered":
        audit(s, actor, "delivery.retry_already_delivered", case=case, delivery=d.delivery_key, receipt=d.receipt)
        return d
    if get_setting(s, "host_fail_next") == "1":
        set_setting(s, "host_fail_next", "0")
        d.status, d.last_error = "failed", "Simulated host outage"
        audit(s, actor, "delivery.failed", case=case, delivery=d.delivery_key, error=d.last_error)
        return d
    d.receipt = _receive(s, actor.tenant_id, d)
    d.status, d.last_error = "delivered", None
    audit(s, actor, "delivery.delivered", case=case, delivery=d.delivery_key, receipt=d.receipt)
    return d


def delivery_view(d: m.Delivery) -> dict:
    return {"deliveryKey": d.delivery_key, "status": d.status, "attempts": d.attempts, "receipt": d.receipt,
            "lastError": d.last_error}


# ---------- search + trace ----------

def search(s: Session, actor: Actor, q: str) -> list[dict]:
    q = (q or "").strip()
    if not q:
        return []
    rows = s.execute(select(m.Passage, m.Source).join(m.Source, m.Passage.source_id == m.Source.id)
                     .where(m.Passage.tenant_id == actor.tenant_id, m.Source.status == "current")).all()
    out = []
    for p, src in rows:
        hay = f"{src.title} {p.text} {' '.join(p.fault_codes)}".lower()
        if q.lower() in hay or normalize_code(q) in p.fault_codes:
            out.append({"sourceId": src.key, "locator": p.locator, "model": src.model, "revision": src.revision,
                        "text": p.text, "url": f"/evidence/{src.key}/{p.locator}"})
    return out


def trace(s: Session, actor: Actor, case_key: str) -> dict:
    if actor.role not in ("reviewer", "agent", "author"):
        raise forbidden()
    case = get_case(s, actor, case_key)
    events = s.scalars(select(m.AuditEvent).where(m.AuditEvent.case_id == case.id).order_by(m.AuditEvent.id)).all()
    runs = s.scalars(select(m.Run).where(m.Run.case_id == case.id).order_by(m.Run.id)).all()
    fb = s.scalars(select(m.Feedback).where(m.Feedback.run_id.in_([r.id for r in runs] or [0])).order_by(m.Feedback.id)).all()
    outs = s.scalars(select(m.Outcome).where(m.Outcome.case_id == case.id).order_by(m.Outcome.id)).all()
    return {"case": case.key,
            "events": [{"seq": e.id, "at": e.created_at.isoformat(), "actor": e.actor_id, "action": e.action, "detail": e.detail}
                       for e in events],
            "runs": [{"runId": r.key, "pathway": f"{r.pathway_version.pathway.key} v{r.pathway_version.version}",
                      "status": r.status, "attemptedSteps": attempted_steps(s, r)} for r in runs],
            "feedback": [{"step": f.step_id, "helpful": f.helpful, "comment": f.comment, "by": f.actor_id} for f in fb],
            "outcomes": [{"kind": o.kind, "terminal": o.terminal, "reason": o.reason, "verification": o.verification,
                          "openQuestion": o.open_question, "attemptedSteps": o.attempted_steps} for o in outs]}
