"""Unit tests for Phase 3 data-quality rules on small hand-built frames."""
import pandas as pd
import pytest

from src.data_quality import dimensions, promotions_targets, returns_inventory, sales
from src.data_quality.catalogue import CATALOGUE
from src.data_quality.core import DQContext, ForbiddenInputError, is_blank, load_config, load_raw, parse_type


@pytest.fixture()
def ctx():
    """Fresh DQContext with the real config and rule catalogue."""
    return DQContext(cfg=load_config(), catalogue=CATALOGUE)


# ------------------------------------------------------------------ helpers
SALES_COLS = ["transaction_id", "line_number", "transaction_date", "transaction_time", "store_id", "product_id",
              "category", "quantity", "unit_price", "discount", "revenue", "unit_cost", "cost", "margin",
              "promotion_id", "extract_batch_id", "extract_timestamp"]


def line(tid, ln, date, store="S01", prod="P00001", cat="Home & Kitchen", q=1, p=10.0, d=0.0, rev=None, uc=6.0,
         cost=None, margin=None, promo="", ts="2025-03-04 02:10:00", batch="B20250304"):
    """One raw sales line as text; revenue, cost and margin are consistent unless overridden."""
    rev = round(q * p - d, 2) if rev is None else rev
    cost = round(q * uc, 2) if cost is None else cost
    margin = round(rev - cost, 2) if margin is None else margin
    vals = [tid, ln, date, "10:00", store, prod, cat, q, p, d, rev, uc, cost, margin, promo, batch, ts]
    return {k: ("" if v is None else str(v)) for k, v in zip(SALES_COLS, vals)}


def frame(rows, name):
    """Rows as a raw extract frame, with source_file and source_row like load_raw adds."""
    df = pd.DataFrame(rows)
    df.insert(0, "source_row", range(2, len(df) + 2))
    df.insert(0, "source_file", name)
    return df


def base_lines(n=12):
    """n clean single-line transactions on 2025-03-03."""
    return [line(f"S01-20250303-{i:05d}", 1, "2025-03-03") for i in range(1, n + 1)]


def dim_product():
    """Two real products plus the Unknown member."""
    return pd.DataFrame({"product_id": ["P00001", "P00002", dimensions.UNKNOWN], "category": ["Home & Kitchen",
                         "Toys & Games", "Unknown"], "unit_cost": [6.0, 3.0, None],
                         "launch_date": pd.to_datetime(["2020-01-06", "2020-01-06", None]),
                         "discontinued_date": pd.to_datetime([None, None, None])})


def run_sales(rows, ctx, late_rows=None, returns_rows=None, promos=None):
    """Run clean_sales on the given lines with default late, returns and promotion inputs."""
    main = frame(rows, "fact_sales.csv")
    late = frame(late_rows or [line("S01-20250310-00001", 1, "2025-03-10", ts="2025-03-30 06:00:00",
                                    batch="LATE-20250330")], "fact_sales_late_batch.csv")
    ret = pd.DataFrame(returns_rows or [], columns=["original_transaction_id", "original_line_number", "product_id"])
    promos = promos if promos is not None else pd.DataFrame(
        {"promotion_id": ["PR00001"], "store_id": ["S01"], "product_id": ["P00001"],
         "start_date": pd.to_datetime(["2025-03-03"]), "end_date": pd.to_datetime(["2025-03-09"]), "discount_pct": [0.2]})
    ref = dimensions.till_reference(pd.concat([main, late]))
    out = sales.clean_sales(main, late, ctx, {"S01", "S02"}, dim_product(), promos, ref, ret)
    return out.set_index(out["transaction_id"] + "|" + out["line_number"].astype(str))


# ------------------------------------------------------------------ core
def test_loader_refuses_evaluation_assets(tmp_path):
    cfg = load_config()
    with pytest.raises(ForbiddenInputError):
        load_raw(tmp_path, "_planted_issues_log", cfg)
    bad = dict(cfg, inputs={**cfg["inputs"], "sneaky": "_scenario_answer_key.csv"})
    with pytest.raises(ForbiddenInputError):
        load_raw(tmp_path, "sneaky", bad)


def test_config_inputs_are_whitelisted_business_extracts():
    cfg = load_config()
    assert not any(f.startswith("_") for f in cfg["inputs"].values())
    assert set(cfg["inputs"]) == set(cfg["contract"])


def test_blank_and_type_parsing():
    s = pd.Series(["", "NULL", " ", "5", "1.5", "abc"])
    assert is_blank(s).tolist() == [True, True, True, False, False, False]
    _, bad = parse_type(s, "int")
    assert bad.tolist() == [False, False, False, False, True, True]
    _, bad = parse_type(pd.Series(["2025-02-30", "2025-02-28", "28/02/2025"]), "date")
    assert bad.tolist() == [True, False, True]


