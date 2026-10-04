"""Phase 10 runner: leakage-aware weekly estate forecasting.

    python -m src.forecasting.run_phase10 --build-input   # read-only SQL Server extraction
    python -m src.forecasting.run_phase10 --dry-run       # configuration, paths and freeze gates only
    python -m src.forecasting.run_phase10                  # full back-test, selection and forecast

The database is only ever read. `--build-input` issues one SELECT against the governed warehouse
and writes a contract-shaped CSV; nothing else in this phase touches SQL Server.

Exits 1 if any validation check in the Phase 10 catalogue fails.
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import yaml

from .backtest import rolling_origins, run_pointwise_backtest, run_rolling_backtest
from .checks import build_catalogue, catalogue_summary
from .config import load_config
from .forecast import build_forecast, build_intervals, calibration_errors
from .models import model_registry
from .selection import METRICS, select_model, summarise
from .validation import load_and_validate_weekly_input, preflight


def _write(path: Path, columns: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def build_input(root: Path, config: dict) -> tuple[int, Path]:
    """Read the governed warehouse once and write the weekly estate input. No database writes."""
    from .source import (build_provenance, fetch_weekly_history, open_read_only_engine, write_provenance,
                         write_weekly_input)

    project = yaml.safe_load((root / "config/project_config.yaml").read_text(encoding="utf-8"))
    source = dict(config["source"])
    engine = open_read_only_engine(project)
    try:
        rows = fetch_weekly_history(engine, source["retail_years"])
    finally:
        engine.close()
    weekly_path = root / config["forecast"]["weekly_input"]
    write_weekly_input(rows, weekly_path)
    write_provenance(build_provenance(rows, {**source, "database": project["database"]["database"]}, engine.name),
                     root / config["forecast"]["outputs"]["provenance"])
    return len(rows), weekly_path


def run(root: Path, config: dict) -> int:
    """Back-test, select, forecast, write every output and the catalogue; return 0 if all checks pass."""
    forecast = config["forecast"]
    outputs = forecast["outputs"]
    models = model_registry(
        season=forecast["seasonal_period_weeks"],
        moving_window=forecast["moving_average_window_weeks"],
        trend_window=forecast["trend_window_weeks"],
    )
    registry_order = [model.name for model in models]

    rows, headline = load_and_validate_weekly_input(root, config)
    print(
        "HEADLINE RECONCILED: "
        f"H2 2024={headline['h2_2024']}; H2 2025={headline['h2_2025']}; "
        f"change={headline['change']}; YoY={headline['yoy_pct']}%"
    )

    history = [float(row["net_revenue"]) for row in rows]
    origins = rolling_origins(
        len(history),
        forecast["minimum_training_weeks"],
        forecast["primary_horizon_weeks"],
        forecast["rolling_origin_step_weeks"],
    )
    if not origins:
        raise ValueError("Insufficient history for the configured rolling-origin back-test")
    print(f"BACKTEST: {len(history)} weeks, {len(origins)} rolling origins, {len(models)} models")

    backtest = run_rolling_backtest(history, origins, models, season=forecast["seasonal_period_weeks"])
    pointwise = run_pointwise_backtest(history, origins, models)

    summaries = summarise(backtest, registry_order)
    decision = select_model(summaries, registry_order, config["selection"], expected_origins=len(origins))
    by_name = {model.name: model for model in models}
    selected = by_name[decision["selected_model"]]

    last = rows[-1]
    forecast_rows = build_forecast(
        history,
        last["week_start_date"],
        int(last["retail_week"]),
        forecast["primary_horizon_weeks"],
        selected,
    )
    errors = calibration_errors(pointwise, decision["selected_model"])
    bands = build_intervals(forecast_rows, errors, forecast["interval_coverages"])

    # Files frozen by earlier phases; the weekly input must not be one of them.
    governed: set[str] = set()
    for manifest in forecast["freeze_manifests"]:
        with (root / manifest).open("r", encoding="utf-8-sig", newline="") as stream:
            governed |= {row["file"] for row in csv.DictReader(stream)}
    catalogue = build_catalogue(
        {
            "forecast": forecast,
            "weekly_rows": rows,
            "weekly_input": forecast["weekly_input"],
            "governed_files": governed,
            "evaluation_refs": [path for path in [forecast["weekly_input"], *forecast["freeze_manifests"]]
                                if "evaluation" in path or "_hidden" in path or "_answer_key" in path],
            "freeze_manifest_rows": [row["file"] for manifest in forecast["freeze_manifests"]
                                     for row in csv.DictReader((root / manifest).open(encoding="utf-8-sig"))],
            "origins": origins,
            "models": models,
            "backtest": backtest,
            "model_summaries": summaries,
            "selection": decision,
            "history": history,
            "forecast_rows": forecast_rows,
            "bands": bands,
            "calibration_errors": errors,
        }
    )

    _write(root / outputs["backtest"],
           ["model", "forecast_grain", "forecast_origin_index", "horizon_weeks", *METRICS], backtest)
    _write(root / outputs["model_comparison"],
           ["model", "family", "origins", "mean_mae", "mean_rmse", "mean_wape", "mean_mase", "mean_bias"],
           [{"model": item.model, "family": item.family, "origins": item.origins,
             **{f"mean_{metric}": item.metric(metric) for metric in METRICS}} for item in summaries])
    _write(root / outputs["selected_model"], ["field", "value"],
           [{"field": key, "value": value} for key, value in decision.items()])
    _write(root / outputs["forecast"],
           ["horizon_step", "retail_year", "retail_week", "week_start_date", "model", "point_forecast"],
           [{"horizon_step": step,
             "retail_year": int(row.week_start_date.isocalendar()[0]),
             "retail_week": row.retail_week,
             "week_start_date": row.week_start_date.isoformat(),
             "model": decision["selected_model"],
             "point_forecast": row.point_forecast}
            for step, row in enumerate(forecast_rows, start=1)])
    _write(root / outputs["intervals"], ["week_start_date", "model", "coverage", "lower", "upper"],
           [{"week_start_date": band["week_start_date"].isoformat(), "model": decision["selected_model"],
             "coverage": band["coverage"], "lower": band["lower"], "upper": band["upper"]} for band in bands])
    _write(root / outputs["validation_checks"],
           ["group", "check", "value", "reference", "status", "detail"], catalogue)

    summary = catalogue_summary(catalogue)
    print(f"SELECTED MODEL: {decision['selected_model']} ({decision['selected_family']}) on "
          f"mean {decision['selection_metric']}; best baseline {decision['best_baseline']}; "
          f"challenger promoted: {decision['promoted_challenger']}")
    print(f"FORECAST: {len(forecast_rows)} weeks to {forecast_rows[-1].week_start_date}, "
          f"{len(bands)} interval bands")
    print(f"VALIDATION: {summary['passed']}/{summary['total']} checks PASS")
    for row in catalogue:
        if row["status"] != "PASS":
            print(f"  FAIL {row['group']}: {row['check']} (value={row['value']}, reference={row['reference']})",
                  file=sys.stderr)
    return 0 if summary["all_passed"] else 1


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Exit codes: 0 success, 1 a catalogue check failed, 2 a data gate failed."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="Validate configuration, paths and freeze gates only")
    parser.add_argument("--build-input", action="store_true", help="Re-extract the weekly input from SQL Server")
    parser.add_argument("--config", type=Path, default=Path("config/forecasting_config.yaml"))
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    root = args.project_root.resolve()
    try:
        config = load_config(root / args.config)
        forecast = config["forecast"]
        models = model_registry(
            season=forecast["seasonal_period_weeks"],
            moving_window=forecast["moving_average_window_weeks"],
            trend_window=forecast["trend_window_weeks"],
        )
        # Check output paths before any work, so a bad config cannot write outside the project.
        for name, path in forecast["outputs"].items():
            if root not in (root / path).resolve().parents:
                raise ValueError(f"Configured output {name} must remain inside the project root")

        if args.build_input:
            count, path = build_input(root, config)
            print(f"Extracted {count} estate retail weeks read-only from SQL Server -> {path}")
            return 0

        missing, issues = preflight(root, config)
        if args.dry_run:
            print(f"DRY RUN OK: configuration, {len(models)} registered models and output path validated")
            print(f"DATA GATE: {'BLOCKED' if missing or issues else 'READY'}")
            for item in missing + issues:
                print(f"- {item}")
            return 0
        if missing or issues:
            print("PHASE 10 DATA GATE FAILED", file=sys.stderr)
            for item in missing + issues:
                print(f"- {item}", file=sys.stderr)
            return 2
        return run(root, config)
    except (OSError, ValueError, KeyError) as error:
        print(f"PHASE 10 DATA GATE FAILED: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
