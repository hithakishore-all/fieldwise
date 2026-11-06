"""Case workflow: assistant questions, applicability, assignment, runs, step responses and outcomes."""
import re
import uuid

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .. import models as m
from . import pathways as pw
from .core import (Actor, AppError, audit, check_version, checksum, conflict, forbidden, normalize_code,
                   not_found, require_role, scoped)

CODE_PATTERN = re.compile(r"\b[A-Z]{1,3}[\s\-_]?\d{1,4}\b", re.I)


# ---------- reads ----------

def get_case(s: Session, actor: Actor, key: str) -> m.Case:
    return scoped(s, m.Case, actor, key)


def detect_codes(s: Session, tenant_id: str, text: str) -> set[str]:
    found = set()
    for token in CODE_PATTERN.findall(text or ""):
        alias = s.scalars(select(m.FaultAlias).where(m.FaultAlias.tenant_id == tenant_id,
                                                     m.FaultAlias.normalized == normalize_code(token))).first()
        if alias:
            found.add(s.get(m.FaultCode, alias.fault_code_id).code)
    return found


def citation(src: m.Source, p: m.Passage) -> dict:
    return {"sourceId": src.key, "title": src.title, "model": src.model, "revision": src.revision,
            "locator": p.locator, "page": p.page, "text": p.text, "url": f"/evidence/{src.key}/{p.locator}"}


def history_summary(s: Session, tenant_id: str, model: str, revision: str, codes: set[str]) -> dict:
    rows = s.scalars(select(m.HistoricalCase).where(
        m.HistoricalCase.tenant_id == tenant_id, m.HistoricalCase.model == model,
        m.HistoricalCase.revision == revision, m.HistoricalCase.fault_code.in_(codes or {"_"}))
        .order_by(m.HistoricalCase.key)).all()
    verified = sum(1 for h in rows if h.outcome == "verified_recovery")
    return {"verified": verified, "total": len(rows),
            "label": f"{verified} verified recovery in {len(rows)} matching case{'s' if len(rows) != 1 else ''}",
            "cases": [{"id": h.key, "outcome": h.outcome, "url": f"/history/{h.key}"} for h in rows]}


def active_run(s: Session, case: m.Case) -> m.Run | None:
    return s.scalar(select(m.Run).where(m.Run.case_id == case.id,
                                        m.Run.status.in_(["active", "awaiting_outcome", "paused"]))
                    .order_by(m.Run.id.desc()))


def latest_run(s: Session, case: m.Case) -> m.Run | None:
    return s.scalar(select(m.Run).where(m.Run.case_id == case.id).order_by(m.Run.id.desc()))


def node_of(run: m.Run, key: str | None = None) -> m.PathwayNode | None:
    key = key or run.current_node
    return next((n for n in run.pathway_version.nodes if n.node_key == key), None)


# ---------- assistant ----------

def ask(s: Session, actor: Actor, case_key: str, question: str, expected_version=None) -> dict:
    """Scoped retrieval with response templates. Never changes a run or chooses a branch."""
    case = get_case(s, actor, case_key)
    if actor.role not in ("agent", "technician", "reviewer"):
        raise forbidden()
    if expected_version is not None and int(expected_version) != case.version:
        raise conflict("The case changed since you loaded it. Reload to ask with current facts.",
                       currentVersion=case.version)
    question = (question or "").strip()
    if not question:
        raise AppError(422, "empty_question", "Type a question.")
    run = active_run(s, case)
    if run and actor.role == "technician" and run.status == "active":
        result = _explain_step(s, run)
    else:
        result = _answer(s, actor, case, question)
    s.add(m.Message(tenant_id=actor.tenant_id, case_id=case.id, author_id=actor.id, role="user", text=question))
    s.add(m.Message(tenant_id=actor.tenant_id, case_id=case.id, role="assistant", text=result["text"], payload=result))
    audit(s, actor, "assistant.answered", case=case, question=question, kind=result["kind"],
          citations=[f"{c['sourceId']} {c['locator']}" for c in result["citations"]])
    return result


def _explain_step(s: Session, run: m.Run) -> dict:
    n = node_of(run)
    allowed = ", ".join(n.edges.keys())
    cits = []
    if n.citation_source:
        src = s.scalar(select(m.Source).where(m.Source.tenant_id == run.tenant_id, m.Source.key == n.citation_source))
        p = next((x for x in src.passages if x.locator == n.citation_locator), None) if src else None
        if src and p and src.status == "current":
            cits.append(citation(src, p))
    text = (f"Step {n.node_key}: {n.prompt} Allowed answers: {allowed}. "
            "I can explain the step, but only a submitted answer moves the procedure.")
    return {"kind": "answer", "text": text, "missingFields": [], "citations": cits,
            "eligiblePathways": [], "history": None, "explainsStep": n.node_key}


