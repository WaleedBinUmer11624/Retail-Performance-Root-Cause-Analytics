"""Core plumbing for the Phase 3 data-quality pipeline.

* safe loading of raw extracts (whitelist only; raw files are never written)
* type parsing helpers that report failures instead of hiding them
* DQContext: collects rule results, row-level issues, quarantined rows and the
  audit trail of every change

Inputs: config/dq_config.yaml and the approved raw extracts. Outputs: parsed frames and a DQContext
holding rule results, issue log, quarantine and audit trail for the reporting step.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = PROJECT_ROOT / "config" / "dq_config.yaml"


def load_config(path: Path = CONFIG_PATH) -> dict:
    """Parsed dq_config.yaml."""
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def sha256(path: Path) -> str:
    """SHA-256 hex digest of a file, read in 1 MB chunks."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_csv(df: pd.DataFrame, path: Path, index: bool = False) -> None:
    """Write a CSV with platform-independent LF record terminators."""
    df.to_csv(path, index=index, lineterminator="\n")


class ForbiddenInputError(RuntimeError):
    """Raised when code tries to read a file that is not an approved input."""


def load_raw(data_dir: Path, table: str, cfg: dict) -> pd.DataFrame:
    """Read one raw extract as text. Only tables listed in dq_config.inputs are allowed,
    and never a file whose name starts with an underscore (evaluation-only assets)."""
    inputs = cfg["inputs"]
    if table not in inputs:
        raise ForbiddenInputError(f"{table} is not an approved Phase 3 input")
    name = inputs[table]
    if name.startswith("_") or table.startswith("_"):
        raise ForbiddenInputError(f"{name} is an evaluation-only asset")
    # Read everything as text so no value is silently coerced; each rule parses what it checks.
    df = pd.read_csv(Path(data_dir) / name, dtype=str, keep_default_na=False, na_filter=False)
    df.insert(0, "source_row", np.arange(2, len(df) + 2))   # CSV line number (header is line 1)
    df.insert(0, "source_file", name)
    return df


# ------------------------------------------------------------------ parsing
NULL_TOKENS = {"", "NULL", "null", "None", "NaN", "nan", "N/A", "n/a", "#N/A"}


def is_blank(s: pd.Series) -> pd.Series:
    """Blank or a null token. Whitespace-only values are rare, so strip only the short values."""
    out = s.isin(NULL_TOKENS)
    short = s.str.len() <= 4
    if short.any():
        out |= short & s.where(short, "x").str.strip().isin(NULL_TOKENS)
    return out


def to_num(s: pd.Series) -> pd.Series:
    """Numeric value, NaN for blanks and unparseable text."""
    return pd.to_numeric(s.where(~is_blank(s)), errors="coerce")


def parse_date_iso(s: pd.Series) -> pd.Series:
    """Strict yyyy-mm-dd date, NaT otherwise."""
    return pd.to_datetime(s.where(~is_blank(s)), format="%Y-%m-%d", errors="coerce")


def parse_date_dmy(s: pd.Series) -> pd.Series:
    """Strict dd/mm/yyyy date (legacy format), NaT otherwise."""
    return pd.to_datetime(s.where(~is_blank(s)), format="%d/%m/%Y", errors="coerce")


def parse_type(s: pd.Series, kind: str) -> tuple[pd.Series, pd.Series]:
    """Parse a text column to its contract type. Returns (parsed, failed_mask); blanks are not failures."""
    blank = is_blank(s)
    if kind == "str":
        return s, pd.Series(False, index=s.index)
    if kind in ("int", "decimal"):
        v = to_num(s)
        bad = v.isna() & ~blank
        if kind == "int":
            bad |= v.notna() & (v != np.round(v))
        return v, bad
    if kind == "date":
        v = parse_date_iso(s)
    elif kind == "datetime":
        v = pd.to_datetime(s.where(~blank), format="%Y-%m-%d %H:%M:%S", errors="coerce")
    elif kind == "time":
        v = pd.to_datetime(s.where(~blank), format="%H:%M", errors="coerce")
    elif kind == "bool":
        v = s.map({"True": True, "False": False})
    else:
        raise ValueError(kind)
    return v, v.isna() & ~blank


