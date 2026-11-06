"""Shared building blocks: errors, identity, tenant-scoped lookups and the audit trail."""
import hashlib
import json
import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m


class AppError(Exception):
    """A business-rule failure with an HTTP status. Messages never reveal other tenants' data."""

    def __init__(self, status: int, code: str, message: str, **extra):
        super().__init__(message)
        self.status, self.code, self.message, self.extra = status, code, message, extra

    def body(self):
        return {"error": self.code, "message": self.message, **self.extra}


def not_found():
    return AppError(404, "not_found", "Not found")


def forbidden(message="You are not allowed to do that."):
    return AppError(403, "forbidden", message)


def conflict(message, **extra):
    return AppError(409, "conflict", message, **extra)


@dataclass
class Actor:
    """The signed-in person, derived on the server from the session. Never from the request body."""
    id: str
    name: str
    tenant_id: str
    role: str


def load_actor(s: Session, user_id: str | None) -> Actor:
    if not user_id:
        raise AppError(401, "unauthenticated", "Pick a demo identity first.")
    row = s.execute(
        select(m.User, m.Membership).join(m.Membership, m.Membership.user_id == m.User.id)
        .where(m.User.id == user_id)
    ).first()
    if not row:
        raise AppError(401, "unauthenticated", "Unknown demo identity.")
    user, mem = row
    return Actor(user.id, user.name, mem.tenant_id, mem.role)


def require_role(actor: Actor, *roles: str):
    if actor.role not in roles:
        raise forbidden(f"This needs the {' or '.join(roles)} role.")


def scoped(s: Session, model, actor: Actor, key: str):
    """Fetch a tenant-scoped row by its public key, or 404. Another tenant's key looks identical to a missing one."""
    obj = s.scalar(select(model).where(model.tenant_id == actor.tenant_id, model.key == key))
    if obj is None:
        raise not_found()
    return obj


def audit(s: Session, actor_or_tenant, action: str, case: "m.Case | None" = None, **detail):
    if isinstance(actor_or_tenant, Actor):
        tenant_id, actor_id = actor_or_tenant.tenant_id, actor_or_tenant.id
    else:
        tenant_id, actor_id = actor_or_tenant, None
    s.add(m.AuditEvent(tenant_id=tenant_id, actor_id=actor_id, action=action,
                       case_id=case.id if case else None, detail=detail))


def normalize_code(text: str) -> str:
    return re.sub(r"[\s\-_]", "", text or "").upper()


def checksum(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def check_version(current: int, expected, what="record"):
    if expected is None:
        raise AppError(422, "missing_version", f"expectedVersion is required for this {what}.")
    if int(expected) != current:
        raise conflict(f"This {what} changed since you loaded it. Reload and try again.",
                       currentVersion=current)
