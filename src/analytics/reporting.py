"""Phase 5 outputs: CSV tables, the executive summary and the validation report."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .evidence import eur, pct


# ============================================================================= CSV outputs
def _round(df: pd.DataFrame, nd: int = 6) -> pd.DataFrame:
    out = df.copy()
    for c in out.columns:
        if pd.api.types.is_float_dtype(out[c]):
            out[c] = out[c].round(nd)
    return out


def _write(df: pd.DataFrame, path: Path, files: dict):
    _round(df).to_csv(path, index=False, lineterminator="\n")
    files[path.name] = len(df)


def write_tables(R: dict, shortlist: pd.DataFrame, out: Path) -> dict:
    per = R["periods"]
    files: dict = {}
    # headline and trend
    h = R["headline"].rename(columns={per.label_py: "h2_prior", per.label_cy: "h2_current"})
    h.insert(0, "prior_period", per.label_py)
    h.insert(1, "current_period", per.label_cy)
    _write(h, out / "headline_kpis.csv", files)
    wk = R["weekly"][["retail_week", "h2_week_index", "week_start_py", "week_start_cy", "net_revenue_py", "net_revenue_cy",
                      "net_revenue_change", "net_revenue_yoy_pct", "contribution_pp", "share_of_change", "cumulative_change",
                      "cumulative_yoy_pct", "rolling_4w_yoy_pct", "sales_revenue_py", "sales_revenue_cy", "sales_revenue_yoy_pct",
                      "returns_value_py", "returns_value_cy", "returns_value_change", "gross_margin_py", "gross_margin_cy",
                      "transactions_py", "transactions_cy", "transactions_yoy_pct", "units_sold_py", "units_sold_cy",
                      "trading_store_days_py", "trading_store_days_cy"]].copy()
    bw = R["basket_week"][["retail_week", "aov_py", "aov_cy", "upt_py", "upt_cy", "asp_py", "asp_cy"]]
    wk = wk.merge(bw, on="retail_week")
    _write(wk, out / "headline_trend.csv", files)
    _write(R["context"], out / "weekly_yoy_full_year.csv", files)
    prof = pd.DataFrame([{"measure": k, "value": json.dumps(v) if isinstance(v, list) else v}
                         for k, v in R["profile"].items()])
    _write(prof, out / "trend_profile.csv", files)

    # stores, regions, formats
    s = R["store"].copy()
    for k in ("aov", "upt", "asp"):
        s[f"{k}_yoy_pct"] = 100 * (s[f"{k}_cy"] / s[f"{k}_py"] - 1)
    s["return_rate_value_change_pp"] = 100 * (s["return_rate_value_cy"] - s["return_rate_value_py"])
    s["availability_change_pp"] = 100 * (s["availability_cy"] - s["availability_py"])
    s["target_achievement_change_pp"] = 100 * (s["target_achievement_cy"] - s["target_achievement_py"])
    sb = R["seg_bridge"][R["seg_bridge"]["segment_type"] == "Store"].rename(columns={"segment_name": "store_id"})
    s = s.merge(sb[["store_id", "transactions_effect", "upt_effect", "asp_effect", "returns_effect"]], on="store_id")
    s["in_decline_cluster"] = s["store_id"].isin(R["store_cluster"])
    cols = ["contribution_rank", "store_id", "store_name", "region", "store_format", "floor_area_m2", "net_revenue_py",
            "net_revenue_cy", "net_revenue_change", "net_revenue_yoy_pct", "contribution_pp", "share_of_change", "yoy_pct_rank",
            "transactions_py", "transactions_cy", "transactions_yoy_pct", "aov_py", "aov_cy", "aov_yoy_pct", "upt_py", "upt_cy",
            "upt_yoy_pct", "asp_py", "asp_cy", "asp_yoy_pct", "return_rate_value_py", "return_rate_value_cy",
            "return_rate_value_change_pp", "availability_py", "availability_cy", "availability_change_pp",
            "target_achievement_py", "target_achievement_cy", "target_achievement_change_pp", "transactions_effect",
            "upt_effect", "asp_effect", "returns_effect", "trading_days_py", "trading_days_cy", "in_decline_cluster"]
    _write(s[cols], out / "store_contribution.csv", files)
    br = R["breadth"]
    for key, name in (("region", "Region"), ("store_format", "Format")):
        d = R["region" if key == "region" else "format"].copy()
        b = br[br["segment_type"] == name].rename(columns={"segment_name": key}).drop(columns=["segment_type", "retail_year",
                                                                                                 "stores"])
        d = d.merge(b, on=key, how="left")
        for k in ("aov", "upt", "asp"):
            d[f"{k}_yoy_pct"] = 100 * (d[f"{k}_cy"] / d[f"{k}_py"] - 1)
        d["availability_change_pp"] = 100 * (d["availability_cy"] - d["availability_py"])
        d["return_rate_value_change_pp"] = 100 * (d["return_rate_value_cy"] - d["return_rate_value_py"])
        keep = ["contribution_rank", key, "stores", "stores_declining", "net_revenue_py", "net_revenue_cy", "net_revenue_change",
                "net_revenue_yoy_pct", "contribution_pp", "share_of_change", "transactions_yoy_pct", "aov_yoy_pct",
                "upt_yoy_pct", "asp_yoy_pct", "return_rate_value_change_pp", "availability_change_pp",
                "target_achievement_py", "target_achievement_cy", "worst_store_yoy_pct", "best_store_yoy_pct",
                "worst_store_change", "best_store_change"]
        _write(d[keep], out / ("region_contribution.csv" if key == "region" else "format_contribution.csv"), files)
    _write(R["region_format"].drop(columns=["retail_year"]).sort_values(["region", "store_format"]).reset_index(drop=True),
           out / "region_format_matrix.csv", files)
    _write(R["cluster_weekly"], out / "store_cluster_weekly.csv", files)

    # categories and products
    c = R["category"].copy()
    lost = R["availability"][R["availability"]["level"] == "Category"].set_index("key")
    c["est_lost_sales_py_ESTIMATE"] = c["category"].map(lost["est_lost_sales_py_ESTIMATE"])
    c["est_lost_sales_cy_ESTIMATE"] = c["category"].map(lost["est_lost_sales_cy_ESTIMATE"])
    c["units_yoy_pct"] = 100 * (c["units_sold_cy"] / c["units_sold_py"] - 1)
    c["incidence_change_pp"] = 100 * (c["incidence_cy"] - c["incidence_py"])
    c["asp_yoy_pct"] = 100 * (c["asp_cy"] / c["asp_py"] - 1)
    c["gross_margin_pct_change_pp"] = 100 * (c["gross_margin_pct_cy"] - c["gross_margin_pct_py"])
    c["return_rate_value_change_pp"] = 100 * (c["return_rate_value_cy"] - c["return_rate_value_py"])
    c["availability_change_pp"] = 100 * (c["availability_cy"] - c["availability_py"])
    c["promo_revenue_share_change_pp"] = 100 * (c["promo_revenue_share_cy"] - c["promo_revenue_share_py"])
    c["in_product_drilldown"] = c["category"].isin(R["material_categories"])
    ccols = ["contribution_rank", "category", "net_revenue_py", "net_revenue_cy", "net_revenue_change", "net_revenue_yoy_pct",
             "contribution_pp", "share_of_change", "sales_revenue_py", "sales_revenue_cy", "transactions_with_category_py",
             "transactions_with_category_cy", "incidence_py", "incidence_cy", "incidence_change_pp", "units_sold_py",
             "units_sold_cy", "units_yoy_pct", "asp_py", "asp_cy", "asp_yoy_pct", "gross_margin_py", "gross_margin_cy",
             "gross_margin_pct_py", "gross_margin_pct_cy", "gross_margin_pct_change_pp", "returns_value_py", "returns_value_cy",
             "return_rate_value_py", "return_rate_value_cy", "return_rate_value_change_pp", "availability_py", "availability_cy",
             "availability_change_pp", "est_lost_sales_py_ESTIMATE", "est_lost_sales_cy_ESTIMATE", "promo_revenue_share_py",
             "promo_revenue_share_cy", "promo_revenue_share_change_pp", "discount_value_py", "discount_value_cy",
             "in_product_drilldown"]
    _write(c[ccols], out / "category_contribution.csv", files)
    _write(R["category_region"], out / "category_region_matrix.csv", files)
    p = R["products"].drop(columns=[c for c in R["products"].columns if c.startswith(("cost_of_sales", "transactions"))])
    _write(p, out / "product_diagnostics.csv", files)
    _write(R["range_change"], out / "range_change.csv", files)

    # bridge
    _write(R["bridge"], out / "revenue_bridge.csv", files)
    e = R["bridge_effects"]
    rows = [{"level": "Estate", "key": "Brightwater estate", **{k: e[k] for k in (
        "transactions_py", "transactions_cy", "upt_py", "upt_cy", "asp_py", "asp_cy", "transactions_effect", "upt_effect",
        "asp_effect", "shapley_residual", "returns_effect", "net_revenue_change", "reconciliation_difference")},
        "aov_py": e["upt_py"] * e["asp_py"], "aov_cy": e["upt_cy"] * e["asp_cy"],
        "aov_upt_effect": R["aov_effects"][0], "aov_asp_effect": R["aov_effects"][1]}]
    sbr = R["seg_bridge"]
    for r in sbr[sbr["segment_type"] != "Estate"].sort_values(["segment_type", "segment_name"]).itertuples():
        rows.append({"level": r.segment_type, "key": r.segment_name, "transactions_py": r.transactions_py,
                     "transactions_cy": r.transactions_cy, "upt_py": r.upt_py, "upt_cy": r.upt_cy, "asp_py": r.asp_py,
                     "asp_cy": r.asp_cy, "transactions_effect": r.transactions_effect, "upt_effect": r.upt_effect,
                     "asp_effect": r.asp_effect, "shapley_residual": r.shapley_residual, "returns_effect": r.returns_effect,
                     "net_revenue_change": r.net_revenue_change, "reconciliation_difference": r.reconciliation_difference})
    for r in R["cat_bridge"].sort_values("category").itertuples():
        rows.append({"level": "Category", "key": r.category, "transactions_py": r.transactions_py,
                     "transactions_cy": r.transactions_cy,
                     "upt_py": r.units_sold_py / r.transactions_py if r.transactions_py else np.nan,
                     "upt_cy": r.units_sold_cy / r.transactions_cy if r.transactions_cy else np.nan,
                     "asp_py": r.asp_py, "asp_cy": r.asp_cy, "transactions_effect": r.transactions_effect,
                     "upt_effect": r.upt_effect, "asp_effect": r.asp_effect, "shapley_residual": r.shapley_residual,
                     "returns_effect": r.returns_effect, "net_revenue_change": r.net_revenue_change,
                     "reconciliation_difference": r.reconciliation_difference})
    tb = pd.DataFrame(rows)
    tb["note"] = np.where(tb["level"] == "Category",
                          "transactions = receipts containing the category; upt = units per such receipt",
                          np.where(tb["level"] == "Estate", "exact Shapley bridge of the estate",
                                   "segment bridge; segment effects do not add up to the estate effects (mix)"))
    _write(tb, out / "transaction_basket_decomposition.csv", files)

    # returns, availability, promotions, targets
    _write(R["returns"], out / "returns_diagnostics.csv", files)
    _write(R["returns_attributes"].sort_values("retail_year").reset_index(drop=True), out / "returns_attributes.csv", files)
    _write(R["availability"], out / "availability_diagnostics.csv", files)
    _write(R["assoc"], out / "availability_association.csv", files)
    mech = pd.DataFrame(R["mechanism"]["by_type"])
    bt = R["backtest"]
    mech = pd.concat([mech, pd.DataFrame([{"type": "BACK-TEST: in-stock, non-promoted H2 weeks (true sales known)",
                                           "cells": bt["cells"], "actual_units": bt["actual_units"],
                                           "expected_units": bt["expected_units"], "actual_to_expected": bt["bias_ratio"],
                                           "est_lost_sales_eur": np.nan}])], ignore_index=True)
    mech["wape_store_category_week"] = [np.nan] * (len(mech) - 1) + [bt["wape_store_category_week"]]
    _write(mech, out / "lost_sales_method_check.csv", files)
    ps = R["promo_summary"]
    pu = R["promo_uplift"]
    promo = ps.merge(pu, on=["level", "key", "retail_year"], how="outer", suffixes=("", "_uplift"))
    promo["period"] = promo["retail_year"].map({per.py_year: per.label_py, per.cy_year: per.label_cy})
    promo = promo.sort_values(["level", "key", "retail_year"]).reset_index(drop=True)
    _write(promo, out / "promotion_diagnostics.csv", files)
    ev = R["promo_events"][["promotion_key", "promotion_type", "store_key", "product_id", "category", "start_date", "year",
                            "week", "n_weeks", "discount_pct", "valid", "overlapping", "baseline_weeks", "baseline_rate",
                            "promo_units", "baseline_units", "incremental_units", "baseline_price", "unit_cost",
                            "promo_discount_cost", "incremental_promo_margin", "post_units", "post_expected_units",
                            "post_weeks_used"]].rename(columns={"year": "retail_year", "week": "first_promo_week"})
    ev = ev.sort_values(["retail_year", "promotion_key", "store_key", "product_id"]).reset_index(drop=True)
    ev["start_date"] = ev["start_date"].astype(str)
    _write(ev, out / "promotion_events.csv", files)
    t = R["targets"].copy()
    t["period"] = t["retail_year"].map({per.py_year: per.label_py, per.cy_year: per.label_cy})
    _write(t, out / "target_performance.csv", files)
    tw = R["target_weeks"]
    tw = tw[tw["retail_year"].isin([per.py_year, per.cy_year])][
        ["retail_year", "retail_week", "store_id", "store_name", "region", "store_format", "net_revenue", "target_net_revenue",
         "variance_to_target", "target_achievement_pct", "is_missed"]].sort_values(["retail_year", "store_id", "retail_week"])
    tw = tw.assign(target_achievement_pct=100 * tw["target_achievement_pct"])        # percent, as in target_performance.csv
    _write(tw, out / "target_weekly.csv", files)
    _write(shortlist, out / "investigation_shortlist.csv", files)
    return files


def _describe_category(r) -> str:
    """Notable measured movements of a category, from its own numbers (no fixed wording per category)."""
    notes = []
    if r["availability_cy"] - r["availability_py"] <= -0.02:
        notes.append(f"availability down {100 * (r['availability_py'] - r['availability_cy']):.1f} pp")
    if r["return_rate_value_cy"] - r["return_rate_value_py"] >= 0.01:
        notes.append(f"return rate up {100 * (r['return_rate_value_cy'] - r['return_rate_value_py']):.1f} pp")
    if r["promo_revenue_share_cy"] - r["promo_revenue_share_py"] >= 0.05:
        notes.append(f"promotional share up {100 * (r['promo_revenue_share_cy'] - r['promo_revenue_share_py']):.1f} pp")
    if r["asp_cy"] / r["asp_py"] - 1 <= -0.03:
        notes.append(f"selling price down {100 * (1 - r['asp_cy'] / r['asp_py']):.1f}%")
    if r["units_sold_cy"] / r["units_sold_py"] - 1 <= -0.08:
        notes.append(f"units down {100 * (1 - r['units_sold_cy'] / r['units_sold_py']):.1f}%")
    return ", ".join(notes) if notes else "no single metric stands out"


def executive_summary(R: dict, sl: pd.DataFrame) -> str:
    per, py, cy = R["periods"], R["py"], R["cy"]
    total = cy["net_revenue"] - py["net_revenue"]
    e, prof = R["bridge_effects"], R["profile"]
    st, rg, cat = R["store"], R["region"], R["category"]
    cl = R["store_cluster"]
    cs = st[st["store_id"].isin(cl)]
    rest = st[~st["store_id"].isin(cl)]
    rest_yoy = 100 * (rest["net_revenue_cy"].sum() / rest["net_revenue_py"].sum() - 1)
    cl_tx = 100 * (cs["transactions_cy"].sum() / cs["transactions_py"].sum() - 1)
    common = [f"{cs[c].iloc[0]}" for c in ("region", "store_format") if cs[c].nunique() == 1]
    lt, mech, bt = R["lost_totals"], R["mechanism"], R["backtest"]
    ps = R["promo_summary"]
    pe = ps[ps["level"] == "Estate"].set_index("retail_year")
    a0, a1 = pe.loc[per.py_year], pe.loc[per.cy_year]
    rs = R["returns_summary"]
    rr = R["returns"]
    reason = rr[rr["level"] == "Category x Reason"].sort_values("returns_change", ascending=False).iloc[0]
    t = R["targets"]
    t0, t1 = t[t["retail_year"] == per.py_year], t[t["retail_year"] == per.cy_year]
    cb = R["cat_bridge"].set_index("category")
    catx = cat[cat["category"] != "Unknown"]
    av = R["availability"]
    avc = av[av["level"] == "Category"].sort_values("availability_change_pp").iloc[0]
    sup = av[(av["level"] == "Supplier x Category") & (av["sub_key"] == avc["key"])].sort_values(
        "est_lost_sales_change_ESTIMATE", ascending=False).iloc[0]
    a_store = R["assoc"][R["assoc"]["level"] == "Store"].iloc[0]
    ue = R["promo_uplift"][R["promo_uplift"]["level"] == "Estate"].set_index("retail_year")
    pk = sl[(sl["area"] == "Promotions") & (sl["metric"].str.startswith("Promo Uplift"))].iloc[0]
    k = pk["finding"].split(":")[0]
    L = []
    A = L.append
    A(f"# Brightwater Retail: {per.label_cy} performance diagnosis (Phase 5)")
    A("")
    A(f"This is an exploratory diagnosis of the {per.label_cy} net revenue decline, built only from the governed Phase 4 model. "
      "Every figure is recalculated from the data and reconciled to Phase 4, and each finding carries a BRD evidence level. "
      "This is not yet a final root-cause conclusion (that is Phase 6).")
    A("")
    A("## In brief")
    A("")
    A(f"- Net revenue fell **{eur(abs(total))} ({abs(100 * total / py['net_revenue']):.2f}%)**, from {eur(py['net_revenue'])} to "
      f"{eur(cy['net_revenue'])}.")
    A(f"- **{e['transactions_effect'] / total:.0%} of the fall is fewer transactions.** Basket size and price together explain "
      f"{(e['upt_effect'] + e['asp_effect']) / total:.0%}, and returns {e['returns_effect'] / total:.0%}.")
    A(f"- **{len(cl)} stores ({', '.join(cl)}{', all ' + ' '.join(common) if common else ''}) carry "
      f"{cs['net_revenue_change'].sum() / total:.0%} of the fall.** Their transactions fell {abs(cl_tx):.0f}%. "
      f"The other {len(rest)} stores are {'down' if rest_yoy < 0 else 'up'} {abs(rest_yoy):.1f}%.")
    top2 = catx.head(2)
    A(f"- Two categories carry {top2['share_of_change'].sum():.0%} of the fall: " + "; ".join(
        f"**{r['category']}** ({_describe_category(r)})" for _, r in top2.iterrows()) + ".")
    A("")
    A("## 1. How large is the decline?")
    A("")
    hk = R["headline"].set_index("metric")
    A("| Measure | " + per.label_py + " | " + per.label_cy + " | Change |")
    A("|---|---:|---:|---:|")
    for m, fmt in (("net_revenue", "eur"), ("sales_revenue", "eur"), ("returns_value", "eur"), ("gross_margin", "eur"),
                   ("gross_margin_pct", "pct"), ("transactions", "int"), ("aov", "eur2"), ("upt", "dec"), ("asp", "eur2")):
        r = hk.loc[m]
        a, b = r[per.label_py], r[per.label_cy]
        if fmt in ("eur", "int"):
            A(f"| {r['label']} | {a:,.0f} | {b:,.0f} | {b - a:+,.0f} ({r['yoy_pct']:+.2f}%) |")
        elif fmt == "pct":
            A(f"| {r['label']} | {100 * a:.1f}% | {100 * b:.1f}% | {100 * (b - a):+.1f} pp |")
        elif fmt == "eur2":
            A(f"| {r['label']} | {a:,.2f} | {b:,.2f} | {r['yoy_pct']:+.2f}% |")
        else:
            A(f"| {r['label']} | {a:,.3f} | {b:,.3f} | {r['yoy_pct']:+.2f}% |")
    A("")
    gm = hk.loc["gross_margin"]
    A(f"Gross margin fell {abs(gm['yoy_pct']):.1f}% ({eur(gm[per.label_cy] - gm[per.label_py])}), "
      f"{'faster' if gm['yoy_pct'] < hk.loc['net_revenue', 'yoy_pct'] else 'slower'} than revenue. The margin rate moved "
      f"{100 * (hk.loc['gross_margin_pct', per.label_cy] - hk.loc['gross_margin_pct', per.label_py]):+.1f} pp, in line with "
      f"deeper discounting (promoted-line margin {100 * a0['promo_line_margin_pct']:.1f}% to {100 * a1['promo_line_margin_pct']:.1f}%).")
    A("")
    A("## 2. When did it happen?")
    A("")
    A(f"H1 {per.cy_year} was {pct(prof['h1_yoy_pct'])} on the prior year. The decline begins with H2:")
    A("")
    A(f"- Weeks {per.week_from} to {prof['step_split_week'] - 1} average {pct(prof['step_mean_before_pct'])} a week, and weeks "
      f"{prof['step_split_week']} to {per.week_to} average {pct(prof['step_mean_after_pct'])}.")
    A(f"- {prof['weeks_negative']} of {prof['weeks']} weeks are down.")
    A(f"- The two halves of H2 are similar ({pct(prof['first_half_yoy_pct'])} and {pct(prof['second_half_yoy_pct'])}), so the "
      f"pattern is **{prof['shape']}** rather than a worsening trend.")
    A(f"- In the {len(cl)} stores above, the fall is abrupt: negative every week from week {R['cluster_onset']}.")
    A("")
    A("Weekly figures are volatile, so single weeks should not be over-read.")
    A("")
    A("## 3. Which stores and regions contributed most?")
    A("")
    A("| Store | Region / format | Change (EUR) | YoY | Share of decline | Transactions YoY |")
    A("|---|---|---:|---:|---:|---:|")
    for r in st.head(6).itertuples():
        A(f"| {r.store_id} {r.store_name} | {r.region} / {r.store_format} | {r.net_revenue_change:+,.0f} | "
          f"{r.net_revenue_yoy_pct:+.1f}% | {r.share_of_change:.0%} | {r.transactions_yoy_pct:+.1f}% |")
    A("")
    top_region = rg.iloc[0]["region"]
    rf = R["region_format"][R["region_format"]["region"] == top_region].sort_values("net_revenue_change")
    A(f"By region, {top_region} contributes {eur(rg.iloc[0]['net_revenue_change'])} ({rg.iloc[0]['share_of_change']:.0%} of the "
      "decline). By format within it: " + "; ".join(f"{r.store_format} stores {pct(r.net_revenue_yoy_pct)}"
                                                   for r in rf.itertuples()) + ". "
      "Percentage falls and EUR contributions rank stores differently. The ranking above uses EUR contribution, because "
      "that is what moves the estate total.")
    A("")
    a_ = st[st["contribution_rank"].between(4, 8)].sort_values("net_revenue_yoy_pct", ascending=False).iloc[0]
    b_ = st[st["contribution_rank"] > a_["contribution_rank"]].sort_values("net_revenue_yoy_pct").iloc[0]
    A(f"For example, {a_['store_id']} {a_['store_name']} is down {abs(a_['net_revenue_yoy_pct']):.1f}% but ranks "
      f"{int(a_['contribution_rank'])} by EUR. That is above {b_['store_id']} {b_['store_name']} (down "
      f"{abs(b_['net_revenue_yoy_pct']):.1f}%, rank {int(b_['contribution_rank'])}), because it is the larger store.")
    A("")
    A(f"**Targets.** {int(t1['persistent_underperformer'].sum())} of {len(t1)} stores missed target in at least 8 of the last "
      f"13 weeks in {per.label_cy}, against {int(t0['persistent_underperformer'].sum())} in {per.label_py}. Estate target "
      f"achievement went from {100 * t0['net_revenue'].sum() / t0['target_net_revenue'].sum():.1f}% to "
      f"{100 * t1['net_revenue'].sum() / t1['target_net_revenue'].sum():.1f}%. A missed target is an outcome, not a cause. "
      "Achievement % ranks the declining stores lowest: " + ", ".join(
        f"{r.store_id} {r.target_achievement_pct:.0f}%" for r in t1.sort_values("target_achievement_pct").head(3).itertuples()) + ".")
    A("")
    A("## 4. Which categories contributed most?")
    A("")
    A("| Category | Change (EUR) | YoY | Share of decline | Largest component | Other notable changes |")
    A("|---|---:|---:|---:|---|---|")
    for _, r in catx.iterrows():
        x = cb.loc[r["category"]]
        comp = min((("fewer receipts with the category", x["transactions_effect"]), ("lower ASP", x["asp_effect"]),
                    ("fewer units per receipt", x["upt_effect"]), ("higher returns", x["returns_effect"])), key=lambda v: v[1])
        A(f"| {r['category']} | {r['net_revenue_change']:+,.0f} | {r['net_revenue_yoy_pct']:+.1f}% | {r['share_of_change']:.0%} | "
          f"{comp[0]} ({comp[1]:+,.0f}) | {_describe_category(r)} |")
    A("")
    A("## 5. Transactions, basket size, price and returns")
    A("")
    A("The bridge splits the change using two identities: Sales Revenue = Transactions x Units per Transaction x Average "
      "Selling Price, and Net Revenue = Sales Revenue - Returns. It uses the exact Shapley method, so there is no "
      "unexplained residual.")
    A("")
    A("| Driver | EUR effect | Share of the decline | pp of prior-year revenue |")
    A("|---|---:|---:|---:|")
    for kk, lab in (("transactions_effect", "Transactions (fewer receipts)"), ("upt_effect", "Units per transaction"),
                    ("asp_effect", "Average selling price"), ("returns_effect", "Returns")):
        A(f"| {lab} | {e[kk]:+,.0f} | {e[kk] / total:.0%} | {100 * e[kk] / py['net_revenue']:+.2f} |")
    A(f"| **Total** | **{total:+,.0f}** | **100%** | **{100 * total / py['net_revenue']:+.2f}** |")
    A("")
    A(f"**Returns.** The return rate rose from {100 * py['return_rate_value']:.2f}% to {100 * cy['return_rate_value']:.2f}% of "
      f"sales. The largest increase is '{reason['sub_key']}' returns in {reason['key']} ({eur(reason['returns_change'])}, the "
      f"reason recorded at the till). {rs['concentration_cells']} store x category cells hold "
      f"{rs['concentration_share_of_gross_increase']:.0%} of the gross increase.")
    A("")
    A("## 6. Availability")
    A("")
    est = av[av["level"] == "Estate"].iloc[0]
    A(f"Estate availability moved {est['availability_change_pp']:+.2f} pp ({100 * est['availability_py']:.1f}% to "
      f"{100 * est['availability_cy']:.1f}%). {avc['key']} fell from {100 * avc['availability_py']:.1f}% to "
      f"{100 * avc['availability_cy']:.1f}%, with the largest loss on SKUs supplied by {sup['key']}.")
    A("")
    A(f"- **Mechanism (visible in the data).** In {mech['full_week_out_cells']} store-SKU-weeks with no stock at any point, "
      f"sales were {mech['full_week_out_actual_units']:.0f} units against {mech['full_week_out_expected_units']:.0f} expected.")
    A(f"- **ESTIMATE.** Sales lost in those weeks rose from {eur(lt['lost_py'])} to {eur(lt['lost_cy'])} "
      f"({(lt['lost_cy'] - lt['lost_py']) / abs(total):.0%} of the decline). This is the conservative figure.")
    A(f"- **Upper bound (not evidence).** Counting weeks that ran out part-way through gives up to {eur(lt['upper_cy'])}, but "
      "that figure cannot be separated from estimation noise.")
    A(f"- **Stores.** Availability does not explain which stores declined most. The store-level correlation is r = "
      f"{a_store['pearson_r']:.2f} (p = {a_store['pearson_p']:.2f}, "
      f"{'not ' if not a_store['significant_at_alpha'] else ''}significant).")
    A("")
    A("## 7. Promotions")
    A("")
    promo_up = a1["promo_revenue_share"] > a0["promo_revenue_share"]
    A(f"Promotions became {'more' if promo_up else 'less'} intense. The promotional share of sales went from "
      f"{100 * a0['promo_revenue_share']:.1f}% to {100 * a1['promo_revenue_share']:.1f}%, and discount cost from "
      f"{eur(a0['promo_discount_cost'])} to {eur(a1['promo_discount_cost'])} ({a1['promo_discount_cost'] / a0['promo_discount_cost']:.1f}x).")
    A("")
    body = pk["finding"].split(": ", 1)[1]
    A(f"- **{k}.** {body[:1].upper() + body[1:]}")
    A(f"- **Pull-forward.** Post-promotion weeks are {ue.loc[per.py_year, 'post_promo_vs_baseline_pct']:+.1f}% and "
      f"{ue.loc[per.cy_year, 'post_promo_vs_baseline_pct']:+.1f}% against baseline (prior and current year).")
    A("")
    A("The data shows what changed in the promotions. Whether they caused part of the decline needs a counterfactual (Phase 6).")
    A("")
    A("## 8. Which findings are confirmed?")
    A("")
    A("These findings are measured in the data (Observed change), a quantified mechanism (Root-cause evidence) or a "
      "correlation (Statistical association, which is not causation):")
    A("")
    A("| ID | Area | Finding | Evidence level |")
    A("|---|---|---|---|")
    for r in sl[sl["evidence_level"] != "Hypothesis"].itertuples():
        A(f"| {r.finding_id} | {r.area} | {r.headline} | {r.evidence_level}{' (estimate)' if r.evidence_level == 'Root-cause evidence' else ''} |")
    A("")
    A("## 9. Which findings are only hypotheses?")
    A("")
    A("These explanations are plausible, but the available data cannot confirm them:")
    A("")
    for r in sl[sl["evidence_level"] == "Hypothesis"].itertuples():
        h = r.headline.replace("Hypothesis: ", "")
        A(f"- **{r.finding_id}** {h[:1].upper() + h[1:]} *Needs:* {r.recommended_next_analysis}")
    A("")
    A("## 10. What Phase 6 should investigate")
    A("")
    A(f"1. **The {len(cl)}-store transaction fall** ({eur(cs['net_revenue_change'].sum())}). Find what changed locally around "
      "the start of H2. This needs footfall, competitor and local-event data that the model does not hold.")
    A(f"2. **{k} promotions** ({eur(float(cb.loc[k, 'asp_effect']))} ASP effect). Build a category-week counterfactual and "
      "test cannibalisation.")
    A(f"3. **{avc['key']} stock-outs** ({eur(lt['lost_cy'] - lt['lost_py'])} estimated, up to {eur(lt['upper_cy'])}). Trace "
      f"the replenishment history of the {sup['key']} SKUs and confirm with order and delivery data.")
    A(f"4. **'{reason['sub_key']}' returns in {reason['key']}** ({eur(reason['returns_change'])}). Break them down by product, "
      "supplier and original sale date.")
    A("5. **Overlaps.** Separate how much of each category's fall sits inside the store cluster, so drivers are not double "
      "counted.")
    A("")
    A("## Caveats")
    A("")
    A("- Findings describe overlapping slices of one decline. Their EUR figures must not be added together.")
    A(f"- Lost sales are an estimate. The baseline is back-tested at {bt['bias_ratio']:.3f} actual/expected in aggregate, "
      f"with {bt['wape_store_category_week']:.1%} error at store x category x week.")
    for g in R["coverage_gaps"].itertuples():
        A(f"- {g.store_id} has {int(g.normal_trading_days - g.trading_days)} missing trading days in week {int(g.retail_week)} "
          f"of {int(g.retail_year)}, which slightly {'flatters' if g.retail_year == per.py_year else 'depresses'} its YoY.")
    A("- Some SKUs have no supplier on the product master.")
    A("")
    A("Detail: `investigation_shortlist.csv` (all findings with evidence levels), `phase5_validation_report.md` (reconciliation "
      "and checks), `docs/05_exploratory_analysis.md` (methods).")
    return "\n".join(L) + "\n"


# ============================================================================= validation report
def validation_report(R: dict, checks: pd.DataFrame, freeze: pd.DataFrame, files: dict, figures: list[str],
                      model_info: dict, sql_log: list[dict], opened: dict, run_meta: dict) -> str:
    per = R["periods"]
    L = []
    A = L.append
    ok = bool((checks["status"] == "PASS").all())
    A("# Phase 5 validation report")
    A("")
    A(f"- Run: {run_meta['run_at']} ({run_meta['runtime_seconds']} s), engine: {model_info['engine']}")
    A(f"- Result: **{'ALL CHECKS PASSED' if ok else 'CHECKS FAILED'}** ({(checks['status'] == 'PASS').sum()} of {len(checks)} checks pass)")
    A(f"- Comparison: {per.label_cy} vs {per.label_py}, retail weeks {per.week_from} to {per.week_to}, week-aligned")
    A("")
    A("## 1. Frozen inputs (Phase 1 to 4)")
    A("")
    A(f"{len(freeze)} files verified against `reports/phase5/phase1_4_input_manifest.csv` (SHA-256, line endings normalised): "
      f"{(freeze['status'] == 'UNCHANGED').sum()} unchanged, {(freeze['status'] != 'UNCHANGED').sum()} changed. Full list: "
      "`input_verification.csv`.")
    A("")
    if model_info["engine"] == "duckdb":
        b = model_info["build"]
        A(f"The model was rebuilt from the frozen curated data with the Phase 4 runner (DuckDB verification engine; "
          f"curated files verified against Phase 3 lineage) and passed its own reconciliation: "
          f"{b['reconciliation'].get('PASS', 0)} of {sum(b['reconciliation'].values())} reconciliation checks and "
          f"{b['kpi_validation'].get('PASS', 0)} of {sum(b['kpi_validation'].values())} KPI checks pass. Build log: `model_build/`.")
    else:
        A("The SQL Server model built by Phase 4 was used; its reconciliation view reports all checks PASS.")
    A("")
    A("## 2. Objects used")
    A("")
    A("Phase 4 governed layer: `mart.v_performance_store_day`, `mart.v_performance_store_week`, `mart.v_performance_category_week`, "
      "`mart.v_availability_store_week`, `mart.v_availability_category_week`, `mart.v_yoy_store_week`; star schema "
      "`dw.fact_sales`, `dw.fact_returns`, `dw.fact_inventory`, `dw.fact_promotion_coverage`, `dw.dim_date`, `dw.dim_retail_week`, "
      "`dw.dim_store`, `dw.dim_product`, `dw.dim_promotion`. Phase 5 diagnostic views (schema `diag`) are created by:")
    A("")
    A("| Script | Batches | Seconds |")
    A("|---|---:|---:|")
    for s in sql_log:
        A(f"| `{s['script']}` | {s['batches']} | {s['seconds']} |")
    A("")
    A("## 3. Checks")
    A("")
    A("| Check | Group | Value | Reference | Difference | Tolerance | Status |")
    A("|---|---|---:|---:|---:|---:|---|")
    fmt = lambda v: "" if v is None or (isinstance(v, float) and np.isnan(v)) else (f"{v:,.6f}".rstrip("0").rstrip(".") if isinstance(v, float) else str(v))  # noqa: E731
    for r in checks.itertuples():
        A(f"| {r.check} | {r.group} | {fmt(r.value)} | {fmt(r.reference)} | {fmt(r.difference)} | {fmt(r.tolerance)} | {r.status} |")
    A("")
    A("## 4. Independence from the synthetic ground truth")
    A("")
    A(f"Every file opened during this run was recorded with a Python audit hook ({opened['count']} opens). Project data, "
      f"report and configuration files READ: {', '.join('`' + f + '`' for f in opened['project_files']) or 'none'}. "
      f"Files written inside the project: {len(opened['written'])}"
      f"{' (all under reports/phase5/)' if all(w.startswith('reports/phase5/') for w in opened['written']) else ''}. "
      "Refused (evaluation-only, raw, sample or "
      f"underscore-prefixed) paths opened: **{len(opened['refused'])}**. The tests repeat this check and also scan the Phase 5 "
      "code, SQL and configuration for evaluation-asset names and imports (`tests/test_phase5_analytics.py`).")
    A("")
    A("## 5. Outputs")
    A("")
    A("| File | Rows |")
    A("|---|---:|")
    for f, n in sorted(files.items()):
        A(f"| `{f}` | {n:,} |")
    A("")
    A("Figures: " + ", ".join(f"`figures/{f}`" for f in figures))
    A("")
    return "\n".join(L) + "\n"
