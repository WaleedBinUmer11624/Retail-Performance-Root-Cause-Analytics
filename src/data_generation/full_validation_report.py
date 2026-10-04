"""Build the Phase 2 full-dataset validation report (evaluation-only asset).

Runs against the persisted files in data/raw:
  * row counts and file sizes, compared with the approved calibration projection
  * the full validation suite (validate_generated.run_all)
  * BRD KPIs from the clean view
  * headline recalculated from the files and reconciled to the answer key
  * reproducibility: regenerate into a scratch folder and compare file hashes

Usage:  python -m src.data_generation.full_validation_report [--skip-reproducibility]
Output: reports/phase2_full_validation_report.json and .md
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import shutil
import tempfile
import time
from pathlib import Path

from .config_loader import PROJECT_ROOT
from .reconcile_headline import reconcile
from .validate_generated import run_all

RAW = PROJECT_ROOT / "data" / "raw"
REPORTS = PROJECT_ROOT / "reports"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def reproducibility_check() -> dict:
    """Regenerate the full dataset into a temp folder and compare each file's hash with data/raw."""
    from .generate_data import run
    tmp = Path(tempfile.mkdtemp(prefix="bw_repro_"))
    try:
        t0 = time.time()
        logging.disable(logging.INFO)
        run("full", out_dir=tmp)
        logging.disable(logging.NOTSET)
        files = {f.name: _sha(f) == _sha(tmp / f.name) for f in sorted(RAW.glob("*.csv"))}
        return {"regeneration_seconds": round(time.time() - t0, 1), "files_identical": files,
                "all_identical": all(files.values())}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def build(check_repro: bool = True) -> dict:
    """Assemble the full-run validation report from the manifest, calibration and validation results."""
    manifest = json.loads((RAW / "_generation_manifest.json").read_text())
    calib = json.loads((REPORTS / "phase2_calibration_report.json").read_text())
    proj = calib["projected_full_row_counts"]

    t0 = time.time()
    res, kpis = run_all(RAW)
    res.to_csv(REPORTS / "phase2_full_validation.csv", index=False)
    validation_seconds = round(time.time() - t0, 1)
    rec = reconcile(RAW)

    files = {}
    for f in sorted(RAW.glob("*.csv")):
        n = manifest["row_counts"][f.name]
        files[f.name] = {"rows": n, "projected_rows": proj.get(f.name), "bytes": f.stat().st_size,
                         "matches_projection": n == proj.get(f.name)}
    groups = res.groupby("group")["status"].agg(passed=lambda s: int((s == "PASS").sum()),
                                                failed=lambda s: int((s == "FAIL").sum()))
    report = {
        "dataset": "data/raw (full, 20 stores)",
        "seed": manifest["seed"], "config_hash": manifest["config_hash"], "generated_at": manifest["generated_at"],
        "generation_runtime_seconds": manifest["runtime_seconds"],
        "files": files,
        "total_bytes": sum(v["bytes"] for v in files.values()),
        "validation": {"passed": int((res["status"] == "PASS").sum()), "failed": int((res["status"] == "FAIL").sum()),
                       "runtime_seconds": validation_seconds, "by_group": groups.to_dict(orient="index"),
                       "failures": res[res["status"] == "FAIL"].to_dict(orient="records")},
        "kpis_clean_view_all_periods": {k: round(v, 4) for k, v in kpis.items()},
        "headline": {
            "h2_2024_reported": rec["answer_key"]["reported_2024"], "h2_2024_underlying": rec["answer_key"]["underlying_2024"],
            "h2_2025_reported": rec["answer_key"]["reported_2025"], "h2_2025_underlying": rec["answer_key"]["underlying_2025"],
            "yoy_reported_pct": calib["yoy_pct_reported"], "yoy_underlying_pct": calib["yoy_pct_underlying"],
            "dq_artefact_eur": calib["dq_artefact_eur"], "dq_artefact_pp": calib["dq_artefact_pp"],
            "matches_approved_calibration": rec["restored_yoy_pct"] == {"reported": calib["yoy_pct_reported"],
                                                                        "underlying": calib["yoy_pct_underlying"]},
        },
        "reconciliation_from_files": rec,
        "reproducibility": reproducibility_check() if check_repro else "skipped",
    }
    (REPORTS / "phase2_full_validation_report.json").write_text(json.dumps(report, indent=2, default=str))
    (REPORTS / "phase2_full_validation_report.md").write_text(_markdown(report))
    return report


