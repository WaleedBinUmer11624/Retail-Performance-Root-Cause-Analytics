"""Phase 6 decision figures (PNG). Palette: validated reference categorical slots (blue, orange, aqua, yellow),
a blue-red diverging pair with a grey midpoint, grey for the prior year. One y-axis per panel (never dual
axes); estimates are hatched and labelled ESTIMATE; every figure names its source table so it can be rebuilt
in Power BI."""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402
from matplotlib.patches import FancyBboxPatch  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402

BLUE, ORANGE, AQUA, YELLOW = "#2a78d6", "#eb6834", "#1baf7a", "#eda100"
RED, GREY, INK, INK2, SURF = "#e34948", "#8f8d87", "#0b0b0b", "#52514e", "#fcfcfb"
DIVERGE = LinearSegmentedColormap.from_list("rb", [RED, "#f0efec", BLUE])
LEVEL_C = {"Observed change": BLUE, "Statistical association": YELLOW, "Root-cause evidence": AQUA, "Hypothesis": GREY}
EUR_K = FuncFormatter(lambda v, _: f"{v / 1000:,.0f}k")


def _style():
    plt.rcParams.update({"font.size": 9, "axes.titlesize": 11, "axes.titleweight": "bold", "axes.spines.top": False,
                         "axes.spines.right": False, "figure.dpi": 110, "savefig.dpi": 150, "axes.grid": True,
                         "grid.alpha": 0.25, "axes.edgecolor": INK2, "text.color": INK, "axes.labelcolor": INK2,
                         "xtick.color": INK2, "ytick.color": INK2, "figure.facecolor": SURF, "axes.facecolor": SURF,
                         "lines.linewidth": 2})


def _footer(fig, text):
    fig.text(0.01, 0.005, text, fontsize=7, color=INK2, ha="left", va="bottom")


def _save(fig, path):
    fig.savefig(path, bbox_inches="tight", facecolor=SURF)
    plt.close(fig)


def eur(v):
    return f"EUR {v / 1000:+,.0f}k"


def root_cause_tree(R, out):
    attr = R["overlap"]["attribution"]
    ev = R["evidence"].set_index("driver_id")
    lv = [ev.loc["D01", "evidence_level"], ev.loc["D03", "evidence_level"], ev.loc["D05", "evidence_level"],
          ev.loc["D07", "evidence_level"], "Not attributed"]
    so_robust = bool(R["sensitivity_summary"].set_index("driver").loc["electronics_stockouts_primary", "robust"])
    cause = ["Cause: UNRESOLVED (Hypothesis:\nexternal local change)",
             "Mechanism visible; net effect\nrobust" if so_robust else "Mechanism visible; net of deferred\ndemand not robust",
             "Cause: Hypothesis (batch or\nstore recording)", "Counterfactual method-dependent",
             "Mostly E&T outside the cluster"]
    kind = ["ESTIMATE vs controls", "ESTIMATE", "measured", "ESTIMATE", "remainder"]
    fig, ax = plt.subplots(figsize=(13, 5.4))
    ax.axis("off")
    ax.set_xlim(0, 1)
    ax.set_ylim(0.14, 0.97)
    total = R["cy"]["net_revenue"] - R["py"]["net_revenue"]
    ax.add_patch(FancyBboxPatch((0.36, 0.83), 0.28, 0.12, boxstyle="round,pad=0.01", fc="#eef3fb", ec=BLUE))
    ax.text(0.5, 0.89, f"H2 net revenue change\n{eur(total)} ({100 * total / R['py']['net_revenue']:+.2f}%)  FACT",
            ha="center", va="center", fontsize=10, fontweight="bold")
    n = len(attr)
    xs = np.linspace(0.1, 0.9, n)
    for i, (r, x) in enumerate(zip(attr.itertuples(), xs)):
        name = r.component.split(" (")[0]
        c = LEVEL_C.get(lv[i], GREY)
        ax.annotate("", xy=(x, 0.62), xytext=(0.5, 0.83), arrowprops=dict(arrowstyle="-", color=INK2, lw=0.8))
        ax.add_patch(FancyBboxPatch((x - 0.085, 0.42), 0.17, 0.2, boxstyle="round,pad=0.01", fc="white", ec=c, lw=2))
        ax.text(x, 0.57, "\n".join(_wrap(name, 22)), ha="center", va="center", fontsize=8, fontweight="bold")
        ax.text(x, 0.475, f"{eur(r.amount_eur)}  ({r.share_of_change:.0%})", ha="center", va="center", fontsize=8.5)
        ax.text(x, 0.44, kind[i], ha="center", va="center", fontsize=7.5, color=INK2, style="italic")
        ax.text(x, 0.36, lv[i], ha="center", va="center", fontsize=8, color=INK, bbox=dict(fc=c, ec="none", alpha=0.25))
        ax.text(x, 0.27, cause[i], ha="center", va="center", fontsize=7.5, color=INK2)
    ax.text(0.5, 0.18, "Components are mutually exclusive and add up to the total (any overlap with the store-cluster excess "
                      "would be removed; here there is none). Box outline = evidence level; the last line = what is known "
                      "about the cause.",
            ha="center", fontsize=8, color=INK2)
    ax.set_title("Root-cause tree: where the H2 decline comes from and how strong each explanation is")
    _footer(fig, "Source: driver_attribution.csv, root_cause_evidence_matrix.csv (Phase 6). No component reaches Root-cause "
                 "evidence." if not (ev["evidence_level"] == "Root-cause evidence").any() else
            "Source: driver_attribution.csv, root_cause_evidence_matrix.csv (Phase 6).")
    _save(fig, out / "01_root_cause_tree.png")


