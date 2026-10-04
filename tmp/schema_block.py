"""Permanent official-schema validation block for validate_pbip.py.

Runs inside validate_pbip.py's namespace, which supplies REPORT and check(); it is not a
standalone script. Inputs: every generated report JSON that declares a $schema, plus the
published PBIR schemas cached in tmp/pbir_schemas. Output: one check() failure per schema
violation and a [19] summary line.
"""
import json as _json
import os as _os
import pathlib as _pth
import urllib.request as _request

from jsonschema import Draft202012Validator as _Validator
from referencing import Registry as _Registry, Resource as _Resource
from referencing.jsonschema import DRAFT202012 as _DRAFT

SCHEMA_PREFIX = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/"
SCHEMA_CACHE = _pth.Path(__file__).resolve().parent / "pbir_schemas"

# The artifacts declare visualContainer 2.13.0, which is not published on the schema
# host; 2.12.0 is the nearest published version of the same family and is used instead.
SCHEMA_VERSION_FALLBACK = {"visualContainer/2.13.0": "visualContainer/2.12.0"}

_SCHEMA_STEMS = {
    "visualContainer": "visualContainer",
    "filterConfiguration": "filterConfiguration",
    "formattingObjectDefinitions": "formattingObjectDefinitions",
    "semanticQuery": "semanticQuery",
    "visualConfiguration": "visualConfiguration",
    "page": "page",
    "report": "report",
    "versionMetadata": "versionMetadata",
    "pagesMetadata": "pagesMetadata",
}

# Remote schemas are cached so validation stays deterministic and works offline.
for _name in ["visualContainer/2.12.0/schema.json",
              "page/2.1.0/schema.json",
              "report/3.3.0/schema.json",
              "versionMetadata/1.0.0/schema.json",
              "pagesMetadata/1.1.0/schema.json",
              "filterConfiguration/1.3.0/schema-embedded.json",
              "formattingObjectDefinitions/1.5.0/schema.json",
              "semanticQuery/1.4.0/schema.json",
              "visualConfiguration/2.7.0/schema-embedded.json"]:
    _dest = SCHEMA_CACHE / _name.replace("/", "-")
    if _dest.is_file():
        continue
    try:
        SCHEMA_CACHE.mkdir(parents=True, exist_ok=True)
        _req = _request.Request(SCHEMA_PREFIX + _name, headers={"User-Agent": "Mozilla/5.0"})
        with _request.urlopen(_req, timeout=90) as _resp:
            _dest.write_bytes(_resp.read())
    except Exception as exc:  # noqa: BLE001
        print(f"[19] WARN could not cache schema {_name}: {type(exc).__name__} {exc}")


def _schema_registry() -> _Registry:
    # Explicit cache-file -> canonical URL map. Deriving the URL from the file name
    # is brittle because the schema host uses both "schema.json" and
    # "schema-embedded.json", and the published $id spells the latter with a dot.
    mapping = {
        "visualContainer-2.12.0-schema.json": "visualContainer/2.12.0/schema.json",
        "page-2.1.0-schema.json": "page/2.1.0/schema.json",
        "report-3.3.0-schema.json": "report/3.3.0/schema.json",
        "versionMetadata-1.0.0-schema.json": "versionMetadata/1.0.0/schema.json",
        "pagesMetadata-1.1.0-schema.json": "pagesMetadata/1.1.0/schema.json",
        "filterConfiguration-1.3.0-schema-embedded.json":
            "filterConfiguration/1.3.0/schema-embedded.json",
        "formattingObjectDefinitions-1.5.0-schema.json":
            "formattingObjectDefinitions/1.5.0/schema.json",
        "semanticQuery-1.4.0-schema.json": "semanticQuery/1.4.0/schema.json",
        "visualConfiguration-2.7.0-schema-embedded.json":
            "visualConfiguration/2.7.0/schema-embedded.json",
    }
    resources = []
    for filename, rel in mapping.items():
        path = SCHEMA_CACHE / filename
        if not path.is_file():
            continue
        resources.append((
            f"{SCHEMA_PREFIX}{rel}",
            _Resource.from_contents(
                _json.loads(path.read_text(encoding="utf-8")), _DRAFT)))
    return _Registry().with_resources(resources)


