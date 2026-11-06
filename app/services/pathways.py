"""Pathway definitions: validation, drafts, publication, withdrawal and templates.

A definition looks like:
{
  "start": "K1",
  "nodes": {
    "K1": {"kind": "step", "prompt": "...", "citation": {"source": "MB2", "locator": "p14"},
           "inputs": ["green", "amber", "unreadable"],
           "edges": {"green": "K2", "amber": "E1", "unreadable": "E2"}},
    "R":  {"kind": "terminal", "outcome": "resolved", "reason": "..."},
    "E1": {"kind": "terminal", "outcome": "escalate", "reason": "...", "openQuestion": "..."}
  }
}
"""
import copy

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from .core import Actor, AppError, audit, conflict, forbidden, not_found, require_role, scoped


def validate(s: Session, tenant_id: str, pathway: m.Pathway, d: dict) -> list[str]:
    errors: list[str] = []
    if not isinstance(d, dict) or not isinstance(d.get("nodes"), dict) or not d["nodes"]:
        return ["Definition needs a non-empty \"nodes\" object."]
    nodes, start = d["nodes"], d.get("start")
    if start not in nodes:
        errors.append(f"Start node {start!r} does not exist.")
    for key, n in nodes.items():
        kind = n.get("kind")
        if kind == "step":
            if not str(n.get("prompt", "")).strip():
                errors.append(f"{key} has no prompt.")
            inputs, edges = n.get("inputs"), n.get("edges")
            if not isinstance(inputs, list) or not inputs:
                errors.append(f"{key} must list its allowed inputs.")
                continue
            if len(set(inputs)) != len(inputs):
                errors.append(f"{key} lists an allowed input more than once.")
            if not isinstance(edges, dict):
                errors.append(f"{key} has no edges.")
                continue
            for a in inputs:
                if a not in edges:
                    errors.append(f"{key} answer {a!r} has no edge.")
            for a, target in edges.items():
                if a not in inputs:
                    errors.append(f"{key} has an edge for {a!r}, which is not an allowed input.")
                if target not in nodes:
                    errors.append(f"{key} answer {a!r} routes to missing step {target}.")
            cit = n.get("citation")
            if cit:
                src = s.scalar(select(m.Source).where(m.Source.tenant_id == tenant_id,
                                                      m.Source.key == cit.get("source")))
                if not src:
                    errors.append(f"{key} cites unknown source {cit.get('source')!r}.")
                else:
                    if src.status != "current":
                        errors.append(f"{key} cites {src.key}, which is {src.status}.")
                    if (src.model, src.revision) != (pathway.model, pathway.revision):
                        errors.append(f"{key} cites {src.key} (Model {src.model} rev {src.revision}), "
                                      f"which does not apply to Model {pathway.model} rev {pathway.revision}.")
                    if not any(p.locator == cit.get("locator") for p in src.passages):
                        errors.append(f"{key} cites locator {cit.get('locator')!r}, not found in {src.key}.")
        elif kind == "terminal":
            if n.get("outcome") not in ("resolved", "escalate"):
                errors.append(f"{key} must end as resolved or escalate.")
            if n.get("outcome") == "escalate" and not str(n.get("openQuestion", "")).strip():
                errors.append(f"Escalation {key} needs an open question.")
        else:
            errors.append(f"{key} has unknown kind {kind!r}.")
    if start not in nodes:
        return errors
    # reachability and cycles
    seen, stack, on_path, cycle = set(), [], set(), []

    def walk(k):
        if k in on_path:
            cycle.append(k)
            return
        if k in seen:
            return
        seen.add(k)
        on_path.add(k)
        for t in (nodes[k].get("edges") or {}).values():
            if t in nodes:
                walk(t)
        on_path.discard(k)

    walk(start)
    for k in nodes:
        if k not in seen:
            errors.append(f"{k} is unreachable from {start}.")
    if cycle:
        errors.append(f"The pathway loops back to {cycle[0]}; cycles are not allowed.")
    if not any(n.get("kind") == "terminal" for n in nodes.values()):
        errors.append("The pathway has no terminal state.")
    return errors


