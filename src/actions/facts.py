"""Phase 8 fact base: every number Phase 8 prints, read from a frozen Phase 5, 6 or 7 file.

A fact carries its value, the file and row it came from and its evidence tag. Text in config/action_config.yaml
refers to facts with {key|format} placeholders, so no figure is typed by hand. `derived` facts are arithmetic on
other facts (named in the locator) and are tagged like their inputs.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from .access import read_csv

REG = "reports/phase7/dashboard_number_register.csv"
P6 = "reports/phase6/"
P5 = "reports/phase5/"
MATRIX = "reports/phase6/root_cause_evidence_matrix.csv"

# key -> Phase 7 register id (the register traces each of these to a DAX measure or a frozen Phase 5/6 cell)
REGISTER_FACTS = {
    "nr_cy": "P1-01", "nr_py": "P1-02", "nr_change": "P1-03", "nr_yoy": "P1-04",
    "gm_cy": "P1-05", "gm_change": "P1-06", "gmpct_cy": "P1-07", "gmpct_py": "P1-08",
    "tx_cy": "P1-09", "tx_change": "P1-10", "tx_yoy": "P1-11", "ret_cy": "P1-12", "rr_cy": "P1-13", "rr_py": "P1-14",
    "d01_eur": "P1-20a", "d01_share": "P1-20b", "d03_eur": "P1-21a", "d03_share": "P1-21b",
    "d05_eur": "P1-22a", "d05_share": "P1-22b", "d07_eur": "P1-23a", "d07_share": "P1-23b",
    "d09_eur": "P1-24a", "d09_share": "P1-24b",
    "bridge_tx": "P1-30", "bridge_upt": "P1-31", "bridge_asp": "P1-32", "bridge_ret": "P1-33",
    "cl_nr_yoy": "P2-00", "cl_tx_yoy": "P2-01", "cl_atv": "P2-02", "cl_upt": "P2-03", "cl_asp": "P2-04",
    "cl_avail": "P2-05", "cl_promo": "P2-06", "cl_rr": "P2-07",
    "mc_nr_yoy": "P2-10", "mc_tx_yoy": "P2-11", "mc_atv": "P2-12", "mc_upt": "P2-13", "mc_asp": "P2-14",
    "mc_avail": "P2-15", "mc_promo": "P2-16", "mc_rr": "P2-17",
    "es_avail": "P2-25", "es_promo": "P2-26", "es_upt": "P2-23", "es_asp": "P2-24", "es_atv": "P2-22",
    "cl_low": "P2-E2", "cl_high": "P2-E3", "cl_did_tx": "P2-E4", "cl_onset": "P2-E5",
    "cl_onset_s03": "P2-OS03", "cl_onset_s04": "P2-OS04", "cl_onset_s05": "P2-OS05", "cl_placebo_p": "P2-E6",
    "et_nr_cy": "P3-01", "et_change": "P3-02", "et_yoy": "P3-03", "et_units_yoy": "P3-04", "et_tx_yoy": "P3-05",
    "et_avail_py": "P3-07", "et_avail_cy": "P3-08", "et_ret_cy": "P3-09",
    "vx_ep_py": "P3-E2024", "vx_ep_cy": "P3-E2025", "vx_len_py": "P3-M2024", "vx_len_cy": "P3-M2025",
    "vx_full_cy": "P3-F1", "vx_full_py": "P3-F0",
    "ls_gross": "P3-L1", "ls_net": "P3-L2", "ls_low": "P3-L3", "ls_high": "P3-L4",
    "ls_top10": "P3-C1", "ls_top1": "P3-C2", "ls_top3": "P3-C3", "vx_rate_diff": "P3-S1",
    "fy_change": "P4-01", "fy_yoy": "P4-02", "fy_cy": "P4-03",
    "fy_top5_stores": "P4-C1", "fy_top5_products": "P4-C2",
    "fy_k202409": "P4-K202409", "fy_k202412": "P4-K202412", "fy_k202509": "P4-K202509", "fy_k202511": "P4-K202511",
    "fy_s13_cy": "P4-SS13", "fy_s13_py": "P4-PS13", "fy_k202411": "P4-K202411", "fy_damaged": "P4-R1",
    "hk_nr_cy": "P5-01", "hk_change": "P5-02", "hk_units_yoy": "P5-03", "hk_asp_cy": "P5-04", "hk_asp_py": "P5-05",
    "hk_gm_change": "P5-06", "hk_promo_cy": "P5-07", "hk_promo_py": "P5-08", "hk_disc_py": "P5-09", "hk_disc_cy": "P5-10",
    "hk_ev_py": "P5-E2024", "hk_ev_cy": "P5-E2025", "hk_dip_py": "P5-D2024", "hk_dip_cy": "P5-D2025",
    "m1": "P5-M1", "m4": "P5-M4", "m2": "P5-M2", "m3": "P5-M3", "m3_contam": "P5-C25", "m1_gm": "P5-GM",
    "d04_eur": "P6-D04",
}


@dataclass
class Fact:
    key: str
    value: object
    source: str
    locator: str
    tag: str
    derived_from: list = field(default_factory=list)


class Facts:
    def __init__(self):
        self.items: dict[str, Fact] = {}
        self.used: set[str] = set()

    def add(self, key, value, source, locator, tag, derived_from=None):
        if key in self.items:
            raise KeyError(f"duplicate fact {key}")
        self.items[key] = Fact(key, value, source, locator, tag, list(derived_from or []))

    def __getitem__(self, key):
        self.used.add(key)
        return self.items[key].value

    def table(self, only_used=False) -> pd.DataFrame:
        keys = sorted(self.used) if only_used else sorted(self.items)
        rows = []
        for k in keys:
            f = self.items[k]
            rows.append({"fact": k, "value": f.value, "source": f.source, "locator": f.locator, "evidence_tag": f.tag,
                         "derived_from": ", ".join(f.derived_from)})
        return pd.DataFrame(rows)


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return v


def build(cfg: dict) -> Facts:
    F = Facts()
    reg = read_csv(REG, cfg).set_index("id")
    for key, rid in REGISTER_FACTS.items():
        r = reg.loc[rid]
        F.add(key, _num(r["value"]), f"{REG} ({r['source']})", f"id={rid}; {r['label']}", r["evidence_tag"])

    def cell(key, file, where: dict, col, tag):
        d = read_csv(file, cfg)
        m = pd.Series(True, index=d.index)
        for c, v in where.items():
            m &= d[c].astype(str) == str(v)
        hit = d[m]
        if len(hit) != 1:
            raise ValueError(f"{file} {where}: {len(hit)} rows")
        loc = ", ".join(f"{c}={v}" for c, v in where.items()) or "single row"
        F.add(key, _num(hit.iloc[0][col]), file, f"{loc}; column {col}", tag)

    F.add("high_seller_share", float(cfg["rca"]["electronics"]["high_seller_top_share"]), "config/rca_config.yaml",
          "electronics.high_seller_top_share (the Phase 6 definition of high-selling SKUs)", "DEFINITION")
    att = P6 + "driver_attribution.csv"
    d = read_csv(att, cfg)
    F.add("att_total", float(d["amount_eur"].sum()), att, "sum of amount_eur over the 5 components", "FACT (sum)")
    F.add("att_share_total", float(d["share_of_change"].sum()), att, "sum of share_of_change", "FACT (sum)")
    sens = P6 + "sensitivity_summary.csv"
    cell("hk_range_low", sens, {"driver": "home_kitchen_promotion"}, "min", "ESTIMATE")
    cell("hk_range_high", sens, {"driver": "home_kitchen_promotion"}, "max", "ESTIMATE")
    cell("fy_range_low", sens, {"driver": "electronics_faulty_returns"}, "max", "ESTIMATE")
    cell("ls_upper_bound", P6 + "electronics_lost_sales_totals.csv", {"scope": "category"}, "upper_change",
         "ESTIMATE (upper bound, not evidence)")
    cell("ls_voltix", P6 + "electronics_lost_sales_totals.csv", {"scope": "top_supplier"}, "primary_change", "ESTIMATE")
    F.add("ls_deferred", abs(F.items["ls_gross"].value) - abs(F.items["ls_net"].value), "derived",
          "|ls_gross| minus |ls_net| (demand that returned after restock)", "ESTIMATE", ["ls_gross", "ls_net"])
    F.add("ls_zero", 0.0, "assumption", "Conservative scenario: no recovery assumed", "SCENARIO (assumption)")
    F.add("ls_voltix_share", abs(F.items["ls_voltix"].value) / abs(F.items["ls_gross"].value), "derived",
          "ls_voltix / ls_gross", "ESTIMATE", ["ls_voltix", "ls_gross"])
    scen = P6 + "counterfactual_scenarios.csv"
    cell("ls_margin", scen, {"scenario": "B"}, "margin_impact_eur", "ESTIMATE")
    hkm = P6 + "hk_promotion_counterfactuals.csv"
    cell("m1_ci_low", hkm, {"method": "M1 category DiD (sales)"}, "ci_low", "ESTIMATE")
    cell("m1_ci_high", hkm, {"method": "M1 category DiD (sales)"}, "ci_high", "ESTIMATE")
    cell("m2_ci_high", hkm, {"method": "M2 dose-response (promotion coverage lags 0-2, depth, store FE)"}, "ci_high", "ESTIMATE")
    cell("m4_ci_low", hkm, {"method": "M4 discount-rate accounting (net volume response 0; range = volume response at the M1 units CI bounds)"},
         "ci_low", "ESTIMATE")
    mx = read_csv(MATRIX, cfg).set_index("driver_id")

    def parsed(key, driver, col, pattern, group, tag, scale=1.0):
        text = str(mx.loc[driver, col])
        m = re.search(pattern, text)
        if not m:
            raise ValueError(f"{key}: pattern not found in {driver}.{col}")
        F.add(key, float(m.group(group)) * scale, MATRIX, f"driver_id={driver}; column {col}; parsed '{m.group(0)}'", tag)

    parsed("m1_units", "D07", "evidence_supporting", r"units (-?[\d.]+)% \(CI (-?[\d.]+)% to \+?(-?[\d.]+)%\)", 1, "ESTIMATE", 0.01)
    parsed("m1_units_ci_low", "D07", "evidence_supporting", r"units (-?[\d.]+)% \(CI (-?[\d.]+)% to \+?(-?[\d.]+)%\)", 2, "ESTIMATE", 0.01)
    parsed("m1_units_ci_high", "D07", "evidence_supporting", r"units (-?[\d.]+)% \(CI (-?[\d.]+)% to \+?(-?[\d.]+)%\)", 3, "ESTIMATE", 0.01)
    parsed("fy_top_supplier_share", "D06", "evidence_supporting", r"largest holds (\d+)% of the increase", 1, "FACT", 0.01)
    cell("cl_dublin_excess", P6 + "cluster_did.csv", {"control_group": "dublin_non_cluster", "outcome": "ly_net_revenue"},
         "ratio_did_excess", "ESTIMATE")
    ev = P6 + "hk_promotion_events_by_year.csv"
    cell("hk_cannib_py", ev, {"retail_year": 2024}, "cannibalised_revenue", "ESTIMATE")
    cell("hk_cannib_cy", ev, {"retail_year": 2025}, "cannibalised_revenue", "ESTIMATE")
    cell("hk_disc_cost_py", ev, {"retail_year": 2024}, "discount_cost", "FACT")
    cell("hk_disc_cost_cy", ev, {"retail_year": 2025}, "discount_cost", "FACT")
    res = P6 + "driver_residual_breakdown.csv"
    for i, k in enumerate(["res_et_other", "res_hk_other", "res_other_cat", "res_cluster_rate"]):
        d = read_csv(res, cfg)
        F.add(k, float(d.iloc[i]["amount_eur"]), res, f"part={d.iloc[i]['part']}; column amount_eur", "ESTIMATE (remainder)")
    rng = P6 + "electronics_range_distribution.csv"
    d = read_csv(rng, cfg)
    for status, k in [("continuing", "d08_continuing"), ("new", "d08_new"), ("delisted", "d08_delisted")]:
        F.add(k, float(d[d["sku_status"] == status]["sales_change"].sum()), rng,
              f"sum of sales_change where sku_status={status} (the file covers stores outside the cluster, as the Phase 6 matrix D08 row states)",
              "FACT")
    epi = P6 + "electronics_stockout_episodes.csv"
    d = read_csv(epi, cfg)
    F.add("et_full_cy", int(d[d["retail_year"] == 2025]["full_weeks_out"].sum()), epi,
          "sum of full_weeks_out where retail_year=2025 (all suppliers)", "FACT")
    F.add("et_full_py", int(d[d["retail_year"] == 2024]["full_weeks_out"].sum()), epi,
          "sum of full_weeks_out where retail_year=2024 (all suppliers)", "FACT")
    sku = P6 + "electronics_sku_stockouts.csv"
    d = read_csv(sku, cfg).sort_values("lost_primary_change", ascending=False)
    F.add("top3_skus", ", ".join(d["product_id"].head(3)), sku, "product_id of the 3 largest lost_primary_change", "FACT")
    conc = P6 + "faulty_returns_concentration.csv"
    cell("fy_stores", conc, {"dimension": "store_id"}, "top_entities", "FACT")
    cell("fy_products", conc, {"dimension": "product_id"}, "top_entities", "FACT")
    cg = P6 + "cluster_control_groups.csv"
    cell("mc_stores", cg, {"control_group": "matched"}, "stores", "FACT")
    cell("n_test_stores", cg, {"control_group": "all_non_cluster"}, "n_stores", "FACT")
    wk = P6 + "cluster_weekly_did.csv"
    d = read_csv(wk, cfg)
    last = d.sort_values("retail_week").iloc[-1]
    F.add("cl_gap_last_week", int(last["retail_week"]), wk, "last retail_week in the file", "FACT")
    F.add("cl_gap_last_pct", math.expm1(float(last["gap_log_transactions"])), wk,
          f"retail_week={int(last['retail_week'])}; exp(gap_log_transactions) - 1", "ESTIMATE")
    hl = P5 + "headline_kpis.csv"
    for metric, k in [("transactions", "tx_py"), ("upt", "upt_py"), ("upt", "upt_cy"), ("asp", "asp_py"),
                      ("asp", "asp_cy"), ("promo_revenue_share", "promo_py"), ("promo_revenue_share", "promo_cy")]:
        col = "h2_prior" if k.endswith("_py") else "h2_current"
        cell(k, hl, {"metric": metric}, col, "FACT")
    return F


# ----------------------------------------------------------------------------- formatting
MINUS = "-"


def _eur(v, dp=0):
    s = f"€{abs(v):,.{dp}f}"
    return (MINUS + s) if v < 0 and round(abs(v), dp) != 0 else s


def fmt(v, spec: str) -> str:
    if spec == "text":
        return str(v)
    if spec == "date":
        return date.fromisoformat(str(v)).strftime("%d %b %Y").lstrip("0")
    if spec == "dmon":
        return date.fromisoformat(str(v)).strftime("%d %b").lstrip("0")
    v = float(v)
    table = {
        "eur": lambda: _eur(v), "eur2": lambda: _eur(v, 2), "abseur": lambda: _eur(abs(v)),
        "seur": lambda: ("+" if v > 0 else "") + _eur(v),
        "eurk": lambda: (MINUS if v < 0 else "") + f"€{abs(v) / 1e3:,.0f}k",
        "abseurk": lambda: f"€{abs(v) / 1e3:,.0f}k",
        "eurm": lambda: (MINUS if v < 0 else "") + f"€{abs(v) / 1e6:,.3f}M",
        "pct0": lambda: f"{100 * v:.0f}%", "pct1": lambda: f"{100 * v:.1f}%", "pct2": lambda: f"{100 * v:.2f}%",
        "abspct0": lambda: f"{100 * abs(v):.0f}%", "abspct1": lambda: f"{100 * abs(v):.1f}%",
        "spct0": lambda: f"{100 * v:+.0f}%", "spct1": lambda: f"{100 * v:+.1f}%",
        "pctv1": lambda: f"{v:.1f}%", "spctv1": lambda: f"{v:+.1f}%",
        "pp1": lambda: f"{v:+.1f} pp", "pp1u": lambda: f"{abs(v):.1f} pp", "pct6": lambda: f"{100 * v:.6f}%",
        "int": lambda: f"{v:,.0f}", "dec1": lambda: f"{v:.1f}", "dec2": lambda: f"{v:.2f}", "p": lambda: f"{v:.4f}",
    }
    if spec not in table:
        raise ValueError(f"unknown format {spec}")
    return table[spec]()


PLACEHOLDER = re.compile(r"\{([a-z0-9_]+)\|([a-z0-9]+)\}")


def render(text: str, F: Facts, used: set | None = None) -> str:
    """Replace every {key|format} with the formatted fact; record the keys used."""
    if not isinstance(text, str):
        return text

    def sub(m):
        key, spec = m.group(1), m.group(2)
        if key not in F.items:
            raise KeyError(f"unknown fact {key} in: {text[:80]}")
        if used is not None:
            used.add(key)
        return fmt(F[key], spec)

    out = PLACEHOLDER.sub(sub, text)
    if "{" in out or "}" in out:
        raise ValueError(f"unresolved placeholder in: {out[:120]}")
    return out
