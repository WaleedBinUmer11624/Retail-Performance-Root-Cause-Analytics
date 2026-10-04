"""Evaluation tables built on the scored alerts: S03-S05 operational detection, the false/unconfirmed alert burden with
corroboration, and the explainable change-point estimates (the advanced method).

Wording rules: an alert outside the known episodes is an "unconfirmed alert" (unexplained, not proven false); an alert
episode lasting one week is an "isolated alert"; an alert with no related alert on another signal within two weeks is
an "alert without corroborating evidence". Nothing is called a confirmed false positive: no ground truth exists
outside the known episodes, and in a live system only an analyst closing the alert as FALSE POSITIVE would say so.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

CAUSE = "Cause not established from available internal data."
WARN_PLUS = ["WARNING", "CRITICAL"]


def _label(cal: pd.DataFrame) -> dict:
    return dict(zip(cal["t"], cal["retail_year"].astype(int).astype(str) + "-W" + cal["retail_week"].astype(int).astype(str).str.zfill(2)))


def operational_detection(scored: pd.DataFrame, alerts: pd.DataFrame, cal: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """S03-S05 under the operational EW01 rule (selected rule + severity + change-point continuation)."""
    ep = [e for e in cfg["monitoring"]["episodes"] if e["id"] == "EP1"][0]
    lab = _label(cal)
    key_t = dict(zip(cal["retail_week_key"], cal["t"]))
    rows = []
    a1 = alerts[alerts["signal"] == "EW01"]
    for s in ep["entities"]:
        start_t = key_t[ep["start_week"][s]]
        mine = scored[scored["entity"] == s].sort_values("t")
        post = mine[mine["t"] >= start_t]
        warn = post[post["level"] >= 2]
        watch = post[post["level"] >= 1]
        crit = post[post["level"] >= 3]
        first_t = int(warn["t"].min()) if len(warn) else None
        before = a1[(a1["severity"].isin(WARN_PLUS)) & (a1["validation_label"] == "unconfirmed")]
        before = before[before["retail_week_key"].map(key_t) < (first_t if first_t is not None else 10 ** 6)]
        rows.append({
            "method": "operational EW01 (selected rule, severity, change-point continuation)",
            "rule": str(mine["rule"].iloc[0]), "store": s, "change_point_week": lab[start_t],
            "first_watch_week": lab[int(watch["t"].min())] if len(watch) else "none",
            "first_detection_week": lab[first_t] if first_t is not None else "not detected",
            "detection_delay_weeks": (first_t - start_t) if first_t is not None else np.nan,
            "severity_at_first_detection": mine.loc[mine["t"] == first_t, "severity"].iloc[0] if first_t is not None else "",
            "first_critical_week": lab[int(crit["t"].min())] if len(crit) else "none",
            "max_severity": post["severity"].map({"NORMAL": 0, "WATCH": 1, "WARNING": 2, "CRITICAL": 3}).max(),
            "warning_plus_alerts_on_this_store_before_change_point": int(((mine["t"] < start_t) & (mine["level"] >= 2)).sum()),
            "unconfirmed_warning_plus_alerts_estate_before_detection": int(len(before)),
            "active_share_after_change_point": float((post["level"] >= 2).mean()) if len(post) else np.nan,
            "active_in_final_week": bool(post["level"].iloc[-1] >= 2) if len(post) else False,
            "cause_status": CAUSE,
        })
    df = pd.DataFrame(rows)
    df["max_severity"] = df["max_severity"].map({0: "NORMAL", 1: "WATCH", 2: "WARNING", 3: "CRITICAL"})
    return df


def related_entities(tables: dict) -> dict:
    """Maps used for corroboration: store -> region, format; product -> category, supplier; supplier -> categories."""
    sw = tables["kpi_store_week"][["store_id", "region", "store_format"]].drop_duplicates()
    pw = tables["kpi_product_week"][["product_id", "category", "supplier_name"]].drop_duplicates()
    return {
        "store_region": dict(zip(sw["store_id"], sw["region"])),
        "store_format": dict(zip(sw["store_id"], sw["store_format"])),
        "product_category": dict(zip(pw["product_id"], pw["category"])),
        "product_supplier": dict(zip(pw["product_id"], pw["supplier_name"])),
        "supplier_categories": pw.groupby("supplier_name")["category"].agg(lambda s: sorted(set(s))).to_dict(),
    }


def _keys(r, maps) -> set:
    """The entities an alert 'touches' (itself plus the groups it belongs to or contains)."""
    e, et = r["entity_id"], r["entity_type"]
    k = {(et, e)}
    if et == "store":
        k |= {("region", maps["store_region"].get(e)), ("format", maps["store_format"].get(e))}
    elif et == "product":
        k |= {("category", maps["product_category"].get(e)), ("supplier", maps["product_supplier"].get(e))}
    elif et == "supplier":
        k |= {("category", c) for c in maps["supplier_categories"].get(e, [])}
    return k


def false_positive_analysis(alerts: pd.DataFrame, cal: pd.DataFrame, maps: dict, window: int = 2) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Per unconfirmed WARNING+ alert: isolated or not, and whether a DIFFERENT signal raised a WARNING+ alert on the
    same entity or a directly linked one (store <-> its region and format; SKU <-> its supplier and category;
    supplier <-> its categories) within +/- `window` weeks. Returns (detail, summary by signal and entity type)."""
    key_t = dict(zip(cal["retail_week_key"], cal["t"]))
    a = alerts[~alerts["dq_hold"]].copy()
    a["t"] = a["retail_week_key"].map(key_t)
    a["keys"] = [_keys(r, maps) for _, r in a.iterrows()]
    # alert episode length (in weeks, WATCH included) for the isolated test
    ep_len = a.groupby("alert_episode_id")["t"].agg(lambda s: s.max() - s.min() + 1)
    ep_max = a.groupby("alert_episode_id")["severity"].agg(lambda s: s.isin(WARN_PLUS).any())
    strong = a[a["severity"].isin(WARN_PLUS)]
    u = strong[strong["validation_label"] == "unconfirmed"].copy()
    rows = []
    for _, r in u.iterrows():
        near = strong[(strong["signal"] != r["signal"]) & ((strong["t"] - r["t"]).abs() <= window)]
        me = (r["entity_type"], r["entity_id"])
        linked = [(me in k) or ((et2, e2) in r["keys"]) for k, et2, e2 in zip(near["keys"], near["entity_type"], near["entity_id"])]
        hits = near[pd.Series(linked, index=near.index, dtype=bool)]
        rows.append({
            "alert_id": r["alert_id"], "retail_week": r["retail_week"], "signal": r["signal"], "entity_type": r["entity_type"],
            "entity_id": r["entity_id"], "severity": r["severity"],
            "alert_episode_weeks": int(ep_len.get(r["alert_episode_id"], 1)),
            "isolated_alert": bool(ep_len.get(r["alert_episode_id"], 1) == 1),
            "corroborating_alerts": ", ".join(sorted(set(hits["signal"] + " " + hits["entity_id"].astype(str))))[:300],
            "alert_without_corroborating_evidence": hits.empty,
            "classification": "unconfirmed alert",
            "interpretation": ("Unexplained by the known episodes; not proven false. An analyst would check it; only a "
                               "closed investigation could mark it FALSE POSITIVE."),
        })
    det = pd.DataFrame(rows)
    summ = []
    weeks = max(int(a["t"].nunique()), 1)
    for (sig, et), g0 in a.groupby(["signal", "entity_type"]):
        g = g0[g0["severity"].isin(WARN_PLUS)]
        d = det[(det["signal"] == sig) & (det["entity_type"] == et)] if len(det) else det
        w = g0[g0["severity"] == "WATCH"]
        eps = g0.groupby("alert_episode_id").agg(unconf=("validation_label", lambda s: (s == "unconfirmed").all()))
        watch_only = eps.index[~eps.index.map(ep_max).astype(bool)]
        iso_watch = [e for e in watch_only if ep_len.get(e, 1) == 1 and eps.loc[e, "unconf"]]
        summ.append({"signal": sig, "entity_type": et,
                     "watch_alerts": len(w), "watch_unconfirmed": int((w["validation_label"] == "unconfirmed").sum()),
                     "watch_only_episodes": len(watch_only), "isolated_unconfirmed_watch_episodes": len(iso_watch),
                     "warning_plus_alerts": len(g),
                     "known_episode": int((g["validation_label"] == "known episode").sum()),
                     "unconfirmed_alerts": len(d),
                     "isolated_alerts": int(d["isolated_alert"].sum()) if len(d) else 0,
                     "alerts_without_corroborating_evidence": int(d["alert_without_corroborating_evidence"].sum()) if len(d) else 0,
                     "unconfirmed_share": len(d) / len(g) if len(g) else 0.0,
                     "unconfirmed_warning_plus_per_week": len(d) / weeks})
    return det, pd.DataFrame(summ)