def _wrap(s, n):
    words, lines, cur = s.split(), [], ""
    for w in words:
        if len(cur) + len(w) + 1 > n and cur:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    return lines + [cur]


def driver_waterfall(R, out):
    attr = R["overlap"]["attribution"]
    py, cy = R["py"]["net_revenue"], R["cy"]["net_revenue"]
    labels = ["H2 prior\nnet revenue"] + ["\n".join(_wrap(c.split(" (")[0], 18)) for c in attr["component"]] + ["H2 current\nnet revenue"]
    fig, ax = plt.subplots(figsize=(11, 5.2))
    bottom = 0.9 * cy
    ax.bar(0, py - bottom, bottom=bottom, color=GREY, width=0.6)
    run = py
    n_comp = len(attr)
    for i, r in enumerate(attr.itertuples(), start=1):
        residual = i == n_comp
        measured = "returns" in r.component.lower()
        hatch = None if (residual or measured) else "///"
        col = GREY if residual else (RED if r.amount_eur < 0 else BLUE)
        ax.bar(i, r.amount_eur, bottom=run, color=col, width=0.6, hatch=hatch, edgecolor=SURF)
        ax.text(i, run, f"{r.amount_eur / 1000:+,.0f}k", ha="center", va="bottom", fontsize=8)
        run += r.amount_eur
    ax.bar(len(labels) - 1, cy - bottom, bottom=bottom, color=BLUE, width=0.6)
    for x, v in ((0, py), (len(labels) - 1, cy)):
        ax.text(x, v, f"EUR {v / 1e6:,.3f}M", ha="center", va="bottom", fontsize=8)
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, fontsize=7.5)
    ax.set_ylim(bottom, py * 1.02)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v / 1e6:,.2f}M"))
    ax.set_ylabel("Net revenue (EUR)")
    ax.set_title("Mutually exclusive driver attribution of the H2 net revenue change")
    ax.text(0.99, 0.97, f"Axis starts at EUR {bottom / 1e6:,.2f}M (not zero)", transform=ax.transAxes, ha="right", va="top",
            fontsize=8, color="#7a1f1f")
    _footer(fig, "Source: driver_attribution.csv. Hatched = ESTIMATE (counterfactual or model); solid red = measured change; "
                 "grey = not attributed. H&K = category-specific change (Statistical association, method-dependent).")
    _save(fig, out / "02_driver_waterfall.png")


