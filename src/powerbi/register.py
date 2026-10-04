"""Dashboard number register: every number the dashboard shows, with its source.

Two source types:
  * DAX   : a measure in powerbi/dax (evaluated here by its Python reference) in a stated filter context;
  * P6/P5 : a cell (or a documented aggregate of cells) of a frozen Phase 6 / Phase 5 output.
The mockups draw their numbers from this register, and tests re-derive every entry from its source, so no
number on a page exists without a traceable source.
"""
from __future__ import annotations

import pandas as pd

from .access import read_csv
from .reference import Ctx, Model, evaluate, h2


def f_eur(v, unit="k", signed=False):
    if v != v:
        return "not quantified"
    s = "+" if signed and v > 0 else ("-" if v < 0 else "")
    a = abs(v)
    if unit == "M":
        return f"{s}€{a / 1e6:,.3f}M"
    if unit == "k":
        return f"{s}€{a / 1e3:,.0f}k"
    return f"{s}€{a:,.0f}"


def f_pct(v, dp=1, signed=False):
    return f"{'+' if signed and v > 0 else ''}{100 * v:.{dp}f}%"


def f_pp(v, dp=1):
    return f"{'+' if v > 0 else ''}{v:.{dp}f} pp"


def f_int(v, signed=False):
    return f"{'+' if signed and v > 0 else ''}{v:,.0f}"


class Register:
    def __init__(self, M: Model, cfg: dict):
        self.M, self.cfg, self.rows, self._csv = M, cfg, [], {}
        hd = cfg["powerbi"]["headline"]
        self.cy, self.py = h2(hd["retail_year_cy"]), h2(hd["retail_year_py"])

    def csv(self, rel):
        if rel not in self._csv:
            self._csv[rel] = read_csv(rel, self.cfg)
        return self._csv[rel]

    def dax(self, rid, page, visual, label, measure, ctx, ctx_text, fmt, tag="FACT"):
        v = evaluate(self.M, measure, ctx)
        self.rows.append({"id": rid, "page": page, "visual": visual, "label": label, "value": v, "display": fmt(v),
                          "source_type": "DAX", "source": f"[{measure}]", "context": ctx_text, "evidence_tag": tag})
        return v

    def p6(self, rid, page, visual, label, rel, where: dict, col, fmt, tag, agg=None):
        df = self.csv(rel)
        sel = df
        for k, v in where.items():
            sel = sel[sel[k] == v]
        if agg is None:
            if len(sel) != 1:
                raise ValueError(f"{rid}: {rel} {where} matched {len(sel)} rows")
            v = sel.iloc[0][col]
        else:
            v = agg(sel, col)
        where_txt = ", ".join(f"{k}={v}" for k, v in where.items()) or "all rows"
        self.rows.append({"id": rid, "page": page, "visual": visual, "label": label, "value": v,
                          "display": fmt(v), "source_type": "P6" if "phase6" in rel else "P5", "source": rel,
                          "context": f"{where_txt}; column {col}" + (f"; derived: {agg.__doc__}" if agg else ""),
                          "evidence_tag": tag})
        return v

    def frame(self) -> pd.DataFrame:
        return pd.DataFrame(self.rows)


def _share_high(df, col):
    """sum over high_seller rows / sum over all rows"""
    return float(df.loc[df["high_seller"], col].sum() / df[col].sum())


def _share_top1(df, col):
    """largest row / sum over all rows"""
    return float(df[col].max() / df[col].sum())


def _primary_test(df, col):
    """the main supplier test row (variant empty)"""
    return float(df[df["variant"].isna()][col].iloc[0])


def _contamination_2025(df, col):
    """share parsed from the M3 detail text ('baseline contamination {2024: x, 2025: y}'), 2025 value"""
    return float(str(df[col].iloc[0]).split("2025:")[1].strip(" }"))


def _share_top3(df, col):
    """three largest rows / sum over all rows"""
    return float(df[col].nlargest(3).sum() / df[col].sum())


