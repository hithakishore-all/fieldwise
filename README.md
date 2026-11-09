# Fieldwise

**Your next move, made clear.**

Fieldwise carries one equipment problem from the support call to a verified fix on a technician's phone. It gives no repair steps until a person confirms the exact model and revision. Then every step is cited to a manual page, pinned to a reviewer-approved procedure version, and recorded in an audit trail.

![Fieldwise service desk with the embedded case workspace](docs/screenshots/service-desk.png)

> **All data is fictional.** Every elevator model, manual, procedure, company and person is invented for this demo. The in-app assistant uses scripted retrieval and response templates, not a live model.

**Live demo (no install):** https://hithakishore-all.github.io/fieldwise/ opens with a 3-minute captioned video of the working app, then a click-through version.

## Contents

- [Why this exists](#why-this-exists)
- [Try it in 2 minutes](#try-it-in-2-minutes)
- [Ways to run it](#ways-to-run-it)
- [Five-minute walkthrough](#five-minute-walkthrough)
- [Demo identities and records](#demo-identities-and-records)
- [How it works](#how-it-works)
- [Commands](#commands)
- [Configuration](#configuration)
- [HTTP API](#http-api)
- [Testing](#testing)
- [Project layout](#project-layout)
- [Security and data handling](#security-and-data-handling)
- [Troubleshooting](#troubleshooting)
- [FAQ and known limitations](#faq-and-known-limitations)
- [Beyond the prototype](#beyond-the-prototype)
- [License](#license)

## Why this exists

| Signal | Number | Source |
| --- | --- | --- |
| Cost of a failed first visit | Adds two more visits and 14 days on average | [Aquant 2025 Field Service Benchmark](https://salestechstar.com/predictive-ai-artificial-intelligence/aquants-2025-field-service-benchmark-report-reveals-ai-enabling-39-faster-machinery-repairs-and-more/) |
| First-time fix gap | 86% for top performers vs 53% for the bottom group | same report |
| Knowledge only experts hold | 30% of solutions appear only in expert-provided data | [Aquant Service Co-Pilot release](https://www.businesswire.com/news/home/20230517005191/en/Aquants-Service-Co-Pilot-Delivers-Generative-AI-Purpose-Built-for-Service) |
| AI trust gap | Gartner predicts more than 40% of agentic AI projects will be cancelled by the end of 2027 | [RCR Wireless](https://www.rcrwireless.com/20250627/business/agentic-ai) |

Everyone is adding AI answers. Fieldwise adds the approved next step: cited, pinned to the right model and carried from the call to the fix. The full product requirements, research and competitive landscape are in [docs/PRD.md](docs/PRD.md).

| Principle | What Fieldwise does |
| --- | --- |
| Refuse to guess | Zero model-specific steps until a person confirms model and revision. Never inferred from a serial number |
| Cite everything | Every answer and step points to a source revision plus page. Superseded and withdrawn content never appears |
| Only approved steps | A past fix can support a hypothesis; only a published, applicable procedure authorizes a step |
| Chat explains, people choose | The assistant can explain the current step but cannot pick a branch |
| Pin and resume | A run is pinned to one procedure version; a refresh or handoff restores the same run |
| Separation of duties | Authors cannot publish their own procedures. Withdrawals pause live runs |
| Exactly once | Retry keys, version checks and an outbox mean a double tap or a retry counts once |

## Try it in 2 minutes

You need Python 3.12 (3.11 works too) and git. No accounts, keys or database server.

```bash
git clone https://github.com/hithakishore-all/fieldwise.git
cd fieldwise
make setup      # creates .venv and installs pinned dependencies
make offline    # loads the demo data into ./fieldwise.db and starts the app
```

Open **http://127.0.0.1:8000** and pick **Ana**. No git? Download the ZIP from the green **Code** button on GitHub, unzip it, and run the same two `make` commands inside the folder.

## Ways to run it

| Mode | Database | Command | Good for |
| --- | --- | --- | --- |
| Guided demo | None (browser only) | Open [the live demo](https://hithakishore-all.github.io/fieldwise/) or `demo/index.html` | A two-minute look at the flow |
| Offline app | SQLite file `./fieldwise.db` | `make offline` | Trying the real app with zero setup |
| Full app | PostgreSQL | `cp .env.example .env`, then `make reset` and `make start` ([setup guide](docs/SETUP_POSTGRES.md)) | The recommended setup |

## Five-minute walkthrough

Use two browser windows: a normal one for Ana, and a narrow one (or your phone's browser pointed at your laptop) for Teo. Each window keeps its own demo identity.

**Resolution (about 3 minutes)**

1. **Ana** lands on the mock **Northline Service Desk** with Fieldwise embedded. C104 shows the caller's words "doors keep reopening, D17", a known serial, and model and revision marked *unknown*.
2. Click **Ask**. Fieldwise answers *clarify*: D17 appears for two models, so confirm model and revision. Zero steps.
3. Choose **Model B**, **rev 2**, click **Confirm**. It's saved as Ana's observation.
4. Click **Ask** again. Now you get manual **MB2 · rev 2 · p14**, **1 verified recovery in 2 matching cases** (H1, H2) and procedure **PB2 v1**. Click the citation to open the exact page.
5. Pick **Teo** and click **Start and assign**.
6. In the narrow window, pick **Teo**, open the run under **My runs**, tap **Green**, then reload: the same run, version and step come back. Open the **MB2 · p15** citation, go back, tap **Pass**, then **Yes**, and **Save verified outcome**.
7. Back as **Ana**, reload, click **Approve and queue for host**, click **Simulate host outage on next send**, then **Send to host** (it fails) and **Retry delivery** (it delivers, with a receipt). The host's sidebar shows exactly one received summary.
8. Pick **Ren** and open **Review → C104** to see the steps, evidence, feedback, outcome and every audit event in order.

**Escalation (about 2 minutes):** run `make reset`, repeat steps 1 to 5, then as Teo tap **Amber**. The run ends in escalation E1 with the steps tried and an open question. Ana approves and sends that summary instead.

**Also try:** as Ren, click **Withdraw v1** under PB2 on the Review page while Teo's run is active (Teo's next tap is refused and the run pauses). As Ari, open **Knowledge**, click **Import** twice (2 accepted, 1 rejected, and nothing new the second time), then apply template **T-IND** to `ELEV-A-1` and watch it refuse to invent a missing page. Open **Hierarchy** to see where codes, manuals and procedures attach.

## Demo identities and records

| Person | Role | Tenant | Use it to |
| --- | --- | --- | --- |
| Ana | Support agent | North | Own C104 and C105, confirm, start runs, approve host updates |
| Teo | Technician | North | Answer the steps of runs assigned to him |
| Mia | Technician (not assigned) | North | Prove that an unassigned technician is blocked |
| Ari | Knowledge author | North | Import manifests, draft pathways, apply templates |
| Ren | Reviewer | North | Publish, withdraw, read traces and feedback |
| Sol, Suri | Technician, agent | South | Prove that another tenant sees nothing of North |

| Record | What it demonstrates |
| --- | --- |
| C104 · asset B002 | The hero run: clarify, confirm, cite, hand off, execute, close |
| C105 · asset B007 | A separate case with its own empty conversation |
| MA1 p8 (Model A rev 1) | The near-identical sibling instruction that never appears for Model B |
| MB2 p14, p15 (Model B rev 2) | The page-addressed evidence behind each step |
| MB1 p9 (superseded) | Stale content that is never cited; confirm B rev 1 to see Fieldwise explain why |
| H1, H2 | History with a denominator; an unknown outcome stays unknown |
| PB2 v1 · PA1 v1 | Approved procedures for B rev 2 and A rev 1 |
| T-IND | A family-level template that binds to each revision's own pages |
| S301 · SM1 (South) | Another tenant's case and manual, including the token `SOUTH-ONLY-41` |

The PB2 v1 procedure:

```mermaid
flowchart LR
  K1["K1 · Read indicator B<br/>MB2 p14"] -->|green| K2["K2 · Run the self-test<br/>MB2 p15"]
  K1 -->|amber| E1([E1 · indicator anomaly])
  K1 -->|unreadable| E2([E2 · need a readable observation])
  K2 -->|pass| V1["V1 · Service restored?"]
  K2 -->|fail| E1
  K2 -->|unknown| E2
  V1 -->|yes| R([R · resolved, needs a verification note])
  V1 -->|no / unknown| E3([E3 · not verified])
```

## How it works

```mermaid
flowchart LR
  subgraph Screens
    H[Mock host page<br/>embeds the workspace]
    W[Case workspace · Ana]
    P[Phone run view · Teo]
    K[Knowledge and review · Ari, Ren]
  end
  subgraph Server["Fieldwise server (FastAPI)"]
    A[Session and access]
    S[Assistant]
    X[Pathway executor]
    I[Imports and validation]
    O[Outbox]
  end
  H & W & P & K --> A
  A --> S & X & I
  X --> O
  Server --> DB[(PostgreSQL<br/>SQLite fallback)]
  O --> R[Mock host receiver]
```

| Part | Reads | Produces | Guardrail |
| --- | --- | --- | --- |
| Assistant | Case facts, current passages for the confirmed revision, history, published procedures | answer, clarify or escalate, with citations | No model-specific content until model and revision are confirmed; during a run it only explains |
| Pathway executor | The pinned version's frozen nodes | One transition per allowed answer | Assigned technician only; retry keys; optimistic versions; paused when withdrawn |
| Imports | JSON manifests | Sources and passages, with a job report | Checksummed and idempotent; bad records rejected with reasons |
| Review | Drafts, sources, feedback, audit | Published or withdrawn versions | Valid graph only; author can't publish their own draft |
| Outbox | Approved outcomes | One host record and receipt | Deduplicated by delivery key |

Details, data model and state diagrams: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

![Teo's phone view](docs/screenshots/phone-step.png)

## Commands

| Job | Command | Without make (macOS/Linux; on Windows use `.venv\Scripts\python`) |
| --- | --- | --- |
| Setup | `make setup` | `python3.12 -m venv .venv && .venv/bin/pip install -r requirements.lock` |
| Seed (empty database only) | `make seed` | `.venv/bin/python -m app.cli seed` |
| Start | `make start` | `.venv/bin/python -m app.cli start` |
| Test | `make test` | `.venv/bin/python -m pytest -q` |
| Reset demo data | `make reset` | `.venv/bin/python -m app.cli reset` |
| Re-record the walkthrough video | `make video` | `.venv/bin/python scripts/record_walkthrough.py .walkthrough` then `scripts/encode_walkthrough.py` |
| Check database | `make check` | `.venv/bin/python -m app.cli check` |
| Zero-setup run | `make offline` | set `DATABASE_URL=sqlite:///./fieldwise.db`, then `reset` and `start` |

`make start` seeds an empty database on its first run. The app listens on http://127.0.0.1:8000.

## Configuration

Environment variables, read from your shell or from `.env` (see `.env.example`):

| Variable | Default | Meaning |
| --- | --- | --- |
| `DATABASE_URL` | `sqlite:///<repo>/fieldwise.db` | `postgresql+psycopg://user:pass@host:5432/db` for PostgreSQL |
| `FIELDWISE_HOST` | `127.0.0.1` | Listen address. Only change it if you mean to expose the app |
| `FIELDWISE_PORT` | `8000` | Port |
| `FIELDWISE_SECRET` | a fixed local value | Signs the demo session cookie |
| `FIELDWISE_TEST_DATABASE_URL` | unset | Run the test suite on PostgreSQL |

## HTTP API

All endpoints use the server-side session for identity. Interactive docs: http://127.0.0.1:8000/api/docs.

| Method and path | Who | What |
| --- | --- | --- |
| `POST /demo/login` (form `user_id`) | anyone | Pick a demo identity |
| `GET /api/health` | anyone | Database check |
| `GET /api/cases`, `GET /api/cases/{id}` | tenant members | Case facts and current run |
| `POST /cases/{id}/questions` `{question, expectedVersion?}` | agent, technician, reviewer | `{kind, text, missingFields, citations, eligiblePathways, history}` |
| `POST /cases/{id}/confirmations` `{model, revision, expectedVersion}` | case owner | Attributed observation; corrections pause the active run |
| `POST /cases/{id}/assignment` `{technicianId, expectedVersion}` | case owner | Assign a technician |
| `POST /cases/{id}/runs` `{pathwayId, technicianId?, expectedVersion}` | case owner | Validate applicability and publication, pin the version |
| `GET /api/runs/{id}` | tenant members | Current step, allowed answers, citation, version |
| `POST /runs/{id}/responses` `{stepId, answer, expectedVersion, retryKey}` | assigned technician | `{runId, version, status, nextStepId}`; 403, 409, 422 as documented |
| `POST /runs/{id}/feedback` `{stepId, helpful, comment}` | assigned technician | Step feedback |
| `POST /cases/{id}/outcomes` `{verification, actionTaken, expectedVersion}` | assigned technician | Resolved closure; 409 if premature |
| `GET /cases/{id}/host-update` | tenant members | Preview of the host summary |
| `POST /cases/{id}/host-update/approve` | case owner | Enqueue once in the outbox |
| `POST /deliveries/{key}/send` | agent | Deliver or retry; same receipt if already delivered |
| `POST /host/failure` `{failNext}` | agent | Simulate one host outage |
| `GET /api/host/records` | tenant members | What the mock host received |
| `POST /imports`, `GET /imports/{id}` | author | Import a manifest; job report |
| `GET /search?q=` | tenant members | Current passages in your tenant only |
| `POST /pathways/{id}/drafts` `{definition}` | author | Save a draft and get validation errors |
| `POST /pathways/{id}/versions/{v}/publish` | reviewer (not the author) | Publish an immutable version |
| `POST /pathways/{id}/versions/{v}/withdraw` | reviewer | Withdraw and pause active runs |
| `POST /sources/{id}/withdraw` | reviewer | Withdraw evidence and invalidate dependent guidance |
| `POST /templates/{id}/apply` `{revisionNode}` | author | Fill a template for one revision, or 422 if a slot has no cited page |
| `GET /api/cases/{id}/trace` | reviewer, agent, author | Ordered events, attempted steps, feedback, outcomes |
| `GET /api/hierarchy` | tenant members | Product and asset trees |

Worked example from the build prompt (in `tests/test_4_idempotency.py`): from a fresh B-confirmed run at K1 version 1, `{"stepId":"K1","answer":"green","expectedVersion":1,"retryKey":"demo-1"}` returns version 2, active, next K2. Replaying it returns the same response with exactly one recorded choice; a new key with version 1 returns 409; after a restart K2 is still current.

## Testing

```bash
make test
```

Each test gets its own freshly seeded temporary database and calls the real routes.

| File | Acceptance criterion covered |
| --- | --- |
| `test_1_applicability.py` | 1 · Ambiguous D17 clarifies; B rev 2 gets MB2 p14, PB2 v1 and 1-of-2 history; MA1 and MB1 excluded; D-17 works; superseded-only explains itself |
| `test_2_transitions.py` | 2 · Every edge of K1, K2 and V1, every terminal, reload after each step, premature closure, ordered audit trace |
| `test_3_access.py` | 3 · Agent, unassigned technician and chat can't advance; other tenants are 404 with no titles; SOUTH-ONLY-41 search is empty |
| `test_4_idempotency.py` | 4 · Replays, conflicting writes, retry-key reuse, the worked example and a restart |
| `test_5_versions.py` | 5 · v2 published mid-run stays pinned; withdrawing v1 pauses; withdrawing MB2 removes guidance; correcting applicability pauses |
| `test_6_imports_and_authoring.py` | 6 · Idempotent import, malformed rejection, unreachable and missing-step drafts, failed publication, no self-approval, templates |
| `test_7_closure_and_host.py` | 7 · Verified closure, host failure, restart, retry, exactly one summary; escalation summary; C105 keeps its own history |
| `test_ui_pages.py` | Every screen renders; author and reviewer forms work |
| `test_browser_smoke.py` | Headless Chromium: embedded workspace, intake and handoff, phone step reload, citation, approved closure. Saves `docs/screenshots/` |

Results on the latest build: **57 passed, 1 skipped** on SQLite (the skipped test needs PostgreSQL), and **58 passed** on PostgreSQL 16, including true parallel writes. To run on PostgreSQL, see [docs/SETUP_POSTGRES.md](docs/SETUP_POSTGRES.md) step 5.

## Project layout

```
fieldwise/
├── app/
│   ├── main.py            FastAPI app, sessions, error handling
│   ├── api.py             JSON API
│   ├── ui.py              Server-rendered screens and form handlers
│   ├── models.py          Data model (SQLAlchemy)
│   ├── seed.py            Resettable fictional fixtures
│   ├── cli.py             seed, reset, start, check
│   ├── services/
│   │   ├── core.py        Identity, tenant scope, errors, audit
│   │   ├── cases.py       Assistant, applicability, runs, responses, outcomes
│   │   ├── pathways.py    Validation, drafts, publish, withdraw, templates
│   │   └── ops.py         Imports, outbox and mock host, search, trace
│   ├── templates/         Jinja pages
│   └── static/            CSS and favicon
├── samples/               Sample import manifest and JSON schemas
├── tests/                 Acceptance suites and browser smoke test
├── demo/index.html        The guided browser-only demo
├── docs/                  PRD, architecture, setup, troubleshooting, screenshots
├── requirements.txt       Pinned direct dependencies
├── requirements.lock      Full pinned lock
└── Makefile               setup, seed, start, test, reset, check, offline
```

## Security and data handling

- Everything in the repo is synthetic. There are no keys, passwords or personal data.
- Identity comes from a signed server-side session; request bodies never carry it. The picker is a labeled demo feature, not authentication.
- Every write checks role and ownership; every read is tenant-scoped, and other tenants' records return 404 with no title.
- The app binds to 127.0.0.1 by default. `.env` is git-ignored.
- See [SECURITY.md](SECURITY.md) to report a problem.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `Cannot reach the database` | Start PostgreSQL and create the database ([setup](docs/SETUP_POSTGRES.md)), or use `make offline` |
| `Database already has data` | `make reset` |
| Teo's buttons are greyed out | Switch to Teo; only the assigned technician can answer |
| `409 · Run is paused` | A procedure or manual was withdrawn, or the revision was corrected. Start a fresh run |

More in [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md).

## FAQ and known limitations

- **Is there an AI model inside?** Not in v0.1. The assistant uses scripted retrieval over stored passages and response templates. That keeps the demo offline and deterministic; a model could phrase answers later while the executor and gates stay the same.
- **Can it read PDFs?** Not yet. Imports are structured JSON (`samples/import_manifest.json`).
- **Is the sign-in real?** No. The identity picker is a demo stand-in backed by a server-side session.
- **Is the host a real CRM?** No. "Northline Service Desk" is a mock page that embeds the workspace and receives the summary.
- **Offline field use, log diagnosis, photo capture, predictive maintenance** are later milestones (see the PRD).
- **Production readiness** needs the pilot evaluation described in the PRD; this is a working prototype with verified tests.

## Beyond the prototype

- A live CRM or CMMS host (Salesforce Service Cloud, ServiceNow, MaintainX) replacing the mock host page
- Claude or another model phrasing answers over the same cited passages, with the executor unchanged
- An import adapter for existing CMMS procedures and asset records
- PDF ingestion with page and table locators
- Offline execution with a local journal and conflict handling

## License

MIT, see [LICENSE](LICENSE). Built by Hitha Kishore.
