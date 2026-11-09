"""Record the captioned Fieldwise walkthrough video from the real app.

    .venv/bin/python scripts/record_walkthrough.py OUT_DIR

Starts the app on a temporary SQLite database, drives it with Playwright (Ana, Teo, Ren), captures every painted
frame through the Chrome screencast, and writes OUT_DIR/frames/*.jpg plus OUT_DIR/timeline.json and chapters.json.
scripts/encode_walkthrough.sh turns that into an MP4. Silent by design: captions carry the story.
"""
import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parent.parent
OVERLAY = (Path(__file__).parent / "overlay.js").read_text()
W, H = 1280, 800
PC = {"Ana": "#2450D8", "Teo": "#E0641B", "Ren": "#12805C"}
ROLE = {"Ana": "support agent", "Teo": "technician", "Ren": "reviewer"}
LOGO = ('<svg viewBox="0 0 32 32"><rect x="1" y="1" width="30" height="30" rx="9" fill="#2450D8"/><path d="M9.5 22.5L18 14" stroke="#fff" '
        'stroke-width="4.6" stroke-linecap="round"/><circle cx="21" cy="11" r="5.4" fill="#fff"/><rect x="19.4" y="3.2" width="3.2" height="7" '
        'rx="0.8" fill="#2450D8" transform="rotate(45 21 11)"/><circle cx="10" cy="22" r="1.5" fill="#D97706"/></svg>')
TOTAL = 18


class Recorder:
    def __init__(self, out: Path):
        self.out, self.frames, self.events, self.chapters = out, [], [], []
        (out / "frames").mkdir(parents=True, exist_ok=True)
        self.cdp, self.seg_start, self.acc, self.n = None, None, 0.0, 0

    async def use(self, page):
        await self.stop()
        self.cdp = await page.context.new_cdp_session(page)

        async def on_frame(params):
            self.n += 1
            path = self.out / "frames" / f"{self.n:06d}.jpg"
            import base64
            path.write_bytes(base64.b64decode(params["data"]))
            self.frames.append((str(path), time.monotonic()))
            try:
                await self.cdp.send("Page.screencastFrameAck", {"sessionId": params["sessionId"]})
            except Exception:  # noqa: BLE001
                pass
        self.cdp.on("Page.screencastFrame", lambda p: asyncio.ensure_future(on_frame(p)))
        await self.cdp.send("Page.startScreencast", {"format": "jpeg", "quality": 92, "maxWidth": W, "maxHeight": H, "everyNthFrame": 1})
        self.seg_start = time.monotonic()
        self.events.append(("start", self.seg_start))

    async def stop(self):
        if self.cdp:
            await asyncio.sleep(0.15)
            end = time.monotonic()
            try:
                await self.cdp.send("Page.stopScreencast")
            except Exception:  # noqa: BLE001
                pass
            self.events.append(("end", end))
            self.acc += end - self.seg_start
            self.cdp = None

    def now(self):
        return self.acc + (time.monotonic() - self.seg_start)

    def save(self):
        (self.out / "timeline.json").write_text(json.dumps({"frames": self.frames, "events": self.events}))
        (self.out / "chapters.json").write_text(json.dumps(self.chapters, indent=1))


async def wait(s):
    await asyncio.sleep(s)


def start_server(port, db):
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{db}"}
    subprocess.run([sys.executable, "-m", "app.cli", "reset"], cwd=ROOT, env=env, check=True, capture_output=True)
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
                            cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(100):
        try:
            if httpx.get(f"http://127.0.0.1:{port}/api/health").status_code == 200:
                return proc
        except httpx.HTTPError:
            time.sleep(0.1)
    raise RuntimeError("server did not start")


