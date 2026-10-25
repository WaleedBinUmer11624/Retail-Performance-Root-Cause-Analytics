"""Verify that protected project outputs still match their recorded group hashes.

Inputs: tmp/protected_hash_baseline.txt and the files in each protected group (Power BI data,
Power Query, governed measures, model definition, freeze manifests, phase 1 to 10 reports, PBIX).
Output: a PASS/FAIL line per group and an overall result; exit code 0 only when every group passes.
This is an author-machine governance check: on a fresh clone it reports FAIL, because it hashes git-ignored
generated files (the .pbix and the generated data/powerbi files) that a clone does not have.
"""
import hashlib
import json
import re
import sys
from pathlib import Path

# The project root is this file's parent folder, so the check works wherever the repository is cloned.
ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "tmp" / "protected_hash_baseline.txt"

# Evaluation-only material is excluded so the check never opens it and its regeneration
# cannot fail the baseline.
EXCLUDE_PARTS = {"evaluation"}
EXCLUDE_EXACT = {"_hidden_scenario.yaml"}
EXCLUDE_PREFIX = ("_scenario_answer_key", "_planted_issues_log")
EXCLUDE_SUBSTR = ("calibration",)


def is_excluded(rel: Path) -> bool:
    """Return True when any path segment marks the file as evaluation-only."""
    for part in rel.parts:
        if part in EXCLUDE_PARTS:
            return True
        if part in EXCLUDE_EXACT:
            return True
        if part.startswith(EXCLUDE_PREFIX):
            return True
        if any(s in part for s in EXCLUDE_SUBSTR):
            return True
    return False


def collect(paths):
    """Expand files and folders into sorted (case-folded key, path) pairs, minus excluded files."""
    files = []
    for p in paths:
        if not p.exists():
            continue
        if p.is_file():
            files.append(p)
            continue
        for f in p.rglob("*"):
            if f.is_file():
                files.append(f)
    out = []
    seen = set()
    for f in files:
        rel = f.relative_to(ROOT)
        if is_excluded(rel):
            continue
        # Windows paths are case-insensitive, so case-fold to avoid hashing one file twice.
        key = rel.as_posix().casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append((key, f))
    out.sort(key=lambda t: t[0])
    return out


def group_hash(files):
    """Return (file count, sha256) over each file's relative path and bytes, in a stable order."""
    if files and isinstance(files[0], tuple):
        files = [t[1] for t in files]
    ordered = sorted(
        {f.relative_to(ROOT).as_posix().casefold(): f for f in files}.values(),
        key=lambda f: f.relative_to(ROOT).as_posix().casefold(),
    )
    h = hashlib.sha256()
    # Length-prefix each field so a rename or a moved byte cannot produce the same digest.
    for f in ordered:
        rel = f.relative_to(ROOT).as_posix()
        data = f.read_bytes()
        h.update(len(rel).to_bytes(8, "big"))
        h.update(rel.encode("utf-8"))
        h.update(len(data).to_bytes(8, "big"))
        h.update(data)
    return len(files), h.hexdigest()


def phase_dirs():
    """Return the reports/phase1 to reports/phase10 folders."""
    out = []
    for i in range(1, 11):
        out.append(ROOT / "reports" / f"phase{i}")
    return out


def build_groups():
    """Map each protected group name to its paths, or to a marker resolved in main()."""
    pd = phase_dirs()
    return {
        "powerbi_data_csv": [ROOT / "powerbi" / "data"],
        "source_date_csv": [ROOT / "data" / "powerbi"],
        "forecast_data": [ROOT / "powerbi" / "forecast_data"],
        "power_query": [ROOT / "powerbi" / "power_query"],
        "governed_measure_source": [ROOT / "powerbi" / "dax" / "measures_tmdl.tmdl"],
        "model_definition": [ROOT / "powerbi" / "model_definition.json"],
        "freeze_manifests": "FREEZE",
        "phase1_10_outputs": "ALL",
        "existing_pbix": "PBIX",
    }


def main():
    """Hash every group, compare with the baseline and print the report; return the exit code."""
    groups = build_groups()
    pd = phase_dirs()

    freeze = []
    for d in pd:
        if not d.exists():
            continue
        for f in d.rglob("*"):
            if not f.is_file():
                continue
            n = f.name.lower()
            if "manifest" in n or "freeze" in n:
                freeze.append(f)

    pbix = []
    if (ROOT / "powerbi").exists():
        pbix = [f for f in (ROOT / "powerbi").glob("*.pbix") if f.is_file()]

    results = {}
    for name, spec in groups.items():
        if spec == "FREEZE":
            results[name] = group_hash(sorted(set(freeze)))
        elif spec == "ALL":
            results[name] = group_hash(collect(pd))
        elif spec == "PBIX":
            results[name] = group_hash(pbix)
        else:
            results[name] = group_hash(collect(spec))

    expected = {}
    for line in BASELINE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("PROTECTED"):
            continue
        m = re.match(r"^(\S+)\s+files=(\d+)\s+sha256=([0-9a-fA-F]{64})$", line)
        if not m:
            continue
        expected[m.group(1)] = (int(m.group(2)), m.group(3).lower())

    all_pass = True
    print("PROTECTED HASH CHECK")
    print("=" * 78)
    print(f"{'group':<24}{'files':>7}  {'expected':>7}  {'result'}")
    print("-" * 78)
    for name in groups:
        if name not in expected:
            print(f"{name:<24}  (not in baseline)")
            all_pass = False
            continue
        e_files, e_hash = expected[name]
        r_files, r_hash = results[name]
        ok = (e_files == r_files) and (e_hash == r_hash)
        all_pass = all_pass and ok
        status = "PASS" if ok else "FAIL"
        if ok:
            print(f"{name:<24}{r_files:>7}  {e_files:>7}  {status}  {r_hash[:16]}...")
        else:
            print(f"{name:<24}{r_files:>7}  {e_files:>7}  {status}")
            print(f"{'':<24}  expected files={e_files} sha256={e_hash}")
            print(f"{'':<24}  actual   files={r_files} sha256={r_hash}")
    print("-" * 78)
    print("OVERALL: " + ("PASS" if all_pass else "FAIL"))
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
