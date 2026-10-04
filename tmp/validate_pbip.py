"""Validate the generated PBIP before it is opened in Power BI Desktop.

Covers every page, not only Page 1: TMDL structure and grammar, relationships and keys, measure
fidelity against powerbi/dax/measures_tmdl.tmdl, field references, layout, page requirements
(including Page 9 data quality, section 10c), and the published PBIR schemas.

Input: the PBIP under powerbi/Brightwater_Executive_Dashboard/ and the governed sources it is
built from. Output: numbered section lines, then PASSED, or FAILED with one line per problem;
exit code 0 only when every check passes.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys
from collections import defaultdict
from datetime import date, timedelta

ROOT = pathlib.Path(__file__).resolve().parents[1]
PBI = ROOT / "powerbi"
NAME = "Brightwater_Executive_Dashboard"
PBIP = PBI / NAME
REPORT = PBIP / f"{NAME}.Report"
MODEL = PBIP / f"{NAME}.SemanticModel"
REFERENCE_REPORT = ROOT / "tmp" / "pbir_reference" / "reference.Report"
DEF = MODEL / "definition"
PAGE_ROOT = REPORT / "definition" / "pages"
PAGE_DIR = PAGE_ROOT / "ReportSection1ExecutiveOverview"

PAGE_W, PAGE_H = 1280, 720

failures: list[str] = []
notes: list[str] = []


def check(cond: bool, msg: str) -> bool:
    """Record msg as a failure when cond is false; checks never stop the run early."""
    if not cond:
        failures.append(msg)
    return cond


sys.path.insert(0, str(ROOT / "tmp"))
from build_pbip import (CARDINALITY_TMDL, CROSS_FILTER_TMDL, DERIVED_FORECAST_COLUMNS,
                        GENERATED_QUERY_COLUMNS, MEASURE_TABLE,
                        build_additional_pages,
                        load_measure_defs, rewrite_measure_table_qualifiers,
                        validate_output_object_names)  # noqa: E402


# --------------------------------------------------------------------------- 1. JSON parses
json_files = sorted(PBIP.rglob("*.json")) + sorted(PBIP.rglob("*.pbip")) + \
    sorted(PBIP.rglob("*.pbir")) + sorted(PBIP.rglob("*.pbism"))
parsed: dict[pathlib.Path, dict] = {}
for f in json_files:
    try:
        parsed[f] = json.loads(f.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        failures.append(f"JSON parse failed: {f.relative_to(ROOT)}: {exc}")
print(f"[1] JSON files parsed: {len(parsed)}/{len(json_files)}")

# UTF-8 without BOM
for f in json_files:
    if f.read_bytes()[:3] == b"\xef\xbb\xbf":
        failures.append(f"UTF-8 BOM present (PBIP requires no BOM): {f.relative_to(ROOT)}")

# --------------------------------------------------------------------------- 2. TMDL model
def unquote_tmdl_name(name: str) -> str:
    """Strip TMDL single quotes and unescape doubled quotes."""
    if name.startswith("'") and name.endswith("'"):
        return name[1:-1].replace("''", "'")
    return name


def parse_table_metadata(path: pathlib.Path) -> dict:
    """Table name, columns and their properties from one table TMDL file."""
    text = path.read_text(encoding="utf-8")
    table_match = re.search(r"^table\s+(.+?)\s*$", text, re.M)
    table = unquote_tmdl_name(table_match.group(1))
    lines = text.splitlines()
    columns: list[str] = []
    column_properties: dict[str, dict[str, str]] = {}
    calculated_columns: dict[str, str] = {}
    measures: list[str] = []
    partitions: list[tuple[str, str]] = []
    for index, line in enumerate(lines):
        column_match = re.match(
            r"^\tcolumn\s+('(?:[^']|'')+'|[^\s=]+)(?:\s*=.*)?$", line
        )
        if column_match:
            column = unquote_tmdl_name(column_match.group(1))
            columns.append(column)
            props: dict[str, str] = {}
            cursor = index + 1
            while cursor < len(lines) and not re.match(r"^\t(column|measure|partition)\b", lines[cursor]):
                prop = re.match(r"^\t{2}([A-Za-z_]\w*):\s*(.*?)\s*$", lines[cursor])
                if prop:
                    props[prop.group(1)] = prop.group(2)
                else:
                    bare = re.match(r"^\t{2}(isKey|isHidden|isUnique)\s*$", lines[cursor])
                    if bare:
                        props[bare.group(1)] = "true"
                cursor += 1
            column_properties[column] = props
            if "=" in line:
                expression = [line.partition("=")[2].strip()]
                for continuation in lines[index + 1:cursor]:
                    if continuation.startswith("\t\t\t"):
                        expression.append(continuation.strip())
                calculated_columns[column] = "\n".join(expression).strip()

        measure_match = re.match(r"^\tmeasure\s+('(?:[^']|'')+'|[^\s=]+)\s*=", line)
        if measure_match:
            measures.append(unquote_tmdl_name(measure_match.group(1)))
        partition_match = re.match(r"^\tpartition\s+\S+\s*=\s*(m|calculated)\s*$", line)
        if partition_match:
            partitions.append((partition_match.group(1), line))

    category = re.search(r"^\tdataCategory:\s*(.*?)\s*$", text, re.M)
    return {
        "name": table,
        "columns": columns,
        "column_properties": column_properties,
        "calculated_columns": calculated_columns,
        "measures": measures,
        "partitions": partitions,
        "data_category": category.group(1) if category else None,
        "text": text,
    }


tbl_files = sorted((DEF / "tables").glob("*.tmdl"))
table_metadata = {metadata["name"]: metadata for metadata in
                  (parse_table_metadata(path) for path in tbl_files)}
tbl_cols: dict[str, set[str]] = {
    table: set(metadata["columns"]) for table, metadata in table_metadata.items()
}
model_tmdl_text = (DEF / "model.tmdl").read_text(encoding="utf-8")
auto_date_tables = sorted(
    table for table in table_metadata
    if table.startswith("LocalDateTable_") or table.startswith("DateTableTemplate_")
)
auto_date_files = sorted(
    path.name for path in (DEF / "tables").glob("*.tmdl")
    if path.name.startswith(("LocalDateTable_", "DateTableTemplate_"))
)
check("annotation __PBI_TimeIntelligenceEnabled = 0" in model_tmdl_text,
      "Auto date/time is not disabled in model.tmdl")
check(not auto_date_tables and not auto_date_files,
      f"Desktop auto-date tables remain: tables={auto_date_tables}, files={auto_date_files}")
print(f"[2d] Auto date/time: disabled={ 'annotation __PBI_TimeIntelligenceEnabled = 0' in model_tmdl_text}; local/template tables={len(auto_date_files)}")

check(len(tbl_files) == 53, f"expected 53 table files, found {len(tbl_files)}")
check(len(tbl_cols) == 53, f"expected 53 unique tables, found {len(tbl_cols)}")
duplicate_columns = {
    table: sorted(column for column in set(metadata["columns"])
                  if metadata["columns"].count(column) > 1)
    for table, metadata in table_metadata.items()
}
duplicate_columns = {table: columns for table, columns in duplicate_columns.items() if columns}
measure_column_collisions = {
    table: sorted(set(metadata["measures"]) & set(metadata["columns"]))
    for table, metadata in table_metadata.items()
}
measure_column_collisions = {
    table: names for table, names in measure_column_collisions.items() if names
}
multiple_keys = {
    table: sorted(column for column, props in metadata["column_properties"].items()
                  if props.get("isKey") == "true")
    for table, metadata in table_metadata.items()
}
multiple_keys = {table: columns for table, columns in multiple_keys.items() if len(columns) > 1}
check(not duplicate_columns, f"duplicate column names within tables: {duplicate_columns}")
check(not measure_column_collisions,
      f"measure names collide with column names in their table: {measure_column_collisions}")
check(not multiple_keys, f"tables have more than one isKey column: {multiple_keys}")
print(f"[2b] table rules: duplicate columns={len(duplicate_columns)}, measure/column collisions={len(measure_column_collisions)}, multiple isKey tables={len(multiple_keys)}")

try:
    output_inventory = {
        table: metadata["columns"] for table, metadata in table_metadata.items()
        if table != MEASURE_TABLE
    }
    output_measures = [
        {"name": name} for name in table_metadata.get(MEASURE_TABLE, {}).get("measures", [])
    ]
    validate_output_object_names(output_inventory, output_measures)
    output_name_errors = 0
except ValueError as exc:
    failures.append(f"invalid output object names: {exc}")
    output_name_errors = 1
check(MEASURE_TABLE in table_metadata, f"missing measure output table {MEASURE_TABLE!r}")
check(not (DEF / "tables" / "Measures.tmdl").exists(), "stale tables/Measures.tmdl file remains")
holder = table_metadata.get(MEASURE_TABLE, {})
holder_column = holder.get("column_properties", {}).get(MEASURE_TABLE, {})
check(holder_column.get("sourceColumn") == f"[{MEASURE_TABLE}]",
    f"{MEASURE_TABLE}: placeholder column/sourceColumn mapping is invalid: {holder_column}")
check(bool(re.search(r"^\tcolumn\s+_Measures\s*$", holder.get("text", ""), re.M)),
    f"{MEASURE_TABLE}: placeholder column is missing")
check(bool(re.search(r"^\tpartition\s+_Measures\s*=\s*calculated\s*$", holder.get("text", ""), re.M)),
    f"{MEASURE_TABLE}: calculated partition is missing")
model_refs = re.findall(r"^ref table\s+(\S+)\s*$", (DEF / "model.tmdl").read_text(encoding="utf-8"), re.M)
check(model_refs.count(MEASURE_TABLE) == 1 and not any(ref.casefold() == "measures" for ref in model_refs),
    f"model.tmdl measure table refs are invalid: {model_refs}")
print(f"[2c] output-name audit: reserved/invalid names and case-insensitive duplicates={output_name_errors}; stale file={'present' if (DEF / 'tables' / 'Measures.tmdl').exists() else 'absent'}")

# no table declared twice anywhere in the model
decls: dict[str, int] = {}
for f in DEF.rglob("*.tmdl"):
    for name in re.findall(r"^table\s+'?([^'\n]+?)'?\s*$", f.read_text(encoding="utf-8"), re.M):
        decls[name] = decls.get(name, 0) + 1
dupes = {t: n for t, n in decls.items() if n > 1}
check(not dupes, f"tables declared more than once: {dupes}")

# no invalid hash comments (a '#' inside a quoted formatString is not a comment)
for f in DEF.rglob("*.tmdl"):
    for i, ln in enumerate(f.read_text(encoding="utf-8").split("\n"), 1):
        if re.match(r"^\t{2,3}(formatString|displayFolder):", ln):
            continue
        if "#" in re.sub(r'"[^"]*"', '""', ln):
            failures.append(f"invalid '#' comment in TMDL: {f.relative_to(ROOT)}:{i}: {ln.strip()}")

# every table has a partition; m partitions must carry a let..in M body
for f in tbl_files:
    text = f.read_text(encoding="utf-8")
    check(re.search(r"^\tpartition\s+(\S+)\s+=\s+(m|calculated)\s*$", text, re.M) is not None,
          f"no valid partition declaration in {f.name}")
    if re.search(r"^\tpartition\s+\S+\s+=\s+m\s*$", text, re.M):
          check(re.search(r"^\t{2,}source\s*=", text, re.M) is not None
              and re.search(r"^\t{3,}let\b", text, re.M) is not None,
              f"m partition without a let..in M body: {f.name}")
print(f"[2] TMDL tables: {len(tbl_files)} files / {len(decls)} declarations / duplicates: {len(dupes)}")

# column data types are no longer all string
all_types: dict[str, int] = {}
for f in tbl_files:
    for t in re.findall(r"^\t\tdataType:\s*(\S+)", f.read_text(encoding="utf-8"), re.M):
        all_types[t] = all_types.get(t, 0) + 1
check(all_types.get("string", 0) < sum(all_types.values()) * 0.9,
      f"column types still overwhelmingly string: {all_types}")
print(f"[3] column dataTypes: {all_types}")

# --------------------------------------------------------------------------- 3. relationships
rel_text = (DEF / "relationships.tmdl").read_text(encoding="utf-8")
_governed = json.loads((PBI / "model_definition.json").read_text(encoding="utf-8"))
governed_relationships = {
    (item["from"].replace("[", ".").replace("]", ""),
     item["to"].replace("[", ".").replace("]", "")): item
    for item in _governed["relationships"]
}
relationship_blocks = list(re.finditer(r"^relationship\s+(\S+)\s*$", rel_text, re.M))
rel_blocks = []
for index, match in enumerate(relationship_blocks):
    end = relationship_blocks[index + 1].start() if index + 1 < len(relationship_blocks) else len(rel_text)
    block = rel_text[match.end():end]
    from_match = re.search(r"^\tfromColumn:\s+(\S+)", block, re.M)
    to_match = re.search(r"^\ttoColumn:\s+(\S+)", block, re.M)
    if not from_match or not to_match:
        continue
    from_ref, to_ref = from_match.group(1), to_match.group(1)
    governed = governed_relationships.get((from_ref, to_ref))
    if governed:
        from_card, to_card = CARDINALITY_TMDL[governed["cardinality"]]
        cross_filter = CROSS_FILTER_TMDL[governed["cross_filter"]]
        active = str(governed["active"]).lower()
    else:
        from_card, to_card = ("many", "one")
        cross_filter = "oneDirection"
        active = "true"
    active_match = re.search(r"^\tisActive:\s+(true|false)\s*$", block, re.M)
    if active_match:
        active = active_match.group(1)
    rel_blocks.append((match.group(1), from_ref, to_ref, from_card, to_card, cross_filter, active))
check(len(rel_blocks) == 15, f"expected 15 relationships, parsed {len(rel_blocks)}")

_expected_xf = {
    CROSS_FILTER_TMDL[r["cross_filter"]] for r in _governed["relationships"]
}
_expected_xf.add("oneDirection")  # the 3 Phase 10 forecast relationships
_expected_card = {CARDINALITY_TMDL[c] for c in {r["cardinality"] for r in _governed["relationships"]}}
_expected_card.add(("many", "one"))

for name, frm, to, fc, tc, xf, act in rel_blocks:
    for ref, side in ((frm, "from"), (to, "to")):
        t, _, c = ref.partition(".")
        if not check(t in tbl_cols, f"relationship {name}: {side} table {t} missing"):
            continue
        check(c in tbl_cols[t], f"relationship {name}: {side} column {t}[{c}] missing")
    check((fc, tc) in _expected_card,
          f"relationship {name}: cardinality {fc}:{tc} not governed "
          f"{sorted(_expected_card)}")
    check(xf in _expected_xf,
          f"relationship {name}: crossFilteringBehavior {xf} not governed "
          f"{sorted(_expected_xf)}")
    check(act in ("true", "false"), f"relationship {name}: isActive {act}")
print(f"[4] relationships validated: {len(rel_blocks)}")

# --------------------------------------------------------------------------- 3b. model-load rules
import csv

folder_parameters = dict(re.findall(
    r'^expression\s+(\w+)\s*=\s*"([^"]+)"',
    (DEF / "expressions.tmdl").read_text(encoding="utf-8"), re.M,
))
partition_count = 0
m_partition_count = 0
partition_sources: dict[str, pathlib.Path] = {}
partition_headers: dict[str, set[str]] = {}
partition_rows: dict[str, list[dict[str, str]]] = {}
partition_query_columns: dict[str, set[str]] = {}
row_validation_tables = {
    table for table, metadata in table_metadata.items()
    if any(props.get("isKey") == "true" for props in metadata["column_properties"].values())
    or any(props.get("sortByColumn") for props in metadata["column_properties"].values())
}
row_validation_tables.update(
    to.partition(".")[0]
    for _, _, to, from_card, to_card, _, _ in rel_blocks
    if (from_card, to_card) == ("many", "one")
)
row_validation_tables.update({"Date", "forecast_weekly", "forecast_intervals", "forecast_selected_model"})
partition_source_errors = 0
query_schema_issues = 0
source_column_checks = 0
source_column_issues = 0
typed_pair_re = re.compile(
    r'\{\s*"(?P<column>[^"]+)"\s*,\s*(?:type\s+[\w.]+|[\w.]+)\s*\}'
)
file_contents_re = re.compile(r'File\.Contents\((\w+)\s*&\s*"([^"]+)"\)')

for table, metadata in table_metadata.items():
    partitions = metadata["partitions"]
    partition_count += len(partitions)
    check(len(partitions) == 1, f"{table}: expected exactly one partition, found {len(partitions)}")
    if len(partitions) != 1:
        continue
    partition_kind = partitions[0][0]
    if partition_kind == "calculated":
        check(f'ROW ( "{MEASURE_TABLE}", "" )' in metadata["text"],
              f"{table}: calculated partition does not emit its {MEASURE_TABLE} column")
        continue

    m_partition_count += 1
    text = metadata["text"]
    check(re.search(r"\blet\b", text) is not None and re.search(r"\bin\b", text) is not None,
          f"{table}: M partition is missing a let/in expression")
    file_match = file_contents_re.search(text)
    if not file_match:
        check(False, f"{table}: M partition has no resolvable File.Contents source")
        partition_source_errors += 1
        continue
    parameter, suffix = file_match.groups()
    if parameter not in folder_parameters:
        check(False, f"{table}: File.Contents uses undefined expression {parameter!r}")
        partition_source_errors += 1
        continue
    csv_path = pathlib.Path(folder_parameters[parameter]) / suffix.lstrip("\\/")
    if not csv_path.is_file():
        check(False, f"{table}: partition source file does not exist: {csv_path}")
        partition_source_errors += 1
        continue
    partition_sources[table] = csv_path
    with csv_path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        partition_headers[table] = set(reader.fieldnames or [])
        if table in row_validation_tables:
            partition_rows[table] = list(reader)
    transform = re.search(r"Table\.TransformColumnTypes\(.*?\{(.*?)\}\s*,\s*\"en-US\"\)",
                          text, re.S)
    query_columns = {match.group("column") for match in typed_pair_re.finditer(transform.group(1))} if transform else set()
    derived_columns = GENERATED_QUERY_COLUMNS.get(table, {})
    added_columns = set(re.findall(r'Table\.Add(?:Column|IndexColumn)\([^,]+,\s*"([^"]+)"', text))
    partition_query_columns[table] = query_columns | set(derived_columns)
    check(transform is not None, f"{table}: M partition has no typed output-column list")
    check(set(derived_columns) <= added_columns,
          f"{table}: declared generated M columns are not added: {sorted(set(derived_columns) - added_columns)}")
    query_schema_matches = query_columns == partition_headers[table]
    check(query_schema_matches,
          f"{table}: Power Query typed columns differ from source CSV headers "
          f"(missing={sorted(partition_headers[table] - query_columns)[:8]}, "
          f"extra={sorted(query_columns - partition_headers[table])[:8]})")
    if not query_schema_matches:
        query_schema_issues += 1

for table, metadata in table_metadata.items():
    if not metadata["partitions"] or metadata["partitions"][0][0] != "m":
        continue
    for column, props in metadata["column_properties"].items():
        source_column = props.get("sourceColumn")
        if not source_column:
            continue
        query_produces_column = source_column in partition_query_columns.get(table, set())
        source_has_column = (
            source_column in partition_headers.get(table, set())
            or source_column in GENERATED_QUERY_COLUMNS.get(table, {})
        )
        source_column_checks += 2
        check(query_produces_column,
              f"{table}[{column}]: sourceColumn {source_column!r} is not produced by its M partition")
        check(source_has_column,
              f"{table}[{column}]: sourceColumn {source_column!r} is absent from its source CSV")
        if not query_produces_column or not source_has_column:
            source_column_issues += 1

check(partition_count == 53, f"expected 53 partition objects (52 M + {MEASURE_TABLE} calculated), found {partition_count}")
check(m_partition_count == 52, f"expected 52 M partitions, found {m_partition_count}")
print(f"[3b] partitions: {partition_count} objects ({m_partition_count} M, {partition_count - m_partition_count} calculated); CSV path errors={partition_source_errors}; query-schema errors={query_schema_issues}; sourceColumn checks={source_column_checks}, issues={source_column_issues}")

# Every isKey is unique/nonblank in its source; marked date tables also require a
# dateTime key with contiguous dates. Date.tmdl currently has no Time dataCategory.
key_data_issues = 0
for table, metadata in table_metadata.items():
    keys = [column for column, props in metadata["column_properties"].items()
            if props.get("isKey") == "true"]
    if not keys:
        continue
    for column in keys:
        props = metadata["column_properties"][column]
        source_column = props.get("sourceColumn")
        rows = partition_rows.get(table)
        if rows is None or not source_column:
            check(False, f"{table}[{column}]: key has no CSV-backed source column")
            key_data_issues += 1
            continue
        values = [(row.get(source_column) or "").strip() for row in rows]
        check(all(values), f"{table}[{column}]: key contains blank source values")
        check(len(values) == len(set(values)), f"{table}[{column}]: key values are not unique")
        if not all(values) or len(values) != len(set(values)):
            key_data_issues += 1
        if metadata["data_category"] == "Time":
            check(props.get("dataType") == "dateTime",
                  f"{table}[{column}]: marked date-table key must be dateTime")
            try:
                dates = sorted(date.fromisoformat(value) for value in values)
                contiguous = bool(dates) and all(
                    later - earlier == timedelta(days=1)
                    for earlier, later in zip(dates, dates[1:])
                )
            except ValueError:
                contiguous = False
            check(contiguous, f"{table}[{column}]: marked date-table key is not contiguous")
print(f"[3c] isKey data checks: selected key columns={sum(len([p for p in m['column_properties'].values() if p.get('isKey') == 'true']) for m in table_metadata.values())}; uniqueness/blank issues={key_data_issues}")
governed_date_mark = json.loads((PBI / "model_definition.json").read_text(encoding="utf-8")).get("mark_as_date_table")
if governed_date_mark:
    marked_table = governed_date_mark["table"]
    marked_column = governed_date_mark["column"]
    marked_props = table_metadata.get(marked_table, {}).get("column_properties", {}).get(marked_column, {})
    marked_source_column = marked_props.get("sourceColumn", marked_column)
    marked_rows = partition_rows.get(marked_table, [])
    marked_blanks = sum(not (row.get(marked_source_column) or "").strip() for row in marked_rows)
    if marked_blanks:
        print(f"[WARN] model_definition.json marks {marked_table}[{marked_column}] as the date-table column, but its source contains {marked_blanks} blank value(s)")

forecast_rows = partition_rows.get("forecast_weekly", [])
date_rows_for_match = partition_rows.get("Date", [])
date_key_column = table_metadata.get("Date", {}).get("column_properties", {}).get("date_key", {}).get("sourceColumn", "date_key")
date_keys_for_match = {(row.get(date_key_column) or "").strip() for row in date_rows_for_match}
unmatched_forecast_weeks = 0
for row in forecast_rows:
    raw_week = (row.get("week_start_date") or "").strip()
    if not raw_week:
        continue
    week = date.fromisoformat(raw_week)
    generated_key = f"{week.year:04d}{week.month:02d}{week.day:02d}"
    if generated_key not in date_keys_for_match:
        unmatched_forecast_weeks += 1
print(f"[WARN] forecast_weekly rows without a Date[date_key] match: {unmatched_forecast_weeks}/{len(forecast_rows)}; date-range coverage gap remains out of scope")

# Relationship endpoint types and all many-to-one one-side uniqueness checks.
numeric_types = {"int64", "double", "decimal"}
relationship_type_issues = 0
relationship_unique_issues = 0
relationship_names = re.findall(r"^relationship\s+(\S+)", rel_text, re.M)
for name, frm, to, from_card, to_card, cross_filter, active in rel_blocks:
    from_table, _, from_column = frm.partition(".")
    to_table, _, to_column = to.partition(".")
    from_type = table_metadata[from_table]["column_properties"].get(from_column, {}).get("dataType")
    to_type = table_metadata[to_table]["column_properties"].get(to_column, {}).get("dataType")
    compatible = from_type == to_type or {from_type, to_type} <= numeric_types
    check(compatible, f"relationship {name}: incompatible endpoint types {from_type!r} and {to_type!r}")
    if not compatible:
        relationship_type_issues += 1
    if (from_card, to_card) == ("many", "one"):
        source_column = table_metadata[to_table]["column_properties"].get(to_column, {}).get("sourceColumn")
        rows = partition_rows.get(to_table)
        if rows is None or not source_column:
            check(False, f"relationship {name}: one-side {to} has no CSV-backed source column")
            relationship_unique_issues += 1
        else:
            values = [(row.get(source_column) or "").strip() for row in rows]
            has_blanks = any(not value for value in values)
            is_unique = len(values) == len(set(values))
            check(not has_blanks,
                  f"relationship {name}: one-side {to} contains blank/null values in {partition_sources[to_table]}")
            check(is_unique,
                  f"relationship {name}: one-side {to} is not unique in {partition_sources[to_table]}")
            if has_blanks or not is_unique:
                relationship_unique_issues += 1

# Count directed active filter paths according to relationship cardinality/direction.
active_graph: dict[str, list[str]] = defaultdict(list)
for _, frm, to, from_card, to_card, cross_filter, active in rel_blocks:
    if active != "true":
        continue
    from_table = frm.partition(".")[0]
    to_table = to.partition(".")[0]
    if cross_filter == "bothDirections":
        active_graph[from_table].append(to_table)
        active_graph[to_table].append(from_table)
    elif from_card == "many" and to_card == "one":
        active_graph[to_table].append(from_table)
    elif from_card == "one" and to_card == "many":
        active_graph[from_table].append(to_table)


def count_active_paths(start: str, target: str, visited: set[str]) -> int:
    """Number of active relationship paths between two tables; more than one is ambiguous."""
    if start == target:
        return 1
    total = 0
    for neighbor in active_graph.get(start, []):
        if neighbor in visited:
            continue
        total += count_active_paths(neighbor, target, visited | {neighbor})
        if total > 1:
            return 2
    return total


ambiguous_paths = []
for source_table in tbl_cols:
    for target_table in tbl_cols:
        if source_table != target_table and count_active_paths(source_table, target_table, {source_table}) > 1:
            ambiguous_paths.append((source_table, target_table))
check(not ambiguous_paths, f"ambiguous active relationship paths: {ambiguous_paths[:10]}")
print(f"[4b] relationship checks: endpoints={2 * len(rel_blocks)}, type mismatches={relationship_type_issues}, nonunique one-sides={relationship_unique_issues}, ambiguous active table paths={len(ambiguous_paths)}")

# sortByColumn requires an existing target and a single sort value for each displayed value.
sort_issues = 0
sort_checks = 0
for table, metadata in table_metadata.items():
    rows = partition_rows.get(table, [])
    for column, props in metadata["column_properties"].items():
        target = props.get("sortByColumn")
        if not target:
            continue
        target = unquote_tmdl_name(target)
        sort_checks += 1
        check(target in metadata["column_properties"],
              f"{table}[{column}]: sortByColumn target {target!r} does not exist in the table")
        sorted_source = props.get("sourceColumn")
        target_source = metadata["column_properties"].get(target, {}).get("sourceColumn")
        mapping: dict[str, set[str]] = defaultdict(set)
        if rows and sorted_source and target_source:
            for row in rows:
                mapping[row.get(sorted_source, "").strip()].add(row.get(target_source, "").strip())
        valid_mapping = bool(mapping) and all(len(values) == 1 for values in mapping.values())
        check(valid_mapping,
              f"{table}[{column}]: values do not map to exactly one {target} sort value")
        if not valid_mapping:
            sort_issues += 1
print(f"[4c] sortByColumn checks: mappings={sort_checks}, invalid={sort_issues}")

# Calculated-column DAX references must resolve to a table/column in this semantic model.
calculated_reference_issues = []
dax_column_ref = re.compile(
    r"'([^']+)'\[([^\]]+)\]|(?<!['\w])([A-Za-z_][A-Za-z0-9_]*)\[([^\]]+)\]"
)
for table, metadata in table_metadata.items():
    for column, expression in metadata["calculated_columns"].items():
        for match in dax_column_ref.finditer(expression):
            ref_table, ref_column = (match.group(1), match.group(2)) if match.group(1) else (match.group(3), match.group(4))
            if ref_table not in tbl_cols or ref_column not in tbl_cols.get(ref_table, set()):
                calculated_reference_issues.append(f"{table}[{column}] -> {ref_table}[{ref_column}]")
check(not calculated_reference_issues,
      f"calculated-column references unresolved: {calculated_reference_issues[:12]}")
print(f"[4d] calculated-column references: {sum(len(m['calculated_columns']) for m in table_metadata.values())} columns, unresolved={len(calculated_reference_issues)}")

# --------------------------------------------------------------------------- 4. measures vs governed source
gov = (PBI / "dax" / "measures_tmdl.tmdl").read_text(encoding="utf-8")
gen_path = DEF / "tables" / f"{MEASURE_TABLE}.tmdl"
gen = gen_path.read_text(encoding="utf-8")
check(not (DEF / "tables" / "Measures.tmdl").exists(),
    "stale tables/Measures.tmdl remains after measure-table rename")
check(MEASURE_TABLE in table_metadata, f"output table {MEASURE_TABLE!r} is missing")
check(not any(table.casefold() == "measures" for table in table_metadata),
    "reserved output table name 'Measures' remains")
gov_names = [unquote_tmdl_name(name) for name in re.findall(r"^\t\tmeasure\s+'((?:[^']|'')+)'", gov, re.M)]
gen_names = table_metadata.get(MEASURE_TABLE, {}).get("measures", [])
normalized_gov_names = gov_names
normalized_gen_names = gen_names
missing_measure_names = sorted(set(normalized_gov_names) - set(normalized_gen_names))
extra_measure_names = sorted(set(normalized_gen_names) - set(normalized_gov_names))
duplicate_measure_names = sorted(
    name for name in set(normalized_gen_names)
    if normalized_gen_names.count(name) > 1
)
check(len(gov_names) == 92, f"governed source should hold 92 measures, found {len(gov_names)}")
check(normalized_gen_names == normalized_gov_names, "measure names/order differ from the governed source")
check(len(set(normalized_gen_names)) == len(normalized_gen_names), "duplicate measure names")
check(not missing_measure_names, f"missing generated measures: {missing_measure_names}")
check(not extra_measure_names, f"extra generated measures: {extra_measure_names}")
check(not duplicate_measure_names, f"duplicate generated measures: {duplicate_measure_names}")
print(f"[5] measures: source={len(gov_names)} generated={len(gen_names)} distinct={len(set(normalized_gen_names))} missing={len(missing_measure_names)} extra={len(extra_measure_names)} duplicates={len(duplicate_measure_names)} identical_order={normalized_gen_names == normalized_gov_names}")

# every DAX Table[Column] and [Measure] reference resolves
gen_text = gen
for f in tbl_files:
    gen_text += "\n" + f.read_text(encoding="utf-8")
dax_cols = set(re.findall(r"'([^']+)'\[([^\]]+)\]|\b([A-Za-z_][A-Za-z0-9_]*)\[([^\]]+)\]", ""))
refs = re.findall(r"'([^']+)'\[([^\]]+)\]", gen_text) + \
    re.findall(r"(?<!['\w])([A-Za-z_][A-Za-z0-9_]*)\[([^\]]+)\]", gen_text)
bad = sorted({f"{t}[{c}]" for t, c in refs
              if t not in tbl_cols or c not in tbl_cols[t]})
check(not bad, f"unresolved DAX column references: {bad[:15]}")

measure_refs = set(re.findall(r"\[([^\]\[]+)\]", gen_text))
defined = {n.replace("''", "'") for n in gen_names}
unresolved_measures = sorted(
    m for m in measure_refs
    if m not in defined and m not in tbl_cols.get(MEASURE_TABLE, set()) and m not in tbl_cols
)
print(f"[6] DAX column refs checked: {len(set(refs))} distinct, unresolved={len(bad)}")

# business logic fidelity: the expression text of every measure must match the governed source
def measure_bodies(text: str, header_re: re.Pattern) -> list[tuple[str, str]]:
    """(name, whitespace-normalised expression) for each measure, in file order."""
    out: list[tuple[str, str]] = []
    lines = text.split("\n")
    name: str | None = None
    expr: list[str] = []
    for ln in lines:
        h = header_re.match(ln)
        if h:
            if name is not None:
                out.append((name, re.sub(r"\s+", " ", " ".join(expr)).strip()))
            groups = h.groups()
            name = next(value for value in groups[:-1] if value is not None).replace("''", "'")
            expression = groups[-1]
            expr = [expression] if expression.strip() else []
            continue
        if name is None:
            continue
        if re.match(r"^\t{1,2}(column|partition|measure)\b", ln):
            out.append((name, re.sub(r"\s+", " ", " ".join(expr)).strip()))
            name, expr = None, []
            continue
        s = ln.strip()
        if s.startswith(("formatString:", "displayFolder:", "lineageTag:", "///")) or not s:
            continue
        expr.append(s)
    if name is not None:
        out.append((name, re.sub(r"\s+", " ", " ".join(expr)).strip()))
    return out


GOV_HDR = re.compile(r"^\t\tmeasure\s+'((?:[^']|'')+)'\s*=\s?(.*)$")
GEN_HDR = re.compile(r"^\tmeasure\s+(?:'((?:[^']|'')+)'|([^\s=]+))\s*=\s?(.*)$")
gen_bodies = measure_bodies(gen, GEN_HDR)
qualifier_rewrites = sum(
    rewrite_measure_table_qualifiers(measure["expression"])[1]
    for measure in load_measure_defs()
)
serialized_gov, serialized_qualifier_count = rewrite_measure_table_qualifiers(gov)
check(serialized_qualifier_count == qualifier_rewrites,
      "governed measure qualifier count differs between parsed and serialized source")
gov_bodies = measure_bodies(serialized_gov, GOV_HDR)
check(len(gov_bodies) == 92, f"governed source should hold 92 measures, parsed {len(gov_bodies)}")
check(len(gen_bodies) == 92, f"generated Measures.tmdl should hold 92 measures, parsed {len(gen_bodies)}")
mismatch = [g[0] for g, x in zip(gov_bodies, gen_bodies) if g != x] if len(gov_bodies) == len(gen_bodies) else []
if mismatch:
    for g, x in zip(gov_bodies, gen_bodies):
        if g != x:
            failures.append(f"DAX expression changed for '{g[0]}':\n      governed: {g[1][:220]}\n"
                            f"      generated: {x[1][:220]}")
            break
check(not mismatch, f"DAX expression text changed outside authorized table-qualifier mapping for {len(mismatch)} measure(s): {mismatch[:10]}")
check(qualifier_rewrites == serialized_qualifier_count,
    "reported DAX qualifier rewrite count does not match the serialized source")
print(f"[7] DAX expression fidelity: {len(gen_bodies)} measures compared, non-qualifier differences={len(mismatch)}, authorized table-qualifier rewrites={qualifier_rewrites}")

# formatString and displayFolder values must survive verbatim (the earlier build mojibake'd them)
PROP_RE = r"^\t{2,3}(formatString|displayFolder):\s*(.+)$"
gov_props = re.findall(PROP_RE, gov, re.M)
gen_props = re.findall(PROP_RE, gen, re.M)
gov_props = [(key, value.strip('"')) for key, value in gov_props]
gen_props = [(key, value.strip('"')) for key, value in gen_props]
if gov_props != gen_props:
    for k, (a, b) in enumerate(zip(gov_props, gen_props)):
        if a != b:
            failures.append(f"property differs at #{k}: governed={a} generated={b}")
            break
    failures.append(f"formatString/displayFolder differ (gov={len(gov_props)} gen={len(gen_props)})")
check(gov_props == gen_props, "formatString/displayFolder values differ from the governed source")
check(chr(0x20AC) in gen, "euro sign missing from generated _Measures.tmdl")
check("â‚¬" not in gen and "â€" not in gen, "mojibake still present in generated _Measures.tmdl")
print(f"[8] formatString/displayFolder: {len(gen_props)} compared, euro_intact={chr(0x20AC) in gen}")

# --------------------------------------------------------------------------- 5. PBIR report
visuals = sorted((PAGE_DIR / "visuals").iterdir())
report_page_dirs = sorted(path for path in PAGE_ROOT.iterdir() if path.is_dir())
expected_page_names = ["ReportSection1ExecutiveOverview"] + [
    spec["name"] for spec in build_additional_pages()
]
pages_doc = json.loads((PAGE_ROOT / "pages.json").read_text(encoding="utf-8"))
check(pages_doc.get("pageOrder") == expected_page_names,
    f"page order differs from generated page specs: {pages_doc.get('pageOrder')}")
check([path.name for path in report_page_dirs] == sorted(expected_page_names),
    f"page folders differ from generated page specs: {[path.name for path in report_page_dirs]}")
all_visual_dirs = [vdir for page_dir in report_page_dirs
             for vdir in sorted((page_dir / "visuals").iterdir())]
print(f"[9a] pages: {len(report_page_dirs)} folders, page order matches generator={pages_doc.get('pageOrder') == expected_page_names}")
names = []
positions = []
for vdir in visuals:
    vp = vdir / "visual.json"
    check(vp.is_file(), f"missing visual.json in {vdir.name}")
    v = json.loads(vp.read_text(encoding="utf-8"))
    names.append(v["name"])
    positions.append((v["name"], v["position"]))
    check(v.get("$schema", "").endswith("visualContainer/2.13.0/schema.json"),
          f"{vdir.name}: visual schema is not Desktop 2.13.0")
    check(set(v) <= {"$schema", "name", "position", "visual", "filterConfig", "isHidden",
                     "annotations", "howCreated", "visualGroup", "parentGroupName"},
          f"{vdir.name}: unexpected top-level property {set(v) - {'$schema','name','position','visual','filterConfig','isHidden','annotations','howCreated','visualGroup','parentGroupName'}}")
    check(v["visual"]["visualType"] in
          {"card", "lineChart", "waterfallChart", "tableEx", "slicer"},
          f"{vdir.name}: unexpected visualType {v['visual']['visualType']}")
    if vdir.name in {"driverAttributionWaterfall", "phase5RevenueBridge"}:
        roles = v["visual"].get("query", {}).get("queryState", {})
        check("Category" in roles and "CategoryAxis" not in roles,
              f"{vdir.name}: waterfall must bind its category to the Category role")
        y_projections = roles.get("Y", {}).get("projections", [])
        expected_column = "amount_eur" if vdir.name == "driverAttributionWaterfall" else "value_eur"
        expected_title = "Driver impact (€)" if vdir.name == "driverAttributionWaterfall" else "Revenue change (€)"
        check(len(y_projections) == 1 and "Aggregation" in y_projections[0].get("field", {}),
              f"{vdir.name}: Y must be an explicit aggregation")
        if len(y_projections) == 1 and "Aggregation" in y_projections[0].get("field", {}):
            aggregation = y_projections[0]["field"]["Aggregation"]
            value_column = aggregation.get("Expression", {}).get("Column", {}).get("Property")
            check(value_column == expected_column and aggregation.get("Function") == 0,
                  f"{vdir.name}: expected Sum of {expected_column}, got {value_column}, {aggregation.get('Function')}")
            check(y_projections[0].get("nativeQueryRef") == expected_title,
                  f"{vdir.name}: expected readable value label {expected_title!r}")
    if vdir.name == "trendRevenueYoY":
        category = v["visual"].get("query", {}).get("queryState", {}).get("Category", {}).get("projections", [])
        check(len(category) == 1 and category[0].get("field", {}).get("Column", {}).get("Property") == "retail_week",
              "trendRevenueYoY: category axis must use Date[retail_week]")
    if vdir.name == "slicerPeriod":
        period_filters = v.get("filterConfig", {}).get("filters", [])
        unknown_filter = next((item for item in period_filters
                               if item.get("field", {}).get("Column", {}).get("Property") == "is_unknown"
                               and item.get("field", {}).get("Column", {}).get("Expression", {}).get("SourceRef", {}).get("Entity") == "Date"), None)
        check(unknown_filter is not None, "slicerPeriod: missing visual-level Date[is_unknown] filter")
        if unknown_filter:
            values = unknown_filter.get("filter", {}).get("Where", [{}])[0].get("Condition", {}).get("In", {}).get("Values")
            check(values == [[{"Literal": {"Value": "0L"}}]],
                  "slicerPeriod: visual filter must include only is_unknown = 0")
check(len(names) == len(set(names)), f"duplicate visual names: {names}")
check(all(n == d.name for n, d in zip(names, visuals)), "visual name must match its folder")
print(f"[9] visuals: {len(visuals)} on page 1, unique names={len(set(names)) == len(names)}")

# layout: inside the canvas and non-overlapping
for name, p in positions:
    check(p["x"] >= 0 and p["y"] >= 0, f"{name}: negative origin")
    check(p["x"] + p["width"] <= PAGE_W, f"{name}: overflows width ({p['x']}+{p['width']} > {PAGE_W})")
    check(p["y"] + p["height"] <= PAGE_H, f"{name}: overflows height ({p['y']}+{p['height']} > {PAGE_H})")

overlaps = []
for i in range(len(positions)):
    for j in range(i + 1, len(positions)):
        (n1, a), (n2, b) = positions[i], positions[j]
        if (a["x"] < b["x"] + b["width"] and b["x"] < a["x"] + a["width"]
                and a["y"] < b["y"] + b["height"] and b["y"] < a["y"] + a["height"]):
            overlaps.append((n1, n2))
check(not overlaps, f"overlapping visuals: {overlaps}")
print(f"[10] layout: {len(positions)} visuals inside {PAGE_W}x{PAGE_H}, overlaps={len(overlaps)}")

for page_dir in report_page_dirs:
    page_doc = json.loads((page_dir / "page.json").read_text(encoding="utf-8"))
    page_width, page_height = page_doc.get("width", PAGE_W), page_doc.get("height", PAGE_H)
    page_positions = []
    for visual_dir in sorted((page_dir / "visuals").iterdir()):
        visual_doc = json.loads((visual_dir / "visual.json").read_text(encoding="utf-8"))
        position = visual_doc["position"]
        page_positions.append((visual_doc["name"], position))
        check(position["x"] >= 0 and position["y"] >= 0,
              f"{page_dir.name}/{visual_doc['name']}: negative origin")
        check(position["x"] + position["width"] <= page_width,
              f"{page_dir.name}/{visual_doc['name']}: overflows page width")
        check(position["y"] + position["height"] <= page_height,
              f"{page_dir.name}/{visual_doc['name']}: overflows page height")
    page_overlaps = []
    for index, (first_name, first) in enumerate(page_positions):
        for second_name, second in page_positions[index + 1:]:
            if (first["x"] < second["x"] + second["width"]
                    and second["x"] < first["x"] + first["width"]
                    and first["y"] < second["y"] + second["height"]
                    and second["y"] < first["y"] + first["height"]):
                page_overlaps.append((first_name, second_name))
    check(not page_overlaps, f"{page_dir.name}: overlapping visuals {page_overlaps}")

page2_dir = PAGE_ROOT / "ReportSection2StoreCustomer"
page2_text = {
    visual_dir.name: json.loads((visual_dir / "visual.json").read_text(encoding="utf-8"))
    .get("visual", {}).get("objects", {}).get("general", [{}])[0]
    .get("properties", {}).get("paragraphs", [{}])[0]
    .get("textRuns", [{}])[0].get("value", "")
    for visual_dir in (page2_dir / "visuals").iterdir()
    if (visual_dir / "visual.json").is_file()
}
check("NOT SHOWN: the eight-measure, three-group comparison matrix requires field parameters"
      in page2_text.get("page2MatrixPlaceholder", ""),
      "Page 2 must label the unavailable field-parameter comparison matrix")
check("NOT SHOWN: the 7-day mean requires a governed measure or query"
      in page2_text.get("page2MeanPlaceholder", ""),
      "Page 2 must label the unavailable governed 7-day mean")

page3_doc = json.loads((PAGE_ROOT / "ReportSection3ProductInventory" / "page.json").read_text(encoding="utf-8"))
page3_category_filters = page3_doc.get("filterConfig", {}).get("filters", [])
check(any(
    item.get("field", {}).get("Column", {}).get("Expression", {}).get("SourceRef", {}).get("Entity") == "Product"
    and item.get("field", {}).get("Column", {}).get("Property") == "category"
    and item.get("filter", {}).get("Where", [{}])[0].get("Condition", {}).get("In", {}).get("Values")
    == [[{"Literal": {"Value": "'Electronics & Tech'"}}]]
    for item in page3_category_filters
), "Page 3 must have the Electronics & Tech Product category page filter")
page3_visual_root = PAGE_ROOT / "ReportSection3ProductInventory" / "visuals"
page3_card_measures = {
    json.loads((visual_dir / "visual.json").read_text(encoding="utf-8"))
    .get("visual", {}).get("query", {}).get("queryState", {})
    .get("Values", {}).get("projections", [{}])[0].get("field", {})
    .get("Measure", {}).get("Property")
    for visual_dir in page3_visual_root.iterdir()
    if (visual_dir / "visual.json").is_file()
}
check("Availability PY" in page3_card_measures,
      "Page 3 must include the Availability PY KPI")

page5_root = PAGE_ROOT / "ReportSection5Promotions"
page5_doc = json.loads((page5_root / "page.json").read_text(encoding="utf-8"))
page5_category_filters = page5_doc.get("filterConfig", {}).get("filters", [])
check(any(
    item.get("field", {}).get("Column", {}).get("Expression", {}).get("SourceRef", {}).get("Entity") == "Product"
    and item.get("field", {}).get("Column", {}).get("Property") == "category"
    and item.get("filter", {}).get("Where", [{}])[0].get("Condition", {}).get("In", {}).get("Values")
    == [[{"Literal": {"Value": "'Home & Kitchen'"}}]]
    for item in page5_category_filters
), "Page 5 must have the Home & Kitchen Product category page filter")
page5_visual_docs = {
    visual_dir.name: json.loads((visual_dir / "visual.json").read_text(encoding="utf-8"))
    for visual_dir in (page5_root / "visuals").iterdir()
}
page5_card_measures = {
    visual_doc.get("visual", {}).get("query", {}).get("queryState", {})
    .get("Values", {}).get("projections", [{}])[0].get("field", {})
    .get("Measure", {}).get("Property")
    for visual_doc in page5_visual_docs.values()
    if visual_doc.get("visual", {}).get("visualType") in {"card", "tableEx"}
}
required_page5_measures = {
    "Net Revenue", "Units YoY %", "ASP", "ASP PY", "Gross Margin YoY",
    "Promotion Events (P6)", "Discount Rate", "Discount Rate PY",
    "Promotion Share", "Promotion Share PY", "Promotion Wording",
}
check(required_page5_measures <= page5_card_measures,
      f"Page 5 is missing KPI measures: {sorted(required_page5_measures - page5_card_measures)}")
method_roles = page5_visual_docs.get("page5MethodEffects", {}).get("visual", {}).get("query", {}).get("queryState", {})
method_values = method_roles.get("Y", {}).get("projections", [])
check(len(method_values) == 1 and method_values[0].get("field", {}).get("Measure", {}).get("Property") == "HK Method Effect Guarded",
      "Page 5 method chart must use HK Method Effect Guarded")
for visual_name in ("page5CoverageDepth", "page5WeeklySales"):
    axis = page5_visual_docs.get(visual_name, {}).get("visual", {}).get("query", {}).get("queryState", {}).get("Category", {}).get("projections", [])
    check(bool(axis) and all(
        item.get("field", {}).get("Column", {}).get("Expression", {}).get("SourceRef", {}).get("Entity") == "p6_hk_weekly"
        for item in axis
    ), f"{visual_name}: weekly chart must use p6_hk_weekly, not Date")
check({"ci_low", "ci_high"} <= {
    projection.get("field", {}).get("Column", {}).get("Property")
    for projection in page5_visual_docs.get("page5MethodIntervals", {}).get("visual", {}).get("query", {}).get("queryState", {}).get("Values", {}).get("projections", [])
}, "Page 5 must expose source confidence bounds for each method")

page6_root = PAGE_ROOT / "ReportSection6EvidenceMatrix"
page6_matrix = json.loads((page6_root / "visuals" / "page6EvidenceMatrix" / "visual.json").read_text(encoding="utf-8"))
page6_sort = page6_matrix.get("visual", {}).get("query", {}).get("sortDefinition", {}).get("sort", [])
check(any(
    entry.get("field", {}).get("Column", {}).get("Property") == "sort_order"
    for entry in page6_sort
), "Page 6 evidence matrix must sort by sort_order")
page6_measure_names = {
    projection.get("field", {}).get("Measure", {}).get("Property")
    for projection in page6_matrix.get("visual", {}).get("query", {}).get("queryState", {}).get("Values", {}).get("projections", [])
}
check("Evidence Colour" not in page6_measure_names,
      "Page 6 must not expose the hexadecimal Evidence Colour measure as a visible column")

page7_root = PAGE_ROOT / "ReportSection7Investigation"
page7_table = json.loads((page7_root / "visuals" / "page7Investigations" / "visual.json").read_text(encoding="utf-8"))
page7_projections = page7_table.get("visual", {}).get("query", {}).get("queryState", {}).get("Values", {}).get("projections", [])
page7_columns = {
    projection.get("field", {}).get("Column", {}).get("Property")
    for projection in page7_projections
}
page7_unsummarised = {
    projection.get("field", {}).get("Column", {}).get("Property")
    for projection in page7_projections
    if "Aggregation" not in projection.get("field", {})
}
check({"priority", "topic", "evidence_level", "known", "unknown", "why_it_matters", "data_required", "proposed_owner", "owner_note"} <= page7_columns
      and "slice_of_decline_eur" in page7_unsummarised,
      "Page 7 investigation table is missing documented columns or the unsummarised slice column")

page8_root = PAGE_ROOT / "ReportSection8Forecast"
page8_visuals = {
    visual_dir.name: json.loads((visual_dir / "visual.json").read_text(encoding="utf-8"))
    for visual_dir in (page8_root / "visuals").iterdir()
}
for visual_name, expected_table in (("page8ForecastPoint", "forecast_weekly"),
                        ("page8ForecastIntervals", "forecast_intervals")):
    projections = page8_visuals.get(visual_name, {}).get("visual", {}).get("query", {}).get("queryState", {}).get("Category", {}).get("projections", [])
    check(len(projections) == 1
        and projections[0].get("field", {}).get("Column", {}).get("Expression", {}).get("SourceRef", {}).get("Entity") == expected_table
        and projections[0].get("field", {}).get("Column", {}).get("Property") == "week_start_date",
        f"{visual_name}: forecast axis must use {expected_table}[week_start_date], never Date")
selected_model_container = page8_visuals.get("page8SelectedModel", {})
selected_model_visual = selected_model_container.get("visual", {})
check(selected_model_visual.get("visualType") == "tableEx",
    "Page 8 selected model must use a table visual so its text value renders")
selected_value_projection = selected_model_visual.get("query", {}).get("queryState", {}).get("Values", {}).get("projections", [{}])[0].get("field", {}).get("Column", {})
check(selected_value_projection.get("Expression", {}).get("SourceRef", {}).get("Entity") == "forecast_selected_model"
    and selected_value_projection.get("Property") == "value",
    "Page 8 selected-model table must display forecast_selected_model[value]")
selected_model_filters = [
    item for item in selected_model_container.get("filterConfig", {}).get("filters", [])
    if item.get("field", {}).get("Column", {}).get("Expression", {}).get("SourceRef", {}).get("Entity") == "forecast_selected_model"
    and item.get("field", {}).get("Column", {}).get("Property") == "field"
]
selected_model_filter_values = [
    value[0].get("Literal", {}).get("Value")
    for item in selected_model_filters
    for value in item.get("filter", {}).get("Where", [{}])[0].get("Condition", {}).get("In", {}).get("Values", [])
]
check(selected_model_filter_values == ["'selected_model'"],
    f"Page 8 selected-model visual must filter forecast_selected_model[field] to selected_model, got {selected_model_filter_values}")
selected_model_rows = partition_rows.get("forecast_selected_model", [])
selected_column = table_metadata["forecast_selected_model"]["column_properties"]["field"].get("sourceColumn", "field")
selected_value_column = table_metadata["forecast_selected_model"]["column_properties"]["value"].get("sourceColumn", "value")
selected_rows = [row for row in selected_model_rows if row.get(selected_column) == "selected_model"]
check(len(selected_rows) == 1 and selected_rows[0].get(selected_value_column) == "B2_seasonal_naive",
    f"Page 8 selected_model row must resolve to one B2_seasonal_naive value, found {selected_rows}")
check("page8ModelComparison" in page8_visuals,
    "Page 8 must include the forecast model-comparison table")
intervals_container = page8_visuals.get("page8ForecastIntervals", {})
intervals_visual = intervals_container.get("visual", {})
interval_roles = intervals_visual.get("query", {}).get("queryState", {})
check(not interval_roles.get("Series", {}).get("projections") and not interval_roles.get("Legend", {}).get("projections"),
    "Page 8 interval chart must not bind a Series or Legend field")
def y_value_column(projection: dict) -> str | None:
    """Resolve the underlying column of a Y projection.

    Value-axis fields are Sum-aggregated, so the column sits under
    field.Aggregation.Expression.Column rather than field.Column.
    """
    field = projection.get("field", {})
    if "Column" in field:
        return field["Column"].get("Property")
    aggregation = field.get("Aggregation", {})
    return aggregation.get("Expression", {}).get("Column", {}).get("Property")


interval_y_columns = {
    y_value_column(projection)
    for projection in interval_roles.get("Y", {}).get("projections", [])
}
check(interval_y_columns == {"lower", "upper"},
    f"Page 8 interval chart must use lower and upper as its two Y values, got {interval_y_columns}")
interval_filters = intervals_container.get("filterConfig", {}).get("filters", [])
interval_filter_map = {
    item.get("field", {}).get("Column", {}).get("Property"): [
      value[0].get("Literal", {}).get("Value")
      for value in item.get("filter", {}).get("Where", [{}])[0].get("Condition", {}).get("In", {}).get("Values", [])
    ]
    for item in interval_filters
    if item.get("field", {}).get("Column", {}).get("Expression", {}).get("SourceRef", {}).get("Entity") == "forecast_intervals"
}
check(interval_filter_map.get("model") == ["'B2_seasonal_naive'"]
    and interval_filter_map.get("coverage") == ["0.95D"],
    f"Page 8 interval chart must filter to B2_seasonal_naive and 0.95 coverage, got {interval_filter_map}")
available_coverages = [float(row["coverage"]) for row in partition_rows.get("forecast_intervals", [])]
check(bool(available_coverages) and max(available_coverages) == 0.95,
    "Page 8 interval coverage filter must use the widest source coverage level")
interval_title = intervals_visual.get("visualContainerObjects", {}).get("title", [{}])[0].get("properties", {}).get("text", {}).get("expr", {}).get("Literal", {}).get("Value", "")
check("95%" in interval_title,
    "Page 8 interval chart title must state its 95% coverage level")

for tooltip_name in ("ReportSectionT1KpiTooltip", "ReportSectionT2EvidenceTooltip"):
    tooltip_page = json.loads((PAGE_ROOT / tooltip_name / "page.json").read_text(encoding="utf-8"))
    check(tooltip_page.get("type") == "Tooltip"
        and tooltip_page.get("pageBinding", {}).get("type") == "Tooltip"
        and tooltip_page.get("width") == 320 and tooltip_page.get("height") == 240,
        f"{tooltip_name}: tooltip page type, binding, or 320x240 dimensions are invalid")

def tooltip_section(visual_doc: dict) -> str | None:
    """The report tooltip page a visual points at, or None."""
    properties = visual_doc.get("visual", {}).get("visualContainerObjects", {}).get("visualTooltip", [{}])[0].get("properties", {})
    literal = properties.get("section", {}).get("expr", {}).get("Literal", {}).get("Value")
    return literal.strip("'") if isinstance(literal, str) else None

for page_name in expected_page_names[:5]:
    page_visual_root = PAGE_ROOT / page_name / "visuals"
    for visual_dir in page_visual_root.iterdir():
      visual_doc = json.loads((visual_dir / "visual.json").read_text(encoding="utf-8"))
      if visual_doc.get("visual", {}).get("visualType") == "card":
        check(tooltip_section(visual_doc) == "ReportSectionT1KpiTooltip",
            f"{page_name}/{visual_dir.name}: KPI card must use T1")
for page_name, visual_name in (("ReportSection1ExecutiveOverview", "driverAttributionWaterfall"),
                     ("ReportSection6EvidenceMatrix", "page6EvidenceMatrix")):
    visual_doc = json.loads((PAGE_ROOT / page_name / "visuals" / visual_name / "visual.json").read_text(encoding="utf-8"))
    check(tooltip_section(visual_doc) == "ReportSectionT2EvidenceTooltip",
        f"{page_name}/{visual_name}: visual must use T2")

for page_name, table_name, column_name in (("ReportSectionD1StoreDetail", "Store", "store_label"),
                             ("ReportSectionD2ProductDetail", "Product", "product_label")):
    drill_page = json.loads((PAGE_ROOT / page_name / "page.json").read_text(encoding="utf-8"))
    binding = drill_page.get("pageBinding", {})
    parameters = binding.get("parameters", [])
    field = parameters[0].get("fieldExpr", {}) if parameters else {}
    expression = field.get("Column", {})
    entity = expression.get("Expression", {}).get("SourceRef", {}).get("Entity")
    check(drill_page.get("type") == "Drillthrough" and binding.get("type") == "Drillthrough"
        and entity == table_name and expression.get("Property") == column_name
        and binding.get("acceptsFilterContext") == "Default",
        f"{page_name}: drill-through field or keep-all-filter context is invalid")
    back = json.loads((PAGE_ROOT / page_name / "visuals" / ("d1Back" if page_name.endswith("D1StoreDetail") else "d2Back") / "visual.json").read_text(encoding="utf-8"))
    back_type = back.get("visual", {}).get("visualContainerObjects", {}).get("visualLink", [{}])[0].get("properties", {}).get("type", {}).get("expr", {}).get("Literal", {}).get("Value")
    check(back.get("visual", {}).get("visualType") == "actionButton" and back_type == "'Back'",
        f"{page_name}: a functional Back action button is required")

page4_doc = json.loads((PAGE_ROOT / "ReportSection4ReturnsQuality" / "page.json").read_text(encoding="utf-8"))
check({"source": "page4Period", "target": "page4Cohort", "type": "NoFilter"}
      in page4_doc.get("visualInteractions", []),
      "Page 4 period slicer must not filter the sale-cohort visual")
page4_visuals = PAGE_ROOT / "ReportSection4ReturnsQuality" / "visuals"
page4_placeholder = json.loads((page4_visuals / "page4DefectPlaceholder" / "visual.json").read_text(encoding="utf-8"))
page4_text = page4_placeholder.get("visual", {}).get("objects", {}).get("general", [{}])[0].get("properties", {}).get("paragraphs", [{}])[0].get("textRuns", [{}])[0].get("value", "")
check(page4_text.startswith("WORDING NOT AVAILABLE:"),
      "Page 4 gap must remain a neutral note that asserts no evidence")

for page_name in expected_page_names[1:]:
    page_visual_root = PAGE_ROOT / page_name / "visuals"
    for visual_dir in page_visual_root.iterdir():
        visual_doc = json.loads((visual_dir / "visual.json").read_text(encoding="utf-8"))
        if visual_doc.get("visual", {}).get("visualType") == "tableEx":
            total_show = visual_doc.get("visual", {}).get("objects", {}).get("total", [{}])[0].get("properties", {}).get("show", {}).get("expr", {}).get("Literal", {}).get("Value")
            check(total_show == "false", f"{page_name}/{visual_dir.name}: table totals must be off")
print("[10b] page requirements: Page 2 gaps, Page 3 filter, Page 4 interaction, neutral wording, and table totals checked")

# --------------------------------------------------------------------------- 10c. page 9 data quality
# Page 9 reads seven standalone DQ extracts. Checks: placement, governed wording, no slicer, no
# measure or non-DQ field, no relationship or DAX on the DQ tables, and the governed figures.
# Defined here, not imported from the builder, so the check does not trust the code it checks.
IDENTIFIER_COLUMN = re.compile(r"^(.*_key|.*_id|.*year.*|t)$").match
DQ_TABLES = {"dq_rule_results", "dq_issue_log", "curated_validation", "kpi_reconciliation",
             "dq_store_week_health", "dq_check_catalogue", "dq_quarantine_by_table"}
P9 = "ReportSection9DataQuality"
p9_root = PAGE_ROOT / P9
pages_order = json.loads((PAGE_ROOT / "pages.json").read_text(encoding="utf-8")).get("pageOrder", [])
check(P9 in pages_order and pages_order.index(P9) == pages_order.index("ReportSection8Forecast") + 1,
      f"Page 9 must follow Page 8 directly in pages.json: {pages_order}")
check(json.loads((p9_root / "page.json").read_text(encoding="utf-8")).get("displayName") == "9 Data quality",
      "Page 9 displayName must be '9 Data quality'")

p9_docs = {d.name: json.loads((d / "visual.json").read_text(encoding="utf-8"))
           for d in sorted((p9_root / "visuals").iterdir())}


def p9_entities(value: object, found: set[str], measures: list[str]) -> None:
    """Collect every SourceRef entity and every Measure reference in a visual document."""
    if isinstance(value, dict):
        if "Entity" in value and isinstance(value["Entity"], str):
            found.add(value["Entity"])
        if "Measure" in value:
            measures.append(json.dumps(value["Measure"])[:80])
        for item in value.values():
            p9_entities(item, found, measures)
    elif isinstance(value, list):
        for item in value:
            p9_entities(item, found, measures)


def p9_title(doc: dict) -> str:
    """A visual's container title text, without PBIR quotes."""
    title = doc.get("visual", {}).get("visualContainerObjects", {}).get("title", [{}])[0]
    return title.get("properties", {}).get("text", {}).get("expr", {}).get("Literal", {}).get("Value", "").strip("'")


