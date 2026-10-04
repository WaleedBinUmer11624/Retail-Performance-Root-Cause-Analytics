"""Profile every raw extract before any cleaning (read-only).

Per column: contract type, blanks, type-parse failures, distinct values, min/max,
leading/trailing whitespace, top values. Per table: rows, columns, key duplicates,
exact duplicate rows, missing/unexpected columns.
"""
from __future__ import annotations

import pandas as pd

from .core import is_blank, key_of, parse_type

META = ("source_file", "source_row")


def profile_table(name: str, df: pd.DataFrame, contract: dict) -> tuple[dict, list[dict]]:
    """Profile one raw table against its contract; return (table summary, per-column rows)."""
    types = contract["types"]
    data_cols = [c for c in df.columns if c not in META]
    cols = []
    for c in data_cols:
        s = df[c]
        blank = is_blank(s)
        kind = types.get(c, "str")
        parsed, failed = parse_type(s, kind)
        nonblank = s[~blank]
        vc = nonblank.value_counts()
        row = {"table_name": name, "column_name": c, "contract_type": kind, "rows": len(s),
               "blank": int(blank.sum()), "blank_pct": round(100 * blank.mean(), 3),
               "type_failures": int(failed.sum()), "distinct": int(nonblank.nunique()),
               "untrimmed": int((nonblank != nonblank.str.strip()).sum()),
               "top_values": "; ".join(f"{k} ({v})" for k, v in vc.head(5).items())}
        if kind in ("int", "decimal", "date", "datetime"):
            ok = parsed[~failed & ~blank]
            row["min"] = str(ok.min()) if len(ok) else ""
            row["max"] = str(ok.max()) if len(ok) else ""
            if kind in ("int", "decimal") and len(ok):
                row["negative"] = int((ok < 0).sum())
                row["zero"] = int((ok == 0).sum())
                row["p50"] = float(ok.median())
                row["p99_9"] = float(ok.quantile(0.999))
        if failed.any():
            row["failure_examples"] = "; ".join(s[failed].unique()[:5])
        cols.append(row)
    key = contract["key"]
    kd = key_of(df, key).duplicated(keep=False) if set(key) <= set(df.columns) else pd.Series(False, index=df.index)
    exact = df[data_cols].duplicated(keep="first")
    table = {"table_name": name, "rows": len(df), "columns": len(data_cols), "primary_key": "+".join(key),
             "rows_in_duplicated_keys": int(kd.sum()), "exact_duplicate_rows": int(exact.sum()),
             "missing_columns": ",".join(sorted(set(types) - set(data_cols))),
             "unexpected_columns": ",".join(sorted(set(data_cols) - set(types))),
             "columns_with_blanks": int(sum(1 for r in cols if r["blank"])),
             "columns_with_type_failures": int(sum(1 for r in cols if r["type_failures"]))}
    return table, cols


def profile_all(raw: dict, cfg: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Profile every raw table; return (table profile, column profile) frames."""
    tables, columns = [], []
    for name, df in raw.items():
        t, c = profile_table(name, df, cfg["contract"][name])
        tables.append(t)
        columns += c
    return pd.DataFrame(tables), pd.DataFrame(columns)
