"""Severity, DQ gating, alert table, alert summary and the alert lifecycle.

Severity is rule-based and fully traceable (no scoring):
  WATCH     the selected threshold is breached this week, but the persistence rule has not fired yet;
            or any breach in a week whose data failed the DQ gate (held, not escalated)
  WARNING   the selected persistent rule fired; or a single-week breach more extreme than every earlier observation
            of the signal (a record, with at least 200 earlier entity-weeks); for EW01 also the online
            change-point test (the Phase 8 EW01 threshold concept) confirming a sustained step
  CRITICAL  a WARNING whose threshold is also breached this week, and that has lasted 4+ consecutive weeks; or 3+ entities of the same signal at WARNING in the
            same week (systemic) with this entity at WARNING for 2+ weeks; or episode exposure to date of at least one normal week of the entity's net
            revenue; or, for EW01, the threshold is breached AND the change-point test confirms a step (two methods agree)
  DQ gate   a failed gate caps severity at WATCH and marks the alert DQ_HOLD
Evidence level is always "Observed change (monitoring alert)"; cause status is always "Not established".
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

from .backtest import fires

LEVEL = {"NORMAL": 0, "WATCH": 1, "WARNING": 2, "CRITICAL": 3}
NAME = {v: k for k, v in LEVEL.items()}
ADVERSE = {"EW01": -1, "EW02": -1, "EW03": -1, "EW06": -1, "EW07": 1}
LIFECYCLE = [
    ("NEW", "Created by the weekly run", "ACKNOWLEDGED, FALSE POSITIVE"),
    ("ACKNOWLEDGED", "An owner has read it and accepted responsibility", "INVESTIGATING, MONITORING, FALSE POSITIVE"),
    ("INVESTIGATING", "Data or evidence is being gathered (Phase 8 data requests)", "ACTIONED, MONITORING, RESOLVED, FALSE POSITIVE"),
    ("ACTIONED", "A decision was taken and logged in the Phase 8 decision log", "MONITORING, RESOLVED"),
    ("MONITORING", "Watching whether the deviation persists or recovers", "INVESTIGATING, RESOLVED"),
    ("RESOLVED", "Deviation ended or explained; the baseline may be reset to the new level", ""),
    ("FALSE POSITIVE", "Investigated and found not to be a real change (reason required)", ""),
]
ALERT_COLUMNS = [
    "alert_id", "alert_date", "retail_week_key", "retail_week", "signal", "signal_name", "entity_type", "entity_id",
    "metric", "actual_value", "baseline_value", "variance", "variance_pct", "z_score", "rule", "severity",
    "severity_reason", "persistence_weeks", "alert_episode_id", "estimated_exposure", "episode_exposure_to_date",
    "exposure_basis", "dq_status", "dq_hold", "dq_note", "evidence_level", "cause_status", "alert_class", "message",
    "proposed_owner", "data_required", "validation_label", "status", "owner", "created_at", "acknowledged_at",
    "resolved_at", "resolution_reason", "notes",
]
EXPOSURE_BASIS = {
    "EW01": "Revenue equivalent of the transaction shortfall at this week's basket value (monitoring ESTIMATE)",
    "EW02": "Revenue equivalent of the transaction shortfall at this week's basket value (monitoring ESTIMATE)",
    "EW03": "Availability gap vs last year x ranged cells x recent sales per in-stock cell (monitoring ESTIMATE)",
    "EW04": "Stores out x the SKU's recent sales per in-stock store-week (monitoring ESTIMATE)",
    "EW05": "Excess 'Faulty' units x average refund, this week's share of the 4-week window (refund cost, ESTIMATE)",
    "EW06": "Margin-rate gap x this week's net revenue (monitoring ESTIMATE)",
    "EW07": "Extra discount vs last year's depth on this week's gross sales (a cost, not a loss estimate)",
    "EW08": "n/a",
}


def _slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "", str(s))[:12].upper()


def record_low(frame: pd.DataFrame, sign: int, min_history: int = 200) -> pd.Series:
    """True where the deviation is more adverse than every earlier evaluated entity-week of the signal (past only)."""
    d = frame.sort_values("t")
    adv = sign * d["deviation"]
    out = pd.Series(False, index=d.index)
    best, n = -np.inf, 0
    for t in sorted(d["t"].unique()):
        idx = d.index[d["t"] == t]
        vals = adv.loc[idx]
        if n >= min_history:
            out.loc[idx] = vals > best
        ok = vals.dropna()
        if len(ok):
            best = max(best, ok.max())
            n += len(ok)
    return out.reindex(frame.index).fillna(False)


def score(frame: pd.DataFrame, sel: pd.Series, cfg: dict) -> pd.DataFrame:
    """Severity per entity-week for one signal x entity type under its selected rule."""
    sv = cfg["monitoring"]["severity"]
    d = frame.sort_values(["entity", "t"]).copy()
    col, k = sel["rule_column"], int(sel["persistence_weeks"])
    ok = d["baseline_ok"].fillna(False).astype(bool)
    d["breach"] = d[col].fillna(False).astype(bool) & ok
    d["fire"], _ = fires(d, col, k)
    sig = d["signal"].iloc[0]
    if sig in ADVERSE:
        d["record"] = record_low(d, ADVERSE[sig], sv.get("record_min_history", 200)) & d["breach"] & ~d["dq_fail"]
    else:
        d["record"] = False
    cc = sel.get("confirm_column") if hasattr(sel, "get") else None
    d["cp_confirm"] = d[cc].fillna(False).astype(bool) if isinstance(cc, str) and cc in d.columns else False
    level = np.where(d["breach"], 1, 0)
    level = np.where(d["fire"] | d["record"], 2, level)
    d["level"] = level
    # EW01: Phase 8 specified the change-point test as the EW01 threshold concept, so it raises a WARNING on its own
    # (it is an alarm-type rule that already requires a sustained step); DQ-failed weeks are excluded.
    if isinstance(cc, str):
        cpw = d["cp_confirm"] & ~d["dq_fail"].astype(bool) & d["baseline_ok"].fillna(False).astype(bool)
        d["level"] = np.where(cpw & (d["level"] < 2), 2, d["level"])
        d["cp_warn"] = cpw
    else:
        d["cp_warn"] = False
    # persistence of WARNING state, breadth, exposure
    warn = pd.Series(d["level"] >= 2, index=d.index)
    from .baselines import consecutive
    d["warn_run"] = consecutive(warn, d["entity"], d["t"])
    d["breadth"] = d.groupby("t")["level"].transform(lambda s: (s >= 2).sum())
    alerting = pd.Series(d["level"] >= 1, index=d.index)
    d["alert_run"] = consecutive(alerting, d["entity"], d["t"])
    ep_start = d["t"] - d["alert_run"] + 1
    d["episode_key"] = np.where(alerting, d["entity"].astype(str) + "|" + ep_start.astype(int).astype(str), "")
    d["exp_w"] = np.where(alerting, d["exposure"].fillna(0).clip(lower=0), 0.0)
    d["episode_exposure_to_date"] = d.groupby("episode_key")["exp_w"].cumsum().where(alerting, 0.0)
    rev = d["entity_weekly_revenue"]
    crit_p = d["warn_run"] >= sv["critical_persistence_weeks"]
    crit_b = (d["breadth"] >= sv["critical_breadth_entities"]) & (d["warn_run"] >= 2)
    crit_e = rev.notna() & (rev > 0) & (d["episode_exposure_to_date"] >= sv["critical_exposure_weeks_of_revenue"] * rev)
    # two independent EW01 methods agree this week: threshold breached AND change-point step confirmed
    crit_cp = (d["cp_warn"] & d["breach"]) if isinstance(cc, str) else False
    # CRITICAL also needs a current breach of the selected threshold: a week kept at WARNING only by the change-point
    # rule (no shortfall beyond the threshold this week) stays WARNING (review follow-up N3)
    critical = (d["level"] >= 2) & d["breach"] & (crit_p | crit_b | crit_e | crit_cp)
    d["level"] = np.where(critical, 3, d["level"])
    # DQ gate: cap at WATCH
    held = d["dq_fail"].astype(bool) & (d[col].fillna(False).astype(bool) | (d["level"] >= 1))
    if sig == "EW08":
        held = pd.Series(False, index=d.index)
    d["dq_hold"] = held
    d["level"] = np.where(held, 1, d["level"])
    d["severity"] = [NAME[int(x)] for x in d["level"]]

    def reason(r):
        if r["level"] == 0:
            return ""
        if r["dq_hold"]:
            return "DQ gate failed: breach held at WATCH until the data is complete"
        parts = []
        if r["level"] >= 3:
            why = []
            if r["warn_run"] >= sv["critical_persistence_weeks"]:
                why.append(f"WARNING for {int(r['warn_run'])} consecutive weeks")
            if r["breadth"] >= sv["critical_breadth_entities"] and r["warn_run"] >= 2:
                why.append(f"{int(r['breadth'])} entities at WARNING this week (systemic) and this one for 2+ weeks")
            if pd.notna(r["entity_weekly_revenue"]) and r["entity_weekly_revenue"] > 0 and \
                    r["episode_exposure_to_date"] >= sv["critical_exposure_weeks_of_revenue"] * r["entity_weekly_revenue"]:
                why.append("episode exposure >= one normal week of revenue")
            if isinstance(cc, str) and bool(r["cp_warn"]) and bool(r["breach"]):
                why.append("threshold breached and the change-point test confirms a sustained step (two methods agree)")
            parts.append("CRITICAL: " + "; ".join(why))
        elif r["level"] == 2:
            if r["fire"]:
                parts.append(f"WARNING: rule breached {k}+ consecutive weeks")
            elif r["record"]:
                parts.append("WARNING: most extreme deviation of this signal so far (record)")
            else:
                parts.append("WARNING: change-point test confirms a sustained step in the peer gap")
        else:
            parts.append("WATCH: threshold breached, persistence not yet met")
        return " ".join(parts)
    d["severity_reason"] = d.apply(reason, axis=1)
    d["persistence_weeks"] = consecutive(d["breach"] & ~d["dq_fail"].astype(bool), d["entity"], d["t"])
    d["rule"] = f"{sel['family']}: {sel['threshold']}, {k} week(s)" + (
        f" OR online change-point test ({sel.get('confirm_threshold')})" if isinstance(cc, str) else "")
    return d


def _week_label(y, w):
    return f"{int(y)}-W{int(w):02d}"


def alert_table(scored: dict, cfg: dict, calendar: pd.DataFrame) -> pd.DataFrame:
    rows = []
    cal = calendar[["retail_week_key", "retail_year", "retail_week", "run_time"]].drop_duplicates("retail_week_key")
    for (sig, et), d in scored.items():
        s = cfg["monitoring"]["signals"][sig]
        a = d[d["level"] >= 1].copy()
        if a.empty:
            continue
        a = a.drop(columns=[c for c in ["retail_year", "retail_week", "run_time"] if c in a.columns])
        a = a.merge(cal, on="retail_week_key", how="left")
        for c, default in [("dq_status", ""), ("dq_note", ""), ("in_episode", False), ("metric", s.get("metric", "")),
                           ("exposure", 0.0)]:
            if c not in a.columns:
                a[c] = default
        a["alert_id"] = [f"{sig}-{et[:3].upper()}-{_slug(e)}-{int(w)}" for e, w in zip(a["entity"], a["retail_week_key"])]
        ep_ids = {k: f"{sig}-{et[:3].upper()}-{_slug(k.split('|')[0])}-E{int(k.split('|')[1]):03d}" for k in a["episode_key"].unique()}
        out = pd.DataFrame({
            "alert_id": a["alert_id"],
            "alert_date": pd.to_datetime(a["run_time"]).dt.date.astype(str) if "run_time" in a.columns else "",
            "retail_week_key": a["retail_week_key"].astype(int),
            "retail_week": [_week_label(y, w) for y, w in zip(a["retail_year"], a["retail_week"])],
            "signal": sig, "signal_name": s["name"], "entity_type": et, "entity_id": a["entity"],
            "metric": a["metric"], "actual_value": a["actual_value"], "baseline_value": a["baseline_value"],
            "variance": a["variance"], "variance_pct": a["variance_pct"],
            "z_score": a["z"] if "z" in a.columns else np.nan,
            "rule": a["rule"], "severity": a["severity"], "severity_reason": a["severity_reason"],
            "persistence_weeks": a["persistence_weeks"].astype(int), "alert_episode_id": a["episode_key"].map(ep_ids),
            "estimated_exposure": a["exposure"].fillna(0).clip(lower=0).round(2),
            "episode_exposure_to_date": a["episode_exposure_to_date"].round(2),
            "exposure_basis": EXPOSURE_BASIS[sig],
            "dq_status": a["dq_status"], "dq_hold": a["dq_hold"], "dq_note": a["dq_note"].fillna(""),
            "evidence_level": s["evidence_level"], "cause_status": "Not established",
            "alert_class": s["alert_class"] if sig != "EW08" else s["alert_class"],
            "message": np.where(a["dq_hold"], "Held (DQ gate): " + s["wording"] + " " + a["dq_note"].fillna("").astype(str), s["wording"]),
            "proposed_owner": s["owner"] + " (PROPOSED)", "data_required": s["data_required"],
            "validation_label": np.where(a["dq_hold"], "DQ-held", np.where(a["in_episode"], "known episode", "unconfirmed")),
            "status": "NEW", "owner": "", "created_at": pd.to_datetime(a["run_time"]).astype(str) if "run_time" in a.columns else "",
            "acknowledged_at": "", "resolved_at": "", "resolution_reason": "",
            "notes": "Back-test replay: generated by the weekly run as it would have run at created_at; no management response is recorded.",
        })
        rows.append(out)
    df = pd.concat(rows, ignore_index=True)[ALERT_COLUMNS]
    return df.sort_values(["retail_week_key", "signal", "entity_type", "entity_id"]).reset_index(drop=True)


def alert_summary(alerts: pd.DataFrame, selected: pd.DataFrame, scored: dict) -> pd.DataFrame:
    rows = []
    for r in selected.itertuples():
        a = alerts[(alerts["signal"] == r.signal) & (alerts["entity_type"] == r.entity_type)]
        d = scored[(r.signal, r.entity_type)]
        rows.append({
            "signal": r.signal, "entity_type": r.entity_type, "rule": f"{r.family}: {r.threshold}, {int(r.persistence_weeks)} week(s)",
            "within_budget": r.within_budget, "entity_weeks_evaluated": int(d["baseline_ok"].fillna(False).sum()),
            "watch": int((a["severity"] == "WATCH").sum()), "warning": int((a["severity"] == "WARNING").sum()),
            "critical": int((a["severity"] == "CRITICAL").sum()), "dq_held": int(a["dq_hold"].sum()),
            "alert_episodes": int(a["alert_episode_id"].nunique()), "entities_alerted": int(a["entity_id"].nunique()),
            "warning_plus_known_episode": int(((a["severity"].isin(["WARNING", "CRITICAL"])) & (a["validation_label"] == "known episode")).sum()),
            "warning_plus_unconfirmed": int(((a["severity"].isin(["WARNING", "CRITICAL"])) & (a["validation_label"] == "unconfirmed")).sum()),
            "exposure_warning_plus_eur": float(a.loc[a["severity"].isin(["WARNING", "CRITICAL"]), "estimated_exposure"].sum()),
            "exposure_note": "Signal-specific proxy; never add across signals (they overlap).",
        })
    return pd.DataFrame(rows)


def lifecycle_table() -> pd.DataFrame:
    return pd.DataFrame(LIFECYCLE, columns=["status", "meaning", "allowed_next_status"])


def valid_transition(old: str, new: str) -> bool:
    allowed = {s: [x.strip() for x in n.split(",") if x.strip()] for s, _, n in LIFECYCLE}
    return new in allowed.get(old, [])
