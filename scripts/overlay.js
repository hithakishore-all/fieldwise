// Walkthrough overlay: caption card, highlight box, and a visible cursor. Injected only while recording.
(() => {
  if (window.top !== window) return;
  const css = `
  #fw-ov{position:fixed;inset:0;pointer-events:none;z-index:2147483000;font-family:"Source Sans 3","Segoe UI",system-ui,sans-serif}
  #fw-hl{position:fixed;border:3px solid #F5B400;border-radius:10px;box-shadow:0 0 0 6px rgba(245,180,0,.22),0 0 24px rgba(245,180,0,.35);
    opacity:0;transition:all .45s cubic-bezier(.4,0,.2,1)}
  #fw-hl.on{opacity:1}
  #fw-hl-l{position:absolute;left:-3px;top:-30px;background:#F5B400;color:#16213E;font:700 13px/1 "IBM Plex Mono",ui-monospace,monospace;
    padding:6px 9px;border-radius:6px 6px 6px 0;white-space:nowrap}
  #fw-hl.below #fw-hl-l{top:auto;bottom:-30px;border-radius:0 6px 6px 6px}
  #fw-cap{position:fixed;left:24px;bottom:24px;width:480px;background:#16213E;color:#E8ECF7;border-radius:12px;padding:16px 18px 18px;
    border-left:6px solid var(--fw-pc,#2450D8);box-shadow:0 18px 40px -12px rgba(5,10,25,.55);opacity:0;transform:translateY(8px);
    transition:opacity .35s, transform .35s}
  #fw-cap.on{opacity:1;transform:none}
  #fw-cap.fw-side{left:40px;top:50%;bottom:auto;width:370px;transform:translateY(-50%)}
  #fw-cap.fw-side.on{transform:translateY(-50%)}
  #fw-cap-n{font:600 12px/1.2 "IBM Plex Mono",ui-monospace,monospace;letter-spacing:.06em;text-transform:uppercase;color:#F5B400;margin-bottom:6px}
  #fw-cap-t{font:700 21px/1.2 "Archivo","Helvetica Neue",Arial,sans-serif;color:#fff;margin-bottom:6px}
  #fw-cap-b{font-size:16px;line-height:1.42;color:#C8D0E6}
  #fw-cur{position:fixed;left:640px;top:420px;width:26px;height:26px;transition:left .75s cubic-bezier(.45,0,.2,1),top .75s cubic-bezier(.45,0,.2,1);filter:drop-shadow(0 2px 3px rgba(0,0,0,.45))}
  #fw-rip{position:fixed;width:44px;height:44px;margin:-22px 0 0 -22px;border-radius:50%;border:3px solid #F5B400;opacity:0}
  #fw-rip.go{animation:fwrip .5s ease-out}
  @keyframes fwrip{0%{opacity:1;transform:scale(.3)}100%{opacity:0;transform:scale(1.4)}}
  body.fw-phone{background:radial-gradient(circle at 70% 30%,#24345e,#0b1222 70%) fixed !important;min-height:100vh}
  body.fw-phone .topbar{display:none}
  body.fw-phone main.wrap{max-width:390px;width:390px;margin:22px 0 22px auto;margin-right:150px;background:var(--bg);border:12px solid #05080f;border-radius:46px;
    min-height:756px;padding:44px 14px 26px;box-shadow:0 30px 60px -20px rgba(0,0,0,.7);position:relative;gap:12px}
  body.fw-phone main.wrap::before{content:"9:41";position:absolute;top:12px;left:30px;font:600 13px/1 system-ui;color:var(--ink)}
  body.fw-phone main.wrap::after{content:"";position:absolute;top:10px;left:50%;width:96px;height:22px;margin-left:-48px;background:#05080f;border-radius:12px}
  body.fw-phone main.wrap > p.small.muted:last-child{display:none}
  body.fw-phone .phone{max-width:100%}
  body.fw-title{background:#0e1630 !important}
  body.fw-title #fw-cur{display:none}
  #fw-cap > div{display:block}
  body.fw-title > *:not(#fw-ov):not(#fw-card){display:none !important}
  #fw-card{position:fixed;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:16px;color:#E8ECF7;text-align:center;
    background:radial-gradient(circle at 50% 35%,#24345e,#0b1222 70%)}
  #fw-card h1{font:700 64px/1 "Archivo","Helvetica Neue",Arial,sans-serif;margin:0;color:#fff;display:flex;align-items:center;gap:18px}
  #fw-card h1 svg{width:64px;height:64px}
  #fw-card .tag{font:500 18px/1.2 "IBM Plex Mono",ui-monospace,monospace;color:#F5B400;letter-spacing:.04em}
  #fw-card p{font-size:22px;max-width:760px;line-height:1.4;margin:0;color:#C8D0E6}
  #fw-card .fine{font:500 13px/1.3 "IBM Plex Mono",ui-monospace,monospace;color:#8f9bbd;text-transform:uppercase;letter-spacing:.08em;margin-top:18px}`;
  const CURSOR = '<svg viewBox="0 0 26 26"><path d="M4 2l17 11.5-7.4 1.4 4.3 8.2-3.3 1.7-4.3-8.3L4.6 21z" fill="#fff" stroke="#111" stroke-width="1.6" stroke-linejoin="round"/></svg>';
  const get = k => { try { return JSON.parse(localStorage.getItem(k) || "null"); } catch (e) { return null; } };
  const put = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} };
  let ready = false;
  function boot() {
    if (ready || !document.body) return;
    ready = true;
    const st = document.createElement("style"); st.textContent = css; document.head.appendChild(st);
    const ov = document.createElement("div"); ov.id = "fw-ov";
    ov.innerHTML = '<div id="fw-hl"><span id="fw-hl-l"></span></div><div id="fw-cap"><div id="fw-cap-n"></div><div id="fw-cap-t"></div><div id="fw-cap-b"></div></div><div id="fw-rip"></div><div id="fw-cur">' + CURSOR + '</div>';
    document.body.appendChild(ov);
    const mode = get("fw-mode");
    if (mode === "phone" && /^\/(runs|evidence)\//.test(location.pathname)) document.body.classList.add("fw-phone");
    const c = get("fw-cap"); if (c) cap(c, true);
    const p = get("fw-cur"); if (p) cur(p.x, p.y, true);
  }
  function cap(c, instant) {
    const el = document.getElementById("fw-cap");
    document.getElementById("fw-cap-n").textContent = c.n || "";
    document.getElementById("fw-cap-t").textContent = c.t || "";
    document.getElementById("fw-cap-b").textContent = c.b || "";
    el.style.setProperty("--fw-pc", c.pc || "#2450D8");
    el.classList.toggle("fw-side", !!c.side);
    if (instant) { el.style.transition = "none"; el.classList.add("on"); el.offsetHeight; el.style.transition = ""; }
    else { el.classList.remove("on"); el.offsetHeight; el.classList.add("on"); }
    put("fw-cap", c);
  }
  function nocap() { document.getElementById("fw-cap").classList.remove("on"); put("fw-cap", null); }
  function cur(x, y, instant) {
    const el = document.getElementById("fw-cur");
    if (instant) { el.style.transition = "none"; }
    el.style.left = x + "px"; el.style.top = y + "px";
    if (instant) { el.offsetHeight; el.style.transition = ""; }
    put("fw-cur", { x, y });
  }
  function ripple() {
    const p = get("fw-cur") || { x: 0, y: 0 }, r = document.getElementById("fw-rip");
    r.style.left = (p.x + 4) + "px"; r.style.top = (p.y + 3) + "px";
    r.classList.remove("go"); r.offsetHeight; r.classList.add("go");
  }
  function hl(x, y, w, h, label) {
    const el = document.getElementById("fw-hl"), pad = 7;
    el.style.left = (x - pad) + "px"; el.style.top = (y - pad) + "px";
    el.style.width = (w + 2 * pad) + "px"; el.style.height = (h + 2 * pad) + "px";
    el.classList.toggle("below", y < 60);
    document.getElementById("fw-hl-l").textContent = label || "";
    document.getElementById("fw-hl-l").style.display = label ? "" : "none";
    el.classList.add("on");
  }
  function nohl() { document.getElementById("fw-hl").classList.remove("on"); }
  function card(html) {
    let c = document.getElementById("fw-card");
    if (!c) { c = document.createElement("div"); c.id = "fw-card"; document.body.appendChild(c); }
    c.innerHTML = html; document.body.classList.add("fw-title");
  }
  function nocard() { const c = document.getElementById("fw-card"); if (c) c.remove(); document.body.classList.remove("fw-title"); }
  window.__fw = { cap, nocap, cur, ripple, hl, nohl, card, nocard };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot); else boot();
})();