def cluster_vs_controls(R, out):
    sc = R["store_cluster"]
    wp = sc["weekly"]
    ctl = sc["groups"][sc["primary_control"]]
    t = wp[wp["store_id"].isin(R["cluster"])].groupby("retail_week")[["transactions", "transactions_py"]].sum()
    c = wp[wp["store_id"].isin(ctl)].groupby("retail_week")[["transactions", "transactions_py"]].sum()
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(11, 7), gridspec_kw={"height_ratios": [3, 2]})
    a1.plot(t.index, 100 * (t["transactions"] / t["transactions_py"] - 1), color=ORANGE, marker="o", ms=3,
            label=f"Cluster {', '.join(R['cluster'])}")
    a1.plot(c.index, 100 * (c["transactions"] / c["transactions_py"] - 1), color=BLUE, marker="s", ms=3,
            label=f"Matched controls {', '.join(ctl)}")
    a1.axhline(0, color=INK2, lw=0.8)
    on = sc["onset"]["onset_date"]
    wk = int(R["data"]["store_day"].set_index("calendar_date").loc[on, "retail_week"].iloc[0])
    a1.axvline(wk, color=INK2, ls="--", lw=1)
    a1.text(wk + 0.3, a1.get_ylim()[0] * 0.9, f"change point {on:%d %b %Y}", fontsize=8, color=INK2)
    a1.set_ylabel("Transactions YoY (%)")
    a1.set_xlabel("Retail week (current year)")
    a1.set_title("Store cluster vs matched control stores: weekly transactions YoY")
    a1.legend(loc="lower left", fontsize=8)
    g = sc["onset"]["gap_daily"]
    a2.plot(g.index, 100 * (np.exp(g.rolling(7, center=True).mean()) - 1), color=INK2, lw=1.2, label="7-day mean gap")
    st = sc["onset"]["step"]
    a2.plot([g.index[0], on, on, g.index[-1]], [100 * (np.exp(st["mean_before"]) - 1)] * 2 + [100 * (np.exp(st["mean_after"]) - 1)] * 2,
            color=ORANGE, lw=2, label="fitted step (change-point model)")
    a2.axhline(0, color=INK2, lw=0.8)
    a2.set_ylabel("Cluster minus controls (%)")
    a2.set_title("Daily gap (same weekday last year): best fitted by a single step (ESTIMATE)", fontsize=10)
    a2.legend(loc="lower left", fontsize=8)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    _footer(fig, f"Source: cluster_weekly_did.csv, cluster_onset_daily.csv. DiD {sc['did'][(sc['primary_control'], 'ly_transactions')]['did_pct']:+.1f}% "
                 f"(placebo p {sc['placebo']['p_value_one_sided']:.4f}). Top: measured values; bottom: fitted step = ESTIMATE.")
    _save(fig, out / "03_cluster_vs_controls.png")


def category_store_heatmap(R, out):
    sch = R["data"]["store_category_h2"]
    sid = R["data"]["stores"].set_index("store_key")["store_id"]
    py, cy = R["periods"].py_year, R["periods"].cy_year
    x = sch.assign(store_id=sch["store_key"].map(sid)).pivot_table(index="store_id", columns=["category", "retail_year"],
                                                                     values="net_revenue", aggfunc="sum").fillna(0)
    ch = pd.DataFrame({c: x[(c, cy)] - x[(c, py)] for c in sorted({c for c, _ in x.columns}) if c != "Unknown"})
    fig, ax = plt.subplots(figsize=(10, 7.5))
    lim = float(np.abs(ch.to_numpy()).max())
    im = ax.imshow(ch.to_numpy(), cmap=DIVERGE, vmin=-lim, vmax=lim, aspect="auto")
    ax.set_xticks(range(ch.shape[1]))
    ax.set_xticklabels(ch.columns, rotation=25, ha="right")
    ax.set_yticks(range(ch.shape[0]))
    ax.set_yticklabels([f"{s}{' *' if s in R['cluster'] else ''}" for s in ch.index])
    for i in range(ch.shape[0]):
        for j in range(ch.shape[1]):
            v = ch.iat[i, j]
            ax.text(j, i, f"{v / 1000:+.0f}", ha="center", va="center", fontsize=7, color=INK)
    ax.grid(False)
    cb = fig.colorbar(im, ax=ax, fraction=0.03)
    cb.set_label("Net revenue change (EUR); cells labelled in EUR thousands")
    ax.set_title("Net revenue change by store and category (H2). * = store cluster")
    _footer(fig, "Source: category_store_contribution.csv. Cells add up exactly to the estate change.")
    _save(fig, out / "04_category_store_heatmap.png")


