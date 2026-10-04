"""Phase 5 report charts (PNG). Each chart states its unit, starts value axes at zero unless it says
otherwise, and marks estimates as ESTIMATE. The CSV behind each chart is named in its footer so the
same visual can be rebuilt in Power BI."""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402

PY_C, CY_C = "#8c96a3", "#1f5f99"
NEG_C, POS_C = "#c0504d", "#4f8f5b"
REGION_C = {"Dublin": "#1f5f99", "Leinster": "#4f8f5b", "Munster": "#d08c2e", "Connacht": "#7a5195",
            "Ulster (ROI)": "#8c96a3"}
EUR_K = FuncFormatter(lambda v, _: f"{v / 1000:,.0f}k")
EUR_M = FuncFormatter(lambda v, _: f"{v / 1e6:,.2f}M")


def _style():
    plt.rcParams.update({"font.size": 9, "axes.titlesize": 11, "axes.titleweight": "bold", "axes.spines.top": False,
                         "axes.spines.right": False, "figure.dpi": 110, "savefig.dpi": 150, "axes.grid": True,
                         "grid.alpha": 0.25, "grid.linestyle": "-"})


def _footer(fig, text):
    fig.text(0.01, 0.005, text, fontsize=7, color="#555555", ha="left", va="bottom")


def _save(fig, path: Path):
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)


def weekly_net_revenue(R, out: Path):
    w, cw, per = R["weekly"], R["cluster_weekly"], R["periods"]
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(10, 7), sharex=True, gridspec_kw={"height_ratios": [3, 2]})
    a1.plot(w["retail_week"], w["net_revenue_py"], color=PY_C, lw=2, marker="o", ms=3, label=per.label_py)
    a1.plot(w["retail_week"], w["net_revenue_cy"], color=CY_C, lw=2, marker="o", ms=3, label=per.label_cy)
    a1.set_ylim(0, None)
    a1.yaxis.set_major_formatter(EUR_K)
    a1.set_ylabel("Net revenue per week (EUR)")
    a1.set_title(f"Weekly net revenue, {per.label_py} vs {per.label_cy} (week-aligned retail weeks {per.week_from}-{per.week_to})")
    a1.legend(loc="upper left")
    cols = np.where(w["net_revenue_yoy_pct"] < 0, NEG_C, POS_C)
    a2.bar(w["retail_week"], w["net_revenue_yoy_pct"], color=cols, alpha=0.55, label="Estate weekly YoY %")
    clus = ", ".join(cw.attrs.get("cluster", []))
    a2.plot(cw["retail_week"], cw["cluster_net_revenue_yoy_pct"], color="#222222", lw=1.8, marker="s", ms=3,
            label=f"Stores {clus}")
    a2.plot(cw["retail_week"], cw["rest_net_revenue_yoy_pct"], color="#d08c2e", lw=1.8, marker="^", ms=3,
            label="All other stores")
    a2.axhline(0, color="#333333", lw=0.8)
    a2.set_ylabel("Net revenue YoY (%)")
    a2.set_xlabel("Retail week")
    a2.legend(loc="upper center", bbox_to_anchor=(0.5, -0.18), fontsize=8, ncol=3, frameon=False)
    a2.set_xticks(w["retail_week"])
    fig.subplots_adjust(bottom=0.14)
    _footer(fig, "Source: headline_trend.csv, store_cluster_weekly.csv (Phase 5). Measured values.")
    _save(fig, out / "01_weekly_net_revenue.png")


