"""Shared pytest fixtures and reproducibility assertion helper."""
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "data" / "sample"


# ------------------------------------------------------------------------------------ reproducibility
# Some committed tables carry a mixed column (numbers and words in one field), so pandas types it as
# object and assert_frame_equal then compares element-by-element with exact float equality. A value
# that is correct to 15 significant digits can still differ in its last bit between platforms, which
# made a numeric reproducibility check fail for the wrong reason. The tolerance the tests already
# intended (rtol=1e-9, atol=1e-6) is applied per element to numeric values only; everything else,
# including all text, is still compared exactly.
REPRO_RTOL = 1e-9
REPRO_ATOL = 1e-6


def _as_number(value):
    """Return value as a float if it is a real finite/NaN number, else None for exact comparison."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def assert_reproducible(a: pd.DataFrame, b: pd.DataFrame, name: str,
                        rtol: float = REPRO_RTOL, atol: float = REPRO_ATOL) -> None:
    """Assert a fresh result table reproduces a committed one.

    Numeric columns and numeric values inside mixed columns are compared with rtol/atol; textual
    values are compared exactly. Column order, column names and row count must match exactly.
    """
    pd.testing.assert_index_equal(a.columns, b.columns, obj=name)
    assert len(a) == len(b), f"{name}: row count differs, committed {len(a)} vs fresh {len(b)}"
    for col in a.columns:
        for i, (left, right) in enumerate(zip(a[col].tolist(), b[col].tolist())):
            ln, rn = _as_number(left), _as_number(right)
            if ln is not None and rn is not None:
                if ln != ln and rn != rn:          # both NaN
                    continue
                assert abs(ln - rn) <= atol + rtol * abs(rn), \
                    f"{name}: column {col!r} row {i} differs beyond tolerance: {ln!r} vs {rn!r}"
            else:
                same = (left is None and right is None) or \
                       (isinstance(left, float) and isinstance(right, float)
                        and left != left and right != right) or left == right
                assert same, f"{name}: column {col!r} row {i} differs: {left!r} vs {right!r}"


@pytest.fixture(scope="session")
def sample_dataset():
    """Loaded sample dataset; skipped if the sample has not been generated."""
    from src.data_generation.validate_generated import load_dataset

    if not (SAMPLE / "fact_sales.csv").exists():
        pytest.skip("Sample not generated. Run: python -m src.data_generation.generate_data --mode sample")
    return load_dataset(SAMPLE)


@pytest.fixture(scope="session")
def validation_results():
    """Full validation suite run on the sample, shared by the session."""
    from src.data_generation.validate_generated import run_all

    if not (SAMPLE / "fact_sales.csv").exists():
        pytest.skip("Sample not generated.")
    res, kpis = run_all(SAMPLE)
    return res, kpis
