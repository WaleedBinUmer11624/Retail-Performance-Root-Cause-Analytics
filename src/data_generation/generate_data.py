"""Brightwater Retail synthetic data generator (Phase 2).

Usage (from the project root):
    python -m src.data_generation.generate_data --mode sample
    python -m src.data_generation.generate_data --mode full      # only after sample sign-off

Pipeline:
    config -> calendar -> dimensions -> promotion plan -> expected demand
    -> weekly stock simulation -> transactions -> returns -> targets
    -> answer key (on clean data) -> planted data-quality issues -> CSV files
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from . import answer_key, calendar_builder, demand, dimensions, dq_injection, promotions, returns, scenario, simulation, targets, transactions
from .config_loader import PROJECT_ROOT, CONFIG_DIR, load_generator_config, load_hidden_scenario

log = logging.getLogger("data_generation")

# Offsets give each component its own reproducible random stream, so changing
# one component's draws never shifts another component's data.
SEED_OFFSETS = dict(store=1, product=2, ranging=3, promo=5, demand=6, traffic=7, fill=8,
                    simulate=9, sales=10, returns=11, targets=12, dq=13)


def setup_logging(mode: str) -> Path:
    """Log to stdout and a timestamped file under logs/; return the file path."""
    logs = PROJECT_ROOT / "logs"
    logs.mkdir(exist_ok=True)
    path = logs / f"data_generation_{mode}_{datetime.now():%Y%m%d_%H%M%S}.log"
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
                        handlers=[logging.FileHandler(path, encoding="utf-8"), logging.StreamHandler(sys.stdout)],
                        force=True)
    return path


def _config_hash() -> str:
    h = hashlib.sha256()
    for f in ("generator_config.yaml", "_hidden_scenario.yaml"):
        h.update((CONFIG_DIR / f).read_bytes())
    return h.hexdigest()[:16]


def run(mode: str = "sample", out_dir: Path | None = None, write_files: bool = True,
        seed: int | None = None) -> dict:
    """Generate a dataset. write_files=False is a calibration dry run: the full
    pipeline runs in memory and only aggregate results are returned; no data
    files are written. `seed` overrides the configured seed (sensitivity checks only)."""
    t0 = time.time()
    cfg = load_generator_config()
    scn = load_hidden_scenario()
    seed = int(cfg["seed"] if seed is None else seed)
    sd = {k: seed + v * 1000 for k, v in SEED_OFFSETS.items()}
    mode_cfg = cfg["run_modes"][mode]
    out = out_dir or PROJECT_ROOT / mode_cfg["output_dir"]
    if write_files:
        out.mkdir(parents=True, exist_ok=True)
    log.info("Mode=%s seed=%s output=%s", mode, seed, out)

    # calendar and dimensions
    weeks = calendar_builder.build_week_table(cfg)
    dim_date = calendar_builder.build_dim_date(cfg, weeks)
    day_w, week_share = calendar_builder.build_day_weights(cfg, weeks)
    dim_store = dimensions.build_dim_store(cfg, np.random.default_rng(sd["store"]))
    products = dimensions.build_dim_product(cfg, np.random.default_rng(sd["product"]))
    ranged = dimensions.build_ranging(cfg, dim_store, products, np.random.default_rng(sd["ranging"]))
    store_mask = dimensions.select_stores(dim_store, mode_cfg["store_ids"])
    live = dimensions.product_week_activity(products, weeks)
    log.info("Stores=%d (simulated %d) SKUs=%d weeks=%d", len(dim_store), store_mask.sum(), len(products), len(weeks))

    # promotions: baseline plan (what Finance budgeted) and actual plan (with scenario)
    S = len(dim_store)
    ev_base = promotions.plan_promotions(cfg, products, weeks, live, S, sd["promo"])
    ev_act = promotions.plan_promotions(cfg, products, weeks, live, S, sd["promo"],
                                        scenario_b3=scn["B3_home_kitchen_promotion_change"])
    depth_b, _, mult_b = promotions.promo_arrays(ev_base, ranged, len(weeks))
    depth_a, ref_a, mult_a = promotions.promo_arrays(ev_act, ranged, len(weeks))
    promo_ids = promotions.promotion_ids(ev_act)

    # expected demand views
    traffic = scenario.traffic_multiplier(scn, dim_store, weeks, sd["traffic"])
    args = (cfg, dim_store, products, weeks, ranged, live, store_mask, sd["demand"], week_share)
    E_actual = demand.expected_lines(*args, promo_mult=mult_a, traffic_mult=traffic)
    E_repl = demand.expected_lines(*args, promo_mult=mult_a, traffic_mult=traffic, with_noise=False)
    E_plan = demand.expected_lines(*args, promo_mult=mult_b, with_noise=False, include_drift=False)
    E_base_ak = demand.expected_lines(*args, promo_mult=mult_b, traffic_mult=traffic, with_noise=False)
    fill, b2_affected = scenario.supplier_fill_rates(cfg, scn, products, weeks, sd["fill"])

    # simulation and facts
    sold, lost, inv_raw, mean_qty = simulation.simulate(cfg, dim_store, products, weeks, ranged, store_mask, live,
                                                        E_actual, E_repl, fill, day_w, sd["simulate"])
    sales, internal = transactions.build_fact_sales(cfg, sold, dim_store, products, weeks, depth_a, ref_a,
                                                    promo_ids, sd["sales"])
    rets = returns.build_fact_returns(cfg, scn, sales, internal, dim_store[store_mask], products, sd["returns"])
    fact_targets = targets.build_fact_targets(cfg, E_plan, mean_qty, depth_b, dim_store, products, weeks, sd["targets"])
    fact_targets = fact_targets[fact_targets["store_id"].isin(dim_store.loc[store_mask, "store_id"])].reset_index(drop=True)

    fact_inventory = pd.DataFrame({
        "snapshot_date": weeks["week_end"].dt.strftime("%Y-%m-%d").to_numpy()[inv_raw["week_idx"]],
        "retail_year": weeks["retail_year"].to_numpy()[inv_raw["week_idx"]],
        "retail_week": weeks["retail_week"].to_numpy()[inv_raw["week_idx"]],
        "store_id": dim_store["store_id"].to_numpy()[inv_raw["store_idx"]],
        "product_id": products["product_id"].to_numpy()[inv_raw["prod_idx"]],
        **{c: inv_raw[c].to_numpy() for c in ("opening_stock", "received_qty", "sold_qty", "adjustment_qty", "closing_stock")},
    })
    fact_promotions = promotions.build_fact_promotions(ev_act, ranged, products, dim_store, weeks)
    sim_stores = dim_store.loc[store_mask, "store_id"]
    fact_promotions = fact_promotions[fact_promotions["store_id"].isin(sim_stores)]
    for c in ("start_date", "end_date"):
        fact_promotions[c] = fact_promotions[c].dt.strftime("%Y-%m-%d")
    fact_promotions = fact_promotions.reset_index(drop=True)

    # clean-data snapshot for the answer key and for sample validation
    dq_log = dq_injection.PlantedIssueLog()
    sales_main, late, missing = dq_injection.split_late_and_missing_batches(sales, cfg, scn, dq_log)
    ak = answer_key.build_answer_key(scn, cfg, weeks, dim_store, products, sales, internal, rets, lost, late, missing,
                                     traffic, b2_affected, E_repl, E_base_ak, mean_qty, depth_a, depth_b)

    # planted data-quality issues
    rng_dq = np.random.default_rng(sd["dq"])
    sales_raw = dq_injection.corrupt_sales(sales_main, cfg, dim_store, products, dq_log, rng_dq)
    dim_product_out = products[["product_id", "product_name", "category", "subcategory", "brand", "supplier_id",
                                "supplier_name", "list_price", "unit_cost", "launch_date", "discontinued_date",
                                "status", "list_price_2024"]].copy()
    for c in ("launch_date", "discontinued_date"):
        dim_product_out[c] = dim_product_out[c].dt.strftime("%Y-%m-%d")
    dim_product_raw = dq_injection.corrupt_dim_product(dim_product_out, cfg, dq_log, rng_dq).drop(columns="list_price_2024")
    dim_store_out = dim_store.copy()
    dim_store_out["open_date"] = dim_store_out["open_date"].dt.strftime("%Y-%m-%d")
    dim_store_raw = dq_injection.corrupt_dim_store(dim_store_out, cfg, dq_log)
    inv_rawdq = dq_injection.corrupt_inventory(fact_inventory, cfg, dq_log, rng_dq)
    ret_rawdq = dq_injection.corrupt_returns(rets, sales, cfg, dq_log, rng_dq)
    ret_rawdq = ret_rawdq.drop(columns=[c for c in ret_rawdq.columns if c.startswith("_")])
    promo_rawdq = dq_injection.corrupt_promotions(fact_promotions, cfg, dq_log, rng_dq)
    tgt_rawdq = dq_injection.corrupt_targets(fact_targets, cfg, dq_log, rng_dq)
    dim_date_out = dim_date.copy()
    for c in ("date", "retail_week_start", "same_day_last_year"):
        dim_date_out[c] = pd.to_datetime(dim_date_out[c]).dt.strftime("%Y-%m-%d")

    files = {
        "dim_store.csv": dim_store_raw, "dim_product.csv": dim_product_raw, "dim_date.csv": dim_date_out,
        "fact_sales.csv": sales_raw, "fact_sales_late_batch.csv": late, "fact_inventory.csv": inv_rawdq,
        "fact_returns.csv": ret_rawdq, "fact_promotions.csv": promo_rawdq, "fact_targets.csv": tgt_rawdq,
        "_planted_issues_log.csv": dq_log.to_frame(), "_scenario_answer_key.csv": ak,
    }
    if not write_files:
        log.info("Dry run complete in %.1fs (no files written)", time.time() - t0)
        return {"mode": mode, "answer_key": ak, "row_counts": {k: int(len(v)) for k, v in files.items()},
                "clean_sales_lines": int(len(sales)), "runtime_seconds": round(time.time() - t0, 1)}
    for name, df in files.items():
        df.to_csv(out / name, index=False)
        log.info("Wrote %-28s %10s rows", name, f"{len(df):,}")

    # projected full-scale volumes (analytical, no full data generated)
    full_mask = np.ones(len(dim_store), dtype=bool)
    E_full = demand.expected_lines(cfg, dim_store, products, weeks, ranged, live, full_mask, sd["demand"], week_share,
                                   promo_mult=mult_a, traffic_mult=traffic, with_noise=False)
    manifest = {
        "mode": mode, "seed": seed, "config_hash": _config_hash(),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "runtime_seconds": round(time.time() - t0, 1),
        "simulated_stores": dim_store.loc[store_mask, "store_id"].tolist(),
        "row_counts": {k: int(len(v)) for k, v in files.items()},
        "clean_sales_lines": int(len(sales)),
        "projected_full_scale_demand_lines": int(E_full.sum()),
    }
    (out / "_generation_manifest.json").write_text(json.dumps(manifest, indent=2))
    log.info("Done in %.1fs", manifest["runtime_seconds"])
    return manifest


def main():
    """CLI entry point: generate the sample or full dataset."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", choices=["sample", "full"], default="sample")
    a = ap.parse_args()
    path = setup_logging(a.mode)
    try:
        run(a.mode)
    except Exception:
        log.exception("Generation failed. See %s", path)
        raise


if __name__ == "__main__":
    main()
