"""Phase 11: build a structurally valid PBIP from the governed Phase 1-10 assets.

Reads only governed inputs:
  powerbi/model_definition.json          column inventory (authoritative)
  powerbi/dax/measures_tmdl.tmdl        92 DAX measures (authoritative)
  powerbi/power_query/*.pq               Power Query M + column types (authoritative)
  powerbi/brightwater_theme.json         report theme
  reports/phase10/forecast_*.csv         Phase 10 forecasts (read-only copies in powerbi/forecast_data)
  powerbi/dq_data/*.csv                  Phase 3 and Phase 9 data-quality extracts (page 9)
  reports/phase3/lineage.json            governed quarantine counts (page 9)

Every write goes through assert_report_scope and stays inside powerbi/<project>/, with two
named exceptions: removing the stale powerbi/<project>.pbip folder, and deriving
powerbi/dq_data/dq_quarantine_by_table.csv from lineage.json. The output is deterministic:
the same inputs rebuild byte-identical files, which the release checks rely on.

Writes a PBIP that satisfies the published schemas:
  fabric/pbip/pbipProperties/1.0.0
  fabric/item/semanticModel/definitionProperties/1.0.0
  fabric/item/report/definitionProperties/2.0.0
  fabric/item/report/definition/{report,versionMetadata,pagesMetadata,page,visualContainer}/1.x
"""
from __future__ import annotations

import csv
import hashlib
import json
import pathlib
import re
import shutil
import unicodedata

ROOT = pathlib.Path(__file__).resolve().parents[1]
PBI = ROOT / "powerbi"

NAME = "Brightwater_Executive_Dashboard"
# Governed sources keep the original name; Desktop's PBIP schema rejects this output table name.
MEASURE_TABLE = "_Measures"
PBIP_ROOT = PBI / NAME
REPORT = PBIP_ROOT / f"{NAME}.Report"
MODEL = PBIP_ROOT / f"{NAME}.SemanticModel"
REFERENCE_REPORT = ROOT / "tmp" / "pbir_reference" / "reference.Report"

SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item"
PBIP_SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/pbip/pbipProperties/1.0.0/schema.json"
PLATFORM_SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/gitIntegration/platformProperties/2.0.0/schema.json"
REPORT_LOGICAL_ID = "2655a729-7dc0-4eae-9882-f0b8f3b44fc1"
MODEL_LOGICAL_ID = "1116ce4e-47ef-48ca-af26-cd18dea4aedc"

# Storytelling-pass colour roles, taken from powerbi/brightwater_theme.json dataColors
# so every page uses the same accent for the same story role (req. 4).
COLOR_CLUSTER = "#2A78D6"   # dataColors[0]: investigated cluster / current-year accent
COLOR_CONTROL = "#8F8D87"   # dataColors[4]: matched control / other-suppliers grey
COLOR_VOLTIX = "#EB6834"    # dataColors[1]: Voltix supplier accent
COLOR_PY = "#9CC3F0"        # dataColors[7]: prior-year muted

PAGE_W, PAGE_H = 1280, 720

# Absolute folder parameters for the CSV route. Forward slashes avoid M backslash escaping.
FOLDERS = {
    "ModelFolder": (ROOT / "data" / "powerbi").as_posix(),
    "AnalyticsFolder": (PBI / "data").as_posix(),
    "ForecastFolder": (PBI / "forecast_data").as_posix(),
    # Read-only copies of the Phase 3 and Phase 9 data-quality extracts. Kept out of
    # powerbi/data so the hash-protected analytics folder stays exactly as governed.
    "DqFolder": (PBI / "dq_data").as_posix(),
}

# store_group is a DAX calculated column, not a Power Query column (Formula.Firewall).
CALC_COLUMNS = {
    ("Store", "store_group"): (
        'VAR _g = LOOKUPVALUE ( p6_store_groups[store_group], p6_store_groups[store_id], Store[store_id] )\n'
        'RETURN IF ( ISBLANK ( _g ), "Unknown", _g )'
    ),
}

# sort_by from powerbi/model_definition.json
SORT_BY = {
    "Date[month_name]": "calendar_month",
    "Date[day_name]": "day_of_week",
    "Date[period_label]": "retail_year",
    "Date[retail_week_label]": "retail_week_key",
    "p5_revenue_bridge[step]": "sort_order",
    "p6_driver_attribution[component]": "sort_order",
}

GENERATED_QUERY_COLUMNS = {
    "forecast_weekly": {"date_key": "int64"},
    "p5_revenue_bridge": {"sort_order": "int64"},
}
HIDE_GENERATED_COLUMNS = {("p5_revenue_bridge", "sort_order")}

HIDE_KEY_COLUMNS = True

# Date.tmdl is not marked with table-level dataCategory: Time. Date[date_key] is the
# unique, nonblank one-side column for the core date relationships; calendar_date retains
# the unknown-date blank and is only an additional forecast relationship endpoint.
TABLE_KEY_COLUMNS = {"Date": "date_key"}

MAX_OBJECT_NAME_LENGTH = 100
INVALID_OBJECT_NAME_CHARS = frozenset('<>:"/\\|?*[]')


# --------------------------------------------------------------------------- helpers
def q(name: str) -> str:
    """TMDL object name, single-quoted when it needs to be."""
    if re.search(r"[.'=:\s]", name):
        return "'" + name.replace("'", "''") + "'"
    return name


def qm(name: str) -> str:
    """Measure names are always quoted, matching the governed measures_tmdl.tmdl."""
    return "'" + name.replace("'", "''") + "'"


def assert_report_scope(path: pathlib.Path) -> pathlib.Path:
    """Refuse to touch anything outside the PBIP project directory.

    This builder owns the report only. Phase 7 outputs under powerbi/dax/ and reports/ are
    frozen and are produced by src/powerbi/run_phase7.py; writing them from here silently
    invalidated a protected hash group once already.
    """
    resolved = pathlib.Path(path).resolve()
    try:
        resolved.relative_to(PBIP_ROOT.resolve())
    except ValueError:
        raise SystemExit(
            f"refusing to write outside the PBIP report directory: {resolved}\n"
            f"allowed root: {PBIP_ROOT.resolve()}")
    return resolved


