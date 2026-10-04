"""Database engines for the Phase 4 model.

SqlServerEngine   the target: SQL Server 2022 via pyodbc (Windows authentication). Batches are sent
                  exactly as written.
DuckDBEngine      local verification engine used where SQL Server is not available (CI, this
                  project's build environment). Each T-SQL statement is parsed with sqlglot's T-SQL
                  dialect, adjusted for a few type differences, and executed in DuckDB. Batches marked
                  @tsql-only (physical design, THROW) are skipped; their intent is verified by tests.
"""
from __future__ import annotations

import time

import pandas as pd

from .scripts import Batch, strip_comments


class EngineError(RuntimeError):
    pass


# --------------------------------------------------------------------------- DuckDB
class DuckDBEngine:
    name = "duckdb"

    def __init__(self, path: str = ":memory:"):
        import duckdb
        self.con = duckdb.connect(path)
        self.path = path
        for schema in ("stg", "dw", "mart", "recon"):     # SQL Server: created by script 01
            self.con.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")

    # ---- T-SQL -> DuckDB translation
    @staticmethod
    def translate(tsql: str) -> list[str]:
        import sqlglot
        from sqlglot import exp

        text_types = {exp.DataType.Type.NVARCHAR, exp.DataType.Type.VARCHAR, exp.DataType.Type.NCHAR,
                      exp.DataType.Type.CHAR, exp.DataType.Type.TEXT}

        def fix(node):
            # T-SQL key columns are parsed as ordered expressions; DuckDB keys take plain columns
            if isinstance(node, exp.Ordered) and isinstance(node.parent, exp.PrimaryKey):
                return node.this
            if isinstance(node, exp.DataType):
                if node.this in text_types:
                    return exp.DataType.build("VARCHAR")
                if node.this in (exp.DataType.Type.DATETIME2, exp.DataType.Type.DATETIME):
                    return exp.DataType.build("TIMESTAMP")
                if node.this == exp.DataType.Type.TIME:
                    return exp.DataType.build("TIME")
                if node.this == exp.DataType.Type.FLOAT:
                    return exp.DataType.build("DOUBLE")
            return node

        out = []
        for stmt in sqlglot.parse(strip_comments(tsql), read="tsql"):
            if stmt is None:
                continue
            if isinstance(stmt, exp.Set) or (isinstance(stmt, exp.Command) and stmt.sql().upper().startswith("SET NOCOUNT")):
                continue
            if isinstance(stmt, exp.Command):
                raise EngineError(f"statement not translatable to DuckDB: {stmt.sql()[:120]}")
            out.append(stmt.transform(fix).sql(dialect="duckdb"))
        return out

    def run_batch(self, batch: Batch) -> float:
        t0 = time.time()
        for sql in self.translate(batch.text):
            try:
                self.con.execute(sql)
            except Exception as e:  # noqa: BLE001
                raise EngineError(f"{batch.file} batch {batch.index}: {e}\n--- SQL ---\n{sql[:1500]}") from e
        return time.time() - t0

    def query(self, tsql: str) -> pd.DataFrame:
        (sql,) = self.translate(tsql)
        return self.con.execute(sql).df()

    def execute(self, tsql: str):
        for sql in self.translate(tsql):
            self.con.execute(sql)

    def load_table(self, table: str, df: pd.DataFrame):
        self.con.register("_load_df", df)
        cols = ", ".join(f'"{c}"' for c in df.columns)
        self.con.execute(f"INSERT INTO {table} ({cols}) SELECT {cols} FROM _load_df")
        self.con.unregister("_load_df")

    def close(self):
        self.con.close()


# --------------------------------------------------------------------------- SQL Server
class SqlServerEngine:
    name = "mssql"

    def __init__(self, db_cfg: dict, database: str | None = None):
        import pyodbc
        self.pyodbc = pyodbc
        self.db_cfg = db_cfg
        self.database = database or db_cfg["database"]
        self.con = self._connect(self.database)

    def _connect(self, database: str):
        c = self.db_cfg
        parts = [f"DRIVER={{{c['driver']}}}", f"SERVER={c['server']}", f"DATABASE={database}"]
        if c.get("trusted_connection", True):
            parts.append("Trusted_Connection=yes")
        if c.get("trust_server_certificate", True):
            parts.append("TrustServerCertificate=yes")
        con = self.pyodbc.connect(";".join(parts), autocommit=True)
        return con

    def use(self, database: str):
        self.con.close()
        self.database = database
        self.con = self._connect(database)

    def run_batch(self, batch: Batch) -> float:
        t0 = time.time()
        cur = self.con.cursor()
        try:
            cur.execute(batch.text)
            while cur.nextset():
                pass
        except self.pyodbc.Error as e:
            raise EngineError(f"{batch.file} batch {batch.index}: {e}") from e
        return time.time() - t0

    def query(self, tsql: str) -> pd.DataFrame:
        cur = self.con.cursor()
        cur.execute(tsql)
        cols = [d[0] for d in cur.description]
        return pd.DataFrame.from_records(cur.fetchall(), columns=cols)

    def execute(self, tsql: str):
        cur = self.con.cursor()
        cur.execute(tsql)

    def load_table(self, table: str, df: pd.DataFrame, chunk: int = 20_000):
        """Parameter-array insert, one transaction per chunk (autocommit would commit row by row)."""
        cols = ", ".join(f"[{c}]" for c in df.columns)
        marks = ", ".join("?" for _ in df.columns)
        sql = f"INSERT INTO {table} ({cols}) VALUES ({marks})"
        rows = df.astype(object).where(df.notna(), None).values.tolist()
        self.con.autocommit = False
        try:
            cur = self.con.cursor()
            cur.fast_executemany = True
            for i in range(0, len(rows), chunk):
                cur.executemany(sql, rows[i:i + chunk])
                self.con.commit()
        except Exception:
            self.con.rollback()
            raise
        finally:
            self.con.autocommit = True

    def close(self):
        self.con.close()