def _relax_schema_const(schema: dict) -> dict:
    # A substituted schema pins $schema to its own version, which the document's declared
    # version can never match; relax that one property so real violations still surface.
    props = schema.get("properties")
    if isinstance(props, dict) and "$schema" in props:
        schema = dict(schema)
        schema["properties"] = dict(props)
        schema["properties"]["$schema"] = {"type": "string"}
    return schema


def schema_documents() -> list[tuple[str, _pth.Path]]:
    """Every generated JSON that carries an official $schema, with its declared URL."""
    found = []
    for dirpath, dirnames, files in _os.walk(REPORT.parent):
        if ".pbi" in dirpath:
            # Desktop's local cache folders are not part of the report definition.
            continue
        for fn in files:
            if not fn.endswith(".json"):
                continue
            path = _pth.Path(dirpath) / fn
            try:
                doc = _json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if isinstance(doc, dict) and "$schema" in doc:
                found.append((doc["$schema"], path))
    return found


def check_official_schemas() -> None:
    """Validate every $schema-bearing document against the published schema."""
    registry = _schema_registry()
    docs = schema_documents()
    by_schema: dict[str, list[_pth.Path]] = {}
    for declared, path in docs:
        by_schema.setdefault(declared, []).append(path)

    total_violations = 0
    substituted_any = False
    unavailable: list[str] = []

    for declared, paths in sorted(by_schema.items()):
        stem = declared.replace(SCHEMA_PREFIX, "")
        if stem.endswith("/schema.json"):
            stem = stem[: -len("/schema.json")]
        url = declared
        if stem in SCHEMA_VERSION_FALLBACK:
            substituted_any = True
            url = f"{SCHEMA_PREFIX}{SCHEMA_VERSION_FALLBACK[stem]}/schema.json"
        schema_file = SCHEMA_CACHE / url.replace(SCHEMA_PREFIX, "").replace("/", "-")
        if not schema_file.is_file():
            unavailable.append(url)
            check(False, f"official schema unavailable, cannot validate: {url}")
            continue
        schema = _json.loads(schema_file.read_text(encoding="utf-8"))
        if url != declared:
            schema = _relax_schema_const(schema)
        validator = _Validator(schema, registry=registry)
        for path in sorted(paths):
            doc = _json.loads(path.read_text(encoding="utf-8"))
            for err in validator.iter_errors(doc):
                pointer = "/".join(str(x) for x in err.absolute_path) or "<root>"
                rel = path.relative_to(REPORT.parent)
                check(False, f"{rel}: schema violation at {pointer}: {err.message}")
                total_violations += 1

    # Self-test: prove the validator actually reaches nested schemas, so a broken
    # registry or ref can never make this block silently pass.
    probe_schema = _json.loads(
        (SCHEMA_CACHE / "visualContainer-2.12.0-schema.json").read_text(encoding="utf-8"))
    probe_schema = _relax_schema_const(probe_schema)
    probe = _Validator(probe_schema, registry=registry)
    base = {"$schema": "x", "name": "selfTest",
            "position": {"x": 0, "y": 0, "z": 0, "height": 10, "width": 10, "tabOrder": 0}}
    self_tests = {
        "filterConfig": {"filterConfig": {"filters": [{
            "name": "f", "type": "NotARealFilterType",
            "field": {"Column": {"Expression": {"SourceRef": {"Entity": "E"}},
                                 "Property": "C"}},
            "filter": {"Version": 2, "From": [], "Where": []}}]}},
        "position": {"position": {"x": 0, "y": 0, "height": 1, "width": 1, "tabOrder": 0}},
        "topLevel": {"someUnknownTopLevelKey": True},
    }
    for label, patch in self_tests.items():
        doc = dict(base)
        doc.update(patch)
        check(bool(list(probe.iter_errors(doc))),
              f"schema self-test '{label}' did not fail, so official-schema "
              f"validation is not reaching this part of the document")

    print(f"[19] official schema validation: {len(docs)} documents checked, "
          f"{total_violations} violation(s)"
          + (f"; substituted nearest published version for {substituted_any}"
             if substituted_any else "")
          + (f"; UNAVAILABLE {unavailable}" if unavailable else ""))


check_official_schemas()