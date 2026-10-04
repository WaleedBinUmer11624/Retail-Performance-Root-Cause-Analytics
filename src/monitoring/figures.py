"""Phase 9 figures (10). Each shows the actual value, its baseline, the selected threshold and the alerts by severity.

Colour: series use the dataviz reference palette (blue #2a78d6 actual, grey baseline); severity uses the reserved
status steps (WATCH #fab219, WARNING #ec835a, CRITICAL #d03b3b) and always carries a text label in the legend, so
colour is never the only signal. One y-axis per panel; two measures of different scale go in separate panels.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.colors import BoundaryNorm, ListedColormap  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

INK, INK2, MUTED, GRID, SURFACE = "#0b0b0b", "#52514e", "#8f8d87", "#e4e3df", "#fcfcfb"
BLUE, ORANGE, BASE = "#2a78d6", "#eb6834", "#8f8d87"
SEV = {"WATCH": "#fab219", "WARNING": "#ec835a", "CRITICAL": "#d03b3b"}
SEV_MARK = {"WATCH": "o", "WARNING": "s", "CRITICAL": "D"}
NORMAL_CELL = "#f0efec"
FOOT = ("Back-test replay of the weekly run (each week as the Monday 06:00 run would have seen it). Alerts are observed "
        "changes; cause not established.")


def _style(ax):
    ax.set_facecolor(SURFACE)
    ax.grid(axis="y", color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    for s in ["top", "right"]:
        ax.spines[s].set_visible(False)
    for s in ["left", "bottom"]:
        ax.spines[s].set_color(GRID)
    ax.tick_params(colors=INK2, labelsize=8, length=0)


def _fig(nrows=1, ncols=1, h=5.2, w=11, **kw):
    fig, axes = plt.subplots(nrows, ncols, figsize=(w, h), dpi=150, **kw)
    fig.patch.set_facecolor(SURFACE)
    for ax in np.atleast_1d(axes).ravel():
        _style(ax)
    return fig, axes


def _titles(fig, title, sub, foot=FOOT):
    fig.suptitle(title, x=0.06, ha="left", fontsize=12.5, color=INK, fontweight="bold", y=0.985)
    fig.text(0.06, 0.915, sub, fontsize=8.8, color=INK2, ha="left", va="top", linespacing=1.35)
    fig.text(0.06, 0.012, foot, fontsize=7.2, color=MUTED, ha="left")


def _save(fig, path: Path, top=0.83, bottom=0.12, left=0.07):
    fig.subplots_adjust(top=top, bottom=bottom, left=left, right=0.97, hspace=0.45, wspace=0.18)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, facecolor=SURFACE, metadata={"Software": None, "Creation Time": None} if path.suffix == ".png" else None)
    plt.close(fig)
    return path


def _weeks(ax, frame, cal):
    lab = dict(zip(cal["t"], cal["retail_year"].astype(int).astype(str) + "-W" + cal["retail_week"].astype(int).astype(str).str.zfill(2)))
    ts = sorted(frame["t"].unique())
    ticks = [t for t in ts if lab[t].endswith(("W01", "W09", "W18", "W27", "W36", "W45"))]
    ax.set_xticks(ticks, [lab[t] for t in ticks], fontsize=7.5)


def _alerts(ax, sc, y):
    for sev in ["WATCH", "WARNING", "CRITICAL"]:
        m = sc["severity"] == sev
        ax.scatter(sc.loc[m, "t"], y[m], s=36 if sev != "WATCH" else 26, marker=SEV_MARK[sev], color=SEV[sev],
                   edgecolor=SURFACE, linewidth=1.2, zorder=4)
    held = sc["dq_hold"].astype(bool)
    if held.any():
        ax.scatter(sc.loc[held, "t"], y[held], s=70, marker="o", facecolor="none", edgecolor=INK, linewidth=1, zorder=5)


def _legend(ax, extra=(), loc="lower left"):
    h = list(extra) + [Line2D([], [], marker=SEV_MARK[s], ls="", color=SEV[s], markersize=6, label=s) for s in SEV]
    h.append(Line2D([], [], marker="o", ls="", markerfacecolor="none", markeredgecolor=INK, markersize=7, label="DQ-held"))
    ax.legend(handles=h, fontsize=7.5, frameon=False, loc=loc, ncol=4)


def _pct(ax, dec=0):
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{100 * v:.{dec}f}%"))


# ----------------------------------------------------------------------------- 1 weekly transactions (estate EW02)
def fig_transactions(sc: pd.DataFrame, cal, thr_pct: float, path: Path, first_warning: str = ""):
    d = sc.sort_values("t")
    fig, ax = _fig()
    v, b = np.expm1(d["value"]), np.expm1(d["baseline"])
    thr = np.expm1(d["baseline"] + np.log(1 - thr_pct / 100))
    ax.plot(d["t"], v, color=BLUE, lw=2, label="Estate transactions YoY (as at the run)")
    ax.plot(d["t"], b, color=BASE, lw=1.6, ls="--", label="Baseline: trailing 13-week median of valid weeks")
    ax.plot(d["t"], thr, color=INK2, lw=1, ls=":", label=f"Threshold: {thr_pct:g}% below the baseline")
    _alerts(ax, d, v)
    ax.axhline(0, color=GRID, lw=1)
    _pct(ax)
    _weeks(ax, d, cal)
    _legend(ax, ax.get_legend_handles_labels()[0])
    _titles(fig, f"EW02 Estate transactions: first WARNING in {first_warning}, repeated through the autumn",
            "Year-on-year change in estate transactions against their own recent normal. Markers show the alert state "
            "each week.\nThe last week is DQ-held: store S16's data had not arrived when the run would have happened.")
    return _save(fig, path)


# ----------------------------------------------------------------------------- 2 S03-S05 detection timeline
def fig_cluster(sc: pd.DataFrame, cal, starts: dict, thr_pct: float, path: Path):
    fig, axes = _fig(3, 1, h=8.4, sharex=True)
    lab = dict(zip(cal["retail_week_key"], cal["t"]))
    for ax, s in zip(axes, starts):
        d = sc[sc["entity"] == s].sort_values("t")
        v, b = np.expm1(d["value"]), np.expm1(d["baseline"])
        ax.plot(d["t"], v, color=BLUE, lw=1.8, label="Peer gap (store YoY vs rest of estate)")
        ax.plot(d["t"], b, color=BASE, lw=1.4, ls="--", label="Baseline (trailing median)")
        ax.plot(d["t"], np.expm1(d["baseline"] + np.log(1 - thr_pct / 100)), color=INK2, lw=1, ls=":",
                label=f"Threshold ({thr_pct:g}% below)")
        _alerts(ax, d, v)
        st = lab[starts[s]]
        ax.axvline(st, color=INK, lw=1, ls="-", alpha=0.6)
        ax.text(st + 0.3, ax.get_ylim()[1] * 0.85, "Phase 6 change point", fontsize=7.5, color=INK2)
        ax.set_title(s, loc="left", fontsize=10, color=INK, fontweight="bold")
        _pct(ax)
    _weeks(axes[-1], sc, cal)
    _legend(axes[-1], axes[0].get_legend_handles_labels()[0], loc="lower left")
    _titles(fig, "EW01 S03, S04 and S05: when the monitor would have raised the alarm",
            "Each store's transactions YoY minus the rest of the estate, against its own normal. Cause not established "
            "from available internal data.", )
    return _save(fig, path, top=0.88, bottom=0.07)


# ----------------------------------------------------------------------------- 3 availability (EW03 category)
def fig_availability(sc: pd.DataFrame, cal, entity: str, thr_pp: float, path: Path, first_warning: str = ""):
    d = sc[sc["entity"] == entity].sort_values("t")
    fig, ax = _fig()
    ax.plot(d["t"], d["value"], color=BLUE, lw=2, label=f"{entity} availability (in-stock store-SKU cells)")
    ax.plot(d["t"], d["avail_py"], color=BASE, lw=1.5, ls="--", label="Same week last year")
    ax.plot(d["t"], d["avail_trailing"], color=ORANGE, lw=1.2, ls="-.", label="Trailing 8-week mean")
    ax.plot(d["t"], d["baseline"] - thr_pp / 100, color=INK2, lw=1, ls=":", label=f"Threshold: {thr_pp:g}pp below both")
    _alerts(ax, d, d["value"])
    _pct(ax, 1)
    _weeks(ax, d, cal)
    _legend(ax, ax.get_legend_handles_labels()[0])
    _titles(fig, f"EW03 {entity} availability: below both baselines, first WARNING in {first_warning}",
            "Share of ranged store-SKU cells in stock at the weekly snapshot. An alert needs the gap against BOTH last "
            "year and the recent trend.")
    return _save(fig, path)


# ----------------------------------------------------------------------------- 4 stock-outs (EW04 top sellers)
def fig_stockouts(sc: pd.DataFrame, cal, path: Path, category_note: str = ""):
    sc = sc[sc["retail_year"] == 2025]
    fig, axes = _fig(2, 1, h=7.4, sharex=True)
    g = sc.groupby("t").agg(cells=("value", "sum")).reset_index()
    axes[0].bar(g["t"], g["cells"], color=BLUE, width=0.8)
    axes[0].set_title("Full-week stock-out store-SKU cells among this week's top-selling 10% of SKUs", loc="left",
                      fontsize=9, color=INK)
    cnt = sc[sc["level"] >= 1].groupby(["t", "severity"]).size().unstack(fill_value=0)
    bottom = np.zeros(len(cnt))
    for s in ["WATCH", "WARNING", "CRITICAL"]:
        if s in cnt:
            axes[1].bar(cnt.index, cnt[s], bottom=bottom, color=SEV[s], width=0.8, label=s, edgecolor=SURFACE, linewidth=0.6)
            bottom += cnt[s].values
    axes[1].set_title("Top-selling SKUs in alert, by severity", loc="left", fontsize=9, color=INK)
    axes[1].legend(fontsize=7.5, frameon=False, loc="upper left", ncol=3)
    _weeks(axes[1], sc, cal)
    _titles(fig, f"EW04 Top-seller stock-outs: a replenishment check list ({category_note})",
            "A SKU alerts when it had a full-week stock-out in at least one store for 2 consecutive weeks (WARNING). "
            "The monitor flags the SKUs;\nit does not say why they ran out (no supplier or ordering data).")
    return _save(fig, path, top=0.84)


# ----------------------------------------------------------------------------- 5 faulty returns (EW05)
def fig_returns(sc: pd.DataFrame, cal, entity: str, path: Path, first_warning: str = ""):
    d = sc[sc["entity"] == entity].sort_values("t")
    fig, ax = _fig()
    ax.plot(d["t"], d["rate_cy"], color=BLUE, lw=2, label="'Faulty' units per 100 sold, trailing 4 weeks")
    ax.plot(d["t"], d["rate_py"], color=BASE, lw=1.5, ls="--", label="Same 4 weeks last year (expected rate)")
    _alerts(ax, d, d["rate_cy"])
    _weeks(ax, d, cal)
    ax.set_ylabel("per 100 units sold", fontsize=8, color=INK2)
    _legend(ax, ax.get_legend_handles_labels()[0], loc="upper left")
    _titles(fig, f"EW05 {entity}: faulty-return activity above expected range, first WARNING {first_warning}",
            "Conditional binomial test: are this window's 'Faulty' returns more than last year's rate would produce? "
            "Faulty-return activity exceeds\nexpected range and requires investigation. Return reasons are "
            "customer-stated; they do not prove a product defect. Early-2025 weeks are held (C12).")
    return _save(fig, path)


# ----------------------------------------------------------------------------- 6 margin (EW06)
def fig_margin(sc: pd.DataFrame, cal, entities: list, thr_pp: float, path: Path):
    fig, axes = _fig(len(entities), 1, h=7.6, sharex=True)
    for ax, e in zip(np.atleast_1d(axes), entities):
        d = sc[sc["entity"] == e].sort_values("t")
        ax.plot(d["t"], d["gm_pct"], color=BLUE, lw=2, label="Gross margin %, trailing 4 weeks")
        ax.plot(d["t"], d["gm_pct_py"], color=BASE, lw=1.5, ls="--", label="Same 4 weeks last year")
        ax.plot(d["t"], d["gm_pct_py"] - thr_pp / 100, color=INK2, lw=1, ls=":", label=f"Threshold ({thr_pp:g}pp below)")
        _alerts(ax, d, d["gm_pct"])
        ax.set_title(e, loc="left", fontsize=10, color=INK, fontweight="bold")
        _pct(ax)
    _weeks(np.atleast_1d(axes)[-1], sc, cal)
    _legend(np.atleast_1d(axes)[-1], np.atleast_1d(axes)[0].get_legend_handles_labels()[0])
    _titles(fig, "EW06 Gross margin %: tracked separately from revenue, alert after 4 weeks below last year",
            "Margin % against the same weeks last year. The driver (price, mix, promotions, cost) is not established by "
            "the alert.")
    return _save(fig, path, top=0.86, bottom=0.08)


# ----------------------------------------------------------------------------- 7 severity distribution
def fig_severity(summary: pd.DataFrame, path: Path):
    s = summary.copy()
    s["label"] = s["signal"] + " " + s["entity_type"]
    s = s.iloc[::-1]
    fig, ax = _fig(h=6)
    ax.grid(axis="x", color=GRID, lw=0.8)
    ax.grid(axis="y", visible=False)
    left = np.zeros(len(s))
    for sev, col in [("WATCH", "watch"), ("WARNING", "warning"), ("CRITICAL", "critical")]:
        ax.barh(s["label"], s[col], left=left, color=SEV[sev], label=sev, edgecolor=SURFACE, linewidth=1.5, height=0.66)
        left += s[col].values
    for y, (tot, u) in enumerate(zip(left, s["warning_plus_unconfirmed"])):
        ax.text(tot + 2, y, f"{int(tot)} ({int(u)} unconf.)", va="center", fontsize=7.5, color=INK2)
    ax.set_xlim(0, left.max() * 1.18)
    ax.legend(fontsize=8, frameon=False, loc="lower right")
    ax.set_xlabel("entity-weeks in alert, 2025 back-test", fontsize=8, color=INK2)
    _titles(fig, "Alert severity by signal: most alerts are WATCH, WARNING+ is concentrated in the known issues",
            "WATCH = threshold breached but not yet persistent; WARNING = persistent; CRITICAL = long, broad or large "
            "exposure.\nunconf. = WARNING or CRITICAL alerts outside every known episode (unexplained, not proven false).")
    return _save(fig, path, bottom=0.12, left=0.13)


# ----------------------------------------------------------------------------- 8 threshold sensitivity
def fig_sensitivity(sens: pd.DataFrame, family: str, selected: dict, budget: float, path: Path):
    d = sens[(sens["signal"] == "EW01") & (sens["family"] == family)].copy()
    d["thr"] = d["threshold"].astype(float)
    fig, axes = _fig(1, 2, h=5)
    cols = {1: MUTED, 2: BLUE, 3: ORANGE}
    for k, g in d.groupby("persistence_weeks"):
        g = g.sort_values("thr")
        axes[0].plot(g["thr"], g["unconfirmed_rate"], color=cols.get(k, INK2), marker="o", lw=2, label=f"{k} week(s)")
        axes[1].plot(g["thr"], g["median_detection_delay_weeks"], color=cols.get(k, INK2), marker="o", lw=2, label=f"{k} week(s)")
    axes[0].axhline(budget, color=SEV["CRITICAL"], lw=1, ls="--")
    axes[0].text(d["thr"].max(), budget + 0.012, f"budget {budget:.0%} of non-episode store-weeks", fontsize=7.5,
                 color=INK2, ha="right")
    for ax in axes:
        ax.axvline(selected["thr"], color=INK, lw=1, alpha=0.5)
        ax.set_xlabel("threshold: peer gap below baseline (%)", fontsize=8, color=INK2)
    axes[0].text(selected["thr"] + 0.3, axes[0].get_ylim()[1] * 0.9, "selected", fontsize=7.5, color=INK2)
    _pct(axes[0], 1)
    axes[0].set_title("Unconfirmed WARNING rate (alert burden)", loc="left", fontsize=9, color=INK)
    axes[1].set_title("Median detection delay, S03-S05 (weeks)", loc="left", fontsize=9, color=INK)
    axes[0].legend(title="persistence", fontsize=7.5, title_fontsize=7.5, frameon=False)
    _titles(fig, "EW01 threshold sensitivity: persistence cuts the alert burden most; high thresholds slow detection",
            "Selection read only the burden (left), counted on store-weeks outside the known episodes; the right "
            "panel was not used and is an in-sample check.")
    return _save(fig, path, top=0.80, bottom=0.16)


# ----------------------------------------------------------------------------- 9 heatmap store x week
def _grid_heat(ax, piv, cmap, norm):
    ax.imshow(piv.values, aspect="auto", cmap=cmap, norm=norm, interpolation="nearest")
    ax.set_yticks(range(len(piv.index)), piv.index, fontsize=7.5)
    ax.grid(False)
    for s in ax.spines.values():
        s.set_visible(False)


def fig_heatmap(sc: pd.DataFrame, cal, path: Path):
    lab = dict(zip(cal["t"], cal["retail_year"].astype(int).astype(str) + "-W" + cal["retail_week"].astype(int).astype(str).str.zfill(2)))
    piv = sc.pivot_table(index="entity", columns="t", values="level", aggfunc="max").fillna(0)
    piv = piv.sort_index()
    fig, ax = _fig(h=6)
    cmap = ListedColormap([NORMAL_CELL, SEV["WATCH"], SEV["WARNING"], SEV["CRITICAL"]])
    _grid_heat(ax, piv, cmap, BoundaryNorm([-0.5, 0.5, 1.5, 2.5, 3.5], 4))
    held = sc[sc["dq_hold"].astype(bool)]
    cols = list(piv.columns)
    ticks = [i for i, t in enumerate(cols) if lab[t].endswith(("W01", "W09", "W18", "W27", "W36", "W45"))]
    ax.set_xticks(ticks, [lab[cols[i]] for i in ticks], fontsize=7.5)
    for r in held.itertuples():
        ax.text(cols.index(r.t), list(piv.index).index(r.entity), "H", ha="center", va="center", fontsize=6, color=INK)
    ax.legend(handles=[Patch(color=NORMAL_CELL, label="NORMAL")] + [Patch(color=SEV[s], label=s) for s in SEV],
              fontsize=7.5, frameon=False, loc="upper left", bbox_to_anchor=(0, -0.08), ncol=4)
    _titles(fig, "EW01 alert heatmap by store and week: S03, S04 and S05 stand out from mid-2025",
            "Highest severity per store-week under the selected rule. H = DQ-held. Isolated WATCH cells elsewhere are "
            "unconfirmed alerts.")
    return _save(fig, path, bottom=0.16)


# ----------------------------------------------------------------------------- 10 DQ health
def fig_dq(dq: pd.DataFrame, cal, path: Path):
    lab = dict(zip(cal["t"], cal["retail_year"].astype(int).astype(str) + "-W" + cal["retail_week"].astype(int).astype(str).str.zfill(2)))
    d = dq[dq["t"].isin(cal["t"])].copy()
    d["lv"] = d["dq_sales_status"].map({"PASS": 0, "WARN": 1, "FAIL": 2})
    piv = d.pivot_table(index="store_id", columns="t", values="lv", aggfunc="max").sort_index()
    fig, ax = _fig(h=6)
    cmap = ListedColormap([NORMAL_CELL, "#86b6ef", SEV["CRITICAL"]])
    _grid_heat(ax, piv, cmap, BoundaryNorm([-0.5, 0.5, 1.5, 2.5], 3))
    cols = list(piv.columns)
    ticks = [i for i, t in enumerate(cols) if lab[t].endswith(("W01", "W18", "W36"))]
    ax.set_xticks(ticks, [lab[cols[i]] for i in ticks], fontsize=7.5)
    for r in d[d["lv"] == 2].itertuples():
        ax.text(cols.index(r.t), list(piv.index).index(r.store_id), "F", ha="center", va="center", fontsize=6, color=SURFACE)
    ax.legend(handles=[Patch(color=NORMAL_CELL, label="PASS"), Patch(color="#86b6ef", label="WARN (row-level repairs)"),
                       Patch(color=SEV["CRITICAL"], label="FAIL (F): business alerts held")],
              fontsize=7.5, frameon=False, loc="upper left", bbox_to_anchor=(0, -0.08), ncol=3)
    _titles(fig, "EW08 Data-quality gate by store and week: three failures; alerts that rely on them are held",
            "FAIL: S13 2024-W42 (two trading days missing) and S16 2025-W51/W52 (sales arrived after the run). WARN "
            "marks weeks with repaired rows\n(duplicates, prices, discounts, unknown products, missing snapshots) above "
            "tolerance: alerts go out with a note.")
    return _save(fig, path, bottom=0.16)
