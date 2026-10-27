/* Brightwater Retail Assistant: the floating evidence chat on index.html and dashboard.html.

   Evidence answers are stored in docs/data/qa.json by tmp/export_web_qa.py; this script only looks
   them up. Nothing is generated or calculated in the browser and there is no live AI model.

   Each message is routed deterministically, one reply and one usage event per message:
     1. normalise (lower case, no punctuation); an empty message is ignored, and emoji or punctuation
        alone gets the friendly request to rephrase;
     2. conversational intents: exact phrases and abbreviations ("hii", "thx", "who r u"), then
        one typo per word of four letters or more ("goodbey"), whole message only;
     3. a greeting in front of a question ("Hi, why did revenue fall?") is dropped, so the
        question reaches the evidence; a topic word on its own ("forecast") gets a choice of that
        topic's stored questions; a request for the printable report ("pdf", "download excel")
        gets a short description and links to the PDF and Excel exports in docs/paginated/; a question
        about the database engines or the dbt port ("bigquery", "which database", "dbt", "lineage") gets the
        engines and dbt summary, unless it also matches a stored question ("why did revenue fall in the
        database"): then the governed answer is shown unchanged, with the engine links added;
     4. evidence matching, unchanged: the closest stored question by shared keywords;
     5. if nothing matched: a one-typo correction against qa.json keywords offers "Did you mean
        ...?" chips (never an answer); "be" asks whether bye was meant; a real question about the
        figures gets "no verified figure" and a nearby topic; random text gets a friendly request
        to rephrase; a clear question outside the project (for example the weather) gets a plain
        out-of-scope reply. No reply shows the raw insufficient-evidence text.

   Privacy: the conversation lives in this page only (no storage, nothing uploaded). User text is
   rendered with textContent. Usage events go through analytics.js, which prefixes the page
   (homepage/ or dashboard/); they carry only a fixed event name, an intent name or a stored question
   id, never typed text; there are no session ids and no journey tracking. If GoatCounter is blocked, nothing changes. */
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

  // ---- conversation layer: deterministic and typo tolerant, checked before evidence matching.
  // Lower case, no punctuation, single spaces. Used for the conversational checks only; evidence
  // matching keeps the typed text, so stored answers match exactly as before.
  const normalise = text => String(text).toLowerCase().replace(/[^\p{L}\p{N}\s]/gu, " ").replace(/\s+/g, " ").trim();

  // Whole-message phrases, including common abbreviations and misspellings.
  const CONVO = {
    greeting: ["hi", "hii", "hiii", "hey", "heyy", "heyyy", "helo", "hello", "helloo", "hellooo", "hiya", "howdy", "yo",
               "salam", "salaam", "assalamualaikum", "assalamu alaikum", "as salamu alaikum", "good morning",
               "good afternoon", "good evening", "morning", "hi there", "hello there", "hey there"],
    bye: ["bye", "by", "byy", "byee", "byeee", "bye bye", "goodbye", "goodby", "good bye", "see you", "see ya",
          "see you later", "talk later", "talk to you later", "cya", "farewell", "take care"],
    thanks: ["thanks", "thank you", "thankyou", "thx", "thanx", "thankss", "ty", "tysm", "thanks a lot",
             "thank you so much", "many thanks", "cheers"],
    help: ["help", "hlp", "halp", "help me", "menu", "options"],
    identity: ["who r u", "who are you", "who are u", "what are you", "what r u", "whats your name", "what is your name",
               "are you a bot", "are you ai", "are you an ai", "are you human", "are you real", "are you a real ai"],
    capabilities: ["wat can u do", "what can you do", "what can u do", "wat can you do", "what do you do",
                   "what can i ask", "wat can i ask", "what do you know", "how does this work"],
  };

  // Two or three wordings per intent, used in turn so repeated small talk does not feel canned.
  const REPLIES = {
    greeting: ["Hello! \u{1F44B} Ask me why H2 2025 net revenue fell, or pick a suggestion below.",
               "Hi there. I can walk you through the revenue evidence. What would you like to know?",
               "Hey! Try a suggestion below, or ask about revenue, stores or the forecast."],
    bye: ["Goodbye! \u{1F44B} Thanks for exploring Brightwater Retail Analytics. If you have more questions later, " +
          "I'll be here to help. Have a great day!",
          "Take care. The full analysis is on the dashboard and in the README, and I'm here if you need me.",
          "Bye for now. Come back any time with another question."],
    thanks: ["You're welcome. Ask another question any time.",
             "Happy to help. Is there anything else you'd like to check?",
             "Glad that helped."],
    help: ["Type a question about the revenue fall in your own words, or tap a suggestion below. For example: why did revenue fall?",
           "Just ask, for example which stores drove the decline, or pick one of the suggestions below."],
    capabilities: ["I can explain the H2 2025 revenue fall: the revenue bridge, which stores drove it, Electronics " +
                   "stock-outs, Faulty returns, Home & Kitchen promotions, the 13-week forecast, early warning, data " +
                   "quality and what is still unknown. I can also point you to the printable PDF and Excel report, " +
                   "and explain how the same model runs on SQL Server, DuckDB and BigQuery, and its dbt port.",
                   "I cover the revenue evidence in this project: what changed, where, the likely drivers, the " +
                   "forecast and the data quality behind it. There's also a printable PDF and Excel report, and a " +
                   "note on the three database engines and the dbt port; just ask. Pick a suggestion below to start."],
    identity: [`I'm the ${NAME}, a guided demo in this portfolio project. I answer from stored, pre-checked answers ` +
               "built from the project's governed evidence, not from a live AI.",
               `I'm the ${NAME}. I only answer from this project's verified evidence about the revenue fall; ` +
               "I'm not a general AI."],
    shopping: [SHOPPING_REPLY],
    navigation: ["Here is where to find things:"],
    paginated: ["There's a printable Executive KPI report built in Power BI Report Builder on SQL Server views, with " +
                "cascading Year/Half parameters and a store parameter. It only exports when reconciliation (45/45) " +
                "and KPI checks (38/38) pass."],
    engines: ["The same star schema builds on three engines: SQL Server, DuckDB and Google BigQuery, all passing " +
              "45/45 reconciliation and 38/38 KPI checks with every money total identical. There is also a dbt port " +
              "on DuckDB: 72 models and 90 tests, including all 85 data-quality rules, reconciling to the cent."],
  };
  const turns = {};
  function wording(intent) {
    const list = REPLIES[intent];
    turns[intent] = turns[intent] === undefined ? 0 : turns[intent] + 1;
    return list[turns[intent] % list.length];
  }

  // Damerau-Levenshtein distance (optimal string alignment), enough to spot one slip of the finger.
  function distance(a, b) {
    if (Math.abs(a.length - b.length) > 1) return 2;
    const d = Array.from({ length: a.length + 1 }, (_, i) => [i, ...new Array(b.length).fill(0)]);
    for (let j = 1; j <= b.length; j++) d[0][j] = j;
    for (let i = 1; i <= a.length; i++) {
      for (let j = 1; j <= b.length; j++) {
        d[i][j] = Math.min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
        if (i > 1 && j > 1 && a[i - 1] === b[j - 2] && a[i - 2] === b[j - 1]) d[i][j] = Math.min(d[i][j], d[i - 2][j - 2] + 1);
      }
    }
    return d[a.length][b.length];
  }
  // A typo is one edit, and only in words of four letters or more (short words are too ambiguous).
  const near = (w, v) => w === v || (w.length >= 4 && v.length >= 4 && distance(w, v) <= 1);

  // The whole message as a conversational intent: exact phrase first, then one typo per long word.
  function conversational(norm) {
    for (const [intent, phrases] of Object.entries(CONVO)) if (phrases.includes(norm)) return { intent, typo: false };
    const words = norm.split(" ");
    for (const [intent, phrases] of Object.entries(CONVO)) {
      for (const phrase of phrases) {
        const target = phrase.split(" ");
        if (target.length === words.length && target.every((t, i) => near(words[i], t))) return { intent, typo: true };
      }
    }
    return null;
  }

  // Topics: a short introduction (what the evidence covers, never a figure or a conclusion) and the
  // stored questions on that topic, the first being the topic's main question. A topic word on its own
  // or a broad request ("Tell me about stores") gets the introduction and the questions as chips.
  // Every id is checked against qa.json at load; a topic with none left is skipped.
  const REVENUE_TOPIC = ["Sure! The revenue evidence covers the H2 2025 fall against H2 2024, how much came from " +
                         "fewer transactions, and which stores were behind it. Where would you like to start?",
                         ["revenue-fall", "transactions", "stores"]];
  const PERFORMANCE_TOPIC = ["Here is where to start with Brightwater's H2 2025 performance: the overall revenue " +
                             "fall, the stores behind it, and the transactions effect.",
                             ["revenue-fall", "stores", "transactions"]];
  const FORECAST_TOPIC = ["I can help you understand the 13-week revenue forecast. What would you like to know?",
                          ["forecast", "forecast-model"]];
  const STORE_TOPIC = ["Happy to help with stores. The store evidence covers which stores drove the decline, when " +
                       "the drop started and whether early warning picked it up.", ["stores", "drop-start", "early-warning"]];
  const CATEGORY_TOPIC = ["The evidence looks at Electronics & Tech and Home & Kitchen in detail. Which would you like to explore?",
                          ["stock-outs", "faulty-returns", "hk-promotions"]];
  const ELECTRONICS_TOPIC = ["The Electronics & Tech evidence covers full-week stock-outs and the rise in Faulty returns.",
                             ["stock-outs", "faulty-returns"]];
  const TOPICS = {
    sales: REVENUE_TOPIC, revenue: REVENUE_TOPIC, decline: REVENUE_TOPIC, "revenue fall": REVENUE_TOPIC,
    "revenue decline": REVENUE_TOPIC, "sales performance": REVENUE_TOPIC, "revenue performance": REVENUE_TOPIC,
    performance: PERFORMANCE_TOPIC, results: PERFORMANCE_TOPIC, numbers: PERFORMANCE_TOPIC,
    transactions: ["Sure. Would you like to see how much of the fall came from fewer transactions?", ["transactions", "revenue-fall"]],
    forecast: FORECAST_TOPIC, forecasts: FORECAST_TOPIC, outlook: FORECAST_TOPIC,
    store: STORE_TOPIC, stores: STORE_TOPIC, "store performance": STORE_TOPIC, "stores performance": STORE_TOPIC,
    category: CATEGORY_TOPIC, categories: CATEGORY_TOPIC, "category performance": CATEGORY_TOPIC,
    electronics: ELECTRONICS_TOPIC, "electronics and tech": ELECTRONICS_TOPIC, "electronics tech": ELECTRONICS_TOPIC,
    promotions: ["Here is what the evidence says about promotions:", ["hk-promotions"]],
    "home and kitchen": ["Here is what the evidence says about Home & Kitchen:", ["hk-promotions"]],
    returns: ["Here is what the evidence says about returns:", ["faulty-returns"]],
    stockouts: ["Here is what the evidence says about stock-outs:", ["stock-outs"]],
    "data quality": ["The data-quality evidence covers the checks run at load and during monitoring.", ["data-quality"]],
    "early warning": ["The early-warning evidence covers which alerts fired and when.", ["early-warning", "drop-start"]],
  };
  TOPICS.transaction = TOPICS.transactions; TOPICS.promotion = TOPICS.promotions;
  TOPICS["stock outs"] = TOPICS.stockouts; TOPICS.return = TOPICS.returns;
  TOPICS["home kitchen"] = TOPICS["home and kitchen"]; TOPICS.monitoring = TOPICS["early warning"];
  TOPICS["faulty returns"] = TOPICS.returns; TOPICS["the decline"] = REVENUE_TOPIC;

  // Natural requests about a topic: "Tell me about revenue", "Sure, tell me about the revenue",
  // "Can you explain the sales?", "I want to know about stores", "Show me the performance". The
  // request words are removed and what is left must be a known topic; anything else falls through
  // to the normal evidence matching. "What happened to X" asks for the main finding, so it gets the
  // topic's main stored answer; the other phrasings are broad and get the introduction and chips.
  const LEAD_IN = /^(?:(?:sure|ok|okay|yes|yeah|yep|alright|right|great|cool|so|and|well|please|then|hmm)\s+)*/;
  const REQUEST = /^(?:(?:can|could|would|will) you\s+)?(?:please\s+)?(tell me (?:more )?about|tell me more on|explain|walk me through|talk (?:me )?(?:through|about)|show me|give me (?:an overview of|a summary of|an update on)|i (?:want|would like|d like) to (?:know|learn|hear) (?:more )?about|what about|how about|info(?:rmation)? (?:on|about)|more (?:on|about)|overview of|summary of|summari[sz]e|what happened (?:to|with)|what s (?:going on|happening) with|what is (?:going on|happening) with)\s+/;
  const FILLER = /^(?:(?:the|our|your|its|brightwater s|brightwater|overall|total|recent|current)\s+)*/;
  function topicRequest(norm) {
    const m = norm.replace(LEAD_IN, "").match(REQUEST);
    if (!m) return null;
    const what = norm.replace(LEAD_IN, "").slice(m[0].length).replace(FILLER, "").replace(/\s+(please|then|now|for me)$/, "").trim();
    const topic = TOPICS[what];
    if (!topic || !topic[1].length) return null;
    return { topic, specific: /^what (happened|s|is)/.test(m[1]) };
  }
  // Looks like a question about the figures, so it gets a friendly "no verified figure" reply.
  const ANALYTICAL = /\b(revenue|sales|profits?|margins?|stores?|s\d{2}|transactions?|forecasts?|customers?|footfall|prices?|costs?|categor(y|ies)|products?|returns?|promotions?|stock|turnover|why|how much|how many)\b/;
  const CLOSEST_TOPIC = [
    [/\b(s\d{2}|stores?|footfall|customers?)\b/, "store performance", ["stores", "drop-start", "early-warning"]],
    [/\bforecasts?\b/, "the forecast", ["forecast", "forecast-model"]],
    [/\bpromotions?\b/, "the Home & Kitchen promotions", ["hk-promotions"]],
    [/\breturns?\b/, "the Faulty returns", ["faulty-returns"]],
    [/\bstock\b/, "the Electronics stock-outs", ["stock-outs"]],
    [/.*/, "the revenue fall", ["revenue-fall", "transactions", "stores"]],
  ];
  const AMBIGUOUS = { be: "bye" };
  const QUESTION_START = /^(what|whats|which|who|whom|whose|when|where|why|how|is|are|was|were|do|does|did|can|could|will|would|should|has|have)\b/;
  let VOCAB = new Set();
  // Every word the assistant recognises: conversational phrases, common short words and (at load) qa.json words.
  let KNOWN = new Set([...Object.values(CONVO).flat().flatMap(p => p.split(" ")), ...STOP]);

  // ---- small talk at the start of a message is peeled off in a loop, so "Hi, thanks!" is small talk
  // and "Hi, why did revenue fall?" is a question.
  const SMALL_TALK = [
    ["greeting", /^(hi+|hello+|hey+|hiya|howdy|yo|salam|salaam|as[- ]?sala+m[uo]?\s*alaikum|assalamu?\s*alaikum|good\s+(morning|afternoon|evening|day)|greetings)\b(\s+(there|all|team|assistant|bot))?[\s,!.?]*/i],
    ["thanks", /^(thanks|thank\s+you|thx|ty|cheers|many\s+thanks|much\s+appreciated|appreciate\s+it)\b(\s+(so|very)\s+much)?[\s,!.?]*/i],
    ["bye", /^(bye|goodbye|good\s*bye|see\s+you(\s+later)?|see\s+ya|cya|take\s+care|that'?s\s+all|farewell)\b[\s,!.?]*/i],
  ];
  const SHOPPING = /\b(how much (did|have|do) i (buy|bought|spend|spent|order|ordered)|my (orders?|purchases?|receipts?|account|delivery|refund|basket|loyalty)|did i (buy|order|purchase)|i (bought|ordered|purchased)|do you (sell|stock|deliver|ship)|do you have .* in stock|can i (buy|order|purchase)|where can i buy|(store|shop) (address|addresses|opening hours)|your (address|addresses|shop|opening hours|phone number|email)|addresses|address of|opening hours|price of)\b/i;
  const NAVIGATION = /\b(where (is|are|can i (find|see)|do i find)\b.*\b(charts?|graphs?|dashboard|code|source|repo|repository|readme|github|notebooks?|sql|power ?bi)|(open|show me|take me to|link to|go to)\b.*\b(dashboard|charts|code|repo|repository|readme|github))\b|^\s*(github|repo|repository|readme|source code|dashboard)\s*\??\s*$/i;
  const IDENTITY = /\b(who are you|what are you|what is this (bot|assistant|chat)|are you (a |an )?(bot|robot|ai|human|real|person|chatgpt|gpt|llm|live)|your name|who (made|built|created|wrote) (you|this))\b/i;
  // Requests for the printable report in docs/paginated/. The links are relative because both pages
  // sit in docs/. Questions about the code or the repository stay with the navigation reply. H2 2025,
  // the headline period, comes first; H1 2025 shows the same report run with other parameters.
  const REPORT_FILES = [["Open PDF report", "paginated/Executive_KPI_Summary_H2_2025.pdf", false],
                        ["Download Excel", "paginated/Executive_KPI_Summary_H2_2025.xlsx", true],
                        ["H1 2025 PDF", "paginated/Executive_KPI_Summary_H1_2025.pdf", false],
                        ["H1 2025 Excel", "paginated/Executive_KPI_Summary_H1_2025.xlsx", true]];
  const REPORT_WORDS = ["paginated", "pdf", "excel", "xlsx", "export", "download"];
  const REPORT_PHRASES = [["report", "builder"], ["printable", "report"]];
  // Real words one edit from a trigger ("expert" from "export") are not report requests.
  const REPORT_LOOKALIKES = new Set(["expert", "experts"]);
  const NOT_REPORT = /\b(code|repo|repository|github|readme|source|notebooks?)\b/;
  function wantsReport(norm) {
    if (NOT_REPORT.test(norm)) return false;
    const words = norm.split(" ").filter(w => !REPORT_LOOKALIKES.has(w));
    return words.some(w => REPORT_WORDS.some(t => near(w, t))) ||
      REPORT_PHRASES.some(([a, b]) => words.some((w, i) => i + 1 < words.length && near(w, a) && near(words[i + 1], b)));
  }
  // Questions about where the model runs (SQL Server, DuckDB, BigQuery) and its dbt port. Same whole-word,
  // one-typo matching as the report request; the BigQuery guide is on GitHub because the site serves .md files
  // as plain text, and the dbt docs are the published static site in docs/dbt.
  const ENGINES_DOC = "https://github.com/WaleedBinUmer11624/Retail-Performance-Root-Cause-Analytics/blob/main/docs/bigquery_engine.md";
  const DBT_DOCS = "dbt/";
  const ENGINE_WORDS = ["bigquery", "duckdb", "engine", "engines", "database", "databases", "warehouse", "gcp", "dbt",
                        "lineage"];
  const ENGINE_PHRASES = [["big", "query"], ["sql", "server"], ["google", "cloud"], ["data", "build", "tool"]];
  function wantsEngines(norm) {
    const words = norm.split(" ");
    return words.some(w => ENGINE_WORDS.some(t => near(w, t))) ||
      ENGINE_PHRASES.some(p => words.some((w, i) => i + p.length <= words.length && p.every((t, k) => near(words[i + k], t))));
  }
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

  // ---- analytics: handed to analytics.js, which adds the page prefix and sends it to GoatCounter.
  // Names are fixed event names, intent names or stored question ids; typed text is never included.
  function track(name) {
    try { document.dispatchEvent(new CustomEvent("chatbot:track", { detail: { name } })); }
    catch (err) { /* never affect the page */ }
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
  // A chip for a stored question. kind names the event: chip (suggestion), followup (after an
  // answer) or chatbot_clarification_selected (picked from a clarification).
  function chip(q, kind) {
    const c = node("button", "cb-chip", q.question);
    c.type = "button";
    c.title = q.question;                    // full question on hover when a compact chip is shortened
    c.dataset.id = q.id;
    c.addEventListener("click", () => askStored(q, kind));
    return c;
  }
  // A chip that runs a conversational action instead of a stored question.
  function actionChip(label, action) {
    const c = node("button", "cb-chip", label);
    c.type = "button";
    c.dataset.action = action;
    c.addEventListener("click", () => runAction(label, action));
    return c;
  }
  function chipGroup(ids, labelText, kind = "chip", extra = []) {
    const g = node("div", "cb-followups");
    if (labelText) g.append(node("span", "cb-followups-label", labelText));
    for (const id of ids) {
      const q = QA && QA.questions.find(x => x.id === id);
      if (q) g.append(chip(q, kind));
    }
    for (const c of extra) g.append(c);
    log.append(g);
    return g;
  }

  // ---- answer presentation. Layout only: the stored answer's words, figures, labels and sources are
  // shown exactly as qa.json holds them.
  // EUR amounts and percentages, emphasised in place (text nodes, so the wording is unchanged).
  const FIGURE = /[-+]?EUR\s?\d[\d,]*(?:\.\d+)?|[-+]?\d[\d,]*(?:\.\d+)?%/g;
  function withFigures(text) {
    const p = node("p");
    let last = 0;
    for (const m of text.matchAll(FIGURE)) {
      if (m.index > last) p.append(text.slice(last, m.index));
      p.append(node("strong", "cb-num", m[0]));
      last = m.index + m[0].length;
    }
    if (last < text.length) p.append(text.slice(last));
    return p;
  }
  // Short paragraphs: the opening sentence on its own, then two sentences at a time. The text is only
  // split where a sentence ends, so joining the paragraphs with a space gives back the stored answer.
  function paragraphs(text) {
    const sentences = text.split(/(?<=[.!?]) (?=[A-Z])/);
    const groups = [sentences.slice(0, 1)];
    for (let i = 1; i < sentences.length; i += 2) groups.push(sentences.slice(i, i + 2));
    return groups.map(g => g.join(" "));
  }

  function answer(q, typed) {
    const b = node("div", "cb-msg cb-bot cb-answer");
    if (typed !== undefined) b.append(node("p", "cb-match", `Closest stored question: ${q.question}`));
    const evidence = node("p", "cb-evidence");
    evidence.append(node("span", "cb-evidence-label", "Evidence level"),
                    node("span", `cb-tag ${TAG[q.governed_label] || "fact"}`, q.governed_label),
                    node("span", "cb-strength", q.evidence_strength === null
                      ? `Strength: ${q.strength} (forecasts are capped at moderate)`
                      : `Strength: ${q.strength} (governed score ${q.evidence_strength} of 3)`));
    const body = node("div", "cb-body");
    for (const para of paragraphs(q.answer)) body.append(withFigures(para));
    const sources = node("div", "cb-sources");
    const list = node("ul");
    for (const s of q.sources) {
      const li = node("li");
      li.append(node("code", "", s.file));
      list.append(li);
    }
    sources.append(node("p", "cb-sources-label", "Sources"), list, node("p", "cb-muted", QA.meta.label));
    b.append(evidence, body, sources);
    log.append(b);
    const next = (FOLLOWUPS[q.id] || []).slice(0, 3);
    if (next.length) chipGroup(next, "Related questions", "followup");
  }

  // A stored question chosen from a chip: the question as the user's bubble, then its answer.
  function askStored(q, kind) {
    const u = userSays(q.question);
    answer(q);
    track(`${kind}/${q.id}`);
    scrollToMessage(u);
  }

  // Links to the engine guide and the dbt docs, styled as chips; they open in a new tab.
  function engineLinks() {
    chipGroup([], "", "chip", [["How it was ported", ENGINES_DOC], ["dbt docs and lineage", DBT_DOCS]].map(([label, href]) => {
      const a = node("a", "cb-chip", label);
      a.href = href;
      a.target = "_blank";
      a.rel = "noopener";                    // the new tab gets no handle back to this page
      a.style.textDecoration = "none";
      return a;
    }));
  }

  // ---- conversational replies (one event each)
  function converse(intent, typo) {
    const text = wording(intent);
    if (intent === "identity") {
      botSays([text, node("p", "cb-muted", DISCLAIMER)]);
    } else if (intent === "navigation") {
      const list = node("ul");
      for (const [label, href] of [["Interactive dashboard (charts)", "dashboard.html"],
                                   ["README (method and results)", `${REPO}#readme`], ["Code repository on GitHub", REPO]]) {
        const li = node("li");
        const a = node("a", "", label);
        a.href = href;
        li.append(a);
        list.append(li);
      }
      botSays([text, list]);
    } else if (intent === "paginated") {
      // Links styled as chips, so the files open or download directly instead of starting another turn.
      botSays([text]);
      chipGroup([], "", "chip", REPORT_FILES.map(([label, href, download]) => {
        const a = node("a", "cb-chip", label);
        a.href = href;
        if (download) a.setAttribute("download", "");
        a.style.textDecoration = "none";
        return a;
      }));
    } else if (intent === "engines") {
      botSays([text]);
      engineLinks();
    } else {
      botSays([text]);
    }
    track(`${typo ? "chatbot_typo_recognised" : "chatbot_conversational_response"}/${intent}`);
  }

  // Clarification chips that are not stored questions: confirming "bye", asking to rephrase, or
  // asking what the assistant can do. The chip label becomes the user's bubble.
  function runAction(label, action) {
    const u = userSays(label);
    if (action === "bye") botSays([wording("bye")]);
    else if (action === "capabilities") botSays([wording("capabilities")]);
    else botSays(["No problem. Could you rephrase your question? For example: why did revenue fall?"]);
    track(`chatbot_clarification_selected/${action}`);
    scrollToMessage(u);
  }

  // "Did you mean revenue?": suggest the corrected word with the stored questions it finds. The
  // question is never answered on the visitor's behalf.
  function didYouMean(fix) {
    const words = fix.corrections.map(([, to]) => `'${to}'`);
    botSays([`Did you mean ${words.join(" and ")}? Here is what I can show you:`]);
    const folded = fix.corrections.flatMap(([, to]) => tokens(to));
    const topic = TOPICS[fix.corrections[0][1]];
    const ids = [...new Set([fix.question.id, ...(topic ? topic[1] : []),
                             ...QA.questions.filter(q => folded.some(t => q._keys.has(t))).map(q => q.id)])].slice(0, 3);
    chipGroup(ids, "", "chatbot_clarification_selected");
    track(`chatbot_typo_recognised/${fix.question.id}`);
  }

  function clarifyTopic(topic) {
    botSays([topic[0]]);
    chipGroup(topic[1], "", "chatbot_clarification_selected");
    track("chatbot_clarification_requested/topic");
  }

  function askBye(word) {
    botSays([`I'm not quite sure what you meant by '${word}'.`,
             "Did you mean 'bye', or were you trying to ask something else?"]);
    chipGroup([], "", "chip", [actionChip("Yes, goodbye", "bye"), actionChip("No, something else", "rephrase")]);
    track("chatbot_clarification_requested/bye");
  }

  // Gibberish: no word is a known conversational word, a qa.json word, or one typo from either.
  function isGibberish(norm) {
    return norm.split(" ").every(w => !KNOWN.has(w) && !(w.length >= 4 && [...KNOWN].some(k => k.length >= 4 && distance(w, k) <= 1)));
  }
  const PROJECT_SUGGESTIONS = ["revenue-fall", "stores", "forecast"];
  function gibberish() {
    botSays(["Sorry, I didn't quite understand your message. I'm here to help you explore the Brightwater Retail " +
             "Analytics project. Would you like to ask about revenue, stores, transactions or the forecast?"]);
    chipGroup(PROJECT_SUGGESTIONS, "", "chatbot_clarification_selected", [actionChip("What can you help me with?", "capabilities")]);
    track("chatbot_clarification_requested/gibberish");
  }
  // Real words, but nothing to match and not a question.
  function unclear() {
    botSays(["Sorry, I didn't quite understand that. Could you rephrase, or pick a suggestion below? I'm happy to help!"]);
    chipGroup(PROJECT_SUGGESTIONS, "", "chatbot_clarification_selected", [actionChip("What can you help me with?", "capabilities")]);
    track("chatbot_clarification_requested/unclear");
  }

  // A real question about the figures that no stored answer covers. Internally this is still the
  // insufficient-evidence outcome (marked on the bubble and counted as chatbot_unsupported_question),
  // but the visitor gets a plain explanation and a nearby topic, never a made-up figure.
  function unsupported(norm) {
    const [, topic, ids] = CLOSEST_TOPIC.find(([re]) => re.test(norm));
    const b = botSays([`I can help with ${topic}, but I don't have a verified figure for that specific question ` +
                       "in the available project data.", `Would you like to explore ${topic} instead?`]);
    b.dataset.classification = "insufficient_evidence";
    chipGroup(ids, "", "chip");
    track("chatbot_unsupported_question");
  }

  // A clear question outside the project (for example the weather): a plain out-of-scope reply and
  // three suggestions. Internally it is still the insufficient-evidence outcome.
  function refuse() {
    const b = botSays(["That's outside what I can help with. I only answer questions about the Brightwater Retail " +
                       "analysis, like why revenue fell, which stores drove it, or the forecast."]);
    b.dataset.classification = "insufficient_evidence";
    chipGroup(REFUSAL_SUGGESTIONS);
    track("chatbot_unsupported_question");
  }

  // Correct single long words that are one edit away from a qa.json keyword, then retry the
  // evidence match. Only used to suggest, never to answer.
  function typoFix(norm) {
    const corrections = [];
    const words = norm.split(" ").map(w => {
      if (w.length < 4 || STOP.has(w) || VOCAB.has(w)) return w;
      const hits = [...VOCAB].filter(v => v.length >= 4 && distance(w, v) === 1);
      if (hits.length !== 1) return w;           // none, or more than one candidate: do not guess
      corrections.push([w, hits[0]]);
      return hits[0];
    });
    if (!corrections.length) return null;
    const question = closest(words.join(" "));
    return question ? { corrections, question } : null;
  }

  // Looks like a sentence-length question, as opposed to random characters.
  function looksLikeQuestion(norm, raw) {
    const words = norm.split(" ");
    const wordy = words.filter(w => /^[a-z]{2,12}$/.test(w) && /[aeiouy]/.test(w)).length;
    return words.length >= 3 && wordy / words.length >= 0.75 && (QUESTION_START.test(norm) || /\?\s*$/.test(raw));
  }

  // ---- routing: one bot reply and one event per message
  function respond(raw, norm) {
    // conversational, whole message: exact phrase, abbreviation or one-typo match
    let c = conversational(norm);
    if (c) return converse(c.intent, c.typo);
    // a greeting or thanks in front of something else: drop it and route the rest
    const { found, rest } = peel(raw);
    const body = found.length ? rest : raw;
    const bodyNorm = normalise(body);
    if (!bodyNorm) return converse(found.includes("bye") ? "bye" : found.includes("thanks") ? "thanks" : "greeting");
    if (found.length) {
      c = conversational(bodyNorm);
      if (c) return converse(c.intent, c.typo);
    }
    if (SHOPPING.test(body)) return converse("shopping");
    if (NAVIGATION.test(body)) return converse("navigation");
    if (IDENTITY.test(body)) return converse("identity");
    if (wantsReport(bodyNorm)) return converse("paginated");
    if (wantsEngines(bodyNorm)) {
      // A message that also matches a stored question ("dbt revenue fall", "why did revenue fall in the database")
      // gets that governed answer, unchanged, with the engine links added. The engines summary alone is for
      // messages that match no stored question.
      const q = QA && closest(body);
      if (q) {
        answer(q, raw);
        engineLinks();
        return track(`ask/${q.id}`);
      }
      return converse("engines");
    }
    if (!QA) {
      botSays(["The stored answers could not be loaded, so I can't answer evidence questions right now."]);
      return track("chatbot_unsupported_question");
    }
    // a topic word on its own: offer that topic's stored questions rather than picking one
    const topic = TOPICS[bodyNorm];
    if (topic && topic[1].length) return clarifyTopic(topic);
    // a natural request about a topic: the main answer for "what happened to", otherwise the choices
    const request = topicRequest(bodyNorm);
    if (request && request.specific) {
      const lead = QA.questions.find(x => x.id === request.topic[1][0]);
      answer(lead, raw);
      return track(`ask/${lead.id}`);
    }
    if (request) return clarifyTopic(request.topic);
    // the evidence match, unchanged
    const q = closest(body);
    if (q) { answer(q, raw); return track(`ask/${q.id}`); }
    if (HELP.test(body)) return converse("capabilities");
    const fix = typoFix(bodyNorm);
    if (fix) return didYouMean(fix);
    if (AMBIGUOUS[bodyNorm]) return askBye(bodyNorm);
    if (ANALYTICAL.test(bodyNorm) && looksLikeQuestion(bodyNorm, raw)) return unsupported(bodyNorm);
    if (looksLikeQuestion(bodyNorm, raw)) return refuse();
    return isGibberish(bodyNorm) ? gibberish() : unclear();
  }

  function handle(text) {
    const raw = String(text).trim();
    if (!raw) return;                        // empty or whitespace only: no message, no event
    const u = userSays(raw);
    // Emoji or punctuation alone ("?", a thumbs-up) has no words to match; answer it instead of staying silent.
    if (!normalise(raw)) unclear();
    else respond(raw, normalise(raw));
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
      const data = await res.json();
      // A file of the wrong shape is treated like a missing one, so one bad entry cannot break every later message.
      const valid = data && Array.isArray(data.questions) && data.questions.length && data.meta &&
        data.questions.every(q => q && typeof q.id === "string" && typeof q.question === "string" &&
                             typeof q.answer === "string" && Array.isArray(q.keywords) && Array.isArray(q.sources));
      if (!valid) throw new Error("unexpected qa.json format");
      QA = data;
    } catch (err) {
      row.append(node("span", "cb-muted", "Suggestions unavailable: the stored answers could not be loaded."));
      return;
    }
    const ids = new Set(QA.questions.map(q => q.id));
    for (const key of Object.keys(FOLLOWUPS)) FOLLOWUPS[key] = FOLLOWUPS[key].filter(id => ids.has(id));
    for (const topic of new Set(Object.values(TOPICS))) topic[1] = topic[1].filter(id => ids.has(id));
    for (const q of QA.questions) {
      q._keys = new Set([...tokens(q.question), ...tokens(q.keywords.join(" "))]);
      row.append(chip(q, "chip"));
    }
    // Words a typo can be corrected to: the stored questions' own words and keywords (four letters or more).
    VOCAB = new Set(QA.questions.flatMap(q => normalise(`${q.question} ${q.keywords.join(" ")}`).split(" "))
      .filter(w => w.length >= 4 && /^[a-z]+$/.test(w) && !STOP.has(w)));
    KNOWN = new Set([...KNOWN, ...VOCAB, ...QA.questions.flatMap(q => normalise(q.question).split(" "))]);
    updateArrows();
  })();
})();