def revenue_bridge(R, out: Path):
    b = R["bridge"]
    b = b[~((b["kind"] == "effect") & (b["value_eur"].abs() < 0.01))]          # drop the zero residual bar
    fig, ax = plt.subplots(figsize=(10, 5.2))
    x = np.arange(len(b))
    bottom_axis = 0.9 * b.loc[b["kind"] == "total", "value_eur"].min()
    prev = 0.0
    for i, r in enumerate(b.itertuples()):
        if r.kind == "total":
            ax.bar(i, r.value_eur - bottom_axis, bottom=bottom_axis, color=CY_C if i else PY_C, width=0.6)
            ax.text(i, r.value_eur, f"EUR {r.value_eur / 1e6:,.3f}M", ha="center", va="bottom", fontsize=8)
            prev = r.value_eur
        else:
            start = prev
            prev = start + r.value_eur
            ax.bar(i, r.value_eur, bottom=start, color=NEG_C if r.value_eur < 0 else POS_C, width=0.6)
            ax.text(i, max(start, prev), f"{r.value_eur / 1000:+,.1f}k\n({r.contribution_pp:+.2f} pp)", ha="center",
                    va="bottom", fontsize=8)
    ax.set_xticks(x)
    ax.set_xticklabels([s.replace(" Net Revenue", "\nNet Revenue") for s in b["step"]], fontsize=8)
    ax.set_ylim(bottom_axis, b["value_eur"].max() * 1.03)
    ax.yaxis.set_major_formatter(EUR_M)
    ax.set_ylabel("Net revenue (EUR)")
    ax.set_title("Net revenue bridge: transactions x UPT x ASP (Shapley) and returns")
    ax.text(0.99, 0.97, f"Axis starts at EUR {bottom_axis / 1e6:,.2f}M (not zero)\nto make the effects readable",
            transform=ax.transAxes, ha="right", va="top", fontsize=8, color="#7a1f1f")
    _footer(fig, "Source: revenue_bridge.csv (Phase 5). Effects are exact (Shapley); residual 0. pp = percentage points of "
                 "prior-year net revenue.")
    _save(fig, out / "02_revenue_bridge.png")


def store_contribution(R, out: Path):
    s = R["store"].sort_values("net_revenue_change", ascending=False)
    fig, ax = plt.subplots(figsize=(9, 7))
    labels = [f"{r.store_id} {r.store_name} ({r.store_format})" for r in s.itertuples()]
    ax.barh(labels, s["net_revenue_change"], color=[REGION_C.get(r, "#999999") for r in s["region"]])
    for i, r in enumerate(s.itertuples()):
        ax.text(r.net_revenue_change, i, f"  {r.net_revenue_yoy_pct:+.1f}%  " if r.net_revenue_change >= 0 else
                f"{r.net_revenue_yoy_pct:+.1f}%  ", va="center", ha="left" if r.net_revenue_change >= 0 else "right",
                fontsize=7.5)
    ax.axvline(0, color="#333333", lw=0.8)
    ax.xaxis.set_major_formatter(EUR_K)
    ax.set_xlabel("Change in H2 net revenue (EUR); label = store YoY %")
    ax.set_title("Store contribution to the H2 net revenue change")
    handles = [plt.Rectangle((0, 0), 1, 1, color=c) for c in REGION_C.values()]
    ax.legend(handles, REGION_C.keys(), title="Region", loc="lower left", fontsize=8)
    lo = s["net_revenue_change"].min()
    ax.set_xlim(lo * 1.25, max(s["net_revenue_change"].max(), 0) + abs(lo) * 0.15)
    _footer(fig, "Source: store_contribution.csv (Phase 5). Bars rank stores by EUR contribution, not by YoY %.")
    _save(fig, out / "03_store_contribution.png")


def category_contribution(R, out: Path):
    cb = R["cat_bridge"].set_index("category")
    cat = R["category"].sort_values("net_revenue_change", ascending=False)
    cat = cat[cat["category"] != "Unknown"]
    comps = [("transactions_effect", "Receipts containing category", "#1f5f99"), ("upt_effect", "Units per receipt", "#7fa7c9"),
             ("asp_effect", "ASP", "#d08c2e"), ("returns_effect", "Returns", "#7a5195")]
    fig, ax = plt.subplots(figsize=(10, 5.5))
    y = np.arange(len(cat))
    pos, neg = np.zeros(len(cat)), np.zeros(len(cat))
    for col, lab, colr in comps:
        v = cb.loc[cat["category"], col].to_numpy()
        ax.barh(y, np.where(v > 0, v, 0), left=pos, color=colr, label=lab, height=0.6)
        ax.barh(y, np.where(v < 0, v, 0), left=neg, color=colr, height=0.6)
        pos += np.where(v > 0, v, 0)
        neg += np.where(v < 0, v, 0)
    ax.scatter(cat["net_revenue_change"], y, color="black", zorder=5, s=30, label="Net change")
    for i, r in enumerate(cat.itertuples()):
        ax.text(pos[i] + 3000, i, f"net {r.net_revenue_change / 1000:+,.0f}k ({r.share_of_change:.0%} of decline)",
                va="center", fontsize=7.5)
    ax.set_yticks(y)
    ax.set_yticklabels(cat["category"])
    ax.axvline(0, color="#333333", lw=0.8)
    ax.xaxis.set_major_formatter(EUR_K)
    ax.set_xlabel("EUR effect on H2 net revenue (Shapley components within each category)")
    ax.set_title("Category contribution and its components")
    ax.legend(loc="lower left", fontsize=8)
    ax.set_xlim(neg.min() * 1.1, pos.max() + 160000)
    _footer(fig, "Source: category_contribution.csv, transaction_basket_decomposition.csv (level Category).")
    _save(fig, out / "04_category_contribution.png")