def test_every_rule_has_severity_treatment_and_rationale():
    for r in CATALOGUE.values():
        assert r["severity"] in {"critical", "high", "medium", "low", "info"}
        assert r["treatment"] in {"CORRECT", "STANDARDISE", "DEDUPLICATE", "IMPUTE", "UNKNOWN_MEMBER", "QUARANTINE",
                                  "FLAG", "INCLUDE", "GAP", "NONE"}
        assert len(r["rationale"]) > 20


@pytest.mark.parametrize("raw,expected", [("Home and Kitchen", "Home & Kitchen"), ("HEALTH & BEAUTY", "Health & Beauty"),
                                          ("Home&Kitchen", "Home & Kitchen"), ("Electronics", "Electronics & Tech"),
                                          ("Electronic & Tech", "Electronics & Tech"), ("Toys", "Toys & Games"),
                                          ("Garden ", "Garden & Outdoor"), ("Stationary & Crafts", "Stationery & Crafts"),
                                          ("Furniture", None)])
def test_category_standardisation(raw, expected):
    assert dimensions.canonical_category(raw, load_config()["domains"]["categories"]) == expected


# ------------------------------------------------------------------ sales
def test_duplicate_lines_keep_earliest_copy(ctx):
    rows = base_lines() + [line("S01-20250303-00001", 1, "2025-03-03", ts="2025-03-04 05:40:00")]
    out = run_sales(rows, ctx)
    assert out.index.is_unique
    assert out.loc["S01-20250303-00001|1", "extract_timestamp"] == pd.Timestamp("2025-03-04 02:10:00")
    q = pd.concat(ctx.quarantine["fact_sales"])
    assert (q["dq_rule_id"] == "FS-01").sum() == 1


def test_dates_and_store_restored_from_transaction_id(ctx):
    rows = base_lines() + [line("S01-20250304-00001", 1, "04/03/2025"), line("S01-20250304-00002", 1, "2051-03-04"),
                           line("S01-20250304-00003", 1, ""), line("S01-20250304-00004", 1, "2025-03-04", store=""),
                           line("S01-20250304-00005", 1, "2025-03-04", store="S21")]
    out = run_sales(rows, ctx)
    for i in range(1, 6):
        r = out.loc[f"S01-20250304-{i:05d}|1"]
        assert r["transaction_date"] == pd.Timestamp("2025-03-04") and r["store_id"] == "S01"
    assert "FS-02" in out.loc["S01-20250304-00001|1", "dq_rules"]
    assert "FS-03" in out.loc["S01-20250304-00002|1", "dq_rules"]


def test_sign_errors_corrected(ctx):
    rows = base_lines() + [line("S01-20250304-00001", 1, "2025-03-04", q=-2, p=10.0, d=-0.0, rev=-20.0, cost=-12.0,
                                margin=-8.0),
                           line("S01-20250304-00002", 1, "2025-03-04", q=1, p=-10.0, d=-0.0, rev=-10.0, margin=-16.0)]
    out = run_sales(rows, ctx)
    a, b = out.loc["S01-20250304-00001|1"], out.loc["S01-20250304-00002|1"]
    assert (a["quantity"], a["revenue"], a["cost"], a["margin"]) == (2, 20.0, 12.0, 8.0)
    assert (b["unit_price"], b["revenue"], b["margin"]) == (10.0, 10.0, 4.0)


def test_decimal_shift_price_corrected_and_zero_price_imputed(ctx):
    rows = base_lines() + [line("S01-20250304-00001", 1, "2025-03-04", p=1000.0),
                           line("S01-20250304-00002", 1, "2025-03-04", p=0.0, rev=0.0, margin=-6.0)]
    out = run_sales(rows, ctx)
    a, b = out.loc["S01-20250304-00001|1"], out.loc["S01-20250304-00002|1"]
    assert (a["unit_price"], a["revenue"], a["margin"]) == (10.0, 10.0, 4.0)
    assert b["unit_price"] == 10.0 and b["is_imputed"] and b["dq_status"] == "imputed"


def test_missing_price_and_discount_derived(ctx):
    rows = base_lines() + [line("S01-20250304-00001", 1, "2025-03-04", q=2, p=None, d=4.0, rev=16.0),
                           line("S01-20250304-00002", 1, "2025-03-04", q=2, p=10.0, d=None, rev=16.0)]
    out = run_sales(rows, ctx)
    assert out.loc["S01-20250304-00001|1", "unit_price"] == 10.0
    assert out.loc["S01-20250304-00002|1", "discount"] == 4.0


