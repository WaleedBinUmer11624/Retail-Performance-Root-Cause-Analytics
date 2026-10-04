"""Offline TMDL grammar/enum linter for the generated SemanticModel.

Desktop reports enum violations only as "TMDL Format Error / InvalidValueFormat", with no
file or property named. This check re-implements the enum domains so a bad value is caught
before Desktop QA, and reports the exact file, property and offending value.

Enum domains transcribed from the TMDL object-properties reference
(plugins/pbip/skills/tmdl/references/object-properties.md). Extend ENUMS before trusting
a new property, and keep BOOLEANS/INTEGERS/STRINGS in sync with the same reference.

Input: every .tmdl file under the generated SemanticModel definition folder.
Output: PASS, or FAIL with one line per problem; exit code 0 only when clean.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

DEFINITION = (Path(__file__).resolve().parents[1] / "powerbi" / "Brightwater_Executive_Dashboard"
              / "Brightwater_Executive_Dashboard.SemanticModel" / "definition")

ENUMS: dict[str, tuple[str, ...]] = {
    "alignment": ("default", "left", "right", "center"),
    "columnType": ("data", "calculated", "rowNumber", "calculatedTableColumn"),
    "compatibilityMode": ("unknown", "analysisServices", "powerBI", "excel"),
    "crossFilteringBehavior": ("oneDirection", "bothDirections", "automatic"),
    "dataType": ("automatic", "string", "int64", "double", "dateTime",
                 "decimal", "boolean", "binary", "unknown", "variant"),
    "dataViewType": ("full", "sample", "default"),
    "encodingHintType": ("default", "hash", "value"),
    "evaluationBehavior": ("automatic", "static", "dynamic"),
    "expressionKind": ("m",),
    "indexBuildingMode": ("off", "auto", "explicit", "full"),
    "modeType": ("import", "directQuery", "default", "push", "dual", "directLake"),
    "partitionSourceType": ("query", "calculated", "none", "m", "entity",
                           "policyRange", "calculationGroup", "inferred"),
    "powerBIDataSourceVersion": ("powerBI_V1", "powerBI_V2", "powerBI_V3"),
    "relationshipEndCardinality": ("none", "one", "many"),
    "relationshipType": ("singleColumn",),
    "summarizationType": ("groupBy", "sum", "count", "min", "max"),
    "aggregateFunction": ("default", "none", "sum", "min", "max",
                          "count", "average", "distinctCount"),
    "dateTimeRelationshipBehavior": ("dateAndTime", "datePartOnly"),
    "securityFilteringBehavior": ("oneDirection", "bothDirections", "none"),
    "readWriteMode": ("readWrite", "readOnly", "readOnlyExclusive"),
}

BOOLEANS = {
    "isActive", "isHidden", "isKey", "isDataTypeInferred", "isNameInferred",
    "isNullable", "isUnique", "isAvailableInMdx", "isDefaultLabel", "isDefaultImage",
    "keepUniqueRows", "relyOnReferentialIntegrity", "excludeFromModelRefresh",
    "excludeFromAutomaticAggregations", "isPrivate", "showAsVariationsOnly",
    "systemManaged", "hideMembers",
}
INTEGERS = {
    "compatibilityLevel", "displayOrdinal", "alternateSourcePrecedence",
    "precedence", "ordinal", "language", "maxConnections", "timeout",
    "tableDetailPosition", "maxParallelismPerQuery", "maxParallelismPerRefresh",
    "disableAutoExists",
}
STRINGLIKE = {
    "name", "description", "expression", "formatString", "displayFolder", "dataCategory",
    "lineageTag", "sourceLineageTag", "sourceColumn", "sortByColumn", "columnOrigin",
    "sourceProviderType", "queryGroup", "fromColumn", "toColumn", "culture", "collation",
    "defaultMeasure", "storageLocation", "mAttributes", "baseColumn", "baseTable",
    "expressionSource", "parameterValuesColumn", "remoteParameterName", "type",
    "sourceType", "primaryColumn", "folder", "privacy", "type_",
}

KNOWN_BOOL = {"true", "false"}


PROP_RE = re.compile(r"^(\t*)([A-Za-z_]\w*)\s*:\s*(.+?)\s*$")
REL_RE = re.compile(r"^\t*relationship\s+(\S+)\s*$")
QUALIFIED_RE = re.compile(r"[A-Za-z_]\w*\.[A-Za-z_]\w*")


def check_file(path: Path) -> list[str]:
    """Validate every `prop: value` line, plus relationship column qualification.

    TMDL as emitted here is indentation-based (braceless at both top level and for nested
    members), so parsing is by indent depth rather than braces. Block ownership is only
    needed for relationship endpoint checks, so it is tracked just for that scope.
    """
    problems: list[str] = []
    lines = path.read_text(encoding="utf-8").splitlines()
    rel_name: str | None = None
    rel_line = 0

    for i, raw in enumerate(lines, 1):
        line = raw.rstrip("\n")
        if line != line.rstrip():
            problems.append(f"{path.name}:{i}: trailing whitespace")
        stripped = line.lstrip("\t")
        if stripped.startswith("//"):
            continue
        if line and not line.startswith("\t") and line[:1] == " ":
            problems.append(f"{path.name}:{i}: space used for indentation (TMDL requires tabs)")

        m = REL_RE.match(line)
        if m:
            rel_name, rel_line = m.group(1), i

        p = PROP_RE.match(line)
        if not p:
            continue
        prop, val = p.group(2), p.group(3)

        if prop in ENUMS:
            allowed = ENUMS[prop]
            if val not in allowed:
                low = val.lower()
                # Desktop gives no hint, so suggest the closest allowed spelling.
                near = [a for a in allowed if a.lower().startswith(low[:3])]
                hint = f"; did you mean {near[0]!r}?" if near else ""
                where = f"{path.name}:{i}"
                if rel_name:
                    where += f" (relationship {rel_name})"
                problems.append(
                    f"{where}: {prop}: invalid enum {val!r}, expected one of {allowed}{hint}")
        elif prop in BOOLEANS:
            if val.lower() not in KNOWN_BOOL:
                problems.append(f"{path.name}:{i}: {prop}: invalid boolean {val!r}")
        elif prop in INTEGERS:
            if not re.fullmatch(r"-?\d+", val):
                problems.append(f"{path.name}:{i}: {prop}: invalid integer {val!r}")

        if rel_name and prop in ("fromColumn", "toColumn"):
            if not QUALIFIED_RE.fullmatch(val):
                problems.append(
                    f"{path.name}:{i} (relationship {rel_name}): {prop}: {val!r} "
                    f"is not a qualified Table.Column")

    return problems


def main() -> int:
    """Lint every .tmdl file in the definition tree and print the result; return the exit code."""
    if not DEFINITION.is_dir():
        print(f"FAIL definition tree not found: {DEFINITION}")
        return 1
    files = sorted(DEFINITION.rglob("*.tmdl"))
    if not files:
        print(f"FAIL no .tmdl files under {DEFINITION}")
        return 1
    all_problems: list[str] = []
    for f in files:
        all_problems += check_file(f)
    if all_problems:
        print(f"FAIL {len(all_problems)} TMDL grammar problem(s) across {len(files)} files:")
        for p in all_problems:
            print("  " + p)
        return 1
    print(f"PASS TMDL grammar/enum check clean across {len(files)} .tmdl files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