def basket_kpis(R, out: Path):
    py, cy, per = R["py"], R["cy"], R["periods"]
    kpis = [("transactions", "Transactions (receipts)", "{:,.0f}"), ("aov", "Average order value (EUR)", "{:,.2f}"),
            ("upt", "Units per transaction", "{:,.3f}"), ("asp", "Average selling price (EUR)", "{:,.2f}")]
    fig, axes = plt.subplots(1, 4, figsize=(12, 3.8))
    for ax, (k, lab, fmt) in zip(axes, kpis):
        vals = [py[k], cy[k]]
        ax.bar([per.label_py, per.label_cy], vals, color=[PY_C, CY_C], width=0.6)
        for i, v in enumerate(vals):
            ax.text(i, v, fmt.format(v), ha="center", va="bottom", fontsize=8)
        ax.set_title(lab, fontsize=9)
        ax.set_ylim(0, max(vals) * 1.15)
        chg = 100 * (cy[k] / py[k] - 1)
        ax.text(0.5, 0.92, f"{chg:+.2f}%", transform=ax.transAxes, ha="center", fontsize=10, fontweight="bold",
                color=NEG_C if chg < 0 else POS_C)
        if k == "transactions":
            ax.yaxis.set_major_formatter(EUR_K)
    fig.suptitle("Traffic and basket KPIs, H2 comparison (axes start at zero)", fontweight="bold")
    _footer(fig, "Source: headline_kpis.csv (Phase 5). AOV = UPT x ASP.")
    fig.tight_layout(rect=(0, 0.03, 1, 0.95))
    _save(fig, out / "05_basket_kpis.png")


def availability_vs_revenue(R, out: Path):
    a = R["availability"]
    st = a[a["level"] == "Store"]
    assoc = R["assoc"]
    r0 = assoc[assoc["level"] == "Store"].iloc[0]
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(12, 5))
    cl = set(R["store_cluster"])
    a1.scatter(st["availability_change_pp"], st["net_revenue_yoy_pct"],
               c=["#c0504d" if k in cl else "#1f5f99" for k in st["key"]], s=35)
    placed = []
    for r in st.sort_values(["availability_change_pp", "net_revenue_yoy_pct"]).itertuples():
        x, y = r.availability_change_pp, r.net_revenue_yoy_pct
        near = sum(1 for (px, py_) in placed if abs(px - x) < 0.06 and abs(py_ - y) < 0.8)
        a1.annotate(r.key, (x, y), fontsize=7, xytext=(3, 2 - 9 * near), textcoords="offset points")
        placed.append((x, y))
    a1.axhline(0, color="#333", lw=0.7)
    a1.set_xlabel("Change in stock availability (percentage points)")
    a1.set_ylabel("Net revenue YoY (%)")
    a1.set_title("Stores: availability change vs revenue change")
    a1.text(0.02, 0.03, f"Statistical association only: Pearson r = {r0['pearson_r']:.2f}, p = {r0['pearson_p']:.2f}, "
                        f"n = {int(r0['n'])}\nRed = stores {', '.join(sorted(cl))} "
                        f"({st[st['key'].isin(cl)]['net_revenue_change'].sum() / st['net_revenue_change'].sum():.0%} of the "
                        f"decline)", transform=a1.transAxes, fontsize=7.5)
    c = a[a["level"] == "Category"].sort_values("est_lost_sales_cy_ESTIMATE")
    y = np.arange(len(c))
    a2.barh(y - 0.2, c["est_lost_sales_py_ESTIMATE"], height=0.4, color=PY_C, hatch="///", edgecolor="white",
            label=f"{R['periods'].label_py} (ESTIMATE)")
    a2.barh(y + 0.2, c["est_lost_sales_cy_ESTIMATE"], height=0.4, color=CY_C, hatch="///", edgecolor="white",
            label=f"{R['periods'].label_cy} (ESTIMATE)")
    a2.barh(y + 0.2, c["est_lost_sales_upper_cy_ESTIMATE"], height=0.4, fill=False, edgecolor="#333333", linestyle="--",
            label=f"{R['periods'].label_cy} upper bound incl. partial weeks (not evidence)")
    a2.set_yticks(y)
    a2.set_yticklabels(c["key"])
    a2.xaxis.set_major_formatter(EUR_K)
    a2.set_xlabel("Estimated lost sales (EUR), ESTIMATE")
    a2.set_title("Estimated sales lost in full-week stock-outs (BR-05 ESTIMATE)")
    a2.legend(fontsize=7.5, loc="lower right")
    _footer(fig, "Source: availability_diagnostics.csv, availability_association.csv. Hatched bars are estimates "
                 "(in-stock baseline method, docs/05).")
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    _save(fig, out / "06_availability_vs_revenue.png")