def p9_text(doc: dict) -> str:
    """The text of a text-box visual."""
    general = doc.get("visual", {}).get("objects", {}).get("general", [{}])[0].get("properties", {})
    runs = general.get("paragraphs", [{}])[0].get("textRuns", [{}])
    return "".join(run.get("value", "") for run in runs)


p9_entity_set: set[str] = set()
p9_measure_refs: list[str] = []
for doc in p9_docs.values():
    p9_entities(doc, p9_entity_set, p9_measure_refs)
check(not (p9_entity_set - DQ_TABLES), f"Page 9 references non-DQ tables: {sorted(p9_entity_set - DQ_TABLES)}")
check(not p9_measure_refs, f"Page 9 must not use DAX measures: {p9_measure_refs[:5]}")
check(not [n for n, d in p9_docs.items() if d.get("visual", {}).get("visualType") == "slicer"],
      "Page 9 must have no slicer (data quality is not period-based)")
check(p9_text(p9_docs.get("page9Subtitle", {})) ==
      "FAIL = issue detected and treated by its rule; treated data feeds the analysis.",
      "Page 9 subtitle wording differs from the governed text")

cards = {n: d for n, d in p9_docs.items() if d.get("visual", {}).get("visualType") == "card"}
check(len(cards) == 8, f"Page 9 expects 8 cards, found {len(cards)}")
quarantine_card = json.dumps(p9_docs.get("page9RowsQuarantined", {}))
check('"Entity": "dq_quarantine_by_table"' in quarantine_card and '"rows_quarantined"' in quarantine_card
      and '"Function": 0' in quarantine_card and "filterConfig" not in p9_docs.get("page9RowsQuarantined", {}),
      "Rows quarantined card must Sum dq_quarantine_by_table[rows_quarantined] with no filter")