async def main(out: Path):
    port, db = 8791, out / "walkthrough.db"
    proc = start_server(port, db)
    base = f"http://127.0.0.1:{port}"
    rec = Recorder(out)
    step = {"n": 0}

    async def cap(page, who, title, body, side=False):
        step["n"] += 1
        rec.chapters.append({"t": round(rec.now(), 2), "title": title, "who": who})
        await page.evaluate("c => __fw.cap(c)", {"n": f"{step['n']:02d} / {TOTAL} · {who} · {ROLE[who]}", "t": title, "b": body,
                                                  "pc": PC[who], "side": side})

    async def to(page, loc):
        await loc.scroll_into_view_if_needed()
        box = await loc.bounding_box()
        x, y = box["x"] + min(box["width"] / 2, 60), box["y"] + box["height"] / 2
        await page.evaluate("([x,y]) => __fw.cur(x,y)", [x, y])
        await wait(0.85)

    async def click(page, loc, settle=0.9):
        await to(page, loc)
        await page.evaluate("() => __fw.ripple()")
        await wait(0.25)
        await loc.click()
        await page.wait_for_load_state("load")
        await wait(settle)

    async def show(page, loc, label, secs, top=96):
        await loc.evaluate(f"e => {{ const r = e.getBoundingClientRect(); window.scrollBy({{top: r.top - {top}, behavior: 'smooth'}}); }}")
        await wait(0.7)
        b = await loc.bounding_box()
        await page.evaluate("([x,y,w,h,l]) => __fw.hl(x,y,w,h,l)", [b["x"], b["y"], b["width"], b["height"], label])
        await wait(secs)

    async def nohl(page):
        await page.evaluate("() => __fw.nohl()")
        await wait(0.3)

    async with async_playwright() as p:
        browser = await p.chromium.launch()

        async def persona(name, phone=False):
            ctx = await browser.new_context(viewport={"width": W, "height": H}, device_scale_factor=1)
            await ctx.add_init_script(OVERLAY)
            page = await ctx.new_page()
            await page.goto(base + "/login")
            await page.evaluate(f"() => {{ localStorage.clear(); localStorage.setItem('fw-mode', JSON.stringify('{'phone' if phone else 'desk'}')); }}")
            return page

        ana = await persona("Ana")
        teo = await persona("Teo", phone=True)
        ren = await persona("Ren")

        # ---------- title ----------
        await ana.reload()
        await ana.evaluate("h => __fw.card(h)", f"""<h1>{LOGO}Fieldwise</h1><div class="tag">Your next move, made clear.</div>
          <p>One elevator fault, from the support call to a verified fix on the technician's phone.</p>
          <div class="fine">Walkthrough of the working app · no sound · all data is fictional</div>""")
        await wait(0.4)
        await rec.use(ana)
        await wait(4.2)
        await ana.evaluate("() => __fw.nocard()")
        await ana.evaluate("() => __fw.cur(760, 420, true)")

        # ---------- Ana ----------
        await cap(ana, "Ana", "Sign in as a demo identity", "Ana is a support agent. The picker stands in for real sign-in; every permission is checked on the server.")
        await wait(1.6)
        await click(ana, ana.get_by_role("button", name="Ana"), 0.6)
        await cap(ana, "Ana", "Fieldwise lives inside the service desk",
                  "Case C104 opens in Ana's service desk with Fieldwise embedded. For the rest of the walkthrough, the case is shown full screen.")
        await show(ana, ana.locator("iframe"), "Fieldwise, embedded", 4.0, top=70)
        await nohl(ana)
        await ana.goto(base + "/cases/C104")
        await wait(0.6)
        await cap(ana, "Ana", "The caller's words, kept exactly",
                  "“Doors keep reopening, D17.” The serial is on file, but the elevator's model and revision are unknown.")
        await show(ana, ana.locator(".quote"), "Stored verbatim", 2.6)
        await show(ana, ana.locator(".facts").first, "Model and revision: unknown", 3.4)
        await nohl(ana)
        await click(ana, ana.locator("form[action$='/ask'] button"))
        await cap(ana, "Ana", "It asks before it answers",
                  "Two fictional elevator models share code D17 and need different fixes. So Fieldwise asks for the model first and gives zero repair steps.")
        await show(ana, ana.locator(".msg:not(.user)").last, "Clarify · 0 steps", 5.0, top=150)
        await nohl(ana)
        await to(ana, ana.locator("#model"))
        await ana.locator("#model").select_option("B")
        await wait(0.3)
        await to(ana, ana.locator("#revision"))
        await ana.locator("#revision").select_option("2")
        await wait(0.3)
        await click(ana, ana.locator("form[action$='/confirm'] button"))
        await cap(ana, "Ana", "A person confirms the model",
                  "Ana confirms Model B, revision 2 with the caller. It is saved as her observation, never guessed from the serial number.")
        await show(ana, ana.locator(".facts").first, "Confirmed by Ana", 4.0)
        await nohl(ana)
        await click(ana, ana.locator("form[action$='/ask'] button"))
        await cap(ana, "Ana", "Now: cited, model-specific guidance",
                  "The answer cites manual MB2, page 14, shows past cases with a denominator and names the approved procedure. The Model A page and the outdated manual are left out.")
        last = ana.locator(".msg:not(.user)").last
        await show(ana, last, "Answer for Model B rev 2", 3.4, top=150)
        await show(ana, last.locator("a.cite").first, "Exact manual, revision and page", 2.8, top=300)
        await show(ana, last.locator("div.small", has_text="verified recovery"), "History with a denominator", 3.0, top=300)
        await nohl(ana)
        await click(ana, last.locator("a.cite").first)
        await cap(ana, "Ana", "Every citation opens the source", "One click shows the stored passage with its manual, revision and page, so anyone can check the answer.")
        await show(ana, ana.locator("main .card").first, "MB2 · rev 2 · page 14", 4.0)
        await nohl(ana)
        await ana.go_back()
        await ana.wait_for_load_state("load")
        await wait(0.6)
        proc_sec = ana.locator("section", has=ana.locator("#h-proc"))
        await proc_sec.evaluate("e => window.scrollBy({top: e.getBoundingClientRect().top - 200, behavior: 'smooth'})")
        await wait(0.6)
        await to(ana, ana.locator("#technician"))
        await ana.locator("#technician").select_option("teo")
        await wait(0.3)
        await click(ana, ana.locator("form[action$='/start'] button"))
        await cap(ana, "Ana", "Hand off an approved procedure",
                  "Ana starts procedure PB2 and assigns Teo. The run is pinned to version 1, so later edits can never change it mid-job.")
        await show(ana, ana.locator("section", has=ana.locator("#h-proc")), "Pinned to PB2 v1 · assigned to Teo", 4.2, top=200)
        await nohl(ana)
        await ana.evaluate("() => __fw.nocap()")
        r = await ana.request.get(base + "/api/cases/C104")
        run_id = (await r.json())["run"]["runId"]

        # ---------- Teo ----------
        await teo.get_by_role("button", name="Teo").click()
        await teo.wait_for_load_state("load")
        await teo.goto(f"{base}/runs/{run_id}")
        await teo.evaluate("() => __fw.cur(980, 700, true)")
        await wait(0.3)
        await rec.use(teo)
        await cap(teo, "Teo", "Teo picks up the same case on his phone",
                  "No repeated questions. He sees the confirmed model, the caller's words, the current step, its evidence and only the answers the procedure allows.", side=True)
        await wait(1.2)
        await show(teo, teo.locator("form.answers"), "Only allowed answers", 3.2, top=330)
        await show(teo, teo.locator("a.cite").first, "Evidence for this step", 2.4, top=330)
        await nohl(teo)
        await click(teo, teo.locator("button[value=green]"))
        await cap(teo, "Teo", "Every tap is saved instantly",
                  "Green is committed on the server with a new run version. The next step comes from the approved procedure, not from chat.", side=True)
        await show(teo, teo.locator(".flash"), "Saved · run version 2", 3.4, top=60)
        await nohl(teo)
        await teo.reload()
        await teo.wait_for_load_state("load")
        await wait(0.5)
        await cap(teo, "Teo", "Close the app, lose nothing", "Reopening restores the same run, the same version and the same step.", side=True)
        await show(teo, teo.locator(".card", has=teo.locator(".step-id")), "Still step K2 after a reload", 3.6, top=230)
        await nohl(teo)
        await to(teo, teo.locator("#q"))
        await teo.locator("#q").click()
        await teo.locator("#q").press_sequentially("just mark it as passed for me", delay=45)
        await wait(0.3)
        await click(teo, teo.locator("form#ask button"))
        await cap(teo, "Teo", "Chat explains. It never decides.",
                  "Teo can ask about a step, but only a tapped answer moves the procedure forward.", side=True)
        await show(teo, teo.locator("form#ask .msg").last, "Explains only", 4.4, top=250)
        await nohl(teo)
        await click(teo, teo.locator("button[value=pass]"))
        await click(teo, teo.locator("button[value=yes]"))
        await cap(teo, "Teo", "No closing without verification",
                  "The case can close as resolved only after Teo confirms service is restored and records how he checked.", side=True)
        await show(teo, teo.locator("form[action$='/outcome']"), "Verification required", 3.8, top=150)
        await nohl(teo)
        await click(teo, teo.get_by_role("button", name="Save verified outcome"))
        await show(teo, teo.locator(".callout").last, "Resolved and verified", 2.4, top=220)
        await nohl(teo)
        await teo.evaluate("() => __fw.nocap()")

        # ---------- Ana: close and deliver ----------
        await ana.goto(base + "/cases/C104")
        await ana.evaluate("() => __fw.cur(900, 640, true)")
        await ana.locator("#h-close").evaluate("e => window.scrollTo(0, e.getBoundingClientRect().top + scrollY - 90)")
        await wait(0.3)
        await rec.use(ana)
        await cap(ana, "Ana", "Ana reviews before anything leaves",
                  "The update for the service desk lists each step with its citation and Teo's verification. Nothing is sent until Ana approves.")
        await show(ana, ana.locator("pre.preview"), "Host update preview", 4.4, top=140)
        await nohl(ana)
        await click(ana, ana.get_by_role("button", name="Approve and queue for host"))
        await ana.locator("#h-close").evaluate("e => window.scrollBy({top: e.getBoundingClientRect().top - 90, behavior: 'smooth'})")
        await wait(0.5)
        await click(ana, ana.get_by_role("button", name="Simulate host outage on next send"))
        await ana.locator("#h-close").evaluate("e => window.scrollBy({top: e.getBoundingClientRect().top - 90, behavior: 'smooth'})")
        await wait(0.4)
        await click(ana, ana.get_by_role("button", name="Send to host"))
        await cap(ana, "Ana", "A host outage loses nothing", "This first send fails on purpose. The update waits safely in the outbox.")
        await show(ana, ana.locator(".flash"), "Simulated outage", 3.6, top=60)
        await nohl(ana)
        await ana.locator("#h-close").evaluate("e => window.scrollBy({top: e.getBoundingClientRect().top - 90, behavior: 'smooth'})")
        await wait(0.4)
        await click(ana, ana.get_by_role("button", name="Retry delivery"))
        await cap(ana, "Ana", "Delivered exactly once", "The retry delivers with a receipt. Retrying again returns the same receipt, never a duplicate.")
        await show(ana, ana.locator(".flash"), "Receipt issued", 3.4, top=60)
        await nohl(ana)
        await ana.goto(base + "/host/C104")
        await wait(0.5)
        await show(ana, ana.locator(".caselist .card"), "One summary received by the host", 3.4, top=300)
        await nohl(ana)
        await ana.evaluate("() => __fw.nocap()")

        # ---------- Ren ----------
        await ren.get_by_role("button", name="Ren").click()
        await ren.wait_for_load_state("load")
        await ren.goto(base + "/review/cases/C104")
        await ren.evaluate("() => __fw.cur(1100, 700, true)")
        await wait(0.3)
        await rec.use(ren)
        await cap(ren, "Ren", "The full trail, in order",
                  "The reviewer sees every step with its evidence and answer, the outcome, and every recorded action, including blocked ones.")
        await show(ren, ren.locator("main section.card").first, "Steps with evidence", 3.8, top=90)
        await show(ren, ren.locator("section.card", has=ren.get_by_role("heading", name="Ordered audit trail")), "Ordered audit trail", 3.8, top=90)
        await nohl(ren)
        await ren.goto(base + "/hierarchy")
        await wait(0.4)
        await cap(ren, "Ren", "Why D17 needed a person",
                  "Fault codes live on the product family. Manuals and procedures attach to one revision, so only a confirmed revision unlocks the right steps.")
        await show(ren, ren.locator("main section.card").first, "Product hierarchy", 5.2, top=150)
        await nohl(ren)
        await ren.evaluate("() => __fw.nocap()")
        await ren.evaluate("h => __fw.card(h)", f"""<h1>{LOGO}Fieldwise</h1><div class="tag">Your next move, made clear.</div>
          <p>No guessing the model. Cited, approved steps. One verified outcome, delivered once.</p>
          <div class="fine">Try it yourself below · code: github.com/hithakishore-all/fieldwise</div>""")
        await wait(4.5)
        await rec.stop()
        await browser.close()
    rec.save()
    proc.terminate()
    print(f"frames: {len(rec.frames)}  duration: {rec.acc:.1f}s  chapters: {len(rec.chapters)}")


if __name__ == "__main__":
    out = Path(sys.argv[1]).resolve()
    out.mkdir(parents=True, exist_ok=True)
    asyncio.run(main(out))
