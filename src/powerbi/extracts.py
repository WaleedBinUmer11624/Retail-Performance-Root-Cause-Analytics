"""Phase 5/6 analytical tables for Power BI (powerbi/data/*.csv).

Power BI cannot recompute difference-in-differences, lost-sales baselines or sensitivity ranges, so the
report imports the validated Phase 6 (and Phase 5) outputs as small tables. This module only SELECTS and
RENAMES columns from frozen files; it never recalculates a figure. Each extract is listed in
powerbi/data/extract_manifest.csv with the SHA-256 of its source file.

These tables are disconnected in the model (no relationships): they describe the validated H2 2025 vs
H2 2024 comparison and must not respond to slicers. Every visual that uses them says so.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.analytics.model_access import PROJECT_ROOT, sha256_normalised

from .access import allowed_path, read_csv

P6 = "reports/phase6/"
P5 = "reports/phase5/"


def _evidence(cfg: dict) -> pd.DataFrame:
    ev = read_csv(P6 + "root_cause_evidence_matrix.csv", cfg)
    lv = cfg["powerbi"]["evidence_levels"]
    drv = cfg["powerbi"]["drivers"]
    out = pd.DataFrame({
        "driver_id": ev["driver_id"],
        "driver": ev["driver_id"].map(lambda d: drv[d]["short"]),
        "candidate_driver": ev["candidate_driver"],
        "evidence_level": ev["evidence_level"],
        "cause_status": ev["driver_id"].map(lambda d: drv[d]["cause_status"]),
        "evidence_display": ev["driver_id"].map(lambda d: drv[d]["display"]),
        "evidence_strength": ev["evidence_level"].map(lambda l: lv[l]["strength"]),
        "evidence_colour": ev["evidence_level"].map(lambda l: lv[l]["colour"]),
        "observed_effect": ev["observed_change"],
        "financial_impact_eur": ev["estimated_impact_eur"],
        "impact_pp_of_py_revenue": ev["estimated_impact_pp"],
        "impact_range": ev["impact_range_eur"],
        "what_we_know": ev["evidence_supporting"],
        "what_we_do_not_know": ev["evidence_against"],
        "confidence": ev["uncertainty"],
        "method": ev["method"],
        "additional_data_required": ev["additional_data_required"],
        "double_counting_risk": ev["double_counting_risk"],
        "conclusion": ev["conclusion"],
    })
    out["sort_order"] = range(1, len(out) + 1)
    return out


def _attribution(cfg: dict) -> pd.DataFrame:
    a = read_csv(P6 + "driver_attribution.csv", cfg)
    ev = read_csv(P6 + "root_cause_evidence_matrix.csv", cfg).set_index("driver_id")
    ids = cfg["powerbi"]["attribution_drivers"]
    if len(ids) != len(a):
        raise ValueError("attribution_drivers does not match driver_attribution.csv")
    drv = cfg["powerbi"]["drivers"]
    kind = {"D01": "ESTIMATE (DiD vs controls)", "D03": "ESTIMATE (lost-sales model)", "D05": "FACT (measured refunds)",
            "D07": "ESTIMATE (category DiD)", "D09": "Remainder (total minus ESTIMATES)"}
    # Category labels for the native waterfall: it cannot hatch bars, so the evidence class is in the label text.
    label = {"D01": "Store-cluster excess vs controls [ESTIMATE; cause UNRESOLVED]",
             "D03": "E&T full-week stock-outs [ESTIMATE; root-cause evidence]",
             "D05": "E&T 'Faulty' refunds increase [FACT; defect is a HYPOTHESIS]",
             "D07": "H&K category-specific change [ESTIMATE; association only]",
             "D09": "Residual [remainder of ESTIMATES; not attributed]"}
    return pd.DataFrame({
        "sort_order": range(1, len(a) + 1), "driver_id": ids, "component": a["component"],
        "waterfall_label": [label[i] for i in ids],
        "driver": [drv[i]["short"] for i in ids], "amount_eur": a["amount_eur"],
        "share_of_change": a["share_of_change"], "overlap_removed_eur": a["overlap_removed_eur"],
        "evidence_level": [ev.loc[i, "evidence_level"] if i != "D09" else "Not attributed" for i in ids],
        "evidence_display": [drv[i]["display"] for i in ids], "figure_type": [kind[i] for i in ids],
        "basis": a["basis"]})


def _investigations(cfg: dict) -> pd.DataFrame:
    ev = read_csv(P6 + "root_cause_evidence_matrix.csv", cfg).set_index("driver_id")
    owners = cfg["powerbi"]["investigation_owners"]
    rows = []
    for i, inv in enumerate(cfg["powerbi"]["investigations"], start=1):
        d = inv["driver"]
        rows.append({"priority": i, "topic": inv["topic"], "driver_id": d, "evidence_level": ev.loc[d, "evidence_level"],
                     "known": inv["known"], "unknown": inv["unknown"], "why_it_matters": inv["why_it_matters"],
                     "slice_of_decline_eur": ev.loc[d, "estimated_impact_eur"],
                     "data_required": ev.loc[d, "additional_data_required"],
                     "proposed_owner": owners[d], "owner_note": "Proposed; for management to confirm"})
    return pd.DataFrame(rows)


def _store_groups(cfg: dict) -> pd.DataFrame:
    g = read_csv(P6 + "cluster_control_groups.csv", cfg).set_index("control_group")
    matched = [s.strip() for s in g.loc["matched", "stores"].split(",")]
    allnc = [s.strip() for s in g.loc["all_non_cluster", "stores"].split(",")]
    cluster = cfg["powerbi"]["store_cluster"]
    rows = [{"store_id": s, "store_group": "Investigated cluster"} for s in cluster]
    rows += [{"store_id": s, "store_group": "Matched control" if s in matched else "Other store"} for s in allnc]
    return pd.DataFrame(rows).sort_values("store_id").reset_index(drop=True)


def _sensitivity(cfg: dict) -> pd.DataFrame:
    s = read_csv(P6 + "sensitivity_summary.csv", cfg)
    return s[["driver", "n_variants", "min", "max", "central", "robust", "variants_excluded_low_coverage"]].rename(
        columns={"min": "range_low_eur", "max": "range_high_eur", "central": "central_eur"})


def _stockout_net(cfg: dict) -> pd.DataFrame:
    s = read_csv(P6 + "sensitivity_analysis.csv", cfg)
    s = s[s["method"].str.contains("net of recovery")]
    return s[["driver", "method", "variant", "estimate_eur"]].reset_index(drop=True)


def _hk_methods(cfg: dict) -> pd.DataFrame:
    c = read_csv(P6 + "hk_promotion_counterfactuals.csv", cfg)
    keep = c[~c["method"].str.contains("gross margin")].copy()
    keep["method_code"] = keep["method"].str.extract(r"^(M\d)")[0]
    keep["direction"] = keep["effect_eur"].map(lambda v: "Promotions reduced revenue" if v < 0 else "Promotions added revenue")
    keep["interval_type"] = keep["method_code"].map({"M1": "95% CI (store bootstrap)", "M2": "95% CI (store bootstrap)",
                                                     "M3": "none", "M4": "range (volume response at M1 units CI)"})
    order = {"M1": 1, "M4": 2, "M2": 3, "M3": 4}
    keep["sort_order"] = keep["method_code"].map(order)
    return keep.sort_values("sort_order")[["sort_order", "method_code", "method", "effect_eur", "ci_low", "ci_high",
                                           "interval_type", "direction", "detail"]].reset_index(drop=True)


# name -> (source file, builder or column selection)
EXTRACTS = {
    "p6_driver_attribution": (P6 + "driver_attribution.csv", _attribution),
    "p6_evidence_matrix": (P6 + "root_cause_evidence_matrix.csv", _evidence),
    "p6_investigations": (P6 + "root_cause_evidence_matrix.csv", _investigations),
    "p6_store_groups": (P6 + "cluster_control_groups.csv", _store_groups),
    "p6_scenarios": (P6 + "counterfactual_scenarios.csv", None),
    "p6_sensitivity_summary": (P6 + "sensitivity_summary.csv", _sensitivity),
    "p6_stockout_net_of_recovery": (P6 + "sensitivity_analysis.csv", _stockout_net),
    "p6_perimeter": (P6 + "driver_perimeter_matrix.csv", None),
    "p6_residual_breakdown": (P6 + "driver_residual_breakdown.csv", None),
    "p6_cluster_did": (P6 + "cluster_did.csv", None),
    "p6_cluster_onset": (P6 + "cluster_onset.csv", None),
    "p6_cluster_onset_by_store": (P6 + "cluster_onset_by_store.csv", None),
    "p6_cluster_onset_daily": (P6 + "cluster_onset_daily.csv", None),
    "p6_cluster_mechanisms": (P6 + "cluster_mechanisms.csv", None),
    "p6_cluster_placebo": (P6 + "cluster_placebo.csv", None),
    "p6_et_kpis": (P6 + "electronics_kpis.csv", None),
    "p6_et_supplier_comparison": (P6 + "electronics_supplier_comparison.csv", None),
    "p6_et_supplier_test": (P6 + "electronics_supplier_test.csv", None),
    "p6_et_sku_stockouts": (P6 + "electronics_sku_stockouts.csv", None),
    "p6_et_episodes": (P6 + "electronics_stockout_episodes.csv", None),
    "p6_et_lost_sales_totals": (P6 + "electronics_lost_sales_totals.csv", None),
    "p6_et_weekly_timeline": (P6 + "electronics_weekly_timeline.csv", None),
    "p6_et_range_distribution": (P6 + "electronics_range_distribution.csv", None),
    "p6_faulty_reasons": (P6 + "faulty_returns_reasons.csv", None),
    "p6_faulty_by_store": (P6 + "faulty_returns_by_store.csv", None),
    "p6_faulty_by_supplier": (P6 + "faulty_returns_by_supplier.csv", None),
    "p6_faulty_by_product": (P6 + "faulty_returns_by_product.csv", None),
    "p6_faulty_by_cohort": (P6 + "faulty_returns_by_cohort.csv", None),
    "p6_faulty_concentration": (P6 + "faulty_returns_concentration.csv", None),
    "p6_hk_methods": (P6 + "hk_promotion_counterfactuals.csv", _hk_methods),
    "p6_hk_weekly": (P6 + "hk_promotion_weekly.csv", None),
    "p6_hk_events_by_year": (P6 + "hk_promotion_events_by_year.csv", None),
    "p5_revenue_bridge": (P5 + "revenue_bridge.csv", None),
}


def build(cfg: dict, out_dir: Path) -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
    out_dir.mkdir(parents=True, exist_ok=True)
    tables, man = {}, []
    for name, (src, fn) in EXTRACTS.items():
        df = fn(cfg) if fn else read_csv(src, cfg)
        tables[name] = df
        df.to_csv(out_dir / f"{name}.csv", index=False, lineterminator="\n")
        man.append({"extract": f"{name}.csv", "rows": len(df), "source_file": src,
                    "source_sha256": sha256_normalised(allowed_path(src, cfg)),
                    "transformation": "column selection / renaming and labels from config/powerbi_config.yaml"
                    if fn else "copy (no transformation)"})
    manifest = pd.DataFrame(man)
    manifest.to_csv(out_dir / "extract_manifest.csv", index=False, lineterminator="\n")
    return tables, manifest


def relpath(p: Path) -> str:
    return p.resolve().relative_to(PROJECT_ROOT).as_posix()
