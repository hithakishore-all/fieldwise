"""Browser smoke test: embedded workspace -> intake and handoff -> phone step reload -> citation -> approved closure.

Starts the real server on a free port with its own temporary database. Skips if Playwright or its browser is missing.
Screenshots land in docs/screenshots/ so the README always shows the current build.
"""
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

pw = pytest.importorskip("playwright.sync_api")
ROOT = Path(__file__).resolve().parent.parent
SHOTS = ROOT / "docs" / "screenshots"


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture()
def server(tmp_path):
    url = f"sqlite:///{tmp_path / 'smoke.db'}"
    env = {**os.environ, "DATABASE_URL": url, "FIELDWISE_PORT": str(free_port())}
    subprocess.run([sys.executable, "-m", "app.cli", "reset"], cwd=ROOT, env=env, check=True, capture_output=True)
    port = env["FIELDWISE_PORT"]
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", port],
                            cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            if httpx.get(base + "/api/health").status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.1)
    yield base
    proc.terminate()
    proc.wait(timeout=10)


def login(page, base, name):
    page.goto(base + "/login")
    page.get_by_role("button", name=name).click()


def test_full_journey(server):
    SHOTS.mkdir(parents=True, exist_ok=True)
    with pw.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as e:  # noqa: BLE001
            pytest.skip(f"Chromium not available: {e}")
        desk = browser.new_context(viewport={"width": 1280, "height": 900}).new_page()
        login(desk, server, "Ana")
        assert "/host/C104" in desk.url
        ws = desk.frame_locator("iframe")
        ws.get_by_role("button", name="Ask").click()
        ws.get_by_text("Confirm the model and revision").wait_for()
        ws.locator("#model").select_option("B")
        ws.locator("#revision").select_option("2")
        ws.get_by_role("button", name="Confirm").click()
        ws.get_by_text("Confirmed Model B rev 2").wait_for()
        ws.get_by_role("button", name="Ask").click()
        ws.get_by_role("link", name="MB2 · rev 2 · p14").first.wait_for()
        ws.get_by_text("1 verified recovery in 2 matching cases").first.wait_for()
        ws.locator("#technician").select_option("teo")
        ws.get_by_role("button", name="Start and assign").click()
        ws.get_by_text("and assigned Teo").wait_for()
        desk.reload()  # headless Chrome skips repainting a frame that navigated itself; a reload makes the shot match
        desk.frame_locator("iframe").get_by_text("pinned to PB2 v1").wait_for()
        desk.screenshot(path=str(SHOTS / "service-desk.png"), full_page=True)

        phone_ctx = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True)
        phone = phone_ctx.new_page()
        login(phone, server, "Teo")
        phone.locator("table a.mono").first.click()
        phone.get_by_text("Read indicator B in the simulator.").wait_for()
        phone.screenshot(path=str(SHOTS / "phone-step.png"), full_page=True)
        phone.get_by_role("button", name="Green").click()
        phone.reload()  # same run, same version, step K2 restored from the server
        phone.get_by_text("Step K2").wait_for()
        assert "run version 2" in phone.content()
        phone.get_by_role("link", name="MB2 · rev 2 · p15").click()
        phone.get_by_text("Run the B simulator self-test and record its result.").wait_for()
        assert "page 15" in phone.content()
        phone.go_back()
        phone.get_by_role("button", name="Pass").click()
        phone.get_by_role("button", name="Yes").click()
        phone.get_by_role("button", name="Save verified outcome").click()
        phone.get_by_text("Outcome recorded").first.wait_for()

        desk.reload()
        ws = desk.frame_locator("iframe")
        ws.get_by_role("button", name="Approve and queue for host").click()
        ws.get_by_role("button", name="Simulate host outage on next send").click()
        ws.get_by_role("button", name="Send to host").click()
        ws.get_by_text("Host unavailable").first.wait_for()
        ws.get_by_role("button", name="Retry delivery").click()
        ws.get_by_text("Delivered. Receipt").wait_for()
        desk.reload()
        desk.get_by_text("Received by this host").wait_for()
        assert desk.locator(".caselist .card .mono").count() == 1
        desk.screenshot(path=str(SHOTS / "delivered.png"), full_page=True)
        desk.goto(server + "/cases/C104")
        desk.screenshot(path=str(SHOTS / "workspace.png"), full_page=True)

        review = browser.new_context(viewport={"width": 1280, "height": 900}).new_page()
        login(review, server, "Ren")
        review.goto(server + "/review/cases/C104")
        review.get_by_text("Ordered audit trail").wait_for()
        review.screenshot(path=str(SHOTS / "trace.png"), full_page=True)
        review.goto(server + "/hierarchy")
        review.screenshot(path=str(SHOTS / "hierarchy.png"), full_page=True)
        browser.close()