check("Quarantine-rule fails" in json.dumps(p9_docs.get("page9RulesQuarantineFailed", {})),
      "The 145-row card must be labelled 'Quarantine-rule fails'")
for name, label in (("page9ValidationPass", "Curated PASS"), ("page9ValidationWarn", "Curated WARN")):
    check(f'"nativeQueryRef": "{label}"' in json.dumps(p9_docs.get(name, {})), f"{name} label must be {label!r}")
check(p9_title(p9_docs.get("page9KpiReconciliation", {})) == "KPI reconciliation: raw vs curated",
      "KPI reconciliation table title must be 'KPI reconciliation: raw vs curated'")


# Every page 9 aggregation must count rows or sum values. Function 2 is Distinct count in the
# PBIR enum; it turned 51 PASS checks into 13 and 38,138 issue rows into about 20.
def p9_functions(value: object, out: list[int]) -> None:
    """Collect every aggregation function id used anywhere in a visual document."""
    if isinstance(value, dict):
        if "Aggregation" in value and isinstance(value["Aggregation"], dict):
            out.append(value["Aggregation"].get("Function"))
        for item in value.values():
            p9_functions(item, out)
    elif isinstance(value, list):
        for item in value:
            p9_functions(item, out)


for name, doc in p9_docs.items():
    functions: list[int] = []
    p9_functions(doc, functions)
    check(2 not in functions, f"Page 9 {name}: distinct count (Function 2) is not allowed; use Count (5)")
    check(set(functions) <= {0, 5}, f"Page 9 {name}: only Sum (0) or Count (5) allowed, found {sorted(set(functions))}")
    if doc.get("visual", {}).get("visualType") == "card":
        labels = json.dumps(doc.get("visual", {}).get("objects", {}).get("labels", []))
        check('"1D"' in labels and '"0L"' in labels,
              f"Page 9 {name}: card must show full numbers (display units None, 0 decimals)")
