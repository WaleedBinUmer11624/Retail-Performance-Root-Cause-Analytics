"""Phase 3 data-quality pipeline: profile -> detect -> treat -> quarantine -> validate -> reconcile -> report.

Usage (from the project root):
    python -m src.data_quality.run_dq                       # full data: data/raw -> data/processed
    python -m src.data_quality.run_dq --data data/sample --out tmp/dq_sample

Raw files are read-only: their SHA-256 hashes are taken before and after the run and must match.
This module never reads evaluation-only assets (see core.load_raw).
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

from . import completeness, dimensions, kpis, promotions_targets, report, returns_inventory, sales
from .catalogue import CATALOGUE, catalogue_frame
from .core import PROJECT_ROOT, DQContext, load_config, load_raw, sha256, write_csv
from .profiling import profile_all
from .validate_curated import validate

log = logging.getLogger("dq")


def run(data_dir: Path, out_root: Path | None = None, report_dir: Path | None = None) -> dict:
    """Profile, clean and validate every raw table, write curated outputs and reports, and
    return the run results."""
    t0 = time.time()
    cfg = load_config()
    data_dir = Path(data_dir)
    out_root = Path(out_root) if out_root else PROJECT_ROOT / "data" / "processed"
    report_dir = Path(report_dir) if report_dir else (PROJECT_ROOT / cfg["outputs"]["reports"]
                                                      if out_root == PROJECT_ROOT / "data" / "processed" else out_root / "reports")
    cur_dir, q_dir = out_root / "curated", out_root / "quarantine"
    for d in (cur_dir, q_dir, report_dir):
        d.mkdir(parents=True, exist_ok=True)
    ctx = DQContext(cfg=cfg, catalogue=CATALOGUE)

    # ---------------------------------------------------------------- 1 load + fingerprint
    input_paths = {t: data_dir / f for t, f in cfg["inputs"].items()}
    hashes_before = {t: sha256(p) for t, p in input_paths.items()}
    raw = {t: load_raw(data_dir, t, cfg) for t in cfg["inputs"]}
    raw_rows = {t: len(df) for t, df in raw.items()}
    log.info("loaded %s", {t: f"{n:,}" for t, n in raw_rows.items()})

    # ---------------------------------------------------------------- 2 profile (before any change)
    prof_t, prof_c = profile_all(raw, cfg)
    miss_cols = prof_t[prof_t["missing_columns"] != ""]
    ctx.result("SCH-01", len(prof_t), len(miss_cols), evidence=", ".join(miss_cols["table_name"]) or "all columns present")
    if len(miss_cols):
        raise SystemExit(f"schema failure: {miss_cols[['table_name', 'missing_columns']].to_dict('records')}")
    tf = prof_c[prof_c["type_failures"] > 0]
    ctx.result("SCH-02", int(prof_c["rows"].sum()), int(tf["type_failures"].sum()),
               evidence="; ".join(f"{a}.{b}: {c}" for a, b, c in zip(tf["table_name"], tf["column_name"], tf["type_failures"])))

    # ---------------------------------------------------------------- 3 dimensions
    till_ref = dimensions.till_reference(pd.concat([raw["fact_sales"], raw["fact_sales_late_batch"]]))
    d_store = dimensions.clean_dim_store(raw["dim_store"], ctx)
    d_date = dimensions.clean_dim_date(raw["dim_date"], ctx)
    d_prod, cat_map = dimensions.clean_dim_product(raw["dim_product"], ctx, till_ref)
    stores = set(d_store["store_id"])
    products = set(d_prod["product_id"]) - {dimensions.UNKNOWN}

    # ---------------------------------------------------------------- 4 facts
    promos = promotions_targets.clean_promotions(raw["fact_promotions"], ctx, stores, products)
    targets = promotions_targets.clean_targets(raw["fact_targets"], ctx, stores, d_date)
    f_sales = sales.clean_sales(raw["fact_sales"], raw["fact_sales_late_batch"], ctx, stores, d_prod, promos, till_ref,
                                raw["fact_returns"])
    promos = restore_promotions(promos, ctx)
    late_keys = set(raw["fact_sales_late_batch"]["transaction_id"] + "|" + raw["fact_sales_late_batch"]["line_number"])
    f_ret = returns_inventory.clean_returns(raw["fact_returns"], ctx, f_sales, stores, products, late_keys)
    f_inv = returns_inventory.clean_inventory(raw["fact_inventory"], ctx, stores, products, d_date)
    trading_stores = sorted(set(f_sales["store_id"]))     # stores with POS data in the extract
    missing_targets = promotions_targets.target_gaps(targets, ctx, trading_stores, d_date)

    # ---------------------------------------------------------------- 5 completeness, timeliness, reconciliation
    main_src = cfg["inputs"]["fact_sales"]
    gaps = completeness.store_day_coverage(f_sales, main_src, d_date, trading_stores, f_inv, raw["fact_returns"], ctx)
    low = completeness.low_volume_days(f_sales, ctx)
    batches = completeness.batch_structure(raw["fact_sales"], ctx)
    last_full_week = d_date.groupby(["retail_year", "retail_week"])["date"].agg(["size", "max"])
    last_full_week = last_full_week.loc[last_full_week["size"] == 7, "max"].max()
    naive_s, naive_r, naive_i = kpis.naive_views(raw["fact_sales"], raw["fact_returns"], raw["fact_inventory"])
    naive_s_keys = naive_s.assign(store_id=raw["fact_sales"]["store_id"],
                                  snapshot_q=naive_s["quantity"])
    inv_raw_typed = raw["fact_inventory"].assign(
        snapshot_date=pd.to_datetime(raw["fact_inventory"]["snapshot_date"], errors="coerce"),
        sold_qty=pd.to_numeric(raw["fact_inventory"]["sold_qty"], errors="coerce"))
    recon_before = returns_inventory.reconcile_pos_to_stock(naive_s_keys.dropna(subset=["transaction_date"]),
                                                            inv_raw_typed, d_date, last_full_week)
    recon_after = returns_inventory.reconcile_pos_to_stock(f_sales, f_inv, d_date, last_full_week)
    ctx.result("TC-07", recon_after["cells"], recon_after["mismatched"],
               evidence=f"match rate {recon_before['match_rate']:.4%} before cleaning, {recon_after['match_rate']:.4%} after "
                        f"({recon_before['mismatched']:,} -> {recon_after['mismatched']:,} store-SKU-weeks)")
    mm = recon_after["mismatch_frame"]
    mm = attribute_mismatches(mm, gaps, f_inv, f_sales, ctx, d_date)
    recon_after["explained"] = mm["explanation"].value_counts().to_dict()
    ctx.results["TC-07"]["evidence"] += "; remaining: " + "; ".join(f"{k} {v}" for k, v in recon_after["explained"].items())
    write_csv(mm, report_dir / "pos_stock_mismatches.csv")
    ctx.log_rows("TC-07", "fact_inventory", mm["store_id"] + "|" + mm["product_id"] + "|" +
                 mm["snapshot_date"].dt.strftime("%Y-%m-%d"), "sold_qty", mm["stock"], mm["pos"], action="REPORT")

    # ---------------------------------------------------------------- 6 KPI reconciliation
    curated_ret = f_ret
    main_only = f_sales[f_sales["source_file"] == main_src]
    views = {
        "raw_as_reported": {**kpis.kpis(naive_s, naive_r, naive_i), **kpis.h2_net_revenue(naive_s, naive_r, d_date)},
        "clean_main_only": {**kpis.kpis(main_only, curated_ret, f_inv), **kpis.h2_net_revenue(main_only, curated_ret, d_date)},
        "clean_complete": {**kpis.kpis(f_sales, curated_ret, f_inv), **kpis.h2_net_revenue(f_sales, curated_ret, d_date)},
    }
    kpi_df = pd.DataFrame(views)
    kpi_df["change_raw_to_complete"] = kpi_df["clean_complete"] - kpi_df["raw_as_reported"]
    kpi_df["change_pct"] = 100 * kpi_df["change_raw_to_complete"] / kpi_df["raw_as_reported"].abs()
    kpi_df.index.name = "kpi"

    # ---------------------------------------------------------------- 7 validate curated
    curated = {"dim_store": d_store, "dim_product": d_prod, "dim_date": d_date, "fact_sales": f_sales,
               "fact_inventory": f_inv, "fact_returns": f_ret, "fact_promotions": promos, "fact_targets": targets}
    val = validate(curated, ctx.quarantine, raw_rows, cfg, {"before": recon_before, "after": recon_after},
                   ctx.results, CATALOGUE)

    # ---------------------------------------------------------------- 8 write outputs
    issues = pd.concat(ctx.issues, ignore_index=True) if ctx.issues else pd.DataFrame()
    results = pd.DataFrame(ctx.results.values())
    order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    results["severity_rank"] = results["severity"].map(order)
    results["status"] = results.apply(lambda r: "INFO" if r["severity"] == "info" else
                                      ("PASS" if r["rows_failed"] == 0 else "FAIL"), axis=1)
    results["failure_rate_pct"] = (100 * results["rows_failed"] / results["rows_checked"].clip(lower=1)).round(4)
    results["rationale"] = results["rule_id"].map(lambda r: CATALOGUE[r]["rationale"])
    results = results.sort_values(["severity_rank", "rule_id"]).drop(columns="severity_rank")
    qcounts = {}
    for t, frames in ctx.quarantine.items():
        q = pd.concat(frames, ignore_index=True)
        write_csv(q, q_dir / f"{t}_quarantine.csv")
        qcounts[t] = len(q)
    outputs = {}
    for t, df in curated.items():
        p = cur_dir / f"{t}.csv"
        w = df.copy()
        for c in w.columns:
            if pd.api.types.is_datetime64_any_dtype(w[c]):
                w[c] = w[c].dt.strftime("%Y-%m-%d %H:%M:%S" if c == "extract_timestamp" else "%Y-%m-%d")
        write_csv(w, p)
        outputs[t] = {"path": str(p.relative_to(PROJECT_ROOT) if p.is_relative_to(PROJECT_ROOT) else p),
                      "rows": len(df), "sha256": sha256(p)}

    audit = pd.DataFrame(ctx.audit)
    write_csv(prof_t, report_dir / "profile_tables.csv")
    write_csv(prof_c, report_dir / "profile_columns.csv")
    write_csv(catalogue_frame(), report_dir / "dq_rule_catalogue.csv")
    write_csv(results, report_dir / "dq_rule_results.csv")
    write_csv(issues, report_dir / "dq_issue_log.csv")
    write_csv(audit, report_dir / "cleaning_audit_trail.csv")
    write_csv(kpi_df, report_dir / "kpi_reconciliation.csv", index=True)
    write_csv(val, report_dir / "curated_validation.csv")
    write_csv(gaps, report_dir / "completeness_store_days.csv")
    write_csv(low, report_dir / "low_volume_store_days.csv")
    write_csv(batches, report_dir / "extract_batches.csv")
    write_csv(missing_targets, report_dir / "missing_targets.csv")
    write_csv(ctx.notes["inventory_missing_weeks"], report_dir / "inventory_missing_weeks.csv")
    write_csv(cat_map, report_dir / "category_mapping.csv")
    write_csv(till_ref, report_dir / "sku_reference_prices.csv")

    hashes_after = {t: sha256(p) for t, p in input_paths.items()}
    raw_unchanged = hashes_before == hashes_after
    val = pd.concat([val, pd.DataFrame([{"group": "lineage", "check": "raw input files unchanged by the run",
                                         "status": "PASS" if raw_unchanged else "FAIL", "value": "SHA-256 before = after"}])],
                    ignore_index=True)
    write_csv(val, report_dir / "curated_validation.csv")

    rev_affected = float(results.loc[results["severity"] != "info", "revenue_affected"].sum())
    summary = {
        "run_at": datetime.now().isoformat(timespec="seconds"), "runtime_seconds": round(time.time() - t0, 1),
        "data_dir": str(data_dir), "inputs": {t: {"file": str(input_paths[t].name), "rows": raw_rows[t],
                                                  "sha256": hashes_before[t]} for t in raw},
        "raw_unchanged": raw_unchanged, "outputs": outputs, "quarantine_rows": qcounts,
        "rules_evaluated": len(results), "rules_failed": int((results["status"] == "FAIL").sum()),
        "dq_check_pass_rate_pct": round(100 * (results["status"] == "PASS").sum() /
                                        max((results["status"] != "INFO").sum(), 1), 2),
        "issue_log_rows": len(issues),
        "validation": val["status"].value_counts().to_dict(),
        "pos_stock_reconciliation": {k: {kk: v for kk, v in d.items() if kk != "mismatch_frame"}
                                     for k, d in (("before", recon_before), ("after", recon_after))},
        "max_plausible_line_quantity": cfg["tolerances"]["max_plausible_line_quantity"],
        "config_sha256": sha256(PROJECT_ROOT / "config" / "dq_config.yaml"),
        "code_sha256": {f.name: sha256(f) for f in sorted((PROJECT_ROOT / "src" / "data_quality").glob("*.py"))},
    }
    (report_dir / "lineage.json").write_text(json.dumps(summary, indent=2, default=str))
    out = {"summary": summary, "results": results, "kpis": kpi_df, "validation": val, "audit": audit,
           "issues": issues, "curated": curated, "gaps": gaps, "recon": (recon_before, recon_after),
           "report_dir": report_dir}
    main_run = report_dir == PROJECT_ROOT / cfg["outputs"]["reports"]
    md = (PROJECT_ROOT / "reports" if main_run else report_dir) / "data_quality_report.md"
    csv = (PROJECT_ROOT / "reports" if main_run else report_dir) / "data_quality_report.csv"
    blind_path = PROJECT_ROOT / cfg["outputs"]["reports"] / "independent_blind_profile_findings.csv"
    blind = pd.read_csv(blind_path) if blind_path.exists() else None
    report.build(out, raw_rows, md, csv, blind)
    log.info("done in %.1fs: %s", time.time() - t0, summary["validation"])
    return out


def restore_promotions(promos: pd.DataFrame, ctx: DQContext) -> pd.DataFrame:
    """Move FP-04 rows whose product was identified from POS lines (see FS-20) back into the curated table."""
    restored = ctx.notes.get("restored_promotions", [])
    if not restored:
        return promos
    r = pd.DataFrame(restored)
    key = set(zip(r["promotion_id"], r["store_id"], r["product_id_raw"]))
    frames = ctx.quarantine["fact_promotions"]
    ctx.quarantine["fact_promotions"] = [f[[k not in key for k in zip(f["promotion_id"], f["store_id"], f["product_id"])]]
                                         for f in frames]
    ctx.log_rows("FP-04", "fact_promotions", r["promotion_id"] + "|" + r["product_id_raw"] + "|" + r["store_id"],
                 "product_id", r["product_id_raw"], r["product_id"], action="CORRECT (product identified from POS lines)")
    ctx.audit_step("fact_promotions", "FP-04", "CORRECT", len(r), "product_id",
                   note="restored from quarantine: POS lines of the promotion and store identify one product")
    ctx.results["FP-04"]["evidence"] = f"{len(r)} of {ctx.notes.get('promo_orphan_count', len(r))} restored from POS lines"
    r = r.drop(columns=["product_id_raw", "pos_lines", "dq_rule_id", "dq_reason"])
    r["start_date"] = pd.to_datetime(r["start_date"], errors="coerce")
    r["end_date"] = pd.to_datetime(r["end_date"], errors="coerce")
    r["discount_pct"] = pd.to_numeric(r["discount_pct"], errors="coerce")
    return pd.concat([promos, r[promos.columns]], ignore_index=True)


def attribute_mismatches(mm, gaps, inv, sales_c, ctx, d_date):
    """Explain each remaining POS-vs-stock mismatch by a known, logged cause (first match wins)."""
    wk_end = d_date.set_index("date")["retail_week_start"] + pd.Timedelta(days=6)
    mm = mm.copy()
    cell = list(zip(mm["store_id"], mm["product_id"], mm["snapshot_date"]))
    gap_weeks = set(zip(gaps.loc[~gaps["resolved_by_late_file"], "store_id"],
                        gaps.loc[~gaps["resolved_by_late_file"], "date"].map(wk_end)))
    flagged_inv = set(zip(inv.loc[inv["dq_rules"] != "", "store_id"], inv.loc[inv["dq_rules"] != "", "product_id"],
                          inv.loc[inv["dq_rules"] != "", "snapshot_date"]))
    miss_wk = ctx.notes["inventory_missing_weeks"]
    miss_inv = set(zip(miss_wk["store_id"], miss_wk["product_id"], pd.to_datetime(miss_wk["snapshot_date"])))
    unk = sales_c[sales_c["product_id"] == dimensions.UNKNOWN]
    unk_weeks = set(zip(unk["store_id"], unk["transaction_date"].map(wk_end)))
    q = pd.concat(ctx.quarantine.get("fact_sales", [pd.DataFrame(columns=["transaction_id", "product_id"])]))
    q = q[q.get("dq_rule_id", pd.Series(dtype=str)) != "FS-01"] if len(q) else q
    q_cells = set(zip(q["transaction_id"].str.slice(0, 3), q["product_id"],
                      pd.to_datetime(q["transaction_id"].str.slice(4, 12), format="%Y%m%d", errors="coerce").map(wk_end))) \
        if len(q) else set()
    expl = []
    for c, pos, stock in zip(cell, mm["pos"], mm["stock"]):
        if (c[0], c[2]) in gap_weeks:
            expl.append("missing POS store-day (TC-02)")
        elif c in miss_inv:
            expl.append("missing stock snapshot (TC-05)")
        elif c in flagged_inv:
            expl.append("flagged stock row (FI-04..FI-07)")
        elif c in q_cells:
            expl.append("quarantined sales line (FS-09)")
        elif c[1] == dimensions.UNKNOWN or ((c[0], c[2]) in unk_weeks and stock > pos):
            expl.append("sales line with UNKNOWN product in that store-week (FS-05/FS-06)")
        else:
            expl.append("unexplained")
    mm["explanation"] = expl
    return mm


def main():
    """CLI entry point: run the pipeline on --data, logging to a timestamped file."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/raw")
    ap.add_argument("--out", default=None, help="output root (default data/processed)")
    a = ap.parse_args()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    (PROJECT_ROOT / "logs").mkdir(exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler(PROJECT_ROOT / "logs" / f"dq_run_{ts}.log")])
    res = run(PROJECT_ROOT / a.data, PROJECT_ROOT / a.out if a.out else None)
    v = res["validation"]
    print(res["results"][["rule_id", "severity", "treatment", "rows_checked", "rows_failed", "status"]].to_string(index=False))
    print(v.to_string(index=False, max_colwidth=70))
    if (v["status"] == "FAIL").any():
        sys.exit(1)


if __name__ == "__main__":
    main()
