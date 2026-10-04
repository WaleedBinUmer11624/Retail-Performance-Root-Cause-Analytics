"""Data contract for the weekly forecasting input.

Inputs: weekly CSV rows at estate, store or category grain. Outputs: rows with typed keys and
Decimal measures, and the H2 headline totals, which must equal the approved values exactly.
"""
import csv
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path


class DataContractError(ValueError):
    """Weekly input that breaks the contract and must not be forecast."""
    pass


WEEKLY_REQUIRED = {
    "retail_year",
    "retail_week",
    "week_start_date",
    "net_revenue",
}
OPTIONAL_NUMERIC = {
    "transactions",
    "units",
    "gross_margin",
    "returns",
    "availability",
    "promotion_share",
    "discount_rate",
}
ENTITY_COLUMNS = {"store": "store_id", "category": "category"}


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    """Read a CSV into string rows; a file without a header is a contract error."""
    # utf-8-sig strips the BOM Excel adds, which would otherwise corrupt the first column name.
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames is None:
            raise DataContractError(f"CSV has no header: {path}")
        return list(reader)


def _decimal(value: object, column: str, row_number: int) -> Decimal:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise DataContractError(
            f"Row {row_number}: {column} must be numeric"
        ) from error
    if not number.is_finite():
        raise DataContractError(f"Row {row_number}: {column} must be finite")
    return number


def _week_key(year: int, week: int) -> tuple[int, int]:
    return year, week


def validate_weekly_rows(
    rows: list[dict],
    grain: str = "estate",
    require_contiguous: bool = True,
    min_rows: int = 1,
) -> list[dict]:
    """Type and check weekly rows: Monday week starts, no duplicates, sorted and, if required, contiguous."""
    if grain not in {"estate", "store", "category"}:
        raise DataContractError(f"Unsupported grain: {grain}")
    if len(rows) < min_rows:
        raise DataContractError(
            f"Expected at least {min_rows} rows at {grain} grain; found {len(rows)}"
        )
    if not rows:
        raise DataContractError("Weekly input is empty")

    required = set(WEEKLY_REQUIRED)
    entity_column = ENTITY_COLUMNS.get(grain)
    if entity_column:
        required.add(entity_column)
    missing_columns = required - set(rows[0])
    if missing_columns:
        raise DataContractError(
            "Missing required columns: " + ", ".join(sorted(missing_columns))
        )

    normalized = []
    seen = set()
    previous_order = None
    series_state = {}
    # Row numbers start at 2 so messages match the spreadsheet line under the header.
    for row_number, row in enumerate(rows, start=2):
        try:
            year = int(row["retail_year"])
            week = int(row["retail_week"])
            week_start = date.fromisoformat(str(row["week_start_date"]))
        except (TypeError, ValueError) as error:
            raise DataContractError(
                f"Row {row_number}: invalid retail year, week or week_start_date"
            ) from error
        if year < 1900 or week < 1 or week > 53:
            raise DataContractError(f"Row {row_number}: invalid retail week {year}-W{week}")
        if week_start.weekday() != 0:
            raise DataContractError(f"Row {row_number}: week_start_date must be Monday")
        key = _week_key(year, week)
        entity = row.get(entity_column, "") if entity_column else "ESTATE"
        identity = (entity, *key)
        if identity in seen:
            raise DataContractError(f"Duplicate week/entity key: {identity}")
        seen.add(identity)
        current_order = (week_start, str(entity))
        if previous_order is not None and current_order < previous_order:
            raise DataContractError("Rows must be sorted by week_start_date and entity")
        if entity in series_state:
            previous_date, previous_key = series_state[entity]
            if week_start <= previous_date:
                raise DataContractError(f"Rows for {entity} must be in ascending date order")
            if require_contiguous and (week_start - previous_date).days != 7:
                raise DataContractError(
                    f"Missing or irregular retail week between {previous_date} and {week_start}"
                )
            if require_contiguous:
                expected = (previous_key[0], previous_key[1] + 1)
                # Week 1 rolls the retail year over, whether the prior year had 52 or 53 weeks.
                if week == 1:
                    expected = (previous_key[0] + 1, 1)
                if key != expected:
                    raise DataContractError(
                        f"Missing or misordered retail period before {year}-W{week}"
                    )

        normalized_row = dict(row)
        normalized_row["retail_year"] = year
        normalized_row["retail_week"] = week
        normalized_row["week_start_date"] = week_start
        normalized_row["net_revenue"] = _decimal(row["net_revenue"], "net_revenue", row_number)
        for column in OPTIONAL_NUMERIC.intersection(row):
            if row[column] not in (None, ""):
                normalized_row[column] = _decimal(row[column], column, row_number)
        normalized.append(normalized_row)
        series_state[entity] = (week_start, key)
        previous_order = current_order
    return normalized


# Governed H2 (retail weeks 27 to 52) net revenue. The input must reproduce these to the cent.
APPROVED_HEADLINE = {
    2024: Decimal("10188727.55"),
    2025: Decimal("9457457.05"),
}


def reconcile_h2_headline(rows: list[dict]) -> dict[str, Decimal]:
    """Return H2 totals, change and YoY %; raise if they differ from the approved headline."""
    totals = {}
    for year in (2024, 2025):
        totals[year] = sum(
            (
                row["net_revenue"]
                for row in rows
                if row["retail_year"] == year and 27 <= row["retail_week"] <= 52
            ),
            Decimal("0"),
        )
    if totals != APPROVED_HEADLINE:
        raise DataContractError(
            "H2 headline mismatch: "
            f"2024={totals[2024]}, 2025={totals[2025]}; "
            "approved values must not be adjusted to fit the model"
        )
    change = totals[2025] - totals[2024]
    yoy = (change / totals[2024] * Decimal("100")).quantize(Decimal("0.000001"))
    return {"h2_2024": totals[2024], "h2_2025": totals[2025], "change": change, "yoy_pct": yoy}
