"""BigQuery engine for the Phase 4 model: T-SQL batches transpiled with sqlglot, run as BigQuery jobs.

The Phase 4 scripts are written for SQL Server and are not changed. Each statement is parsed with
sqlglot's T-SQL dialect and generated in the BigQuery dialect. Where the generated SQL is not valid
or not equivalent on BigQuery, a named rewrite rule adjusts the parsed statement first (RULES below,
documented in docs/bigquery_engine.md). Every rule application is logged, so the build report lists
exactly which statements needed a rewrite.

Free tier and sandbox: no DML is used. Staging and expected values arrive by load jobs, and every
INSERT is rebuilt as CREATE OR REPLACE TABLE ... AS SELECT. Every query job carries
maximum_bytes_billed. Authentication is Application Default Credentials only.
"""
from __future__ import annotations

import io
import time
from collections import defaultdict
from dataclasses import dataclass, field

import pandas as pd
import sqlglot
from sqlglot import exp

from src.sql_model.engines import EngineError
from src.sql_model.scripts import Batch, strip_comments

SCHEMAS = ("stg", "dw", "mart", "recon")

# Hand-rewrite rules: id -> why sqlglot's generated BigQuery SQL is not used as is.
RULES = {
    "R1_national_literal": "T-SQL N'...' literals are generated unchanged; BigQuery has no N prefix (syntax error).",
    "R2_decimal_cast": "BigQuery rejects parameterized types in CAST. CAST(x AS DECIMAL(p,s)) rounds to s places in "
                       "T-SQL, so it becomes ROUND(CAST(x AS NUMERIC), s).",
    "R3_text_cast": "CAST(x AS NVARCHAR(n)) becomes CAST(x AS STRING); the length is not allowed in CAST.",
    "R4_dataset_qualify": "BigQuery has datasets, not schemas: stg, dw, mart and recon become prefixed datasets in the "
                          "configured project.",
    "R5_insert_to_ctas": "The sandbox (no billing account) does not allow DML. Each table's INSERT statements are "
                         "combined with UNION ALL into CREATE OR REPLACE TABLE ... AS SELECT, every value cast to the "
                         "column type declared by the Phase 4 DDL, in DDL column order.",
    "R6_skip_clear": "DELETE and TRUNCATE before a reload are not needed (and not allowed): the reload replaces the table.",
    "R7_replace_objects": "CREATE OR ALTER VIEW and SELECT ... INTO become CREATE OR REPLACE, so a rebuild is re-runnable.",
    "R8_table_ddl": "CREATE TABLE keeps column names and types; PRIMARY KEY, NOT NULL and other constraints are dropped "
                    "(BigQuery does not enforce keys).",
    "R9_skip_session": "SET statements (SET NOCOUNT ON) have no BigQuery equivalent and are skipped.",
    "R10_percentile_cont": "T-SQL PERCENTILE_CONT(q) WITHIN GROUP (ORDER BY x) OVER (...) is generated unchanged; BigQuery "
                           "writes the same exact median as PERCENTILE_CONT(x, q) OVER (...).",
    "R11_time_precision": "CAST(x AS TIME(0)) or DATETIME2(0) becomes TIME or DATETIME (precision is not allowed in "
                          "CAST). T-SQL also converts 'HH:MM' text to TIME, which BigQuery's cast rejects, so text is "
                          "read as COALESCE(SAFE_CAST(x AS TIME), SAFE.PARSE_TIME('%H:%M', x)).",
    "R12_concat_to_string": "T-SQL CONCAT converts numbers to text implicitly; BigQuery CONCAT needs STRING arguments, so "
                            "non-string arguments are cast to STRING (NULLs still become empty text, as in T-SQL).",
    "R13_integer_types": "CAST/TRY_CONVERT to TINYINT, SMALLINT, INT or BIT becomes INT64; sqlglot keeps TINYINT as "
                         "UTINYINT, which BigQuery does not have.",
    "R14_self_reference_guard": "An INSERT guarded by WHERE NOT EXISTS (SELECT 1 FROM <same table> ...) reads the rows "
                                "earlier INSERTs wrote. Inside one CREATE OR REPLACE the table is still the previous "
                                "build, so the guard reads a CTE of the earlier rows instead (same meaning as T-SQL); "
                                "BigQuery also needs a FROM before WHERE, so the guard row selects from a one-row table.",
    "R15_keep_staging": "DROP TABLE of a staging table is skipped and it is created only if missing: its rows are always "
                        "replaced by the load job (WRITE_TRUNCATE), or kept only when its recorded SHA-256 and row "
                        "count match the verified curated file, so the result equals T-SQL's drop and reload.",
}

