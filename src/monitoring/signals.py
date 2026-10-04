"""EW01-EW08 evaluation frames.

Each function returns one row per entity x retail week that the monitor could evaluate, with the metric as the weekly
run would have seen it (as-at replay), its baseline, the deviation, the DQ gate result, an exposure proxy and one
boolean column per candidate breach (`b_<rule>`). Persistence, selection and severity are applied later
(backtest.py, alerts.py), identically for every signal.

Exposure is a MONITORING PROXY (ESTIMATE), not a Phase 6 estimate: the euro size of this week's deviation under a
simple, stated assumption. It is never summed across signals (they overlap: a store alert and its region alert,
a category availability alert and its SKU stock-out alerts).
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from . import baselines as B
from .kpis import asat

LOG = np.log


def binom_sf(x: int, n: int, p: float) -> float:
    """P(X >= x) for X ~ Binomial(n, p); exact, via log-gamma (no scipy dependency)."""
    if x <= 0:
        return 1.0
    if n <= 0 or x > n:
        return 0.0
    if p <= 0:
        return 0.0
    if p >= 1:
        return 1.0
    lp, lq = math.log(p), math.log1p(-p)
    terms = [math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1) + k * lp + (n - k) * lq for k in range(x, n + 1)]
    m = max(terms)
    return float(min(1.0, math.exp(m) * sum(math.exp(t - m) for t in terms)))


def _episode_flags(df: pd.DataFrame, signal: str, entity_type: str, episodes: list, members: dict | None = None) -> pd.Series:
    flag = pd.Series(False, index=df.index)
    for ep in episodes:
        if ep["signal"] != signal or ep["entity_type"] != entity_type:
            continue
        ents = ep["entities"]
        if members and ents and ents[0] in members:
            ents = members[ents[0]]
        for e in ents:
            start = ep["start_week"][e] if isinstance(ep["start_week"], dict) else ep["start_week"]
            flag |= (df["entity"] == e) & (df["retail_week_key"] >= start) & (df["retail_week_key"] <= ep["end_week"])
    return flag


def _frame(df, signal, entity_type, cfg, members=None):
    df = df.copy()
    df["signal"], df["entity_type"] = signal, entity_type
    df["in_episode"] = _episode_flags(df, signal, entity_type, cfg["monitoring"]["episodes"], members)
    return df


# ----------------------------------------------------------------------------- EW01 store transactions (peer gap)
def ew01(T, W, dq, cfg) -> pd.DataFrame:
    c = cfg["monitoring"]["signals"]["EW01"]["candidates"]
    bl = cfg["monitoring"]["baseline"]
    cal = W["calendar"]
    sw = T["kpi_store_week"].merge(cal[["retail_week_key", "t", "retail_year", "retail_week", "py_week_key"]], on="retail_week_key")
    # as-at: each week as its own run saw it
    sw = asat(sw, ["transactions", "sales_revenue"], sw["run_time"])
    sw = sw.merge(dq[["store_id", "retail_week_key", "dq_sales_status", "dq_checks_failed"]], on=["store_id", "retail_week_key"])
    fin = T["kpi_store_week"][["store_id", "retail_week_key", "transactions", "sales_revenue", "returns_value"]].rename(
        columns={"retail_week_key": "py_week_key", "transactions": "tx_py", "sales_revenue": "sales_py", "returns_value": "ret_py"})
    sw = sw.merge(fin, on=["store_id", "py_week_key"], how="left")
    pyq = dq[["store_id", "retail_week_key", "dq_sales_status"]].rename(columns={"retail_week_key": "py_week_key",
                                                                                "dq_sales_status": "dq_py_status"})
    sw = sw.merge(pyq, on=["store_id", "py_week_key"], how="left")
    sw = sw[sw["retail_year"].isin(cfg["monitoring"]["calendar"]["yoy_years"])].copy()
    sw["dq_fail"] = (sw["dq_sales_status"] == "FAIL") | (sw["dq_py_status"] == "FAIL")
    # leave-one-out peers, excluding DQ-failed stores from both years' totals
    ok = ~sw["dq_fail"]
    tot = sw[ok].groupby("retail_week_key")[["transactions", "tx_py"]].sum().rename(columns={"transactions": "tot", "tx_py": "tot_py"})
    sw = sw.merge(tot, on="retail_week_key")
    own = np.where(ok, sw["transactions"], 0.0)
    own_py = np.where(ok, sw["tx_py"], 0.0)
    sw["peer_yoy"] = LOG((sw["tot"] - own) / (sw["tot_py"] - own_py))
    with np.errstate(divide="ignore", invalid="ignore"):
        sw["yoy"] = LOG(sw["transactions"] / sw["tx_py"])
    sw["yoy"] = sw["yoy"].replace([np.inf, -np.inf], np.nan)
    sw["value"] = sw["yoy"] - sw["peer_yoy"]
    sw["entity"] = sw["store_id"]
    p = B.robust_walk_forward(sw[["entity", "t", "value", "dq_fail"]], trailing=bl["trailing_weeks"],
                              min_valid=bl["min_valid_weeks"], exclude_low=bl["guard_z_adverse"],
                              exclude_high=bl["guard_z_other"], pooled=True,
                              hold_release_weeks=bl["hold_release_weeks"], hold_release_z=bl["hold_release_z"])
    sw = sw.merge(p[["entity", "t", "baseline", "scale", "deviation", "z", "baseline_ok", "n_valid"]], on=["entity", "t"])
    r = B.rolling_mean_sd(sw[["entity", "t", "value", "dq_fail"]].copy(), trailing=bl["trailing_weeks"], min_valid=bl["min_valid_weeks"])
    sw = sw.merge(r[["entity", "t", "z_roll"]], on=["entity", "t"])
    net = sw["sales_revenue"] - sw["returns_value"]
    sw["actual_value"] = sw["transactions"]
    sw["baseline_value"] = sw["transactions"] * np.exp(-sw["deviation"])       # transactions at the store's usual peer gap
    sw["variance"] = sw["actual_value"] - sw["baseline_value"]
    sw["variance_pct"] = np.expm1(sw["deviation"])
    sw["exposure"] = np.where(sw["deviation"] < 0, net * (np.exp(-sw["deviation"]) - 1), 0.0)
    sw["entity_weekly_revenue"] = sw["sales_py"] - sw["ret_py"]
    for x in c["threshold_pct"]:
        sw[f"b_gap{x}"] = sw["deviation"] <= LOG(1 - x / 100)
        sw[f"b_yoy{x}"] = sw["yoy"] <= LOG(1 - x / 100)
    for z in c["robust_z"]:
        sw[f"b_rz{z}"] = sw["z"] <= -z
        sw[f"b_zroll{z}"] = sw["z_roll"] <= -z
    sw = cusum(sw, c["cusum_k"], c["cusum_h"])
    sw = online_changepoint(sw, c["changepoint_min_segment"], c["changepoint_bic_delta"])
    sw["metric"] = "peer gap in transactions YoY (log)"
    sw["dq_status"] = np.where(sw["dq_fail"], "FAIL", np.where(sw["dq_sales_status"] == "WARN", "WARN", "PASS"))
    sw["dq_note"] = np.where(sw["dq_py_status"] == "FAIL", "Prior-year week failed DQ; YoY not trusted. ", "") + sw["dq_checks_failed"].fillna("")
    return _frame(sw, "EW01", "store", cfg)


def cusum(df: pd.DataFrame, k: float, hs: list) -> pd.DataFrame:
    """One-sided lower CUSUM on the robust z of each entity: S_t = max(0, S_(t-1) - z_t - k). DQ-failed weeks and weeks
    without a baseline leave S unchanged. Alarm while S_t >= h (the alarm stays on while the shift persists)."""
    df = df.sort_values(["entity", "t"]).copy()
    S = np.zeros(len(df))
    prev_e, s = None, 0.0
    for i, (e, z, bad) in enumerate(zip(df["entity"], df["z"], df["dq_fail"])):
        if e != prev_e:
            s = 0.0
        if pd.notna(z) and not bad:
            s = max(0.0, s - z - k)
        S[i] = s
        prev_e = e
    df["cusum"] = S
    for h in hs:
        df[f"b_cusum{h}"] = df["cusum"] >= h
    return df


def online_changepoint(df: pd.DataFrame, min_seg: int, deltas: list) -> pd.DataFrame:
    """At each week t, using only weeks up to t, fit one downward step in the entity's series (best split by SSE) and
    compare with a flat mean: stat = n*ln(SSE0/SSE1) - 2*ln(n). Alarm when stat >= delta, the step is downward with
    at least `min_seg` weeks after it, and week t itself is still at least half the step below the pre-step mean. The
    estimated step week is kept (it dates the change retrospectively)."""
    df = df.sort_values(["entity", "t"]).copy()
    stat = np.full(len(df), np.nan)
    tau = np.full(len(df), np.nan)
    step = np.full(len(df), np.nan)
    pre = np.full(len(df), np.nan)
    pos = 0
    for e, g in df.groupby("entity", sort=False):
        vals, ts, bad = g["value"].values, g["t"].values, g["dq_fail"].values
        for j in range(len(g)):
            use = [(ts[i], vals[i]) for i in range(j + 1) if not bad[i] and not np.isnan(vals[i])]
            n = len(use)
            if n >= 2 * min_seg + 2:
                y = np.array([v for _, v in use])
                sse0 = float(((y - y.mean()) ** 2).sum())
                best = None
                for s in range(min_seg + 2, n - min_seg + 1):
                    a, b = y[:s], y[s:]
                    sse1 = float(((a - a.mean()) ** 2).sum() + ((b - b.mean()) ** 2).sum())
                    if best is None or sse1 < best[0]:
                        best = (sse1, s, b.mean() - a.mean(), a.mean())
                if best and best[0] > 0 and sse0 > 0:
                    stat[pos + j] = n * math.log(sse0 / best[0]) - 2 * math.log(n)
                    tau[pos + j] = use[best[1]][0]
                    step[pos + j] = best[2]
                    pre[pos + j] = best[3]
        pos += len(g)
    df["cp_stat"], df["cp_tau_t"], df["cp_step"], df["cp_pre_mean"] = stat, tau, step, pre
    # off-switch (review finding M3): the alarm is on only while THIS week is still on the lower level, i.e. at least
    # half the estimated step below the pre-step mean; a recovered week switches it off even though the growing
    # history still contains the step
    still_low = (df["value"] - df["cp_pre_mean"]) <= df["cp_step"] / 2
    for d in deltas:
        df[f"b_cp{d}"] = (df["cp_stat"] >= d) & (df["cp_step"] < 0) & still_low.fillna(False)
    return df


# ----------------------------------------------------------------------------- EW02 estate / region / format
def ew02(T, W, dq, cfg) -> pd.DataFrame:
    c = cfg["monitoring"]["signals"]["EW02"]["candidates"]
    bl = cfg["monitoring"]["baseline"]
    cal = W["calendar"]
    sw = T["kpi_store_week"].merge(cal[["retail_week_key", "t", "retail_year", "retail_week", "py_week_key"]], on="retail_week_key")
    sw = asat(sw, ["transactions", "sales_revenue"], sw["run_time"])
    sw = sw.merge(dq[["store_id", "retail_week_key", "dq_sales_status"]], on=["store_id", "retail_week_key"])
    fin = T["kpi_store_week"][["store_id", "retail_week_key", "transactions", "sales_revenue", "returns_value"]].rename(
        columns={"retail_week_key": "py_week_key", "transactions": "tx_py", "sales_revenue": "sales_py", "returns_value": "ret_py"})
    sw = sw.merge(fin, on=["store_id", "py_week_key"], how="left")
    pyq = dq[["store_id", "retail_week_key", "dq_sales_status"]].rename(columns={"retail_week_key": "py_week_key", "dq_sales_status": "dq_py"})
    sw = sw.merge(pyq, on=["store_id", "py_week_key"], how="left")
    sw = sw[sw["retail_year"].isin(cfg["monitoring"]["calendar"]["yoy_years"])]
    frames = []
    groups = [("estate", lambda d: pd.Series("Estate", index=d.index)), ("region", lambda d: d["region"]),
              ("format", lambda d: d["store_format"])]
    for etype, key in groups:
        d = sw.assign(entity=key(sw))
        d["bad"] = (d["dq_sales_status"] == "FAIL") | (d["dq_py"] == "FAIL")
        g = d.groupby(["entity", "retail_week_key", "t", "retail_year", "retail_week"]).agg(
            transactions=("transactions", "sum"), tx_py=("tx_py", "sum"), sales=("sales_revenue", "sum"),
            returns=("returns_value", "sum"), sales_py=("sales_py", "sum"), ret_py=("ret_py", "sum"),
            dq_fail=("bad", "any"), failing=("store_id", lambda s: ", ".join(sorted(s[d.loc[s.index, "bad"]]))),
            dq_warn=("dq_sales_status", lambda s: (s == "WARN").any())).reset_index()
        g["value"] = LOG(g["transactions"] / g["tx_py"])
        p = B.robust_walk_forward(g[["entity", "t", "value", "dq_fail"]], trailing=bl["trailing_weeks"],
                                  min_valid=bl["min_valid_weeks"], exclude_low=bl["guard_z_adverse"],
                                  exclude_high=bl["guard_z_other"], pooled=False,
                                  hold_release_weeks=bl["hold_release_weeks"], hold_release_z=bl["hold_release_z"])
        g = g.merge(p[["entity", "t", "baseline", "scale", "deviation", "z", "baseline_ok"]], on=["entity", "t"])
        g["entity_type"] = etype
        frames.append(g)
    df = pd.concat(frames, ignore_index=True)
    net = df["sales"] - df["returns"]
    df["actual_value"] = df["transactions"]
    df["baseline_value"] = df["transactions"] * np.exp(-df["deviation"])
    df["variance"] = df["actual_value"] - df["baseline_value"]
    df["variance_pct"] = np.expm1(df["deviation"])
    df["exposure"] = np.where(df["deviation"] < 0, net * (np.exp(-df["deviation"]) - 1), 0.0)
    df["entity_weekly_revenue"] = df["sales_py"] - df["ret_py"]
    for x in c["threshold_pct"]:
        df[f"b_yoydev{x}"] = df["deviation"] <= LOG(1 - x / 100)
    df["metric"] = "transactions YoY (log) vs own trailing 13-week median"
    df["dq_status"] = np.where(df["dq_fail"], "FAIL", np.where(df["dq_warn"], "WARN", "PASS"))
    df["dq_note"] = np.where(df["dq_fail"], "Incomplete totals: DQ gate failed for " + df["failing"], "")
    out = []
    for etype in ["estate", "region", "format"]:
        out.append(_frame(df[df["entity_type"] == etype], "EW02", etype, cfg))
    return pd.concat(out, ignore_index=True)


# ----------------------------------------------------------------------------- EW03 availability (category, supplier)
def _guarded_trailing(df: pd.DataFrame, n: int, guard: float) -> pd.Series:
    """Trailing mean of the previous `n` VALID weeks (at least n // 2), walking forward per entity. A week is not valid
    for later baselines when its DQ gate failed or when it is below its own trailing mean by `guard` or more (and, where
    a prior year exists, below last year by `guard` too): a shortage must not become the baseline it is judged
    against (review finding M2). Week t never enters its own baseline."""
    out = pd.Series(np.nan, index=df.index)
    for _, g in df.sort_values("t").groupby(["entity_type", "entity"], sort=False):
        hist = []
        for i, v, py, bad in zip(g.index, g["value"], g["avail_py"], g["dq_fail"]):
            h = hist[-n:]
            tr = float(np.mean(h)) if len(h) >= n // 2 else np.nan
            out.at[i] = tr
            low = pd.notna(tr) and v - tr <= -guard and (pd.isna(py) or v - py <= -guard)
            if not bad and pd.notna(v) and not low:
                hist.append(v)
    return out


def ew03(T, W, est_dq, cfg) -> pd.DataFrame:
    s = cfg["monitoring"]["signals"]["EW03"]
    cal = W["calendar"]
    pw = asat(T["kpi_product_week"], ["sales_revenue", "units"], T["kpi_product_week"]["run_time"])
    cat = pw.groupby(["category", "retail_week_key"])[["ranged_cells", "in_stock_cells", "full_week_stockout_cells", "sales_revenue"]].sum().reset_index()
    cat = cat[cat["category"] != "Unknown"].rename(columns={"category": "entity"}).assign(entity_type="category")
    sup = pw.groupby(["supplier_name", "retail_week_key"])[["ranged_cells", "in_stock_cells", "full_week_stockout_cells", "sales_revenue"]].sum().reset_index()
    sup = sup[sup["supplier_name"] != "Unknown supplier"].rename(columns={"supplier_name": "entity"}).assign(entity_type="supplier")
    df = pd.concat([cat, sup], ignore_index=True).merge(cal[["retail_week_key", "t", "retail_year", "retail_week", "py_week_key"]],
                                                        on="retail_week_key")
    df = df[df["ranged_cells"] > 0].copy()
    df["value"] = df["in_stock_cells"] / df["ranged_cells"]
    df = df.merge(est_dq[["retail_week_key", "dq_inventory_status"]], on="retail_week_key", how="left")
    df["dq_fail"] = df["dq_inventory_status"] == "FAIL"
    py = df[["entity_type", "entity", "retail_week_key", "value"]].rename(columns={"retail_week_key": "py_week_key", "value": "avail_py"})
    df = df.merge(py, on=["entity_type", "entity", "py_week_key"], how="left")
    df = df.sort_values(["entity_type", "entity", "t"])
    n = s["trailing_mean_weeks"]
    df["avail_trailing"] = _guarded_trailing(df, n, cfg["monitoring"]["baseline"]["trailing_guard_pp"] / 100)
    df["sales_per_instock_cell"] = df.groupby(["entity_type", "entity"]).apply(
        lambda g: (g["sales_revenue"].shift(1).rolling(n, min_periods=2).sum() /
                   g["in_stock_cells"].shift(1).rolling(n, min_periods=2).sum())).reset_index(level=[0, 1], drop=True)
    df = df[df["retail_year"].isin(cfg["monitoring"]["calendar"]["yoy_years"])].copy()
    gap_py = df["value"] - df["avail_py"]
    gap_tr = df["value"] - df["avail_trailing"]
    df["deviation"] = np.maximum(gap_py, gap_tr)      # below BOTH baselines: the smaller of the two drops
    df["baseline"] = np.minimum(df["avail_py"], df["avail_trailing"])
    df["baseline_ok"] = df["avail_py"].notna() & df["avail_trailing"].notna()
    df["actual_value"], df["baseline_value"] = df["value"], df["avail_py"]
    df["variance"] = df["value"] - df["avail_py"]
    df["variance_pct"] = df["variance"]
    df["exposure"] = np.maximum(0.0, df["avail_py"] - df["value"]) * df["ranged_cells"] * df["sales_per_instock_cell"]
    df["entity_weekly_revenue"] = df["sales_revenue"]
    for x in s["candidates"]["threshold_pp"]:
        df[f"b_pp{x}"] = df["deviation"] <= -x / 100
    df["metric"] = "availability vs last year and trailing 8 weeks (pp, smaller gap)"
    df["dq_status"] = df["dq_inventory_status"].fillna("PASS")
    df["dq_note"] = np.where(df["dq_fail"], "A store had no stock snapshot this week.", "")
    out = [_frame(df[df["entity_type"] == et], "EW03", et, cfg) for et in ["category", "supplier"]]
    return pd.concat(out, ignore_index=True)


# ----------------------------------------------------------------------------- EW04 top-seller full-week stock-outs
def ew04(T, W, est_dq, cfg, phase6_skus: list) -> pd.DataFrame:
    s = cfg["monitoring"]["signals"]["EW04"]
    cal = W["calendar"]
    pw = T["kpi_product_week"].merge(cal[["retail_week_key", "t", "retail_year", "retail_week"]], on="retail_week_key")
    pw = asat(pw, ["sales_revenue", "units"], pw["run_time"])   # ranking and exposure as the run saw them (m1)
    pw = pw.sort_values(["product_id", "t"]).copy()
    g = pw.groupby("product_id")
    rk, ex = s["ranking_weeks"], s["exposure_weeks"]
    pw["sales_trailing"] = g["sales_revenue"].transform(lambda v: v.shift(1).rolling(rk, min_periods=rk).sum())
    num = g["sales_revenue"].transform(lambda v: v.shift(1).rolling(ex, min_periods=2).sum())
    den = g["in_stock_cells"].transform(lambda v: v.shift(1).rolling(ex, min_periods=2).sum())
    pw["sales_per_instock_cell"] = num / den.replace(0, np.nan)
    pw = pw[pw["sales_trailing"].notna()].copy()
    # top sellers re-ranked each week from the previous 13 weeks only
    pw["rank_pct"] = pw.groupby("t")["sales_trailing"].rank(ascending=False, pct=True, method="first")
    top = pw[(pw["rank_pct"] <= s["top_seller_share"]) & (pw["sales_trailing"] > 0)].copy()
    top = top.merge(est_dq[["retail_week_key", "dq_inventory_status"]], on="retail_week_key", how="left")
    top["entity"] = top["product_id"]
    top["value"] = top["full_week_stockout_cells"]
    top["dq_fail"] = top["dq_inventory_status"] == "FAIL"
    top["baseline"] = 0.0
    top["baseline_ok"] = True
    top["deviation"] = top["value"]
    top["actual_value"], top["baseline_value"] = top["value"], 0.0
    top["variance"] = top["value"]
    top["variance_pct"] = np.nan
    top["exposure"] = top["value"] * top["sales_per_instock_cell"].fillna(0)
    top["entity_weekly_revenue"] = top["sales_trailing"] / rk
    for m in s["candidates"]["min_stores"]:
        top[f"b_st{m}"] = top["value"] >= m
    top["metric"] = "stores with a full-week stock-out (top-selling SKU)"
    top["dq_status"] = top["dq_inventory_status"].fillna("PASS")
    top["dq_note"] = ""
    members = {"ELECTRONICS_SKUS_WITH_PHASE6_STOCKOUTS": phase6_skus}
    return _frame(top, "EW04", "product", cfg, members)


# ----------------------------------------------------------------------------- window DQ materiality
def _window_dq(d: pd.DataFrame, key: str, win: int) -> pd.DataFrame:
    """Rolling share of the window's expected lines that failed store-weeks are missing (needs lines_expected,
    lines_missing, bad, sorted by key and t). Adds dq_any_w (any failed week in the window) and dq_missing_share_w."""
    g = d.groupby(key)
    d["dq_any_w"] = g["bad"].transform(lambda v: v.astype(int).rolling(win, min_periods=1).max().astype(bool))
    miss = g["lines_missing"].transform(lambda v: v.fillna(0).rolling(win, min_periods=1).sum())
    exp_ = g["lines_expected"].transform(lambda v: v.fillna(0).rolling(win, min_periods=1).sum())
    d["dq_missing_share_w"] = (miss / exp_.replace(0, np.nan)).fillna(0.0)
    return d


def _apply_window_dq(d2: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """Material window failure (this year or last) holds the alert; an immaterial one is a WARN with a note."""
    mat = cfg["monitoring"]["dq"]["window_materiality_share"]
    share = np.maximum(d2["dq_missing_share_w"].fillna(0), d2["dq_missing_share_py"].fillna(0))
    anyf = d2["dq_any_w"].fillna(False).astype(bool) | d2["dq_any_py"].fillna(False).astype(bool)
    d2["dq_window_missing_share"] = share
    d2["dq_fail"] = anyf & (share > mat)
    d2["dq_window_warn"] = anyf & ~d2["dq_fail"]
    d2["dq_note"] = np.where(
        d2["dq_fail"], [f"A failed store-week in the window (this year or last) is missing {100 * x:.1f}% of the window's lines."
                        for x in share],
        np.where(d2["dq_window_warn"], [f"Window includes a failed store-week missing {100 * x:.1f}% of its lines (below the "
                                         f"{100 * mat:.0f}% materiality level; ratio still used)." for x in share], ""))
    return d2


def _returns_warmup(d2: pd.DataFrame, cal: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """C12: hold returns-based comparisons whose prior-year window touches the returns warm-up weeks at the start of
    history (returns of pre-extract sales are missing there, so last year's rate is understated)."""
    win = cfg["monitoring"]["baseline"]["rolling_window_weeks"]
    warm = cfg["monitoring"]["dq"]["returns_history_warmup_weeks"]
    t0 = int(cal["t"].min())
    tpy = d2["py_week_key"].map(dict(zip(cal["retail_week_key"], cal["t"])))
    inc = (tpy - (win - 1)) < t0 + warm
    note = (f"C12 prior-year returns history incomplete: last year's window touches the first {warm} weeks of history, "
            "when returns of sales made before the extract start are missing.")
    d2["returns_py_incomplete"] = inc.fillna(False).astype(bool)
    d2["dq_note"] = np.where(d2["returns_py_incomplete"], note + " " + d2["dq_note"].fillna("").astype(str), d2["dq_note"])
    d2["dq_fail"] = d2["dq_fail"].astype(bool) | d2["returns_py_incomplete"]
    return d2


# ----------------------------------------------------------------------------- EW05 'Faulty' returns
def _faulty_window(d: pd.DataFrame, keys: list, win: int) -> pd.DataFrame:
    d = d.sort_values(keys + ["t"]).copy()
    g = d.groupby(keys)
    for c in ["faulty_units", "units", "faulty_value"]:
        d[f"{c}_w"] = g[c].transform(lambda v: v.rolling(win, min_periods=win).sum())
    return d


def ew05(T, W, dq, est_dq, cfg) -> pd.DataFrame:
    s = cfg["monitoring"]["signals"]["EW05"]
    win = cfg["monitoring"]["baseline"]["rolling_window_weeks"]
    cal = W["calendar"]
    frames = []
    # store level, Electronics & Tech
    sc = T["kpi_store_category_week"]
    sc = sc[sc["category"] == s["category"]].merge(cal[["retail_week_key", "t", "retail_year", "retail_week", "py_week_key"]], on="retail_week_key")
    sc = asat(sc, ["units"], sc["run_time"])
    sc = sc.merge(dq[["store_id", "retail_week_key", "dq_sales_status", "lines_expected", "lines_missing"]],
                  on=["store_id", "retail_week_key"])
    sc["bad"] = sc["dq_sales_status"] == "FAIL"
    sc = _window_dq(sc.sort_values(["store_id", "t"]), "store_id", win)
    sc = _faulty_window(sc, ["store_id"], win).rename(columns={"store_id": "entity"}).assign(entity_type="store")
    # estate level, every category
    cw = T["kpi_category_week"]
    cw = cw[cw["category"] != "Unknown"].merge(cal[["retail_week_key", "t", "retail_year", "retail_week", "py_week_key"]], on="retail_week_key")
    cw = asat(cw, ["units"], cw["run_time"])
    cw = cw.merge(est_dq[["retail_week_key", "dq_sales_status", "lines_expected", "lines_missing"]], on="retail_week_key", how="left")
    cw["bad"] = cw["dq_sales_status"] == "FAIL"
    cw = _window_dq(cw.sort_values(["category", "t"]), "category", win)
    cw = _faulty_window(cw, ["category"], win).rename(columns={"category": "entity"}).assign(entity_type="category")
    for d in (sc, cw):
        py = d[["entity", "retail_week_key", "faulty_units_w", "units_w", "faulty_value_w", "dq_any_w", "dq_missing_share_w"]].rename(
            columns={"retail_week_key": "py_week_key", "faulty_units_w": "fpy", "units_w": "upy", "faulty_value_w": "fvpy",
                     "dq_any_w": "dq_any_py", "dq_missing_share_w": "dq_missing_share_py"})
        d2 = d.merge(py, on=["entity", "py_week_key"], how="left")
        d2 = d2[d2["retail_year"].isin(cfg["monitoring"]["calendar"]["yoy_years"]) & d2["faulty_units_w"].notna() & d2["fpy"].notna()].copy()
        d2 = _returns_warmup(_apply_window_dq(d2, cfg), cal, cfg)
        x, u, xp, up = d2["faulty_units_w"], d2["units_w"], d2["fpy"], d2["upy"]
        p0 = u / (u + up)
        d2["pvalue"] = [binom_sf(int(a), int(a + b), float(p)) if (a + b) > 0 and p == p else 1.0 for a, b, p in zip(x, xp, p0)]
        d2["rate_cy"] = 100 * x / u.replace(0, np.nan)
        d2["rate_py"] = 100 * xp / up.replace(0, np.nan)
        d2["expected_units"] = u * xp / up.replace(0, np.nan)
        d2["excess_units"] = x - d2["expected_units"].fillna(0)
        d2["value"] = d2["rate_cy"]
        d2["baseline"] = d2["rate_py"]
        d2["baseline_ok"] = d2["units_w"].gt(0) & d2["upy"].gt(0)
        d2["deviation"] = d2["rate_cy"] - d2["rate_py"]
        d2["actual_value"], d2["baseline_value"] = d2["rate_cy"], d2["rate_py"]
        d2["variance"] = d2["deviation"]
        d2["variance_pct"] = d2["rate_cy"] / d2["rate_py"].replace(0, np.nan) - 1
        avg_refund = d2["faulty_value_w"] / x.replace(0, np.nan)
        d2["exposure"] = np.maximum(0.0, d2["excess_units"]) * avg_refund.fillna(0) / win   # this week's share of the window
        d2["entity_weekly_revenue"] = np.nan
        for a in s["candidates"]["alpha"]:
            for m in s["candidates"]["min_excess_units"]:
                d2[f"b_a{a}_m{m}"] = (d2["pvalue"] < a) & (d2["excess_units"] >= m)
        d2["metric"] = f"'Faulty' units per 100 sold, trailing {win} weeks vs same weeks last year"
        d2["dq_status"] = np.where(d2["dq_fail"], "FAIL", np.where(d2["dq_window_warn"], "WARN", "PASS"))
        frames.append(_frame(d2, "EW05", d2["entity_type"].iloc[0], cfg))
    return pd.concat(frames, ignore_index=True)


# ----------------------------------------------------------------------------- EW06 margin, EW07 promotions (category, 4 weeks)
def _category_windows(T, W, est_dq, cfg) -> pd.DataFrame:
    win = cfg["monitoring"]["baseline"]["rolling_window_weeks"]
    cal = W["calendar"]
    cw = T["kpi_category_week"]
    cw = cw[cw["category"] != "Unknown"].merge(cal[["retail_week_key", "t", "retail_year", "retail_week", "py_week_key"]], on="retail_week_key")
    cw = asat(cw, ["sales_revenue", "gross_amount", "discount_amount", "cost_amount", "units", "promo_revenue", "promo_lines"], cw["run_time"])
    cw["net_revenue"] = cw["sales_revenue"] - cw["returns_value"]
    cw["gross_margin"] = cw["net_revenue"] - (cw["cost_amount"] - cw["restock_cost_credit"])
    cw = cw.merge(est_dq[["retail_week_key", "dq_sales_status", "lines_expected", "lines_missing"]], on="retail_week_key", how="left")
    cw["bad"] = cw["dq_sales_status"] == "FAIL"
    cw = _window_dq(cw.sort_values(["category", "t"]), "category", win)
    g = cw.groupby("category")
    for c in ["net_revenue", "gross_margin", "gross_amount", "discount_amount", "sales_revenue", "promo_revenue", "promo_lines", "units"]:
        cw[f"{c}_w"] = g[c].transform(lambda v: v.rolling(win, min_periods=win).sum())
    wcols = [c for c in cw.columns if c.endswith("_w")]
    py = cw[["category", "retail_week_key"] + wcols].rename(
        columns={"retail_week_key": "py_week_key", "dq_any_w": "dq_any_py", "dq_missing_share_w": "dq_missing_share_py",
                 **{c: c + "_py" for c in wcols if c not in ("dq_any_w", "dq_missing_share_w")}})
    cw = cw.merge(py, on=["category", "py_week_key"], how="left")
    cw = cw[cw["retail_year"].isin(cfg["monitoring"]["calendar"]["yoy_years"]) & cw["net_revenue_w"].notna()
            & cw["net_revenue_w_py"].notna()].copy()
    cw["entity"] = cw["category"]
    cw = _apply_window_dq(cw, cfg)
    cw["gm_pct"] = cw["gross_margin_w"] / cw["net_revenue_w"]
    cw["gm_pct_py"] = cw["gross_margin_w_py"] / cw["net_revenue_w_py"]
    cw["disc"] = cw["discount_amount_w"] / cw["gross_amount_w"]
    cw["disc_py"] = cw["discount_amount_w_py"] / cw["gross_amount_w_py"]
    cw["promo_share"] = cw["promo_revenue_w"] / cw["sales_revenue_w"]
    cw["promo_share_py"] = cw["promo_revenue_w_py"] / cw["sales_revenue_w_py"]
    cw["revenue_window_yoy"] = cw["net_revenue_w"] / cw["net_revenue_w_py"] - 1
    cw["baseline_ok"] = True
    cw["dq_status"] = np.where(cw["dq_fail"], "FAIL", np.where(cw["dq_window_warn"] | (cw["dq_sales_status"] == "WARN"), "WARN", "PASS"))
    return cw


def ew06(T, W, est_dq, cfg) -> pd.DataFrame:
    s = cfg["monitoring"]["signals"]["EW06"]
    d = _returns_warmup(_category_windows(T, W, est_dq, cfg), W["calendar"], cfg)   # GM uses net revenue (returns)
    d["dq_status"] = np.where(d["dq_fail"], "FAIL", d["dq_status"])
    d["value"], d["baseline"] = d["gm_pct"], d["gm_pct_py"]
    d["deviation"] = d["gm_pct"] - d["gm_pct_py"]
    d["actual_value"], d["baseline_value"] = d["gm_pct"], d["gm_pct_py"]
    d["variance"] = d["deviation"]
    d["variance_pct"] = d["gross_margin_w"] / d["gross_margin_w_py"] - 1     # gross margin EUR change, same window
    d["gm_eur_change"] = d["gross_margin_w"] - d["gross_margin_w_py"]
    d["exposure"] = np.maximum(0.0, -d["deviation"]) * d["net_revenue"]      # this week's revenue at the window's margin gap
    d["entity_weekly_revenue"] = d["net_revenue_w_py"] / cfg["monitoring"]["baseline"]["rolling_window_weeks"]
    d["margin_only"] = d["revenue_window_yoy"] >= 0
    for x in s["candidates"]["threshold_pp"]:
        d[f"b_pp{x}"] = d["deviation"] <= -x / 100
    d["metric"] = "gross margin % (4 weeks) vs same 4 weeks last year (pp)"
    return _frame(d, "EW06", "category", cfg)


def ew07(T, W, est_dq, cfg) -> pd.DataFrame:
    s = cfg["monitoring"]["signals"]["EW07"]
    d = _category_windows(T, W, est_dq, cfg)
    d["value"], d["baseline"] = d["disc"], d["disc_py"]
    d["deviation"] = d["disc"] - d["disc_py"]
    d["actual_value"], d["baseline_value"] = d["disc"], d["disc_py"]
    d["variance"] = d["deviation"]
    d["variance_pct"] = d["promo_share"] - d["promo_share_py"]
    d["promo_lines_ratio"] = d["promo_lines_w"] / d["promo_lines_w_py"].replace(0, np.nan)
    d["exposure"] = np.maximum(0.0, d["deviation"]) * d["gross_amount"]      # extra discount this week vs last year's depth
    d["entity_weekly_revenue"] = d["net_revenue_w_py"] / cfg["monitoring"]["baseline"]["rolling_window_weeks"]
    for x in s["candidates"]["threshold_pp"]:
        d[f"b_pp{x}"] = d["deviation"] >= x / 100
    d["metric"] = "discount rate (4 weeks) vs same 4 weeks last year (pp)"
    return _frame(d, "EW07", "category", cfg)


# ----------------------------------------------------------------------------- EW08 data quality
def ew08(dq: pd.DataFrame, cfg) -> pd.DataFrame:
    d = dq.copy()
    d["entity"] = d["store_id"]
    d["value"] = d["days_asat"]
    d["baseline"] = d["trading_days"]
    d["deviation"] = d["days_asat"] - d["trading_days"]
    d["actual_value"], d["baseline_value"] = d["lines_asat"], d["lines_trailing_median"]
    d["variance"] = d["lines_asat"] - d["lines_trailing_median"]
    d["variance_pct"] = d["lines_asat"] / d["lines_trailing_median"] - 1
    d["exposure"] = np.nan
    d["entity_weekly_revenue"] = np.nan
    d["baseline_ok"] = True
    d["dq_fail"] = False
    d["b_fail"] = d["dq_sales_status"] == "FAIL"
    d["metric"] = "DQ gate (C1-C11)"
    d["dq_status"] = d["dq_sales_status"]
    d["dq_note"] = d["dq_checks_failed"]
    return _frame(d, "EW08", "store", cfg)