def returns_trend(R, out: Path):
    r = R["returns"]
    w = r[r["level"] == "Week"].copy()
    w["week"] = w["key"].str[1:].astype(int)
    per = R["periods"]
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(10, 6.5), sharex=True)
    a1.plot(w["week"], w["returns_value_py"], color=PY_C, lw=2, marker="o", ms=3, label=per.label_py)
    a1.plot(w["week"], w["returns_value_cy"], color=CY_C, lw=2, marker="o", ms=3, label=per.label_cy)
    a1.set_ylim(0, None)
    a1.yaxis.set_major_formatter(EUR_K)
    a1.set_ylabel("Returns value per week (EUR)")
    a1.set_title("Weekly returns: value and return rate (by return date)")
    a1.legend()
    a2.plot(w["week"], 100 * w["return_rate_value_py"], color=PY_C, lw=2, marker="o", ms=3, label=per.label_py)
    a2.plot(w["week"], 100 * w["return_rate_value_cy"], color=CY_C, lw=2, marker="o", ms=3, label=per.label_cy)
    a2.set_ylim(0, None)
    a2.set_ylabel("Return rate by value (%)")
    a2.set_xlabel("Retail week")
    a2.set_xticks(w["week"])
    _footer(fig, "Source: returns_diagnostics.csv (level Week). Returns are dated on the return, so post-Christmas "
                 "returns of December sales fall in later weeks.")
    _save(fig, out / "07_returns_trend.png")


def target_heatmap(R, out: Path):
    tw, per = R["target_weeks"], R["periods"]
    t = tw[tw["retail_year"] == per.cy_year].pivot(index="store_id", columns="retail_week",
                                                     values="target_achievement_pct") * 100
    t = t.sort_index()
    fig, ax = plt.subplots(figsize=(12, 6))
    im = ax.imshow(t.to_numpy(), cmap="RdYlGn", vmin=60, vmax=140, aspect="auto")
    ax.set_xticks(range(t.shape[1]))
    ax.set_xticklabels(t.columns, fontsize=7)
    summ = R["targets"][R["targets"]["retail_year"] == per.cy_year].set_index("store_id")
    ax.set_yticks(range(t.shape[0]))
    ax.set_yticklabels([f"{sid} ({int(summ.loc[sid, 'missed_weeks'])} of {int(summ.loc[sid, 'target_weeks'])} missed)"
                        for sid in t.index], fontsize=8)
    ax.set_xlabel("Retail week")
    ax.set_title(f"Weekly target achievement by store, {per.label_cy} (net revenue / target, %)")
    ax.grid(False)
    cb = fig.colorbar(im, ax=ax, fraction=0.025)
    cb.set_label("Achievement % (100 = on target; scale clipped at 60 and 140)")
    _footer(fig, "Source: target_weekly.csv, target_performance.csv. A missed target is an outcome, not a cause.")
    _save(fig, out / "08_target_heatmap.png")


def make_all(R: dict, out: Path) -> list[str]:
    _style()
    out.mkdir(parents=True, exist_ok=True)
    fns = [weekly_net_revenue, revenue_bridge, store_contribution, category_contribution, basket_kpis,
           availability_vs_revenue, returns_trend, target_heatmap]
    for fn in fns:
        fn(R, out)
    return sorted(p.name for p in out.glob("*.png"))