def write(path: pathlib.Path, text: str) -> None:
    """Write UTF-8 text with LF endings to a path inside the PBIP project."""
    target = assert_report_scope(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    # UTF-8, no BOM, LF - the documented requirement for PBIP files edited externally.
    target.write_bytes(text.replace("\r\n", "\n").encode("utf-8"))


def remove_tree(path: pathlib.Path) -> None:
    """Delete a directory inside the PBIP project only."""
    target = assert_report_scope(path)
    if target.is_dir():
        shutil.rmtree(target)


def write_json(path: pathlib.Path, payload: dict) -> None:
    """Write a JSON document with 2-space indent and a trailing newline, as Desktop does."""
    write(path, json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


def tmdl_expression_lines(declaration: str, expression: str) -> list[str]:
    """Serialize a default-property expression without folding multiline DAX into its header."""
    expr_lines = expression.split("\n")
    if len(expr_lines) == 1:
        return [f"{declaration} {expr_lines[0]}"]
    return [declaration, *(f"\t\t\t{line}" if line.strip() else "" for line in expr_lines)]


def validate_output_object_names(
    inventory: dict[str, list[str]], measures: list[dict]
) -> None:
    """Reject names that cannot be represented safely in this PBIP/TMDL output."""
    problems: list[str] = []

    def validate_name(name: str, context: str) -> None:
        if not name or name != name.strip():
            problems.append(f"{context}: empty or leading/trailing whitespace in {name!r}")
        if len(name) > MAX_OBJECT_NAME_LENGTH:
            problems.append(f"{context}: name exceeds {MAX_OBJECT_NAME_LENGTH} characters: {name!r}")
        invalid = sorted({char for char in name
                          if unicodedata.category(char) == "Cc" or char in INVALID_OBJECT_NAME_CHARS})
        if invalid:
            problems.append(f"{context}: disallowed characters in {name!r}: {invalid!r}")

    output_tables = list(inventory) + [MEASURE_TABLE]
    table_names: dict[str, str] = {}
    for table in output_tables:
        validate_name(table, "table")
        if table.casefold() == "measures":
            problems.append(f"table: reserved name {table!r} is not allowed in PBIP output")
        previous = table_names.get(table.casefold())
        if previous is not None:
            problems.append(f"table: case-insensitive duplicate names {previous!r} and {table!r}")
        table_names[table.casefold()] = table

    for table, columns in inventory.items():
        output_columns = list(columns)
        if table == MEASURE_TABLE:
            output_columns.append(MEASURE_TABLE)
        seen_columns: dict[str, str] = {}
        for column in output_columns:
            validate_name(column, f"{table} column")
            previous = seen_columns.get(column.casefold())
            if previous is not None:
                problems.append(
                    f"{table}: case-insensitive duplicate columns {previous!r} and {column!r}"
                )
            seen_columns[column.casefold()] = column

    measure_names: dict[str, str] = {}
    measure_columns = {column.casefold(): column for column in (inventory.get(MEASURE_TABLE, []) + [MEASURE_TABLE])}
    for measure in measures:
        name = measure["name"]
        validate_name(name, f"{MEASURE_TABLE} measure")
        previous = measure_names.get(name.casefold())
        if previous is not None:
            problems.append(
                f"{MEASURE_TABLE}: case-insensitive duplicate measures {previous!r} and {name!r}"
            )
        measure_names[name.casefold()] = name
        if name.casefold() in measure_columns:
            problems.append(
                f"{MEASURE_TABLE}: measure {name!r} collides with column "
                f"{measure_columns[name.casefold()]!r}"
            )

    if problems:
        raise ValueError("invalid output object names:\n  " + "\n  ".join(problems))


_MEASURE_TABLE_REF = re.compile(
    r'(?P<literal>"(?:[^\"]|"")*"|//[^\r\n]*|--[^\r\n]*|/\*[\s\S]*?\*/)|'
    r"(?P<table>'Measures'|(?<![\w'])Measures)(?=\s*\[)"
)


def rewrite_measure_table_qualifiers(expression: str) -> tuple[str, int]:
    """Map only DAX table qualifiers, leaving strings and comments untouched."""
    rewrites = 0

    def replace(match: re.Match) -> str:
        nonlocal rewrites
        if match.group("literal") is not None:
            return match.group("literal")
        rewrites += 1
        return f"'{MEASURE_TABLE}'"

    return _MEASURE_TABLE_REF.sub(replace, expression), rewrites


# --------------------------------------------------------------------------- inputs
MEASURE_HDR = re.compile(r"^\t\tmeasure\s+(?P<name>'(?:[^']|'')+'|\S+)\s*=\s?(?P<inline>.*)$")
DESCRIPTION = re.compile(r"^\t\t///\s?(?P<text>.*)$")


def load_measure_defs() -> list[dict]:
    """Parse the governed TMDL measure script into structured measure definitions.

    Layout of the governed file: descriptions (///) precede the measure they document;
    measure bodies are `measure NAME = <inline>` followed by either 3-tab property
    lines (formatString / displayFolder) or, for multi-line DAX, 4-tab expression
    continuation lines.
    """
    lines = (PBI / "dax" / "measures_tmdl.tmdl").read_text(encoding="utf-8").split("\n")
    start = next(i for i, ln in enumerate(lines) if MEASURE_HDR.match(ln))
    end = next(i for i, ln in enumerate(lines) if re.match(r"^\t\tcolumn Measures", ln))

    measures: list[dict] = []
    pending_desc: list[str] = []
    current: dict | None = None

    for ln in lines[start:end]:
        d = DESCRIPTION.match(ln)
        if d:
            pending_desc.append(d.group("text").rstrip())
            continue

        h = MEASURE_HDR.match(ln)
        if h:
            raw = h.group("name")
            name = raw[1:-1].replace("''", "'") if raw.startswith("'") else raw
            current = {
                "name": name,
                "description": pending_desc,
                "inline": h.group("inline"),
                "expr_lines": [],
                "props": {},
            }
            measures.append(current)
            pending_desc = []
            continue

        if current is None or not ln.strip():
            continue

        indent = len(ln) - len(ln.lstrip("\t"))
        stripped = ln.strip()
        if indent == 3 and stripped.startswith(("formatString:", "displayFolder:")):
            key, _, val = stripped.partition(":")
            current["props"][key] = val.strip()
        else:
            current["expr_lines"].append(ln)

    for m in measures:
        if m["inline"]:
            expr = [m["inline"]] + m["expr_lines"]
        else:
            expr = m["expr_lines"]
        while expr and not expr[0].strip():
            expr.pop(0)
        while expr and not expr[-1].strip():
            expr.pop()
        base = min((len(x) - len(x.lstrip("\t ")) for x in expr), default=0)
        m["expression"] = "\n".join(
            (x[base:] if x.strip() else "") for x in expr
        )
        del m["inline"], m["expr_lines"]

    return measures


TRANSFORM = re.compile(
    r"Table\.TransformColumnTypes\(.*?\{\s*(?P<body>.*?)\s*\}\s*,\s*\"en-US\"\)", re.S)
PAIR = re.compile(r'\{\"(?P<col>[^\"]+)\",\s*(?P<ty>type\s+\w+|\w+\.\w+)\}')
TYPE_MAP = {
    "Int64.Type": "int64", "Currency.Type": "decimal", "Currency.EUR.Type": "decimal",
    "type date": "dateTime", "type dateTime": "dateTime", "type number": "double",
    "type text": "string", "type logical": "boolean", "type duration": "double",
}


def load_queries() -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    """Return (M expression per table stem, column types per table stem) from governed .pq files."""
    bodies: dict[str, str] = {}
    types: dict[str, dict[str, str]] = {}
    for f in sorted((PBI / "power_query").glob("*.pq")):
        text = f.read_text(encoding="utf-8")
        stem = re.sub(r"\.(csv|sql_server)$", "", f.stem)
        if stem in bodies:
            continue  # first file wins; the .csv route is the chosen source
        m = TRANSFORM.search(text)
        if not m:
            continue
        for col, ty in PAIR.findall(m.group("body")):
            types.setdefault(stem, {})[col] = TYPE_MAP.get(ty, ty)
        # M body: everything from the first `let` onwards; drop the // documentation header.
        idx = text.index("\nlet")
        bodies[stem] = text[idx + 1:].rstrip()
    bridge = bodies.get("p5_revenue_bridge")
    if bridge is None or not bridge.endswith("\nin\n    Typed"):
        raise ValueError("p5_revenue_bridge M query must end in the Typed step")
    bridge = bridge[:-len("\nin\n    Typed")].rstrip()
    bodies["p5_revenue_bridge"] = (
        bridge + ',\n'
        '    WithSortOrder = Table.AddIndexColumn(Typed, "sort_order", 1, 1, Int64.Type)\n'
        "in\n"
        "    WithSortOrder"
    )
    types.setdefault("p5_revenue_bridge", {})["sort_order"] = "int64"
    return bodies, types


FORECAST_TYPES = {
    "forecast_weekly": {
        "horizon_step": "int64", "retail_year": "int64", "retail_week": "int64",
        "week_start_date": "dateTime", "date_key": "int64",
        "model": "string", "point_forecast": "double",
    },
    "forecast_intervals": {
        "week_start_date": "dateTime", "model": "string", "coverage": "double",
        "lower": "double", "upper": "double",
    },
    "forecast_model_comparison": {
        "model": "string", "family": "string", "origins": "int64", "mean_mae": "double",
        "mean_rmse": "double", "mean_wape": "double", "mean_mase": "double", "mean_bias": "double",
    },
    "forecast_selected_model": {"field": "string", "value": "string"},
}

DERIVED_FORECAST_COLUMNS = {"forecast_weekly": {"date_key": "int64"}}

# Phase 3 and Phase 9 data-quality extracts, copied read-only into powerbi/dq_data.
# Standalone by design: no relationships, so the page reports what each DQ artefact
# says without touching the 15 governed relationships or any existing table.
DQ_TYPES = {
    "dq_rule_results": {
        "rule_id": "string", "table": "string", "dimension": "string", "check": "string",
        "severity": "string", "treatment": "string", "rows_checked": "int64",
        "rows_failed": "int64", "revenue_affected": "decimal", "evidence": "string",
        "status": "string", "failure_rate_pct": "double", "rationale": "string",
    },
    "dq_issue_log": {
        "rule_id": "string", "table_name": "string", "row_key": "string",
        "column_name": "string", "raw_value": "string", "new_value": "string",
        "action": "string", "severity": "string",
    },
    "curated_validation": {
        "group": "string", "check": "string", "status": "string", "value": "string",
    },
    "kpi_reconciliation": {
        "kpi": "string", "raw_as_reported": "double", "clean_main_only": "double",
        "clean_complete": "double", "change_raw_to_complete": "double",
        "change_pct": "double",
    },
    "dq_store_week_health": {
        "store_id": "string", "retail_week_key": "int64", "t": "int64",
        "trading_days": "int64", "days_asat": "int64", "lines": "int64",
        "lines_asat": "int64", "lines_trailing_median": "double",
        "C2_ontime_share": "double", "n_dup": "int64", "n_price": "int64",
        "n_discount": "int64", "n_quarantine": "int64", "n_missing_snapshots": "int64",
        "snapshot_rows": "int64", "lines_unknown_product": "int64",
        "lines_dq_flagged": "int64", "returns_unlinked": "int64",
        # lines_expected holds half values (e.g. 1077.5); Int64 would round them silently.
        "lines_expected": "double", "lines_missing": "int64",
        "C1": "boolean", "C2": "boolean", "C3": "boolean", "C4": "boolean",
        "C5": "boolean", "C6": "boolean", "C7": "boolean", "C8": "boolean",
        "C9": "boolean", "C10": "boolean", "C11": "boolean",
        "dq_sales_status": "string", "dq_inventory_status": "string",
        # Text, not a count: it lists the failed checks, e.g. "C10 Quarantined lines".
        # Typing it Int64 raised 794 load errors, one per store-week with a failed check.
        "dq_checks_failed": "string",
    },
    "dq_check_catalogue": {
        "check_id": "string", "severity": "string", "check": "string",
        "description": "string", "tolerance": "string",
        "blocks_business_alerts": "string",
    },
    # Derived by derive_dq_quarantine_by_table() from reports/phase3/lineage.json.
    "dq_quarantine_by_table": {"table": "string", "rows_quarantined": "int64"},
}

def is_identifier_column(column: str) -> bool:
    """Keys, ids, years and the week index are labels, not quantities: 202527, not 202,527."""
    return column.endswith(("_key", "_id")) or "year" in column or column == "t"


def dq_column_formats(table: str) -> dict[str, str]:
    """Thousands separators for every numeric DQ amount; plain digits for identifier columns."""
    pattern = {"int64": "#,0", "double": "#,0.00", "decimal": "#,0.00"}
    return {column: "0" if is_identifier_column(column) else pattern[data_type]
            for column, data_type in DQ_TYPES[table].items() if data_type in pattern}


# The governed quarantine count is recorded in lineage.json (quarantine_rows), not in any CSV
# column, so it is derived into one small extract that the page can Sum without DAX.
LINEAGE_JSON = ROOT / "reports" / "phase3" / "lineage.json"
DQ_QUARANTINE_CSV = PBI / "dq_data" / "dq_quarantine_by_table.csv"
_CONSERVATION = re.compile(r"^([\d,]+) = ([\d,]+) \+ ([\d,]+)$")


def derive_dq_quarantine_by_table() -> int:
    """Write dq_quarantine_by_table.csv (table, rows_quarantined) from lineage.json; return the total.

    Besides the stale .pbip removal in main(), this is the builder's only write outside
    PBIP_ROOT. The target is one named file in powerbi/dq_data, checked here, so
    assert_report_scope still refuses every other path, including all Phase 7 outputs.
    """
    target = DQ_QUARANTINE_CSV.resolve()
    if target.parent != (PBI / "dq_data").resolve() or target.name != "dq_quarantine_by_table.csv":
        raise SystemExit(f"refusing to derive the quarantine extract at an unexpected path: {target}")
    counts = json.loads(LINEAGE_JSON.read_text(encoding="utf-8"))["quarantine_rows"]

    # Cross-check against the row-conservation checks in curated_validation, so the card can
    # never disagree with the governed "raw = curated + quarantined" evidence.
    conserved: dict[str, int] = {}
    with open(PBI / "dq_data" / "curated_validation.csv", encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            if row["group"] == "row conservation":
                match = _CONSERVATION.match(row["value"])
                if match:
                    conserved[row["check"].split(":")[0]] = int(match.group(3).replace(",", ""))
    for table, rows in counts.items():
        if conserved.get(table, 0) != int(rows):
            raise ValueError(f"lineage.json quarantine_rows[{table}]={rows} disagrees with "
                             f"curated_validation row conservation ({conserved.get(table)})")

    lines = ["table,rows_quarantined"] + [f"{table},{int(counts[table])}" for table in sorted(counts)]
    target.write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
    return sum(int(value) for value in counts.values())


def csv_route_m(stem: str, types: dict[str, str], folder_parameter: str) -> str:
    """M for a CSV extract read straight from a folder parameter, with an explicit type step."""
    mtype = {"int64": "Int64.Type", "double": "type number",
             "string": "type text", "dateTime": "type date", "decimal": "Currency.Type",
             "boolean": "type logical"}
    typed = ", ".join(f'{{"{column}", {mtype[data_type]}}}'
                      for column, data_type in types.items())
    return (
        "let\n"
        f'    Source = Csv.Document(File.Contents({folder_parameter} & "\\{stem}.csv"),\n'
        '                          [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),\n'
        "    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),\n"
        "    Typed = Table.TransformColumnTypes(Promoted, {\n"
        f"        {typed}\n"
        '    }, "en-US")\n'
        "in\n"
        "    Typed"
    )


def dq_m(stem: str) -> str:
    """M for the six data-quality extracts (CSV route, read-only copies)."""
    return csv_route_m(stem, DQ_TYPES[stem], "DqFolder")


def forecast_m(stem: str) -> str:
    """M for the four Phase 10 forecast extracts (CSV route, read-only copies)."""
    mtype = {"int64": "Int64.Type", "double": "type number",
             "string": "type text", "dateTime": "type date", "decimal": "Currency.Type"}
    typed_columns = {
        column: data_type for column, data_type in FORECAST_TYPES[stem].items()
        if column not in DERIVED_FORECAST_COLUMNS.get(stem, {})
    }
    typed = ", ".join(
        f'{{"{column}", {mtype[data_type]}}}'
        for column, data_type in typed_columns.items()
    )
    query = (
        f"let\n"
        f'    Source = Csv.Document(File.Contents(ForecastFolder & "\\{stem}.csv"),\n'
        f'                          [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),\n'
        f"    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),\n"
        f"    Typed = Table.TransformColumnTypes(Promoted, {{\n"
        f"        {typed}\n"
        f'    }}, "en-US")\n'
    )
    if stem == "forecast_weekly":
        # The Date unknown row has a blank calendar_date, so this relationship uses its
        # complete, deterministic date_key instead of Date[calendar_date].
        query = query.rstrip("\n") + ",\n"
        query += (
            '    WithDateKey = Table.AddColumn(Typed, "date_key", '
            'each Date.Year([week_start_date]) * 10000 + Date.Month([week_start_date]) * 100 '
            '+ Date.Day([week_start_date]), Int64.Type)\n'
            "in\n"
            "    WithDateKey"
        )
    else:
        query += "in\n    Typed"
    return query


# --------------------------------------------------------------------------- relationships
# powerbi/model_definition.json uses the *business* vocabulary. TMDL requires the
# CrossFilteringBehavior / RelationshipEndCardinality enum members. Mapping is explicit and
# fails loudly on an unknown value so a governed change can never silently emit a bad enum.
# Authority: TMDL object-properties reference (crossFilteringBehavior, relationshipEndCardinality)
CROSS_FILTER_TMDL = {
    "single": "oneDirection",
    "one-direction": "oneDirection",
    "both": "bothDirections",
    "both-directions": "bothDirections",
    "automatic": "automatic",
}
CARDINALITY_TMDL = {
    "many-to-one": ("many", "one"),
    "one-to-many": ("one", "many"),
    "many-to-many": ("many", "many"),
    "one-to-one": ("one", "one"),
}


def _enum(mapping: dict, value: str, kind: str, where: str) -> str:
    try:
        return mapping[value]
    except KeyError:
        raise SystemExit(
            f"{where}: unknown {kind} {value!r}; expected one of {sorted(mapping)}"
        ) from None


def relationships() -> list[dict]:
    """12 governed star relationships + Phase 10 forecast relationships.

    forecast_model_comparison[model] is the unique side; forecast_weekly[model] is not
    (13 rows, 1 model), so the relationship runs weekly -> comparison.
    """
    md = json.loads((PBI / "model_definition.json").read_text(encoding="utf-8"))
    out = []
    for r in md["relationships"]:
        ft, _, rest = r["from"].partition("[")
        fc = rest.rstrip("]")
        tt, _, rest = r["to"].partition("[")
        tc = rest.rstrip("]")
        where = f"model_definition.json relationship {ft}[{fc}]->{tt}[{tc}]"
        from_card, to_card = _enum(CARDINALITY_TMDL, r["cardinality"], "cardinality", where)
        out.append({
            "name": f"{ft}_{fc}_to_{tt}_{tc}", "fromTable": ft, "fromColumn": fc,
            "toTable": tt, "toColumn": tc,
            "fromCardinality": from_card, "toCardinality": to_card,
            "crossFilteringBehavior": _enum(CROSS_FILTER_TMDL, r["cross_filter"],
                                            "crossFilteringBehavior", where),
            "isActive": r["active"],
        })
    for name, ft, fc, tt, tc in [
        # model_definition.json still names Date[calendar_date], but its unknown row is blank.
        ("forecast_weekly_to_Date", "forecast_weekly", "date_key", "Date", "date_key"),
        ("forecast_intervals_to_forecast_weekly", "forecast_intervals", "week_start_date",
         "forecast_weekly", "week_start_date"),
        ("forecast_weekly_to_forecast_model_comparison", "forecast_weekly", "model",
         "forecast_model_comparison", "model"),
    ]:
        out.append({
            "name": name, "fromTable": ft, "fromColumn": fc, "toTable": tt, "toColumn": tc,
            "fromCardinality": "many", "toCardinality": "one",
            "crossFilteringBehavior": "oneDirection", "isActive": True,
        })
    return out


def render_relationships_tmdl(rels: list[dict]) -> str:
    """relationships.tmdl text for the governed relationships, in their declared order."""
    rel_lines: list[str] = []
    for relationship in rels:
        rel_lines += [
            f"relationship {q(relationship['name'])}",
            f"\tfromColumn: {relationship['fromTable']}.{relationship['fromColumn']}",
            f"\ttoColumn: {relationship['toTable']}.{relationship['toColumn']}",
            f"\tfromCardinality: {relationship['fromCardinality']}",
            f"\ttoCardinality: {relationship['toCardinality']}",
            f"\tcrossFilteringBehavior: {relationship['crossFilteringBehavior']}",
            f"\tisActive: {str(relationship['isActive']).lower()}",
            "",
        ]
    return "\n".join(rel_lines)


# --------------------------------------------------------------------------- semantic model
def table_inventory() -> dict[str, list[str]]:
    """Table to column list: model_definition.json first, then forecast and DQ extracts."""
    md = json.loads((PBI / "model_definition.json").read_text(encoding="utf-8"))
    inv = {t: list(spec["columns"]) for t, spec in md["star_schema_tables"].items()}
    inv.update({t: list(spec["columns"]) for t, spec in md["phase6_tables"].items()})
    for stem, cols in FORECAST_TYPES.items():
        inv[stem] = list(cols)
    for stem, cols in DQ_TYPES.items():
        inv[stem] = list(cols)
    for table, generated in GENERATED_QUERY_COLUMNS.items():
        inv[table].extend(column for column in generated if column not in inv[table])
    return inv


def relationship_key_columns(rels: list[dict], inventory: dict[str, list[str]]) -> dict[str, str]:
    """Choose one key column per table, rejecting unresolved multiple one-side candidates."""
    candidates: dict[str, set[str]] = {}
    for relationship in rels:
        if relationship["fromCardinality"] == "one":
            candidates.setdefault(relationship["fromTable"], set()).add(relationship["fromColumn"])
        if relationship["toCardinality"] == "one":
            candidates.setdefault(relationship["toTable"], set()).add(relationship["toColumn"])

    selected: dict[str, str] = {}
    for table, columns in candidates.items():
        preferred = TABLE_KEY_COLUMNS.get(table)
        if preferred is None:
            if len(columns) != 1:
                raise ValueError(
                    f"{table}: multiple relationship one-side columns {sorted(columns)}; "
                    "select one table key explicitly"
                )
            preferred = next(iter(columns))
        if preferred not in columns:
            raise ValueError(
                f"{table}: configured key {preferred!r} is not a relationship one-side column"
            )
        if preferred not in inventory.get(table, []):
            raise ValueError(f"{table}: configured key {preferred!r} is not a table column")
        selected[table] = preferred

    unexpected = set(TABLE_KEY_COLUMNS) - set(candidates)
    if unexpected:
        raise ValueError(f"configured table keys have no one-side relationship: {sorted(unexpected)}")
    return selected


def render_table_tmdl(
    table: str,
    cols: list[str],
    body: str,
    types: dict[str, str],
    key_column: str | None,
    formats: dict[str, str] | None = None,
) -> tuple[str, list[str]]:
    """Render one table and report columns lacking a known source data type.

    `formats` adds a column formatString; only the page 9 DQ tables pass it, so every other
    table renders exactly as before.
    """
    untyped: list[str] = []
    out = [f"table {q(table)}", ""]
    for col in cols:
        key = (table, col)
        if key in CALC_COLUMNS:
            out.extend(tmdl_expression_lines(f"\tcolumn {q(col)} =", CALC_COLUMNS[key]))
            out.append("\t\tdataType: string")
            out.append("\t\tsummarizeBy: none")
        else:
            out.append(f"\tcolumn {q(col)}")
            if col not in types:
                untyped.append(f"{table}[{col}]")
            data_type = types.get(col, "string")
            out.append(f"\t\tdataType: {data_type}")
            if formats and col in formats:
                out.append(f'\t\tformatString: "{formats[col]}"')
            if data_type != "string":
                out.append("\t\tsummarizeBy: none")
            out.append(f"\t\tsourceColumn: {col}")
        if col == key_column:
            out.append("\t\tisKey")
        if (col.endswith("_key") and HIDE_KEY_COLUMNS) or key in HIDE_GENERATED_COLUMNS:
            out.append("\t\tisHidden")
        for owner, target in SORT_BY.items():
            if owner == f"{table}[{col}]":
                out.append(f"\t\tsortByColumn: {target}")
        out.append("")
    query = body.replace("\n", "\n\t\t\t")
    out.append(f"\tpartition {q(table)} = m")
    out.append("\t\tmode: import")
    out.append("\t\tsource =")
    out.append("\t\t\t" + query)
    out.append("")
    return "\n".join(out), untyped


def render_measures_tmdl(measures: list[dict]) -> str:
    """Render governed measures in the Desktop-safe output table, preserving their definitions."""
    mlines = [f"table {q(MEASURE_TABLE)}", ""]
    for meas in measures:
        for description in meas["description"]:
            mlines.append(f"\t/// {description}")
        expression, _ = rewrite_measure_table_qualifiers(meas["expression"])
        mlines.extend(tmdl_expression_lines(
            f"\tmeasure {qm(meas['name'])} =", expression
        ))
        for key in ("formatString", "displayFolder"):
            if key in meas["props"]:
                mlines.append(f"\t\t{key}: {meas['props'][key]}")
        mlines.append("")
    mlines += [
        f"\tcolumn {q(MEASURE_TABLE)}",
        "\t\tdataType: string",
        "\t\tisHidden",
        f"\t\tsourceColumn: [{MEASURE_TABLE}]",
        "",
        f"\tpartition {q(MEASURE_TABLE)} = calculated",
        "\t\tmode: import",
        f'\t\tsource = ROW ( "{MEASURE_TABLE}", "" )',
        "",
    ]
    return "\n".join(mlines)


def render_model_tmdl(inventory: dict[str, list[str]]) -> str:
    """model.tmdl: culture, auto date/time off, and a fixed table order for stable output."""
    model_lines = [f"model {NAME}", "\tculture: en-GB",
                   "\tdefaultPowerBIDataSourceVersion: powerBI_V3",
                   "\tannotation __PBI_TimeIntelligenceEnabled = 0", ""]
    model_lines += [f"ref table {q(table)}" for table in inventory]
    model_lines += [f"ref table {q(MEASURE_TABLE)}", ""]
    return "\n".join(model_lines)


def regenerate_table_tmdl(table: str) -> dict:
    """Regenerate a single table TMDL file without rebuilding the semantic model or report."""
    inventory = table_inventory()
    bodies, types = load_queries()
    for stem in FORECAST_TYPES:
        bodies[stem] = forecast_m(stem)
        types[stem] = dict(FORECAST_TYPES[stem])
    for stem in DQ_TYPES:
        bodies[stem] = dq_m(stem)
        types[stem] = dict(DQ_TYPES[stem])
    if table not in inventory or table not in bodies:
        raise ValueError(f"no generated table/query named {table!r}")
    rels = relationships()
    selected_keys = relationship_key_columns(rels, inventory)
    rendered, untyped = render_table_tmdl(
        table, inventory[table], bodies[table], types.get(table, {}),
        selected_keys.get(table),
    )
    if untyped:
        raise ValueError(f"{table}: missing source data types for {untyped}")
    write(MODEL / "definition" / "tables" / f"{table}.tmdl", rendered)
    return {"table": table, "key_column": selected_keys.get(table), "untyped_columns": untyped}


def regenerate_forecast_date_relationship() -> dict:
    """Regenerate only forecast_weekly and its relationship after adding the date key."""
    table_result = regenerate_table_tmdl("forecast_weekly")
    rels = relationships()
    write(MODEL / "definition" / "relationships.tmdl", render_relationships_tmdl(rels))
    return {
        **table_result,
        "relationships": len(rels),
        "model_definition_deviation": {
            "relationship": "forecast_weekly_to_Date",
            "model_definition_to": "Date[calendar_date]",
            "pbip_output_to": "Date[date_key]",
            "reason": "the governed Date unknown row has a blank calendar_date",
        },
    }


def build_semantic_model() -> dict:
    """Regenerate the whole SemanticModel definition folder; return build statistics."""
    inv = table_inventory()
    bodies, types = load_queries()
    measures = load_measure_defs()
    validate_output_object_names(inv, measures)
    measure_table_qualifier_rewrites = sum(
        rewrite_measure_table_qualifiers(measure["expression"])[1] for measure in measures
    )

    for stem in FORECAST_TYPES:
        bodies[stem] = forecast_m(stem)
        types[stem] = dict(FORECAST_TYPES[stem])

    for stem in DQ_TYPES:
        bodies[stem] = dq_m(stem)
        types[stem] = dict(DQ_TYPES[stem])

    rels = relationships()
    selected_keys = relationship_key_columns(rels, inv)

    definition = MODEL / "definition"
    if definition.exists():
        remove_tree(definition)
    (definition / "tables").mkdir(parents=True, exist_ok=True)

    # ---- database.tmdl. `database` is a NAMED object: the declaration needs a name.
    write(definition / "database.tmdl", f"database {NAME}\n\tcompatibilityLevel: 1567\n")

    # ---- model.tmdl : model properties + deterministic table ordering.
    # `model` is likewise a NAMED object, so the declaration must carry a name.
    write(definition / "model.tmdl", render_model_tmdl(inv))

    # ---- expressions.tmdl : the three CSV-route folder parameters
    expr = []
    for name, value in FOLDERS.items():
        expr.append(
            f'expression {name} = "{value}" '
            "meta [IsParameterQuery=true, Type=\"Text\", IsParameterQueryRequired=true]\n"
        )
    write(definition / "expressions.tmdl", "\n".join(expr))

    # ---- relationships.tmdl
    write(definition / "relationships.tmdl", render_relationships_tmdl(rels))

    # ---- tables
    untyped: list[str] = []
    for table, cols in inv.items():
        if table not in bodies:
            raise ValueError(f"no Power Query for table {table}")
        rendered, table_untyped = render_table_tmdl(
            table, cols, bodies[table], types.get(table, {}),
            selected_keys.get(table),
            formats=dq_column_formats(table) if table in DQ_TYPES else None,
        )
        untyped.extend(table_untyped)
        write(definition / "tables" / f"{table}.tmdl", rendered)

    # The governed source retains its Measures container name; PBIP uses the mapped output name.
    write(definition / "tables" / f"{MEASURE_TABLE}.tmdl", render_measures_tmdl(measures))

    write(MODEL / "definition.pbism", json.dumps({
        "$schema": f"{SCHEMA}/semanticModel/definitionProperties/1.0.0/schema.json",
        "version": "4.0",
    }, indent=2) + "\n")

    write(MODEL / ".gitignore", "**/.pbi/localSettings.json\n**/.pbi/cache.abf\n")
    write_json(MODEL / ".platform", {
        "$schema": PLATFORM_SCHEMA,
        "metadata": {"type": "SemanticModel", "displayName": NAME},
        "config": {"version": "2.0", "logicalId": MODEL_LOGICAL_ID},
    })

    return {
        "tables": len(inv) + 1,
        "measures": len(measures),
        "relationships": len(rels),
        "queries": len(bodies),
        "untyped_columns": untyped,
        "measure_table_qualifier_rewrites": measure_table_qualifier_rewrites,
        "relationship_deviations": [{
            "relationship": "forecast_weekly_to_Date",
            "model_definition_to": "Date[calendar_date]",
            "pbip_output_to": "Date[date_key]",
            "reason": "the governed Date unknown row has a blank calendar_date",
        }],
    }


# --------------------------------------------------------------------------- report / PBIR
def field(entity: str, prop: str, kind: str) -> dict:
    """A semantic-query field reference; kind is "Column" or "Measure"."""
    inner = {"Expression": {"SourceRef": {"Entity": entity}}, "Property": prop}
    return {kind: inner}


def measure_ref(name: str) -> dict:
    """Reference to a governed measure in the output measure table."""
    return field(MEASURE_TABLE, name, "Measure")


def column_ref(entity: str, name: str) -> dict:
    """Reference to a model column."""
    return field(entity, name, "Column")


def projection(fld: dict, ref: str, native_ref: str | None = None) -> dict:
    """A query-role projection; native_ref is the label Desktop shows for the field."""
    result = {"field": fld, "queryRef": ref}
    field_value = next(iter(fld.values())) if isinstance(fld, dict) else {}
    readable_name = native_ref or field_value.get("Property") or ref
    result["displayName"] = readable_name
    if native_ref is not None:
        result["nativeQueryRef"] = native_ref
    return result


def aggregation_ref(entity: str, name: str, function: int = 0) -> dict:
    """Aggregated column reference. PBIR functions: 0 Sum, 2 Distinct count, 5 Count non-null."""
    return {"Aggregation": {"Expression": column_ref(entity, name), "Function": function}}


def sum_projection(entity: str, column: str, alias: str, label: str) -> dict:
    """A Sum-aggregated value projection for a numeric column.

    Desktop renders a value-axis column blank unless the field carries an explicit
    aggregation, so every Y projection on a numeric extract column goes through
    here. This is the same shape as the working "Sum of gap_log" series.
    """
    return projection(aggregation_ref(entity, column), f"Sum({entity}.{column})", label)


def pbir_literal(value: object) -> dict:
    """PBIR literal: bool as true/false, int with L, float with D, text single-quoted."""
    if isinstance(value, bool):
        literal = "true" if value else "false"
    elif isinstance(value, int):
        literal = f"{value}L"
    elif isinstance(value, float):
        literal = f"{value:g}D"
    else:
        literal = "'" + str(value).replace("'", "''") + "'"
    return {"expr": {"Literal": {"Value": literal}}}


def entity_source(alias: str, entity: str) -> dict:
    """A From-clause source for a filter query."""
    return {"Name": alias, "Entity": entity, "Type": 0}


def categorical_filter(name: str, entity: str, column: str, values: list[object]) -> dict:
    """A visual or page filter keeping only the listed values of one column."""
    alias = "filterSource"
    return {
        "name": name,
        "field": column_ref(entity, column),
        "type": "Categorical",
        "filter": {
            "Version": 2,
            "From": [entity_source(alias, entity)],
            "Where": [{
                "Condition": {
                    "In": {
                        "Expressions": [{
                            "Column": {
                                "Expression": {"SourceRef": {"Source": alias}},
                                "Property": column,
                            }
                        }],
                        "Values": [[{"Literal": {"Value": pbir_literal(value)["expr"]["Literal"]["Value"]}}]
                                   for value in values],
                    }
                }
            }],
        },
        "howCreated": "User",
    }


def filter_name(seed: str) -> str:
    """Stable filter id derived from a readable seed, so rebuilds do not churn ids."""
    return "Filter" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]


def slicer_selection_state(entity: str, column: str, values: list[str]) -> dict:
    """The saved selection of a slicer, in the shape Desktop writes.

    Desktop keeps a slicer's selected items at
    `visual.objects.general[].properties.filter`, holding the filter state itself
    (Version / From / Where), the same shape as a filterConfig entry. Wrapping that
    state in an extra `filter` key makes Desktop ignore it: the slicer opens with
    nothing selected and every card reads across every period.
    """
    alias = "d"
    return {
        "Version": 2,
        "From": [entity_source(alias, entity)],
        "Where": [{
            "Condition": {
                "In": {
                    "Expressions": [{
                        "Column": {
                            "Expression": {"SourceRef": {"Source": alias}},
                            "Property": column,
                        }
                    }],
                    "Values": [[{
                        "Literal": {
                            "Value": pbir_literal(value)["expr"]["Literal"]["Value"]
                        }
                    }] for value in values],
                }
            }
        }],
    }


def sort_def(fld: dict, direction: str = "Ascending") -> dict:
    """Default sort on one field; the field must also be in the visual's query."""
    return {"sort": [{"field": fld, "direction": direction}], "isDefaultSort": True}


def title_block(text: str) -> list[dict]:
    """Visual container title at 12pt with wrapping on."""
    return [{"properties": {
        "show": pbir_literal(True),
        "text": pbir_literal(text),
        "fontSize": pbir_literal(12.0),
        "titleWrap": pbir_literal(True),
    }}]


# Evidence wording stays on the visual title; the governance register code moves to
# the visual tooltip so the title reads as a plain claim.
EVIDENCE_LABELS = (
    "fact", "estimate", "association", "statistical association",
    "observed change", "hypothesis", "root-cause evidence", "not attributed",
)
_TRAILING_PAREN = re.compile(r"\s*\(([^()]*)\)\s*$")
_REGISTER_CODE = re.compile(r"^P\d")


def split_register_code(title: str) -> tuple[str, str]:
    """Split a trailing title parenthetical into (clean title, register code).

    A title of the form "<claim> (fact, P4-01/02)" keeps its evidence label and
    yields "P4-01/02" as the register code. A parenthetical that carries no
    register code (a plain qualifier such as "(most recent observed weeks)") is
    left untouched.
    """
    match = _TRAILING_PAREN.search(title)
    if not match:
        return title, ""
    inner = match.group(1).strip()
    head = title[: match.start()].rstrip()
    if not head or not inner:
        return title, ""
    parts = [piece.strip() for piece in inner.split(",") if piece.strip()]
    if not any(_REGISTER_CODE.match(part) for part in parts):
        return title, ""
    label = ""
    code_parts: list[str] = []
    for part in parts:
        lowered = part.lower()
        if any(lowered == word or lowered.startswith(word) for word in EVIDENCE_LABELS):
            label = label or part
        elif not label and any(word in lowered for word in EVIDENCE_LABELS):
            label = part
        else:
            code_parts.append(part)
    if not code_parts:
        return title, ""
    clean = f"{head} ({label})" if label else head
    return clean, ", ".join(code_parts)


def visual_object_properties(objects: dict) -> dict:
    """Convert plain Python property values in visual objects to PBIR literals."""
    converted = {}
    for object_name, instances in objects.items():
        converted[object_name] = []
        for instance in instances:
            properties = instance.get("properties", {})
            converted[object_name].append({
                **{key: value for key, value in instance.items() if key != "properties"},
                "properties": {
                    # "filter" values and pre-built expr/solid-colour dicts pass through
                    # unchanged; plain scalars still go through pbir_literal.
                    key: value if key == "filter" or isinstance(value, dict) else pbir_literal(value)
                    for key, value in properties.items()
                },
            })
    return converted


def solid_color(hex_value: str) -> dict:
    """Solid fill colour from a hex string."""
    return {"solid": {"color": pbir_literal(hex_value)}}


def metadata_color_objects(mapping: dict[str, str]) -> dict:
    """Per-measure colour override for multi-measure Y charts (req. 4).

    mapping: queryRef -> hex colour, matched by the visual's own queryRef string.
    """
    return {"dataPoint": [
        {"properties": {"fill": solid_color(color)}, "selector": {"metadata": ref}}
        for ref, color in mapping.items()
    ]}


def category_color_objects(entity: str, column: str, mapping: dict[object, str]) -> dict:
    """Per-legend-value colour override for Series-based charts (req. 4)."""
    entries = []
    for value, color in mapping.items():
        entries.append({
            "properties": {"fill": solid_color(color)},
            "selector": {"data": [{"scopeId": {"Comparison": {
                "ComparisonKind": 0,
                "Left": column_ref(entity, column),
                "Right": {"Literal": {"Value": pbir_literal(value)["expr"]["Literal"]["Value"]}},
            }}}]},
        })
    return {"dataPoint": entries}


def visual(
    name: str, x: int, y: int, w: int, h: int, visual_type: str,
    query_state: dict, objects: dict | None = None, title: str | None = None,
    alt: str | None = None, sort: dict | None = None,
    filter_config: dict | None = None, z: int = 0,
    tab: int = 0, sync_group: str | None = None,
) -> dict:
    """One visual.json payload: position, query, formatting, title, alt text, sort and filters."""
    if visual_type in {
        "lineChart", "barChart", "clusteredBarChart", "clusteredColumnChart",
        "stackedBarChart", "stackedColumnChart", "areaChart", "stackedAreaChart",
    } and "CategoryAxis" in query_state:
        query_state = dict(query_state)
        query_state["Category"] = query_state.pop("CategoryAxis")
    v: dict = {
        "$schema": f"{SCHEMA}/report/definition/visualContainer/2.13.0/schema.json",
        "name": name,
        "position": {"x": x, "y": y, "z": z, "height": h, "width": w, "tabOrder": tab},
        "visual": {"visualType": visual_type, "query": {"queryState": query_state}},
    }
    if title:
        title, register_code = split_register_code(title)
        if register_code:
            note = f"Governance register: {register_code}."
            alt = f"{alt.rstrip()} {note}" if alt else note
    if sort:
        v["visual"]["query"]["sortDefinition"] = sort
    if filter_config:
        v["filterConfig"] = filter_config
    if sync_group:
        v["visual"]["syncGroup"] = {
            "groupName": sync_group,
            "fieldChanges": False,
            "filterChanges": True,
        }
    if objects:
        v["visual"]["objects"] = visual_object_properties(objects)
    # visualContainerObjects lives inside `visual` per visualContainer 1.4.0
    vc: dict = {
        "title": title_block(title) if title else [{"properties": {"show": pbir_literal(False)}}],
        "subTitle": [{"properties": {"show": pbir_literal(False)}}],
        "background": [{"properties": {
            "show": pbir_literal(True),
            "color": {"solid": {"color": pbir_literal("#FFFFFF")}},
            "transparency": pbir_literal(0.0),
        }}],
        "border": [{"properties": {
            "show": pbir_literal(True),
            "color": {"solid": {"color": pbir_literal("#E1DFDB")}},
            "radius": pbir_literal(6.0),
        }}],
        "visualHeader": [{"properties": {"show": pbir_literal(False)}}],
    }
    if alt:
        vc["general"] = [{"properties": {"altText": pbir_literal(alt)}}]
    v["visual"]["visualContainerObjects"] = vc
    return v


def textbox_visual(name: str, x: int, y: int, w: int, h: int, text: str,
                   font_size: str = "11pt", color: str = "#333333") -> dict:
    """Static PBIR textbox, used for governed wording and explicit spec gaps."""
    return {
        "$schema": f"{SCHEMA}/report/definition/visualContainer/2.13.0/schema.json",
        "name": name,
        "position": {"x": x, "y": y, "z": 0, "height": h, "width": w, "tabOrder": 0},
        "visual": {
            "visualType": "textbox",
            "objects": {"general": [{"properties": {"paragraphs": [{
                "textRuns": [{"value": text, "textStyle": {
                    "fontFamily": "Segoe UI", "fontSize": font_size, "color": color,
                }}],
                "horizontalTextAlignment": "left",
            }]}}]},
            "visualContainerObjects": {
                "background": [{"properties": {"show": pbir_literal(False)}}],
                "border": [{"properties": {"show": pbir_literal(False)}}],
                "padding": [{"properties": {
                    side: pbir_literal(0.0) for side in ("top", "bottom", "left", "right")
                }}],
            },
        },
    }


def page_slicer(name: str, x: int, y: int, width: int, title: str,
                entity: str, column: str, query_ref: str, sync_group: str | None = None,
                filter_config: dict | None = None, height: int = 78) -> tuple[str, dict]:
    """A dropdown slicer; Period slicers open on the governed default period."""
    general = {"orientation": 0}
    general["placeholder"] = f"Select {title.lower()}..."
    if entity == "Date" and column == "period_label":
        general["filter"] = slicer_selection_state("Date", "period_label",
                                                   [REPORT_DEFAULT_PERIOD])
        if filter_config is None:
            filter_config = {"filters": [
                categorical_filter(
                    filter_name(name + ":unknown-date"), "Date", "is_unknown", [0]),
                categorical_filter(
                    filter_name(name + ":periods"), "Date", "period_label",
                    list(REPORT_PERIODS)),
            ]}
    return name, visual(
        # 78px leaves room for the field header, the selected value and the dropdown
        # affordance; at the previous 52px the selection was clipped on pages 2 to 6.
        name, x, y, width, height, "slicer",
        {"Values": {"projections": [projection(column_ref(entity, column), query_ref, column)]}},
        # The container title carries the readable label; the slicer field header would
        # repeat it as a raw column name, so it is switched off on every slicer.
        objects={"general": [{"properties": general}],
                 "data": [{"properties": {"mode": "Dropdown"}}],
                 "header": [{"properties": {"show": False}}]},
        title=title, tab=0, sync_group=sync_group, filter_config=filter_config,
    )


TEXT_MEASURES = {"Cluster Cause Callout", "Phase 6 Scope Note", "Voltix Wording", "Promotion Wording"}

# The report scope is the two governed half-years of 2024 and 2025. date.csv also
# carries an "Unknown" bucket and three H1 2026 days; the period slicer filters both
# out so the dropdown offers only these four labels, with H2 2025 pre-selected.
REPORT_PERIODS = ("H1 2024", "H2 2024", "H1 2025", "H2 2025")
# The saved selection every Period slicer opens on, so the cards read H2 2025 rather
# than all four periods.
REPORT_DEFAULT_PERIOD = "H2 2025"


def text_measure_visual(name: str, measure: str, x: int, y: int, width: int, height: int,
                        native_ref: str | None = None) -> tuple[str, dict]:
    """A one-cell table for a text measure; a card would truncate the sentence."""
    return name, visual(
        name, x, y, width, height, "tableEx",
        {"Values": {"projections": [projection(
            measure_ref(measure), f"m.{measure.replace(' ', '')}", native_ref or measure,
        )]}},
        objects={
            "columnHeaders": [{"properties": {"show": False}}],
            "values": [{"properties": {"fontSize": 9, "wordWrap": True}}],
            "total": [{"properties": {"show": False, "totals": False}}],
        },
    )


def card_label_font_size(height: int) -> int:
    """Card category labels are full descriptive sentences, so they are sized to the
    card rather than left at the default, which clips them on every page."""
    if height >= 100:
        return 10
    return 9 if height >= 60 else 8


def card_category_label_objects(height: int) -> dict:
    """Card category label shown, sized to the card height."""
    return {"categoryLabels": [{"properties": {
        "show": True, "fontSize": card_label_font_size(height)}}]}


def measure_card(name: str, measure: str, x: int, y: int, width: int, height: int,
                 title: str | None = None, filter_config: dict | None = None) -> tuple[str, dict]:
    """A KPI card over one governed measure; text measures become one-cell tables."""
    if measure in TEXT_MEASURES:
        return text_measure_visual(name, measure, x, y, width, height, title or measure)
    # The card visual already shows the field's own display name (set below as the
    # native query ref), so a container title would duplicate it. Below 100px there
    # is not room for both, so the container title is hidden and the descriptive
    # text instead becomes the tooltip (alt) text; nothing is lost since the native
    # display name on the card is still the full title text.
    label = title or measure
    show_title = height >= 100
    return name, visual(
        name, x, y, width, height, "card",
        {"Values": {"projections": [projection(measure_ref(measure), f"m.{measure.replace(' ', '')}", label)]}},
        title=label if show_title else None,
        alt=None if show_title else label,
        # Ask for the category label explicitly so the card always says what it shows,
        # at a size that fits the card instead of the default that clips it.
        objects=card_category_label_objects(height),
        filter_config=filter_config,
    )


def table_visual(name: str, x: int, y: int, width: int, height: int,
                 projections: list[dict], title: str,
                 filters: list[dict] | None = None, totals: bool = False,
                                 sort: dict | None = None, word_wrap: bool = True,
                 alt: str | None = None) -> tuple[str, dict]:
    """A table visual with 9pt wrapped text and totals off unless requested."""
    objects = {"columnHeaders": [{"properties": {
                   "show": True, "fontSize": 9, "wordWrap": word_wrap}}],
                   "values": [{"properties": {"fontSize": 9, "wordWrap": word_wrap}}],
                   "total": [{"properties": {"show": totals, "totals": totals}}]}
    return name, visual(
        name, x, y, width, height, "tableEx",
        {"Values": {"projections": projections}},
        objects=objects, title=title, alt=alt,
        filter_config={"filters": filters} if filters else None,
        sort=sort,
    )


# PBIR QueryAggregateFunction: 2 is Distinct count, 5 is Count of non-null values.
COUNT_ROWS = 5


def count_projection(entity: str, column: str, alias: str, label: str) -> dict:
    """A row-count value projection: Count of non-null values on a column that is never blank.

    Function 2 is Distinct count, which collapsed 51 PASS checks to their 13 groups and the
    38,138 issue-log rows to their distinct rule ids. Counting non-null values of a non-null
    key counts every row. It also keeps the page free of new DAX.
    """
    return projection(aggregation_ref(entity, column, COUNT_ROWS),
                      f"CountNonNull({entity}.{column})", label)


def column_card(name: str, entity: str, column: str, label: str, x: int, y: int,
                width: int, height: int, title: str,
                filters: list[dict] | None = None,
                aggregate: str = "Count") -> tuple[str, dict]:
    """A KPI card over one column, so no DAX measure is needed for the page.

    `aggregate` is "Count" for a row tally or "Sum" for a governed numeric column.
    Below 100px the container title is hidden and becomes the tooltip text instead,
    matching measure_card: the card then shows only the value and its category label.
    """
    value = (sum_projection(entity, column, name, label) if aggregate == "Sum"
             else count_projection(entity, column, name, label))
    show_title = height >= 100
    # Display units "None" (1D) and 0 decimals: the card shows 38,138, not 38.14K.
    objects = {**card_category_label_objects(height),
               "labels": [{"properties": {"labelDisplayUnits": 1.0, "labelPrecision": 0}}]}
    return name, visual(
        name, x, y, width, height, "card",
        {"Values": {"projections": [value]}},
        title=title if show_title else None,
        alt=None if show_title else f"{title}: {label}",
        objects=objects,
        filter_config={"filters": filters} if filters else None,
    )


def page_spec(name: str, display_name: str, visuals: list[tuple[str, dict]],
              page_filters: list[dict] | None = None,
              visual_interactions: list[dict] | None = None,
              page_type: str | None = None, page_binding: dict | None = None,
              width: int = PAGE_W, height: int = PAGE_H) -> dict:
    """A page spec: page.json payload plus its named visuals, ready for write_page_spec."""
    page = {
        "$schema": f"{SCHEMA}/report/definition/page/2.1.0/schema.json",
        "name": name,
        "displayName": display_name,
        "displayOption": "FitToPage",
        "height": height,
        "width": width,
        "objects": {"background": [{"properties": {
            "color": {"solid": {"color": pbir_literal("#F7F6F3")}},
            "transparency": pbir_literal(0.0),
        }}]},
    }
    if page_filters:
        page["filterConfig"] = {"filters": page_filters}
    if visual_interactions:
        page["visualInteractions"] = visual_interactions
    if page_type:
        page["type"] = page_type
    if page_binding:
        page["pageBinding"] = page_binding
    return {"name": name, "page": page, "visuals": visuals}


def write_page_spec(definition: pathlib.Path, spec: dict) -> tuple[str, int]:
    """Write one page folder; return (page name, visual count)."""
    page_dir = definition / "pages" / spec["name"]
    page_dir.mkdir(parents=True, exist_ok=True)
    write_json(page_dir / "page.json", spec["page"])
    written = 0
    for visual_name, payload in spec["visuals"]:
        write_json(page_dir / "visuals" / visual_name / "visual.json", payload)
        written += 1
    return spec["name"], written


def column_projection(entity: str, column: str, query_ref: str | None = None,
                      native_ref: str | None = None) -> dict:
    """A bare column projection (no aggregation), as category axes and table columns need."""
    return projection(column_ref(entity, column), query_ref or f"{entity}.{column}", native_ref or column)


def measure_projection(name: str, query_ref: str | None = None) -> dict:
    """A governed measure projection."""
    return projection(measure_ref(name), query_ref or f"m.{name.replace(' ', '')}", name)


def csv_top_values(filename: str, column: str, score_column: str, limit: int) -> list[str]:
    """Top `limit` values of a column from a powerbi/data extract, ranked by a score column."""
    import csv
    path = PBI / "data" / filename
    with path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    ranked = sorted(rows, key=lambda row: float(row[score_column]), reverse=True)
    return [row[column] for row in ranked[:limit]]


def text_visual(name: str, x: int, y: int, width: int, height: int, text: str,
                font_size: str = "11pt", color: str = "#333333") -> tuple[str, dict]:
    """A static text box (titles, subtitles, notes)."""
    return name, textbox_visual(name, x, y, width, height, text, font_size, color)


def phase6_caption_visual(name: str, x: int, y: int, width: int = 360,
                          height: int = 44) -> tuple[str, dict]:
    """The governed Phase 6 scope note, shown wherever Phase 6 figures appear."""
    return text_measure_visual(name, "Phase 6 Scope Note", x, y, width, height, "Phase 6 scope")



def build_page1() -> list[tuple[str, dict]]:
    """Twelve PBIR visuals for the Executive Overview page.

    Positions are on a 1280x720 canvas. KPI band y=48..158, middle y=168..418,
    bottom y=428..708, slicer rail x=12..212.
    """
    M = measure_ref
    kpi_x = [224, 434, 644, 854, 1064]
    kpi_w = 200
    kpis = [
        ("kpiNetRevenue", "Net Revenue", "1 Executive Overview KPI: governed headline net revenue."),
        ("kpiNetRevenueYoYPct", "Net Revenue YoY %", "1 Executive Overview KPI: net revenue change versus the same period one year earlier."),
        ("kpiGrossMarginPct", "Gross Margin %", "1 Executive Overview KPI: gross margin as a share of sales revenue."),
        ("kpiTransactions", "Transactions", "1 Executive Overview KPI: distinct transaction count."),
        ("kpiReturnRate", "Return Rate", "1 Executive Overview KPI: refund value as a share of sales revenue."),
    ]
    out: list[tuple[str, dict]] = []
    tab = 0
    for (name, measure, alt), x in zip(kpis, kpi_x):
        out.append((name, visual(
            name, x, 48, kpi_w, 110, "card",
            {"Values": {"projections": [projection(M(measure), f"m.{measure}")]}},
            title=measure, alt=alt, tab=tab,
            objects=card_category_label_objects(110),
        )))
        tab += 1

    # 6. Revenue YoY trend
    out.append(("trendRevenueYoY", visual(
        "trendRevenueYoY", 224, 168, 520, 250, "lineChart",
        {
            "CategoryAxis": {"projections": [
                projection(column_ref("Date", "retail_week"), "d.retail_week", "Retail week")]},
            "Y": {"projections": [
                projection(M("Net Revenue"), "m.NetRevenue", "Net Revenue, 2025"),
                projection(M("Net Revenue PY"), "m.NetRevenuePY", "Net Revenue, 2024"),
            ]},
        },
        sort=sort_def(column_ref("Date", "retail_week_key")),
        objects={"labels": [{"properties": {"show": False}}],
                 **metadata_color_objects({"m.NetRevenue": COLOR_CLUSTER, "m.NetRevenuePY": COLOR_PY})},
        title="Net Revenue down 7.18% YoY in H2 2025: \u20ac9.46M vs \u20ac10.19M (P1-01/02/04)",
        alt="Line chart comparing net revenue with the same period one year earlier.",
        tab=tab,
    )))
    tab += 1

    # 7. Driver attribution waterfall
    out.append(("driverAttributionWaterfall", visual(
        "driverAttributionWaterfall", 754, 168, 514, 250, "waterfallChart",
        {
            "Category": {"projections": [
                projection(column_ref("p6_driver_attribution", "driver"), "d.driver", "Driver")]},
            "Y": {"projections": [
                projection(aggregation_ref("p6_driver_attribution", "amount_eur"),
                           "Sum(p6_driver_attribution.amount_eur)", "Driver impact (\u20ac)")]},
        },
        sort=sort_def(column_ref("p6_driver_attribution", "sort_order")),
        objects={"labels": [{"properties": {"show": True, "fontSize": 9}}]},
        title="Store-cluster excess decline is the largest driver: -\u20ac397,778, 54% of the H2 decline (estimate, P1-20a/b)",
        alt="Waterfall of the H2 revenue change split into the Phase 6 driver components.",
        tab=tab,
    )))
    tab += 1

    # 8. Phase 5 revenue bridge (Shapley-style decomposition)
    out.append(("phase5RevenueBridge", visual(
        "phase5RevenueBridge", 224, 428, 520, 280, "waterfallChart",
        {
            "Category": {"projections": [
                projection(column_ref("p5_revenue_bridge", "step"), "b.step", "Bridge step")]},
            "Y": {"projections": [
                projection(aggregation_ref("p5_revenue_bridge", "value_eur"),
                           "Sum(p5_revenue_bridge.value_eur)", "Revenue change (\u20ac)")]},
        },
        sort=sort_def(column_ref("p5_revenue_bridge", "sort_order")),
        objects={"labels": [{"properties": {"show": True, "fontSize": 9}}]},
        title="Transactions effect is the largest bridge step: -\u20ac614k of the H2 net revenue change (fact, P1-30)",
        alt="Waterfall bridging H2 2024 net revenue to H2 2025 through transaction, UPT, ASP, interaction and returns effects.",
        tab=tab,
    )))
    tab += 1

    # 9. Executive driver / evidence summary
    ev_cols = [
        ("driver", "Driver"),
        ("evidence_level", "Evidence level"),
        ("cause_status", "Cause status"),
        ("evidence_strength", "Strength"),
        ("financial_impact_eur", "Financial impact EUR"),
        ("confidence", "Confidence"),
    ]
    out.append(("executiveEvidenceSummary", visual(
        "executiveEvidenceSummary", 754, 428, 514, 280, "tableEx",
        {"Values": {"projections": [
            projection(column_ref("p6_evidence_matrix", c), f"e.{c}", label) for c, label in ev_cols]}},
        objects={"columnHeaders": [{"properties": {"show": True, "fontSize": 9}}],
                 "values": [{"properties": {"fontSize": 9, "wordWrap": True}}]},
        title="Store-cluster transaction loss is the largest evidence-matrix line: -\u20ac397,778, cause still unresolved (P6-D01, Observed change)",
        alt="Table of Phase 6 drivers with evidence level, cause status, strength, financial impact and confidence.",
        tab=tab,
    )))
    tab += 1

    # Slicers
    out.append(("slicerPeriod", visual(
        "slicerPeriod", 12, 56, 200, 150, "slicer",
        {"Values": {"projections": [
            projection(column_ref("Date", "period_label"), "f.period_label")]}},
        objects={"general": [{"properties": {
                     "orientation": 0,
                     "placeholder": "Select period...",
                     "filter": slicer_selection_state("Date", "period_label",
                                                     [REPORT_DEFAULT_PERIOD]),
                 }}],
                 "data": [{"properties": {"mode": "Basic"}}],
                 "header": [{"properties": {"show": False}}]},
        filter_config={"filters": [
            categorical_filter(
                "a6198dc19a2b47e6bf0ba8e7", "Date", "is_unknown", [0]),
            categorical_filter(
                "a6198dc19a2b47e6bf0ba8e8", "Date", "period_label",
                list(REPORT_PERIODS)),
        ]},
        title="Period", alt="Slicer filtering on reporting period.", tab=tab,
        sync_group="Period",
    )))
    tab += 1
    out.append(("slicerStore", visual(
        "slicerStore", 12, 216, 200, 150, "slicer",
        {"Values": {"projections": [
            projection(column_ref("Store", "store_name"), "f.store_name")]}},
        objects={"general": [{"properties": {"orientation": 0, "placeholder": "Select store..."}}],
                 "data": [{"properties": {"mode": "Basic"}}],
                 "header": [{"properties": {"show": False}}],
                 "search": [{"properties": {"show": False}}]},
        title="Store", alt="Slicer filtering on store.", tab=tab,
        sync_group="Store",
    )))
    tab += 1
    out.append(("slicerCategory", visual(
        "slicerCategory", 12, 376, 200, 150, "slicer",
        {"Values": {"projections": [
            projection(column_ref("Product", "category"), "f.category")]}},
        objects={"general": [{"properties": {"orientation": 0, "placeholder": "Select category..."}}],
                 "data": [{"properties": {"mode": "Basic"}}],
                 "header": [{"properties": {"show": False}}]},
        title="Category", alt="Slicer filtering on product category.", tab=tab,
    )))
    tab += 1

    return out


def build_page2() -> dict:
    """Page 2: store and customer diagnostics (cluster versus matched controls)."""
    visuals: list[tuple[str, dict]] = [
        text_visual("page2Title", 16, 8, 1248, 36,
                    "Store and customer diagnostics", "22pt", "#111111"),
        text_visual("page2Subtitle", 16, 44, 1248, 24,
                    "Where did customers stop coming, and is the cause known?"),
        page_slicer("page2Period", 16, 72, 230, "Period", "Date", "period_label", "f.period_label", "Period"),
        page_slicer("page2StoreGroup", 256, 72, 230, "Store group", "Store", "store_group", "f.store_group", "StoreGroup"),
        page_slicer("page2Region", 496, 72, 230, "Region", "Store", "region", "f.region", "Region"),
        page_slicer("page2Format", 736, 72, 230, "Store format", "Store", "store_format", "f.store_format", "StoreFormat"),
        page_slicer("page2Store", 976, 72, 288, "Store", "Store", "store_name", "f.store_name", "Store"),
        measure_card("page2ClusterTransactions", "Transactions YoY %", 16, 154, 300, 84,
                     "Investigated cluster: transactions YoY %",
                     {"filters": [categorical_filter(filter_name("p2-cluster"), "Store", "store_group", ["Investigated cluster"])]}),
        measure_card("page2ControlTransactions", "Transactions YoY %", 330, 154, 300, 84,
                     "Matched controls: transactions YoY %",
                     {"filters": [categorical_filter(filter_name("p2-controls"), "Store", "store_group", ["Matched control"])]}),
        measure_card("page2ClusterExcess", "Cluster Excess (P6)", 644, 154, 300, 84,
                     "Estimated cluster excess decline"),
        ("page2MatchedDid", visual(
            "page2MatchedDid", 958, 154, 306, 84, "card",
            {"Values": {"projections": [projection(
                aggregation_ref("p6_cluster_did", "did_pct"),
                "Sum(p6_cluster_did.did_pct)", "Transactions DiD (%)")] }},
            objects=card_category_label_objects(84),
            filter_config={"filters": [
                categorical_filter(filter_name("p2-did-matched"), "p6_cluster_did", "control_group", ["matched"]),
                categorical_filter(filter_name("p2-did-transactions"), "p6_cluster_did", "outcome", ["ly_transactions"]),
            ]},
        )),
        measure_card("page2Callout", "Cluster Cause Callout", 16, 242, 610, 104, "Cause status"),
        phase6_caption_visual("page2Scope", 638, 242, 626, 104),
        ("page2WeeklyTransactions", visual(
            "page2WeeklyTransactions", 16, 350, 610, 180, "lineChart",
            {
                "CategoryAxis": {"projections": [column_projection("Date", "retail_week", "d.retail_week", "Retail week")]},
                "Series": {"projections": [column_projection("Store", "store_group", "s.store_group", "Store group")]},
                "Y": {"projections": [measure_projection("Transactions YoY %", "m.TransactionsYoYPercent")]},
            },
            title="Investigated cluster transactions down 27.8% YoY vs -1.1% for matched controls (P2-T0/T1)",
            sort=sort_def(column_ref("Date", "retail_week_key")),
            objects=category_color_objects("Store", "store_group",
                                            {"Investigated cluster": COLOR_CLUSTER, "Matched control": COLOR_CONTROL}),
            filter_config={"filters": [categorical_filter(filter_name("p2-line-groups"), "Store", "store_group", ["Investigated cluster", "Matched control"])]},
        )),
        ("page2DailyGap", visual(
            "page2DailyGap", 638, 350, 626, 180, "lineChart",
            {
                "CategoryAxis": {"projections": [column_projection("p6_cluster_onset_daily", "calendar_date", "onset.calendar_date", "Date")]},
                "Y": {"projections": [projection(aggregation_ref("p6_cluster_onset_daily", "gap_log"), "Sum(p6_cluster_onset_daily.gap_log)", "Daily gap to controls")]},
            },
            title="Change point: daily gap to controls widens after 15 Jul 2025 (P6 cluster onset, estimate)",
            sort=sort_def(column_ref("p6_cluster_onset_daily", "calendar_date")),
        )),
        # Gap notes, not claims. The governed design requires a field-parameter
        # comparison matrix and a 7-day mean on the change-point chart; neither exists
        # in the model, so each panel states only what is missing and why. No caveat
        # prose is written here: nothing is claimed about the counterfactual level
        # beyond what docs/06_root_cause_analysis.md already states.
        text_visual("page2MatrixPlaceholder", 16, 534, 400, 48,
                    "NOT SHOWN: the eight-measure, three-group comparison matrix requires "
                    "field parameters, which are not in the governed model.", "9pt"),
        text_visual("page2MeanPlaceholder", 638, 534, 626, 48,
                    "NOT SHOWN: the 7-day mean requires a governed measure or query; "
                    "only the raw daily gap_log is available.", "9pt"),
        table_visual("page2Sensitivity", 16, 584, 400, 134, [
            column_projection("p6_sensitivity_summary", "range_low_eur", "s.range_low_eur", "Low"),
            column_projection("p6_sensitivity_summary", "range_high_eur", "s.range_high_eur", "High"),
            column_projection("p6_sensitivity_summary", "n_variants", "s.n_variants", "Variants"),
        ], "Cluster excess sensitivity range", [categorical_filter(filter_name("p2-sensitivity"), "p6_sensitivity_summary", "driver", ["store_cluster_excess"])]),
        table_visual("page2StoreOnsets", 426, 584, 390, 134, [
            column_projection("p6_cluster_onset_by_store", "store_id", "o.store_id", "Store"),
            column_projection("p6_cluster_onset_by_store", "onset_date", "o.onset_date", "Onset date"),
            column_projection("p6_cluster_onset_by_store", "shift_pct", "o.shift_pct", "Shift %"),
        ], "Per-store onset dates"),
        # The Priority 1 row carries a 137-character data_required value, so the panel is
        # 134px: at 110px the header and the row overflowed and Desktop showed only
        # the column headers.
        table_visual("page2DataRequired", 826, 584, 438, 134, [
            column_projection("p6_investigations", "data_required", "i.data_required", "Additional data required"),
            column_projection("p6_investigations", "proposed_owner", "i.proposed_owner", "Proposed owner"),
        ], "Priority 1: data required", [categorical_filter(filter_name("p2-investigation"), "p6_investigations", "priority", [1])]),
    ]
    return page_spec("ReportSection2StoreCustomer", "2 Store and customer diagnostics", visuals)


def build_page3() -> dict:
    """Page 3: product, category and inventory (Electronics availability and lost sales)."""
    visuals: list[tuple[str, dict]] = [
        text_visual("page3Title", 16, 8, 1248, 36, "Product, category and inventory: Electronics and Tech", "22pt", "#111111"),
        text_visual("page3Subtitle", 16, 44, 1248, 24,
                    "Electronics & Tech availability and supplier evidence from Phase 6. "
                    "Availability and returns cards are blank by design: a category filter reaches Promotion "
                    "through Sales, and stock and returns carry no promotion key.", "9pt"),
        page_slicer("page3Period", 16, 72, 245, "Period", "Date", "period_label", "f.period_label", "Period"),
        page_slicer("page3Category", 271, 72, 245, "Category", "Product", "category", "f.category", "Category"),
        page_slicer("page3Supplier", 526, 72, 300, "Supplier", "Product", "supplier_name", "f.supplier_name", "Supplier"),
        page_slicer("page3Store", 836, 72, 428, "Store", "Store", "store_name", "f.store_name", "Store"),
        measure_card("page3Revenue", "Net Revenue", 16, 154, 150, 84, "Net Revenue"),
        measure_card("page3RevenueYoY", "Net Revenue YoY", 172, 154, 150, 84, "Revenue change vs PY"),
        measure_card("page3UnitsYoY", "Units YoY %", 328, 154, 150, 84, "Units YoY"),
        measure_card("page3TransactionsYoY", "Transactions YoY %", 484, 154, 150, 84, "Transactions YoY"),
        measure_card("page3ASP", "ASP", 640, 154, 150, 84, "ASP"),
        measure_card("page3Availability", "Availability", 796, 154, 150, 84, "Availability"),
        measure_card("page3AvailabilityPY", "Availability PY", 952, 154, 150, 84, "Availability prior year"),
        measure_card("page3Returns", "Returns Value", 1108, 154, 150, 84, "Returns"),
        ("page3AvailabilityTrend", visual(
            "page3AvailabilityTrend", 16, 242, 400, 150, "lineChart",
            {"CategoryAxis": {"projections": [column_projection("p6_et_weekly_timeline", "retail_week", "w.retail_week", "Retail week")]},
             "Y": {"projections": [
                 sum_projection("p6_et_weekly_timeline", "availability_supplier_cy", "w", "Voltix, 2025"),
                 sum_projection("p6_et_weekly_timeline", "availability_other_suppliers_cy", "w", "Other suppliers, 2025"),
             ]}},
            title="Voltix stock-out rate rose 6.8pp more than other suppliers in H2 2025 (statistical association, P3-S1)",
            sort=sort_def(column_ref("p6_et_weekly_timeline", "retail_week")),
            objects=metadata_color_objects({
                "Sum(p6_et_weekly_timeline.availability_supplier_cy)": COLOR_VOLTIX,
                "Sum(p6_et_weekly_timeline.availability_other_suppliers_cy)": COLOR_CONTROL,
            }),
        )),
        ("page3TopSkus", visual(
            "page3TopSkus", 426, 242, 400, 150, "barChart",
            {"CategoryAxis": {"projections": [column_projection("p6_et_sku_stockouts", "product_id", "sku.product_id", "SKU")]},
             "Y": {"projections": [projection(aggregation_ref("p6_et_sku_stockouts", "lost_primary_change"), "Sum(p6_et_sku_stockouts.lost_primary_change)", "Estimated lost sales change (\u20ac)")]}},
            # No Series field: splitting the eight SKUs by supplier collapses the bars
            # in Desktop. Supplier composition of this panel is not a governed claim,
            # so it stays out of the title too.
            title="Top SKU alone is 25% of estimated lost sales; top 3 SKUs are 50% (estimate, P3-C2/C3)",
            sort=sort_def(aggregation_ref("p6_et_sku_stockouts", "lost_primary_change"), "Descending"),
            filter_config={"filters": [categorical_filter(
                filter_name("p3-top-eight-skus"), "p6_et_sku_stockouts", "product_id",
                csv_top_values("p6_et_sku_stockouts.csv", "product_id", "lost_primary_change", 8),
            )]},
        )),
        measure_card("page3HighSellerShare", "High-Seller Share of Lost Sales (P6)", 16, 396, 300, 80, "High sellers share"),
        measure_card("page3TopSkuShare", "Top SKU Share of Lost Sales (P6)", 326, 396, 300, 80, "Top SKU share"),
        measure_card("page3Top3SkuShare", "Top 3 SKU Share of Lost Sales (P6)", 636, 396, 300, 80, "Top 3 SKU share"),
        phase6_caption_visual("page3Scope", 946, 396, 318, 104),
        table_visual("page3VoltixEpisodes", 16, 588, 610, 128, [
            column_projection("p6_et_episodes", "retail_year", "ep.retail_year", "Year"),
            column_projection("p6_et_episodes", "episodes", "ep.episodes", "Episodes"),
            column_projection("p6_et_episodes", "mean_weeks_out", "ep.mean_weeks_out", "Mean weeks out"),
            column_projection("p6_et_episodes", "full_weeks_out", "ep.full_weeks_out", "Full weeks out"),
        ], "Voltix stock-out episodes nearly doubled: 609 (H2 2024) to 1,181 (H2 2025) (fact, P3-E2024/E2025)", [categorical_filter(filter_name("p3-voltix-episodes"), "p6_et_episodes", "supplier_name", ["Voltix Distribution Ltd"])]),
        table_visual("page3VoltixTest", 836, 242, 428, 150, [
            column_projection("p6_et_supplier_test", "metric", "test.metric", "Test metric"),
            column_projection("p6_et_supplier_test", "difference", "test.difference", "Difference"),
            column_projection("p6_et_supplier_test", "ci_low", "test.ci_low", "CI low"),
            column_projection("p6_et_supplier_test", "ci_high", "test.ci_high", "CI high"),
            column_projection("p6_et_supplier_test", "permutation_p_two_sided", "test.permutation_p_two_sided", "Permutation p"),
        ], "Voltix supplier test: +6.8pp stock-out rate difference (statistical association, P3-S1)", [categorical_filter(filter_name("p3-voltix-test"), "p6_et_supplier_test", "supplier", ["Voltix Distribution Ltd"])]),
        measure_card("page3LostGross", "Lost Sales Gross (P6)", 16, 504, 300, 80, "Estimated gross lost sales"),
        measure_card("page3LostNet", "Lost Sales Net of Deferred Demand (P6)", 326, 504, 300, 80, "After deferred demand"),
        measure_card("page3RangeLow", "Lost Sales Range Low (P6)", 636, 504, 300, 80, "Sensitivity range low"),
        measure_card("page3RangeHigh", "Lost Sales Range High (P6)", 946, 504, 318, 80, "Sensitivity range high"),
        measure_card("page3VoltixWording", "Voltix Wording", 638, 588, 626, 128, "Required wording"),
    ]
    return page_spec(
        "ReportSection3ProductInventory", "3 Product and inventory", visuals,
        page_filters=[categorical_filter(filter_name("p3-page-category"), "Product", "category", ["Electronics & Tech"])],
    )


def build_page4() -> dict:
    """Page 4: returns and quality signals ("Faulty" returns by product, supplier and cohort)."""
    faulty_filter = categorical_filter(filter_name("p4-faulty-card"), "Returns", "return_reason", ["Faulty"])
    visuals: list[tuple[str, dict]] = [
        text_visual("page4Title", 16, 8, 1248, 36, "Returns and product-quality signals", "22pt", "#111111"),
        text_visual("page4Subtitle", 16, 44, 1248, 24, "Returns and sale-cohort analysis."),
        page_slicer("page4Period", 16, 72, 235, "Period", "Date", "period_label", "f.period_label", "Period"),
        page_slicer("page4Category", 261, 72, 235, "Category", "Product", "category", "f.category", "Category"),
        page_slicer("page4Reason", 506, 72, 235, "Return reason", "Returns", "return_reason", "f.return_reason", "Return reason"),
        page_slicer("page4Supplier", 751, 72, 235, "Supplier", "Product", "supplier_name", "f.supplier_name", "Supplier"),
        page_slicer("page4Store", 996, 72, 268, "Store", "Store", "store_name", "f.store_name", "Store"),
        # Cards sit on their own band under the slicer rail, tall enough for the full
        # category label; the scope caption moves to the bottom band.
        measure_card("page4ReturnsYoY", "Returns Value YoY", 16, 154, 390, 92, "Returns value change"),
        measure_card("page4ReturnsYoYPct", "Returns Value YoY %", 418, 154, 390, 92, "Returns value change %"),
        measure_card("page4FaultyValue", "Returns Value", 820, 154, 444, 92, "Faulty refunds", {"filters": [faulty_filter]}),
        ("page4Reasons", visual(
            "page4Reasons", 16, 250, 385, 198, "barChart",
            {"CategoryAxis": {"projections": [column_projection("Returns", "return_reason", "r.return_reason", "Return reason")]},
             "Y": {"projections": [measure_projection("Returns Value YoY", "m.ReturnsValueYoY")]}},
            title="'Faulty' returns rose +\u20ac31,589 (+90%) YoY; other reasons were flat or fell (fact, P4-01/02/R0-3)",
            sort=sort_def(measure_ref("Returns Value YoY"), "Descending"),
        )),
        ("page4Stores", visual(
            "page4Stores", 413, 250, 424, 198, "barChart",
            {"CategoryAxis": {"projections": [column_projection("p6_faulty_by_store", "store_id", "fs.store_id", "Store")]},
             "Y": {"projections": [
                 sum_projection("p6_faulty_by_store", "rate_per_100_py", "fs", "Faulty per 100 sold, 2024"),
                 sum_projection("p6_faulty_by_store", "rate_per_100_cy", "fs", "Faulty per 100 sold, 2025"),
             ]}},
            title="Five highest-rate stores (S07, S13-S16) show 2025 faulty rates of 4.0-4.8 per 100 sold, up from 1.1-1.9 in 2024 (fact, P4-SS07/13-16)",
            # Sort by the same aggregated field the 2025 series is bound to; a raw
            # column reference does not match the projection and Desktop falls back
            # to alphabetical order.
            sort=sort_def(aggregation_ref("p6_faulty_by_store", "rate_per_100_cy"), "Descending"),
            objects=metadata_color_objects({
                "Sum(p6_faulty_by_store.rate_per_100_py)": COLOR_PY,
                "Sum(p6_faulty_by_store.rate_per_100_cy)": COLOR_CLUSTER,
            }),
        )),
        ("page4Cohort", visual(
            "page4Cohort", 849, 250, 415, 198, "lineChart",
            {"CategoryAxis": {"projections": [column_projection("Date", "calendar_month", "d.calendar_month", "Sale month")]},
             "Series": {"projections": [column_projection("Date", "calendar_year", "d.calendar_year", "Sale year")]},
             "Y": {"projections": [measure_projection("Returned Units per 100 Sold (Sale Cohort)", "m.ReturnedUnitsPer100SoldSaleCohort")]}},
            title="Faulty rate by sale month peaked at 3.0 per 100 for the Nov 2025 cohort (fact, P4-K202511)",
            sort=sort_def(column_ref("Date", "calendar_month")),
            objects=category_color_objects("Date", "calendar_year", {2025: COLOR_CLUSTER, 2024: COLOR_PY}),
            filter_config={"filters": [
                categorical_filter(filter_name("p4-cohort-faulty"), "Returns", "return_reason", ["Faulty"]),
                categorical_filter(filter_name("p4-cohort-year"), "Date", "calendar_year", [2024, 2025]),
            ]},
        )),
        table_visual("page4FaultySupplier", 16, 456, 408, 134, [
            column_projection("p6_faulty_by_supplier", "supplier_name", "fsu.supplier_name", "Supplier"),
            column_projection("p6_faulty_by_supplier", "rate_per_100_py", "fsu.rate_per_100_py", "Faulty per 100 sold, 2024"),
            column_projection("p6_faulty_by_supplier", "rate_per_100_cy", "fsu.rate_per_100_cy", "Faulty per 100 sold, 2025"),
            column_projection("p6_faulty_by_supplier", "value_change", "fsu.value_change", "Refund change"),
        ], "Faulty refund rates rose across suppliers in H2 2025 vs H2 2024 (fact, P4-02)"),
        table_visual("page4FaultyProduct", 436, 456, 401, 134, [
            column_projection("p6_faulty_by_product", "product_id", "fp.product_id", "Product"),
            column_projection("p6_faulty_by_product", "rate_per_100_py", "fp.rate_per_100_py", "Faulty per 100 sold, 2024"),
            column_projection("p6_faulty_by_product", "rate_per_100_cy", "fp.rate_per_100_cy", "Faulty per 100 sold, 2025"),
            column_projection("p6_faulty_by_product", "value_change", "fp.value_change", "Refund change"),
        ], "Top 5 products are 53% of the gross faulty-returns increase (fact, P4-C2)"),
        table_visual("page4Investigation", 849, 456, 415, 134, [
            column_projection("p6_investigations", "topic", "i.topic", "Investigation"),
            column_projection("p6_investigations", "known", "i.known", "Known"),
            column_projection("p6_investigations", "unknown", "i.unknown", "Unknown"),
            column_projection("p6_investigations", "data_required", "i.data_required", "Data required"),
        ], "Priority 3: investigation panel", [categorical_filter(filter_name("p4-investigation"), "p6_investigations", "priority", [3])]),
        phase6_caption_visual("page4Scope", 16, 594, 420, 124),
        # Neutral note. The governed dashboard design asks for a "recorded reason
        # is not a verified defect" callout, but no governed wording measure supplies
        # that sentence, so the panel records the gap rather than paraphrasing
        # docs/06_root_cause_analysis.md into a dashboard claim.
        text_visual("page4DefectPlaceholder", 448, 594, 816, 124,
                    "WORDING NOT AVAILABLE: no governed wording measure supplies this "
                    "callout text, so no evidence claim is made here.", "11pt"),
    ]
    return page_spec(
        "ReportSection4ReturnsQuality", "4 Returns and quality signals", visuals,
        visual_interactions=[{"source": "page4Period", "target": "page4Cohort", "type": "NoFilter"}],
    )


def build_page5() -> dict:
    """Page 5: promotions and Home & Kitchen (coverage, method effects, post-promotion dip)."""
    visuals: list[tuple[str, dict]] = [
        text_visual("page5Title", 16, 8, 1248, 36, "Promotions and Home & Kitchen", "22pt", "#111111"),
        text_visual("page5Subtitle", 16, 44, 1248, 24,
                    "Promotion effects are method-specific; guarded results are not additive. "
                    "Revenue cards are blank by design: a category filter reaches Promotion through Sales, "
                    "and sales and returns share a promotion key that limits the comparison.", "9pt"),
        page_slicer("page5Period", 16, 72, 225, "Period", "Date", "period_label", "f.period_label", "Period"),
        page_slicer("page5Region", 251, 72, 225, "Region", "Store", "region", "f.region", "Region"),
        page_slicer("page5Format", 486, 72, 225, "Store format", "Store", "store_format", "f.store_format", "Store format"),
        page_slicer("page5Store", 721, 72, 543, "Store", "Store", "store_name", "f.store_name", "Store"),
    ]
    card_specs = [
        ("Net Revenue", "Net Revenue"), ("Units YoY %", "Units YoY %"),
        ("ASP", "ASP"), ("ASP PY", "ASP PY"), ("Gross Margin YoY", "Gross Margin YoY"),
        ("Promotion Events (P6)", "Promotion Events (P6)"),
        ("Discount Rate", "Discount Rate"), ("Discount Rate PY", "Discount Rate PY"),
        ("Promotion Share", "Promotion Share"), ("Promotion Share PY", "Promotion Share PY"),
    ]
    for index, (measure, title) in enumerate(card_specs):
        visuals.append(measure_card(
            f"page5Kpi{index + 1}", measure, 16 + (index % 5) * 250,
            154 + (index // 5) * 84, 240, 80, title,
        ))
    visuals.extend([
        ("page5CoverageDepth", visual(
            "page5CoverageDepth", 16, 322, 610, 132, "lineChart",
            {"CategoryAxis": {"projections": [column_projection("p6_hk_weekly", "retail_week", "hk.retail_week", "Retail week")]},
             "Y": {"projections": [
                 sum_projection("p6_hk_weekly", "promo_coverage_cy", "hk", "Coverage, 2025"),
                 sum_projection("p6_hk_weekly", "promo_coverage_py", "hk", "Coverage, 2024"),
                 sum_projection("p6_hk_weekly", "discount_depth_cy", "hk", "Discount depth, 2025"),
                 sum_projection("p6_hk_weekly", "discount_depth_py", "hk", "Discount depth, 2024"),
             ]}},
            title="Promotion events rose to 8,848 in H2 2025 from 2,427 in H2 2024 (fact, P5-E2024/E2025)",
            sort=sort_def(column_ref("p6_hk_weekly", "retail_week")),
            objects=metadata_color_objects({
                "Sum(p6_hk_weekly.promo_coverage_cy)": COLOR_CLUSTER,
                "Sum(p6_hk_weekly.promo_coverage_py)": COLOR_PY,
                "Sum(p6_hk_weekly.discount_depth_cy)": COLOR_VOLTIX,
                "Sum(p6_hk_weekly.discount_depth_py)": COLOR_CONTROL,
            }),
        )),
        ("page5WeeklySales", visual(
            "page5WeeklySales", 638, 322, 626, 132, "lineChart",
            {"CategoryAxis": {"projections": [column_projection("p6_hk_weekly", "retail_week", "hk.retail_week", "Retail week")]},
             "Y": {"projections": [
                 sum_projection("p6_hk_weekly", "sales_revenue_cy", "hk", "Sales, 2025"),
                 sum_projection("p6_hk_weekly", "sales_revenue_py", "hk", "Sales, 2024"),
             ]}},
            title="Home & Kitchen weekly sales revenue down \u20ac240k YoY in H2 2025 (fact, P5-02)",
            sort=sort_def(column_ref("p6_hk_weekly", "retail_week")),
            objects=metadata_color_objects({
                "Sum(p6_hk_weekly.sales_revenue_cy)": COLOR_CLUSTER,
                "Sum(p6_hk_weekly.sales_revenue_py)": COLOR_PY,
            }),
        )),
        ("page5MethodEffects", visual(
            "page5MethodEffects", 16, 460, 610, 146, "barChart",
            {"CategoryAxis": {"projections": [column_projection("p6_hk_methods", "method_code", "hk.method_code", "Method")]},
             "Y": {"projections": [measure_projection("HK Method Effect Guarded", "m.HKMethodEffectGuarded")]}},
            title="All four promotion methods disagree in sign: M1 -\u20ac186k and M4 -\u20ac265k vs M2 +\u20ac98k and M3 +\u20ac79k; guarded, so they are never summed (estimate, P5-M1/M2/M3/M4)",
            sort=sort_def(column_ref("p6_hk_methods", "sort_order")),
        )),
        table_visual("page5MethodIntervals", 638, 460, 626, 146, [
            column_projection("p6_hk_methods", "method_code", "hk.method_code", "Method"),
            column_projection("p6_hk_methods", "interval_type", "hk.interval_type", "Interval type"),
            column_projection("p6_hk_methods", "ci_low", "hk.ci_low", "CI low"),
            column_projection("p6_hk_methods", "ci_high", "hk.ci_high", "CI high"),
        ], "Confidence and range bounds exclude zero for M1, M2 and M4; M3 has no interval reported (estimate, P6 hk_promotion_counterfactuals)", sort=sort_def(column_ref("p6_hk_methods", "sort_order"))),
        # Two values in a 100px box: a bar chart showed only Desktop's too-small placeholder (the
        # smallest chart that renders in this report is 132px), so this is a two-row table.
        # The box is not enlarged because that would move the visuals around it.
        # In 100px a titled table showed only its header. The title is off (its text, evidence
        # label and register code move to the alt text), the grid is 9pt with no row padding and
        # no wrapping, so the header and both rows fit without a scrollbar. Built with visual()
        # directly so the shared table_visual defaults stay unchanged for every other table.
        ("page5PostPromotionDip", visual(
            "page5PostPromotionDip", 16, 612, 400, 100, "tableEx",
            {"Values": {"projections": [
                column_projection("p6_hk_events_by_year", "retail_year", "events.retail_year", "Year"),
                sum_projection("p6_hk_events_by_year", "post_dip_revenue", "events", "Post-promotion shortfall"),
            ]}},
            objects={"columnHeaders": [{"properties": {"show": True, "fontSize": 9, "wordWrap": False}}],
                     "values": [{"properties": {"fontSize": 9, "wordWrap": False}}],
                     "grid": [{"properties": {"rowPadding": 0.0}}],
                     "total": [{"properties": {"show": False, "totals": False}}]},
            alt="Post-promotion shortfall: \u20ac23K (2024) to \u20ac110K (2025) (estimate, P5-D2024/D2025)",
            sort=sort_def(column_ref("p6_hk_events_by_year", "retail_year")),
        )),
        measure_card("page5PromotionWording", "Promotion Wording", 426, 612, 400, 100, "Promotion evidence"),
        phase6_caption_visual("page5Scope", 836, 612, 428, 100),
    ])
    return page_spec(
        "ReportSection5Promotions", "5 Promotions and Home & Kitchen", visuals,
        page_filters=[categorical_filter(filter_name("p5-page-category"), "Product", "category", ["Home & Kitchen"])],
    )


def build_page6() -> dict:
    """Page 6: the Phase 6 evidence matrix, one row per driver."""
    visuals: list[tuple[str, dict]] = [
        text_visual("page6Title", 16, 8, 1248, 36, "Evidence matrix", "22pt", "#111111"),
        text_visual("page6Subtitle", 16, 44, 1248, 24, "Evidence level and impact are shown per driver; overlapping rows are not additive."),
        page_slicer("page6EvidenceLevel", 16, 72, 260, "Evidence level", "p6_evidence_matrix", "evidence_level", "em.evidence_level", "Evidence level"),
        page_slicer("page6Driver", 286, 72, 420, "Driver", "p6_evidence_matrix", "driver", "em.driver", "Driver"),
        table_visual("page6EvidenceMatrix", 16, 154, 1248, 450, [
            column_projection("p6_evidence_matrix", "driver", "em.driver", "Driver"),
            column_projection("p6_evidence_matrix", "evidence_level", "em.evidence_level", "Evidence level"),
            column_projection("p6_evidence_matrix", "evidence_strength", "em.evidence_strength", "Causal evidence strength"),
            column_projection("p6_evidence_matrix", "cause_status", "em.cause_status", "Cause status"),
            measure_projection("Driver Impact (single driver)", "m.DriverImpactSingleDriver"),
            column_projection("p6_evidence_matrix", "what_we_know", "em.what_we_know", "What we know"),
            column_projection("p6_evidence_matrix", "what_we_do_not_know", "em.what_we_do_not_know", "What we do not know"),
            column_projection("p6_evidence_matrix", "additional_data_required", "em.additional_data_required", "Additional data required"),
        ], "Only 1 of 9 evidence-matrix drivers has root-cause evidence; most are observed changes, hypotheses or associations", sort=sort_def(column_ref("p6_evidence_matrix", "sort_order"))),
        phase6_caption_visual("page6Scope", 16, 608, 420, 108),
    ]
    return page_spec("ReportSection6EvidenceMatrix", "6 Evidence matrix", visuals)


def build_page7() -> dict:
    """Page 7: investigation priorities from the Phase 6 investigations table."""
    visuals: list[tuple[str, dict]] = [
        text_visual("page7Title", 16, 8, 1248, 36, "Investigation priorities and ownership", "22pt", "#111111"),
        text_visual("page7Subtitle", 16, 44, 1248, 24, "Knowns, unknowns, required data, and accountable owners."),
        table_visual("page7Investigations", 16, 84, 1248, 498, [
            column_projection("p6_investigations", "priority", "i.priority", "Priority"),
            column_projection("p6_investigations", "topic", "i.topic", "Topic"),
            column_projection("p6_investigations", "evidence_level", "i.evidence_level", "Evidence level"),
            column_projection("p6_investigations", "known", "i.known", "Known"),
            column_projection("p6_investigations", "unknown", "i.unknown", "Unknown"),
            column_projection("p6_investigations", "why_it_matters", "i.why_it_matters", "Why it matters"),
            # Bound as the raw column with no aggregation, so the table never returns
            # only one row: a measure on this table's overlapping slice collapsed the
            # rows in Desktop. The overlap caveat stays in the visual tooltip.
            column_projection("p6_investigations", "slice_of_decline_eur", "i.slice_of_decline_eur", "Slice of decline (EUR)"),
            column_projection("p6_investigations", "data_required", "i.data_required", "Data required"),
            column_projection("p6_investigations", "proposed_owner", "i.proposed_owner", "Proposed owner"),
            column_projection("p6_investigations", "owner_note", "i.owner_note", "Owner note"),
        ], "All 5 open investigations need additional data before the cause can be confirmed (P6 investigations register)"),
        phase6_caption_visual("page7Scope", 16, 592, 420, 110),
    ]
    return page_spec("ReportSection7Investigation", "7 Investigation priorities", visuals)


def binding_parameter(name: str, field_expr: dict) -> dict:
    """A tooltip or drill-through page binding parameter."""
    return {"name": name, "fieldExpr": field_expr}


def build_page8() -> dict:
    """Page 8: the 13-week forecast, its intervals and the model comparison."""
    visuals: list[tuple[str, dict]] = [
        text_visual("page8Title", 16, 8, 1248, 36, "Forecast and model evidence", "22pt", "#111111"),
        text_visual("page8Subtitle", 16, 44, 1248, 24, "Thirteen-week estate forecast with rolling-origin comparison and empirical intervals."),
        table_visual("page8SelectedModel", 16, 80, 360, 146, [
            column_projection("forecast_selected_model", "value", "sel.value", "Selected model"),
        ], "Selected model", [categorical_filter(
                filter_name("p8-selected-model-card"), "forecast_selected_model", "field", ["selected_model"]
            )]),
            text_visual("page8SelectionRule", 16, 230, 360, 92,
                    "SELECTION RULE: the challenger must beat the best eligible baseline on WAPE. The seasonal-naive baseline remains selected.", "9pt"),
        table_visual("page8ModelComparison", 390, 80, 874, 202, [
            column_projection("forecast_model_comparison", "model", "cmp.model", "Model"),
            column_projection("forecast_model_comparison", "family", "cmp.family", "Family"),
            column_projection("forecast_model_comparison", "mean_mae", "cmp.mean_mae", "Mean MAE"),
            column_projection("forecast_model_comparison", "mean_rmse", "cmp.mean_rmse", "Mean RMSE"),
            column_projection("forecast_model_comparison", "mean_wape", "cmp.mean_wape", "Mean WAPE"),
            column_projection("forecast_model_comparison", "mean_mase", "cmp.mean_mase", "Mean MASE"),
            column_projection("forecast_model_comparison", "mean_bias", "cmp.mean_bias", "Mean bias"),
        ], "Rolling-origin model comparison", sort=sort_def(column_ref("forecast_model_comparison", "mean_wape"))),
        ("page8RecentActual", visual(
            "page8RecentActual", 16, 330, 610, 160, "lineChart",
            {"CategoryAxis": {"projections": [column_projection("Date", "retail_week", "d.retail_week", "Retail week")]},
             "Y": {"projections": [projection(measure_ref("Net Revenue"), "m.NetRevenue", "Net Revenue, 2025")]}},
            title="Actual weekly net revenue, H2 2025 (most recent observed weeks, before the forecast)",
            sort=sort_def(column_ref("Date", "retail_week_key")),
            objects=metadata_color_objects({"m.NetRevenue": COLOR_CLUSTER}),
            filter_config={"filters": [categorical_filter(filter_name("p8-recent-actual"), "Date", "period_label", ["H2 2025"])]},
        )),
        ("page8ForecastPoint", visual(
            "page8ForecastPoint", 638, 330, 626, 160, "lineChart",
            {"CategoryAxis": {"projections": [column_projection("forecast_weekly", "week_start_date", "fc.week_start_date", "Forecast week start")]},
             "Y": {"projections": [projection(
                 aggregation_ref("forecast_weekly", "point_forecast"),
                 "Sum(forecast_weekly.point_forecast)", "Point forecast (\u20ac)")]}},
            title="13-week point forecast follows directly after the actual weeks shown on the left",
            sort=sort_def(column_ref("forecast_weekly", "week_start_date")),
            filter_config={"filters": [categorical_filter(
                filter_name("p8-selected-model"), "forecast_weekly", "model", ["B2_seasonal_naive"]
            )]},
        )),
        ("page8ForecastIntervals", visual(
            "page8ForecastIntervals", 16, 498, 1248, 160, "lineChart",
            {"CategoryAxis": {"projections": [column_projection("forecast_intervals", "week_start_date", "fi.week_start_date", "Forecast week start")]},
             "Y": {"projections": [
                 sum_projection("forecast_intervals", "lower", "fi", "Lower bound"),
                 sum_projection("forecast_intervals", "upper", "fi", "Upper bound"),
             ]}},
            title="95% empirical interval bounds: seasonal-naive has the lowest rolling-origin WAPE at 7.7% vs 34% for the challenger",
            sort=sort_def(column_ref("forecast_intervals", "week_start_date")),
            filter_config={"filters": [
                categorical_filter(filter_name("p8-interval-model"), "forecast_intervals", "model", ["B2_seasonal_naive"]),
                categorical_filter(filter_name("p8-interval-coverage"), "forecast_intervals", "coverage", [0.95]),
            ]},
        )),
        text_visual("page8Limitations", 16, 666, 1248, 44,
                    "FORECAST EVIDENCE: 104 observed weeks across two retail years; constant-width empirical intervals. The challenger did not beat the seasonal-naive baseline. "
                    "The actual-revenue panel (left) uses retail week; the forecast panels use calendar week start date, so the two axes are not perfectly contiguous.", "10pt"),
    ]
    return page_spec("ReportSection8Forecast", "8 Forecast", visuals)



def build_page9() -> dict:
    """Page 9: data quality, built only from the seven standalone DQ extracts with no DAX."""
    visuals: list[tuple[str, dict]] = [
        text_visual("page9Title", 16, 8, 1248, 36, "Data quality", "22pt", "#111111"),
        # Subtitle wording is governed: FAIL records that a rule found an issue and that
        # the rule treated it. It is not a statement that the analysis is unusable.
        text_visual("page9Subtitle", 16, 46, 1248, 24,
                    "FAIL = issue detected and treated by its rule; treated data feeds the analysis.", "10pt"),
    ]

    # KPI band. Counts come from the governed extracts with a column Count and a visual
    # filter, so no DAX measure is introduced on this page.
    card_specs = [
        ("page9RulesRun", "dq_rule_results", "rule_id", "Rules run", "Phase 3 rules evaluated",
         None, "Count"),
        ("page9RulesPass", "dq_rule_results", "rule_id", "Rules PASS", "Rules with status PASS",
         categorical_filter(filter_name("dq-status-pass"), "dq_rule_results", "status", ["PASS"]), "Count"),
        ("page9RulesFail", "dq_rule_results", "rule_id", "Rules FAIL", "Rules with status FAIL",
         categorical_filter(filter_name("dq-status-fail"), "dq_rule_results", "status", ["FAIL"]), "Count"),
        ("page9RulesInfo", "dq_rule_results", "rule_id", "Rules INFO", "Advisory rules with status INFO",
         categorical_filter(filter_name("dq-status-info"), "dq_rule_results", "status", ["INFO"]), "Count"),
        # rows_failed summed over the six rules whose treatment is QUARANTINE (145). Labelled
        # as rule failures because de-duplication also quarantines rows under other rules.
        ("page9RulesQuarantineFailed", "dq_rule_results", "rows_failed", "Quarantine-rule fails",
         "dq_rule_results[rows_failed] where treatment = QUARANTINE",
         categorical_filter(filter_name("dq-treatment-quarantine"), "dq_rule_results", "treatment", ["QUARANTINE"]),
         "Sum"),
        # Governed value: reports/phase3/lineage.json quarantine_rows, via dq_quarantine_by_table.
        ("page9RowsQuarantined", "dq_quarantine_by_table", "rows_quarantined", "Rows quarantined",
         "dq_quarantine_by_table[rows_quarantined] from reports/phase3/lineage.json", None, "Sum"),
        # Count `check`, which is never blank, so every validation row is counted once.
        ("page9ValidationPass", "curated_validation", "check", "Curated PASS",
         "Curated validation checks with status PASS",
         categorical_filter(filter_name("dq-validated-pass"), "curated_validation", "status", ["PASS"]), "Count"),
        ("page9ValidationWarn", "curated_validation", "check", "Curated WARN",
         "Curated validation checks with status WARN",
         categorical_filter(filter_name("dq-validated-warn"), "curated_validation", "status", ["WARN"]), "Count"),
    ]
    # Eight cards across the 1,248px content width: 150px each on a 156px pitch.
    for index, (name, entity, column, label, title, rule_filter, aggregate) in enumerate(card_specs):
        visuals.append(column_card(
            name, entity, column, label, 16 + index * 156, 72, 150, 84, title,
            [rule_filter] if rule_filter else None, aggregate,
        ))

    visuals.extend([
        # Reconciliation is shown as a table of raw against curated values. It makes no
        # pass or fail claim: the governed H2 headline is checked in the Phase 4 and
        # Phase 6 reconciliation gates, not on this page.
        table_visual("page9KpiReconciliation", 16, 160, 400, 170, [
            column_projection("kpi_reconciliation", "kpi", "kr.kpi", "KPI"),
            sum_projection("kpi_reconciliation", "raw_as_reported", "kr", "Raw as reported"),
            sum_projection("kpi_reconciliation", "clean_complete", "kr", "Curated complete"),
            sum_projection("kpi_reconciliation", "change_pct", "kr", "Change %"),
        ], "KPI reconciliation: raw vs curated"),
        ("page9QuarantineByTable", visual(
            "page9QuarantineByTable", 424, 160, 202, 170, "barChart",
            {"CategoryAxis": {"projections": [
                column_projection("dq_quarantine_by_table", "table", "dqq.table", "Table")]},
             "Y": {"projections": [
                 sum_projection("dq_quarantine_by_table", "rows_quarantined", "dqq", "Rows quarantined")]}},
            title="Quarantined rows by table",
            sort=sort_def(aggregation_ref("dq_quarantine_by_table", "rows_quarantined", 0), "Descending"),
        )),
        table_visual("page9ChecksBySeverity", 638, 160, 626, 170, [
            column_projection("dq_rule_results", "severity", "dq.severity", "Severity"),
            column_projection("dq_rule_results", "dimension", "dq.dimension", "Dimension"),
            column_projection("dq_rule_results", "treatment", "dq.treatment", "Treatment"),
            column_projection("dq_rule_results", "status", "dq.status", "Status"),
            sum_projection("dq_rule_results", "rows_checked", "dq", "Rows checked"),
            sum_projection("dq_rule_results", "rows_failed", "dq", "Rows failed"),
        ], "Phase 3 checks by severity, dimension, treatment and status"),
        ("page9IssueActions", visual(
            "page9IssueActions", 16, 334, 610, 180, "barChart",
            {"CategoryAxis": {"projections": [
                column_projection("dq_issue_log", "action", "dq.action", "Action")]},
             "Y": {"projections": [
                 count_projection("dq_issue_log", "rule_id", "dq", "Logged issues")]}},
            title="Issue-log actions by type",
            sort=sort_def(aggregation_ref("dq_issue_log", "rule_id", COUNT_ROWS), "Descending"),
        )),
        # Stacked bar (barChart is the stacked variant): one bar per table, segments by severity.
        ("page9IssueSeverity", visual(
            "page9IssueSeverity", 638, 334, 626, 180, "barChart",
            {"CategoryAxis": {"projections": [
                column_projection("dq_issue_log", "table_name", "dq.table_name", "Table")]},
             "Series": {"projections": [
                 column_projection("dq_issue_log", "severity", "dq.severity", "Severity")]},
             "Y": {"projections": [
                 count_projection("dq_issue_log", "rule_id", "dq", "Logged issues")]}},
            title="Issue-log rows by table and severity",
            sort=sort_def(aggregation_ref("dq_issue_log", "rule_id", COUNT_ROWS), "Descending"),
        )),
        table_visual("page9StoreWeekGate", 16, 518, 610, 180, [
            column_projection("dq_store_week_health", "store_id", "sw.store_id", "Store"),
            column_projection("dq_store_week_health", "retail_week_key", "sw.retail_week_key", "Retail week"),
            column_projection("dq_store_week_health", "dq_sales_status", "sw.dq_sales_status", "Sales DQ status"),
            column_projection("dq_store_week_health", "dq_inventory_status", "sw.dq_inventory_status", "Inventory DQ status"),
            # Text list of failed checks. As a Sum on a mistyped column it errored and blanked the table.
            column_projection("dq_store_week_health", "dq_checks_failed", "sw.dq_checks_failed", "Failed checks"),
        ], "Phase 9 data-quality gate by store-week (2,080 store-weeks)"),
        table_visual("page9CheckCatalogue", 638, 518, 626, 180, [
            column_projection("dq_check_catalogue", "check_id", "cc.check_id", "Check"),
            column_projection("dq_check_catalogue", "check", "cc.check", "Name"),
            column_projection("dq_check_catalogue", "severity", "cc.severity", "Severity"),
            column_projection("dq_check_catalogue", "tolerance", "cc.tolerance", "Tolerance"),
            column_projection("dq_check_catalogue", "blocks_business_alerts", "cc.blocks_business_alerts", "Blocks alerts"),
        ], "Check catalogue (C1 to C12)"),
    ])
    return page_spec("ReportSection9DataQuality", "9 Data quality", visuals)


def build_t1_tooltip() -> dict:
    """Hidden tooltip page T1: KPI definitions for the KPI cards."""
    definitions = (
        "Net Revenue: Sales Revenue minus Returns Value.\n"
        "Net Revenue YoY %: growth versus the same period one year earlier.\n"
        "Gross Margin %: Gross Margin as a share of Net Revenue.\n"
        "Transactions: distinct receipts; category counts are not additive.\n"
        "Return Rate: Returns Value as a share of Sales Revenue."
    )
    parameters = [
        binding_parameter(name, measure_ref(name))
        for name in ("Net Revenue", "Net Revenue YoY %", "Gross Margin %", "Transactions", "Return Rate")
    ]
    spec = page_spec(
        "ReportSectionT1KpiTooltip", "T1 KPI definitions", [
            text_visual("t1Title", 12, 8, 296, 26, "KPI definitions", "14pt", "#111111"),
            text_visual("t1Definitions", 12, 38, 296, 118, definitions, "8pt"),
            measure_card("t1NetRevenue", "Net Revenue", 12, 160, 142, 50, "Net Revenue"),
            measure_card("t1NetRevenuePY", "Net Revenue PY", 162, 160, 146, 50, "Net Revenue PY"),
            text_visual("t1EvidenceTag", 12, 216, 296, 18, "Evidence tag: FACT", "9pt"),
        ],
        page_type="Tooltip",
        page_binding={"name": "T1KpiDefinitions", "type": "Tooltip", "parameters": parameters},
        width=320,
        height=240,
    )
    spec["page"]["visibility"] = "HiddenInViewMode"
    return spec


def build_t2_tooltip() -> dict:
    """Hidden tooltip page T2: evidence details for a driver."""
    fields = ("driver", "evidence_level", "cause_status", "method", "confidence", "additional_data_required")
    parameters = [
        binding_parameter(f"p6_evidence_matrix[{field}]", column_ref("p6_evidence_matrix", field))
        for field in fields
    ]
    spec = page_spec(
        "ReportSectionT2EvidenceTooltip", "T2 Evidence details", [
            text_visual("t2Title", 12, 8, 296, 26, "Evidence details", "14pt", "#111111"),
            table_visual("t2Evidence", 12, 40, 296, 164, [
                column_projection("p6_evidence_matrix", "driver", "tip.driver", "Driver"),
                column_projection("p6_evidence_matrix", "evidence_level", "tip.evidence_level", "Evidence level"),
                column_projection("p6_evidence_matrix", "cause_status", "tip.cause_status", "Cause status"),
                column_projection("p6_evidence_matrix", "method", "tip.method", "Method"),
                column_projection("p6_evidence_matrix", "confidence", "tip.confidence", "Confidence"),
                column_projection("p6_evidence_matrix", "additional_data_required", "tip.additional_data_required", "Additional data required"),
            ], "Evidence, method and remaining data"),
            phase6_caption_visual("t2Scope", 12, 210, 296, 28),
        ],
        page_type="Tooltip",
        page_binding={"name": "T2EvidenceDetails", "type": "Tooltip", "parameters": parameters},
        width=320,
        height=240,
    )
    spec["page"]["visibility"] = "HiddenInViewMode"
    return spec


def back_button_visual(name: str, x: int, y: int) -> tuple[str, dict]:
    """A Back action button for drill-through pages."""
    return name, {
        "$schema": f"{SCHEMA}/report/definition/visualContainer/2.13.0/schema.json",
        "name": name,
        "position": {"x": x, "y": y, "z": 0, "height": 36, "width": 92, "tabOrder": 0},
        "visual": {
            "visualType": "actionButton",
            "visualContainerObjects": {
                "title": title_block("Back"),
                "visualLink": [{"properties": {
                    "show": pbir_literal(True),
                    "type": pbir_literal("Back"),
                }}],
            },
        },
    }


def build_d1_drillthrough() -> dict:
    """Hidden drill-through page D1: store detail, keeping all filter context."""
    field_expr = column_ref("Store", "store_label")
    spec = page_spec(
        "ReportSectionD1StoreDetail", "D1 Store detail", [
            back_button_visual("d1Back", 16, 8),
            text_visual("d1Title", 120, 8, 1144, 36, "Store detail", "22pt", "#111111"),
            measure_card("d1NetRevenue", "Net Revenue", 16, 56, 300, 64, "Net Revenue"),
            measure_card("d1Transactions", "Transactions", 326, 56, 300, 64, "Transactions"),
            measure_card("d1Availability", "Availability", 636, 56, 300, 64, "Availability"),
            table_visual("d1StoreProfile", 16, 132, 600, 130, [
                column_projection("Store", "store_label", "store.store_label", "Store"),
                column_projection("Store", "region", "store.region", "Region"),
                column_projection("Store", "store_format", "store.store_format", "Format"),
                column_projection("Store", "store_group", "store.store_group", "Store group"),
            ], "Selected store"),
            ("d1WeeklyTrend", visual(
                "d1WeeklyTrend", 16, 278, 1248, 390, "lineChart",
                {"CategoryAxis": {"projections": [column_projection("Date", "retail_week", "d.retail_week", "Retail week")]},
                 "Y": {"projections": [measure_projection("Net Revenue"), measure_projection("Net Revenue PY")]}},
                title="Weekly net revenue versus prior year",
                sort=sort_def(column_ref("Date", "retail_week_key")),
            )),
        ],
        page_type="Drillthrough",
        page_binding={"name": "D1StoreDetailBinding", "type": "Drillthrough",
                      "parameters": [binding_parameter("Store[store_label]", field_expr)],
                      "acceptsFilterContext": "Default"},
    )
    spec["page"]["visibility"] = "HiddenInViewMode"
    return spec


def build_d2_drillthrough() -> dict:
    """Hidden drill-through page D2: product detail, keeping all filter context."""
    field_expr = column_ref("Product", "product_label")
    spec = page_spec(
        "ReportSectionD2ProductDetail", "D2 Product detail", [
            back_button_visual("d2Back", 16, 8),
            text_visual("d2Title", 120, 8, 1144, 36, "Product detail", "22pt", "#111111"),
            measure_card("d2NetRevenue", "Net Revenue", 16, 56, 300, 64, "Net Revenue"),
            measure_card("d2Units", "Units", 326, 56, 300, 64, "Units"),
            measure_card("d2Availability", "Availability", 636, 56, 300, 64, "Availability"),
            table_visual("d2ProductProfile", 16, 132, 720, 130, [
                column_projection("Product", "product_label", "product.product_label", "Product"),
                column_projection("Product", "category", "product.category", "Category"),
                column_projection("Product", "subcategory", "product.subcategory", "Subcategory"),
                column_projection("Product", "supplier_name", "product.supplier_name", "Supplier"),
            ], "Selected product"),
            ("d2WeeklyTrend", visual(
                "d2WeeklyTrend", 16, 278, 1248, 390, "lineChart",
                {"CategoryAxis": {"projections": [column_projection("Date", "retail_week", "d.retail_week", "Retail week")]},
                 "Y": {"projections": [measure_projection("Net Revenue")]},
                 # Units is a count against a euro scale, so it rides its own axis.
                 "Y2": {"projections": [measure_projection("Units")]}},
                title="Weekly product performance",
                sort=sort_def(column_ref("Date", "retail_week_key")),
                objects={"secondaryValues": [{"properties": {"show": True}}]},
            )),
        ],
        page_type="Drillthrough",
        page_binding={"name": "D2ProductDetailBinding", "type": "Drillthrough",
                      "parameters": [binding_parameter("Product[product_label]", field_expr)],
                      "acceptsFilterContext": "Default"},
    )
    spec["page"]["visibility"] = "HiddenInViewMode"
    return spec


def attach_page_tooltip(payload: dict, page_name: str) -> None:
    """Point a visual's tooltip at a report tooltip page."""
    container = payload["visual"].setdefault("visualContainerObjects", {})
    container["visualTooltip"] = [{"properties": {
        "show": pbir_literal(True),
        "type": pbir_literal("ReportPage"),
        "section": pbir_literal(page_name),
    }}]


def build_additional_pages() -> list[dict]:
    """Pages 2 to 9, then the hidden tooltip and drill-through pages, in pages.json order."""
    return [
        build_page2(), build_page3(), build_page4(), build_page5(), build_page6(), build_page7(),
        build_page8(), build_page9(),
        build_t1_tooltip(), build_t2_tooltip(), build_d1_drillthrough(), build_d2_drillthrough(),
    ]


def build_report(visuals: list[tuple[str, dict]], additional_pages: list[dict] | None = None) -> dict:
    """Regenerate the whole Report definition folder (theme, report.json, every page)."""
    definition = REPORT / "definition"
    if definition.exists():
        remove_tree(definition)
    legacy_report = REPORT / "report.json"
    if legacy_report.exists():
        assert_report_scope(legacy_report).unlink()

    write(REPORT / "definition.pbir", json.dumps({
        "version": "4.0",
        "datasetReference": {"byPath": {"path": f"../{NAME}.SemanticModel"}},
    }, indent=2) + "\n")

    write(REPORT / ".gitignore", "**/.pbi/localSettings.json\n**/.pbi/cache.abf\n")
    write_json(REPORT / ".platform", {
        "$schema": PLATFORM_SCHEMA,
        "metadata": {"type": "Report", "displayName": NAME},
        "config": {"version": "2.0", "logicalId": REPORT_LOGICAL_ID},
    })

    # Registered resource: the governed Brightwater theme.
    reg = REPORT / "RegisteredResources"
    reg.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(PBI / "brightwater_theme.json",
                    assert_report_scope(reg / "BrightwaterEvidence.json"))

    base_theme_rel = pathlib.Path("StaticResources/SharedResources/BaseThemes/Fluent2-CY26SU09.json")
    base_theme = REPORT / base_theme_rel
    base_theme_source = REFERENCE_REPORT / base_theme_rel
    if base_theme_source.is_file():
        base_theme.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(base_theme_source, assert_report_scope(base_theme))
    elif not base_theme.is_file():
        raise FileNotFoundError(
            f"Desktop PBIR base theme is required from {base_theme_source} "
            f"or an existing generated asset at {base_theme}"
        )

    write(definition / "version.json", json.dumps({
        "$schema": f"{SCHEMA}/report/definition/versionMetadata/1.0.0/schema.json",
        "version": "2.0.0",
    }, indent=2) + "\n")

    write(definition / "report.json", json.dumps({
        "$schema": f"{SCHEMA}/report/definition/report/3.3.0/schema.json",
        "themeCollection": {
            "baseTheme": {"name": "Fluent2-CY26SU09",
                          "reportVersionAtImport": {"visual": "2.13.0", "report": "3.4.0", "page": "2.3.1"},
                          "type": "SharedResources"},
            "customTheme": {"name": "Brightwater Evidence",
                             "reportVersionAtImport": {"visual": "2.13.0", "report": "3.4.0", "page": "2.3.1"},
                            "type": "RegisteredResources"},
        },
        "objects": {
            "section": [{"properties": {"verticalAlignment": {
                "expr": {"Literal": {"Value": "'Top'"}}
            }}}]
        },
        "resourcePackages": [
            {
                "name": "SharedResources",
                "type": "SharedResources",
                "items": [{"name": "Fluent2-CY26SU09",
                           "path": "BaseThemes/Fluent2-CY26SU09.json",
                           "type": "BaseTheme"}],
            },
            {
                "name": "RegisteredResources",
                "type": "RegisteredResources",
                "items": [{"name": "BrightwaterEvidence",
                           "path": "RegisteredResources/BrightwaterEvidence.json",
                           "type": "CustomTheme"}],
            },
        ],
        "settings": {
            "useStylableVisualContainerHeader": True,
            "exportDataMode": "AllowSummarized",
            "defaultDrillFilterOtherVisuals": True,
            "allowChangeFilterTypes": True,
            "useEnhancedTooltips": True,
            "useDefaultAggregateDisplayName": True,
        },
    }, indent=2) + "\n")

    page_dir = definition / "pages" / "ReportSection1ExecutiveOverview"
    page_dir.mkdir(parents=True, exist_ok=True)

    write(page_dir / "page.json", json.dumps({
        "$schema": f"{SCHEMA}/report/definition/page/2.1.0/schema.json",
        "name": "ReportSection1ExecutiveOverview",
        "displayName": "1 Executive Overview",
        "displayOption": "FitToPage",
        "height": PAGE_H,
        "width": PAGE_W,
        "objects": {
            "background": [{"properties": {
                "color": {"solid": {"color": pbir_literal("#F7F6F3")} },
                "transparency": pbir_literal(0.0),
            }}],
        },
    }, indent=2) + "\n")

    written = []
    for name, payload in visuals:
        if payload.get("visual", {}).get("visualType") == "card":
            attach_page_tooltip(payload, "ReportSectionT1KpiTooltip")
        elif name == "driverAttributionWaterfall":
            attach_page_tooltip(payload, "ReportSectionT2EvidenceTooltip")
        write_json(page_dir / "visuals" / name / "visual.json", payload)
        written.append(name)

    page_order = ["ReportSection1ExecutiveOverview"]
    page_visual_counts = {"ReportSection1ExecutiveOverview": len(written)}
    for spec in additional_pages or []:
        for visual_name, payload in spec["visuals"]:
            if (spec["name"].startswith(("ReportSection2", "ReportSection3", "ReportSection4", "ReportSection5"))
                    and payload.get("visual", {}).get("visualType") == "card"):
                attach_page_tooltip(payload, "ReportSectionT1KpiTooltip")
            elif spec["name"] == "ReportSection6EvidenceMatrix" and visual_name == "page6EvidenceMatrix":
                attach_page_tooltip(payload, "ReportSectionT2EvidenceTooltip")
        page_name, count = write_page_spec(definition, spec)
        page_order.append(page_name)
        page_visual_counts[page_name] = count
    write(definition / "pages" / "pages.json", json.dumps({
        "$schema": f"{SCHEMA}/report/definition/pagesMetadata/1.1.0/schema.json",
        "pageOrder": page_order,
        "activePageName": "ReportSection1ExecutiveOverview",
    }, indent=2) + "\n")

    return {"visuals": sum(page_visual_counts.values()), "page_visual_counts": page_visual_counts}


def write_project_files() -> None:
    """The .pbip entry point and the project .gitignore."""
    write(PBIP_ROOT / f"{NAME}.pbip", json.dumps({
        "version": "1.0",
        "artifacts": [{"report": {"path": f"{NAME}.Report"}}],
        "settings": {},
    }, indent=2) + "\n")
    write(PBIP_ROOT / ".gitignore", "**/.pbi/localSettings.json\n**/.pbi/cache.abf\n")


def regenerate_report_only() -> dict:
    """Regenerate the currently implemented PBIR pages without writing the PBIP or SemanticModel."""
    return build_report(build_page1(), build_additional_pages())


_REPORT_QUERY_TABLE_REF = re.compile(r"^(?:'Measures'|Measures)(?=[.\[])")


def rewrite_report_measure_table_refs(payload: object) -> tuple[object, int]:
    """Rename only structured PBIR references to the governed measure-holder table."""
    replacements = 0

    def visit(value: object) -> object:
        nonlocal replacements
        if isinstance(value, dict):
            for key, child in list(value.items()):
                if key in {"Entity", "entity", "table", "Table"} and child == "Measures":
                    value[key] = MEASURE_TABLE
                    replacements += 1
                elif key in {"queryRef", "nativeQueryRef"} and isinstance(child, str):
                    if key == "nativeQueryRef" and child == "Measures":
                        rewritten, count = MEASURE_TABLE, 1
                    else:
                        rewritten, count = _REPORT_QUERY_TABLE_REF.subn(MEASURE_TABLE, child, count=1)
                    value[key] = rewritten
                    replacements += count
                else:
                    value[key] = visit(child)
            return value
        if isinstance(value, list):
            return [visit(child) for child in value]
        return value

    return visit(payload), replacements


def regenerate_measure_table_and_page1() -> dict:
    """Regenerate only the measure table, model order reference, and Page 1 reference JSON."""
    inventory = table_inventory()
    measures = load_measure_defs()
    validate_output_object_names(inventory, measures)

    table_dir = MODEL / "definition" / "tables"
    new_table_path = table_dir / f"{MEASURE_TABLE}.tmdl"
    old_table_path = table_dir / "Measures.tmdl"
    write(new_table_path, render_measures_tmdl(measures))
    if old_table_path.exists() and old_table_path != new_table_path:
        assert_report_scope(old_table_path).unlink()
    write(MODEL / "definition" / "model.tmdl", render_model_tmdl(inventory))

    page_dir = REPORT / "definition" / "pages" / "ReportSection1ExecutiveOverview"
    reference_rewrites = 0
    json_files = sorted(page_dir.rglob("*.json"))
    if not json_files:
        raise FileNotFoundError(f"Page 1 JSON definition not found: {page_dir}")
    for path in json_files:
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload, count = rewrite_report_measure_table_refs(payload)
        if count:
            write_json(path, payload)
            reference_rewrites += count

    stale = []
    for path in json_files:
        payload = json.loads(path.read_text(encoding="utf-8"))
        _, remaining = rewrite_report_measure_table_refs(payload)
        if remaining:
            stale.append(path.relative_to(ROOT).as_posix())
    if stale:
        raise ValueError(f"legacy {MEASURE_TABLE} table references remain in Page 1: {stale}")

    visual_count = sum((path.parent / "visual.json").is_file() for path in page_dir.rglob("visual.json"))
    return {
        "measure_table": MEASURE_TABLE,
        "measure_count": len(measures),
        "measure_table_qualifier_rewrites": sum(
            rewrite_measure_table_qualifiers(measure["expression"])[1] for measure in measures
        ),
        "page1_reference_rewrites": reference_rewrites,
        "page1_visuals": visual_count,
        "stale_table_file_removed": not old_table_path.exists(),
    }


def main() -> None:
    """Full rebuild: derive the quarantine extract, then the semantic model, report and project files."""
    # The earlier build produced an invalid PBIP at powerbi/<name>.pbip/; replace it wholesale.
    # It is the one path this builder may delete outside PBIP_ROOT, and it is named explicitly here
    # rather than reached through a loop, so the exception stays visible and auditable.
    stale = PBI / f"{NAME}.pbip"
    if stale.is_dir():
        if stale.name != f"{NAME}.pbip" or stale.parent != PBI:
            raise SystemExit(f"refusing to remove an unexpected path: {stale}")
        shutil.rmtree(stale)
    PBIP_ROOT.mkdir(parents=True, exist_ok=True)
    quarantined = derive_dq_quarantine_by_table()
    print(f"dq_quarantine_by_table.csv: {quarantined:,} quarantined rows from lineage.json")
    stats = build_semantic_model()
    visuals = build_page1()
    rstats = build_report(visuals, build_additional_pages())
    write_project_files()
    print("semantic model:", json.dumps(stats, indent=2))
    print("report:", json.dumps(rstats, indent=2))
    if stats["untyped_columns"]:
        print("UNRESOLVED COLUMN TYPES (defaulted to string):")
        for c in stats["untyped_columns"]:
            print("  ", c)


if __name__ == "__main__":
    main()

