"""Back-test of every candidate rule, false-alarm analysis and threshold selection.

Terminology (no ground truth exists outside the known episodes, so nothing is called a confirmed false positive):
  known-episode alert   an alert on an entity-week inside a known episode (Phase 5/6 findings)
  DQ-held alert         the rule was breached but the week failed the DQ gate: held, not escalated
  unconfirmed alert     an alert outside every known episode: unexplained, not proven false
  isolated alert        an alert episode that lasted one week
A rule fires at week t when its breach held for `k` consecutive evaluated weeks ending at t (DQ-failed weeks and
weeks without a baseline never count as breaches).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .baselines import consecutive

# candidate families per signal, in interpretability order; comparison families are reported but not selectable
FAMILIES = {
    "EW01": [("peer_gap_threshold", "gap", "threshold_pct", [1, 2, 3]), ("robust_z", "rz", "robust_z", [1, 2]),
             ("cusum", "cusum", "cusum_h", [1])],
    "EW02": [("yoy_vs_trend_threshold", "yoydev", "threshold_pct", [1, 2, 3])],
    "EW03": [("availability_gap_pp", "pp", "threshold_pp", [1, 2, 4])],
    "EW04": [("stores_out_count", "st", "min_stores", [1, 2, 3])],
    "EW05": [("binomial_excess", "a", "alpha", [1, 2])],
    "EW06": [("margin_gap_pp", "pp", "threshold_pp", [1, 2, 4])],
    "EW07": [("discount_gap_pp", "pp", "threshold_pp", [1, 2, 3])],
    "EW08": [("dq_gate_fail", "fail", None, [1])],
}
COMPARISON = {"EW01": [("yoy_threshold", "yoy", "threshold_pct", [1, 2, 3]), ("rolling_z", "zroll", "robust_z", [1, 2])]}
# second, independent rule that also raises WARNING: Phase 8 named a change-point test as the EW01 threshold concept.
# It goes through the same budget-based selection as the primary rule (review finding M3).
SECONDARY = {"EW01": [("changepoint_online", "cp", "changepoint_bic_delta", [1])]}
ALARM_FAMILIES = {"cusum", "changepoint_online", "dq_gate_fail"}   # the rule itself carries persistence


def candidate_columns(frame: pd.DataFrame, signal: str, cfg: dict, comparison: bool | str = False) -> list[dict]:
    fams = (SECONDARY.get(signal, []) if comparison == "secondary" else COMPARISON.get(signal, []) if comparison
            else FAMILIES[signal])
    c = cfg["monitoring"]["signals"][signal].get("candidates", {})
    out = []
    for fam, prefix, key, ks in fams:
        if signal == "EW05":
            for a in c["alpha"]:
                for m in c["min_excess_units"]:
                    for k in c["persistence"]:
                        out.append({"family": fam, "col": f"b_a{a}_m{m}", "threshold": f"p<{a}, excess>={m}",
                                    "sort": -a * 1000 + m, "k": k})
            continue
        if key is None:
            out.append({"family": fam, "col": "b_fail", "threshold": "gate FAIL", "sort": 0, "k": 1})
            continue
        vals = c[key]
        ks_use = c.get("persistence", ks) if fam not in ALARM_FAMILIES else [1]
        if fam == "robust_z" or fam == "rolling_z":
            ks_use = [k for k in c.get("persistence", [1, 2]) if k <= 2]
        for v in vals:
            for k in ks_use:
                if f"b_{prefix}{v}" in frame.columns:
                    # sensitivity order: the smaller threshold (percentage, pp, z, h, store count) is the more sensitive
                    out.append({"family": fam, "col": f"b_{prefix}{v}", "threshold": str(v), "sort": v, "k": k})
    return out


def fires(frame: pd.DataFrame, col: str, k: int) -> tuple[pd.Series, pd.Series]:
    """(fire, dq_held): fire when the gated breach has lasted k consecutive evaluated weeks."""
    ok = frame["baseline_ok"].fillna(False).astype(bool)
    breach = frame[col].fillna(False).astype(bool) & ok
    gated = breach & ~frame["dq_fail"].astype(bool)
    run = consecutive(gated, frame["entity"], frame["t"])
    return run >= k, breach & frame["dq_fail"].astype(bool)


def _episodes(entity: pd.Series, t: pd.Series, on: pd.Series) -> list[tuple]:
    df = pd.DataFrame({"e": entity, "t": t, "on": on}).sort_values(["e", "t"])
    eps, cur = [], None
    for e, tt, o in zip(df["e"], df["t"], df["on"]):
        if o and cur and cur[0] == e and tt == cur[2] + 1:
            cur = (e, cur[1], tt)
        elif o:
            if cur:
                eps.append(cur)
            cur = (e, tt, tt)
        else:
            if cur:
                eps.append(cur)
            cur = None
    if cur:
        eps.append(cur)
    return eps


def metrics(frame: pd.DataFrame, fire: pd.Series, held: pd.Series, cfg: dict) -> dict:
    ev = frame["baseline_ok"].fillna(False).astype(bool)
    f = fire & ev
    nep = ev & ~frame["in_episode"] & ~frame["dq_fail"].astype(bool)
    unconf = f & ~frame["in_episode"]
    eps = _episodes(frame["entity"], frame["t"], f)
    lengths = [b - a + 1 for _, a, b in eps]
    ents_multi = pd.Series([e for e, _, _ in eps]).value_counts()
    weeks = frame.loc[ev, "t"].nunique()
    m = {
        "weeks_tested": int(weeks), "entity_weeks_tested": int(ev.sum()), "alerts": int(f.sum()),
        "alert_rate": float(f.sum() / max(ev.sum(), 1)), "entities_affected": int(frame.loc[f, "entity"].nunique()),
        "alert_episodes": len(eps), "isolated_alerts": int(sum(1 for L in lengths if L == 1)),
        "persistent_episodes_4w": int(sum(1 for L in lengths if L >= 4)),
        "repeat_alert_entities": int((ents_multi > 1).sum()) if len(ents_multi) else 0,
        "median_alert_duration_weeks": float(np.median(lengths)) if lengths else 0.0,
        "non_episode_entity_weeks": int(nep.sum()), "unconfirmed_alerts": int(unconf.sum()),
        "unconfirmed_rate": float(unconf.sum() / max(nep.sum(), 1)),
        "unconfirmed_per_week": float(unconf.sum() / max(weeks, 1)),
        "dq_held_breaches": int(held.sum()),
        "known_episode_alerts": int((f & frame["in_episode"]).sum()),
    }
    # detection of known episodes
    epi = frame[frame["in_episode"]]
    delays, detected, active, pre = [], 0, [], 0
    for e, g in epi.groupby("entity"):
        start_t = g["t"].min()
        hits = frame.index[(frame["entity"] == e) & f & (frame["t"] >= start_t)]
        pre += int(((frame["entity"] == e) & f & (frame["t"] < start_t)).sum())
        if len(hits):
            detected += 1
            delays.append(int(frame.loc[hits, "t"].min() - start_t))
        active.append(float(f.loc[g.index].mean()))
    n_ep = epi["entity"].nunique()
    m.update({
        "episode_entities": int(n_ep), "episode_entities_detected": int(detected),
        "median_detection_delay_weeks": float(np.median(delays)) if delays else np.nan,
        "max_detection_delay_weeks": float(np.max(delays)) if delays else np.nan,
        "episode_weeks_active_share": float(np.mean(active)) if active else np.nan,
        "pre_onset_alerts_on_episode_entities": int(pre),
    })
    exp = frame["exposure"].fillna(0).clip(lower=0)
    tot = exp[frame["in_episode"]].sum()
    m["episode_exposure_covered_share"] = float(exp[frame["in_episode"] & f].sum() / tot) if tot > 0 else np.nan
    return m


def run_candidates(frame: pd.DataFrame, signal: str, cfg: dict) -> pd.DataFrame:
    rows = []
    for comparison in (False, "secondary", True):
        role = {False: "primary", "secondary": "secondary", True: "comparison"}[comparison]
        for c in candidate_columns(frame, signal, cfg, comparison):
            for et, g in frame.groupby("entity_type"):
                g = g.sort_values(["entity", "t"])
                f, h = fires(g, c["col"], c["k"])
                m = metrics(g, f, h, cfg)
                rows.append({"signal": signal, "entity_type": et, "family": c["family"], "rule_column": c["col"],
                             "threshold": c["threshold"], "persistence_weeks": c["k"], "sensitivity_order": c["sort"],
                             "selectable": comparison is False, "role": role, **m})
    return pd.DataFrame(rows)


def select(results: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """Choose one rule per signal x entity type, using only the non-episode false-alarm budget (never the episodes).
    WARNING-level rules need persistence >= 2 weeks unless the rule is an alarm-type rule (CUSUM, DQ gate)."""
    budget = cfg["monitoring"]["selection"]["warning_budget"]
    out = []
    for (sig, et), g in results[results["selectable"]].groupby(["signal", "entity_type"], sort=False):
        order = [f[0] for f in FAMILIES[sig]]
        chosen, reason = None, ""
        for fam in order:
            cand = g[g["family"] == fam]
            if fam not in ALARM_FAMILIES:
                cand = cand[cand["persistence_weeks"] >= 2]
            ok = cand[cand["unconfirmed_rate"] <= budget]
            if len(ok):
                # the smallest threshold inside the budget (it can detect the smallest sustained shift), then the
                # shortest persistence at that threshold. Detection results on the known episodes are never read;
                # the episodes only define which weeks count as noise (unconfirmed_rate is on non-episode weeks).
                ok = ok.sort_values(["sensitivity_order", "persistence_weeks"])
                chosen = ok.iloc[0]
                reason = (f"First family in interpretability order ({fam}) with a candidate inside the {budget:.0%} "
                          f"non-episode budget; smallest compliant threshold, then shortest persistence.")
                break
        if chosen is None:
            cand = g[(g["persistence_weeks"] >= 2) | g["family"].isin(ALARM_FAMILIES)].sort_values("unconfirmed_rate")
            chosen = cand.iloc[0]
            reason = f"No candidate met the {budget:.0%} budget; the lowest-burden candidate is used and flagged."
        row = chosen.to_dict()
        row["selection_reason"] = reason
        row["within_budget"] = bool(chosen["unconfirmed_rate"] <= budget)
        out.append(row)
    return pd.DataFrame(out)


def select_secondary(results: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """The secondary (change-point) rule, chosen exactly like the primary one: within the budget, most sensitive
    compliant candidate. Returns one row per signal x entity type that has a secondary family."""
    budget = cfg["monitoring"]["selection"]["warning_budget"]
    out = []
    for (sig, et), g in results[results["role"] == "secondary"].groupby(["signal", "entity_type"], sort=False):
        ok = g[g["unconfirmed_rate"] <= budget].sort_values(["sensitivity_order", "persistence_weeks"])
        chosen = ok.iloc[0] if len(ok) else g.sort_values("unconfirmed_rate").iloc[0]
        row = chosen.to_dict()
        row["within_budget"] = bool(chosen["unconfirmed_rate"] <= budget)
        row["selection_reason"] = (f"Secondary rule (Phase 8 change-point concept): most sensitive candidate inside the "
                                   f"{budget:.0%} budget." if len(ok) else "No candidate met the budget; lowest burden used.")
        out.append(row)
    return pd.DataFrame(out)


def sensitivity_view(results: pd.DataFrame) -> pd.DataFrame:
    cols = ["signal", "entity_type", "family", "threshold", "persistence_weeks", "alerts", "alert_rate", "unconfirmed_alerts",
            "unconfirmed_rate", "unconfirmed_per_week", "isolated_alerts", "median_detection_delay_weeks",
            "episode_entities_detected", "episode_entities", "episode_weeks_active_share", "episode_exposure_covered_share",
            "selectable", "role"]
    return results[cols].copy()


# ----------------------------------------------------------------------------- S03-S05 detection timing
def cluster_detection(frame: pd.DataFrame, results: pd.DataFrame, selected: pd.Series, cal: pd.DataFrame, cfg: dict,
                      secondary_column: str | None = None) -> pd.DataFrame:
    """For each method family (its best budget-compliant candidate, or its lowest-burden one), the first week each
    cluster store is flagged, the delay after its own change point, and the burden before detection."""
    ep = [e for e in cfg["monitoring"]["episodes"] if e["id"] == "EP1"][0]
    label = dict(zip(cal["t"], cal["retail_year"].astype(str) + "-W" + cal["retail_week"].astype(int).astype(str).str.zfill(2)))
    budget = cfg["monitoring"]["selection"]["warning_budget"]
    rows = []
    st = results[results["entity_type"] == "store"]
    for fam, g in st.groupby("family", sort=False):
        pers = g if fam in ALARM_FAMILIES else g[g["persistence_weeks"] >= 2]
        ok = pers[pers["unconfirmed_rate"] <= budget]
        best = (ok.sort_values(["sensitivity_order", "persistence_weeks"]).iloc[0] if len(ok)
                else pers.sort_values("unconfirmed_rate").iloc[0])
        f, _ = fires(frame, best["rule_column"], int(best["persistence_weeks"]))
        f = f & frame["baseline_ok"].fillna(False)
        for s in ep["entities"]:
            start_key = ep["start_week"][s]
            start_t = int(cal.loc[cal["retail_week_key"] == start_key, "t"].iloc[0])
            mine = frame[(frame["entity"] == s)]
            hit = mine[f.loc[mine.index] & (mine["t"] >= start_t)]
            first_t = int(hit["t"].min()) if len(hit) else None
            others_before = int((f & ~frame["in_episode"] & (frame["t"] < (first_t if first_t is not None else 10 ** 6))).sum())
            post = mine[mine["t"] >= start_t]
            rows.append({
                "method": fam, "rule": f"{best['rule_column']} (threshold {best['threshold']}, persistence {int(best['persistence_weeks'])})",
                "within_budget": bool(best["unconfirmed_rate"] <= budget), "selected_for_operations": bool(
                    (best["rule_column"] == selected["rule_column"] and int(best["persistence_weeks"]) == int(selected["persistence_weeks"]))
                    or best["rule_column"] == secondary_column),   # operational EW01 = selected threshold OR change-point
                "store": s, "change_point_week": label[start_t],
                "first_detection_week": label.get(first_t, "not detected") if first_t is not None else "not detected",
                "detection_delay_weeks": (first_t - start_t) if first_t is not None else np.nan,
                "alerts_on_this_store_before_change_point": int((f & (frame["entity"] == s) & (frame["t"] < start_t)).sum()),
                "unconfirmed_alerts_estate_before_detection": others_before,
                "active_share_after_change_point": float(f.loc[post.index].mean()) if len(post) else np.nan,
                "active_in_final_week": bool(f.loc[post.index[-1]]) if len(post) else False,
                "method_unconfirmed_rate": float(best["unconfirmed_rate"]),
                "cause_status": "Cause not established from available internal data.",
            })
    return pd.DataFrame(rows)


# ----------------------------------------------------------------------------- baseline comparison (EW01 store transactions)
def baseline_comparison(T: dict, W: dict, dq: pd.DataFrame, ew01: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """Compare baselines on the same question (is this store's transaction count abnormally low?), on the SAME
    store-weeks (the 2025 weeks where every baseline exists) and with the SAME rule (at least 15% below the baseline
    for 2 consecutive weeks); report unconfirmed-alert burden, detection and stability (review finding m2)."""
    from .baselines import rolling_mean_sd, trailing_level
    cal = W["calendar"]
    sw = T["kpi_store_week"].merge(cal[["retail_week_key", "t", "retail_year", "retail_week"]], on="retail_week_key")
    sw = sw.merge(dq[["store_id", "retail_week_key", "dq_sales_status"]], on=["store_id", "retail_week_key"])
    sw = sw.rename(columns={"store_id": "entity"})
    sw["dq_fail"] = sw["dq_sales_status"] == "FAIL"
    sw["tx"] = np.where(sw["last_extract_timestamp"] > sw["run_time"], sw["transactions_ontime"], sw["transactions"])
    sw["log_tx"] = np.log(sw["tx"].replace(0, np.nan))
    for how, n in [("mean", 8), ("median", 8), ("mean", 4)]:
        sw[f"lvl_{how}{n}"] = trailing_level(sw.assign(value=sw["log_tx"]), "value", n, how)
    e = ew01.merge(sw[["entity", "t", "log_tx", "lvl_mean8", "lvl_median8", "lvl_mean4"]], on=["entity", "t"], how="left")
    rm = rolling_mean_sd(e[["entity", "t", "value", "dq_fail"]].copy(), trailing=cfg["monitoring"]["baseline"]["trailing_weeks"],
                         min_valid=cfg["monitoring"]["baseline"]["min_valid_weeks"])
    e = e.merge(rm[["entity", "t", "roll_mean"]], on=["entity", "t"], how="left")
    devs = {
        "B1 same retail week last year (store YoY, log)": e["yoy"],
        "B2 trailing 4-week mean of the level": e["log_tx"] - e["lvl_mean4"],
        "B2 trailing 8-week mean of the level": e["log_tx"] - e["lvl_mean8"],
        "B3 trailing 8-week median of the level": e["log_tx"] - e["lvl_median8"],
        "B4 peer gap vs trailing 13-week median (robust, guarded, frozen while anomalous)": e["deviation"],
        "B5 peer gap vs trailing 13-week mean (unguarded)": e["value"] - e["roll_mean"],
    }
    interp = {
        "B1": "High; seasonality handled; an estate-wide move hits every store at once",
        "B2": "High (easy to explain) but blind to seasonality (Christmas, January)",
        "B3": "High, robust to one bad week, but blind to seasonality",
        "B4": "High once explained ('this store against the rest, against its own normal'); seasonality and estate moves removed",
        "B5": "Medium; the mean is pulled down by the anomaly itself",
    }
    common = pd.concat(list(devs.values()), axis=1).notna().all(axis=1) & e["baseline_ok"].fillna(False)
    thr = np.log(0.85)
    out = []
    for name, dev in devs.items():
        d = e.loc[common].copy()
        d["baseline_ok"] = True
        d["b_x"] = dev.loc[common] <= thr
        f, _ = fires(d, "b_x", 2)
        m = metrics(d.assign(exposure=0.0), f, f & False, cfg)
        nep = d[~d["in_episode"] & ~d["dq_fail"]]
        out.append({"baseline": name, "rule": "at least 15% below the baseline, 2 consecutive weeks",
                    "weeks_tested": m["weeks_tested"], "store_weeks_tested": m["entity_weeks_tested"],
                    "unconfirmed_rate": m["unconfirmed_rate"], "unconfirmed_alerts": m["unconfirmed_alerts"],
                    "episode_entities_detected": m["episode_entities_detected"],
                    "median_detection_delay_weeks": m["median_detection_delay_weeks"],
                    "episode_weeks_active_share": m["episode_weeks_active_share"],
                    "stability_sd_of_deviation": float(dev.loc[nep.index].std()),
                    "interpretability": interp[name[:2]]})
    return pd.DataFrame(out)