def cited_sources(defn: dict) -> set[str]:
    return {n["citation"]["source"] for n in defn.get("nodes", {}).values() if n.get("citation")}


def version_usable(s: Session, v: m.PathwayVersion) -> bool:
    """Published and every cited source still current."""
    if v.status != "published":
        return False
    keys = cited_sources(v.definition)
    if not keys:
        return True
    srcs = s.scalars(select(m.Source).where(m.Source.tenant_id == v.tenant_id, m.Source.key.in_(keys))).all()
    return len(srcs) == len(keys) and all(x.status == "current" for x in srcs)


def latest_usable(s: Session, pathway: m.Pathway) -> m.PathwayVersion | None:
    for v in sorted(pathway.versions, key=lambda x: -x.version):
        if version_usable(s, v):
            return v
    return None


def eligible(s: Session, tenant_id: str, model: str, revision: str, codes: set[str]):
    rows = s.scalars(select(m.Pathway).where(m.Pathway.tenant_id == tenant_id, m.Pathway.model == model,
                                             m.Pathway.revision == revision)).all()
    out = []
    for p in rows:
        if codes and p.fault_code not in codes:
            continue
        v = latest_usable(s, p)
        if v:
            out.append((p, v))
    return out


def save_draft(s: Session, actor: Actor, pathway_key: str, definition: dict):
    require_role(actor, "author")
    p = scoped(s, m.Pathway, actor, pathway_key)
    draft = next((v for v in p.versions if v.status == "draft"), None)
    if draft:
        draft.definition = definition
        draft.author_id = actor.id
    else:
        nxt = max([v.version for v in p.versions] or [0]) + 1
        draft = m.PathwayVersion(tenant_id=actor.tenant_id, pathway_id=p.id, version=nxt, status="draft",
                                 definition=definition, author_id=actor.id)
        s.add(draft)
        p.versions.append(draft)
    errors = validate(s, actor.tenant_id, p, definition)
    s.flush()
    audit(s, actor, "pathway.draft_saved", pathway=p.key, version=draft.version, errors=len(errors))
    return draft, errors


def _materialize(s: Session, v: m.PathwayVersion):
    for key, n in v.definition["nodes"].items():
        cit = n.get("citation") or {}
        s.add(m.PathwayNode(version_id=v.id, node_key=key, kind=n["kind"],
                            prompt=n.get("prompt") or n.get("reason", ""),
                            citation_source=cit.get("source"), citation_locator=cit.get("locator"),
                            edges=n.get("edges", {}), outcome=n.get("outcome"),
                            open_question=n.get("openQuestion")))


def publish(s: Session, actor: Actor, pathway_key: str, version: int, now):
    require_role(actor, "reviewer")
    p = scoped(s, m.Pathway, actor, pathway_key)
    v = next((x for x in p.versions if x.version == version), None)
    if not v:
        raise not_found()
    if v.status != "draft":
        raise conflict(f"Version {version} is {v.status}; published versions never change.")
    if v.author_id == actor.id:
        raise forbidden("Authors cannot publish their own pathway. Ask a different reviewer.")
    errors = validate(s, actor.tenant_id, p, v.definition)
    if errors:
        audit(s, actor, "pathway.publish_rejected", pathway=p.key, version=version, errors=errors)
        s.commit()
        raise AppError(422, "invalid_pathway", "This draft does not pass validation.", errors=errors)
    v.status, v.reviewer_id, v.published_at = "published", actor.id, now
    v.definition = copy.deepcopy(v.definition)
    s.flush()
    _materialize(s, v)
    audit(s, actor, "pathway.published", pathway=p.key, version=version)
    return v


