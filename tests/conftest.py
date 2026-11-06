"""Each test gets a freshly seeded database and real HTTP routes.

Default: a temporary SQLite file. Set FIELDWISE_TEST_DATABASE_URL to run the same suite on PostgreSQL,
e.g. postgresql+psycopg://fieldwise:fieldwise@127.0.0.1:5432/fieldwise_test
"""
import os
import uuid

import pytest
from fastapi.testclient import TestClient

from app import db, seed
from app.main import create_app

PG_URL = os.environ.get("FIELDWISE_TEST_DATABASE_URL")


@pytest.fixture()
def db_url(tmp_path):
    url = PG_URL or f"sqlite:///{tmp_path / 'test.db'}"
    db.configure(url)
    seed.reset(db.engine)
    yield url
    db.engine.dispose()


@pytest.fixture()
def app(db_url):
    return create_app()


@pytest.fixture()
def as_(app):
    """as_('ana') returns a client signed in as that demo identity. Each identity has its own cookie jar."""
    clients = {}

    def make(user_id):
        if user_id not in clients:
            c = TestClient(app)
            r = c.post("/demo/login", data={"user_id": user_id}, follow_redirects=False)
            assert r.status_code == 303
            clients[user_id] = c
        return clients[user_id]
    return make


def key():
    return uuid.uuid4().hex


@pytest.fixture()
def flow(as_):
    """Helpers that drive C104 through the real routes."""
    class Flow:
        def case(self, cid="C104", who="ana"):
            return as_(who).get(f"/api/cases/{cid}").json()

        def confirm(self, model="B", rev="2", cid="C104"):
            v = self.case(cid)["version"]
            r = as_("ana").post(f"/cases/{cid}/confirmations", json={"model": model, "revision": rev, "expectedVersion": v})
            assert r.status_code == 200, r.text
            return r.json()

        def start(self, pathway="PB2", tech="teo", cid="C104"):
            v = self.case(cid)["version"]
            r = as_("ana").post(f"/cases/{cid}/runs", json={"pathwayId": pathway, "technicianId": tech, "expectedVersion": v})
            assert r.status_code == 200, r.text
            return r.json()

        def run(self, run_id, who="teo"):
            return as_(who).get(f"/api/runs/{run_id}").json()

        def answer(self, run_id, answer, who="teo", step=None, version=None, retry=None):
            st = self.run(run_id)
            payload = {"stepId": step or st["currentStepId"], "answer": answer,
                       "expectedVersion": st["version"] if version is None else version, "retryKey": retry or key()}
            return as_(who).post(f"/runs/{run_id}/responses", json=payload)

        def ready_run(self):
            self.confirm()
            return self.start()["runId"]
    return Flow()