for name, title in (("page9IssueActions", "Issue-log actions by type"),
                    ("page9QuarantineByTable", "Quarantined rows by table"),
                    ("page9IssueSeverity", "Issue-log rows by table and severity")):
    check(p9_title(p9_docs.get(name, {})) == title, f"Page 9 {name} title must be {title!r}")
check("filterConfig" not in p9_docs.get("page9IssueActions", {}),
      "Issue-log actions chart must show every action type (no filter)")
severity_query = p9_docs.get("page9IssueSeverity", {}).get("visual", {}).get("query", {}).get("queryState", {})


def role_properties(role: str) -> list[str]:
    """Column names projected into one query role (the generator writes the axis role as Category)."""
    return [p.get("field", {}).get("Column", {}).get("Property")
            for p in severity_query.get(role, {}).get("projections", [])]


check(p9_docs.get("page9IssueSeverity", {}).get("visual", {}).get("visualType") == "barChart"
      and role_properties("Category") == ["table_name"] and role_properties("Series") == ["severity"],
      "Issue-log severity chart must be stacked by table_name with severity as legend")
check(json.dumps(p9_docs.get("page9CheckCatalogue", {})).count("Check catalogue (C1 to C12)") == 1,
      "Check catalogue title must be 'Check catalogue (C1 to C12)'")

