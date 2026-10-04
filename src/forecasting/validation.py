"""Pre-flight governance checks for Phase 10.

Inputs: the project root, the forecasting configuration and the freeze manifests it names.
Outputs: missing inputs, manifest checksum issues, a READY/BLOCKED status, and the validated
weekly rows with their reconciled H2 headline.
"""
import csv
import hashlib
from pathlib import Path

from .contracts import DataContractError, read_csv_rows, reconcile_h2_headline, validate_weekly_rows


# Evaluation-only assets: a manifest that references one is reported, never hashed or opened.
PROTECTED_NAMES = {"_hidden_scenario.yaml", "_scenario_answer_key.csv", "_planted_issues_log.csv"}
PROTECTED_SEGMENTS = {"evaluation"}
# Earlier phases named their manifest columns differently; accept each known spelling.
MANIFEST_COLUMNS = {
    "path": ("path", "relative_path", "file", "source_path"),
    "sha256": ("sha256", "sha_256", "checksum", "hash"),
}


def is_protected_path(path: str) -> bool:
    """True when any segment of the path names an evaluation-only asset or folder."""
    parts = Path(path.replace("\\", "/")).parts
    return any(part.lower() in PROTECTED_SEGMENTS for part in parts) or any(
        part.lower() in PROTECTED_NAMES for part in parts
    )


def sha256_file(path: Path) -> str:
    """Stream the file in 1 MB blocks and return its SHA-256 hex digest."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_manifest(root: Path, manifest_path: Path) -> list[str]:
    """Return one issue per protected, escaping, missing or changed dependency; empty when clean."""
    issues = []
    with manifest_path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        headers = {name.lower(): name for name in (reader.fieldnames or [])}
        path_column = next((headers[name] for name in MANIFEST_COLUMNS["path"] if name in headers), None)
        hash_column = next((headers[name] for name in MANIFEST_COLUMNS["sha256"] if name in headers), None)
        if not path_column or not hash_column:
            return [f"{manifest_path}: expected a path and SHA-256 column"]
        rows = list(reader)
    if not rows:
        return [f"{manifest_path}: manifest contains no dependency rows"]
    for row in rows:
        relative_path = row[path_column]
        expected = row[hash_column].strip().lower()
        if is_protected_path(relative_path):
            issues.append(f"{manifest_path}: prohibited evaluation-only dependency reference")
            # Skip before hashing: opening the file to check it would itself be the violation.
            continue
        target = (root / relative_path).resolve()
        if root.resolve() not in target.parents:
            issues.append(f"{manifest_path}: dependency path escapes project root")
        elif not target.is_file():
            issues.append(f"Missing frozen dependency: {relative_path}")
        elif sha256_file(target) != expected:
            issues.append(f"Frozen dependency checksum mismatch: {relative_path}")
    return issues


def preflight(root: Path, config: dict) -> tuple[list[str], list[str]]:
    """Return (missing inputs, manifest and output-path issues) without writing anything."""
    forecast = config["forecast"]
    required = [forecast["weekly_input"], *forecast["freeze_manifests"]]
    missing = [path for path in required if not (root / path).is_file()]
    reconciliation_candidates = forecast["phase4_reconciliation_candidates"]
    if not any((root / path).is_file() for path in reconciliation_candidates):
        missing.append("one Phase 4 reconciliation artifact: " + " or ".join(reconciliation_candidates))
    issues = []
    # Only verify checksums once every input exists; otherwise the missing list says it all.
    if not missing:
        for manifest in forecast["freeze_manifests"]:
            issues.extend(verify_manifest(root, root / manifest))
    output_path = root / forecast["outputs"]["backtest"]
    if root.resolve() not in output_path.resolve().parents:
        issues.append("Configured output path must remain inside the project root")
    return missing, issues


def load_and_validate_weekly_input(root: Path, config: dict) -> tuple[list[dict], dict]:
    """Load the weekly input and hold it to the contract, including enough history for one
    training-plus-horizon window. History shallower than that cannot support the configured
    rolling origins, so it is rejected here rather than half way through a back-test."""
    forecast = config["forecast"]
    required_rows = forecast["minimum_training_weeks"] + forecast["primary_horizon_weeks"]
    rows = validate_weekly_rows(
        read_csv_rows(root / forecast["weekly_input"]),
        grain="estate",
        require_contiguous=True,
        min_rows=required_rows,
    )
    headline = reconcile_h2_headline(rows)
    return rows, headline


def data_contract_status(root: Path, config: dict) -> str:
    """READY when pre-flight finds nothing missing and no issues, otherwise BLOCKED."""
    missing, issues = preflight(root, config)
    if missing or issues:
        return "BLOCKED"
    return "READY"
