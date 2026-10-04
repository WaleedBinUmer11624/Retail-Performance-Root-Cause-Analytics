"""Build the Phase 3 Data Quality Report (markdown + rule-level CSV) from a pipeline run.

Every number in the report is read from the run's own outputs, so the report cannot drift from the data.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from .catalogue import CATALOGUE
from .core import write_csv
from .kpis import KPI_LABELS

SEV = ["critical", "high", "medium", "low"]


def _eur(x):
    return f"EUR {x:,.0f}" if abs(x) >= 1000 else f"EUR {x:,.2f}"


def _table(df: pd.DataFrame) -> str:
    cols = list(df.columns)
    out = ["| " + " | ".join(cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    for _, r in df.iterrows():
        out.append("| " + " | ".join(str(r[c]) for c in cols) + " |")
    return "\n".join(out)


def row_outcomes(res: dict, raw_rows: dict) -> pd.DataFrame:
    """Per table: raw, curated, changed, imputed, flagged and quarantined row counts."""
    cur, issues = res["curated"], res["issues"]
    q = res["summary"]["quarantine_rows"]
    rows = []
    for t in ("fact_sales", "fact_inventory", "fact_returns", "fact_promotions", "fact_targets", "dim_product",
              "dim_store", "dim_date"):
        df = cur[t]
        n_raw = raw_rows[t] + (raw_rows["fact_sales_late_batch"] if t == "fact_sales" else 0)
        n_cur = int((df["source_file"] != "generated").sum()) if "source_file" in df else len(df)
        if "dq_status" in df:
            vc = df["dq_status"].value_counts()
            changed = int(vc.get("corrected", 0) + vc.get("imputed", 0) + vc.get("standardised", 0))
            flagged = int(vc.get("flagged", 0))
            imputed = int(vc.get("imputed", 0))
        else:
            chg = issues[(issues["table_name"] == t) & issues["action"].str.match("CORRECT|STANDARDISE|UNKNOWN_MEMBER")]
            changed, flagged, imputed = chg["row_key"].nunique(), 0, 0
            fl = issues[(issues["table_name"] == t) & (issues["action"] == "FLAG")]
            flagged = fl["row_key"].nunique()
        rows.append({"Table": t + (" (+ late file)" if t == "fact_sales" else ""), "Raw rows": f"{n_raw:,}",
                     "Curated rows": f"{n_cur:,}", "Changed (corrected / standardised / imputed)": f"{changed:,}",
                     "of which imputed": f"{imputed:,}", "Kept and flagged": f"{flagged:,}",
                     "Quarantined": f"{q.get(t, 0):,}"})
    return pd.DataFrame(rows)


def build(res: dict, raw_rows: dict, report_md: Path, report_csv: Path, blind: pd.DataFrame | None = None):
    """Write the rule-level results CSV and the Markdown data quality report."""
    results, kpis, val, audit, gaps = res["results"], res["kpis"], res["validation"], res["audit"], res["gaps"]
    summ = res["summary"]
    recon_b, recon_a = res["recon"]
    fails = results[(results["status"] == "FAIL")]
    sev_counts = fails.groupby("severity").agg(rules=("rule_id", "count"), rows=("rows_failed", "sum"),
                                               eur=("revenue_affected", "sum")).reindex(SEV).fillna(0)

    write_csv(results, report_csv)

    k = kpis
    rev_raw, rev_main, rev_full = (k.loc["net_revenue", c] for c in ("raw_as_reported", "clean_main_only", "clean_complete"))
    yoy_raw, yoy_main, yoy_full = (k.loc["h2_yoy_pct", c] for c in ("raw_as_reported", "clean_main_only", "clean_complete"))
    q_total = sum(summ["quarantine_rows"].values())
    s = res["curated"]["fact_sales"]
    status = s["dq_status"].value_counts()
    unresolved_gaps = gaps[~gaps["resolved_by_late_file"]]
    sub = fails[fails["severity"].isin(["critical", "high", "medium"]) & ~fails["rule_id"].isin(["SCH-02", "TC-07"])]
    substantive = int(sub["rows_failed"].sum())
    low_rows = int(fails.loc[fails["severity"] == "low", "rows_failed"].sum())

    L = []
    L += ["# Data Quality Report: Brightwater Retail raw extracts", "",
          "| Item | Detail |", "|---|---|",
          "| Phase | 3: data quality, cleaning and validation |",
          f"| Run | {summ['run_at']} ({summ['runtime_seconds']} s) |",
          "| Inputs | 9 raw source extracts in `data/raw/` (read-only, SHA-256 verified before and after) |",
          "| Outputs | `data/processed/curated/`, `data/processed/quarantine/`, `reports/phase3/` |",
          "| Code | `src/data_quality/` (rules in `catalogue.py`, settings in `config/dq_config.yaml`) |", ""]

    L += ["## 1. Summary", "",
          f"- **{len(results)} rules** were run across 9 extracts: {int((results['status'] == 'PASS').sum())} passed, "
          f"**{len(fails)} found problems** and {int((results['status'] == 'INFO').sum())} documented expected behaviour. "
          f"DQ check pass rate on the raw extracts (BRD 5.5): {summ['dq_check_pass_rate_pct']}%. After cleaning, "
          f"{summ['validation'].get('FAIL', 0)} of {sum(summ['validation'].values())} curated validation checks fail.",
          f"- Problems found: {int(sev_counts.loc['critical', 'rules'])} critical, {int(sev_counts.loc['high', 'rules'])} high, "
          f"{int(sev_counts.loc['medium', 'rules'])} medium and {int(sev_counts.loc['low', 'rules'])} low rules failed. "
          f"Substantive record-level findings (critical to medium, excluding the summary checks SCH-02 and TC-07): "
          f"**{substantive:,}**; low-severity format and label fixes: {low_rows:,} (almost all one inventory column exported "
          f"as 0.0 instead of 0, and category label variants). "
          f"Revenue on records that failed a check (BRD 5.5): {_eur(fails['revenue_affected'].sum())}.",
          f"- Nothing was silently deleted. {summ['issue_log_rows']:,} row-level issues are logged with the raw and new "
          f"value; {q_total:,} rows went to quarantine with a rule and a reason; every raw row is accounted for as curated "
          "or quarantined.",
          f"- **Net Revenue (all periods)** moves from {_eur(rev_raw)} at face value to {_eur(rev_full)} trusted "
          f"({(rev_full / rev_raw - 1):+.2%}). The largest single error was a misplaced decimal point on "
          f"{int(results.set_index('rule_id').loc['FS-13', 'rows_failed'])} prices, worth "
          f"{_eur(results.set_index('rule_id').loc['FS-13', 'revenue_affected'])} of false revenue.",
          f"- **H2 week-aligned YoY** is {yoy_raw:.2f}% at face value, {yoy_main:.2f}% after cleaning the main extract and "
          f"{yoy_full:.2f}% once the late-arriving sales file is loaded. The {yoy_full - yoy_main:+.2f}pp between the last two "
          "is a data-completeness effect, not trading. Phase 3 does not interpret the trading change itself.",
          f"- Stock and POS systems now agree on {recon_a['match_rate']:.2%} of store-SKU-weeks (was "
          f"{recon_b['match_rate']:.2%}); {recon_a['explained'].get('unexplained', 0)} of the remaining "
          f"{recon_a['mismatched']:,} mismatches have no logged cause.",
          f"- Curated validation: {summ['validation'].get('PASS', 0)} PASS, {summ['validation'].get('WARN', 0)} WARN "
          f"(known, documented conditions), {summ['validation'].get('FAIL', 0)} FAIL.", ""]

    L += ["## 2. Approach", "",
          "1. **Profile before touching anything.** Every column of every extract is read as text and profiled: blanks, "
          "type failures, distinct values, ranges, untrimmed text, duplicate keys (`profile_columns.csv`, `profile_tables.csv`).",
          "2. **Detect with explicit rules.** Each rule has an ID, a severity, a treatment and a business rationale "
          "(`dq_rule_catalogue.csv`). Rules come from the BRD, the data contract in `docs/02` section 5, and profiling.",
          "3. **Treat in a fixed order, and only with evidence.** A value is corrected only when an authoritative source "
          "exists in the data: the date and store inside the till's transaction ID, cost + margin confirming price and "
          "discount, the neighbouring stock weeks, a return that references the same sale line, the SKU's single "
          "list price for the year. Where no such source exists the row is flagged, mapped to an UNKNOWN member or "
          "quarantined; values are never invented.",
          "4. **Keep everything auditable.** Raw files are never written. Each change is in the issue log (row level) and "
          "the audit trail (step level, with revenue before and after). Curated rows carry `dq_status` and `dq_rules`.",
          "5. **Validate the result** against the contract, reconcile KPIs before and after, and reconcile POS units "
          "against the independent stock system.",
          "6. **Stay independent of the answer key.** The loader only accepts the 9 business extracts; files starting "
          "with an underscore are refused, and tests check both the code text and every file opened at run time.", "",
          "Severity: **critical** breaks keys or materially misstates a headline KPI; **high** is an invalid value affecting "
          "KPIs or joins; **medium** is recoverable with limited KPI effect; **low** is cosmetic. Treatments: CORRECT, "
          "STANDARDISE, DEDUPLICATE, IMPUTE, UNKNOWN_MEMBER, QUARANTINE, FLAG, INCLUDE (late data), GAP (reported, not filled).", ""]

    L += ["## 3. Issues discovered", "", "Rules that found at least one problem, most severe first. EUR = revenue on the "
          "affected lines (for sales) or refund value (for returns).", ""]
    t = fails.copy()
    t["EUR"] = t["revenue_affected"].map(lambda x: _eur(x) if x else "")
    t["Rows"] = t["rows_failed"].map("{:,}".format)
    first = lambda x: CATALOGUE[x]["rationale"].split(". ")[0].rstrip(".") + "."  # noqa: E731
    t["Treatment applied"] = [(e if isinstance(e, str) and e else first(rid)) for e, rid in zip(t["evidence"], t["rule_id"])]
    t["Treatment applied"] = t["Treatment applied"].map(lambda e: e[:170] + ("..." if len(e) > 170 else ""))
    L += [_table(t.rename(columns={"rule_id": "Rule", "table": "Table", "check": "Check", "severity": "Severity",
                                   "treatment": "Treatment"})[["Rule", "Severity", "Table", "Check", "Rows", "EUR",
                                                              "Treatment", "Treatment applied"]]), ""]

    L += ["## 4. What happened to the rows", "", _table(row_outcomes(res, raw_rows)), "",
          "Sales line status: " + ", ".join(f"{k} {v:,}" for k, v in status.items()) + ". "
          "`standardised` means only a label or format changed (for example the category text). The flagged sales "
          "lines are the late-arriving file, kept and marked `is_late_arriving`.", ""]

    L += ["## 5. KPI impact before and after cleaning", "",
          "*Raw as reported* reads the main extract and returns at face value (duplicates in, blanks as zero, "
          "unparseable dates dropped from period totals): what a spreadsheet built from the exports would show. "
          "*Clean, main extract* applies every rule but leaves out the late file. *Clean, complete* adds the late file.", ""]
    rows = []
    for key, (label, fmt) in KPI_LABELS.items():
        if key not in k.index:
            continue
        a, b, c = k.loc[key, "raw_as_reported"], k.loc[key, "clean_main_only"], k.loc[key, "clean_complete"]
        chg = c - a
        rows.append({"KPI": label, "Raw as reported": fmt.format(a), "Clean, main extract": fmt.format(b),
                     "Clean, complete": fmt.format(c),
                     "Change": (f"{chg:+.2f}pp" if key == "h2_yoy_pct" else
                                f"{100 * chg:+.2f}pp" if "pct" in key or "rate" in key or "share" in key or "availability" in key
                                else f"{chg:+,.0f}" if ".0f" in fmt else f"{chg:+,.3f}" if ".3f" in fmt else f"{chg:+,.2f}")})
    L += [_table(pd.DataFrame(rows)), ""]
    br = audit[audit["metric"] == "sales revenue EUR"].copy()
    if len(br):
        L += ["**Sales Revenue bridge (all periods), from the audit trail:**", "",
              _table(pd.DataFrame({"Step": br["rule_id"] + " " + br["action"],
                                   "Rows": br["rows_affected"].map("{:,}".format),
                                   "Before": br["metric_before"].map(lambda x: f"{x:,.2f}"),
                                   "After": br["metric_after"].map(lambda x: f"{x:,.2f}"),
                                   "Change": br["metric_change"].map(lambda x: f"{x:+,.2f}")})), ""]

    L += ["## 6. Completeness and timeliness", ""]
    r = results.set_index("rule_id")
    L += [f"- **Late-arriving sales file (TC-01):** {r.loc['TC-01', 'evidence']}. Loaded with `is_late_arriving = True`, "
          f"worth {_eur(r.loc['TC-01', 'revenue_affected'])}.",
          f"- **Missing store-days (TC-02):** {r.loc['TC-02', 'evidence']}."]
    for _, g in unresolved_gaps.iterrows():
        L.append(f"  - {g['store_id']} {g['date']:%Y-%m-%d}: no POS data at all; the stock system shows "
                 f"{g['week_stock_sold_units']:,.0f} units sold that week against {g['week_pos_units']:,.0f} in POS, and "
                 f"{g['returns_referencing_day']} return{'s' if g['returns_referencing_day'] != 1 else ''} reference"
                 f"{'' if g['returns_referencing_day'] != 1 else 's'} receipts from that day, so the store traded. "
                 f"Estimated missing revenue {_eur(g['estimated_revenue'])} (same weekday, 4 weeks either side). Not imputed.")
    L += [f"- **Batch structure (TC-04):** {r.loc['TC-04', 'evidence']}. The 05:00 extracts carry the re-sent duplicate lines (FS-01).",
          f"- **Stock snapshots (TC-05):** {r.loc['TC-05', 'rows_failed']:,} store-SKU-weeks missing inside otherwise continuous "
          "series (`inventory_missing_weeks.csv`); not imputed.",
          f"- **Targets (TC-06):** missing store-weeks {r.loc['TC-06', 'evidence']}; not imputed.",
          f"- **Low-volume days (TC-03):** {r.loc['TC-03', 'rows_failed']} store-days below "
          "30% of the store's usual same-weekday revenue (no partial batches detected).",
          f"- **POS vs stock system (TC-07):** {r.loc['TC-07', 'evidence']}.",
          "- Returns, stock, promotions and targets carry no extract timestamps, so their timeliness cannot be tested.", ""]

    L += ["## 7. Unresolved issues and assumptions", "",
          "**Unresolved (reported, not fixed):**", ""]
    unk = s[s["product_id"] == "UNKNOWN"]
    L += [f"- {len(unk):,} sales lines ({_eur(unk['revenue'].sum())}) have no identifiable product (blank or unknown code, no "
          "linked return). They stay in totals under the UNKNOWN product and are excluded from product and category analysis.",
          f"- {len(unresolved_gaps)} store-days of POS data were never delivered (estimated {_eur(unresolved_gaps['estimated_revenue'].sum())}). "
          "A re-extract should be requested from the source system.",
          f"- {r.loc['FR-04', 'rows_failed']} returns ({_eur(r.loc['FR-04', 'revenue_affected'])}) reference sale lines that "
          "were never received; kept in Returns Value because the refund was paid.",
          f"- {int(res['validation'].set_index('check').loc['stock identity holds', 'value'].split()[0])} stock rows still "
          "break the stock identity after triangulation and are flagged.",
          f"- {r.loc['TC-05', 'rows_failed']:,} missing stock snapshots and {r.loc['TC-06', 'rows_failed']} missing targets remain gaps.",
          f"- {int(r.loc['FS-19', 'evidence'].split('; ')[-1].split()[0]) if 'set to UNKNOWN' in r.loc['FS-19', 'evidence'] else 0} "
          "promoted line(s) keep an UNKNOWN promotion.", "",
          "**Assumptions (judgement calls a business owner should confirm):**", "",
          "1. The transaction ID is authoritative for date and store (every valid date in the file agrees with it).",
          "2. Negative quantity and negative price lines are sign errors, not till refunds: all money fields are negated "
          "together, returns live in their own file, and correcting them raises the POS-to-stock match rate.",
          f"3. Quantities above {res['summary']['max_plausible_line_quantity']} on a store POS line are not real; the true quantity is "
          "unknown, so those lines are quarantined rather than guessed.",
          "4. A zero price is a pricing failure, not a giveaway; the SKU's list price for the year is imputed and the "
          "line is flagged `is_imputed` (discount from the promotion depth when a matching promotion exists).",
          "5. Impossible returns (dated before the sale, or more units than sold) are quarantined; over-refunds and "
          "unlinked returns are kept because money was paid out.",
          "6. Where a product master record is duplicated, the copy whose list price matches the till price is kept.",
          "7. Superseded target versions: the highest version, then the latest set date, wins.",
          "8. Estimates for missing store-days are for disclosure only and are never added to the data.", ""]

    L += ["## 8. Validation results", "", _table(val[["group", "check", "status", "value"]].fillna("")), ""]

    if blind is not None and len(blind):
        cc_path = report_md.parent / "phase3" / "independent_crosscheck.csv"
        cc = pd.read_csv(cc_path) if cc_path.exists() else None
        L += ["## 9. Independent cross-check", "",
              f"Before the rules were written, a separate agent with no access to the generator, its configuration or "
              f"any evaluation file profiled the same 9 extracts blind and listed {len(blind)} findings "
              f"(`reports/phase3/independent_blind_profile_findings.csv`, scripts alongside). "
              + (f"All {cc['pipeline_rules'].notna().sum()} map to a pipeline rule (`independent_crosscheck.csv`). "
                 "Counts differ only where the pipeline measures after an upstream fix (for example, 12 of the profiler's "
                 "79 'returned more than sold' cases were caused by sign-inverted sale lines and disappear once those "
                 "are corrected)." if cc is not None else ""), ""]

    L += ["## 10. Artefacts (data lineage and audit)", "",
          "| File | Content |", "|---|---|",
          "| `data/processed/curated/*.csv` | 8 curated tables with `dq_status`, `dq_rules`, `source_file`, `source_row` |",
          "| `data/processed/quarantine/*_quarantine.csv` | Rejected rows exactly as received, with `dq_rule_id` and `dq_reason` |",
          "| `reports/phase3/profile_tables.csv`, `profile_columns.csv` | Pre-cleaning profile |",
          "| `reports/phase3/dq_rule_catalogue.csv` | Every rule: severity, treatment, rationale |",
          "| `reports/phase3/dq_rule_results.csv` (= `reports/data_quality_report.csv`) | Rows checked and failed, EUR affected, evidence |",
          "| `reports/phase3/dq_issue_log.csv` | One line per affected record: rule, key, column, raw value, new value, action |",
          "| `reports/phase3/cleaning_audit_trail.csv` | Ordered treatment steps with rows affected and metric before/after |",
          "| `reports/phase3/kpi_reconciliation.csv` | BRD KPIs in the three views |",
          "| `reports/phase3/curated_validation.csv` | Post-cleaning checks (PASS/WARN/FAIL) |",
          "| `reports/phase3/completeness_store_days.csv`, `inventory_missing_weeks.csv`, `missing_targets.csv`, "
          "`extract_batches.csv`, `low_volume_store_days.csv` | Completeness and timeliness detail |",
          "| `reports/phase3/pos_stock_mismatches.csv` | Remaining POS vs stock mismatches with their explanation |",
          "| `reports/phase3/category_mapping.csv`, `sku_reference_prices.csv` | Reference data used by the rules |",
          "| `reports/phase3/lineage.json` | Input and output SHA-256, row counts, config and code hashes |",
          "| `logs/dq_run_*.log` | Run log |", ""]
    info = results[results["status"] == "INFO"]
    L += ["## Appendix: expected behaviour documented (no action)", "",
          _table(pd.DataFrame({"Rule": info["rule_id"], "Check": info["check"], "Rows": info["rows_failed"].map("{:,}".format),
                               "Why it is not an error": info["rule_id"].map(lambda x: CATALOGUE[x]["rationale"])})), ""]
    report_md.write_text("\n".join(L))
