"""Phase 5 runner: exploratory business analysis and diagnostics of the H2 change.

Usage (from the project root):
    python -m src.analytics.run_phase5                     # SQL Server model built by Phase 4 (config/project_config.yaml)
    python -m src.analytics.run_phase5 --engine duckdb     # rebuild the Phase 4 model locally, then analyse it
    python -m src.analytics.run_phase5 --record-freeze     # record the Phase 1-4 input checksums (once, at phase start)

Steps
    1  verify the Phase 1-4 inputs against the freeze manifest (stops if anything changed)
    2  open the model (DuckDB: build and reconcile it with the Phase 4 runner)
    3  create the diag.* views (sql/analysis/diagnostics/01-09)
    4  recompute the H2 headline and reconcile it to Phase 4 (stops on any difference above tolerance)
    5  diagnostics, evidence shortlist, figures, executive summary, validation report
Exit code 1 if the freeze, the headline reconciliation or any SQL-vs-Python check fails.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from . import contribution as C
from . import diagnostics as D
from . import period_comparison as PC
from .model_access import (PROJECT_ROOT, InputError, benchmark, fetch, load_config, open_model, record_freeze,
                           run_diagnostic_sql, verify_freeze)


class HeadlineMismatch(RuntimeError):
    pass


class Log:
    def __init__(self):
        self.t0 = time.time()
        self.lines = []

    def __call__(self, msg: str):
        line = f"[{time.time() - self.t0:7.1f}s] {msg}"
        self.lines.append(line)
        print(line, flush=True)


def _q(engine, sql):
    return fetch(engine, sql)


# ============================================================================= analysis
def analyse(engine, cfg: dict, project: dict, p4cfg: dict, bench: pd.DataFrame, log: Log) -> dict:
    per = PC.load_periods(project)
    py, cy = per.py_year, per.cy_year
    R: dict = {"periods": per}
    tol4 = p4cfg["tolerances"]

    # ---- 1 headline and reconciliation (STOP on mismatch)
    wk = _q(engine, f"SELECT * FROM diag.v_h2_week_comparison WHERE retail_year = {cy}")
    R["alignment"] = PC.check_week_alignment(wk, per)
    if not R["alignment"]["passed"].all():
        raise HeadlineMismatch("week alignment failed:\n" + R["alignment"].to_string(index=False))
    h = _q(engine, f"SELECT * FROM diag.v_h2_headline WHERE retail_year IN ({py}, {cy})")
    facts = _q(engine, "SELECT * FROM diag.v_h2_headline_from_facts")
    pyd, cyd = PC.headline_components(h, per)
    R["py"], R["cy"] = pyd, cyd
    R["headline"] = PC.headline_table(pyd, cyd, per)
    R["headline_recon"] = PC.check_headline_against_phase4(pyd, cyd, facts, bench, per, tol4)
    if (R["headline_recon"]["status"] != "PASS").any():
        raise HeadlineMismatch("H2 headline does not reconcile to Phase 4:\n" + R["headline_recon"].to_string(index=False))
    total_py = pyd["net_revenue"]
    total_change = cyd["net_revenue"] - pyd["net_revenue"]
    log(f"headline reconciled: {per.label_py} {pyd['net_revenue']:,.2f} -> {per.label_cy} {cyd['net_revenue']:,.2f} "
        f"({C.yoy_pct(cyd['net_revenue'], pyd['net_revenue']):+.6f}%)")

    # ---- 2 weekly trend
    R["weekly"] = PC.weekly_trend(wk, total_py, cfg["trend"]["rolling_weeks"])
    R["profile"] = PC.trend_profile(R["weekly"], cfg["trend"])
    ew = _q(engine, "SELECT * FROM diag.v_estate_week")
    R["context"] = PC.full_year_context(ew, per, cfg["trend"]["rolling_weeks"])
    R["profile"]["h1_yoy_pct"] = float(C.yoy_pct(R["context"].query("half == 'H1'")["net_revenue_cy"].sum(),
                                                 R["context"].query("half == 'H1'")["net_revenue_py"].sum()))
    R["profile"]["context_sustained_onset_week"] = PC.sustained_onset(
        R["context"][f"rolling_{cfg['trend']['rolling_weeks']}w_yoy_pct"].fillna(0), R["context"]["retail_week"])
    log(f"trend profile: {R['profile']['shape']}, {R['profile']['weeks_negative']}/26 weeks negative")

    # ---- 3 store / region / format
    seg = _q(engine, f"SELECT * FROM diag.v_segment_h2_contribution WHERE retail_year = {cy}")
    stores = _q(engine, "SELECT store_key, store_id, store_name, region, store_format, floor_area_m2 FROM dw.dim_store WHERE store_key > 0")
    products = _q(engine, "SELECT product_key, product_id, product_name, category, subcategory, supplier_name FROM dw.dim_product")
    R["stores_dim"], R["products_dim"] = stores, products
    st = seg[seg["segment_type"] == "Store"].rename(columns={"segment_name": "store_id"})
    st = st.merge(stores, on="store_id", how="left")
    R["store"] = C.contribution_table(st, "store_id", total_py, total_change)
    R["region"] = C.contribution_table(seg[seg["segment_type"] == "Region"].rename(columns={"segment_name": "region"}),
                                       "region", total_py, total_change)
    R["format"] = C.contribution_table(seg[seg["segment_type"] == "Format"].rename(columns={"segment_name": "store_format"}),
                                       "store_format", total_py, total_change)
    R["breadth"] = _q(engine, f"SELECT * FROM diag.v_segment_h2_breadth WHERE retail_year = {cy}")
    R["region_format"] = _q(engine, f"SELECT * FROM diag.v_region_format_h2 WHERE retail_year = {cy}")
    R["seg_sql"] = seg
    R["store_sql"] = _q(engine, f"SELECT * FROM diag.v_store_h2_contribution WHERE retail_year = {cy}")

    # the smallest set of stores carrying half of the decline, and its weekly timing vs the rest of the estate
    R["store_cluster"] = C.decline_cluster(R["store"], "store_id", cfg["trend"]["cluster_cover"])
    sw = _q(engine, f"SELECT retail_week, store_id, net_revenue_cy, net_revenue_py, transactions_cy, transactions_py "
                    f"FROM mart.v_yoy_store_week WHERE retail_year = {cy} AND retail_week BETWEEN {per.week_from} AND {per.week_to}")
    R["cluster_weekly"] = PC.cluster_weekly(sw, R["store_cluster"], cfg["trend"]["rolling_weeks"])
    R["cluster_onset"] = PC.sustained_onset(R["cluster_weekly"]["cluster_net_revenue_yoy_pct"], R["cluster_weekly"]["retail_week"])

    # ---- 4 categories
    cat = _q(engine, f"SELECT * FROM diag.v_category_h2_contribution WHERE retail_year = {cy}")
    R["category_sql"] = cat
    R["category"] = C.contribution_table(cat.drop(columns=["contribution_pp", "share_of_change", "contribution_rank"]),
                                         "category", total_py, total_change)

    # ---- 5 bridge
    R["bridge"] = C.bridge_table(pyd, cyd, per.label_py, per.label_cy)
    R["bridge_effects"] = R["bridge"].attrs["effects"]
    e = R["bridge_effects"]
    R["aov_effects"] = C.shapley_two(e["upt_py"], e["asp_py"], e["upt_cy"], e["asp_cy"])
    R["seg_bridge_sql"] = _q(engine, f"SELECT * FROM diag.v_basket_bridge_segment WHERE retail_year = {cy}")
    R["seg_bridge"] = C.segment_bridges(seg)
    cb_sql = _q(engine, f"SELECT * FROM diag.v_basket_bridge_category WHERE retail_year = {cy}")
    R["cat_bridge_sql"] = cb_sql
    cb = cat.rename(columns={"transactions_with_category_py": "transactions_py",
                             "transactions_with_category_cy": "transactions_cy"})
    R["cat_bridge"] = C.segment_bridges(cb)
    R["basket_week"] = _q(engine, f"SELECT * FROM diag.v_basket_week WHERE retail_year = {cy}")
    log(f"bridge: T {e['transactions_effect']:,.0f}  UPT {e['upt_effect']:,.0f}  ASP {e['asp_effect']:,.0f}  "
        f"returns {e['returns_effect']:,.0f}  (residual {e['shapley_residual']:.2e})")

    # ---- 6 returns
    sc = _q(engine, "SELECT * FROM diag.v_returns_h2_store_category")
    reason = _q(engine, "SELECT * FROM diag.v_returns_h2_reason")
    prod = _q(engine, "SELECT * FROM diag.v_product_h2_components")
    R["returns_attributes"] = _q(engine, f"SELECT * FROM diag.v_returns_h2_attributes WHERE retail_year IN ({py}, {cy})")
    R["returns"], R["returns_summary"] = D.returns_diagnostics(wk, sc, reason, prod, py, cy, total_py, cfg)

    # ---- 7 availability and estimated lost sales
    cells = _q(engine, "SELECT * FROM diag.v_stock_cell_week")
    weeks = _q(engine, "SELECT retail_week_key, retail_year, retail_week FROM dw.dim_retail_week WHERE retail_week_key IN "
                       "(SELECT DISTINCT retail_week_key FROM dw.fact_inventory)")
    panel = D.Panel(cells, weeks)
    ls_cfg = cfg["lost_sales"]
    est = D.estimate_expected(panel, ls_cfg["windows"], ls_cfg["min_history_weeks"])
    lost = D.lost_sales_cells(panel, est, (py, cy), per.week_from, per.week_to)
    R["lost_cells"] = lost
    R["backtest"] = D.lost_sales_backtest(panel, est, (py, cy), per.week_from, per.week_to)
    R["mechanism"] = D.stockout_mechanism(lost, (py, cy))
    sca = _q(engine, "SELECT * FROM diag.v_availability_h2_store_category")
    wav = _q(engine, "SELECT * FROM diag.v_availability_week")
    R["availability"], R["assoc"], R["lost_totals"] = D.availability_diagnostics(
        sca, R["store"].rename(columns={"store_id": "segment_name"}), R["category"], lost, wav, sc, stores, products,
        py, cy, per.week_from, per.week_to, cfg["evidence"]["association_alpha"],
        _q(engine, "SELECT * FROM diag.v_availability_h2_supplier"), products)
    R["availability_week_all"] = wav
    log(f"estimated lost sales (ESTIMATE): {per.label_py} {R['lost_totals']['lost_py']:,.0f}  "
        f"{per.label_cy} {R['lost_totals']['lost_cy']:,.0f}; backtest bias {R['backtest']['bias_ratio']:.3f}")

    # ---- 5b products (only material categories)
    lp = lost.assign(v=lost["est_lost_sales_eur"].fillna(0)).groupby(["product_key", "retail_year"])["v"].sum().unstack()
    lp = lp.reindex(columns=[py, cy]).fillna(0.0)
    lp.columns = ["est_lost_sales_py", "est_lost_sales_cy"]
    R["category_region"] = D.category_region_matrix(sc, py, cy, total_py)
    R["range_change"] = D.range_change(prod, py, cy)
    R["products"], R["material_categories"] = D.product_drilldown(prod, R["category"], lp.reset_index(), py, cy, cfg,
                                                                  total_change)

    # ---- 8 promotions
    lines = _q(engine, "SELECT * FROM diag.v_promo_h2_lines")
    scope = _q(engine, "SELECT * FROM diag.v_promo_h2_scope")
    events = _q(engine, "SELECT * FROM diag.v_promo_event_week")
    R["promo_summary"] = D.promotion_summary(lines, scope, py, cy)
    R["promo_uplift"], R["promo_events"] = D.promotion_uplift(panel, est, events, cfg, py, cy, per.week_from,
                                                              per.week_to, products)

    # ---- 9 targets
    tw = _q(engine, "SELECT * FROM diag.v_target_store_week")
    R["target_weeks"] = tw
    R["targets"] = D.target_diagnostics(tw, cfg, py, cy, per.week_to)
    R["targets_sql"] = _q(engine, "SELECT * FROM diag.v_target_store_h2")

    # ---- data coverage
    cov = _q(engine, "SELECT * FROM diag.v_store_week_coverage")
    cov = cov[cov["retail_year"].isin([py, cy]) & cov["retail_week"].between(per.week_from, per.week_to)]
    # a store-week is a gap when it traded on fewer days than most stores that week (e.g. not Christmas Day closure)
    norm = cov.groupby("retail_week_key")["trading_days"].transform(lambda s: s.mode().max())
    gaps = cov[cov["trading_days"] < norm].assign(normal_trading_days=norm[cov["trading_days"] < norm])
    gaps = gaps.merge(stores[["store_key", "store_id"]], on="store_key")
    R["coverage_gaps"] = gaps
    return R


# ============================================================================= checks
def cross_checks(R: dict, shortlist: pd.DataFrame, cfg: dict, p4cfg: dict) -> pd.DataFrame:
    from .evidence import EVIDENCE_LEVELS
    tol4, tol = p4cfg["tolerances"], cfg["tolerances"]
    per = R["periods"]
    rows = []

    def add(group, check, value, reference, tolerance, passed=None):
        diff = abs(value - reference) if isinstance(value, (int, float)) and isinstance(reference, (int, float)) else np.nan
        if passed is None:
            passed = bool(diff <= tolerance)
        rows.append({"group": group, "check": check, "value": value, "reference": reference, "difference": diff,
                     "tolerance": tolerance, "status": "PASS" if passed else "FAIL"})

    for r in R["alignment"].itertuples():
        add("Period", r.check, r.detail, "", np.nan, bool(r.passed))
    for r in R["headline_recon"].itertuples():
        add("Headline vs Phase 4", r.check, r.recomputed, r.reference, r.tolerance, r.status == "PASS")
    total_py, total = R["py"]["net_revenue"], R["cy"]["net_revenue"] - R["py"]["net_revenue"]
    yoy = 100 * total / total_py
    add("Contribution", "weekly changes add up to the H2 change", float(R["weekly"]["net_revenue_change"].sum()), total, tol4["eur"])
    for name, df in (("store", R["store"]), ("region", R["region"]), ("format", R["format"]), ("category", R["category"])):
        add("Contribution", f"{name} EUR changes add up to the estate change", float(df["net_revenue_change"].sum()), total, tol4["eur"])
        add("Contribution", f"{name} contributions (pp) add up to the estate YoY %", float(df["contribution_pp"].sum()), yoy,
            tol4["yoy_pct_points"])
        add("Contribution", f"{name} shares of change add up to 100%", float(df["share_of_change"].sum()), 1.0, 1e-9)
    s_py = R["store"].set_index("store_id").sort_index()
    s_sql = R["store_sql"].set_index("segment_name").reindex(s_py.index)
    add("SQL vs Python", "store contribution (pp), max abs difference",
        float((s_sql["contribution_pp"] - s_py["contribution_pp"]).abs().max()), 0.0, tol["sql_vs_python_ratio"])
    add("SQL vs Python", "store share of change, max abs difference",
        float((s_sql["share_of_change"] - s_py["share_of_change"]).abs().max()), 0.0, tol["sql_vs_python_ratio"])
    add("SQL vs Python", "store ranking identical (EUR contribution)", int((s_sql["contribution_rank"] != s_py["contribution_rank"]).sum()),
        0, 0)
    add("SQL vs Python", "store ranking identical (YoY %)", int((s_sql["yoy_pct_rank"] != s_py["yoy_pct_rank"]).sum()), 0, 0)
    c_py = R["category"].set_index("category").sort_index()
    c_sql = R["category_sql"].set_index("category").reindex(c_py.index)
    add("SQL vs Python", "category contribution (pp), max abs difference",
        float((c_sql["contribution_pp"] - c_py["contribution_pp"]).abs().max()), 0.0, tol["sql_vs_python_ratio"])
    add("SQL vs Python", "category ranking identical", int((c_sql["contribution_rank"] != c_py["contribution_rank"]).sum()), 0, 0)
    e = R["bridge_effects"]
    add("Bridge", "Shapley residual (estate)", abs(e["shapley_residual"]), 0.0, tol["bridge_eur"])
    add("Bridge", "transactions + UPT + ASP + residual + returns = net revenue change",
        e["transactions_effect"] + e["upt_effect"] + e["asp_effect"] + e["shapley_residual"] + e["returns_effect"], total,
        tol["bridge_eur"])
    b = R["bridge"]
    add("Bridge", "waterfall ends at the current-period net revenue", float(b["running_total_eur"].iloc[-2]),
        R["cy"]["net_revenue"], tol["bridge_eur"])
    add("Bridge", "AOV change = UPT part + ASP part", float(sum(R["aov_effects"])), R["cy"]["aov"] - R["py"]["aov"], 1e-9)
    sb, sq = R["seg_bridge"], R["seg_bridge_sql"]
    add("Bridge", "segment bridges reconcile (max abs difference)", float(sb["reconciliation_difference"].abs().max()), 0.0,
        tol["bridge_eur"])
    m = sb.merge(sq, on=["segment_type", "segment_name"], suffixes=("", "_sql"))
    for k in ("transactions_effect", "upt_effect", "asp_effect", "returns_effect"):
        add("SQL vs Python", f"segment {k} (max abs difference)", float((m[k] - m[f"{k}_sql"]).abs().max()), 0.0,
            tol["sql_vs_python_eur"])
    cbp, cbs = R["cat_bridge"], R["cat_bridge_sql"]
    mc = cbp.merge(cbs, on="category", suffixes=("", "_sql"))
    add("Bridge", "category bridges reconcile (max abs difference)", float(cbp["reconciliation_difference"].abs().max()), 0.0,
        tol["bridge_eur"])
    for k in ("transactions_effect", "upt_effect", "asp_effect"):
        add("SQL vs Python", f"category {k} (max abs difference)", float((mc[k] - mc[f"{k}_sql"]).abs().max()), 0.0,
            tol["sql_vs_python_eur"])
    tp, ts = R["targets"], R["targets_sql"]
    mt = tp.merge(ts, on=["retail_year", "store_id"], suffixes=("", "_sql"))
    last = f"last{cfg['targets']['last_n_weeks']}_missed_weeks"
    for k, ksql in (("missed_weeks", "missed_weeks_sql"), ("longest_miss_streak", "longest_miss_streak_sql"),
                    (last, "last13_missed_weeks")):
        add("SQL vs Python", f"targets: {k} identical for every store and year", int((mt[k] != mt[ksql]).sum()), 0, 0)
    rr = R["returns"]
    est = rr[rr["level"] == "Estate"].iloc[0]
    add("Returns", "store returns add up to the estate returns", float(rr[rr["level"] == "Store"]["returns_value_cy"].sum()),
        float(est["returns_value_cy"]), tol4["eur"])
    add("Returns", "recorded-reason returns add up to the estate returns",
        float(rr[rr["level"] == "Recorded reason"]["returns_value_cy"].sum()), float(est["returns_value_cy"]), tol4["eur"])
    add("Returns", "estate returns equal the headline returns", float(est["returns_value_cy"]), R["cy"]["returns_value"], tol4["eur"])
    av = R["availability"]
    add("Availability", "store ranged cells add up to the estate", float(av[av["level"] == "Store"]["ranged_cells_cy"].sum()),
        float(av[av["level"] == "Estate"]["ranged_cells_cy"].iloc[0]), 0)
    lost = R["lost_cells"]
    add("Lost sales", "estimated lost sales are never negative", float(np.nanmin(lost["est_lost_sales_eur"].to_numpy())), 0.0, 0,
        bool(np.nanmin(lost["est_lost_sales_eur"].to_numpy()) >= 0))
    add("Lost sales", "stock-out weeks with a baseline (coverage)", R["mechanism"]["coverage"], 1.0, 0.1)
    add("Lost sales", "back-test: actual / expected on in-stock weeks", R["backtest"]["bias_ratio"], 1.0,
        cfg["lost_sales"]["backtest_max_abs_bias"])
    add("Evidence", "every finding has exactly one allowed evidence level",
        int((~shortlist["evidence_level"].isin(EVIDENCE_LEVELS)).sum()), 0, 0)
    add("Evidence", "finding ids are unique", int(shortlist["finding_id"].duplicated().sum()), 0, 0)
    inf = 0
    for k, v in R.items():
        if isinstance(v, pd.DataFrame):
            num = v.select_dtypes(include=[np.number])
            inf += int(np.isinf(num.to_numpy(dtype=float)).sum()) if not num.empty else 0
    add("Robustness", "no infinite values (division by zero) in any result table", inf, 0, 0)
    return pd.DataFrame(rows)


# ============================================================================= runner
class OpenRecorder:
    """Records every file opened (Python audit hook) while active."""
    active = False
    paths: list = []

    @classmethod
    def hook(cls, event, args):
        if cls.active and event == "open" and args and isinstance(args[0], (str, Path)):
            mode = args[1] if len(args) > 1 else None
            flags = args[2] if len(args) > 2 and isinstance(args[2], int) else 0
            if isinstance(mode, str):
                write = any(ch in mode for ch in "wax+")
            else:
                write = bool(flags & (os.O_WRONLY | os.O_RDWR))
            cls.paths.append((str(args[0]), write))

    @classmethod
    def summary(cls) -> dict:
        from .model_access import _is_refused
        root = str(PROJECT_ROOT).replace("\\", "/") + "/"
        norm = [(p.replace("\\", "/"), w) for p, w in cls.paths]
        proj = [(p[len(root):], w) for p, w in norm if p.startswith(root)]
        read = sorted({p for p, w in proj if not w and p.startswith(("data/", "reports/", "config/"))})
        written = sorted({p for p, w in proj if w})
        refused = sorted({p for p, _ in proj if _is_refused(p)})
        return {"count": len(cls.paths), "project_files": read, "written": written, "refused": refused}


_HOOKED = False


def run(engine_name: str = "duckdb", out_dir: Path | None = None, make_figures: bool = True) -> dict:
    global _HOOKED
    if not _HOOKED:
        sys.addaudithook(OpenRecorder.hook)
        _HOOKED = True
    OpenRecorder.paths = []
    OpenRecorder.active = True
    log = Log()
    t0 = time.time()
    try:
        cfg, project, p4cfg = load_config()
        out = Path(out_dir) if out_dir else PROJECT_ROOT / cfg["outputs"]["reports"]
        out.mkdir(parents=True, exist_ok=True)
        freeze = verify_freeze(cfg)
        log(f"freeze verified: {len(freeze)} Phase 1-4 files unchanged")
        engine, info = open_model(engine_name, cfg, project, out if out_dir else None)
        log(f"model open ({engine_name})")
        try:
            sql_log = run_diagnostic_sql(engine, cfg)
            log(f"diagnostic SQL: {sum(s['batches'] for s in sql_log)} batches in {len(sql_log)} scripts")
            bench = benchmark(engine_name, cfg)
            R = analyse(engine, cfg, project, p4cfg, bench, log)
        finally:
            engine.close()
        from .evidence import build_shortlist
        from .reporting import executive_summary, validation_report, write_tables
        shortlist = build_shortlist(R, cfg)
        checks = cross_checks(R, shortlist, cfg, p4cfg)
        log(f"checks: {(checks['status'] == 'PASS').sum()}/{len(checks)} pass")
        files = write_tables(R, shortlist, out)
        freeze.to_csv(out / "input_verification.csv", index=False, lineterminator="\n")
        files["input_verification.csv"] = len(freeze)
        checks.to_csv(out / "validation_checks.csv", index=False, lineterminator="\n")
        files["validation_checks.csv"] = len(checks)
        figs = []
        if make_figures:
            from .figures import make_all
            figs = make_all(R, out / "figures")
            log(f"figures: {len(figs)}")
        (out / "phase5_executive_summary.md").write_text(executive_summary(R, shortlist), encoding="utf-8")
        OpenRecorder.active = False
        opened = OpenRecorder.summary()
        meta = {"run_at": datetime.now().isoformat(timespec="seconds"), "runtime_seconds": round(time.time() - t0, 1)}
        (out / "phase5_validation_report.md").write_text(
            validation_report(R, checks, freeze, files, figs, info, sql_log, opened, meta), encoding="utf-8")
        passed = bool((checks["status"] == "PASS").all()) and not opened["refused"]
        log(f"{'PASSED' if passed else 'FAILED'}; outputs in {out}")
        (out / "phase5_run_log.txt").write_text("\n".join(log.lines) + "\n", encoding="utf-8")
        return {"passed": passed, "R": R, "shortlist": shortlist, "checks": checks, "files": files, "figures": figs,
                "opened": opened, "out": out}
    finally:
        OpenRecorder.active = False


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--engine", choices=["mssql", "duckdb"], default="mssql")
    ap.add_argument("--out-dir", default=None, help="write outputs here instead of reports/phase5")
    ap.add_argument("--no-figures", action="store_true")
    ap.add_argument("--record-freeze", action="store_true", help="record the Phase 1-4 input manifest and exit")
    a = ap.parse_args()
    if a.record_freeze:
        cfg = load_config()[0]
        df = record_freeze(cfg)
        print(f"recorded {len(df)} files in {cfg['inputs']['freeze_manifest']}")
        return
    try:
        res = run(a.engine, a.out_dir, not a.no_figures)
    except (InputError, HeadlineMismatch) as e:
        print(f"STOPPED: {e}", file=sys.stderr)
        sys.exit(1)
    if not res["passed"]:
        bad = res["checks"][res["checks"]["status"] != "PASS"]
        print(bad.to_string(index=False), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
