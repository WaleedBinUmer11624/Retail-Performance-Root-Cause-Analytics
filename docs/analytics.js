/* Cookie-free usage events for the project pages, sent through GoatCounter.

   Observability only: this file adds listeners next to the existing ones and never changes page
   behaviour, layout, filters, charts or data. It sends no personal data, sets no cookies and does
   no fingerprinting. Every call is guarded, so if GoatCounter is blocked or not yet loaded each
   event is simply dropped. Page views are counted by GoatCounter's own count.js, not here.

   Events (window.goatcounter.count with event: true):
     filter-period/<value>, filter-store/<value>, filter-category/<value>   user "change" only
     filter-reset
     link/<project|repository|readme|linkedin|github>                       never delays navigation
     section/<headline|explore|evidence|data-quality>                       once per page load
     chart-legend/<chart>                                                    Chart.js legend clicks

   The chat assistant (chatbot.js) sends its own events with the same guards, prefixed with the page
   (homepage/ or dashboard/): chat-open, ask/<id>, chip/<id>, followup/<id>, intent/<name>, no-match.
*/
(function () {
  "use strict";

  var REPO = "https://github.com/WaleedBinUmer11624/Retail-Performance-Root-Cause-Analytics";
  var PAGE = /dashboard\.html$/.test(location.pathname) ? "dashboard" : "index";

  // Lowercase slug for paths: "Electronics & Tech" -> "electronics-tech", "" -> "all".
  function slug(value) {
    var s = String(value || "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
    return s || "all";
  }

  function send(path) {
    try {
      if (window.goatcounter && typeof window.goatcounter.count === "function") {
        window.goatcounter.count({ path: path, title: PAGE + ": " + path, event: true });
      }
    } catch (err) { /* blocked or failed: drop the event, never affect the page */ }
  }

  function safely(fn) {
    try { fn(); } catch (err) { /* a missing element must not stop the other listeners */ }
  }

  // ---- filters: listen alongside the page's own handlers; "change" fires only for user input.
  safely(function () {
    [["f-period", "filter-period"], ["f-store", "filter-store"], ["f-category", "filter-category"]].forEach(function (pair) {
      var el = document.getElementById(pair[0]);
      if (el) el.addEventListener("change", function () { send(pair[1] + "/" + slug(el.value)); });
    });
    var reset = document.getElementById("f-reset");
    if (reset) reset.addEventListener("click", function () { send("filter-reset"); });
  });

  // ---- outbound and cross-page links, identified by URL. No preventDefault: navigation is untouched.
  function linkName(href) {
    if (!href) return null;
    if (/^https:\/\/www\.linkedin\.com\/in\/waleedbinumer\/?$/.test(href)) return "linkedin";
    if (href === REPO + "#readme") return "readme";
    if (href === REPO || href === REPO + "/") return "repository";
    if (/^https:\/\/github\.com\/WaleedBinUmer11624\/?$/.test(href)) return "github";
    if (/(^|\/)index\.html$/.test(href) && PAGE === "dashboard") return "project";
    return null;
  }
  safely(function () {
    document.addEventListener("click", function (e) {
      try {
        var a = e.target && e.target.closest ? e.target.closest("a[href]") : null;
        var name = a ? linkName(a.getAttribute("href")) : null;
        if (name) send("link/" + name);
      } catch (err) { /* ignore */ }
    }, { capture: true, passive: true });
  });

  // ---- sections seen, once each per page load.
  var SECTIONS = PAGE === "dashboard"
    ? { headline: "kpi-title", explore: "charts-title", evidence: "findings-title", "data-quality": "dq-title" }
    : { headline: "headline", explore: "dashboard", evidence: "findings" };
  safely(function () {
    if (!("IntersectionObserver" in window)) return;
    var seen = {};
    var watched = [];  // [element, name]: kept here so the page's DOM is not modified
    var observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        var match = watched.filter(function (w) { return w[0] === entry.target; })[0];
        var name = match ? match[1] : null;
        if (entry.isIntersecting && name && !seen[name]) {
          seen[name] = true;
          send("section/" + name);
          observer.unobserve(entry.target);
        }
      });
    }, { threshold: 0.25 });
    Object.keys(SECTIONS).forEach(function (name) {
      var el = document.getElementById(SECTIONS[name]);
      var target = el ? (el.closest("section") || el) : null;
      if (target) { watched.push([target, name]); observer.observe(target); }
    });
  });

  // ---- Chart.js legend clicks (dashboard only). Read-only hit test against each chart's own
  // legend boxes; Chart.js still handles the click exactly as before. No hover events.
  safely(function () {
    if (PAGE !== "dashboard") return;
    document.addEventListener("click", function (e) {
      try {
        var canvas = e.target;
        if (!canvas || canvas.tagName !== "CANVAS" || !window.Chart || !window.Chart.getChart) return;
        var chart = window.Chart.getChart(canvas);
        var boxes = chart && chart.legend && chart.legend.options && chart.legend.options.display !== false
          ? chart.legend.legendHitBoxes || [] : [];
        var x = e.offsetX, y = e.offsetY;
        for (var i = 0; i < boxes.length; i++) {
          var b = boxes[i];
          if (x >= b.left && x <= b.left + b.width && y >= b.top && y <= b.top + b.height) {
            send("chart-legend/" + slug(canvas.id.replace(/^c-/, "")));
            return;
          }
        }
      } catch (err) { /* ignore */ }
    }, { capture: true, passive: true });
  });
})();