def key_of(df: pd.DataFrame, cols: list[str]) -> pd.Series:
    """Pipe-joined business key, the row_key format used in the issue log."""
    out = df[cols[0]].astype(str)
    for c in cols[1:]:
        out = out + "|" + df[c].astype(str)
    return out


# ------------------------------------------------------------------ rule results and audit
@dataclass
class DQContext:
    """Mutable state for one pipeline run."""
    cfg: dict
    catalogue: dict
    results: dict = field(default_factory=dict)        # rule_id -> {rows_checked, rows_failed, ...}
    issues: list = field(default_factory=list)          # row-level issue frames
    quarantine: dict = field(default_factory=dict)      # table -> list of frames
    audit: list = field(default_factory=list)           # one entry per treatment step
    notes: dict = field(default_factory=dict)           # rule_id -> free-text evidence

    def rule(self, rule_id: str) -> dict:
        """Catalogue entry for a rule."""
        return self.catalogue[rule_id]

    def result(self, rule_id: str, rows_checked: int, rows_failed: int, revenue_affected: float = 0.0,
               evidence: str = "", **extra):
        """Record or accumulate a rule's checked and failed counts."""
        r = self.catalogue[rule_id]
        prev = self.results.get(rule_id)
        if prev:   # a rule can be evaluated on several tables or passes: accumulate
            prev["rows_checked"] += rows_checked
            prev["rows_failed"] += rows_failed
            prev["revenue_affected"] += revenue_affected
            prev["evidence"] = "; ".join(x for x in (prev["evidence"], evidence) if x)
            return
        self.results[rule_id] = {"rule_id": rule_id, "table": r["table"], "dimension": r["dimension"],
                                 "check": r["check"], "severity": r["severity"], "treatment": r["treatment"],
                                 "rows_checked": int(rows_checked), "rows_failed": int(rows_failed),
                                 "revenue_affected": float(revenue_affected), "evidence": evidence, **extra}

    def log_rows(self, rule_id: str, table: str, keys: pd.Series, column: str = "",
                 raw_value=None, new_value=None, action: str | None = None):
        """Row-level issue log: one line per affected record."""
        if len(keys) == 0:
            return
        n = len(keys)

        def _vals(v):
            if v is None:
                return [""] * n
            if isinstance(v, pd.Series):
                return v.astype(object).where(v.notna(), "").astype(str).to_numpy()
            return [str(v)] * n
        self.issues.append(pd.DataFrame({
            "rule_id": rule_id, "table_name": table, "row_key": keys.astype(str).to_numpy(), "column_name": column,
            "raw_value": _vals(raw_value), "new_value": _vals(new_value),
            "action": action or self.catalogue[rule_id]["treatment"],
            "severity": self.catalogue[rule_id]["severity"]}))

    def add_quarantine(self, table: str, rows: pd.DataFrame, rule_id: str, reason: str):
        """Hold rows out of the curated table, tagged with the rule and reason."""
        if len(rows):
            q = rows.copy()
            q["dq_rule_id"] = rule_id
            q["dq_reason"] = reason
            self.quarantine.setdefault(table, []).append(q)

    def audit_step(self, table: str, rule_id: str, action: str, rows_affected: int, column: str = "",
                   metric: str = "", before=None, after=None, note: str = ""):
        """Append one numbered treatment step, with the metric's value before and after."""
        self.audit.append({"step": len(self.audit) + 1, "table_name": table, "rule_id": rule_id,
                           "action": action, "column_name": column, "rows_affected": int(rows_affected),
                           "metric": metric, "metric_before": before, "metric_after": after,
                           "metric_change": (None if before is None or after is None else round(after - before, 2)),
                           "note": note})


def id_date(transaction_id: pd.Series) -> pd.Series:
    """Business date encoded in the transaction ID (Sxx-yyyymmdd-nnnnn)."""
    return pd.to_datetime(transaction_id.str.slice(4, 12), format="%Y%m%d", errors="coerce")


def id_store(transaction_id: pd.Series) -> pd.Series:
    """Store id encoded in the transaction ID (first three characters)."""
    return transaction_id.str.slice(0, 3)


def matches(s: pd.Series, pattern: str) -> pd.Series:
    """Full-string regex match, ASCII only; missing values count as no match."""
    return s.str.fullmatch(pattern, flags=re.ASCII).fillna(False)