def _answer(s: Session, actor: Actor, case: m.Case, question: str) -> dict:
    codes = detect_codes(s, actor.tenant_id, question)
    about_case = bool(codes) or bool(re.search(r"\b(doors?|reopen\w*|fault|code|indicator|self.?test)\b", question, re.I))
    if about_case and not codes:
        codes = detect_codes(s, actor.tenant_id, case.intake_text)
    if not about_case:
        return _resp("escalate", "Insufficient evidence. No current, applicable passage answers that question.")
    missing = [f for f in ("model", "revision") if not getattr(case, f)]
    if missing:
        n_models = 0
        if codes:
            n_models = len({(src.model) for src in s.scalars(select(m.Source).where(m.Source.tenant_id == actor.tenant_id)).all()
                            for p in src.passages if set(p.fault_codes) & codes})
        lead = f"{'/'.join(sorted(codes))} appears in manuals for {n_models} models. " if n_models > 1 else ""
        return _resp("clarify", f"{lead}Confirm the {' and '.join(missing)} before I give any model-specific steps.",
                     missing=missing)
    srcs = s.scalars(select(m.Source).where(m.Source.tenant_id == actor.tenant_id, m.Source.model == case.model,
                                            m.Source.revision == case.revision)).all()
    current = [(src, p) for src in srcs if src.status == "current" for p in src.passages if set(p.fault_codes) & codes]
    stale = [(src, p) for src in srcs if src.status != "current" for p in src.passages if set(p.fault_codes) & codes]
    history = history_summary(s, actor.tenant_id, case.model, case.revision, codes)
    if not current:
        if stale:
            names = ", ".join(f"{src.key} rev {src.revision} {p.locator} ({src.status})" for src, p in stale)
            return _resp("escalate", f"Guidance is unavailable: the only matching material is {names}, which can't be used. "
                         "Escalate with the caller's words, or ask a reviewer to publish current guidance.", history=history)
        return _resp("escalate", f"Insufficient evidence for Model {case.model} rev {case.revision}. Escalate with the caller's words.",
                     history=history)
    current.sort(key=lambda sp: sp[1].page)
    elig = pw.eligible(s, actor.tenant_id, case.model, case.revision, codes)
    first = current[0]
    text = f"For Model {case.model} rev {case.revision}, start here: {first[1].text}"
    if elig:
        text += f" Approved procedure: {elig[0][0].key} v{elig[0][1].version}."
    else:
        text += " No approved procedure is available for this model yet, so escalate before any repair."
    if history["total"]:
        text += f" History: {history['label']}."
    return {"kind": "answer", "text": text, "missingFields": [],
            "citations": [citation(src, p) for src, p in current],
            "eligiblePathways": [{"pathwayId": p.key, "version": v.version, "name": p.name} for p, v in elig],
            "history": history}


def _resp(kind, text, missing=None, history=None):
    return {"kind": kind, "text": text, "missingFields": missing or [], "citations": [],
            "eligiblePathways": [], "history": history}


# ---------- applicability, assignment ----------

def confirm(s: Session, actor: Actor, case_key: str, model: str, revision: str, expected_version):
    require_role(actor, "agent")
    case = get_case(s, actor, case_key)
    if case.owner_id != actor.id:
        raise forbidden("Only the case owner can confirm applicability.")
    check_version(case.version, expected_version, "case")
    model, revision = (model or "").strip().upper(), (revision or "").strip()
    if not model or not revision:
        raise AppError(422, "missing_fields", "Give both a model and a revision.")
    correcting = case.model is not None and (case.model, case.revision) != (model, revision)
    case.model, case.revision = model, revision
    case.version += 1
    for field, value in (("model", model), ("revision", revision)):
        s.add(m.Observation(tenant_id=actor.tenant_id, key=f"O-{field}-{case.version}", case_id=case.id,
                            field=field, value=value, status="observed", origin="agent_confirmation",
                            supplied_by=actor.id, original_text=f"Confirmed by {actor.name}"))
    node = s.scalar(select(m.ProductNode).where(m.ProductNode.tenant_id == actor.tenant_id, m.ProductNode.kind == "revision",
                                                m.ProductNode.model == model, m.ProductNode.revision == revision))
    case.asset.product_node_id = node.id if node else None
    audit(s, actor, "case.applicability_confirmed", case=case, model=model, revision=revision, correction=correcting)
    if correcting:
        run = active_run(s, case)
        if run and run.status in ("active", "awaiting_outcome"):
            run.status, run.pause_reason = "paused", "Applicability was corrected; start a fresh applicable run."
            run.version += 1
            audit(s, actor, "run.paused", case=case, run=run.key, reason=run.pause_reason)
    return case