def electronics_timeline(R, out):
    tl = R["electronics"]["timeline"]
    sup = R["electronics"]["top_supplier"]
    fig, ax = plt.subplots(figsize=(11, 4.8))
    ax.plot(tl["retail_week"], 100 * tl["availability_supplier_py"], color=BLUE, ls="--", lw=1.5, label=f"{sup}, prior year")
    ax.plot(tl["retail_week"], 100 * tl["availability_supplier_cy"], color=BLUE, lw=2.2, marker="o", ms=3, label=f"{sup}, current year")
    ax.plot(tl["retail_week"], 100 * tl["availability_other_suppliers_py"], color=ORANGE, ls="--", lw=1.5,
            label="Other suppliers, prior year")
    ax.plot(tl["retail_week"], 100 * tl["availability_other_suppliers_cy"], color=ORANGE, lw=2.2, marker="s", ms=3,
            label="Other suppliers, current year")
    ax.set_ylabel("Stock availability (% of ranged store-SKU-weeks)")
    ax.set_xlabel("Retail week (H2)")
    ax.set_title(f"{R['electronics']['category']} availability by week: {sup} vs other suppliers")
    ax.legend(fontsize=8, loc="lower left", ncol=2)
    _footer(fig, "Source: electronics_weekly_timeline.csv. Axis does not start at zero (availability is a percentage near 100). Measured values.")
    _save(fig, out / "05_electronics_availability_timeline.png")


def stockout_revenue_overlay(R, out):
    tl = R["electronics"]["timeline"]
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(11, 6.5), sharex=True)
    a1.bar(tl["retail_week"], tl["category_sales_yoy_pct"], color=np.where(tl["category_sales_yoy_pct"] < 0, RED, BLUE), width=0.7)
    a1.axhline(0, color=INK2, lw=0.8)
    a1.set_ylabel("Category sales YoY (%)")
    a1.set_title(f"{R['electronics']['category']}: weekly sales change (top) and estimated sales lost to full-week stock-outs (bottom)")
    a2.bar(tl["retail_week"], tl["lost_primary_cy"], color=BLUE, hatch="///", edgecolor=SURF, width=0.7,
           label="Current year, full-week stock-outs (ESTIMATE)")
    a2.bar(tl["retail_week"], tl["lost_primary_py"], color=GREY, width=0.35, label="Prior year (ESTIMATE)")
    a2.set_ylabel("Estimated lost sales (EUR)")
    a2.set_xlabel("Retail week (H2)")
    a2.legend(fontsize=8)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    _footer(fig, "Source: electronics_weekly_timeline.csv. Two panels, one axis each; lost sales are an ESTIMATE (hatched).")
    _save(fig, out / "06_stockout_revenue_overlay.png")


def supplier_concentration(R, out):
    s = R["electronics"]["by_supplier_category"].sort_values("availability_change_pp")
    t = R["electronics"]["supplier_tests"].iloc[0]
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(12, 4.2))
    a1.barh(s["supplier_name"], s["availability_change_pp"], color=[BLUE if n == t["supplier"] else GREY for n in s["supplier_name"]])
    for i, r in enumerate(s.itertuples()):
        a1.text(0.3, i, f"{r.availability_change_pp:+.1f} pp ({int(r.skus_cy)} SKUs)", va="center", fontsize=8,
                ha="left", color=INK)
    a1.axvline(0, color=INK2, lw=0.8)
    a1.set_xlim(min(float(s["availability_change_pp"].min()) * 1.1, -1), 9)
    a1.set_xlabel("Availability change (percentage points)")
    a1.set_title("Availability change by supplier")
    a2.barh(s["supplier_name"], s["lost_primary_change"], color=[BLUE if n == t["supplier"] else GREY for n in s["supplier_name"]],
            hatch="///", edgecolor=SURF)
    for i, r in enumerate(s.itertuples()):
        a2.text(r.lost_primary_change, i, f" EUR {r.lost_primary_change:,.0f}", va="center", fontsize=8)
    a2.set_xlabel("Increase in estimated lost sales, full-week stock-outs (EUR, ESTIMATE)")
    a2.set_title("Estimated lost sales by supplier")
    a2.xaxis.set_major_formatter(EUR_K)
    a2.set_yticklabels([])
    fig.suptitle(f"Supplier concentration: {t['supplier']} SKUs' stock-out rate rose {t['difference']:+.1f} pp more than other "
                 f"suppliers' (95% CI {t['ci_low']:+.1f} to {t['ci_high']:+.1f}; permutation p {t['permutation_p_two_sided']:.3f})",
                 fontsize=10, fontweight="bold")
    fig.tight_layout(rect=(0, 0.04, 1, 0.94))
    _footer(fig, "Source: electronics_supplier_comparison.csv, electronics_supplier_test.csv. Statistical association.")
    _save(fig, out / "07_supplier_concentration.png")