_TEXT = {exp.DataType.Type.NVARCHAR, exp.DataType.Type.VARCHAR, exp.DataType.Type.NCHAR, exp.DataType.Type.CHAR,
         exp.DataType.Type.TEXT}
_INT = {exp.DataType.Type.INT, exp.DataType.Type.SMALLINT, exp.DataType.Type.TINYINT, exp.DataType.Type.UTINYINT,
        exp.DataType.Type.BIGINT, exp.DataType.Type.BIT}
_DECIMAL = {exp.DataType.Type.DECIMAL}


def _decimal_params(dt: exp.DataType) -> tuple[int, int] | None:
    vals = [int(e.this.this) if isinstance(e, exp.DataTypeParam) else int(e.name) for e in dt.expressions]
    if not vals:
        return None
    return vals[0], vals[1] if len(vals) > 1 else 0


def bq_type(dt: exp.DataType) -> str:
    """BigQuery column type for a T-SQL DDL type (parameters dropped; decimals checked to fit NUMERIC)."""
    t = dt.this
    if t in _TEXT:
        return "STRING"
    if t in _INT:
        return "INT64"
    if t in _DECIMAL or t == exp.DataType.Type.DOUBLE:
        if t == exp.DataType.Type.DOUBLE:
            return "FLOAT64"
        p, s = _decimal_params(dt) or (18, 0)
        if s > 9 or p - s > 29:
            raise EngineError(f"DECIMAL({p},{s}) does not fit BigQuery NUMERIC")
        return "NUMERIC"
    if t in (exp.DataType.Type.FLOAT,):
        return "FLOAT64"
    if t == exp.DataType.Type.DATE:
        return "DATE"
    if t in (exp.DataType.Type.DATETIME2, exp.DataType.Type.DATETIME):
        return "DATETIME"
    if t == exp.DataType.Type.TIME:
        return "TIME"
    raise EngineError(f"no BigQuery mapping for T-SQL type {dt.sql(dialect='tsql')}")


@dataclass
class Column:
    name: str
    type: str                 # BigQuery type
    scale: int | None = None  # decimal places to round to, for DECIMAL columns


@dataclass
class Step:
    kind: str                 # "query" or "skip"
    sql: str | None
    rules: list[str] = field(default_factory=list)
    note: str = ""