def assign(s: Session, actor: Actor, case_key: str, technician_id: str, expected_version):
    require_role(actor, "agent")
    case = get_case(s, actor, case_key)
    if case.owner_id != actor.id:
        raise forbidden("Only the case owner can assign a technician.")
    check_version(case.version, expected_version, "case")
    tech = s.execute(select(m.Membership).where(m.Membership.user_id == technician_id,
                                                m.Membership.tenant_id == actor.tenant_id)).scalar()
    if not tech or tech.role != "technician":
        raise AppError(422, "invalid_technician", "Assign a technician from your organization.")
    case.assigned_tech_id = technician_id
    case.version += 1
    audit(s, actor, "case.assigned", case=case, technician=technician_id)
    return case


def start_run(s: Session, actor: Actor, case_key: str, pathway_key: str, technician_id: str | None, expected_version):
    """Validate applicability and publication, then pin the latest usable version. Optionally assigns in one step."""
    require_role(actor, "agent")
    case = get_case(s, actor, case_key)
    if case.owner_id != actor.id:
        raise forbidden("Only the case owner can start a procedure.")
    check_version(case.version, expected_version, "case")
    technician_id = technician_id or case.assigned_tech_id
    if not technician_id:
        raise AppError(422, "missing_technician", "Assign a technician before starting the procedure.")
    if not (case.model and case.revision):
        raise conflict("Confirm model and revision before starting a procedure.")
    current = active_run(s, case)
    if current and current.status in ("active", "awaiting_outcome"):
        raise conflict(f"Run {current.key} is already in progress.")
    p = scoped(s, m.Pathway, actor, pathway_key)
    if (p.model, p.revision) != (case.model, case.revision):
        raise conflict(f"{p.key} applies to Model {p.model} rev {p.revision}, not this asset.")
    v = pw.latest_usable(s, p)
    if not v:
        raise conflict(f"{p.key} has no published version with current evidence.")
    tech = s.execute(select(m.Membership).where(m.Membership.user_id == technician_id,
                                                m.Membership.tenant_id == actor.tenant_id)).scalar()
    if not tech or tech.role != "technician":
        raise AppError(422, "invalid_technician", "Assign a technician from your organization.")
    reassigned = case.assigned_tech_id != technician_id
    case.assigned_tech_id = technician_id
    case.version += 1
    run = m.Run(tenant_id=actor.tenant_id, key=f"RUN-{uuid.uuid4().hex[:6].upper()}", case_id=case.id,
                pathway_version_id=v.id, status="active", current_node=v.definition["start"], version=1,
                started_by=actor.id)
    s.add(run)
    s.flush()
    if reassigned:
        audit(s, actor, "case.assigned", case=case, technician=technician_id)
    audit(s, actor, "run.started", case=case, run=run.key, pathway=p.key, version=v.version)
    return run


# ---------- step responses ----------

def respond(s: Session, actor: Actor, run_key: str, step_id: str, answer: str, expected_version, retry_key: str) -> dict:
    run = scoped(s, m.Run, actor, run_key)
    case = run.case
    if actor.role != "technician" or case.assigned_tech_id != actor.id:
        audit(s, actor, "run.response_blocked", case=case, run=run.key, step=step_id, reason="not the assigned technician")
        s.commit()
        raise forbidden("Only the assigned technician can submit a step result.")
    if not retry_key:
        raise AppError(422, "missing_retry_key", "retryKey is required.")
    req_hash = checksum({"stepId": step_id, "answer": answer, "expectedVersion": expected_version})
    prior = s.scalar(select(m.Response).where(m.Response.run_id == run.id, m.Response.retry_key == retry_key))
    if prior:
        if prior.request_hash == req_hash and prior.actor_id == actor.id:
            return prior.result  # identical retry: original response, nothing new recorded
        raise conflict("This retry key was already used with different input.")
    v = run.pathway_version
    if run.status == "paused" or not pw.version_usable(s, v):
        if run.status != "paused":
            run.status, run.pause_reason = "paused", "The procedure or its evidence is no longer approved."
            run.version += 1
            audit(s, actor, "run.paused", case=case, run=run.key, reason=run.pause_reason)
            s.commit()
        raise conflict(f"Run is paused: {run.pause_reason}", runStatus="paused")
    if run.status != "active":
        raise conflict(f"Run is {run.status}; no step is waiting for an answer.")
    check_version(run.version, expected_version, "run")
    if step_id != run.current_node:
        raise conflict(f"Step {step_id} is not the current step ({run.current_node}).")
    node = node_of(run)
    if answer not in node.edges:
        raise AppError(422, "invalid_answer", f"{answer!r} is not an allowed answer for {step_id}.",
                       allowed=list(node.edges))
    nxt = node.edges[answer]
    # Optimistic, atomic version bump: only one writer at this expected version can win.
    res = s.execute(update(m.Run).where(m.Run.id == run.id, m.Run.version == int(expected_version))
                    .values(version=m.Run.version + 1).execution_options(synchronize_session=False))
    if res.rowcount != 1:
        raise conflict("Another submission changed this run first. Reload.")
    s.refresh(run)
    target = node_of(run, nxt)
    status = "active"
    if target.kind == "terminal":
        status = "awaiting_outcome" if target.outcome == "resolved" else "escalated"
    run.current_node, run.status = nxt, status
    result = {"runId": run.key, "version": run.version, "status": status, "nextStepId": nxt}
    s.add(m.Response(tenant_id=actor.tenant_id, run_id=run.id, step_id=step_id, answer=answer, next_node=nxt,
                     actor_id=actor.id, retry_key=retry_key, request_hash=req_hash, result=result))
    audit(s, actor, "run.step_answered", case=case, run=run.key, step=step_id, answer=answer, next=nxt,
          version=run.version, citation=f"{node.citation_source} {node.citation_locator}" if node.citation_source else None)
    for inf in s.scalars(select(m.Inference).where(m.Inference.case_id == case.id, m.Inference.pending_check == step_id)):
        inf.status = "checked"
    if status == "escalated":
        _record_outcome(s, actor, case, run, target, kind="escalated")
    s.flush()
    return result