def test_revenue_recomputed_only_when_cost_plus_margin_confirms(ctx):
    rows = base_lines() + [line("S01-20250304-00001", 1, "2025-03-04", rev=3.52, margin=4.0),   # components confirmed
                           line("S01-20250304-00002", 1, "2025-03-04", rev=3.52, margin=1.0)]   # not confirmed
    out = run_sales(rows, ctx)
    assert out.loc["S01-20250304-00001|1", "revenue"] == 10.0
    assert "S01-20250304-00002|1" not in out.index
    q = pd.concat(ctx.quarantine["fact_sales"])
    assert "FS-17" in set(q["dq_rule_id"])


def test_bulk_quantity_quarantined(ctx):
    rows = base_lines() + [line("S01-20250304-00001", 1, "2025-03-04", q=120)]
    out = run_sales(rows, ctx)
    assert "S01-20250304-00001|1" not in out.index
    assert "FS-09" in set(pd.concat(ctx.quarantine["fact_sales"])["dq_rule_id"])


def test_unknown_products_recovered_from_return_or_mapped_to_unknown(ctx):
    rows = base_lines() + [line("S01-20250304-00001", 1, "2025-03-04", prod=""),
                           line("S01-20250304-00002", 1, "2025-03-04", prod="P91234"),
                           line("S01-20250304-00003", 1, "2025-03-04", prod="P91235")]
    rets = [{"original_transaction_id": "S01-20250304-00001", "original_line_number": "1", "product_id": "P00001"},
            {"original_transaction_id": "S01-20250304-00002", "original_line_number": "1", "product_id": "P00001"}]
    out = run_sales(rows, ctx, returns_rows=rets)
    assert out.loc["S01-20250304-00001|1", "product_id"] == "P00001"
    assert out.loc["S01-20250304-00002|1", "product_id"] == "P00001"
    assert out.loc["S01-20250304-00003|1", "product_id"] == dimensions.UNKNOWN


def test_unknown_promotion_codes(ctx):
    rows = base_lines() + [line("S01-20250304-00001", 1, "2025-03-04", d=2.0, promo="PR90001"),   # matches PR00001
                           line("S01-20250304-00002", 1, "2025-03-04", promo="PR90002"),          # no discount
                           line("S01-20250304-00003", 1, "2025-03-04", d=1.0, promo="PR90003")]   # 10%: no match
    out = run_sales(rows, ctx)
    assert out.loc["S01-20250304-00001|1", "promotion_id"] == "PR00001"
    assert pd.isna(out.loc["S01-20250304-00002|1", "promotion_id"])
    assert out.loc["S01-20250304-00003|1", "promotion_id"] == dimensions.UNKNOWN


def test_late_file_included_and_flagged(ctx):
    out = run_sales(base_lines(), ctx)
    late = out[out["source_file"] == "fact_sales_late_batch.csv"]
    assert len(late) == 1 and late["is_late_arriving"].all()
    assert ctx.results["TC-01"]["rows_failed"] == 1


def test_category_taken_from_product_master(ctx):
    rows = base_lines() + [line("S01-20250304-00001", 1, "2025-03-04", cat="HOME and KITCHEN ")]
    out = run_sales(rows, ctx)
    assert out.loc["S01-20250304-00001|1", "category"] == "Home & Kitchen"


# ------------------------------------------------------------------ inventory
INV_COLS = ["snapshot_date", "retail_year", "retail_week", "store_id", "product_id", "opening_stock", "received_qty",
            "sold_qty", "adjustment_qty", "closing_stock"]


def inv_row(date, wk, o, r, s, a, c, prod="P00001"):
    """One raw inventory row: opening, received, sold, adjustment, closing."""
    return dict(zip(INV_COLS, [date, "2025", str(wk), "S01", prod, str(o), r, str(s), str(a), str(c)]))