def build(M: Model, cfg: dict) -> pd.DataFrame:
    R = Register(M, cfg)
    cy, py = R.cy, R.py
    H = "H2 2025 (Date[period_label] = \"H2 2025\")"
    pc = cfg["powerbi"]
    et, hk, sup = pc["focus_category_availability"], pc["focus_category_promotions"], pc["focus_supplier"]
    P6 = "reports/phase6/"

    # ------------------------------------------------------------------ Page 1 Executive overview
    p = "1 Executive overview"
    R.dax("P1-01", p, "KPI card", "Net Revenue H2 2025", "Net Revenue", cy, H, lambda v: f_eur(v, "M"))
    R.dax("P1-02", p, "KPI card", "Net Revenue H2 2024", "Net Revenue PY", cy, H, lambda v: f_eur(v, "M"))
    R.dax("P1-03", p, "KPI card", "Revenue change", "Net Revenue YoY", cy, H, lambda v: f_eur(v, "k"))
    R.dax("P1-04", p, "KPI card", "Net Revenue YoY %", "Net Revenue YoY %", cy, H, lambda v: f_pct(v, 2, True))
    R.dax("P1-05", p, "KPI card", "Gross Margin H2 2025", "Gross Margin", cy, H, lambda v: f_eur(v, "M"))
    R.dax("P1-06", p, "KPI card", "Gross Margin change", "Gross Margin YoY", cy, H, lambda v: f_eur(v, "k"))
    R.dax("P1-07", p, "KPI card", "Gross Margin % H2 2025", "Gross Margin %", cy, H, lambda v: f_pct(v, 1))
    R.dax("P1-08", p, "KPI card", "Gross Margin % H2 2024", "Gross Margin % PY", cy, H, lambda v: f_pct(v, 1))
    R.dax("P1-09", p, "KPI card", "Transactions H2 2025", "Transactions", cy, H, f_int)
    R.dax("P1-10", p, "KPI card", "Transaction change", "Transactions YoY", cy, H, lambda v: f_int(v, True))
    R.dax("P1-11", p, "KPI card", "Transactions YoY %", "Transactions YoY %", cy, H, lambda v: f_pct(v, 2, True))
    R.dax("P1-12", p, "KPI card", "Returns H2 2025", "Returns Value", cy, H, lambda v: f_eur(v, "k"))
    R.dax("P1-13", p, "KPI card", "Return Rate H2 2025", "Return Rate", cy, H, lambda v: f_pct(v, 2))
    R.dax("P1-14", p, "KPI card", "Return Rate H2 2024", "Return Rate PY", cy, H, lambda v: f_pct(v, 2))
    at = P6 + "driver_attribution.csv"
    names = {"D01": "Store-cluster excess decline", "D03": "Electronics full-week stock-outs",
             "D05": "Electronics 'Faulty' returns", "D07": "Home & Kitchen category-specific change", "D09": "Residual"}
    comp = R.csv(at)["component"].tolist()
    tags = {"D01": "ESTIMATE", "D03": "ESTIMATE", "D05": "FACT", "D07": "ESTIMATE", "D09": "ESTIMATE (remainder)"}
    for i, d in enumerate(pc["attribution_drivers"]):
        R.p6(f"P1-2{i}a", p, "Driver attribution waterfall", f"{names[d]} (EUR)", at, {"component": comp[i]},
             "amount_eur", lambda v: f_eur(v, "eur"), tags[d])
        R.p6(f"P1-2{i}b", p, "Driver attribution waterfall", f"{names[d]} (share)", at, {"component": comp[i]},
             "share_of_change", lambda v: f_pct(v, 0), tags[d])
    br = "reports/phase5/revenue_bridge.csv"
    for i, step in enumerate(("Transactions effect", "UPT effect", "ASP effect", "Returns effect")):
        R.p6(f"P1-3{i}", p, "Revenue bridge strip (Phase 5 Shapley)", step, br, {"step": step}, "value_eur",
             lambda v: f_eur(v, "k"), "FACT")

    # ------------------------------------------------------------------ Page 2 Store diagnostics
    p = "2 Store and customer diagnostics"
    groups = (("Investigated cluster", "S03-S05"), ("Matched control", "Matched controls"), (None, "Estate"))
    rows = (("Net Revenue YoY %", lambda v: f_pct(v, 1, True)), ("Transactions YoY %", lambda v: f_pct(v, 1, True)),
            ("Average Transaction Value", lambda v: f"€{v:,.2f}"), ("UPT", lambda v: f"{v:.2f}"),
            ("ASP", lambda v: f"€{v:,.2f}"), ("Availability", lambda v: f_pct(v, 1)),
            ("Promotion Share", lambda v: f_pct(v, 1)), ("Return Rate", lambda v: f_pct(v, 2)))
    for gi, (grp, lab) in enumerate(groups):
        ctx = cy if grp is None else cy.with_("Store", store_group=grp)
        ctx_t = H + ("" if grp is None else f", Store[store_group] = \"{grp}\"")
        for ri, (m, fmt) in enumerate(rows):
            R.dax(f"P2-{gi}{ri}", p, "Cluster vs controls vs estate table", f"{lab}: {m}", m, ctx, ctx_t, fmt)
    for gi, (grp, lab) in enumerate(groups[:2]):
        ctx = cy.with_("Store", store_group=grp)
        R.dax(f"P2-T{gi}", p, "Highlight cards", f"{lab}: transactions per store YoY %", "Transactions YoY %", ctx,
              H + f", Store[store_group] = \"{grp}\"", lambda v: f_pct(v, 1, True))
    R.p6("P2-E1", p, "Highlight cards", "Estimated cluster revenue impact", at, {"component": comp[0]}, "amount_eur",
         lambda v: f_eur(v, "eur"), "ESTIMATE")
    ss = P6 + "sensitivity_summary.csv"
    R.p6("P2-E2", p, "Highlight cards", "Impact range, smallest loss", ss, {"driver": "store_cluster_excess"}, "max",
         lambda v: f_eur(v, "eur"), "ESTIMATE")
    R.p6("P2-E3", p, "Highlight cards", "Impact range, largest loss", ss, {"driver": "store_cluster_excess"}, "min",
         lambda v: f_eur(v, "eur"), "ESTIMATE")
    R.p6("P2-E4", p, "Highlight cards", "DiD transactions vs matched controls", P6 + "cluster_did.csv",
         {"control_group": "matched", "outcome": "ly_transactions"}, "did_pct", lambda v: f"{v:+.1f}%", "ESTIMATE")
    R.p6("P2-E5", p, "Change-point panel", "Cluster change point", P6 + "cluster_onset.csv", {}, "onset_date",
         lambda v: pd.Timestamp(v).strftime("%d %b %Y"), "ESTIMATE")
    for s in pc["store_cluster"]:
        R.p6(f"P2-O{s}", p, "Change-point panel", f"{s} change point", P6 + "cluster_onset_by_store.csv",
             {"store_id": s}, "onset_date", lambda v: pd.Timestamp(v).strftime("%d %b"), "ESTIMATE")
    R.p6("P2-E6", p, "Change-point panel", "Placebo p-value (smallest attainable)", P6 + "cluster_placebo.csv", {},
         "p_value_one_sided", lambda v: f"{v:.4f}", "ESTIMATE")

    # ------------------------------------------------------------------ Page 3 Product, category, inventory
    p = "3 Product, category and inventory"
    c_et = cy.with_("Product", category=et)
    Het = H + f", Product[category] = \"{et}\""
    R.dax("P3-01", p, "KPI card", f"{et} Net Revenue H2 2025", "Net Revenue", c_et, Het, lambda v: f_eur(v, "M"))
    R.dax("P3-02", p, "KPI card", f"{et} Net Revenue change", "Net Revenue YoY", c_et, Het, lambda v: f_eur(v, "eur"))
    R.dax("P3-03", p, "KPI card", f"{et} Net Revenue YoY %", "Net Revenue YoY %", c_et, Het, lambda v: f_pct(v, 1, True))
    R.dax("P3-04", p, "KPI card", f"{et} Units YoY %", "Units YoY %", c_et, Het, lambda v: f_pct(v, 1, True))
    R.dax("P3-05", p, "KPI card", f"{et} Transactions (containing E&T) YoY %", "Transactions YoY %", c_et, Het,
          lambda v: f_pct(v, 1, True))
    R.dax("P3-06", p, "KPI card", f"{et} ASP H2 2025", "ASP", c_et, Het, lambda v: f"€{v:,.2f}")
    R.dax("P3-07", p, "KPI card", f"{et} Availability H2 2024", "Availability PY", c_et, Het, lambda v: f_pct(v, 1))
    R.dax("P3-08", p, "KPI card", f"{et} Availability H2 2025", "Availability", c_et, Het, lambda v: f_pct(v, 1))
    R.dax("P3-09", p, "KPI card", f"{et} Returns H2 2025", "Returns Value", c_et, Het, lambda v: f_eur(v, "k"))
    ep = P6 + "electronics_stockout_episodes.csv"
    for yr, lab in ((2024, "H2 2024"), (2025, "H2 2025")):
        R.p6(f"P3-E{yr}", p, "Voltix panel", f"{sup} stock-out episodes {lab}", ep,
             {"supplier_name": sup, "retail_year": yr}, "episodes", f_int, "FACT")
        R.p6(f"P3-M{yr}", p, "Voltix panel", f"{sup} mean episode length {lab} (weeks)", ep,
             {"supplier_name": sup, "retail_year": yr}, "mean_weeks_out", lambda v: f"{v:.1f}", "FACT")
    c_sup = cy.with_("Product", supplier_name=sup)
    Hs = H + f", Product[supplier_name] = \"{sup}\""
    R.dax("P3-F1", p, "Voltix panel", f"{sup} full-week zero-stock store-SKU-weeks H2 2025", "Full-Week Stock-Outs",
          c_sup, Hs, f_int)
    R.dax("P3-F0", p, "Voltix panel", f"{sup} full-week zero-stock store-SKU-weeks H2 2024", "Full-Week Stock-Outs PY",
          c_sup, Hs, f_int)
    lt = P6 + "electronics_lost_sales_totals.csv"
    R.p6("P3-L1", p, "Lost-sales panel", "Estimated gross lost sales (increase)", lt, {"scope": "category"},
         "primary_change", lambda v: f_eur(v, "eur"), "ESTIMATE")
    R.p6("P3-L2", p, "Lost-sales panel", "Estimated net impact after deferred demand", P6 + "sensitivity_analysis.csv",
         {"driver": "electronics_stockouts_primary", "method": "full-week lost sales change net of recovery"},
         "estimate_eur", lambda v: f_eur(-v, "eur"), "ESTIMATE")
    R.p6("P3-L3", p, "Lost-sales panel", "Sensitivity range, low", ss, {"driver": "electronics_stockouts_primary"},
         "max", lambda v: f_eur(-v, "eur"), "ESTIMATE")
    R.p6("P3-L4", p, "Lost-sales panel", "Sensitivity range, high", ss, {"driver": "electronics_stockouts_primary"},
         "min", lambda v: f_eur(-v, "eur"), "ESTIMATE")
    sk = P6 + "electronics_sku_stockouts.csv"
    R.p6("P3-C1", p, "Top SKUs panel", "Top 10% selling SKUs: share of lost sales", sk, {}, "lost_primary_change",
         lambda v: f_pct(v, 0), "ESTIMATE", _share_high)
    R.p6("P3-C2", p, "Top SKUs panel", "Top SKU (P00149): share of lost sales", sk, {}, "lost_primary_change",
         lambda v: f_pct(v, 0), "ESTIMATE", _share_top1)
    R.p6("P3-C3", p, "Top SKUs panel", "Top three SKUs: share of lost sales", sk, {}, "lost_primary_change",
         lambda v: f_pct(v, 0), "ESTIMATE", _share_top3)
    st = P6 + "electronics_supplier_test.csv"
    R.p6("P3-S1", p, "Voltix panel", "Stock-out rate rise vs other suppliers (pp)", st,
         {"metric": "oos_rate_change_pp"},
         "difference", lambda v: f_pp(v), "STATISTICAL ASSOCIATION", _primary_test)

    # ------------------------------------------------------------------ Page 4 Returns
    p = "4 Returns and product-quality signals"
    c_f = c_et.with_("Returns", return_reason="Faulty")
    Hf = Het + ", Returns[return_reason] = \"Faulty\""
    R.dax("P4-01", p, "KPI card", "'Faulty' returns change", "Returns Value YoY", c_f, Hf, lambda v: f_eur(v, "eur", True))
    R.dax("P4-02", p, "KPI card", "'Faulty' returns YoY %", "Returns Value YoY %", c_f, Hf, lambda v: f_pct(v, 0, True))
    R.dax("P4-03", p, "KPI card", "'Faulty' returns H2 2025", "Returns Value", c_f, Hf, lambda v: f_eur(v, "k"))
    for i, reason in enumerate(("Changed mind", "Damaged", "Gift return", "Not as described")):
        R.dax(f"P4-R{i}", p, "Change by return reason", f"'{reason}' change", "Returns Value YoY",
              c_et.with_("Returns", return_reason=reason), Het + f", Returns[return_reason] = \"{reason}\"",
              lambda v: f_eur(v, "eur", True))
    fs = P6 + "faulty_returns_by_store.csv"
    for s in ("S13", "S14", "S07", "S15", "S16"):
        R.p6(f"P4-S{s}", p, "Faulty rate by store", f"{s} 'Faulty' units per 100 sold H2 2025", fs, {"store_id": s},
             "rate_per_100_cy", lambda v: f"{v:.1f}", "FACT")
        R.p6(f"P4-P{s}", p, "Faulty rate by store", f"{s} 'Faulty' units per 100 sold H2 2024", fs, {"store_id": s},
             "rate_per_100_py", lambda v: f"{v:.1f}", "FACT")
    fc = P6 + "faulty_returns_concentration.csv"
    R.p6("P4-C1", p, "Faulty rate by store", "Top 5 stores: share of the gross increase", fc, {"dimension": "store_id"},
         "top_k_share_of_gross", lambda v: f_pct(v, 0), "FACT")
    R.p6("P4-C2", p, "Faulty by product", "Top 5 products: share of the gross increase", fc,
         {"dimension": "product_id"}, "top_k_share_of_gross", lambda v: f_pct(v, 0), "FACT")
    for ym in (202409, 202410, 202411, 202412, 202509, 202510, 202511, 202512):
        c = Ctx({"Date": {"year_month": ym}, "Product": {"category": et}, "Returns": {"return_reason": "Faulty"}})
        v_ret = float(M.rows("Returns", Ctx(c.filters, True))["return_quantity"].sum())
        v = 100 * v_ret / evaluate(M, "Units", c)
        R.rows.append({"id": f"P4-K{ym}", "page": p, "visual": "Sale-cohort line", "label": f"Faulty per 100 sold, sale month {ym}",
                       "value": v, "display": f"{v:.1f}", "source_type": "DAX",
                       "source": "[Returned Units per 100 Sold (Sale Cohort)]",
                       "context": f"Date[year_month] = {ym}, Product[category] = \"{et}\", Returns[return_reason] = \"Faulty\"",
                       "evidence_tag": "FACT"})

    # ------------------------------------------------------------------ Page 5 Promotions
    p = "5 Promotions and Home & Kitchen"
    c_hk = cy.with_("Product", category=hk)
    Hh = H + f", Product[category] = \"{hk}\""
    R.dax("P5-01", p, "KPI card", f"{hk} Net Revenue H2 2025", "Net Revenue", c_hk, Hh, lambda v: f_eur(v, "M"))
    R.dax("P5-02", p, "KPI card", f"{hk} Net Revenue change", "Net Revenue YoY", c_hk, Hh, lambda v: f_eur(v, "k"))
    R.dax("P5-03", p, "KPI card", f"{hk} Units YoY %", "Units YoY %", c_hk, Hh, lambda v: f_pct(v, 1, True))
    R.dax("P5-04", p, "KPI card", f"{hk} ASP H2 2025", "ASP", c_hk, Hh, lambda v: f"€{v:,.2f}")
    R.dax("P5-05", p, "KPI card", f"{hk} ASP H2 2024", "ASP PY", c_hk, Hh, lambda v: f"€{v:,.2f}")
    R.dax("P5-06", p, "KPI card", f"{hk} Gross Margin change", "Gross Margin YoY", c_hk, Hh, lambda v: f_eur(v, "k"))
    R.dax("P5-07", p, "KPI card", f"{hk} Promotion Share H2 2025", "Promotion Share", c_hk, Hh, lambda v: f_pct(v, 1))
    R.dax("P5-08", p, "KPI card", f"{hk} Promotion Share H2 2024", "Promotion Share PY", c_hk, Hh, lambda v: f_pct(v, 1))
    R.dax("P5-09", p, "KPI card", f"{hk} Discount Rate H2 2024", "Discount Rate PY", c_hk, Hh, lambda v: f_pct(v, 1))
    R.dax("P5-10", p, "KPI card", f"{hk} Discount Rate H2 2025", "Discount Rate", c_hk, Hh, lambda v: f_pct(v, 1))
    ev_ = P6 + "hk_promotion_events_by_year.csv"
    for yr in (2024, 2025):
        R.p6(f"P5-E{yr}", p, "KPI card", f"Promotion events H2 {yr}", ev_, {"retail_year": yr}, "events", f_int, "FACT")
        R.p6(f"P5-D{yr}", p, "Post-promotion dip", f"Post-promotion shortfall H2 {yr}", ev_, {"retail_year": yr},
             "post_dip_revenue", lambda v: f_eur(v, "eur"), "ESTIMATE")
    hm = P6 + "hk_promotion_counterfactuals.csv"
    meth = R.csv(hm)["method"].tolist()
    for code in ("M1", "M4", "M2", "M3"):
        name = next(m for m in meth if m.startswith(code) and "gross margin" not in m)
        R.p6(f"P5-{code}", p, "Four methods, shown separately", f"{code} effect", hm, {"method": name}, "effect_eur",
             lambda v: f_eur(v, "eur", True), "ESTIMATE")
    m3 = next(m for m in meth if m.startswith("M3"))
    R.p6("P5-C25", p, "Margin and post-promotion panel", "M3: share of 2025 events with a contaminated baseline", hm,
         {"method": m3}, "detail", lambda v: f_pct(v, 0), "ESTIMATE", _contamination_2025)
    gm = next(m for m in meth if m.startswith("M1") and "cost of the unit change" in m)
    R.p6("P5-GM", p, "Four methods, shown separately", "M1 gross margin effect", hm, {"method": gm}, "effect_eur",
         lambda v: f_eur(v, "eur", True), "ESTIMATE")

    # ------------------------------------------------------------------ Page 6 and 7 (Phase 6 tables)
    em = P6 + "root_cause_evidence_matrix.csv"
    for d in ("D01", "D02", "D03", "D04", "D05", "D06", "D07", "D08"):
        R.p6(f"P6-{d}", "6 Root-cause evidence matrix", "Evidence matrix", f"{d} financial impact", em,
             {"driver_id": d}, "estimated_impact_eur", lambda v: f_eur(v, "eur"),
             {"D05": "FACT", "D02": "HYPOTHESIS", "D06": "HYPOTHESIS", "D08": "n/a (partition, not an estimate)"}.get(
                 d, "ESTIMATE"))
    for inv in pc["investigations"]:
        d = inv["driver"]
        tag = {"D06": "FACT", "D08": "n/a (partition, not an estimate)"}.get(d, "ESTIMATE")
        R.p6(f"P7-{d}", "7 Investigation priorities", "Priorities table", f"{inv['topic']}: slice of decline", em,
             {"driver_id": d}, "estimated_impact_eur", lambda v: f_eur(v, "eur"), tag)
    return R.frame()