def attempted_steps(s: Session, run: m.Run) -> list[dict]:
    rows = s.scalars(select(m.Response).where(m.Response.run_id == run.id).order_by(m.Response.id)).all()
    out = []
    for r in rows:
        n = node_of(run, r.step_id)
        out.append({"step": r.step_id, "prompt": n.prompt, "answer": r.answer, "next": r.next_node,
                    "citation": f"{n.citation_source} {n.citation_locator}" if n.citation_source else None,
                    "by": r.actor_id, "at": r.created_at.isoformat()})
    return out


def _record_outcome(s, actor, case, run, terminal, kind, action=None, verification=None):
    o = m.Outcome(tenant_id=actor.tenant_id, case_id=case.id, run_id=run.id, kind=kind, terminal=terminal.node_key,
                  reason=terminal.prompt, action_taken=action, verification=verification,
                  open_question=terminal.open_question if kind == "escalated" else None,
                  attempted_steps=attempted_steps(s, run), actor_id=actor.id)
    s.add(o)
    case.status = "resolved" if kind == "resolved" else "escalated"
    case.version += 1
    audit(s, actor, f"case.{kind}", case=case, run=run.key, terminal=terminal.node_key,
          open_question=o.open_question)
    return o


def record_outcome(s: Session, actor: Actor, case_key: str, verification: str, action_taken: str, expected_version):
    case = get_case(s, actor, case_key)
    if actor.role != "technician" or case.assigned_tech_id != actor.id:
        raise forbidden("Only the assigned technician records the verified outcome.")
    run = latest_run(s, case)
    if not run or run.status != "awaiting_outcome":
        audit(s, actor, "case.closure_refused", case=case, reason="no verified outcome")
        s.commit()
        raise conflict("This case has no verified outcome yet. Finish the approved procedure first.")
    check_version(run.version, expected_version, "run")
    if not (verification or "").strip():
        raise AppError(422, "missing_verification", "Add a verification note to close as resolved.")
    terminal = node_of(run)
    run.status = "resolved"
    run.version += 1
    return _record_outcome(s, actor, case, run, terminal, "resolved", action=action_taken, verification=verification)


def feedback(s: Session, actor: Actor, run_key: str, step_id: str, helpful: bool, comment: str | None):
    run = scoped(s, m.Run, actor, run_key)
    if actor.role != "technician" or run.case.assigned_tech_id != actor.id:
        raise forbidden("Only the assigned technician can leave step feedback.")
    if not node_of(run, step_id):
        raise AppError(422, "unknown_step", f"{step_id} is not part of this procedure.")
    s.add(m.Feedback(tenant_id=actor.tenant_id, run_id=run.id, step_id=step_id, helpful=bool(helpful),
                     comment=comment, actor_id=actor.id))
    audit(s, actor, "run.feedback", case=run.case, run=run.key, step=step_id, helpful=bool(helpful))


def latest_outcome(s: Session, case: m.Case) -> m.Outcome | None:
    return s.scalar(select(m.Outcome).where(m.Outcome.case_id == case.id).order_by(m.Outcome.id.desc()))