def faulty_concentration(R, out):
    rt = R["returns"]
    bs = rt["by_store"].sort_values("value_change")
    coh = rt["cohort"]
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(13, 5.2))
    y = np.arange(len(bs))
    a1.barh(y - 0.2, bs["rate_per_100_py"], height=0.4, color=GREY, label="Prior year")
    a1.barh(y + 0.2, bs["rate_per_100_cy"], height=0.4, color=ORANGE, label="Current year")
    a1.set_yticks(y)
    a1.set_yticklabels([f"{s}{' (p<0.01)' if p < 0.01 else ''}" for s, p in zip(bs["store_id"], bs["p_increase"])],
                       fontsize=8)
    a1.set_xlabel("'Faulty' returned units per 100 units sold")
    a1.set_title("By store (H2, by return date)")
    a1.legend(fontsize=8, loc="lower right")
    lab = coh["sale_year_month"].astype(str)
    a2.plot(range(len(coh)), coh["rate_per_100"], color=BLUE, marker="o", ms=4)
    a2.set_xticks(range(len(coh)))
    a2.set_xticklabels([f"{s[:4]}-{s[4:]}" for s in lab], rotation=60, fontsize=7)
    a2.set_ylabel("'Faulty' returned units per 100 units sold")
    a2.set_ylim(0, None)
    a2.set_title("By sale month (cohort)")
    fig.suptitle(f"{rt['category']} '{rt['reason']}' returns: concentrated in a few stores and in recent sale cohorts",
                 fontsize=11, fontweight="bold")
    fig.tight_layout(rect=(0, 0.04, 1, 0.94))
    _footer(fig, "Source: faulty_returns_by_store.csv, faulty_returns_by_cohort.csv. 'Faulty' is the till reason, not a verified defect.")
    _save(fig, out / "08_faulty_return_concentration.png")


def promotion_counterfactual(R, out):
    pr = R["promotions"]
    w = pr["weekly"]
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(11, 7), sharex=True, gridspec_kw={"height_ratios": [3, 2]})
    a1.plot(w["retail_week"], w["sales_revenue_py"], color=GREY, lw=1.6, label="Prior year (measured)")
    a1.plot(w["retail_week"], w["sales_revenue_cy"], color=BLUE, lw=2.2, label="Current year (measured)")
    a1.plot(w["retail_week"], w["counterfactual_m1"], color=ORANGE, lw=2, ls="--",
            label=f"Current year without the H&K-specific change (M1 ESTIMATE, {pr['m1']['delta_pct_sales']:+.1f}%)")
    a1.set_ylim(0, None)
    a1.yaxis.set_major_formatter(EUR_K)
    a1.set_ylabel("Weekly sales (EUR)")
    a1.set_title(f"{pr['category']}: actual vs counterfactual weekly sales (H2)")
    a1.legend(fontsize=8, loc="upper left")
    a2.plot(w["retail_week"], 100 * w["promo_coverage_py"], color=GREY, lw=1.6, label="Prior year")
    a2.plot(w["retail_week"], 100 * w["promo_coverage_cy"], color=BLUE, lw=2.2, label="Current year")
    a2.set_ylim(0, None)
    a2.set_ylabel("Promotion coverage (% of SKU-days)")
    a2.set_xlabel("Retail week (H2)")
    a2.legend(fontsize=8)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    _footer(fig, "Source: hk_promotion_weekly.csv, hk_promotion_counterfactuals.csv. M1 = category DiD vs control categories in "
                 "the same store-weeks; other methods disagree (see sensitivity). Statistical association.")
    _save(fig, out / "09_hk_promotion_counterfactual.png")


def overlap_matrix(R, out):
    m = R["overlap"]["pairwise"]
    fig, ax = plt.subplots(figsize=(9, 7))
    lim = float(np.abs(m.to_numpy()).max())
    ax.imshow(m.to_numpy(), cmap=DIVERGE, vmin=-lim, vmax=lim)
    ax.set_xticks(range(len(m)))
    ax.set_xticklabels(m.columns, rotation=25, ha="right")
    ax.set_yticks(range(len(m)))
    ax.set_yticklabels(m.index)
    for i in range(len(m)):
        for j in range(len(m)):
            v = m.iat[i, j]
            first = (i == 0) != (j == 0)
            txt = f"{v / 1000:+,.1f}k" if abs(v) > 0.5 else ("0 (cluster below\ncontrol rate)" if first else "0 (exclusive)")
            ax.text(j, i, txt, ha="center", va="center", fontsize=8, fontweight="bold" if i == j else "normal")
    ax.grid(False)
    ax.set_title("Driver overlap (EUR): diagonal = driver estimate;\noff-diagonal = amount counted in both")
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    _footer(fig, "Source: driver_overlap_matrix.csv, driver_overlap_details.csv. Category drivers vs each other: exclusive by "
                 "construction (different category or ledger line).\nCluster excess vs drivers: overlap only where the cluster has "
                 "more of a driver than the control-store rate implies.")
    _save(fig, out / "10_driver_overlap_matrix.png")


