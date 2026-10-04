"""Unit tests for the data generator components (no generated files needed)."""
import hashlib

import numpy as np
import pandas as pd
import pytest

from src.data_generation import calendar_builder, demand, dimensions, promotions, simulation
from src.data_generation.config_loader import load_generator_config
from src.data_generation.validate_generated import compute_kpis


@pytest.fixture(scope="module")
def cfg():
    """Generator configuration."""
    return load_generator_config()


def test_retail_weeks_are_week_aligned(cfg):
    weeks = calendar_builder.build_week_table(cfg)
    w27_24 = weeks[(weeks.retail_year == 2024) & (weeks.retail_week == 27)].week_start.iloc[0]
    w27_25 = weeks[(weeks.retail_year == 2025) & (weeks.retail_week == 27)].week_start.iloc[0]
    assert w27_24.dayofweek == 0 and w27_25.dayofweek == 0          # both Mondays
    assert (w27_25 - w27_24).days == 364                           # exactly 52 weeks apart


def test_dim_date_flags(cfg):
    weeks = calendar_builder.build_week_table(cfg)
    d = calendar_builder.build_dim_date(cfg, weeks).set_index("date")
    assert len(d) == 731
    assert not d.loc["2025-12-25", "is_trading_day"]
    assert d.loc["2025-03-17", "is_bank_holiday"]
    assert d.loc["2025-06-30", "retail_week"] == 27 and d.loc["2025-06-30", "retail_half"] == "H2"


def test_day_weights_sum_to_one_and_christmas_closed(cfg):
    weeks = calendar_builder.build_week_table(cfg)
    w, share = calendar_builder.build_day_weights(cfg, weeks)
    assert np.allclose(w.sum(axis=1), 1)
    xmas_week = weeks.index[weeks.week_start == pd.Timestamp("2025-12-22")][0]
    assert w[xmas_week, 3] == 0                                     # Thursday 25 Dec 2025
    assert share[-1] < 1 and share[:-1].min() == 1                  # only final week is partial


def test_seasonality_index_mean_one(cfg):
    idx = demand.seasonality_index(cfg)
    for cat, v in idx.items():
        assert v.shape == (52,) and np.isclose(v.mean(), 1.0), cat
    assert idx["Seasonal & Gifts"][49] > 3 * idx["Seasonal & Gifts"][20]


def test_products_prices_and_margins(cfg):
    p = dimensions.build_dim_product(cfg, np.random.default_rng(1))
    assert len(p) == 600 and p.product_id.is_unique
    assert (p.list_price_2025 >= p.list_price_2024).all()
    assert (p.unit_cost_2024 < p.list_price_2024).all() and (p.unit_cost_2024 > 0).all()
    assert (p.launch_date.dt.dayofweek == 0).all()                  # range changes on Mondays


def test_ranging_respects_format_shares(cfg):
    rng = np.random.default_rng(3)
    stores = dimensions.build_dim_store(cfg, rng)
    p = dimensions.build_dim_product(cfg, rng)
    r = dimensions.build_ranging(cfg, stores, p, rng)
    share = pd.Series(r.mean(axis=1), index=stores.store_format).groupby(level=0).mean()
    assert share["Flagship"] == 1.0
    assert abs(share["Compact"] - 0.60) < 0.02 and abs(share["Standard"] - 0.86) < 0.02


def test_cum_within_groups():
    keys = np.array([1, 1, 1, 2, 2, 5])
    qty = np.array([1, 2, 1, 3, 1, 2])
    assert simulation._cum_within_groups(keys, qty).tolist() == [1, 3, 4, 3, 4, 2]


def test_promotion_uplift_and_pull_forward():
    ev = promotions.PromoEvent("X", "Percent Off", week_idx=1, duration=1, skus=np.array([0]),
                               depths=np.array([0.3]), stores=np.array([0]), elasticity=2.0,
                               display_effect=0.1, pull_forward_share=0.5, pull_forward_weeks=2)
    ranged = np.ones((1, 1), dtype=bool)
    depth, ref, mult = promotions.promo_arrays([ev], ranged, n_weeks=5)
    assert depth[1, 0, 0] == 0.3 and ref[1, 0, 0] == 0
    assert np.isclose(mult[1, 0, 0], 1 + 2.0 * 0.3 + 0.1)           # 1.7x during promotion
    assert np.isclose(mult[2, 0, 0], 1 - 0.5 * 0.7 / 2)             # dip after
    assert np.isclose(mult[3, 0, 0], 1 - 0.5 * 0.7 / 2) and mult[4, 0, 0] == 1


def test_kpi_identities_on_toy_data():
    sales = pd.DataFrame({
        "transaction_id": ["T1", "T1", "T2"], "product_id": ["A", "B", "A"], "quantity": [2, 1, 1],
        "unit_price": [10.0, 5.0, 10.0], "discount": [2.0, 0.0, 0.0], "revenue": [18.0, 5.0, 10.0],
        "unit_cost": [6.0, 2.0, 6.0], "cost": [12.0, 2.0, 6.0], "promotion_id": ["P1", None, None]})
    returns = pd.DataFrame({"product_id": ["A"], "return_quantity": [1], "refund_value": [9.0],
                            "restockable_flag": [True]})
    k = compute_kpis(sales, returns)
    assert k["gross_sales"] == 35 and k["discount_value"] == 2 and k["sales_revenue"] == 33
    assert k["net_revenue"] == 24 and k["transactions"] == 2 and k["upt"] == 2.0
    assert np.isclose(k["transactions"] * k["upt"] * k["asp"], k["sales_revenue"])
    assert k["cogs"] == 20 - 6 and k["gross_margin"] == 24 - 14


def _hash_dir(path):
    h = hashlib.sha256()
    for f in sorted(path.glob("*.csv")):
        h.update(f.read_bytes())
    return h.hexdigest()


@pytest.mark.slow
def test_generation_is_reproducible(tmp_path):
    """Same config + seed must give byte-identical files."""
    from src.data_generation.generate_data import run

    run("sample", out_dir=tmp_path / "a")
    run("sample", out_dir=tmp_path / "b")
    assert _hash_dir(tmp_path / "a") == _hash_dir(tmp_path / "b")