def changepoint_estimates(ew01: pd.DataFrame, cal: pd.DataFrame, delta: int = 6) -> pd.DataFrame:
    """The online change-point detector (advanced, explainable): for every store it flags, the first week it fired, the
    week it estimates the step began (using data up to the firing week only) and the size of the step."""
    lab = _label(cal)
    col = f"b_cp{delta}"
    rows = []
    for s, g in ew01.sort_values("t").groupby("entity"):
        hit = g[g[col].fillna(False).astype(bool)]
        if hit.empty:
            continue
        h = hit.iloc[0]
        rows.append({
            "store": s, "first_fired_week": lab[int(h["t"])],
            "estimated_step_week": lab.get(int(h["cp_tau_t"]), "") if pd.notna(h.get("cp_tau_t")) else "",
            "step_in_peer_gap_log": float(h["cp_step"]) if pd.notna(h.get("cp_step")) else np.nan,
            "step_in_peer_gap_pct": float(np.expm1(h["cp_step"])) if pd.notna(h.get("cp_step")) else np.nan,
            "test_statistic": float(h["cp_stat"]) if pd.notna(h.get("cp_stat")) else np.nan,
            "weeks_flagged": int(g[col].fillna(False).sum()),
            "in_known_episode": bool(h["in_episode"]),
            "reading": ("Sustained step down in the store's transactions against the rest of the estate. " + CAUSE)
            if (pd.notna(h.get("cp_step")) and h["cp_step"] < 0) else "Sustained step up (not an adverse alert).",
        })
    return pd.DataFrame(rows)
