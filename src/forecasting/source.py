"""Read-only extraction of the contract-shaped weekly estate forecasting input.

The authoritative source is the governed SQL Server warehouse: `mart.v_performance_store_week`
already carries store x retail-week net revenue on the same definition the Phase 4 and Phase 6
reconciliations use (sales revenue less returns value, returns attributed to their return week).
Summing that view over stores gives one estate row per retail week.

Nothing here writes to the database. The module issues a single SELECT and formats the result.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from .contracts import WEEKLY_REQUIRED, OPTIONAL_NUMERIC

ESTATE_SOURCE_QUERY = """
SELECT w.retail_year,
       w.retail_week,
       w.retail_week_key,
       CONVERT(varchar(10), w.week_start_date, 23) AS week_start_date,
       CONVERT(varchar(32), CAST(ROUND(SUM(p.net_revenue), 2) AS DECIMAL(38, 2)))  AS net_revenue,
       CONVERT(varchar(32), CAST(ROUND(SUM(p.transactions), 0) AS DECIMAL(38, 0))) AS transactions,
       CONVERT(varchar(32), CAST(ROUND(SUM(p.units_sold), 0) AS DECIMAL(38, 0)))   AS units,
       CONVERT(varchar(32), CAST(ROUND(SUM(p.returns_value), 2) AS DECIMAL(38, 2))) AS [returns],
       CONVERT(varchar(32), CAST(ROUND(SUM(p.gross_margin), 2) AS DECIMAL(38, 2)))  AS gross_margin
FROM mart.v_performance_store_week AS p
JOIN dw.dim_retail_week AS w ON w.retail_week_key = p.retail_week_key
WHERE w.retail_year IN ({years})
GROUP BY w.retail_year, w.retail_week, w.retail_week_key, w.week_start_date
ORDER BY w.week_start_date
"""

# The forecast input is written in this order. The first four columns are the contract keys and
# target; the rest are optional numeric context the models may use but never assume into the future.
OUTPUT_COLUMNS = ["retail_year", "retail_week", "week_start_date", "net_revenue", "transactions",
                  "units", "returns", "gross_margin"]

PROVENANCE_COLUMNS = ["record", "value"]


@dataclass(frozen=True)
class Provenance:
    """What the weekly input is and where it came from, recorded next to the data itself."""

    records: dict[str, str]

    def as_rows(self) -> list[dict[str, str]]:
        """Record/value rows sorted by record name, for a stable CSV."""
        return [{"record": key, "value": self.records[key]} for key in sorted(self.records)]


def _week_query(retail_years: list[int]) -> str:
    return ESTATE_SOURCE_QUERY.format(years=", ".join(str(int(year)) for year in sorted(retail_years)))


def open_read_only_engine(project_config: dict):
    """SQL Server engine opened on the governed database. Callers must never issue DDL or DML."""
    from src.analytics.model_access import PROJECT_ROOT
    from src.sql_model.engines import SqlServerEngine

    database = dict(project_config["database"])
    if not database.get("trusted_connection", False):
        raise ValueError("Phase 10 requires Windows authentication; no credentials may be stored in config")
    if not str(database.get("database", "")).lower().startswith("brightwater"):
        raise ValueError(f"Refusing to read from an unexpected database: {database.get('database')}")
    engine = SqlServerEngine(database)
    return engine


def fetch_weekly_history(engine, retail_years: list[int]) -> list[dict[str, str]]:
    """Estate x retail-week rows ordered by week_start_date. Read-only SELECT against the warehouse."""
    frame = engine.query(_week_query(retail_years))
    rows = []
    for record in frame.to_dict("records"):
        row = {column: str(record[column]) for column in OUTPUT_COLUMNS}
        for column in WEEKLY_REQUIRED:
            if not str(row[column]).strip():
                raise ValueError(f"SQL Server returned an empty contract column: {column}")
        # Optional context columns default to 0 when the warehouse has no value; the target never does.
        for column in OPTIONAL_NUMERIC.intersection(row):
            if row[column].strip() in ("", "None"):
                row[column] = "0"
        rows.append(row)
    rows.sort(key=lambda item: item["week_start_date"])
    return rows


def h2_totals(rows: list[dict[str, str]]) -> dict[int, Decimal]:
    """Cent-exact H2 totals straight from the weekly rows, the way the contract reconciles them."""
    totals: dict[int, Decimal] = {}
    for row in rows:
        year, week = int(row["retail_year"]), int(row["retail_week"])
        if 27 <= week <= 52:
            totals[year] = totals.get(year, Decimal("0")) + Decimal(row["net_revenue"])
    return totals


def build_provenance(rows: list[dict[str, str]], source: dict, engine_name: str) -> Provenance:
    """A self-describing record of the extraction, stored beside the data it produced."""
    totals = h2_totals(rows)
    first, last = rows[0], rows[-1]
    return Provenance(
        {
            "authoritative_source": f"{source['governed_view']} (read-only SELECT)",
            "build_engine": engine_name,
            "database": source.get("database", "BrightwaterRetail"),
            "grain": "estate x retail_week",
            "target": "net_revenue",
            "row_count": str(len(rows)),
            "first_week": f"{first['retail_year']}-W{int(first['retail_week']):02d} ({first['week_start_date']})",
            "last_week": f"{last['retail_year']}-W{int(last['retail_week']):02d} ({last['week_start_date']})",
            "retail_years": ", ".join(str(year) for year in sorted({int(row["retail_year"]) for row in rows})),
            "h2_2024_net_revenue": str(totals.get(2024, Decimal("0"))),
            "h2_2025_net_revenue": str(totals.get(2025, Decimal("0"))),
            "rounding": "net revenue aggregated in DECIMAL(38,2) per retail week before export",
            "excluded": "retail weeks outside the configured retail_years, including the partial "
                        "trailing week beyond the last closed retail year",
            "database_writes": "none; the extraction issues a single SELECT",
        }
    )


def write_weekly_input(rows: list[dict[str, str]], path: Path) -> None:
    """UTF-8, LF, no BOM, deterministic ordering by week_start_date."""
    import csv

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=OUTPUT_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_provenance(provenance: Provenance, path: Path) -> None:
    """Write the provenance record/value CSV beside the weekly input."""
    import csv

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=PROVENANCE_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(provenance.as_rows())
