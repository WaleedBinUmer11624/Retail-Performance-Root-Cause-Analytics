"""Data dictionary of the Power BI semantic model (star schema + Phase 6 tables) and a model profile
(rows, cardinality) used for the performance review."""
from __future__ import annotations

import pandas as pd

TABLE_DESC = {
    "Date": "Calendar, one row per day (plus key -1 'unknown'). Retail weeks Monday-Sunday; H1 = weeks 1-26, H2 = 27-52.",
    "Store": "One row per store (plus -1 'unknown'); store_group comes from Phase 6 (investigated cluster, matched control, other).",
    "Product": "One row per SKU (plus -1 'unknown'), with category, subcategory, brand and supplier.",
    "Promotion": "One row per promotion event; key 0 = not promoted, -1 = unknown promotion.",
    "Sales": "Fact: one row per receipt line, on the sale date at the selling store.",
    "Returns": "Fact: one row per return line, on the return date at the returning store (BRD assumption 2).",
    "Inventory": "Fact (periodic snapshot): store x SKU x retail week, Sunday closing stock. Semi-additive.",
    "Targets": "Fact (plan): Finance weekly Net Revenue target per store. Not related to Date; mapped by week in DAX.",
}

COL_DESC = {
    "date_key": "Surrogate date key yyyymmdd (-1 unknown)", "calendar_date": "Calendar date",
    "day_of_week": "1 = Monday ... 7 = Sunday", "day_name": "Weekday name", "is_weekend": "1 on Saturday and Sunday",
    "calendar_month": "Month number", "month_name": "Month name (sort by calendar_month)", "year_month": "yyyymm",
    "calendar_year": "Calendar year", "retail_year": "Retail year", "retail_week": "Retail week 1-52",
    "retail_week_key": "Retail week key yyyyww", "retail_week_label": "e.g. 2025-W27",
    "retail_week_start": "Monday of the retail week", "retail_half": "H1 (weeks 1-26) or H2 (weeks 27-52)",
    "period_label": "e.g. 'H2 2025' (slicer label)", "is_bank_holiday": "1 on Irish bank holidays",
    "is_trading_day": "1 when stores trade", "same_day_last_year_key": "Date key 364 days earlier (same weekday); drives PY measures",
    "is_unknown": "1 for the unknown member (-1)", "store_key": "Surrogate store key", "store_id": "Store code, e.g. S03",
    "store_name": "Store name", "store_label": "store_id + name", "town": "Town", "county": "County", "region": "Region",
    "store_format": "Flagship / Standard / Express", "floor_area_m2": "Sales floor area", "open_date": "Opening date",
    "weekly_trading_hours": "Trading hours per week", "store_group": "Phase 6 group: Investigated cluster / Matched control / Other store / Unknown",
    "product_key": "Surrogate product key", "product_id": "SKU code, e.g. P00149", "product_name": "Product name",
    "product_label": "product_id + name", "category": "Category", "subcategory": "Subcategory", "brand": "Brand",
    "supplier_id": "Supplier code", "supplier_name": "Supplier name", "list_price": "Current list price (EUR, excl. VAT)",
    "product_status": "Active / Discontinued", "promotion_key": "Surrogate promotion key (0 = none)",
    "promotion_id": "Promotion code", "promotion_name": "Promotion name", "promotion_type": "Promotion mechanic",
    "promotion_category": "Category of the covered products", "start_date": "Promotion start", "end_date": "Promotion end",
    "duration_days": "Length in days", "min_discount_pct": "Lowest discount", "max_discount_pct": "Highest discount",
    "member_type": "Promotion / No promotion / Unknown", "sales_line_id": "Receipt-line id",
    "transaction_key": "Integer surrogate of the receipt id (DISTINCTCOUNT = Transactions)", "quantity": "Units sold",
    "gross_amount": "Quantity x unit price (EUR)", "discount_amount": "Discount (EUR)",
    "sales_revenue": "Gross amount minus discount (EUR)", "cost_amount": "Quantity x standard cost (EUR)",
    "is_promoted": "1 if sold on promotion", "return_id": "Return-line id", "return_date_key": "Return date key (active relationship)",
    "original_sale_date_key": "Original sale date key (inactive relationship, cohort analysis)",
    "return_quantity": "Units returned", "refund_value": "Refund (EUR)", "restock_cost_credit": "Cost credited for restocked units (EUR)",
    "return_reason": "Till reason code (e.g. 'Faulty'); NOT a verified defect", "is_restockable": "1 if returned to stock",
    "is_linked_to_sale": "1 if the original sale line is in the data", "sale_promotion_status": "Whether the returned item was sold on promotion",
    "snapshot_date_key": "Sunday snapshot date key", "opening_stock": "Units at the start of the week",
    "received_qty": "Units received in the week", "closing_stock": "Units at the Sunday snapshot",
    "is_in_stock": "1 if closing stock > 0 (availability numerator)",
    "is_full_week_stockout": "1 if no opening stock, nothing received and out of stock (full-week stock-out)",
    "target_net_revenue": "Finance weekly Net Revenue target (EUR)",
}


def data_dictionary(tables: dict, extracts: dict, manifest: pd.DataFrame) -> pd.DataFrame:
    rows = []
    src = manifest.set_index("extract")["source_file"].to_dict()
    for t, df in tables.items():
        cols = list(df.columns) + (["store_group"] if t == "Store" else [])
        for c in cols:
            dt = "text" if c == "store_group" else str(df[c].dtype)
            rows.append({"table": t, "table_type": "dimension" if t in ("Date", "Store", "Product", "Promotion") else "fact",
                         "table_description": TABLE_DESC[t], "column": c, "dtype": dt,
                         "description": COL_DESC.get(c, ""), "source": f"pbi.{'dim' if t in ('Date', 'Store', 'Product', 'Promotion') else 'fact'}_"
                         f"{t.lower()}" + (" + p6_store_groups" if c == "store_group" else "")})
    for t, df in extracts.items():
        if t.startswith("_"):
            continue
        for c in df.columns:
            rows.append({"table": t, "table_type": "Phase 6 analytical (disconnected)",
                         "table_description": f"Validated Phase 5/6 output, imported unchanged; not affected by slicers.",
                         "column": c, "dtype": str(df[c].dtype), "description": COL_DESC.get(c, ""),
                         "source": src.get(f"{t}.csv", "")})
    return pd.DataFrame(rows)


def model_profile(tables: dict) -> pd.DataFrame:
    rows = []
    for t, df in tables.items():
        for c in df.columns:
            rows.append({"table": t, "rows": len(df), "column": c, "distinct_values": int(df[c].nunique(dropna=True)),
                         "dtype": str(df[c].dtype)})
    out = pd.DataFrame(rows)
    out["cardinality_ratio"] = out["distinct_values"] / out["rows"]
    return out
