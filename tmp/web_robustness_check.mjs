// Robustness checks for docs/index.html, docs/dashboard.html and the chat assistant, in headless Chrome.
//
// Usage: node tmp/web_robustness_check.mjs <chrome executable> <docs folder> <http base url> <results json>
// The pages are served over HTTP by the caller (tests/test_web_robustness.py); the file:// check opens
// them from <docs folder>. Chrome runs with its own temporary profile and is closed at the end. Each
// check records ok/false plus detail; the caller asserts on the JSON. Nothing in the repository is written.
import { spawn } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

const [chromePath, docsDir, base, outFile] = process.argv.slice(2);
const PORT = 9400 + Math.floor(Math.random() * 400);
const profile = mkdtempSync(join(tmpdir(), "rpca-chrome-"));
const chrome = spawn(chromePath, ["--headless=new", `--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`,
  "--no-first-run", "--no-default-browser-check", "about:blank"], { stdio: "ignore" });
const sleep = ms => new Promise(r => setTimeout(r, ms));

let wsUrl;
for (let i = 0; i < 75 && !wsUrl; i++) {
  await sleep(200);
  try { wsUrl = (await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json()).find(t => t.type === "page")?.webSocketDebuggerUrl; } catch {}
}
if (!wsUrl) { console.error("Chrome did not start"); chrome.kill(); process.exit(2); }
const ws = new WebSocket(wsUrl);
await new Promise(r => ws.addEventListener("open", r));
let id = 0; const pending = new Map(); let exceptions = []; const requests = [];
let intercept = null;                                   // { pattern, body } for the next navigation
ws.addEventListener("message", e => {
  const m = JSON.parse(e.data);
  if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); return; }
  if (m.method === "Runtime.exceptionThrown") exceptions.push(m.params.exceptionDetails.exception?.description || m.params.exceptionDetails.text);
  if (m.method === "Network.requestWillBeSent") requests.push(m.params.request.url);
  if (m.method === "Fetch.requestPaused") {
    const body = Buffer.from(intercept ? intercept.body : "").toString("base64");
    send("Fetch.fulfillRequest", { requestId: m.params.requestId, responseCode: 200,
      responseHeaders: [{ name: "Content-Type", value: "application/json" }], body });
  }
});
const send = (method, params = {}) => new Promise(r => { const i = ++id; pending.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
const evaluate = async expr => {
  const r = await send("Runtime.evaluate", { expression: expr, awaitPromise: true, returnByValue: true });
  if (r.result?.exceptionDetails) throw new Error(r.result.exceptionDetails.exception?.description || "evaluate failed");
  return r.result?.result?.value;
};
await send("Page.enable"); await send("Runtime.enable"); await send("Network.enable");

const results = [];
const record = (check, page, ok, detail = "") => results.push({ check, page, ok: Boolean(ok), detail: String(detail).slice(0, 400) });

async function open(url, { width = 1280, height = 900, mobile = false, scheme = "light", block = [], fake = null } = {}) {
  exceptions = [];
  await send("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile });
  await send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-color-scheme", value: scheme }] });
  await send("Network.setBlockedURLs", { urls: block });
  if (fake) { intercept = fake; await send("Fetch.enable", { patterns: [{ urlPattern: fake.pattern }] }); }
  else { intercept = null; await send("Fetch.disable"); }
  await send("Page.navigate", { url });
  // Wait until the page has loaded and the chat has started (a slow CDN delays both), then let data load.
  for (let i = 0; i < 75; i++) {
    await sleep(200);
    const ready = await evaluate(`document.readyState === "complete" && !!document.getElementById("cb-panel")`).catch(() => false);
    if (ready) break;
  }
  await sleep(1500);
  await evaluate(`window.__ev = []; document.addEventListener("chatbot:track", e => window.__ev.push(String(e.detail.name))); true`);
}

// Send one chat message through the real form and return what the page shows for it.
const ask = text => evaluate(`(async () => {
  const launcher = document.getElementById("cb-launcher");
  if (document.getElementById("cb-panel").hidden) { launcher.click(); await new Promise(r => setTimeout(r, 300)); }
  const log = document.getElementById("cb-log"); const before = log.children.length; const evBefore = window.__ev.length;
  const input = document.getElementById("cb-input"); input.value = ${JSON.stringify(text)};
  const t0 = performance.now(); document.getElementById("cb-form").requestSubmit(); const ms = performance.now() - t0;
  await new Promise(r => setTimeout(r, 150));
  const added = [...log.children].slice(before);
  return { ms, users: added.filter(n => n.classList.contains("cb-user")).map(n => n.textContent),
           bots: added.filter(n => n.classList.contains("cb-bot")).map(n => n.innerText.replace(/\\s+/g, " ").trim()),
           events: window.__ev.slice(evBefore) };
})()`);

const SAFE_EVENT = /^[a-z][a-z0-9_-]{0,40}(\/[a-z0-9-]{1,40})?$/;
const qa = JSON.parse(readFileSync(join(docsDir, "data", "qa.json"), "utf-8"));
const norm = s => s.replace(/\s+/g, " ").trim();

try {
  for (const page of ["index.html", "dashboard.html"]) {
    for (const scheme of ["light", "dark"]) {
      await open(`${base}/${page}`, { scheme });
      // 1. HTML or script typed into the chat is shown as text and never runs
      const hostile = [`<img src=x onerror="window.__xss=1">`, `<script>window.__xss=2</script>`,
                       `"><svg onload="window.__xss=3">`, `<a href="javascript:window.__xss=4">click</a>`];
      for (const h of hostile) {
        const r = await ask(h);
        const dom = await evaluate(`({ xss: window.__xss === undefined ? null : window.__xss,
          injected: document.querySelectorAll("#cb-log img, #cb-log script, #cb-log svg, #cb-log a[href^='javascript']").length })`);
        record("html_in_chat_is_text", `${page}/${scheme}`, dom.xss === null && dom.injected === 0 && r.users[0] === h,
               JSON.stringify({ dom, shown: r.users[0] }));
      }
      // 2. Very long input: the box caps typing at 200 characters; 5,000 characters set by script still get one reply
      const cap = await evaluate(`document.getElementById("cb-input").maxLength`);
      const long = await ask("why did revenue fall ".repeat(240).slice(0, 5000));
      record("long_input", `${page}/${scheme}`, cap === 200 && long.bots.length === 1 && long.ms < 2000,
             JSON.stringify({ maxLength: cap, replies: long.bots.length, ms: Math.round(long.ms) }));
      // 3. Emoji, Arabic and Urdu: a friendly reply, no error
      for (const text of ["\u{1F600}\u{1F600}\u{1F600}", "لماذا انخفضت الإيرادات؟",
                          "آمدنی کیوں کم ہوئی؟"]) {
        const r = await ask(text);
        record("non_latin_input", `${page}/${scheme}`, r.bots.length === 1 && r.users[0] === text, JSON.stringify(r.bots));
      }
      // 4. Rapid repeated sends: one user bubble and one reply each
      const burst = await evaluate(`(async () => {
        const log = document.getElementById("cb-log"); const before = log.children.length;
        for (let i = 0; i < 25; i++) { document.getElementById("cb-input").value = "hi " + i; document.getElementById("cb-form").requestSubmit(); }
        await new Promise(r => setTimeout(r, 300));
        const added = [...log.children].slice(before);
        return { users: added.filter(n => n.classList.contains("cb-user")).length, bots: added.filter(n => n.classList.contains("cb-bot")).length };
      })()`);
      record("rapid_sends", `${page}/${scheme}`, burst.users === 25 && burst.bots === 25, JSON.stringify(burst));
      // 5. Empty or whitespace: no message and no event
      const empty = await ask("   \t  ");
      record("whitespace_ignored", `${page}/${scheme}`, empty.users.length === 0 && empty.bots.length === 0 && empty.events.length === 0,
             JSON.stringify(empty));
      // 6. Governed answers are shown word for word
      for (const q of qa.questions) {
        const r = await ask(q.question);
        record("governed_answer_unchanged", `${page}/${scheme}`, norm(r.bots.join(" ")).includes(norm(q.answer)) && r.events.includes(`ask/${q.id}`),
               q.id);
      }
      // 7. Analytics never carry typed text: every chat event is a short fixed name
      const names = await evaluate(`window.__ev`);
      const typed = ["xss", "onerror", "script", "لماذا", "revenue fall why"];
      const leak = requests.filter(u => /goatcounter|zgo\.at/.test(u) && typed.some(t => decodeURIComponent(u).toLowerCase().includes(t)));
      record("analytics_no_typed_text", `${page}/${scheme}`, names.every(n => SAFE_EVENT.test(n)) && leak.length === 0,
             JSON.stringify({ unsafe: names.filter(n => !SAFE_EVENT.test(n)), leak }));
      record("no_uncaught_errors", `${page}/${scheme}`, exceptions.length === 0, exceptions.join(" | "));
    }
  }

  // 8. Every store and category filter combination renders without an error
  await open(`${base}/dashboard.html`);
  const combos = await evaluate(`(async () => {
    const s = document.getElementById("f-store"), c = document.getElementById("f-category"), p = document.getElementById("f-period");
    let n = 0;
    for (const period of ["h2", "fy"]) for (const store of [...s.options].map(o => o.value)) for (const cat of [...c.options].map(o => o.value)) {
      p.value = period; s.value = store; c.value = cat; c.dispatchEvent(new Event("change")); n++;
    }
    return { n, notice: !document.getElementById("load-error").hidden, cards: document.querySelectorAll("#kpis .kpi").length };
  })()`);
  record("all_filter_combinations", "dashboard.html", combos.n === 2 * 21 * 9 && !combos.notice && combos.cards > 0 && exceptions.length === 0,
         JSON.stringify({ ...combos, exceptions }));

  // 9. Opened from disk (file://): a clear instruction instead of a blank page
  const fileUrl = page => pathToFileURL(join(docsDir, page)).href;
  await open(fileUrl("dashboard.html"));
  // Browsers differ: some block a page opened from disk from reading its data, some allow it. Either the
  // page works, or it shows the instruction; never a blank page or an error.
  const fromDisk = await evaluate(`({ shown: !document.getElementById("load-error").hidden, text: document.getElementById("load-error").textContent,
    cards: document.querySelectorAll("#kpis .kpi").length })`);
  const diskOk = (fromDisk.cards > 0 && !fromDisk.shown) || (fromDisk.shown && /python -m http\.server/.test(fromDisk.text));
  record("dashboard_from_disk", "dashboard.html", diskOk && exceptions.length === 0,
         JSON.stringify({ outcome: fromDisk.cards > 0 ? "page works from disk" : "instruction shown", ...fromDisk, exceptions }));
  const chatFromDisk = await ask("Why did H2 2025 revenue fall?");
  const chatOk = chatFromDisk.bots.length === 1 && (/could not be loaded/.test(chatFromDisk.bots[0])
                 || norm(chatFromDisk.bots[0]).includes(norm(qa.questions.find(q => q.id === "revenue-fall").answer)));
  record("chat_from_disk", "dashboard.html", chatOk, chatFromDisk.bots[0]);

  // 10. Chart.js blocked or offline: the cards still render and a notice explains the missing charts
  await open(`${base}/dashboard.html`, { block: ["*chart.umd.min.js*"] });
  const noCharts = await evaluate(`({ notice: document.getElementById("charts-error")?.hidden === false, cards: document.querySelectorAll("#kpis .kpi").length,
    findings: document.querySelectorAll("#findings .finding").length, dq: document.querySelectorAll("#dq .kpi").length })`);
  record("chart_library_blocked", "dashboard.html", noCharts.notice && noCharts.cards === 4 && noCharts.findings === 4 && noCharts.dq === 3
         && exceptions.length === 0, JSON.stringify({ ...noCharts, exceptions }));

  // 11. Corrupted or incomplete data files: a message, never a crash or wrong figures
  for (const [label, body, expect] of [["dashboard_json_corrupt", "{not json", /could not be loaded/], ["dashboard_json_incomplete", "{}", /incomplete/]]) {
    await open(`${base}/dashboard.html`, { fake: { pattern: "*data/dashboard.json*", body } });
    const r = await evaluate(`({ shown: !document.getElementById("load-error").hidden, text: document.getElementById("load-error").textContent,
      cards: document.querySelectorAll("#kpis .kpi").length })`);
    record(label, "dashboard.html", r.shown && expect.test(r.text) && r.cards === 0 && exceptions.length === 0, JSON.stringify({ ...r, exceptions }));
  }
  for (const [label, body] of [["qa_json_corrupt", "{not json"], ["qa_json_incomplete", JSON.stringify({ questions: [{ id: 1 }] })]]) {
    await open(`${base}/index.html`, { fake: { pattern: "*data/qa.json*", body } });
    const r = await ask("Why did H2 2025 revenue fall?");
    const hi = await ask("hello");
    const row = await evaluate(`document.getElementById("cb-row").textContent`);
    record(label, "index.html", /could not be loaded/.test(r.bots[0] || "") && hi.bots.length === 1 && /unavailable/.test(row)
           && exceptions.length === 0, JSON.stringify({ reply: r.bots[0], row, exceptions }));
  }

  // 12. Phone width (320 px): no sideways scrolling, and the open chat fits the screen
  for (const page of ["index.html", "dashboard.html"]) {
    await open(`${base}/${page}`, { width: 320, height: 640, mobile: true });
    await evaluate(`document.getElementById("cb-launcher").click(); true`);
    await sleep(400);
    const r = await evaluate(`(() => { const p = document.getElementById("cb-panel").getBoundingClientRect();
      return { scrollW: document.documentElement.scrollWidth, clientW: document.documentElement.clientWidth,
               panelLeft: Math.round(p.left), panelRight: Math.round(p.right), innerW: innerWidth }; })()`);
    record("phone_320px", page, r.scrollW <= r.clientW && r.panelLeft >= 0 && r.panelRight <= r.innerW && exceptions.length === 0,
           JSON.stringify({ ...r, exceptions }));
  }
} catch (err) {
  record("script_error", "-", false, err.stack || String(err));
} finally {
  writeFileSync(outFile, JSON.stringify(results, null, 1));
  ws.close(); chrome.kill();
  await sleep(500);
  try { rmSync(profile, { recursive: true, force: true }); } catch {}
}
console.log(`${results.filter(r => r.ok).length}/${results.length} checks passed`);
