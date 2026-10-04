"""Data tests on the generated sample (data/sample) against the Phase 1 BRD."""
import pytest

GROUPS = ["keys", "transaction integrity", "referential integrity", "dates", "business rules", "reconciliation",
          "KPI identities", "expected ranges", "seasonality", "store/product", "planted issues", "headline",
          "calibration", "scenario separation"]


@pytest.mark.parametrize("group", GROUPS)
def test_validation_group_passes(validation_results, group):
    res, _ = validation_results
    grp = res[res["group"] == group]
    assert len(grp) > 0, f"no checks in group {group}"
    failed = grp[grp["status"] == "FAIL"]
    assert failed.empty, "\n" + failed.to_string(index=False)


def test_sales_revenue_identity(validation_results):
    _, k = validation_results
    assert k["transactions"] * k["upt"] * k["asp"] == pytest.approx(k["sales_revenue"], rel=1e-9)


def test_net_revenue_identity(validation_results):
    _, k = validation_results
    assert k["net_revenue"] == pytest.approx(k["sales_revenue"] - k["returns_value"], rel=1e-12)


def test_every_raw_table_has_planted_issues(sample_dataset):
    tables = set(sample_dataset.log["table_name"])
    assert {"fact_sales", "dim_product", "dim_store", "fact_inventory", "fact_returns",
            "fact_promotions", "fact_targets"} <= tables


def test_late_batch_is_separate_file(sample_dataset):
    late = sample_dataset.raw["fact_sales_late_batch"]
    assert len(late) > 0
    assert late["extract_batch_id"].str.startswith("LATE-").all()