def _markdown(r: dict) -> str:
    h, rec, v = r["headline"], r["reconciliation_from_files"], r["validation"]
    rep = r["reproducibility"]
    L = [
        "# Phase 2: Full Dataset Validation Report", "",
        "> Evaluation-only asset: contains answer-key figures. Phase 3+ code must not read it.", "",
        f"Seed `{r['seed']}`, config hash `{r['config_hash']}`, generated {r['generated_at']}, "
        f"generation runtime {r['generation_runtime_seconds']} s.", "",
        "## Files", "", "| File | Rows | Projected | Match | Size (MB) |", "|---|---|---|---|---|",
    ]
    for name, f in r["files"].items():
        L.append(f"| {name} | {f['rows']:,} | {f['projected_rows']:,} | {'yes' if f['matches_projection'] else 'NO'} "
                 f"| {f['bytes'] / 1e6:.2f} |")
    L += [f"| **Total** | | | | **{r['total_bytes'] / 1e6:.1f}** |", "",
          "## Validation", "", f"**{v['passed']} passed, {v['failed']} failed** ({v['runtime_seconds']} s).", "",
          "| Group | Passed | Failed |", "|---|---|---|"]
    L += [f"| {g} | {c['passed']} | {c['failed']} |" for g, c in v["by_group"].items()]
    L += ["", "## Headline (H2, week-aligned, net revenue)", "", "| Measure | Reported | Underlying |", "|---|---|---|",
          f"| H2 2024 | EUR {h['h2_2024_reported']:,.2f} | EUR {h['h2_2024_underlying']:,.2f} |",
          f"| H2 2025 | EUR {h['h2_2025_reported']:,.2f} | EUR {h['h2_2025_underlying']:,.2f} |",
          f"| YoY | {h['yoy_reported_pct']}% | {h['yoy_underlying_pct']}% |", "",
          f"DQ artefact: EUR {h['dq_artefact_eur']:,.2f} ({h['dq_artefact_pp']}pp). "
          f"Matches approved calibration: **{'yes' if h['matches_approved_calibration'] else 'NO'}**.", "",
          "## Reconciliation from the persisted files", "",
          "| Measure | Restored from files | Answer key | Difference |", "|---|---|---|---|"]
    for k in ("reported_2024", "reported_2025", "underlying_2024", "underlying_2025"):
        L.append(f"| {k} | EUR {rec['restored_from_files'][k]:,.2f} | EUR {rec['answer_key'][k]:,.2f} "
                 f"| EUR {rec['difference_eur'][k]:,.2f} |")
    L += ["", f"Restored YoY: reported {rec['restored_yoy_pct']['reported']}%, underlying "
          f"{rec['restored_yoy_pct']['underlying']}%. The small positive difference comes from "
          f"{rec['rows_with_unrecoverable_discount']} planted rows whose original discount was overwritten "
          "(restored at gross value). The missing batch (EUR "
          f"{rec['missing_batch_h2_2024_from_key_only']:,.2f}) was never delivered, so it is known only from the key.", "",
          f"Naive face-value result (raw files, no DQ handling): H2 2024 EUR {rec['naive_face_value']['h2_2024']:,.2f}, "
          f"H2 2025 EUR {rec['naive_face_value']['h2_2025']:,.2f}, YoY {rec['naive_face_value']['yoy_pct']}%.", "",
          "## Reproducibility", ""]
    if isinstance(rep, dict):
        L.append(f"Full regeneration ({rep['regeneration_seconds']} s): "
                 f"**{'all files byte-identical' if rep['all_identical'] else 'DIFFERENCES FOUND'}**.")
    else:
        L.append("Skipped.")
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-reproducibility", action="store_true")
    out = build(not ap.parse_args().skip_reproducibility)
    print(json.dumps({k: out[k] for k in ("validation", "headline", "reproducibility")}, indent=2, default=str)[:3000])