def pause_runs(s: Session, actor: Actor, version_ids: list[int], reason: str):
    runs = s.scalars(select(m.Run).where(m.Run.pathway_version_id.in_(version_ids),
                                         m.Run.status.in_(["active", "awaiting_outcome"]))).all() if version_ids else []
    for r in runs:
        r.status, r.pause_reason = "paused", reason
        r.version += 1
        audit(s, actor, "run.paused", case=r.case, run=r.key, reason=reason)
    return runs


def withdraw(s: Session, actor: Actor, pathway_key: str, version: int, now):
    require_role(actor, "reviewer")
    p = scoped(s, m.Pathway, actor, pathway_key)
    v = next((x for x in p.versions if x.version == version), None)
    if not v:
        raise not_found()
    if v.status != "published":
        raise conflict(f"Version {version} is {v.status}; only published versions can be withdrawn.")
    v.status, v.withdrawn_at = "withdrawn", now
    audit(s, actor, "pathway.withdrawn", pathway=p.key, version=version)
    pause_runs(s, actor, [v.id], f"{p.key} v{version} was withdrawn by a reviewer")
    return v


def withdraw_source(s: Session, actor: Actor, source_key: str):
    require_role(actor, "reviewer")
    src = scoped(s, m.Source, actor, source_key)
    if src.status == "withdrawn":
        return src, []
    src.status = "withdrawn"
    audit(s, actor, "source.withdrawn", source=src.key)
    versions = s.scalars(select(m.PathwayVersion).where(m.PathwayVersion.tenant_id == actor.tenant_id)).all()
    dependent = [v.id for v in versions if src.key in cited_sources(v.definition)]
    paused = pause_runs(s, actor, dependent, f"Evidence {src.key} was withdrawn")
    return src, paused


def apply_template(s: Session, actor: Actor, template_key: str, revision_node_key: str):
    """Fill a family-level template for one revision. Every bound slot must cite that revision's own page."""
    require_role(actor, "author")
    t = scoped(s, m.Template, actor, template_key)
    node = scoped(s, m.ProductNode, actor, revision_node_key)
    if node.kind != "revision":
        raise AppError(422, "not_a_revision", "Apply a template to a revision node.")
    d = copy.deepcopy(t.definition)
    errors, bound = [], []
    srcs = s.scalars(select(m.Source).where(m.Source.tenant_id == actor.tenant_id, m.Source.model == node.model,
                                            m.Source.revision == node.revision, m.Source.status == "current")).all()
    for key, n in d["nodes"].items():
        topic = n.pop("bind", None)
        if not topic:
            continue
        hit = next(((src, p) for src in srcs for p in src.passages if p.topic == topic), None)
        if not hit:
            errors.append(f"Slot {key} ({topic}) has no cited passage for Model {node.model} rev {node.revision}.")
        else:
            n["citation"] = {"source": hit[0].key, "locator": hit[1].locator}
            n["prompt"] = hit[1].text.split(". Record")[0].rstrip(".") + "."
            bound.append({"slot": key, "topic": topic, "source": hit[0].key, "locator": hit[1].locator})
    if errors:
        audit(s, actor, "template.apply_blocked", template=t.key, node=node.key, errors=errors)
        s.commit()
        raise AppError(422, "unbound_slot", "A template cannot invent evidence.", errors=errors, bound=bound)
    fault = d.pop("faultCode", "D17")
    p = s.scalar(select(m.Pathway).where(m.Pathway.tenant_id == actor.tenant_id, m.Pathway.model == node.model,
                                         m.Pathway.revision == node.revision, m.Pathway.fault_code == fault))
    if not p:
        p = m.Pathway(tenant_id=actor.tenant_id, key=f"P{node.model}{node.revision}-T", name=f"{t.name} · Model {node.model} rev {node.revision}",
                      fault_code=fault, model=node.model, revision=node.revision, product_node_id=node.id, template_id=t.id)
        s.add(p)
        s.flush()
    draft, verrors = save_draft(s, actor, p.key, d)
    audit(s, actor, "template.applied", template=t.key, node=node.key, pathway=p.key, version=draft.version)
    return p, draft, bound, verrors
