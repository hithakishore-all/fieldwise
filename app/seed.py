"""Resettable synthetic fixtures. Every person, manual, asset and procedure here is fictional."""
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from . import db
from . import models as m
from .services.core import checksum
from .services.pathways import _materialize

USERS = [  # id, name, title, tenant, role
    ("ana", "Ana", "Support agent", "north", "agent"),
    ("teo", "Teo", "Field technician", "north", "technician"),
    ("mia", "Mia", "Field technician (not assigned)", "north", "technician"),
    ("ari", "Ari", "Knowledge author", "north", "author"),
    ("ren", "Ren", "Procedure reviewer", "north", "reviewer"),
    ("sol", "Sol", "Field technician", "south", "technician"),
    ("suri", "Suri", "Support agent", "south", "agent"),
]

SOURCES = [  # tenant, key, externalId, title, model, rev, status, passages
    ("north", "MA1", "north-manual-a-r1", "Model A service manual", "A", "1", "current",
     [("p8", 8, "Inspect the blue indicator in simulator A.", ["D17"], "indicator")]),
    ("north", "MB2", "north-manual-b-r2", "Model B service manual", "B", "2", "current",
     [("p14", 14, "Read indicator B in the simulator. Record green, amber or unreadable.", ["D17"], "indicator"),
      ("p15", 15, "Run the B simulator self-test and record its result.", ["D17"], "self-test")]),
    ("north", "MB1", "north-manual-b-r1", "Model B service manual (old)", "B", "1", "superseded",
     [("p9", 9, "Use legacy dial B.", ["D17"], "indicator")]),
    ("south", "SM1", "south-manual-c-r1", "South simulator manual", "C", "1", "current",
     [("p3", 3, "SOUTH-ONLY-41 calibration note for the South simulator.", ["D17"], "indicator")]),
]

ESCALATIONS = {
    "E1": ("Simulated indicator anomaly.", "What is causing the simulated indicator anomaly on this unit?"),
    "E2": ("A readable observation is needed.", "Can someone on site capture a readable indicator or self-test result?"),
    "E3": ("Simulated service was not verified as restored.", "Why does the fault persist after a passing self-test?"),
}


def _esc(key):
    reason, q = ESCALATIONS[key]
    return {"kind": "terminal", "outcome": "escalate", "reason": reason, "openQuestion": q}


PB2_V1 = {"start": "K1", "nodes": {
    "K1": {"kind": "step", "prompt": "Read indicator B in the simulator.", "citation": {"source": "MB2", "locator": "p14"},
           "inputs": ["green", "amber", "unreadable"], "edges": {"green": "K2", "amber": "E1", "unreadable": "E2"}},
    "K2": {"kind": "step", "prompt": "Run the B simulator self-test and record its result.", "citation": {"source": "MB2", "locator": "p15"},
           "inputs": ["pass", "fail", "unknown"], "edges": {"pass": "V1", "fail": "E1", "unknown": "E2"}},
    "V1": {"kind": "step", "prompt": "Was simulated service restored?", "inputs": ["yes", "no", "unknown"],
           "edges": {"yes": "R", "no": "E3", "unknown": "E3"}},
    "R": {"kind": "terminal", "outcome": "resolved", "reason": "Simulated service restored. Record a verification note to close."},
    "E1": _esc("E1"), "E2": _esc("E2"), "E3": _esc("E3"),
}}

PA1_V1 = {"start": "K1", "nodes": {
    "K1": {"kind": "step", "prompt": "Inspect the blue indicator in simulator A.", "citation": {"source": "MA1", "locator": "p8"},
           "inputs": ["normal", "abnormal"], "edges": {"normal": "V1", "abnormal": "E1"}},
    "V1": {"kind": "step", "prompt": "Was simulated service restored?", "inputs": ["yes", "no"], "edges": {"yes": "R", "no": "E3"}},
    "R": {"kind": "terminal", "outcome": "resolved", "reason": "Simulated service restored. Record a verification note to close."},
    "E1": _esc("E1"), "E3": _esc("E3"),
}}

