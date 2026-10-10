/* Brightwater Retail Assistant: the floating evidence chat on index.html and dashboard.html.

   Evidence answers are stored in docs/data/qa.json by tmp/export_web_qa.py; this script only looks
   them up. Nothing is generated or calculated in the browser and there is no live AI model.

   Each message goes through two deterministic layers:
     1. conversation intents (greeting, identity, help, thanks, bye, navigation, shopping), matched
        by fixed patterns; a greeting in front of a question ("Hi, why did revenue fall?") is
        peeled off so the question still reaches the evidence;
     2. evidence matching: the typed question is matched to the closest stored question by shared
        keywords (the same rule the dashboard panel used). No match gives the assistant's refusal
        text and three suggestions.

   Privacy: the conversation lives in this page only (no storage, nothing uploaded). User text is
   rendered with textContent. Usage events are aggregate GoatCounter counts prefixed with the page
   (homepage/ or dashboard/) and carry only a fixed event name or a stored question id, never typed
   text; there are no session ids and no journey tracking. If GoatCounter is blocked, nothing changes. */
(function () {
  "use strict";

  const PAGE = /dashboard\.html$/.test(location.pathname) ? "dashboard" : "homepage";
  const REPO = "https://github.com/WaleedBinUmer11624/Retail-Performance-Root-Cause-Analytics";
  const NAME = "Brightwater Retail Assistant";
  const DISCLAIMER = "Brightwater is a fictional retailer; answers come from the project's governed evidence, no live AI.";
  const SHOPPING_REPLY = "This is an analytics demo for a fictional retailer, not a shop; I can't see personal orders.";
  const TAG = { "Observed change": "fact", "Fact": "fact", "Root-cause evidence": "root",
                "Statistical association": "assoc", "Hypothesis": "hyp", "Forecast": "est" };

  // ---- evidence matching (unchanged from the dashboard panel)
  const STOP = new Set(("a an the of to in on for and or is are was were be been being did do does what which who " +
    "how why when where it its this that these those there their they we our you your me my i about show tell " +
    "give from with by at as much many would could should have has had can will any all some more most than " +
    "then so not no please explain").split(" "));
  // Lower case, keep h&k, and fold a plural "s" so "stores" matches "store".
  const tokens = text => (String(text).toLowerCase().match(/[a-z0-9&]+/g) || [])
    .filter(t => !STOP.has(t))
    .map(t => (t.length > 3 && t.endsWith("s") && !t.endsWith("ss")) ? t.slice(0, -1) : t);
  let QA = null;

  function closest(text) {
    const typed = [...new Set(tokens(text))];
    if (!typed.length) return null;
    let best = null;
    for (const q of QA.questions) {
      const hits = typed.filter(t => q._keys.has(t)).length;
      const ratio = hits / typed.length;
      if (!best || hits > best.hits || (hits === best.hits && ratio > best.ratio)) best = { q, hits, ratio };
    }
    return best && best.hits >= Math.min(2, typed.length) && best.ratio >= 0.5 ? best.q : null;
  }

  // ---- follow-ups: only ids that exist in qa.json are ever shown (filtered at load)
  const FOLLOWUPS = {
    "revenue-fall": ["transactions", "stores", "unknowns"],
    "transactions": ["stores", "drop-start", "revenue-fall"],
    "stores": ["drop-start", "early-warning", "unknowns"],
    "drop-start": ["stores", "early-warning"],
    "stock-outs": ["faulty-returns", "hk-promotions", "unknowns"],
    "faulty-returns": ["stock-outs", "unknowns"],
    "hk-promotions": ["stock-outs", "unknowns"],
    "forecast": ["forecast-model", "early-warning"],
    "forecast-model": ["forecast", "data-quality"],
    "early-warning": ["drop-start", "data-quality"],
    "data-quality": ["revenue-fall", "unknowns"],
    "unknowns": ["stores", "hk-promotions", "faulty-returns"],
  };
  const REFUSAL_SUGGESTIONS = ["revenue-fall", "stores", "stock-outs"];

  // ---- conversation intents. Small talk at the start of a message is peeled off in a loop, so
  // "Hi, thanks!" is small talk and "Hi, why did revenue fall?" is a question.
  const SMALL_TALK = [
    ["greeting", /^(hi+|hello+|hey+|hiya|howdy|yo|salam|salaam|as[- ]?sala+m[uo]?\s*alaikum|assalamu?\s*alaikum|good\s+(morning|afternoon|evening|day)|greetings)\b(\s+(there|all|team|assistant|bot))?[\s,!.?]*/i],
    ["thanks", /^(thanks|thank\s+you|thx|ty|cheers|many\s+thanks|much\s+appreciated|appreciate\s+it)\b(\s+(so|very)\s+much)?[\s,!.?]*/i],
    ["bye", /^(bye|goodbye|good\s*bye|see\s+you(\s+later)?|see\s+ya|cya|take\s+care|that'?s\s+all|farewell)\b[\s,!.?]*/i],
  ];
  const SHOPPING = /\b(how much (did|have|do) i (buy|bought|spend|spent|order|ordered)|my (orders?|purchases?|receipts?|account|delivery|refund|basket|loyalty)|did i (buy|order|purchase)|i (bought|ordered|purchased)|do you (sell|stock|deliver|ship)|do you have .* in stock|can i (buy|order|purchase)|where can i buy|(store|shop) (address|addresses|opening hours)|your (address|addresses|shop|opening hours|phone number|email)|addresses|address of|opening hours|price of)\b/i;
  const NAVIGATION = /\b(where (is|are|can i (find|see)|do i find)\b.*\b(charts?|graphs?|dashboard|code|source|repo|repository|readme|github|notebooks?|sql|power ?bi)|(open|show me|take me to|link to|go to)\b.*\b(dashboard|charts|code|repo|repository|readme|github))\b|^\s*(github|repo|repository|readme|source code|dashboard)\s*\??\s*$/i;
  const IDENTITY = /\b(who are you|what are you|what is this (bot|assistant|chat)|are you (a |an )?(bot|robot|ai|human|real|person|chatgpt|gpt|llm|live)|your name|who (made|built|created|wrote) (you|this))\b/i;
  const HELP = /^\s*(help|help me|menu|options)\s*[?!.]*\s*$|\bwhat can (you|i) (do|ask)\b|\bhow (does|do) (this|you) work\b|\bwhat do you (know|cover|do)\b|\bwhat (questions|topics) can\b|\bcapabilit|\bhow do i use\b/i;

  function peel(text) {
    let rest = text.trim();
    const found = [];
    for (let changed = true; changed && rest;) {
      changed = false;
      for (const [name, re] of SMALL_TALK) {
        if (re.test(rest)) { found.push(name); rest = rest.replace(re, "").trim(); changed = true; break; }
      }
    }
    return { found, rest };
  }

  // ---- analytics: aggregate counts only
  function track(name) {
    try {
      if (window.goatcounter && typeof window.goatcounter.count === "function") {
        window.goatcounter.count({ path: `${PAGE}/${name}`, title: `${PAGE}: ${name}`, event: true });
      }
    } catch (err) { /* blocked or failed: drop the event, never affect the page */ }
  }

  // ---- DOM helpers (text only; no innerHTML anywhere)
  function node(tag, cls, text) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  }
  function svg(paths, size) {
    const ns = "http://www.w3.org/2000/svg";
    const s = document.createElementNS(ns, "svg");
    s.setAttribute("viewBox", "0 0 24 24"); s.setAttribute("width", size); s.setAttribute("height", size);
    s.setAttribute("aria-hidden", "true"); s.setAttribute("focusable", "false");
    for (const d of paths) {
      const p = document.createElementNS(ns, "path");
      for (const [k, v] of Object.entries(d)) p.setAttribute(k, v);
      s.append(p);
    }
    return s;
  }
  const ICON_CHAT = [{ fill: "currentColor", d: "M4 4h16a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H9l-4.6 3.5A.9.9 0 0 1 3 20.8V6a2 2 0 0 1 1-2zm3 6.2a1.3 1.3 0 1 0 0 2.6 1.3 1.3 0 0 0 0-2.6zm5 0a1.3 1.3 0 1 0 0 2.6 1.3 1.3 0 0 0 0-2.6zm5 0a1.3 1.3 0 1 0 0 2.6 1.3 1.3 0 0 0 0-2.6z" }];
  const ICON_X = [{ fill: "none", stroke: "currentColor", "stroke-width": "2.2", "stroke-linecap": "round", d: "M6 6l12 12M18 6L6 18" }];
  const ICON_LEFT = [{ fill: "none", stroke: "currentColor", "stroke-width": "2.2", "stroke-linecap": "round", "stroke-linejoin": "round", d: "M15 6l-6 6 6 6" }];
  const ICON_RIGHT = [{ fill: "none", stroke: "currentColor", "stroke-width": "2.2", "stroke-linecap": "round", "stroke-linejoin": "round", d: "M9 6l6 6-6 6" }];

  // ---- build the widget
  const launcher = node("button", "cb-launcher");
  launcher.type = "button";
  launcher.id = "cb-launcher";
  launcher.setAttribute("aria-label", "Ask a revenue question");
  launcher.setAttribute("aria-haspopup", "dialog");
  launcher.setAttribute("aria-expanded", "false");
  launcher.setAttribute("aria-controls", "cb-panel");
  launcher.append(svg(ICON_CHAT, 26));

  const panel = node("div", "cb-panel");
  panel.id = "cb-panel";
  panel.hidden = true;
  panel.setAttribute("role", "dialog");
  panel.setAttribute("aria-modal", "false");
  panel.setAttribute("aria-labelledby", "cb-title");
  panel.setAttribute("aria-describedby", "cb-sub");

  const head = node("div", "cb-head");
  const titles = node("div");
  const title = node("h2", "", NAME); title.id = "cb-title";
  const sub = node("p", "", "Ask about the revenue evidence"); sub.id = "cb-sub";
  titles.append(title, sub);
  const closeBtn = node("button", "cb-close");
  closeBtn.type = "button"; closeBtn.id = "cb-close";
  closeBtn.setAttribute("aria-label", "Close");
  closeBtn.append(svg(ICON_X, 18));
  head.append(titles, closeBtn);

  const log = node("div", "cb-log");
  log.id = "cb-log";
  log.setAttribute("role", "log");
  log.setAttribute("aria-live", "polite");
  log.setAttribute("aria-label", "Conversation");

  const suggest = node("div", "cb-suggest");
  const left = node("button", "cb-arrow"); left.type = "button"; left.setAttribute("aria-label", "Scroll suggestions left"); left.append(svg(ICON_LEFT, 16));
  const row = node("div", "cb-row"); row.id = "cb-row"; row.setAttribute("aria-label", "Suggested questions"); row.setAttribute("role", "group");
  const right = node("button", "cb-arrow"); right.type = "button"; right.setAttribute("aria-label", "Scroll suggestions right"); right.append(svg(ICON_RIGHT, 16));
  suggest.append(left, row, right);

  const form = node("form", "cb-form");
  form.id = "cb-form";
  form.setAttribute("autocomplete", "off");
  const label = node("label", "cb-sr", "Type a question"); label.htmlFor = "cb-input";
  const input = node("input"); input.id = "cb-input"; input.type = "text"; input.maxLength = 200;
  input.placeholder = "Type a question, e.g. why did revenue fall?";
  const send = node("button", "cb-send", "Ask"); send.type = "submit";
  form.append(label, input, send);

  panel.append(head, log, suggest, form);
  document.body.append(launcher, panel);

  // Homepage greeting beside the launcher until the chat is opened or the greeting dismissed.
  let teaser = null;
  if (PAGE === "homepage") {
    teaser = node("div", "cb-teaser");
    teaser.hidden = true;
    const open = node("button", "cb-teaser-open", "Want to know why revenue fell by EUR 731K? Ask me!");
    open.type = "button";
    const dismiss = node("button", "cb-teaser-close");
    dismiss.type = "button"; dismiss.setAttribute("aria-label", "Dismiss greeting");
    dismiss.append(svg(ICON_X, 14));
    teaser.append(open, dismiss);
    document.body.append(teaser);
    open.addEventListener("click", () => openChat());
    dismiss.addEventListener("click", () => hideTeaser());
    setTimeout(() => {
      if (teaser && panel.hidden) { teaser.hidden = false; requestAnimationFrame(() => teaser && teaser.classList.add("cb-show")); }
    }, 1200);
  }
  function hideTeaser() {
    if (!teaser) return;
    const t = teaser; teaser = null;
    t.classList.remove("cb-show");
    setTimeout(() => t.remove(), 200);
  }

  // ---- conversation
  function scrollToMessage(target) {
    if (typeof log.scrollTo === "function") log.scrollTo({ top: Math.max(0, target.offsetTop - 8), behavior: "smooth" });
  }
  function userSays(text) {
    const b = node("div", "cb-msg cb-user");
    b.append(node("p", "", text));
    log.append(b);
    return b;
  }
  function botSays(parts) {
    const b = node("div", "cb-msg cb-bot");
    for (const p of parts) b.append(typeof p === "string" ? node("p", "", p) : p);
    log.append(b);
    return b;
  }
  function chip(q, kind) {
    const c = node("button", "cb-chip", q.question);
    c.type = "button";
    c.dataset.id = q.id;
    c.addEventListener("click", () => askStored(q, kind));
    return c;
  }
  function chipGroup(ids, labelText) {
    const g = node("div", "cb-followups");
    if (labelText) g.append(node("span", "cb-followups-label", labelText));
    for (const id of ids) {
      const q = QA && QA.questions.find(x => x.id === id);
      if (q) g.append(chip(q, labelText === "Related questions" ? "followup" : "chip"));
    }
    log.append(g);
  }

  function answer(q, typed) {
    const parts = [];
    if (typed !== undefined) parts.push(node("p", "cb-match", `Closest stored question: ${q.question}`));
    const badge = node("p");
    badge.append(node("span", `cb-tag ${TAG[q.governed_label] || "fact"}`, q.governed_label));
    badge.append(node("span", "cb-strength", q.evidence_strength === null
      ? `Strength: ${q.strength} (forecasts are capped at moderate)`
      : `Strength: ${q.strength} (governed score ${q.evidence_strength} of 3)`));
    parts.push(badge, q.answer);
    const src = node("p", "cb-src", "Sources: ");
    q.sources.forEach((s, i) => { if (i) src.append(", "); src.append(node("code", "", s.file)); });
    parts.push(src, node("p", "cb-muted", QA.meta.label));
    botSays(parts);
    const next = (FOLLOWUPS[q.id] || []).slice(0, 3);
    if (next.length) chipGroup(next, "Related questions");
  }

  // A stored question chosen from a chip: the question as the user's bubble, then its answer.
  function askStored(q, kind) {
    const u = userSays(q.question);
    answer(q);
    track(`${kind}/${q.id}`);
    scrollToMessage(u);
  }

  function reply(intent) {
    if (intent === "greeting") {
      botSays([`Hello! I'm the ${NAME}. Ask me why H2 2025 net revenue fell, or pick a suggestion below.`]);
    } else if (intent === "identity") {
      botSays([`I'm the ${NAME}, a guided demo in this portfolio project. I answer from stored, pre-checked answers ` +
               "built from the project's governed evidence. There is no live AI model.", node("p", "cb-muted", DISCLAIMER)]);
    } else if (intent === "help") {
      botSays(["I can explain the H2 2025 revenue fall: the revenue bridge, which stores drove it, Electronics " +
               "stock-outs, Faulty returns, Home & Kitchen promotions, the 13-week forecast, early warning, data " +
               "quality and what is still unknown. Type a question or tap a suggestion below."]);
    } else if (intent === "thanks") {
      botSays(["You're welcome. Ask another question any time."]);
    } else if (intent === "bye") {
      botSays(["Thanks for visiting. The full analysis is on the dashboard and in the README."]);
    } else if (intent === "navigation") {
      const list = node("ul");
      for (const [text, href] of [["Interactive dashboard (charts)", "dashboard.html"],
                                  ["README (method and results)", `${REPO}#readme`], ["Code repository on GitHub", REPO]]) {
        const li = node("li");
        const a = node("a", "", text);
        a.href = href;
        li.append(a);
        list.append(li);
      }
      botSays(["Here is where to find things:", list]);
    } else if (intent === "shopping") {
      botSays([SHOPPING_REPLY]);
    }
    track(`intent/${intent}`);
  }

  function refuse() {
    botSays([QA ? QA.meta.refusal : "Insufficient evidence to determine this from the available project data.",
             node("p", "cb-match", "No stored answer covers this question. Try one of these:")]);
    if (QA) chipGroup(REFUSAL_SUGGESTIONS);
    track("no-match");
  }

  // Typed text: conversation intents first, then evidence matching, then the refusal.
  function handle(text) {
    const raw = String(text).trim();
    if (!raw) return;
    const u = userSays(raw);
    const { found, rest } = peel(raw);
    if (rest) {
      if (SHOPPING.test(rest)) reply("shopping");
      else if (NAVIGATION.test(rest)) reply("navigation");
      else if (IDENTITY.test(rest)) reply("identity");
      else {
        const q = QA ? closest(rest) : null;
        if (q) { answer(q, raw); track(`ask/${q.id}`); }
        else if (HELP.test(rest)) reply("help");
        else if (!tokens(rest).length && found.length) reply(found[found.length - 1]);
        else if (!QA) botSays(["The stored answers could not be loaded, so I can't answer evidence questions right now."]);
        else refuse();
      }
    } else {
      reply(found.includes("bye") ? "bye" : found.includes("thanks") ? "thanks" : "greeting");
    }
    scrollToMessage(u);
  }

  // ---- open, close, Escape, focus. The conversation stays in the DOM while the panel is hidden.
  let welcomed = false;
  let closeTimer = null;
  function isOpen() { return !panel.hidden && panel.classList.contains("cb-open"); }
  function openChat() {
    clearTimeout(closeTimer);
    hideTeaser();
    panel.hidden = false;
    requestAnimationFrame(() => panel.classList.add("cb-open"));
    launcher.setAttribute("aria-expanded", "true");
    if (!welcomed) {
      welcomed = true;
      botSays([`Hi, I'm the ${NAME}. I can explain why H2 2025 net revenue fell: the revenue bridge, stores, ` +
               "stock-outs, returns, promotions, the forecast, early warning and data quality.",
               node("p", "cb-muted", DISCLAIMER)]);
    }
    input.focus({ preventScroll: true });
    fitToKeyboard();
    updateArrows();
    track("chat-open");
  }
  function closeChat() {
    panel.classList.remove("cb-open");
    launcher.setAttribute("aria-expanded", "false");
    closeTimer = setTimeout(() => { panel.hidden = true; }, 200);
    launcher.focus({ preventScroll: true });
  }

  // On phones, keep the input above the on-screen keyboard (the visual viewport shrinks, the layout
  // viewport does not on every browser).
  function fitToKeyboard() {
    const vv = window.visualViewport;
    if (!vv) return;
    const keyboard = window.innerHeight - vv.height - vv.offsetTop;
    if (keyboard > 80 && !panel.hidden) {
      panel.style.bottom = `${keyboard + 8}px`;
      panel.style.maxHeight = `${vv.height - 16}px`;
    } else {
      panel.style.bottom = "";
      panel.style.maxHeight = "";
    }
  }
  if (window.visualViewport) window.visualViewport.addEventListener("resize", fitToKeyboard);

  function updateArrows() {
    left.disabled = row.scrollLeft <= 1;
    right.disabled = row.scrollLeft + row.clientWidth >= row.scrollWidth - 1;
  }
  left.addEventListener("click", () => row.scrollBy({ left: -row.clientWidth * 0.7, behavior: "smooth" }));
  right.addEventListener("click", () => row.scrollBy({ left: row.clientWidth * 0.7, behavior: "smooth" }));
  row.addEventListener("scroll", updateArrows, { passive: true });
  window.addEventListener("resize", updateArrows, { passive: true });

  launcher.addEventListener("click", () => (isOpen() ? closeChat() : openChat()));
  closeBtn.addEventListener("click", closeChat);
  panel.addEventListener("keydown", e => { if (e.key === "Escape") { e.preventDefault(); closeChat(); } });
  form.addEventListener("submit", e => {
    e.preventDefault();
    const text = input.value;
    if (!text.trim()) { input.focus(); return; }
    input.value = "";
    handle(text);
  });
  // Any page element marked data-chat-open (e.g. the dashboard's "Ask the evidence" line) opens the chat.
  for (const el of document.querySelectorAll("[data-chat-open]")) el.addEventListener("click", () => openChat());

  // ---- load the stored answers
  (async () => {
    try {
      const res = await fetch("data/qa.json", { cache: "no-cache" });
      if (!res.ok) throw new Error(res.status);
      QA = await res.json();
    } catch (err) {
      row.append(node("span", "cb-muted", "Suggestions unavailable: the stored answers could not be loaded."));
      return;
    }
    const ids = new Set(QA.questions.map(q => q.id));
    for (const key of Object.keys(FOLLOWUPS)) FOLLOWUPS[key] = FOLLOWUPS[key].filter(id => ids.has(id));
    for (const q of QA.questions) {
      q._keys = new Set([...tokens(q.question), ...tokens(q.keywords.join(" "))]);
      row.append(chip(q, "chip"));
    }
    updateArrows();
  })();
})();
