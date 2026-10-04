"""Scenario calibration dry run (estate level).

Runs the complete 20-store generator in memory with the same seed and code
path as `--mode full`, and writes ONLY an aggregate calibration report. No
row-level data files are produced. Because generation is deterministic, the
full run will reproduce exactly these figures.

Why a dry run: the 4-store sample over-represents the scenario stores, so its
percentages are not company-level. The BRD headline (about -8% H2 net revenue)
can only be checked across the whole estate.

Usage:  python -m src.data_generation.calibrate_scenario [--sensitivity]
        --sensitivity also re-runs the dry run with alternative seeds to show
        how much of the headline is design and how much is random variation.
Output: reports/phase2_calibration_report.json (evaluation-only; contains answer-key figures)
"""
from __future__ import annotations

import argparse
import json
import logging
import statistics
import sys

from .config_loader import PROJECT_ROOT
from .generate_data import run

TARGET_BAND = (-8.5, -7.5)  # apparent (reported) YoY %, BRD headline
REPORT = PROJECT_ROOT / "reports" / "phase2_calibration_report.json"
SENSITIVITY_SEEDS = (11, 2027, 424242, 777, 31337)


def _reported_yoy(seed: int) -> dict:
    ak = run("full", write_files=False, seed=seed)["answer_key"].set_index("behaviour")
    pp = ak["impact_pp_of_h2_2024_net_revenue"]
    return {"seed": seed, "reported_yoy_pct": float(pp["H2 2025 net revenue (reported)"]),
            "underlying_yoy_pct": float(pp["H2 2025 net revenue (underlying)"]),
            "residual_pp": float(pp["Natural variation, price, mix and other (residual)"])}


def calibrate(sensitivity: bool = False) -> dict:
    """Run the full generator in memory and write the aggregate calibration report."""
    res = run("full", write_files=False)
    ak = res["answer_key"].set_index("behaviour")
    v = lambda name: float(ak.loc[name, "impact_eur"])
    pp = lambda name: float(ak.loc[name, "impact_pp_of_h2_2024_net_revenue"])
    drivers = ak[ak["behaviour_id"].isin(["B1", "B2", "B3", "B4", "OTHER"])].reset_index()
    report = {
        "h2_2024_net_revenue_underlying": v("H2 2024 net revenue (underlying)"),
        "h2_2024_net_revenue_reported": v("H2 2024 net revenue (reported)"),
        "h2_2025_net_revenue_underlying": v("H2 2025 net revenue (underlying)"),
        "h2_2025_net_revenue_reported": v("H2 2025 net revenue (reported)"),
        "yoy_pct_underlying": pp("H2 2025 net revenue (underlying)"),
        "yoy_pct_reported": pp("H2 2025 net revenue (reported)"),
        "dq_artefact_pp": pp("Data-completeness artefact (reported minus underlying YoY)"),
        "dq_artefact_eur": v("Data-completeness artefact (reported minus underlying YoY)"),
        "late_batch_revenue_h2_2025": v("Late batch sales revenue (H2 2025)"),
        "missing_batch_revenue_h2_2024": v("Missing batch sales revenue (H2 2024)"),
        "drivers": {r["behaviour"]: {"eur": r["impact_eur"], "pp": r["impact_pp_of_h2_2024_net_revenue"]}
                    for _, r in drivers.iterrows()},
        "target_band_reported_yoy_pct": list(TARGET_BAND),
        "projected_full_row_counts": res["row_counts"],
        "clean_sales_lines": res["clean_sales_lines"],
        "runtime_seconds": res["runtime_seconds"],
    }
    report["in_target_band"] = TARGET_BAND[0] <= report["yoy_pct_reported"] <= TARGET_BAND[1]
    report["drivers_sum_pp"] = round(sum(d["pp"] for d in report["drivers"].values()), 2)
    if sensitivity:
        runs = [_reported_yoy(s) for s in SENSITIVITY_SEEDS]
        allrep = [report["yoy_pct_reported"]] + [r["reported_yoy_pct"] for r in runs]
        report["seed_sensitivity"] = {"alternative_seeds": runs, "reported_yoy_mean_all_seeds": round(statistics.mean(allrep), 2),
                                      "reported_yoy_sd_all_seeds": round(statistics.stdev(allrep), 2)}
    REPORT.parent.mkdir(exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2))
    return report


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s", stream=sys.stdout)
    ap = argparse.ArgumentParser()
    ap.add_argument("--sensitivity", action="store_true")
    print(json.dumps(calibrate(ap.parse_args().sensitivity), indent=2))
