"""Fieldwise data model.

Every business table carries tenant_id, and public identifiers ("C104", "MB2", "PB2") are
unique per tenant (`key`), never globally. Lookups always filter by the caller's tenant, so a
crafted ID from another tenant simply does not exist for that caller.
"""
from datetime import datetime, timezone

from sqlalchemy import (JSON, Boolean, DateTime, ForeignKey, Integer, String, Text,
                        UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def now():
    return datetime.now(timezone.utc)


class Tenant(Base):
    __tablename__ = "tenants"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(100))


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    title: Mapped[str] = mapped_column(String(100))


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("user_id", "tenant_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"))
    role: Mapped[str] = mapped_column(String(20))  # agent | technician | author | reviewer


class ProductNode(Base):
    """Product hierarchy: family -> model -> revision."""
    __tablename__ = "product_nodes"
    __table_args__ = (UniqueConstraint("tenant_id", "key"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"))
    key: Mapped[str] = mapped_column(String(40))
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("product_nodes.id"), nullable=True)
    kind: Mapped[str] = mapped_column(String(10))  # family | model | revision
    name: Mapped[str] = mapped_column(String(100))
    model: Mapped[str | None] = mapped_column(String(10), nullable=True)
    revision: Mapped[str | None] = mapped_column(String(10), nullable=True)


class FaultCode(Base):
    __tablename__ = "fault_codes"
    __table_args__ = (UniqueConstraint("tenant_id", "code"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"))
    family_id: Mapped[int] = mapped_column(ForeignKey("product_nodes.id"))
    code: Mapped[str] = mapped_column(String(20))  # canonical, e.g. D17
    label: Mapped[str] = mapped_column(String(200))


class FaultAlias(Base):
    __tablename__ = "fault_aliases"
    __table_args__ = (UniqueConstraint("tenant_id", "alias"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"))
    fault_code_id: Mapped[int] = mapped_column(ForeignKey("fault_codes.id"))
    alias: Mapped[str] = mapped_column(String(20))       # as written in the source, e.g. D-17
    normalized: Mapped[str] = mapped_column(String(20))  # lookup form, e.g. D17


class Asset(Base):
    __tablename__ = "assets"
    __table_args__ = (UniqueConstraint("tenant_id", "key"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"))
    key: Mapped[str] = mapped_column(String(40))  # opaque, e.g. B002 (never parsed)
    serial: Mapped[str] = mapped_column(String(60))
    site: Mapped[str] = mapped_column(String(100))
    location: Mapped[str] = mapped_column(String(200))  # e.g. "Elevator bank 1 / Car 2"
    product_node_id: Mapped[int | None] = mapped_column(ForeignKey("product_nodes.id"), nullable=True)


class Case(Base):
    __tablename__ = "cases"
    __table_args__ = (UniqueConstraint("tenant_id", "key"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"))
    key: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(200))
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id"))
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    assigned_tech_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    intake_text: Mapped[str] = mapped_column(Text)  # caller's words, verbatim
    status: Mapped[str] = mapped_column(String(20), default="open")  # open | resolved | escalated
    model: Mapped[str | None] = mapped_column(String(10), nullable=True)     # confirmed by a person
    revision: Mapped[str | None] = mapped_column(String(10), nullable=True)  # confirmed by a person
    version: Mapped[int] = mapped_column(Integer, default=1)
    asset: Mapped[Asset] = relationship()


class Observation(Base):
    __tablename__ = "observations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"))
    key: Mapped[str] = mapped_column(String(20))
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id"))
    field: Mapped[str] = mapped_column(String(40))        # fault_report | model | revision | ...
    value: Mapped[str | None] = mapped_column(String(200), nullable=True)
    original_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(12))       # observed | inferred | unknown
    origin: Mapped[str] = mapped_column(String(30))       # caller | agent_confirmation | suggestion | host
    supplied_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    polarity: Mapped[str] = mapped_column(String(10), default="present")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Inference(Base):
    __tablename__ = "inferences"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"))
    key: Mapped[str] = mapped_column(String(20))
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id"))
    text: Mapped[str] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(20), default="open")
    pending_check: Mapped[str | None] = mapped_column(String(20), nullable=True)


class Message(Base):
    """Assistant conversation, stored per case so switching cases never mixes context."""
    __tablename__ = "messages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"))
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id"))
    author_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    role: Mapped[str] = mapped_column(String(12))  # user | assistant
    text: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Source(Base):
    """One revision of a manual. Citations point at a Source plus a passage locator."""
    __tablename__ = "sources"
    __table_args__ = (UniqueConstraint("tenant_id", "key"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"))
    key: Mapped[str] = mapped_column(String(40))            # e.g. MB2
    external_id: Mapped[str] = mapped_column(String(80))    # uploader's ID, unique per tenant
    title: Mapped[str] = mapped_column(String(200))
    model: Mapped[str] = mapped_column(String(10))
    revision: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(12))         # current | superseded | withdrawn
    checksum: Mapped[str] = mapped_column(String(64))
    passages: Mapped[list["Passage"]] = relationship(back_populates="source", order_by="Passage.page")


class Passage(Base):
    __tablename__ = "passages"
    __table_args__ = (UniqueConstraint("source_id", "locator"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"))
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"))
    locator: Mapped[str] = mapped_column(String(20))   # e.g. p14
    page: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    fault_codes: Mapped[list] = mapped_column(JSON, default=list)  # normalized codes
    topic: Mapped[str | None] = mapped_column(String(40), nullable=True)  # e.g. indicator, self-test
    source: Mapped[Source] = relationship(back_populates="passages")


class HistoricalCase(Base):
    __tablename__ = "historical_cases"
    __table_args__ = (UniqueConstraint("tenant_id", "key"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"))
    key: Mapped[str] = mapped_column(String(20))
    model: Mapped[str] = mapped_column(String(10))
    revision: Mapped[str] = mapped_column(String(10))
    fault_code: Mapped[str] = mapped_column(String(20))
    summary: Mapped[str] = mapped_column(Text)
    attempts: Mapped[list] = mapped_column(JSON)  # [{"action":..., "result":...}]
    outcome: Mapped[str] = mapped_column(String(20))  # verified_recovery | unknown | not_resolved


class Template(Base):
    """A procedure skeleton defined at family level, filled per revision from cited passages."""
    __tablename__ = "templates"
    __table_args__ = (UniqueConstraint("tenant_id", "key"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"))
    key: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(200))
    family_id: Mapped[int] = mapped_column(ForeignKey("product_nodes.id"))
    definition: Mapped[dict] = mapped_column(JSON)


class Pathway(Base):
    __tablename__ = "pathways"
    __table_args__ = (UniqueConstraint("tenant_id", "key"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"))
    key: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(200))
    fault_code: Mapped[str] = mapped_column(String(20))
    model: Mapped[str] = mapped_column(String(10))
    revision: Mapped[str] = mapped_column(String(10))
    product_node_id: Mapped[int] = mapped_column(ForeignKey("product_nodes.id"))
    template_id: Mapped[int | None] = mapped_column(ForeignKey("templates.id"), nullable=True)
    versions: Mapped[list["PathwayVersion"]] = relationship(back_populates="pathway", order_by="PathwayVersion.version")


class PathwayVersion(Base):
    __tablename__ = "pathway_versions"
    __table_args__ = (UniqueConstraint("pathway_id", "version"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"))
    pathway_id: Mapped[int] = mapped_column(ForeignKey("pathways.id"))
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(12))  # draft | published | withdrawn
    definition: Mapped[dict] = mapped_column(JSON)
    author_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    reviewer_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    pathway: Mapped[Pathway] = relationship(back_populates="versions")
    nodes: Mapped[list["PathwayNode"]] = relationship(back_populates="version_row", order_by="PathwayNode.id")


class PathwayNode(Base):
    """Nodes of a published version, frozen at publication. The executor branches from these rows."""
    __tablename__ = "pathway_nodes"
    __table_args__ = (UniqueConstraint("version_id", "node_key"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("pathway_versions.id"))
    node_key: Mapped[str] = mapped_column(String(20))
    kind: Mapped[str] = mapped_column(String(10))  # step | terminal
    prompt: Mapped[str] = mapped_column(Text)
    citation_source: Mapped[str | None] = mapped_column(String(40), nullable=True)
    citation_locator: Mapped[str | None] = mapped_column(String(20), nullable=True)
    edges: Mapped[dict] = mapped_column(JSON, default=dict)  # answer -> next node
    outcome: Mapped[str | None] = mapped_column(String(12), nullable=True)  # resolved | escalate
    open_question: Mapped[str | None] = mapped_column(Text, nullable=True)
    version_row: Mapped[PathwayVersion] = relationship(back_populates="nodes")


class Run(Base):
    __tablename__ = "runs"
    __table_args__ = (UniqueConstraint("tenant_id", "key"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"))
    key: Mapped[str] = mapped_column(String(40))
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id"))
    pathway_version_id: Mapped[int] = mapped_column(ForeignKey("pathway_versions.id"))
    status: Mapped[str] = mapped_column(String(20))  # active | paused | awaiting_outcome | resolved | escalated
    pause_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    current_node: Mapped[str] = mapped_column(String(20))
    version: Mapped[int] = mapped_column(Integer, default=1)
    started_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    pathway_version: Mapped[PathwayVersion] = relationship()
    case: Mapped[Case] = relationship()


class Response(Base):
    __tablename__ = "responses"
    __table_args__ = (UniqueConstraint("run_id", "retry_key"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"))
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"))
    step_id: Mapped[str] = mapped_column(String(20))
    answer: Mapped[str] = mapped_column(String(40))
    next_node: Mapped[str] = mapped_column(String(20))
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    retry_key: Mapped[str] = mapped_column(String(80))
    request_hash: Mapped[str] = mapped_column(String(64))
    result: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Outcome(Base):
    __tablename__ = "outcomes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"))
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id"))
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"))
    kind: Mapped[str] = mapped_column(String(12))  # resolved | escalated
    terminal: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str] = mapped_column(Text)
    action_taken: Mapped[str | None] = mapped_column(Text, nullable=True)
    verification: Mapped[str | None] = mapped_column(Text, nullable=True)
    open_question: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempted_steps: Mapped[list] = mapped_column(JSON)
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Feedback(Base):
    __tablename__ = "feedback"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"))
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"))
    step_id: Mapped[str] = mapped_column(String(20))
    helpful: Mapped[bool] = mapped_column(Boolean)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"))
    case_id: Mapped[int | None] = mapped_column(ForeignKey("cases.id"), nullable=True)
    actor_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(60))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ImportJob(Base):
    __tablename__ = "import_jobs"
    __table_args__ = (UniqueConstraint("tenant_id", "checksum"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"))
    uploader_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    checksum: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20))
    accepted: Mapped[list] = mapped_column(JSON)
    rejected: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Delivery(Base):
    """Transactional outbox row for an approved host update."""
    __tablename__ = "deliveries"
    __table_args__ = (UniqueConstraint("delivery_key"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"))
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id"))
    outcome_id: Mapped[int] = mapped_column(ForeignKey("outcomes.id"))
    delivery_key: Mapped[str] = mapped_column(String(80))
    payload: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(12))  # pending | failed | delivered
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    receipt: Mapped[str | None] = mapped_column(String(40), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    approved_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class HostRecord(Base):
    """What the mock host received. Deduplicated by delivery key."""
    __tablename__ = "host_records"
    __table_args__ = (UniqueConstraint("delivery_key"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"))
    delivery_key: Mapped[str] = mapped_column(String(80))
    case_key: Mapped[str] = mapped_column(String(40))
    receipt: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict] = mapped_column(JSON)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[str] = mapped_column(String(200))
