"""Page mockups (PNG, 16:9) of the seven dashboard pages, drawn with the real, reconciled numbers.

They are the visual specification for the Power BI build: layout, visual types, titles, evidence labels and
captions. Every number in a card or label is taken from the dashboard number register; every chart series
comes from a DAX measure (evaluated through its Python reference) or a named Phase 6 table.
These are wireframes of the intended report, NOT screenshots of Power BI.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.patches import FancyBboxPatch, Rectangle  # noqa: E402

from .access import read_csv  # noqa: E402
from .reference import Ctx, Model, evaluate  # noqa: E402

BLUE, ORANGE, AQUA, YELLOW = "#2A78D6", "#EB6834", "#1BAF7A", "#EDA100"
RED, GREY, INK, INK2, MUTED, SURF, LINE = "#E34948", "#8F8D87", "#0B0B0B", "#52514E", "#8F8D87", "#FFFFFF", "#E6E4DF"
PANEL = "#F7F6F3"
LEVEL = {"Root-cause evidence": AQUA, "Observed change": BLUE, "Statistical association": YELLOW,
         "Hypothesis": GREY, "Not attributed": "#C9C7C1", "Unresolved": "#52514E"}
PAGES = ["Executive overview", "Store & customer", "Product & inventory", "Returns & quality", "Promotions",
         "Evidence matrix", "Investigation"]


class Page:
    def __init__(self, n: int, title: str, subtitle: str):
        plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9, "axes.spines.top": False,
                             "axes.spines.right": False, "axes.edgecolor": LINE, "xtick.color": INK2,
                             "ytick.color": INK2, "axes.labelcolor": INK2, "axes.grid": True, "grid.color": LINE,
                             "grid.linewidth": 0.6})
        self.fig = plt.figure(figsize=(16, 9), dpi=100, facecolor=SURF)
        f = self.fig
        f.add_artist(Rectangle((0, 0.955), 1, 0.045, transform=f.transFigure, color="#0B2545", zorder=-5))
        f.text(0.012, 0.972, "Brightwater Retail  |  H2 performance and root-cause dashboard", color="white",
               fontsize=10, fontweight="bold", va="center")
        x = 0.37
        for i, p in enumerate(PAGES, start=1):
            f.text(x, 0.972, f"{i} {p}", color="white" if i == n else "#9DB4CF", fontsize=8.2, va="center",
                   fontweight="bold" if i == n else "normal")
            x += 0.016 + 0.0047 * len(p)
        f.text(0.012, 0.925, title, fontsize=17, fontweight="bold", color=INK, va="center")
        f.text(0.012, 0.895, subtitle, fontsize=10, color=INK2, va="center")
        f.text(0.988, 0.012, "Mockup of the Power BI page (built from reconciled data; not a Power BI screenshot)",
               fontsize=7, color=MUTED, ha="right")

    def slicers(self, names, y=0.852):
        x = 0.012
        for n in names:
            w = 0.012 + 0.0062 * len(n) + 0.05
            self.box(x, y, w, 0.026, PANEL, LINE)
            self.fig.text(x + 0.006, y + 0.013, n, fontsize=7.5, color=INK2, va="center")
            self.fig.text(x + w - 0.008, y + 0.013, "v", fontsize=7, color=MUTED, va="center")
            x += w + 0.006

    def box(self, x, y, w, h, fc=SURF, ec=LINE, lw=0.8, r=0.004):
        self.fig.add_artist(FancyBboxPatch((x, y), w, h, boxstyle=f"round,pad=0,rounding_size={r}",
                                           transform=self.fig.transFigure, fc=fc, ec=ec, lw=lw, zorder=-5))

    def tag(self, x, y, text, colour, fs=7):
        t = self.fig.text(x, y, f" {text} ", fontsize=fs, color=INK, va="center",
                          bbox=dict(boxstyle="round,pad=0.25", fc=colour, ec="none", alpha=0.28))
        return t

    def card(self, x, y, w, h, title, value, sub="", tag=None, tagc=BLUE, vcol=INK):
        self.box(x, y, w, h)
        self.fig.text(x + 0.008, y + h - 0.02, title, fontsize=8, color=INK2)
        self.fig.text(x + 0.008, y + h * 0.42, value, fontsize=17, fontweight="bold", color=vcol, va="center")
        if sub:
            self.fig.text(x + 0.008, y + 0.016, sub, fontsize=7.5, color=INK2, va="center")
        if tag:
            self.tag(x + w - 0.012 - 0.0047 * len(tag), y + 0.016, tag, tagc, 6.3)

    def panel(self, x, y, w, h, title, note=None, bottom=0.045, left=0.04):
        self.box(x, y, w, h)
        self.fig.text(x + 0.008, y + h - 0.02, title, fontsize=9.5, fontweight="bold", color=INK)
        if note:
            self.fig.text(x + 0.008, y + h - 0.042, note, fontsize=7.3, color=INK2)
        return self.fig.add_axes([x + left, y + bottom, w - left - 0.015, h - 0.065 - bottom])

    def text_panel(self, x, y, w, h, title, lines, fc=PANEL, ec=LINE, title_col=INK, fs=8):
        self.box(x, y, w, h, fc, ec, lw=1.2)
        self.fig.text(x + 0.008, y + h - 0.022, title, fontsize=9.5, fontweight="bold", color=title_col)
        yy = y + h - 0.05
        for ln in lines:
            self.fig.text(x + 0.01, yy, ln, fontsize=fs, color=INK2, va="top")
            yy -= 0.026

    def save(self, path: Path):
        self.fig.savefig(path, facecolor=SURF)
        plt.close(self.fig)


def _v(reg, rid):
    return reg.set_index("id").loc[rid, "display"]


def _style(ax):
    ax.tick_params(labelsize=7.5)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(LINE)


def weekly(M: Model, measure: str, year: int, extra: dict | None = None) -> pd.Series:
    out = {}
    for w in range(27, 53):
        f = {"Date": {"retail_year": year, "retail_week": w}}
        for k, v in (extra or {}).items():
            f.setdefault(k, {}).update(v)
        out[w] = evaluate(M, measure, Ctx(f))
    return pd.Series(out)


def extracts_attr(cfg):
    from .extracts import _attribution
    return list(_attribution(cfg)["waterfall_label"])


def page1(M, reg, cfg, out):
    P = Page(1, "H2 2025 Net Revenue Decline", f"Net revenue {_v(reg, 'P1-02')} to {_v(reg, 'P1-01')}  "
             f"({_v(reg, 'P1-03')}, {_v(reg, 'P1-04')})   |   H2 2025 vs H2 2024, retail weeks 27-52, week-aligned")
    P.slicers(["Period: H2 2025", "Region: All", "Store format: All", "Store: All", "Category: All"])
    cards = [("Net Revenue", _v(reg, "P1-01"), f"PY {_v(reg, 'P1-02')}"),
             ("YoY %", _v(reg, "P1-04"), "vs H2 2024"), ("Revenue change", _v(reg, "P1-03"), "-€731,270.50 exact"),
             ("Gross Margin", _v(reg, "P1-05"), f"GM% {_v(reg, 'P1-07')} (PY {_v(reg, 'P1-08')})"),
             ("Gross Margin change", _v(reg, "P1-06"), "vs H2 2024"),
             ("Transactions", _v(reg, "P1-09"), "receipts"),
             ("Transaction change", _v(reg, "P1-10"), _v(reg, "P1-11")),
             ("Returns", _v(reg, "P1-12"), "refund value"),
             ("Return Rate", _v(reg, "P1-13"), f"PY {_v(reg, 'P1-14')}")]
    w = (0.976 - 8 * 0.006) / 9
    for i, (t, v, s) in enumerate(cards):
        neg = v.startswith("-")
        P.card(0.012 + i * (w + 0.006), 0.735, w, 0.1, t, v, s, None, BLUE, RED if neg else INK)
    P.fig.text(0.988, 0.842, "All KPI cards: FACT (DAX measures on the governed model)", fontsize=7, color=INK2, ha="right")
    # weekly trend
    ax = P.panel(0.012, 0.06, 0.43, 0.655, "When: weekly net revenue, H2 2025 vs H2 2024",
                 "DAX [Net Revenue] and [Net Revenue PY] by Date[retail_week]. FACT.")
    cy, py = weekly(M, "Net Revenue", 2025), weekly(M, "Net Revenue PY", 2025)
    ax.plot(py.index, py / 1e3, color=GREY, lw=2, label="H2 2024")
    ax.plot(cy.index, cy / 1e3, color=BLUE, lw=2.2, label="H2 2025")
    ax.axvline(29, color=INK2, lw=0.8, ls="--")
    ax.text(29.3, 20, "S03-S05 step, mid-July", fontsize=7, color=INK2, va="bottom")
    ax.set_ylim(0, max(cy.max(), py.max()) / 1e3 * 1.08)
    ax.set_ylabel("€ thousand per week", fontsize=8)
    ax.set_xlabel("Retail week", fontsize=8)
    ax.legend(fontsize=7.5, frameon=False, loc="upper left")
    _style(ax)
    # waterfall
    at = read_csv("reports/phase6/driver_attribution.csv", cfg)
    ids = cfg["powerbi"]["attribution_drivers"]
    ev = read_csv("reports/phase6/root_cause_evidence_matrix.csv", cfg).set_index("driver_id")
    ax = P.panel(0.455, 0.2, 0.533, 0.515, "What drove the decline: exclusive driver attribution (sums to -€731,270)",
                 "Phase 6 validated result; not affected by slicers. Colour = evidence level (labelled below); "
                 "hatched = ESTIMATE, solid = measured; the class is also in each label.", bottom=0.1)
    wl = extracts_attr(cfg)
    labels = ["\n".join(_wrap(x, 17)) for x in wl]
    run = 0.0
    for i, (d, r) in enumerate(zip(ids, at.itertuples())):
        lvl = "Not attributed" if d == "D09" else ev.loc[d, "evidence_level"]
        ax.bar(i, r.amount_eur / 1e3, bottom=run / 1e3, color=LEVEL[lvl], width=0.62,
               hatch=None if d in ("D05", "D09") else "///", edgecolor="white", lw=0.5)
        ax.text(i, (run + r.amount_eur) / 1e3 - 12, f"{_v(reg, f'P1-2{i}a')}\n{_v(reg, f'P1-2{i}b')}", ha="center",
                va="top", fontsize=7.5, color=INK)
        run += r.amount_eur
    ax.bar(5, run / 1e3, color="#0B2545", width=0.62)
    ax.text(5, run / 1e3 - 12, "-€731,270\n100%", ha="center", va="top", fontsize=7.5, color=INK)
    ax.set_xticks(range(6), labels + ["Total H2\nchange [FACT]"], fontsize=6.4)
    ax.set_ylim(run / 1e3 * 1.22, 25)
    ax.set_ylabel("€ thousand", fontsize=8)
    ax.axhline(0, color=INK2, lw=0.8)
    _style(ax)
    P.fig.text(0.463, 0.645, "The €397,778 is an ESTIMATE of an observed change (vs matched controls); its cause is "
               "UNRESOLVED.", fontsize=7.3, color=RED)
    # legend + bridge strip
    P.box(0.455, 0.06, 0.533, 0.125, PANEL)
    P.fig.text(0.463, 0.163, "Evidence level (colour always shown with this text)", fontsize=8.5, fontweight="bold")
    x = 0.463
    for lvl in ("Root-cause evidence", "Observed change", "Statistical association", "Hypothesis", "Not attributed"):
        P.tag(x, 0.137, lvl, LEVEL[lvl])
        x += 0.016 + 0.0042 * len(lvl)
    P.fig.text(0.463, 0.1, "How the fall splits (Phase 5 Shapley bridge, FACT):  Transactions "
               f"{_v(reg, 'P1-30')}  |  Basket size (UPT) {_v(reg, 'P1-31')}  |  Price (ASP) {_v(reg, 'P1-32')}  "
               f"|  Returns {_v(reg, 'P1-33')}", fontsize=8, color=INK2)
    P.fig.text(0.463, 0.075, "Read with the evidence page: only the stock-out mechanism is root-cause evidence.",
               fontsize=8, color=INK2)
    P.save(out / "page1_executive_overview.png")


def page2(M, reg, cfg, out):
    P = Page(2, "Store & customer transactions: S03, S04, S05",
             "A sudden loss of receipts in three stores, measured against matched control stores")
    P.slicers(["Period: H2 2025", "Store group: All", "Region: All", "Store format: All", "Store: All"])
    P.card(0.012, 0.735, 0.15, 0.1, "Transactions per store, S03-S05", _v(reg, "P2-T0"), "H2 2025 vs H2 2024", "FACT",
           BLUE, RED)
    sg = read_csv("reports/phase6/cluster_control_groups.csv", cfg).set_index("control_group")
    P.card(0.168, 0.735, 0.15, 0.1, "Matched controls", _v(reg, "P2-T1"), sg.loc["matched", "stores"], "FACT", BLUE)
    P.card(0.324, 0.735, 0.17, 0.1, "Estimated cluster revenue impact", _v(reg, "P2-E1"),
           f"range {_v(reg, 'P2-E2')} to {_v(reg, 'P2-E3')}", "ESTIMATE", BLUE, RED)
    P.card(0.5, 0.735, 0.15, 0.1, "DiD vs matched controls", _v(reg, "P2-E4"), f"placebo p {_v(reg, 'P2-E6')}*",
           "ESTIMATE", BLUE)
    P.fig.text(0.012, 0.722, f"* {_v(reg, 'P2-E6')} is the smallest attainable p (680 placebo groups, cluster vs all other "
               "stores). Phase 5 selected these stores because they fell most, so it overstates significance; the size and "
               "stability of the gap are the evidence.", fontsize=7, color=INK2)
    P.box(0.656, 0.735, 0.332, 0.1, "#FDF1E0", YELLOW, lw=1.5)
    P.fig.text(0.666, 0.807, "Cause not established from available internal data.", fontsize=11, fontweight="bold")
    P.fig.text(0.666, 0.78, "Observed and quantified; underlying cause UNRESOLVED. Price, promotions, availability,",
               fontsize=7.8, color=INK2)
    P.fig.text(0.666, 0.76, "range and returns moved close to the controls. External cause = HYPOTHESIS.", fontsize=7.8,
               color=INK2)
    # weekly yoy by group
    ax = P.panel(0.012, 0.36, 0.475, 0.355, "When: weekly transactions YoY, cluster vs matched controls",
                 "DAX [Transactions YoY %] by Date[retail_week] and Store[store_group]. FACT.")
    for grp, col in (("Matched control", GREY), ("Investigated cluster", RED)):
        s = weekly(M, "Transactions YoY %", 2025, {"Store": {"store_group": grp}})
        ax.plot(s.index, 100 * s, color=col, lw=2, label=grp)
    ax.axhline(0, color=INK2, lw=0.8)
    ax.set_ylabel("% vs same week 2024", fontsize=8)
    ax.legend(fontsize=7.5, frameon=False, loc="lower left")
    _style(ax)
    ax = P.panel(0.497, 0.36, 0.491, 0.355, "Change point: daily gap to controls (7-day mean) and fitted step",
                 f"Phase 6 ESTIMATE; not affected by slicers. Step {_v(reg, 'P2-E5')}; S03 {_v(reg, 'P2-OS03')}, "
                 f"S04 {_v(reg, 'P2-OS04')}, S05 {_v(reg, 'P2-OS05')}.")
    d = read_csv("reports/phase6/cluster_onset_daily.csv", cfg)
    d["calendar_date"] = pd.to_datetime(d["calendar_date"])
    on = read_csv("reports/phase6/cluster_onset.csv", cfg).iloc[0]
    g = 100 * (np.exp(d["gap_log"].rolling(7, center=True).mean()) - 1)
    ax.plot(d["calendar_date"], g, color=INK2, lw=1.2, label="7-day mean gap")
    od = pd.Timestamp(on["onset_date"])
    pre = d["calendar_date"] < od
    for m, col in ((pre, GREY), (~pre, RED)):
        lvl = 100 * (np.exp(d.loc[m, "gap_log"].mean()) - 1)
        ax.plot(d.loc[m, "calendar_date"], [lvl] * m.sum(), color=col, lw=2.4)
    ax.axvline(od, color=INK, ls="--", lw=0.9)
    ax.set_ylabel("cluster minus controls, %", fontsize=8)
    _style(ax)
    # table
    P.box(0.012, 0.06, 0.62, 0.28)
    P.fig.text(0.02, 0.318, "How the cluster compares: H2 2025 (DAX by Store[store_group]; estate = total)",
               fontsize=9.5, fontweight="bold")
    hdr = ["Measure", "S03-S05", "Matched controls", "Estate"]
    xs = [0.02, 0.25, 0.37, 0.51]
    for x, h in zip(xs, hdr):
        P.fig.text(x, 0.292, h, fontsize=8, fontweight="bold", color=INK2)
    names = ["Net Revenue YoY %", "Transactions YoY %", "Avg Transaction Value", "Units per Transaction",
             "Avg Selling Price", "Availability", "Promotion Share", "Return Rate"]
    for ri, n in enumerate(names):
        y = 0.268 - ri * 0.0245
        P.fig.text(xs[0], y, n, fontsize=8, color=INK)
        for gi in range(3):
            P.fig.text(xs[gi + 1], y, _v(reg, f"P2-{gi}{ri}"), fontsize=8, color=RED if (gi == 0 and ri < 2) else INK)
    P.text_panel(0.642, 0.06, 0.346, 0.28, "Additional data required to explain the loss",
                 ["- Footfall counters (visits, not receipts)", "- Competitor openings and promotions nearby",
                  "- Road and access works", "- Local events", "- Store operating logs: opening hours, closures, refits",
                  "", "Owner (proposed): Retail Operations / Commercial"])
    P.save(out / "page2_store_customer.png")


def page3(M, reg, cfg, out):
    P = Page(3, "Product, category & inventory: Electronics & Tech",
             "Availability fell and full-week stock-outs concentrated on Voltix SKUs; the lost-sales effect is small")
    P.slicers(["Period: H2 2025", "Category: Electronics & Tech", "Supplier: All", "Product: All", "Store: All"])
    cards = [("Net Revenue", _v(reg, "P3-01"), f"{_v(reg, 'P3-02')} ({_v(reg, 'P3-03')})", RED),
             ("Units YoY", _v(reg, "P3-04"), "units sold", RED), ("Transactions YoY", _v(reg, "P3-05"), "receipts with E&T", RED),
             ("ASP", _v(reg, "P3-06"), "per unit", INK), ("Availability", _v(reg, "P3-08"), f"was {_v(reg, 'P3-07')}", RED),
             ("Returns", _v(reg, "P3-09"), "refund value", INK)]
    w = (0.976 - 5 * 0.006) / 6
    for i, (t, v, s, c) in enumerate(cards):
        P.card(0.012 + i * (w + 0.006), 0.735, w, 0.1, t, v, s, "FACT", BLUE, c)
    tl = read_csv("reports/phase6/electronics_weekly_timeline.csv", cfg)
    ax = P.panel(0.012, 0.36, 0.475, 0.355, "Weekly availability: Voltix SKUs vs other suppliers, H2 2025",
                 "Phase 6 table (electronics_weekly_timeline); FACT; not affected by slicers.")
    ax.plot(tl["retail_week"], 100 * tl["availability_other_suppliers_cy"], color=GREY, lw=2, label="Other suppliers")
    ax.plot(tl["retail_week"], 100 * tl["availability_supplier_cy"], color=ORANGE, lw=2.2, label="Voltix Distribution Ltd")
    ax.set_ylabel("% of ranged store-SKU-weeks in stock", fontsize=8)
    ax.text(0.99, 0.02, "axis does not start at zero", transform=ax.transAxes, ha="right", fontsize=6.5, color=MUTED)
    ax.legend(fontsize=7.5, frameon=False, loc="lower left")
    _style(ax)
    sk = read_csv("reports/phase6/electronics_sku_stockouts.csv", cfg).nlargest(8, "lost_primary_change")[::-1]
    ax = P.panel(0.497, 0.36, 0.491, 0.355, "Top affected SKUs: increase in estimated lost sales",
                 f"Phase 6 ESTIMATE. Top 10% sellers {_v(reg, 'P3-C1')}; top SKU P00149 {_v(reg, 'P3-C2')}; "
                 f"top three {_v(reg, 'P3-C3')}.")
    cols = [ORANGE if s == "Voltix Distribution Ltd" else GREY for s in sk["supplier_name"]]
    ax.barh(sk["product_id"], sk["lost_primary_change"], color=cols, height=0.6, hatch="///", edgecolor="white")
    for y, (v, sp) in enumerate(zip(sk["lost_primary_change"], sk["supplier_name"])):
        ax.text(v, y, f" €{v:,.0f}  {sp.split()[0]}", va="center", fontsize=7)
    ax.set_xlabel("€ (orange = Voltix SKU)", fontsize=8)
    ax.grid(axis="y", visible=False)
    _style(ax)
    P.box(0.012, 0.06, 0.475, 0.28)
    P.fig.text(0.02, 0.318, "Voltix Distribution Ltd: stock-out pattern (FACT)", fontsize=9.5, fontweight="bold")
    rows = [("Stock-out episodes", _v(reg, "P3-E2024"), _v(reg, "P3-E2025")),
            ("Mean episode length (weeks)", _v(reg, "P3-M2024"), _v(reg, "P3-M2025")),
            ("Full-week zero-stock store-SKU-weeks", _v(reg, "P3-F0"), _v(reg, "P3-F1")),
            ("Stock-out rate rise vs other suppliers", "", _v(reg, "P3-S1") + "  (STAT. ASSOCIATION)")]
    for x, h in zip((0.02, 0.27, 0.35), ("Measure", "H2 2024", "H2 2025")):
        P.fig.text(x, 0.29, h, fontsize=8, fontweight="bold", color=INK2)
    for i, (n, a, b) in enumerate(rows):
        y = 0.262 - i * 0.03
        P.fig.text(0.02, y, n, fontsize=8)
        P.fig.text(0.27, y, a, fontsize=8)
        P.fig.text(0.35, y, b, fontsize=8, color=RED)
    P.box(0.02, 0.075, 0.46, 0.06, "#FDF1E0", YELLOW, lw=1.2)
    P.fig.text(0.026, 0.118, "Stock-out concentration is associated with Voltix SKUs. Available data cannot determine",
               fontsize=7.8)
    P.fig.text(0.026, 0.096, "whether the cause was supplier performance or Brightwater ordering/replenishment.",
               fontsize=7.8)
    P.box(0.497, 0.06, 0.491, 0.28)
    P.fig.text(0.505, 0.318, "Lost sales in full-week stock-outs (ESTIMATE, ROOT-CAUSE EVIDENCE)", fontsize=9.5,
               fontweight="bold")
    P.tag(0.505, 0.29, "Root-cause evidence (mechanism)", AQUA)
    for i, (lab, rid) in enumerate((("Estimated gross lost sales", "P3-L1"),
                                    ("Net impact after deferred demand", "P3-L2"))):
        P.fig.text(0.505 + i * 0.24, 0.25, lab, fontsize=8, color=INK2)
        P.fig.text(0.505 + i * 0.24, 0.215, _v(reg, rid), fontsize=17, fontweight="bold")
    P.fig.text(0.505, 0.175, f"Sensitivity range {_v(reg, 'P3-L3')} to {_v(reg, 'P3-L4')} (21 variants). About 5% of "
               "the H2 decline.", fontsize=8, color=INK2)
    P.fig.text(0.505, 0.15, "Upper bound incl. partial weeks is not evidence and is not shown as a result.", fontsize=8,
               color=INK2)
    P.fig.text(0.505, 0.1, "Data needed: purchase orders, ASNs, lead times, fill rates, ordering parameters.", fontsize=8,
               color=INK2)
    P.save(out / "page3_product_inventory.png")


def page4(M, reg, cfg, out):
    P = Page(4, "Returns & product-quality signals: Electronics & Tech",
             "Recorded 'Faulty' refunds rose; a verified product defect is NOT established")
    P.slicers(["Period: H2 2025", "Category: Electronics & Tech", "Return reason: All", "Supplier: All", "Store: All"])
    P.card(0.012, 0.735, 0.17, 0.1, "'Faulty' returns change", _v(reg, "P4-01"), f"{_v(reg, 'P4-02')} vs H2 2024",
           "FACT", BLUE, RED)
    P.card(0.188, 0.735, 0.15, 0.1, "'Faulty' returns H2 2025", _v(reg, "P4-03"), "refund value", "FACT", BLUE)
    P.card(0.344, 0.735, 0.17, 0.1, "Top 5 stores: share of increase", _v(reg, "P4-C1"), "5 named stores",
           "STAT. ASSOCIATION", YELLOW)
    P.card(0.52, 0.735, 0.15, 0.1, "Top 5 products: share", _v(reg, "P4-C2"), "spread across products", "FACT", BLUE)
    P.box(0.676, 0.735, 0.312, 0.1, "#FDF1E0", YELLOW, lw=1.5)
    P.fig.text(0.686, 0.807, "Recorded reason 'Faulty'  is not  a verified defect", fontsize=10.5, fontweight="bold")
    P.fig.text(0.686, 0.78, "The till reason is observed (FACT). A product defect remains a HYPOTHESIS;",
               fontsize=7.8, color=INK2)
    P.fig.text(0.686, 0.76, "a change in store recording practice fits the data equally well.", fontsize=7.8, color=INK2)
    ax = P.panel(0.012, 0.36, 0.3, 0.355, "Change by return reason (E&T)", "DAX [Returns Value YoY] by Returns[return_reason].",
                 left=0.075)
    labs = ["Faulty", "Changed mind", "Damaged", "Gift return", "Not as described"]
    vals = [reg.set_index("id").loc[r, "value"] for r in ("P4-01", "P4-R0", "P4-R1", "P4-R2", "P4-R3")]
    ax.barh(labs[::-1], [v / 1e3 for v in vals[::-1]], color=[RED if v > 0 else GREY for v in vals[::-1]], height=0.6)
    ax.axvline(0, color=INK2, lw=0.8)
    ax.set_xlabel("€ thousand vs H2 2024", fontsize=8)
    ax.grid(axis="y", visible=False)
    _style(ax)
    fs = read_csv("reports/phase6/faulty_returns_by_store.csv", cfg).nlargest(10, "value_change")[::-1]
    ax = P.panel(0.322, 0.36, 0.33, 0.355, "'Faulty' units per 100 sold, by store (top 10 by increase)",
                 "Phase 6 table; FACT; not affected by slicers.")
    y = np.arange(len(fs))
    ax.barh(y + 0.18, fs["rate_per_100_py"], height=0.34, color=GREY, label="H2 2024")
    ax.barh(y - 0.18, fs["rate_per_100_cy"], height=0.34, color=ORANGE, label="H2 2025")
    ax.set_yticks(y, fs["store_id"], fontsize=7.5)
    ax.legend(fontsize=7, frameon=False, loc="lower right")
    ax.grid(axis="y", visible=False)
    _style(ax)
    ax = P.panel(0.662, 0.36, 0.326, 0.355, "By sale month (cohort): 'Faulty' per 100 units sold",
                 "DAX [Returned Units per 100 Sold (Sale Cohort)]; inactive relationship.")
    months = [(y_, m) for y_ in (2024, 2025) for m in range(1, 13)]
    vals = []
    for y_, m in months:
        c = Ctx({"Date": {"year_month": y_ * 100 + m}, "Product": {"category": cfg["powerbi"]["focus_category_availability"]},
                 "Returns": {"return_reason": "Faulty"}})
        vals.append(100 * float(M.rows("Returns", Ctx(c.filters, True))["return_quantity"].sum()) / evaluate(M, "Units", c))
    ax.plot(range(12), vals[:12], color=GREY, lw=2, label="2024 sales")
    ax.plot(range(12), vals[12:], color=ORANGE, lw=2.2, label="2025 sales")
    ax.set_xticks(range(12), list("JFMAMJJASOND"), fontsize=7.5)
    ax.axvline(8, color=INK2, ls="--", lw=0.8)
    ax.text(8.1, max(vals) * 0.98, "Sep", fontsize=7, color=INK2, va="top")
    ax.legend(fontsize=7, frameon=False, loc="upper left")
    _style(ax)
    P.text_panel(0.012, 0.06, 0.48, 0.28, "What the data shows (FACT / STATISTICAL ASSOCIATION)",
                 [f"- 'Faulty' refunds {_v(reg, 'P4-01')} ({_v(reg, 'P4-02')}); other reasons flat or down",
                  "- Concentrated in S13, S14, S07, S15, S16 (significant increase, p < 0.01)",
                  "- Increase begins mainly with products sold from September 2025 onward",
                  f"  (Sep: {_v(reg, 'P4-K202409')} per 100 in 2024 vs {_v(reg, 'P4-K202509')} in 2025)",
                  "- All four suppliers rose in those stores; sale-to-return lag unchanged"])
    P.text_panel(0.502, 0.06, 0.486, 0.28, "Investigation panel: evidence required to confirm a defect",
                 ["- QA inspection results", "- Batch / lot / serial numbers", "- Supplier RMA reports",
                  "- Warranty claims", "- Returns-handling audit in the named stores", "",
                  "Owner (proposed): Quality / Buying"], fc="#EEF4FC", ec=BLUE)
    P.save(out / "page4_returns_quality.png")


def page5(M, reg, cfg, out):
    P = Page(5, "Promotions & Home & Kitchen", "Promotion activity is associated with the Home & Kitchen decline, "
             "but causality is not established")
    P.slicers(["Period: H2 2025", "Category: Home & Kitchen", "Promotion: All", "Store: All"])
    cards = [("Net Revenue", _v(reg, "P5-01"), _v(reg, "P5-02") + " vs H2 2024", RED),
             ("Units YoY", _v(reg, "P5-03"), "units sold", RED),
             ("ASP", _v(reg, "P5-04"), f"was {_v(reg, 'P5-05')}", RED),
             ("Gross Margin change", _v(reg, "P5-06"), "vs H2 2024", RED),
             ("Promotion events", _v(reg, "P5-E2025"), f"was {_v(reg, 'P5-E2024')} (Phase 6)", INK),
             ("Discount rate", _v(reg, "P5-10"), f"was {_v(reg, 'P5-09')} of gross sales", RED),
             ("Promotion share", _v(reg, "P5-07"), f"was {_v(reg, 'P5-08')} of sales", INK)]
    w = (0.976 - 6 * 0.006) / 7
    for i, (t, v, s, c) in enumerate(cards):
        P.card(0.012 + i * (w + 0.006), 0.735, w, 0.1, t, v, s, "FACT", BLUE, c)
    hm = read_csv("reports/phase6/hk_promotion_counterfactuals.csv", cfg)
    rows = []
    for code in ("M1", "M4", "M2", "M3"):
        r = hm[hm["method"].str.startswith(code) & ~hm["method"].str.contains("gross margin")].iloc[0]
        rows.append((code, r))
    ax = P.panel(0.012, 0.3, 0.475, 0.415, "Four Phase 6 methods, shown separately (never combined)",
                 "ESTIMATES with intervals. The methods disagree in sign, so the effect is a STATISTICAL ASSOCIATION.",
                 left=0.1)
    desc = {"M1": "M1 category DiD", "M4": "M4 discount accounting", "M2": "M2 dose-response", "M3": "M3 event-level"}
    for i, (code, r) in enumerate(rows[::-1]):
        col = RED if r["effect_eur"] < 0 else BLUE
        ax.barh(i, r["effect_eur"] / 1e3, color=col, height=0.55, hatch="///", edgecolor="white")
        if pd.notna(r["ci_low"]):
            ax.plot([r["ci_low"] / 1e3, r["ci_high"] / 1e3], [i, i], color=INK, lw=1.2)
        ax.text(0, i + 0.38, f"  {_v(reg, f'P5-{code}')}  ", fontsize=8, va="bottom",
                ha="left" if r["effect_eur"] < 0 else "right")
    ax.set_yticks(range(4), [desc[c] for c, _ in rows[::-1]], fontsize=7.5)
    ax.axvline(0, color=INK2, lw=0.9)
    ax.set_xlabel("€ thousand (negative = promotions reduced revenue)", fontsize=8)
    ax.grid(axis="y", visible=False)
    _style(ax)
    wk = read_csv("reports/phase6/hk_promotion_weekly.csv", cfg)
    ax = P.panel(0.497, 0.53, 0.491, 0.185, "Promotion frequency: share of SKU-days on promotion",
                 "Phase 6 table (hk_promotion_weekly).")
    ax.plot(wk["retail_week"], 100 * wk["promo_coverage_py"], color=GREY, lw=1.8, label="H2 2024")
    ax.plot(wk["retail_week"], 100 * wk["promo_coverage_cy"], color=BLUE, lw=1.8, label="H2 2025")
    ax.legend(fontsize=7, frameon=False, loc="upper right", ncol=2, bbox_to_anchor=(1, 1.42))
    _style(ax)
    ax = P.panel(0.497, 0.3, 0.491, 0.215, "Sales response: weekly H&K sales", "Phase 6 table; separate axis from frequency.")
    ax.plot(wk["retail_week"], wk["sales_revenue_py"] / 1e3, color=GREY, lw=1.8, label="H2 2024")
    ax.plot(wk["retail_week"], wk["sales_revenue_cy"] / 1e3, color=BLUE, lw=1.8, label="H2 2025")
    ax.set_ylabel("€ thousand", fontsize=8)
    _style(ax)
    m3d = hm[hm["method"].str.startswith("M3")]["detail"].iloc[0]
    contam = f"{100 * float(m3d.split('2025:')[1].strip(' }')):.0f}%"
    P.text_panel(0.012, 0.06, 0.475, 0.22, "Margin and post-promotion response (ESTIMATES)",
                 [f"- M1 gross-margin effect: {_v(reg, 'P5-GM')} (consistent with the unit response)",
                  f"- Post-promotion shortfall: {_v(reg, 'P5-D2024')} (H2 2024) to {_v(reg, 'P5-D2025')} (H2 2025)",
                  "- Cannibalisation of non-promoted H&K SKUs: none measurable",
                  f"- M3 baselines are exposed to back-to-back promotions ({contam} of 2025 events)"])
    P.box(0.497, 0.06, 0.491, 0.22, "#FDF1E0", YELLOW, lw=1.5)
    P.fig.text(0.507, 0.25, "Promotion activity is associated with the Home & Kitchen decline,", fontsize=10.5,
               fontweight="bold")
    P.fig.text(0.507, 0.225, "but causality is not established.", fontsize=10.5, fontweight="bold")
    for i, t in enumerate(["Two methods say the promotions reduced revenue, two say they added it.",
                           "Needed: campaign objectives, a holdout-store test or SKU price elasticities.",
                           "Owner (proposed): Commercial / Marketing"]):
        P.fig.text(0.507, 0.18 - i * 0.028, t, fontsize=8, color=INK2)
    P.save(out / "page5_promotions.png")


def _wrap(s: str, n: int) -> list[str]:
    words, lines, cur = str(s).split(), [], ""
    for w in words:
        if len(cur) + len(w) + 1 > n and cur:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    return lines + [cur]


def page6(M, reg, cfg, extracts, out):
    P = Page(6, "Root-cause evidence matrix",
             "What each candidate driver is worth, how strong the evidence is, and what is still unknown")
    P.slicers(["Evidence level: All", "Driver: All"])
    em = extracts["p6_evidence_matrix"]
    em = em[em["driver_id"] != "D09"]
    cols = [("Driver", 0.02, 30), ("Evidence level", 0.19, 22), ("Cause", 0.29, 14), ("Impact", 0.36, 12),
            ("What we know", 0.43, 44), ("What we do not know", 0.625, 44), ("Additional data required", 0.82, 38)]
    y = 0.83
    for name, x, _ in cols:
        P.fig.text(x, y, name, fontsize=8.5, fontweight="bold", color=INK2)
    y -= 0.012
    rh = 0.089
    cause_c = {"Established": AQUA, "Unresolved": "#52514E", "Not established": YELLOW, "Not attributed": "#C9C7C1"}
    for r in em.itertuples():
        y -= rh
        P.box(0.01, y, 0.978, rh - 0.006, SURF, LINE)
        lvl = r.evidence_level
        P.fig.add_artist(Rectangle((0.01, y), 0.005, rh - 0.006, transform=P.fig.transFigure, color=LEVEL[lvl], zorder=-4))
        for j, ln in enumerate(_wrap(f"{r.driver_id}  {r.driver}", 32)[:2]):
            P.fig.text(0.02, y + rh - 0.022 - 0.016 * j, ln, fontsize=8, fontweight="bold", va="top")
        for j, ln in enumerate(_wrap(r.evidence_display, 36)[:2]):
            P.fig.text(0.02, y + rh - 0.056 - 0.015 * j, ln, fontsize=6.6, color=INK2, va="top")
        P.tag(0.19, y + rh - 0.028, lvl, LEVEL[lvl], 7)
        strength = int(r.evidence_strength)
        for k in range(3):
            P.fig.add_artist(Rectangle((0.191 + k * 0.012, y + 0.018), 0.009, 0.012, transform=P.fig.transFigure,
                                       color=LEVEL[lvl] if k < strength else "#ECEBE7"))
        cs = r.cause_status
        t = P.tag(0.29, y + rh - 0.028, cs, cause_c[cs], 7)
        if cs == "Unresolved":
            t.set_color("white")
            t.get_bbox_patch().set_alpha(0.9)
        rid = f"P6-{r.driver_id}"
        P.fig.text(0.36, y + rh - 0.028, _v(reg, rid) if rid in set(reg["id"]) else "not quantified", fontsize=8,
                   fontweight="bold")
        for (name, x, n), txt in zip(cols[4:], (r.what_we_know, r.what_we_do_not_know, r.additional_data_required)):
            lines = _wrap(txt, n + 4)
            if len(lines) > 5:
                lines = lines[:5]
                lines[-1] += " ..."
            for j, ln in enumerate(lines):
                P.fig.text(x, y + rh - 0.017 - 0.0142 * j, ln, fontsize=6, color=INK2, va="top")
    P.fig.text(0.012, 0.012, "Causal-evidence bars: 3 = Root-cause evidence, 2 = Statistical association, 1 = Observed change "
               "(measured, no cause claimed), 0 = Hypothesis. Cause: Established / Not established / Unresolved.\n"
               "Impacts overlap (D02 repeats D01, D04 is part of D03, D06 repeats D05): never add rows; the table total is "
               "switched off. Phase 6 table; not affected by slicers.\nPower BI word-wraps the cells; '...' marks text cut "
               "only in this mockup (full text in tooltip T2).", fontsize=6.6, color=INK2, va="bottom")
    P.save(out / "page6_evidence_matrix.png")


def page7(M, reg, cfg, extracts, out):
    P = Page(7, "Management investigation: what to find out next",
             "Investigation priorities, not prescribed actions. Owners are proposals for management to confirm.")
    inv = extracts["p6_investigations"]
    cols = [("#", 0.014, 3), ("Topic", 0.03, 24), ("Known", 0.19, 40), ("Unknown", 0.39, 40), ("Why it matters", 0.59, 26),
            ("Data required", 0.72, 40), ("Owner (proposed)", 0.9, 16)]
    y = 0.85
    for name, x, _ in cols:
        P.fig.text(x, y, name, fontsize=8.5, fontweight="bold", color=INK2)
    rh = 0.148
    for r in inv.itertuples():
        y -= rh
        P.box(0.01, y + 0.004, 0.978, rh - 0.01)
        lvl = r.evidence_level
        P.fig.add_artist(Rectangle((0.01, y + 0.004), 0.005, rh - 0.01, transform=P.fig.transFigure, color=LEVEL[lvl],
                                    zorder=-4))
        P.fig.text(0.018, y + rh - 0.024, str(r.priority), fontsize=11, fontweight="bold", va="top")
        for j, ln in enumerate(_wrap(r.topic, 24)[:2]):
            P.fig.text(0.03, y + rh - 0.024 - 0.018 * j, ln, fontsize=8.2, fontweight="bold", va="top")
        P.tag(0.03, y + 0.05, lvl, LEVEL[lvl], 6.5)
        P.fig.text(0.03, y + 0.022, f"slice: {_v(reg, f'P7-{r.driver_id}')}", fontsize=7, color=INK2)
        for (name, x, n), txt in zip(cols[2:], (r.known, r.unknown, r.why_it_matters, r.data_required, r.proposed_owner)):
            for j, ln in enumerate(_wrap(txt, n)[:5]):
                P.fig.text(x, y + rh - 0.024 - 0.017 * j, ln, fontsize=7, color=INK2, va="top")
    P.fig.text(0.012, 0.035, "Slices overlap and are not additive. The analysis does not prescribe actions: each row is "
               "a question the named data would answer. Phase 6 tables; not affected by slicers.", fontsize=7, color=INK2)
    P.save(out / "page7_investigation.png")


def make_all(M: Model, reg: pd.DataFrame, cfg: dict, extracts: dict, out: Path) -> list[str]:
    out.mkdir(parents=True, exist_ok=True)
    page1(M, reg, cfg, out)
    page2(M, reg, cfg, out)
    page3(M, reg, cfg, out)
    page4(M, reg, cfg, out)
    page5(M, reg, cfg, out)
    page6(M, reg, cfg, extracts, out)
    page7(M, reg, cfg, extracts, out)
    return sorted(p.name for p in out.glob("page*.png"))