def test_inventory_rules(ctx):
    dd = pd.DataFrame({"date": pd.date_range("2025-03-03", "2025-03-30")})
    dd["retail_year"] = 2025
    dd["retail_week"] = 10 + (dd.index // 7)
    rows = [inv_row("2025-03-09", 10, 5, "2.0", 3, 0, 4),
            inv_row("2025-03-16", 11, 9, "0.0", 1, 0, 3),     # opening corrupted (should be 4)
            inv_row("2025-03-23", 12, 3, "", 2, 0, 6),        # received missing (should be 5)
            inv_row("2025-03-30", 13, 6, "0.0", 1, 0, -5),    # closing sign flipped
            inv_row("2025-03-30", 13, 6, "0.0", 1, 0, -5)]    # exact duplicate
    out = returns_inventory.clean_inventory(frame(rows, "fact_inventory.csv"), ctx, {"S01"}, {"P00001"}, dd)
    out = out.set_index("retail_week")
    assert len(out) == 4
    assert out.loc[11, "opening_stock"] == 4
    assert out.loc[12, "received_qty"] == 5
    assert out.loc[13, "closing_stock"] == 5
    ident = out["opening_stock"] + out["received_qty"] - out["sold_qty"] + out["adjustment_qty"]
    assert (ident == out["closing_stock"]).all()
    assert ctx.results["TC-05"]["rows_failed"] == 0


# ------------------------------------------------------------------ returns
def test_returns_rules(ctx):
    s = pd.DataFrame({"transaction_id": ["S01-20250303-00001", "S01-20250303-00002"], "line_number": [1, 1],
                      "store_id": ["S01", "S01"], "product_id": ["P00001", "P00001"], "quantity": [1, 1],
                      "revenue": [10.0, 10.0], "transaction_date": pd.to_datetime(["2025-03-03"] * 2)})
    ctx.notes["sales_all_keys"] = {"S01-20250303-00001|1", "S01-20250303-00002|1"}
    cols = ["return_id", "return_date", "store_id", "original_transaction_id", "original_line_number", "product_id",
            "return_quantity", "refund_value", "return_reason", "restockable_flag"]
    rows = [["R0000001", "2025-03-05", "S01", "S01-20250303-00001", "1", "P00001", "1", "10.0", "Faulty", "False"],
            ["R0000002", "2025-03-01", "S01", "S01-20250303-00002", "1", "P00001", "1", "10.0", "Faulty", "False"],
            ["R0000003", "2025-03-05", "S01", "S01-20250303-00002", "1", "P00001", "3", "30.0", "Faulty", "False"],
            ["R0000004", "2025-03-05", "S01", "S01-20250303-00099", "7", "P00001", "1", "10.0", "Faulty", "False"],
            ["R0000005", "2025-03-05", "S01", "", "", "P00001", "1", "10.0", "Changed mind", "True"],
            ["R0000005", "2025-03-05", "S01", "", "", "P00001", "1", "10.0", "Changed mind", "True"]]
    raw = frame([dict(zip(cols, r)) for r in rows], "fact_returns.csv")
    out = returns_inventory.clean_returns(raw, ctx, s, {"S01"}, {"P00001"}, set()).set_index("return_id")
    assert set(out.index) == {"R0000001", "R0000004", "R0000005"}
    assert "FR-04" in out.loc["R0000004", "dq_rules"]
    assert ctx.results["FR-05"]["rows_failed"] == 1 and ctx.results["FR-06"]["rows_failed"] == 1
    assert ctx.results["FR-01"]["rows_failed"] == 1


# ------------------------------------------------------------------ promotions and targets
def test_promotion_window_restored_and_orphans_quarantined(ctx):
    cols = ["promotion_id", "promotion_name", "promotion_type", "product_id", "store_id", "start_date", "end_date",
            "discount_pct"]
    rows = [["PR00001", "A", "Percent Off", "P00001", "S01", "2025-03-03", "2025-03-16", "0.2"],
            ["PR00001", "A", "Percent Off", "P00002", "S01", "2025-03-16", "2025-03-03", "0.2"],
            ["PR00001", "A", "Percent Off", "P91111", "S01", "2025-03-03", "2025-03-16", "0.2"]]
    out = promotions_targets.clean_promotions(frame([dict(zip(cols, r)) for r in rows], "fact_promotions.csv"), ctx,
                                              {"S01"}, {"P00001", "P00002"})
    assert len(out) == 2 and (out["end_date"] >= out["start_date"]).all()
    assert out.loc[out["product_id"] == "P00002", "start_date"].iloc[0] == pd.Timestamp("2025-03-03")


def test_targets_versions_and_decimal_shift(ctx):
    dd = pd.DataFrame({"date": pd.date_range("2025-01-06", "2025-03-02")})
    dd["retail_year"], dd["retail_week"] = 2025, 2 + dd.index // 7
    cols = ["store_id", "retail_year", "retail_week", "week_start_date", "week_end_date", "target_net_revenue",
            "target_version", "target_set_date"]
    rows = []
    for w in range(2, 10):
        s0 = pd.Timestamp("2025-01-06") + pd.Timedelta(weeks=w - 2)
        rows.append(["S01", "2025", str(w), f"{s0:%Y-%m-%d}", f"{s0 + pd.Timedelta(days=6):%Y-%m-%d}", "40000.0", "V1",
                     "2024-11-20"])
    rows[3][5] = "4200000.0"
    rows.append(rows[0][:5] + ["41000.0", "V2", "2024-11-20"])
    out = promotions_targets.clean_targets(frame([dict(zip(cols, r)) for r in rows], "fact_targets.csv"), ctx, {"S01"}, dd)
    out = out.set_index("retail_week")
    assert len(out) == 8
    assert out.loc[2, "target_version"] == "V2"
    assert out.loc[5, "target_net_revenue"] == 42000.0


def test_design_document_lists_every_rule():
    from pathlib import Path
    doc = (Path(__file__).resolve().parents[1] / "docs" / "03_data_quality_design.md").read_text()
    missing = [r for r in CATALOGUE if f"| {r} |" not in doc]
    assert not missing, missing