TEMPLATE_T_IND = {"faultCode": "D17", "start": "K1", "nodes": {
    "K1": {"kind": "step", "prompt": "Read the indicator in the simulator.", "bind": "indicator",
           "inputs": ["green", "amber", "unreadable"], "edges": {"green": "K2", "amber": "E1", "unreadable": "E2"}},
    "K2": {"kind": "step", "prompt": "Run the simulator self-test and record its result.", "bind": "self-test",
           "inputs": ["pass", "fail", "unknown"], "edges": {"pass": "V1", "fail": "E1", "unknown": "E2"}},
    "V1": {"kind": "step", "prompt": "Was simulated service restored?", "inputs": ["yes", "no", "unknown"],
           "edges": {"yes": "R", "no": "E3", "unknown": "E3"}},
    "R": {"kind": "terminal", "outcome": "resolved", "reason": "Simulated service restored. Record a verification note to close."},
    "E1": _esc("E1"), "E2": _esc("E2"), "E3": _esc("E3"),
}}


def reset(engine=None):
    engine = engine or db.engine
    m.Base.metadata.drop_all(engine)
    m.Base.metadata.create_all(engine)
    with db.SessionLocal(bind=engine) as s:
        populate(s)
        s.commit()


def populate(s: Session):
    t0 = datetime(2026, 11, 2, 9, 0, tzinfo=timezone.utc)
    s.add_all([m.Tenant(id="north", name="North (fictional)"), m.Tenant(id="south", name="South (fictional)")])
    for uid, name, title, tenant, role in USERS:
        s.add(m.User(id=uid, name=name, title=title))
        s.flush()
        s.add(m.Membership(user_id=uid, tenant_id=tenant, role=role))
    s.flush()

    # Product hierarchy: family -> model -> revision
    def node(tenant, key, kind, name, parent=None, model=None, rev=None):
        n = m.ProductNode(tenant_id=tenant, key=key, kind=kind, name=name, parent_id=parent.id if parent else None,
                          model=model, revision=rev)
        s.add(n)
        s.flush()
        return n

    fam = node("north", "ELEV", "family", "Elevators (simulated)")
    ma = node("north", "ELEV-A", "model", "Model A", fam, "A")
    na1 = node("north", "ELEV-A-1", "revision", "rev 1", ma, "A", "1")
    mb = node("north", "ELEV-B", "model", "Model B", fam, "B")
    node("north", "ELEV-B-1", "revision", "rev 1", mb, "B", "1")
    nb2 = node("north", "ELEV-B-2", "revision", "rev 2", mb, "B", "2")
    sfam = node("south", "SELEV", "family", "South elevators (simulated)")
    sc = node("south", "SELEV-C", "model", "Model C", sfam, "C")
    sc1 = node("south", "SELEV-C-1", "revision", "rev 1", sc, "C", "1")

    for tenant, family in (("north", fam), ("south", sfam)):
        fc = m.FaultCode(tenant_id=tenant, family_id=family.id, code="D17", label="Door reopen fault (simulated)")
        s.add(fc)
        s.flush()
        s.add_all([m.FaultAlias(tenant_id=tenant, fault_code_id=fc.id, alias="D17", normalized="D17"),
                   m.FaultAlias(tenant_id=tenant, fault_code_id=fc.id, alias="D-17", normalized="D17")])

    for tenant, key, ext, title, model, rev, status, passages in SOURCES:
        rec = {"sourceId": key, "externalId": ext, "title": title, "model": model, "revision": rev, "status": status,
               "passages": [{"locator": l, "page": p, "text": t, "faultCodes": c, "topic": tp} for l, p, t, c, tp in passages]}
        src = m.Source(tenant_id=tenant, key=key, external_id=ext, title=title, model=model, revision=rev,
                       status=status, checksum=checksum(rec))
        s.add(src)
        s.flush()
        for loc, page, text, codes, topic in passages:
            s.add(m.Passage(tenant_id=tenant, source_id=src.id, locator=loc, page=page, text=text, fault_codes=codes, topic=topic))

    s.add_all([
        m.HistoricalCase(tenant_id="north", key="H1", model="B", revision="2", fault_code="D17",
                         summary="Doors reopened repeatedly with D17 on a Model B rev 2 simulator.",
                         attempts=[{"action": "Ran the self-test only", "result": "Service not restored"},
                                   {"action": "Read indicator B, then ran the self-test", "result": "Verified recovery"}],
                         outcome="verified_recovery"),
        m.HistoricalCase(tenant_id="north", key="H2", model="B", revision="2", fault_code="D17",
                         summary="D17 reported; indicator read green and self-test run. Technician left before verification.",
                         attempts=[{"action": "Read indicator B, then ran the self-test", "result": "Not verified"}],
                         outcome="unknown"),
    ])

    # Assets and cases. B002 is opaque: its model is unknown until a person confirms it.
    b002 = m.Asset(tenant_id="north", key="B002", serial="SN-48213", site="Harbor Tower", location="Elevator bank 1 / Car 2")
    b007 = m.Asset(tenant_id="north", key="B007", serial="SN-90551", site="Harbor Tower", location="Elevator bank 1 / Car 3")
    s900 = m.Asset(tenant_id="south", key="S900", serial="SN-77001", site="Pier Seven", location="Lobby / Car 1",
                   product_node_id=sc1.id)
    s.add_all([b002, b007, s900])
    s.flush()
    c104 = m.Case(tenant_id="north", key="C104", title="Doors keep reopening", asset_id=b002.id, owner_id="ana",
                  intake_text="doors keep reopening, D17")
    c105 = m.Case(tenant_id="north", key="C105", title="Car stops between floors", asset_id=b007.id, owner_id="ana",
                  intake_text="car stops between floors, no code shown")
    s301 = m.Case(tenant_id="south", key="S301", title="Hoistway noise at Pier Seven", asset_id=s900.id, owner_id="suri",
                  intake_text="loud noise in the shaft", model="C", revision="1")
    s.add_all([c104, c105, s301])
    s.flush()
    s.add_all([
        m.Observation(tenant_id="north", key="O1", case_id=c104.id, field="fault_report", value="D17",
                      original_text="doors keep reopening, D17", status="observed", origin="caller", created_at=t0),
        m.Observation(tenant_id="north", key="O-model-0", case_id=c104.id, field="model", value=None,
                      status="unknown", origin="host", created_at=t0),
        m.Observation(tenant_id="north", key="O-revision-0", case_id=c104.id, field="revision", value=None,
                      status="unknown", origin="host", created_at=t0),
        m.Inference(tenant_id="north", key="I1", case_id=c104.id, text="Door reopen fault behind D17", status="open",
                    pending_check="K1"),
    ])
    for c in (c104, c105, s301):
        s.add(m.AuditEvent(tenant_id=c.tenant_id, case_id=c.id, action="case.opened",
                           detail={"intake": c.intake_text}, created_at=t0))

    tpl = m.Template(tenant_id="north", key="T-IND", name="Indicator, self-test, verify", family_id=fam.id,
                     definition=TEMPLATE_T_IND)
    s.add(tpl)
    s.flush()
    for key, name, model, rev, nd, defn, tid in (("PB2", "D17 door reopen · Model B rev 2", "B", "2", nb2, PB2_V1, tpl.id),
                                                 ("PA1", "D17 door reopen · Model A rev 1", "A", "1", na1, PA1_V1, None)):
        p = m.Pathway(tenant_id="north", key=key, name=name, fault_code="D17", model=model, revision=rev,
                      product_node_id=nd.id, template_id=tid)
        s.add(p)
        s.flush()
        v = m.PathwayVersion(tenant_id="north", pathway_id=p.id, version=1, status="published", definition=defn,
                             author_id="ari", reviewer_id="ren", published_at=t0)
        s.add(v)
        s.flush()
        _materialize(s, v)
    s.add(m.Setting(key="host_fail_next", value="0"))