class BigQueryEngine:
    name = "bigquery"

    def __init__(self, project: str | None, dataset_prefix: str, location: str, maximum_bytes_billed: int,
                 client=None, connect: bool = True):
        self.project = project
        self.prefix = dataset_prefix
        self.location = location
        self.max_bytes = int(maximum_bytes_billed)
        self.tables: dict[str, list[Column]] = {}       # "dw.fact_sales" -> columns, from the Phase 4 DDL
        self.rule_log: list[dict] = []
        self.jobs: list[dict] = []
        self.client = client
        if self.client is None and connect:
            from google.cloud import bigquery           # Application Default Credentials
            self.client = bigquery.Client(project=project, location=location)

    # ---------------------------------------------------------------- naming
    def dataset(self, schema: str) -> str:
        return f"{self.prefix}{schema}"

    def table_id(self, qualified: str) -> str:
        schema, table = qualified.split(".")
        return f"{self.project}.{self.dataset(schema)}.{table}"

    def ensure_datasets(self):
        from google.cloud import bigquery
        for s in SCHEMAS:
            ds = bigquery.Dataset(f"{self.project}.{self.dataset(s)}")
            ds.location = self.location
            self.client.create_dataset(ds, exists_ok=True)

    # ---------------------------------------------------------------- translation
    def _qualify(self, node):
        if isinstance(node, exp.Table) and node.db in SCHEMAS:
            node.set("db", exp.to_identifier(self.dataset(node.db)))
            node.set("catalog", exp.to_identifier(self.project or "project", quoted=True))
        return node

    @staticmethod
    def _cast_fix(node, used: set):
        if isinstance(node, exp.National):
            used.add("R1_national_literal")
            return exp.Literal.string(node.this)
        if isinstance(node, exp.Convert) and isinstance(node.this, exp.DataType):
            # TRY_CONVERT(type, x) / CONVERT(type, x): sqlglot keeps the type in `this`; the rules below need a cast
            if node.args.get("style") is not None:
                raise EngineError(f"CONVERT with a style argument is not translated: {node.sql(dialect='tsql')}")
            cls = exp.TryCast if node.args.get("safe") else exp.Cast
            node = cls(this=node.expression.copy(), to=node.this.copy())
        if isinstance(node, exp.Concat):
            # T-SQL CONCAT converts every argument to text; BigQuery CONCAT accepts only STRING. Edited in
            # place (not copied) so the walk continues into the arguments, and string arguments are left alone.
            def is_text(a):
                return (isinstance(a, exp.Literal) and a.is_string) or isinstance(a, exp.National) or \
                    (isinstance(a, exp.Cast) and a.to.is_type(exp.DataType.Type.TEXT, *_TEXT))
            if not all(is_text(a) for a in node.expressions):
                used.add("R12_concat_to_string")
                node.set("expressions", [a if is_text(a) else
                                         exp.Cast(this=a, to=exp.DataType.build("STRING", dialect="bigquery"))
                                         for a in node.expressions])
            return node
        if isinstance(node, exp.Cast) and isinstance(node.to, exp.DataType) and node.to.this in _INT \
                and node.to.this != exp.DataType.Type.BIGINT:
            # TINYINT (parsed as UTINYINT), SMALLINT, INT and BIT have one BigQuery integer type
            used.add("R13_integer_types")
            cast = node.copy()
            cast.set("to", exp.DataType.build("INT64", dialect="bigquery"))
            return cast
        if isinstance(node, exp.Window) and isinstance(node.this, exp.WithinGroup) \
                and isinstance(node.this.this, exp.PercentileCont):
            # PERCENTILE_CONT(q) WITHIN GROUP (ORDER BY x) OVER (...) -> PERCENTILE_CONT(x, q) OVER (...)
            used.add("R10_percentile_cont")
            (ordered,) = node.this.expression.expressions
            node = node.copy()
            node.set("this", exp.Anonymous(this="PERCENTILE_CONT", expressions=[ordered.this.copy(),
                                                                                 node.this.this.this.copy()]))
            return node
        if isinstance(node, exp.Cast) and isinstance(node.to, exp.DataType) and node.to.expressions \
                and node.to.this in (exp.DataType.Type.TIME, exp.DataType.Type.DATETIME2, exp.DataType.Type.DATETIME):
            used.add("R11_time_precision")
            cast = node.copy()
            is_time = node.to.this == exp.DataType.Type.TIME
            cast.set("to", exp.DataType.build("TIME" if is_time else "DATETIME", dialect="bigquery"))
            if is_time:
                # T-SQL converts 'HH:MM' and 'HH:MM:SS' to TIME; BigQuery's cast needs seconds, so 'HH:MM'
                # (the curated transaction_time format) is parsed explicitly as well
                parse = exp.Anonymous(this="SAFE.PARSE_TIME",
                                      expressions=[exp.Literal.string("%H:%M"),
                                                   exp.Cast(this=node.this.copy(),
                                                            to=exp.DataType.build("STRING", dialect="bigquery"))])
                return exp.Coalesce(this=cast, expressions=[parse])
            return cast
        if isinstance(node, exp.Cast) and isinstance(node.to, exp.DataType) and node.to.expressions:
            if node.to.this in _DECIMAL:
                used.add("R2_decimal_cast")
                _, s = _decimal_params(node.to)
                cast = node.copy()
                cast.set("to", exp.DataType.build("NUMERIC"))
                return exp.func("ROUND", cast, exp.Literal.number(s))
            if node.to.this in _TEXT:
                used.add("R3_text_cast")
                cast = node.copy()
                cast.set("to", exp.DataType.build("STRING"))
                return cast
        return node

    def _gen(self, tree: exp.Expression, used: set) -> str:
        # Two passes: transform() does not revisit a replacement's children, so literals inside a converted
        # TRY_CONVERT are fixed on the second pass. No rule fires again on its own output.
        for _ in range(2):
            tree = tree.transform(lambda n: self._cast_fix(n, used))
        tree = tree.transform(self._qualify)
        used.add("R4_dataset_qualify")
        return tree.sql(dialect="bigquery")

    def _register_table(self, create: exp.Create) -> str:
        name = create.this.this.sql(dialect="tsql")
        cols = []
        for c in create.this.expressions:
            if isinstance(c, exp.ColumnDef):
                kind = c.args["kind"]
                scale = _decimal_params(kind)[1] if kind.this in _DECIMAL and kind.expressions else None
                cols.append(Column(c.name, bq_type(kind), scale))
        self.tables[name] = cols
        return name

    def _ctas_from_inserts(self, target: str, inserts: list[exp.Insert], used: set) -> str:
        """R5: the INSERTs into one table, as one CREATE OR REPLACE TABLE ... AS SELECT in DDL column order."""
        cols = self.tables.get(target)
        if cols is None:
            raise EngineError(f"INSERT into {target}: no CREATE TABLE seen for it")
        selects = []
        prior_cte = None
        for ins in inserts:
            names = [c.name for c in ins.this.expressions]
            source = ins.expression
            refs = [t for t in source.find_all(exp.Table) if t.sql(dialect="tsql") == target]
            if refs:
                # R14: a guard such as WHERE NOT EXISTS (SELECT 1 FROM <target> ...) reads the rows the earlier
                # INSERTs wrote. In one CREATE OR REPLACE the target is still the old table, so the reference
                # points at a CTE of the earlier rows instead; a FROM-less SELECT gets a one-row FROM.
                if not selects:
                    raise EngineError(f"INSERT into {target} reads {target} before any row is written")
                used.add("R14_self_reference_guard")
                source = source.copy()
                for t in source.find_all(exp.Table):
                    if t.sql(dialect="tsql") == target:
                        t.replace(exp.to_table("_prior"))
                if isinstance(source, exp.Select) and source.args.get("from") is None:
                    source = source.from_("(SELECT 1) AS _one")
                prior = selects[0]
                for s in selects[1:]:
                    prior = exp.union(prior, s, distinct=False)
                prior_cte = prior
            rows = ([[e for e in t.expressions] for t in source.expressions] if isinstance(source, exp.Values)
                    else None)
            sub_alias = "src"
            if rows is None:
                # SELECT, or SELECTs joined by UNION ALL: name every branch's outputs by position (c0, c1, ...)
                # so the outer SELECT can cast them to the DDL types in DDL column order
                inner = source.copy()
                col_type = {c.name: c.type for c in cols}

                def typed_null(p, i):
                    # BigQuery types a bare NULL in a subquery as INT64, which cannot then be cast to DATE or
                    # STRING; give it the target column's type where it is selected
                    if isinstance(p, exp.Null) and i < len(names):
                        return exp.Cast(this=p, to=exp.DataType.build(col_type[names[i]], dialect="bigquery"))
                    return p
                for branch in self._union_branches(inner):
                    branch.set("expressions", [exp.alias_(typed_null(p.unalias() if isinstance(p, exp.Alias) else p, i),
                                                          f"c{i}") for i, p in enumerate(branch.selects)])
                pos = {n: f"c{i}" for i, n in enumerate(names)}
                values = None
            else:
                pos, inner = None, None
                values = rows
            if values is not None:
                for row in values:
                    by_name = dict(zip(names, row))
                    selects.append(exp.select(*[self._typed(by_name.get(c.name), c) for c in cols]))
            else:
                sel = exp.select(*[self._typed(exp.column(pos[c.name], table=sub_alias) if c.name in pos else None, c)
                                   for c in cols]).from_(exp.Subquery(this=inner, alias=exp.TableAlias(
                                       this=exp.to_identifier(sub_alias))))
                selects.append(sel)
        union = selects[0]
        for s in selects[1:]:
            union = exp.union(union, s, distinct=False)
        if prior_cte is not None:
            union = exp.select("*").from_(exp.Subquery(this=union, alias=exp.TableAlias(this=exp.to_identifier("_all")))) \
                .with_("_prior", as_=prior_cte)
        target_table = exp.to_table(target)
        create = exp.Create(this=target_table, kind="TABLE", replace=True, expression=union)
        used.add("R5_insert_to_ctas")
        return self._gen(create, used)

    @staticmethod
    def _union_branches(node) -> list[exp.Select]:
        if isinstance(node, exp.SetOperation):
            return BigQueryEngine._union_branches(node.left) + BigQueryEngine._union_branches(node.right)
        if isinstance(node, exp.Subquery):
            return BigQueryEngine._union_branches(node.this)
        if isinstance(node, exp.Select):
            return [node]
        raise EngineError(f"unsupported INSERT source {type(node).__name__}")

    @staticmethod
    def _typed(value, col: Column):
        value = value if value is not None else exp.Null()
        cast = exp.Cast(this=value, to=exp.DataType.build(col.type, dialect="bigquery"))
        out = exp.func("ROUND", cast, exp.Literal.number(col.scale)) if col.scale is not None else cast
        return exp.alias_(out, col.name)

    def translate(self, tsql: str, label: str = "") -> list[Step]:
        """T-SQL batch -> BigQuery steps. INSERTs are held until the end of the batch, then combined per table."""
        steps: list[Step] = []
        pending: dict[str, list[exp.Insert]] = defaultdict(list)
        order: list[str] = []
        for stmt in sqlglot.parse(strip_comments(tsql), read="tsql"):
            if stmt is None:
                continue
            used: set = set()
            if isinstance(stmt, exp.Set) or (isinstance(stmt, exp.Command) and stmt.sql().upper().startswith("SET ")):
                steps.append(Step("skip", None, ["R9_skip_session"], "SET"))
                continue
            if isinstance(stmt, (exp.Delete, exp.TruncateTable)):
                steps.append(Step("skip", None, ["R6_skip_clear"], stmt.sql(dialect="tsql")[:80]))
                continue
            if isinstance(stmt, exp.Drop):
                targets = stmt.args.get("tables") or ([stmt.this] if stmt.this is not None else [])
                names = [t.sql(dialect="tsql") for t in targets]
                if names and all(n.startswith("stg.") for n in names):
                    steps.append(Step("skip", None, ["R15_keep_staging"], stmt.sql(dialect="tsql")[:80]))
                    continue
            if isinstance(stmt, exp.Command):
                raise EngineError(f"statement not translatable to BigQuery: {stmt.sql()[:120]}")
            if isinstance(stmt, exp.Insert):
                target = stmt.this.this.sql(dialect="tsql")
                if target not in pending:
                    order.append(target)
                pending[target].append(stmt)
                continue
            if isinstance(stmt, exp.Create) and stmt.args.get("kind") == "TABLE" and isinstance(stmt.this, exp.Schema):
                name = self._register_table(stmt)
                cols = ", ".join(f"`{c.name}` {c.type}" for c in self.tables[name])
                # Staging tables are kept so a verified load can be reused (load_csv_file); their rows are
                # always replaced by the load job. Every other table is rebuilt.
                create = "CREATE TABLE IF NOT EXISTS" if name.startswith("stg.") else "CREATE OR REPLACE TABLE"
                ddl = sqlglot.parse_one(f"{create} {name} ({cols})", read="bigquery")
                used |= {"R8_table_ddl"}
                steps.append(Step("query", self._gen(ddl, used), sorted(used)))
                continue
            if isinstance(stmt, exp.Create) and stmt.args.get("kind") == "VIEW":
                stmt.set("replace", True)
                used.add("R7_replace_objects")
            if isinstance(stmt, exp.Select) and stmt.args.get("into") is not None:
                into = stmt.args["into"].this
                stmt = stmt.copy()
                stmt.set("into", None)
                stmt = exp.Create(this=into, kind="TABLE", replace=True, expression=stmt)
                used.add("R7_replace_objects")
            steps.append(Step("query", self._gen(stmt, used), sorted(used)))
        for target in order:
            used = set()
            steps.append(Step("query", self._ctas_from_inserts(target, pending[target], used), sorted(used),
                              f"{len(pending[target])} INSERT(s) into {target}"))
        for s in steps:
            for r in s.rules:
                if r != "R4_dataset_qualify":
                    self.rule_log.append({"batch": label, "rule": r, "note": s.note})
        return steps

    # ---------------------------------------------------------------- execution
    def _job_config(self):
        from google.cloud import bigquery
        return bigquery.QueryJobConfig(maximum_bytes_billed=self.max_bytes, use_legacy_sql=False)

    def _run(self, sql: str, label: str):
        t0 = time.time()
        job = self.client.query(sql, job_config=self._job_config(), location=self.location)
        rows = job.result()
        self.jobs.append({"label": label, "statement_type": getattr(job, "statement_type", None),
                          "bytes_processed": getattr(job, "total_bytes_processed", None),
                          "bytes_billed": getattr(job, "total_bytes_billed", None),
                          "seconds": round(time.time() - t0, 2)})
        return rows

    def run_batch(self, batch: Batch) -> float:
        t0 = time.time()
        label = f"{batch.file} batch {batch.index}"
        for step in self.translate(batch.text, label):
            if step.kind != "query":
                continue
            try:
                self._run(step.sql, label)
            except Exception as e:  # noqa: BLE001
                raise EngineError(f"{label}: {e}\n--- SQL ---\n{step.sql[:1500]}") from e
        return time.time() - t0

    def query(self, tsql: str) -> pd.DataFrame:
        steps = [s for s in self.translate(tsql, "query") if s.kind == "query"]
        (step,) = steps
        rows = self._run(step.sql, "query")
        cols = [f.name for f in rows.schema]
        return pd.DataFrame([list(r.values()) for r in rows], columns=cols)

    def execute(self, tsql: str):
        for step in self.translate(tsql, "execute"):
            if step.kind == "query":
                self._run(step.sql, "execute")

    # ---------------------------------------------------------------- loads (load jobs, never streaming)
    def _load_job_config(self, table: str, columns: list[str]):
        from google.cloud import bigquery
        types = {c.name: c.type for c in self.tables[table]}
        schema = [bigquery.SchemaField(c, types[c]) for c in columns]
        return bigquery.LoadJobConfig(source_format=bigquery.SourceFormat.CSV, skip_leading_rows=1, schema=schema,
                                      write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
                                      null_marker="", allow_quoted_newlines=True, encoding="UTF-8")

    def load_csv_file(self, table: str, path, sha256: str, rows: int) -> int:
        """Load a curated CSV as it is into a staging table (all STRING, blanks as NULL).

        The table's description records the SHA-256 of the file it was loaded from. A rebuild reuses the
        table only when that SHA-256 and the row count match the verified curated file, which avoids
        uploading the same 0.3 GB again; anything else is reloaded.
        """
        import csv
        with open(path, encoding="utf-8", newline="") as fh:
            header = next(csv.reader(fh))
        if header != [c.name for c in self.tables[table]]:
            raise EngineError(f"{path}: header does not match {table} DDL")
        stamp = f"sha256={sha256}"
        try:
            existing = self.client.get_table(self.table_id(table))
            if existing.description == stamp and int(existing.num_rows) == rows \
                    and [f.name for f in existing.schema] == header:
                self.jobs.append({"label": f"reuse {table}", "statement_type": "REUSED", "bytes_processed": 0,
                                  "bytes_billed": 0, "seconds": 0})
                return rows
        except Exception:  # noqa: BLE001 - not found or not readable: load it
            pass
        t0 = time.time()
        with open(path, "rb") as fh:
            job = self.client.load_table_from_file(fh, self.table_id(table), job_config=self._load_job_config(table, header),
                                                   location=self.location)
            job.result()
        loaded = self.client.get_table(self.table_id(table))
        loaded.description = stamp
        self.client.update_table(loaded, ["description"])
        self.jobs.append({"label": f"load {table}", "statement_type": "LOAD", "bytes_processed": None,
                          "bytes_billed": 0, "seconds": round(time.time() - t0, 2)})
        return int(job.output_rows)

    def load_table(self, table: str, df: pd.DataFrame):
        """Load a small DataFrame (recon.expected) by a load job, replacing the table's rows."""
        buf = io.BytesIO(df.to_csv(index=False).encode("utf-8"))
        job = self.client.load_table_from_file(buf, self.table_id(table),
                                               job_config=self._load_job_config(table, list(df.columns)),
                                               location=self.location)
        job.result()
        self.jobs.append({"label": f"load {table}", "statement_type": "LOAD", "bytes_processed": None,
                          "bytes_billed": 0, "seconds": None})

    def close(self):
        if self.client is not None and hasattr(self.client, "close"):
            self.client.close()