# The DQ tables stay standalone: no relationship and no measure on any of them.
check(not [t for t in DQ_TABLES if re.search(rf"\b{t}\.", rel_text)],
      "DQ tables must have no relationships")
check(not [t for t in DQ_TABLES if re.search(r"(?m)^\s*measure ", (DEF / "tables" / f"{t}.tmdl").read_text(encoding="utf-8"))],
      "DQ tables must carry no DAX measures")

# Governed figures, read from the extracts the page uses.
DQ_DIR = PBI / "dq_data"


def dq_rows(stem: str) -> list[dict]:
    """All rows of a powerbi/dq_data extract as text."""
    with open(DQ_DIR / f"{stem}.csv", encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


lineage_q = json.loads((ROOT / "reports" / "phase3" / "lineage.json").read_text(encoding="utf-8"))["quarantine_rows"]
derived_q = {r["table"]: int(r["rows_quarantined"]) for r in dq_rows("dq_quarantine_by_table")}
validation_status = [r["status"] for r in dq_rows("curated_validation")]
check(derived_q == {k: int(v) for k, v in lineage_q.items()},
      "dq_quarantine_by_table.csv must equal lineage.json quarantine_rows")
check(len(dq_rows("dq_rule_results")) == 85, "dq_rule_results must hold 85 rules")
check((validation_status.count("PASS"), validation_status.count("WARN")) == (51, 2),
      "curated_validation must be 51 PASS / 2 WARN")
check(len(dq_rows("dq_store_week_health")) == 2080, "dq_store_week_health must hold 2,080 store-weeks")
check(len(dq_rows("dq_check_catalogue")) == 12, "dq_check_catalogue must hold 12 checks")

# M types against the CSV values: every non-blank value in a numeric or logical column must
# convert, or Power BI reports load errors (dq_checks_failed once raised 794 of them).
M_TYPE = re.compile(r'\{"([^"]+)", (Int64\.Type|type number|Currency\.Type|type logical|type text|type date)\}')
INT_TEXT = re.compile(r"^-?\d+(\.0+)?$")
NUM_TEXT = re.compile(r"^-?(\d+(\.\d*)?|\.\d+)([eE][-+]?\d+)?$")
m_type_errors: dict[str, list[str]] = {}
dq_format_gaps: list[str] = []
for table in sorted(DQ_TABLES):
    tmdl = (DEF / "tables" / f"{table}.tmdl").read_text(encoding="utf-8")
    m_types = dict(M_TYPE.findall(tmdl))
    rows = dq_rows(table)
    check(rows and set(m_types) == set(rows[0]), f"{table}: M type step columns differ from the CSV header")
    for column, m_type in m_types.items():
        if m_type == "Int64.Type":
            bad = [r[column] for r in rows if r[column] and not INT_TEXT.match(r[column])]
        elif m_type in ("type number", "Currency.Type"):
            bad = [r[column] for r in rows if r[column] and not NUM_TEXT.match(r[column])]
        elif m_type == "type logical":
            bad = [r[column] for r in rows if r[column] and r[column].lower() not in ("true", "false")]
        else:
            bad = []
        if bad:
            m_type_errors[f"{table}[{column}] {m_type}"] = sorted(set(bad))[:3] + [f"({len(bad)} rows)"]
    # Thousands separators on every numeric amount; identifier columns are checked below.
    for column in re.findall(r"(?m)^\tcolumn (\S+)\n\t\tdataType: (?:int64|double|decimal)\n(?!\t\tformatString: \"#,0)", tmdl):
        if not IDENTIFIER_COLUMN(column):
            dq_format_gaps.append(f"{table}[{column}]")
check(not m_type_errors, f"Page 9 M types reject CSV values (load errors in Desktop): {m_type_errors}")
check(not dq_format_gaps, f"Page 9 numeric DQ columns without a thousands-separator format: {dq_format_gaps[:8]}")

# Keys, ids, years and the week index are labels: a grouped format would print 202,527 for
# retail week 202527. Checked on every table in the model, not only the DQ tables.
identifier_formats = []
for table_file in sorted((DEF / "tables").glob("*.tmdl")):
    for column, fmt in re.findall(r'(?m)^\tcolumn \'?([^\n\']+)\'?\n(?:\t\t[^\n]*\n)*?\t\tformatString: "?([^"\n]*)"?$',
                                  table_file.read_text(encoding="utf-8")):
        if IDENTIFIER_COLUMN(column) and "#,0" in fmt:
            identifier_formats.append(f"{table_file.stem}[{column}] {fmt}")
check(not identifier_formats, f"key/id/year columns must not use a '#,0' format: {identifier_formats[:8]}")
# Category axes must be bare columns: an aggregation there collapses every category into one
# value and left the Page 5 post-promotion dip chart blank. Checked on every page.
aggregated_axes = []
for visual_json in sorted(PAGE_ROOT.glob("*/visuals/*/visual.json")):
    axis = json.loads(visual_json.read_text(encoding="utf-8")).get("visual", {}).get("query", {}).get(
        "queryState", {}).get("Category", {}).get("projections", [])
    if any("Aggregation" in projection.get("field", {}) for projection in axis):
        aggregated_axes.append(f"{visual_json.parts[-4]}/{visual_json.parts[-2]}")
check(not aggregated_axes, f"category axes must not be aggregated: {aggregated_axes}")
# Page 5 post-promotion dip: a 100px box is too small for a chart plot, so it is a two-row
# table of the bare year and the summed shortfall, sorted by year, in its original position.
dip = json.loads((PAGE_ROOT / "ReportSection5Promotions" / "visuals" / "page5PostPromotionDip" / "visual.json").read_text(encoding="utf-8"))
dip_values = dip.get("visual", {}).get("query", {}).get("queryState", {}).get("Values", {}).get("projections", [])
dip_fields = [("Column", p["field"]["Column"]["Property"]) if "Column" in p.get("field", {})
              else ("Sum" if p.get("field", {}).get("Aggregation", {}).get("Function") == 0 else "other",
                    p.get("field", {}).get("Aggregation", {}).get("Expression", {}).get("Column", {}).get("Property"))
              for p in dip_values]
dip_sort = dip.get("visual", {}).get("query", {}).get("sortDefinition", {}).get("sort", [{}])[0].get("field", {})
dip_container = dip.get("visual", {}).get("visualContainerObjects", {})
dip_title_shown = dip_container.get("title", [{}])[0].get("properties", {}).get("show", {}).get(
    "expr", {}).get("Literal", {}).get("Value")
dip_alt = dip_container.get("general", [{}])[0].get("properties", {}).get("altText", {}).get(
    "expr", {}).get("Literal", {}).get("Value", "")
dip_objects = json.dumps(dip.get("visual", {}).get("objects", {}))
check(dip.get("visual", {}).get("visualType") == "tableEx"
      and dip_fields == [("Column", "retail_year"), ("Sum", "post_dip_revenue")]
      and dip_sort.get("Column", {}).get("Property") == "retail_year"
      and dip["position"] == {"x": 16, "y": 612, "z": 0, "height": 100, "width": 400, "tabOrder": dip["position"].get("tabOrder")},
      "Page 5 post-promotion dip must be a Year / Sum(post_dip_revenue) table at 16,612 400x100")
# A title leaves room for the header only; the rows must fit without a scrollbar.
check(dip_title_shown == "false"
      and "Post-promotion shortfall: €23K (2024) to €110K (2025)" in dip_alt
      and '"rowPadding"' in dip_objects and dip_objects.count('"9L"') == 2,
      "Page 5 post-promotion dip: title off with its text in alt text, 9pt grid and zero row padding")

print(f"[10c] page 9: {len(p9_docs)} visuals, {len(cards)} cards, tables={sorted(p9_entity_set)}, "
      f"measures={len(p9_measure_refs)}, quarantined={sum(derived_q.values()):,}, "
      f"M type errors={sum(len(v) for v in m_type_errors.values())}, unformatted numeric columns={len(dq_format_gaps)}")

# --------------------------------------------------------------------------- 6. field references
measures_defined = {n.replace("''", "'") for n in gen_names}
ref_problems = []
total_refs = 0

def literal_text(value: object) -> str:
    """A PBIR literal as plain text: quotes and the D/L type suffix removed."""
    if not isinstance(value, str):
        return str(value)
    if len(value) >= 2 and value[0] == "'" and value[-1] == "'":
        return value[1:-1].replace("''", "'")
    return value[:-1] if value.endswith(("D", "L")) else value

for vdir in all_visual_dirs:
    v = json.loads((vdir / "visual.json").read_text(encoding="utf-8"))
    roles = v["visual"].get("query", {}).get("queryState", {})
    visual_type = v.get("visual", {}).get("visualType")
    if visual_type in {"lineChart", "areaChart", "barChart"}:
        legend_count = sum(len(roles.get(role, {}).get("projections", [])) for role in ("Legend", "Series"))
        check(legend_count <= 1,
              f"{vdir.name}: {visual_type} has {legend_count} fields in Legend/Series, maximum is one")
    if visual_type == "card":
        card_projections = roles.get("Values", {}).get("projections", [])
        for card_projection in card_projections:
            card_field = card_projection.get("field", {}).get("Column", {})
            if not card_field:
                continue
            entity = card_field.get("Expression", {}).get("SourceRef", {}).get("Entity")
            column = card_field.get("Property")
            props = table_metadata.get(entity, {}).get("column_properties", {}).get(column, {})
            if props.get("dataType") != "string":
                continue
            source_column = props.get("sourceColumn", column)
            source_rows = partition_rows.get(entity, [])
            filtered_rows = list(source_rows)
            used_filter = False
            for filter_item in v.get("filterConfig", {}).get("filters", []):
                filter_field = filter_item.get("field", {}).get("Column", {})
                if (filter_field.get("Expression", {}).get("SourceRef", {}).get("Entity") != entity
                        or filter_item.get("type") != "Categorical"):
                    continue
                filter_column = filter_field.get("Property")
                filter_source_column = table_metadata[entity]["column_properties"].get(filter_column, {}).get("sourceColumn", filter_column)
                raw_values = filter_item.get("filter", {}).get("Where", [{}])[0].get("Condition", {}).get("In", {}).get("Values", [])
                selected_values = {literal_text(value[0].get("Literal", {}).get("Value")) for value in raw_values if value}
                if not selected_values:
                    continue
                used_filter = True
                filtered_rows = [row for row in filtered_rows if row.get(filter_source_column, "") in selected_values]
            check(used_filter and bool(source_rows) and len(filtered_rows) == 1,
                  f"{vdir.name}: text card {entity}[{column}] must have a visual filter that leaves exactly one source row; found {len(filtered_rows)}")
    seen_qref = set()
    for role, state in roles.items():
        for proj in state["projections"]:
            total_refs += 1
            if proj["queryRef"] in seen_qref:
                ref_problems.append(f"{vdir.name}: duplicate queryRef {proj['queryRef']}")
            seen_qref.add(proj["queryRef"])
            f = proj["field"]
            if "Measure" in f:
                m = f["Measure"]["Property"]
                if m not in measures_defined:
                    ref_problems.append(f"{vdir.name}: unknown measure '{m}'")
                if f["Measure"]["Expression"]["SourceRef"]["Entity"] != MEASURE_TABLE:
                    ref_problems.append(f"{vdir.name}: measure entity {f['Measure']['Expression']['SourceRef']['Entity']}")
            elif "Column" in f:
                ent = f["Column"]["Expression"]["SourceRef"]["Entity"]
                col = f["Column"]["Property"]
                if ent not in tbl_cols:
                    ref_problems.append(f"{vdir.name}: unknown table '{ent}'")
                elif col not in tbl_cols[ent]:
                    ref_problems.append(f"{vdir.name}: unknown column '{ent}[{col}]'")
            elif "Aggregation" in f:
                aggregation = f["Aggregation"]
                column = aggregation.get("Expression", {}).get("Column", {})
                ent = column.get("Expression", {}).get("SourceRef", {}).get("Entity")
                col = column.get("Property")
                if ent not in tbl_cols or col not in tbl_cols.get(ent, set()):
                    ref_problems.append(f"{vdir.name}: unresolved aggregation column '{ent}[{col}]'")
                if aggregation.get("Function") not in range(9):
                    ref_problems.append(f"{vdir.name}: invalid aggregation function {aggregation.get('Function')!r}")
            else:
                ref_problems.append(f"{vdir.name}: unsupported field kind {list(f)}")
    for filter_item in v.get("filterConfig", {}).get("filters", []):
        field = filter_item.get("field", {})
        if "Column" in field:
            column = field["Column"]
            entity = column.get("Expression", {}).get("SourceRef", {}).get("Entity")
            prop = column.get("Property")
            if entity not in tbl_cols or prop not in tbl_cols.get(entity, set()):
                ref_problems.append(f"{vdir.name}: unresolved filter column {entity}[{prop}]")
        elif "Measure" in field:
            measure = field["Measure"]
            entity = measure.get("Expression", {}).get("SourceRef", {}).get("Entity")
            prop = measure.get("Property")
            if entity != MEASURE_TABLE or prop not in measures_defined:
                ref_problems.append(f"{vdir.name}: unresolved filter measure {entity}[{prop}]")
    if vdir.name == "slicerPeriod":
        # Desktop stores a saved slicer selection at objects.general.properties.filter
        # as the filter state itself; an extra wrapper key there is silently ignored.
        selected = v.get("visual", {}).get("objects", {}).get("general", [{}])[0].get("properties", {}).get("filter", {})
        selected_values = selected.get("Where", [{}])[0].get("Condition", {}).get("In", {}).get("Values")
        check(selected.get("Version") == 2 and bool(selected.get("From"))
              and selected_values == [[{"Literal": {"Value": "'H2 2025'"}}]],
              "slicerPeriod: H2 2025 saved selection was not preserved")
period_slicers = {
    json.loads((vdir / "visual.json").read_text(encoding="utf-8"))["name"]: json.loads(
        (vdir / "visual.json").read_text(encoding="utf-8"))
    for vdir in all_visual_dirs
    if json.loads((vdir / "visual.json").read_text(encoding="utf-8"))["visual"]["visualType"] == "slicer"
    and json.loads((vdir / "visual.json").read_text(encoding="utf-8"))["visual"]
    .get("query", {}).get("queryState", {}).get("Values", {}).get("projections", [{}])[0]
    .get("field", {}).get("Column", {}).get("Property") == "period_label"
}
check(len(period_slicers) == 5,
      f"expected 5 Period slicers (pages 1 to 5), found {len(period_slicers)}")
for period_name, period_doc in period_slicers.items():
    period_properties = period_doc["visual"].get("objects", {}).get("general", [{}])[0].get("properties", {})
    period_values = period_properties.get("filter", {}).get(
        "Where", [{}])[0].get("Condition", {}).get("In", {}).get("Values")
    check(period_values == [[{"Literal": {"Value": "'H2 2025'"}}]],
          f"{period_name}: H2 2025 saved selection was not preserved")
    check(period_doc["visual"].get("syncGroup") == {"groupName": "Period",
                                                    "fieldChanges": False, "filterChanges": True},
          f"{period_name}: must sync with the other Period slicers in one group named Period")
check(len({d["visual"]["syncGroup"]["groupName"] for d in period_slicers.values()}) == 1,
      "the Period slicers must all use one sync group")
check(not ref_problems, f"field reference problems: {ref_problems[:10]}")
print(f"[11] visual field references validated: {total_refs} projections, problems={len(ref_problems)}")

legacy_measure_table_refs: list[str] = []
current_measure_entity_refs = 0
all_page_json_files = sorted(path for page_dir in report_page_dirs for path in page_dir.rglob("*.json"))
report_table_ref_keys = {"Entity", "entity", "table", "Table"}
report_query_ref_keys = {"queryRef", "nativeQueryRef"}
legacy_qualified_ref = re.compile(r"^(?:'Measures'|Measures)(?=[.\[])")


def scan_page_table_refs(value: object, path: pathlib.Path) -> None:
    """Record legacy 'Measures' table references and count Page 1 references to the renamed table."""
    global current_measure_entity_refs
    if isinstance(value, dict):
        for key, child in value.items():
            if key in report_table_ref_keys and isinstance(child, str):
                if child.casefold() == "measures":
                    legacy_measure_table_refs.append(f"{path.relative_to(ROOT)}:{key}")
                elif child.casefold() == MEASURE_TABLE.casefold():
                    if path.is_relative_to(PAGE_DIR):
                        current_measure_entity_refs += 1
            elif key in report_query_ref_keys and isinstance(child, str):
                if (key == "nativeQueryRef" and child.casefold() == "measures") or legacy_qualified_ref.match(child):
                    legacy_measure_table_refs.append(f"{path.relative_to(ROOT)}:{key}={child}")
            scan_page_table_refs(child, path)
    elif isinstance(value, list):
        for child in value:
            scan_page_table_refs(child, path)


for json_path in all_page_json_files:
    scan_page_table_refs(json.loads(json_path.read_text(encoding="utf-8")), json_path)
check(not legacy_measure_table_refs,
    f"Report still references table 'Measures': {legacy_measure_table_refs[:10]}")
check(current_measure_entity_refs == 7,
      f"expected 7 Page 1 _Measures entity references, found {current_measure_entity_refs}")
print(f"[11b] Page 1 measure table references: _Measures={current_measure_entity_refs}, legacy Measures={len(legacy_measure_table_refs)}")

# slicer coverage
slicers = [v for v in visuals if json.loads((v / "visual.json").read_text(encoding="utf-8"))["visual"]["visualType"] == "slicer"]
slicer_fields = sorted(
    json.loads((s / "visual.json").read_text(encoding="utf-8"))["visual"]["query"]["queryState"]["Values"]["projections"][0]["field"]["Column"]["Property"]
    for s in slicers)
check(slicer_fields == ["category", "period_label", "store_name"],
      f"unexpected slicer fields: {slicer_fields}")
print(f"[12] slicers: {len(slicers)} -> {slicer_fields}")

# required measures present for the 5 KPIs
kpi_measures = sorted(
    json.loads((v / "visual.json").read_text(encoding="utf-8"))["visual"]["query"]["queryState"]["Values"]["projections"][0]["field"]["Measure"]["Property"]
    for v in visuals if json.loads((v / "visual.json").read_text(encoding="utf-8"))["visual"]["visualType"] == "card")
check(kpi_measures == ["Gross Margin %", "Net Revenue", "Net Revenue YoY %", "Return Rate", "Transactions"],
      f"unexpected KPI measures: {kpi_measures}")
print(f"[13] KPI cards: {kpi_measures}")

# report scaffolding
for rel in ["definition.pbir", "definition/report.json", "definition/version.json",
            "definition/pages/pages.json", "definition/pages/pages.json"]:
    check((REPORT / rel).is_file(), f"missing report file {rel}")
check((MODEL / "definition.pbism").is_file(), "missing definition.pbism")
check((PBIP / f"{NAME}.pbip").is_file(), "missing project .pbip file")
pbir = json.loads((REPORT / "definition.pbir").read_text(encoding="utf-8"))
check(pbir["datasetReference"]["byPath"]["path"] == f"../{NAME}.SemanticModel",
      f"pbir datasetReference wrong: {pbir}")
check((REPORT / pbir["datasetReference"]["byPath"]["path"]).resolve().is_dir(),
      "pbir datasetReference does not resolve to the semantic model folder")
print("[14] PBIR scaffolding and model binding: OK")

# theme registered
rep = json.loads((REPORT / "definition" / "report.json").read_text(encoding="utf-8"))
items = [i for pkg in rep.get("resourcePackages", []) for i in pkg["items"]]
check(any(i["name"] == "BrightwaterEvidence" for i in items), "Brightwater theme not registered")
check((REPORT / "RegisteredResources" / "BrightwaterEvidence.json").is_file(), "theme file missing")
gov_theme = json.loads((PBI / "brightwater_theme.json").read_text(encoding="utf-8"))
reg_theme = json.loads((REPORT / "RegisteredResources" / "BrightwaterEvidence.json").read_text(encoding="utf-8"))
check(gov_theme == reg_theme, "registered theme differs from the governed theme")
print("[15] theme: Brightwater Evidence registered and byte-identical to source")

# --------------------------------------------------------------------------- 6b. schema conformance
# jsonschema is not installed, so the published schemas' hard constraints are asserted directly:
# required keys, additionalProperties:false, and the documented key sets.
ALLOWED = {
    "pbip": ({"$schema", "version", "artifacts", "settings"}, {"version", "artifacts", "settings"}),
    "pbism": ({"$schema", "version", "settings"}, {"version"}),
    "pbir": ({"$schema", "version", "datasetReference"}, {"version", "datasetReference"}),
    "report": ({"$schema", "themeCollection", "objects", "filterConfig",
                "reportSource", "publicCustomVisuals", "resourcePackages",
                "organizationCustomVisuals", "annotations", "dataSourceVariables", "settings",
                "slowDataSourceSettings"},
               {"$schema", "themeCollection", "objects", "resourcePackages", "settings"}),
    "version": ({"$schema", "version"}, {"$schema", "version"}),
    "pages": ({"$schema", "pageOrder", "activePageName"}, {"$schema"}),
    "page": ({"$schema", "name", "displayName", "displayOption", "height", "width", "filterConfig",
              "pageBinding", "objects", "visualInteractions", "type", "ordinal", "visibility"},
             {"$schema", "name", "displayOption"}),
    "visual": ({"$schema", "name", "position", "visual", "visualGroup", "parentGroupName",
                "filterConfig", "isHidden", "annotations", "howCreated"},
               {"$schema", "name", "position", "visual"}),
}
VISUAL_ALLOWED = {"visualType", "autoSelectVisualType", "query", "expansionStates", "objects",
                  "visualContainerObjects", "syncGroup", "drillFilterOtherVisuals", "howCreated"}
POS_REQUIRED = {"x", "y", "z", "height", "width", "tabOrder"}


def conform(kind: str, doc: dict, label: str) -> None:
    """Fail on any top-level key outside, or missing from, the schema's allowed set."""
    allowed, required = ALLOWED[kind]
    extra = set(doc) - allowed
    check(not extra, f"{label}: properties outside the {kind} schema: {sorted(extra)}")
    missing = required - set(doc)
    check(not missing, f"{label}: required {kind} properties missing: {sorted(missing)}")


conform("pbip", json.loads((PBIP / f"{NAME}.pbip").read_text(encoding="utf-8")), "project.pbip")
conform("pbism", json.loads((MODEL / "definition.pbism").read_text(encoding="utf-8")), "definition.pbism")
conform("pbir", json.loads((REPORT / "definition.pbir").read_text(encoding="utf-8")), "definition.pbir")
conform("report", json.loads((REPORT / "definition" / "report.json").read_text(encoding="utf-8")), "report.json")

# Nested shapes required by the reference Report schema: ThemeMetadata, ResourcePackage and ResourcePackageItem.
rep = json.loads((REPORT / "definition" / "report.json").read_text(encoding="utf-8"))
for slot in ("baseTheme", "customTheme"):
    tm = rep["themeCollection"][slot]
    check(set(tm) == {"name", "reportVersionAtImport", "type"},
          f"themeCollection.{slot} has keys {sorted(tm)}")
    check(tm["type"] in ("RegisteredResources", "SharedResources"),
          f"themeCollection.{slot}.type invalid: {tm['type']!r}")
for pkg in rep.get("resourcePackages", []):
    check({"items", "name", "type"} <= set(pkg) and set(pkg) <= {"id", "name", "type", "items", "disabled"},
          f"resourcePackage has keys {sorted(pkg)}")
    check(pkg["type"] in ("CustomVisual", "RegisteredResources", "SharedResources",
                          "OrganizationalStoreCustomVisual"),
          f"resourcePackage.type invalid: {pkg['type']!r}")
    for item in pkg["items"]:
        check(set(item) <= {"id", "name", "path", "type"} and {"name", "path", "type"} <= set(item),
              f"resourcePackageItem has keys {sorted(item)}")
        check(item["type"] in ("CustomVisualJavascript", "CustomVisualsCss", "CustomVisualScreenshot",
                               "CustomVisualIcon", "CustomVisualWatermark", "CustomVisualMetadata",
                               "Image", "ShapeMap", "CustomTheme", "BaseTheme", "DashboardTheme",
                               "DashboardBaseTheme", "HighContrastTheme", "AppNavigation",
                               "AppTheme", "AppBaseTheme"),
              f"resourcePackageItem.type invalid: {item['type']!r}")
        if pkg["type"] == "SharedResources":
            item_path = REPORT / "StaticResources" / "SharedResources" / item["path"]
        else:
            item_path = REPORT / item["path"]
        check(item_path.is_file(),
              f"resourcePackageItem path does not resolve: {item['path']}")
check(set(rep.get("settings", {})) <= {
    "isPersistentUserStateDisabled", "hideVisualContainerHeader",
    "useStylableVisualContainerHeader", "exportDataMode", "isReportAnnotationsDisabled",
    "defaultFilterActionIsDataFilter", "defaultDrillFilterOtherVisuals",
    "useCrossReportDrillthrough", "allowChangeFilterTypes", "allowInlineExploration",
    "useEnhancedTooltips", "useScaledTooltips", "filterPaneHiddenInEditMode",
    "disableFilterPaneSearch", "pagesPosition", "allowAutomatedInsightsNotification",
    "useDefaultAggregateDisplayName", "enableDeveloperMode", "pauseQueries",
    "queryLimitOption", "customMemoryLimit", "customTimeoutLimit"},
      f"report settings has unknown keys {sorted(rep.get('settings', {}))}")
print("[17b] report.json nested schema: themeCollection, resourcePackages, settings conform")
conform("version", json.loads((REPORT / "definition" / "version.json").read_text(encoding="utf-8")), "version.json")
conform("pages", json.loads((REPORT / "definition" / "pages" / "pages.json").read_text(encoding="utf-8")), "pages.json")
for page_dir in report_page_dirs:
    conform("page", json.loads((page_dir / "page.json").read_text(encoding="utf-8")), f"{page_dir.name}/page.json")
page_doc = json.loads((PAGE_DIR / "page.json").read_text(encoding="utf-8"))
page_background = page_doc.get("objects", {}).get("background", [{}])[0].get("properties", {})
check(page_background.get("color", {}).get("solid", {}).get("color", {}).get("expr", {}).get("Literal", {}).get("Value") == "'#F7F6F3'",
    f"Page 1 Brightwater background color is missing or invalid: {page_background}")
check(page_background.get("transparency", {}).get("expr", {}).get("Literal", {}).get("Value") == "0D",
    f"Page 1 background transparency should be 0D: {page_background}")
check(re.fullmatch(r"[1-9][0-9]*\.(0|[1-9][0-9]*)\.0",
                   json.loads((REPORT / "definition" / "version.json").read_text(encoding="utf-8"))["version"]) is not None,
      "version.json version does not match major.minor.patch")

if REFERENCE_REPORT.is_dir():
    reference_page_dirs = sorted(path for path in (REFERENCE_REPORT / "definition" / "pages").iterdir()
                       if path.is_dir())
    current_page_dirs = sorted(path for path in (REPORT / "definition" / "pages").iterdir()
                     if path.is_dir())
    check(len(reference_page_dirs) == 1,
        f"reference is expected to contain one sample page, found {len(reference_page_dirs)}")
    check(len(current_page_dirs) == len(expected_page_names),
        f"current Report page-folder count differs from generated specs: {len(current_page_dirs)}")
    if reference_page_dirs and current_page_dirs:
        current_page1 = REPORT / "definition" / "pages" / "ReportSection1ExecutiveOverview"
        reference_pairs = [
        ("definition.pbir", "definition.pbir"),
        ("definition/version.json", "definition/version.json"),
        ("definition/report.json", "definition/report.json"),
        ("definition/pages/pages.json", "definition/pages/pages.json"),
        ((reference_page_dirs[0] / "page.json").relative_to(REFERENCE_REPORT).as_posix(),
         (current_page1 / "page.json").relative_to(REPORT).as_posix()),
        ]
        for reference_rel, current_rel in reference_pairs:
            reference_doc = json.loads((REFERENCE_REPORT / reference_rel).read_text(encoding="utf-8"))
            current_doc = json.loads((REPORT / current_rel).read_text(encoding="utf-8"))
            reference_schema = reference_doc.get("$schema")
            if reference_schema is not None:
                check(current_doc.get("$schema") == reference_schema,
                    f"{current_rel}: $schema differs from Desktop reference: "
                    f"{current_doc.get('$schema')!r} != {reference_schema!r}")
            if "version" in reference_doc:
                check(current_doc.get("version") == reference_doc["version"],
                    f"{current_rel}: version differs from Desktop reference: "
                    f"{current_doc.get('version')!r} != {reference_doc['version']!r}")
            missing_reference_keys = set(reference_doc) - set(current_doc)
            if not current_rel.endswith("/page.json"):
                check(not missing_reference_keys,
                    f"{current_rel}: missing Desktop-reference top-level keys {sorted(missing_reference_keys)}")
            if current_rel in ("definition.pbir", "definition/version.json",
                         "definition/report.json", "definition/pages/pages.json"):
                check(set(current_doc) == set(reference_doc),
                    f"{current_rel}: top-level keys differ from Desktop reference; "
                    f"reference-only={sorted(set(reference_doc) - set(current_doc))}, "
                    f"current-only={sorted(set(current_doc) - set(reference_doc))}")

    reference_visuals = list(REFERENCE_REPORT.rglob("visual.json"))
    reference_chart_roles = []
    for reference_visual_path in reference_visuals:
        reference_visual = json.loads(reference_visual_path.read_text(encoding="utf-8"))["visual"]
        if reference_visual.get("visualType") in {"lineChart", "barChart", "areaChart", "stackedAreaChart"}:
            reference_roles = reference_visual.get("query", {}).get("queryState", {})
            reference_chart_roles.append(reference_roles)
            check("Category" in reference_roles and "CategoryAxis" not in reference_roles,
                  f"Desktop reference {reference_visual_path.name}: chart role must be Category")
            check(bool(reference_roles.get("Y", {}).get("projections")),
                  f"Desktop reference {reference_visual_path.name}: chart must have a Y projection")
    check(bool(reference_chart_roles), "Desktop PBIR reference has no line, bar, or area chart sample")
    print(f"[18] Desktop reference equality: metadata schemas checked; {len(reference_visuals)} sample visuals parsed; chart role convention checked")
else:
    failures.append(f"Desktop PBIR reference not found: {REFERENCE_REPORT}")

for vdir in all_visual_dirs:
    v = json.loads((vdir / "visual.json").read_text(encoding="utf-8"))
    conform("visual", v, vdir.name)
    visual_type = v["visual"].get("visualType")
    query_roles = v["visual"].get("query", {}).get("queryState", {})
    if visual_type in {"lineChart", "areaChart", "stackedAreaChart", "barChart", "clusteredBarChart", "clusteredColumnChart", "stackedBarChart", "stackedColumnChart"}:
        check("Category" in query_roles and "CategoryAxis" not in query_roles,
              f"{vdir.name}: {visual_type} must use the Desktop Category role, not CategoryAxis")
        legend_count = sum(len(query_roles.get(role, {}).get("projections", [])) for role in ("Legend", "Series"))
        check(legend_count <= 1,
              f"{vdir.name}: {visual_type} has {legend_count} Legend/Series projections, maximum is one")
    if visual_type == "slicer":
        check(v["position"].get("height", 0) >= 52,
              f"{vdir.name}: dropdown slicer height must be at least 52px")
        page_name = vdir.parent.parent.name
        if page_name in {
            "ReportSection2StoreCustomer", "ReportSection3ProductInventory",
            "ReportSection4ReturnsQuality", "ReportSection5Promotions",
            "ReportSection6EvidenceMatrix",
        }:
            mode_value = v["visual"].get("objects", {}).get("data", [{}])[0].get("properties", {}).get("mode", {}).get("expr", {}).get("Literal", {}).get("Value")
            check(mode_value == "'Dropdown'",
                  f"{page_name}/{vdir.name}: slicer mode must be Dropdown")
    if visual_type == "card":
        title_instances = v["visual"].get("visualContainerObjects", {}).get("title", [{}])
        title_visible = title_instances[0].get("properties", {}).get("show", {}).get("expr", {}).get("Literal", {}).get("Value") == "true"
        check(v["position"].get("height", 0) >= 100 or not title_visible,
              f"{vdir.name}: cards below 100px must hide the duplicate visual title")
    if visual_type == "tableEx" and vdir.parent.parent.name != "ReportSection1ExecutiveOverview":
        total_show = v["visual"].get("objects", {}).get("total", [{}])[0].get("properties", {}).get("show", {}).get("expr", {}).get("Literal", {}).get("Value")
        check(total_show == "false", f"{vdir.name}: table totals must be off")
    extra = set(v["visual"]) - VISUAL_ALLOWED
    check(not extra, f"{vdir.name}: visual.* properties outside VisualConfig: {sorted(extra)}")
    required_visual_keys = {"visualType", "visualContainerObjects"}
    if visual_type not in {"textbox", "actionButton"}:
        required_visual_keys.add("query")
    check(required_visual_keys <= set(v["visual"]),
          f"{vdir.name}: VisualConfig is missing required keys {required_visual_keys - set(v['visual'])}")
    check(POS_REQUIRED <= set(v["position"]), f"{vdir.name}: position missing {POS_REQUIRED - set(v['position'])}")
    check(isinstance(v["position"]["x"], (int, float)) and isinstance(v["position"]["height"], (int, float)),
          f"{vdir.name}: position values must be numbers")
print(f"[17] schema conformance: pbip/pbism/pbir/report/version/pages/page + {len(all_visual_dirs)} visuals conform")

# --------------------------------------------------------------------------- 7. staged pages
extra_pages = sorted(path.name for path in report_page_dirs if path.name not in expected_page_names)
check(not extra_pages, f"unexpected report page folders: {extra_pages}")
check(not (PBI / "Brightwater_Executive_Dashboard.pbip").exists(),
      "the superseded invalid PBIP folder should be gone")
print(f"[16] scope: {len(report_page_dirs)} expected pages generated (unexpected folders: {len(extra_pages)})")

# --------------------------------------------------------------------------- 8. official schemas
exec((pathlib.Path(__file__).resolve().parent / "schema_block.py").read_text(encoding="utf-8"))

# --------------------------------------------------------------------------- result
print()
if failures:
    print(f"VALIDATION FAILED: {len(failures)} problem(s)")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("VALIDATION PASSED: all structural, reference, layout and fidelity checks green")