def evidence_chart(R, out):
    ev = R["evidence"][R["evidence"]["estimated_impact_eur"].notna()].copy()
    sens = R["sensitivity_summary"].set_index("driver")
    rmap = {"D01": "store_cluster_excess", "D02": "store_cluster_excess", "D03": "electronics_stockouts_primary",
            "D05": "electronics_faulty_returns", "D06": "electronics_faulty_returns", "D07": "home_kitchen_promotion"}
    ev = ev.iloc[::-1]
    fig, ax = plt.subplots(figsize=(12, 6))
    y = np.arange(len(ev))
    for i, r in enumerate(ev.itertuples()):
        c = GREY if r.driver_id == "D09" else LEVEL_C[r.evidence_level]
        if r.evidence_level == "Hypothesis":            # outline only: the slice a hypothesis would explain, not a new amount
            ax.barh(i, r.estimated_impact_eur, height=0.55, fill=False, edgecolor=GREY, linestyle="--", lw=1.2)
        else:
            ax.barh(i, r.estimated_impact_eur, color=c, height=0.55, alpha=0.45 if r.driver_id == "D09" else 1.0,
                    hatch="///" if r.driver_id in ("D01", "D03", "D04", "D07") else None, edgecolor=SURF)
        if r.driver_id in rmap:
            s = sens.loc[rmap[r.driver_id]]
            ax.plot([s["min"], s["max"]], [i, i], color=INK, lw=1.2)
        ax.text(1.01, i, "Not attributed (residual)" if r.driver_id == "D09" else f"{r.evidence_level}", va="center", ha="left", fontsize=8, color=INK,
                transform=ax.get_yaxis_transform())
    ax.set_yticks(y)
    ax.set_yticklabels([f"{r.driver_id} " + "\n".join(_wrap(r.candidate_driver, 48)) for r in ev.itertuples()], fontsize=7.5)
    ax.axvline(0, color=INK2, lw=0.8)
    ax.xaxis.set_major_formatter(EUR_K)
    ax.set_xlabel("Estimated impact on H2 net revenue (EUR); black line = sensitivity range")
    lo = float(min(ev["estimated_impact_eur"].min(), sens["min"].min()))
    ax.set_xlim(lo * 1.1, max(0, float(sens["max"].max())) * 1.1 + 20000)
    handles = [plt.Rectangle((0, 0), 1, 1, fill=False, edgecolor=GREY, linestyle="--") if lv == "Hypothesis"
               else plt.Rectangle((0, 0), 1, 1, color=c) for lv, c in LEVEL_C.items()]
    ax.legend(handles, LEVEL_C.keys(), fontsize=8, loc="upper center", title="Evidence level",
              bbox_to_anchor=(0.5, -0.12), ncol=4, frameon=False)
    fig.tight_layout(rect=(0, 0.04, 0.9, 1))
    ax.set_title("Root-cause evidence matrix: size, range and strength of each candidate driver")
    _footer(fig, "Source: root_cause_evidence_matrix.csv, sensitivity_summary.csv. Hatched = ESTIMATE; dashed outline = "
                 "Hypothesis (repeats the slice it would explain). D04 is part of D03. Rows overlap; do not add them.")
    _save(fig, out / "11_evidence_matrix.png")


def make_all(R, out: Path) -> list[str]:
    _style()
    out.mkdir(parents=True, exist_ok=True)
    for fn in (root_cause_tree, driver_waterfall, cluster_vs_controls, category_store_heatmap, electronics_timeline,
               stockout_revenue_overlay, supplier_concentration, faulty_concentration, promotion_counterfactual,
               overlap_matrix, evidence_chart):
        fn(R, out)
    return sorted(p.name for p in out.glob("*.png"))
