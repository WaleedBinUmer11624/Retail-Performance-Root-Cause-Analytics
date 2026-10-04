"""The Power BI semantic model's tables, read from the pbi views, and their CSV extracts.

Two routes feed Power BI Desktop:
  * SQL Server (recommended): Power Query reads the pbi.* views directly (powerbi/power_query/*.pq).
  * CSV (no SQL Server): `python -m src.powerbi.run_phase7 --extract` writes the same tables to data/powerbi/
    from the locally rebuilt DuckDB model. Same views, same rows.
The Python reference measures (reference.py) evaluate against exactly these tables.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from .access import query

# Power BI table name -> (pbi view, key columns used to sort the extract deterministically)
TABLES = {
    "Date": ("pbi.dim_date", ["date_key"]),
    "Store": ("pbi.dim_store", ["store_key"]),
    "Product": ("pbi.dim_product", ["product_key"]),
    "Promotion": ("pbi.dim_promotion", ["promotion_key"]),
    "Sales": ("pbi.fact_sales", ["sales_line_id"]),
    "Returns": ("pbi.fact_returns", ["return_id"]),
    "Inventory": ("pbi.fact_inventory", ["retail_week_key", "store_key", "product_key"]),
    "Targets": ("pbi.fact_targets", ["retail_week_key", "store_key"]),
}

# Relationships of the semantic model: (from table, from column) -> (to table, to column), many-to-one,
# single direction (dimension filters fact). `active=False` marks the one inactive relationship.
RELATIONSHIPS = [
    {"from": ("Sales", "date_key"), "to": ("Date", "date_key"), "active": True},
    {"from": ("Sales", "store_key"), "to": ("Store", "store_key"), "active": True},
    {"from": ("Sales", "product_key"), "to": ("Product", "product_key"), "active": True},
    {"from": ("Sales", "promotion_key"), "to": ("Promotion", "promotion_key"), "active": True},
    {"from": ("Returns", "return_date_key"), "to": ("Date", "date_key"), "active": True},
    {"from": ("Returns", "original_sale_date_key"), "to": ("Date", "date_key"), "active": False},
    {"from": ("Returns", "store_key"), "to": ("Store", "store_key"), "active": True},
    {"from": ("Returns", "product_key"), "to": ("Product", "product_key"), "active": True},
    {"from": ("Inventory", "snapshot_date_key"), "to": ("Date", "date_key"), "active": True},
    {"from": ("Inventory", "store_key"), "to": ("Store", "store_key"), "active": True},
    {"from": ("Inventory", "product_key"), "to": ("Product", "product_key"), "active": True},
    {"from": ("Targets", "store_key"), "to": ("Store", "store_key"), "active": True},
]


def load_tables(engine) -> dict[str, pd.DataFrame]:
    out = {}
    for name, (view, keys) in TABLES.items():
        df = query(engine, f"SELECT * FROM {view}")
        out[name] = df.sort_values(keys, kind="mergesort").reset_index(drop=True)
    for t in ("Date",):
        out[t]["calendar_date"] = pd.to_datetime(out[t]["calendar_date"])
    return out


def write_extracts(tables: dict[str, pd.DataFrame], out_dir: Path) -> pd.DataFrame:
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for name, df in tables.items():
        path = out_dir / f"{name.lower()}.csv"
        df.to_csv(path, index=False, lineterminator="\n", date_format="%Y-%m-%d")
        rows.append({"table": name, "file": path.name, "rows": len(df), "columns": len(df.columns)})
    return pd.DataFrame(rows)


def schema(tables: dict[str, pd.DataFrame]) -> dict[str, list[str]]:
    return {k: list(v.columns) for k, v in tables.items()}
