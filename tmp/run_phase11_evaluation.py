"""Run the Phase 11 evaluation suite offline and record the golden results.

Input: the governed artifacts read by the experimental assistant in mock mode (no API key).
Output: per-case PASS/FAIL lines, the acceptance verdict, and
reports/phase11/golden_question_results.csv; exit code 0 only when the suite is accepted.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# The Windows console defaults to a legacy code page that cannot print every answer character.
sys.stdout.reconfigure(encoding="utf-8")

from experimental.ai_layer.evaluation import run_evaluation, write_golden_results
from experimental.ai_layer.runtime import create_runtime

OUTPUT = ROOT / "reports/phase11/golden_question_results.csv"

runtime = create_runtime(ROOT, environ={})
report = run_evaluation(runtime.assistant, runtime.retriever)

for result in report.results:
    print(f"{result.case_id} {result.category:<13} "
          f"{'PASS' if result.passed else 'FAIL'}  {result.detail}")

import json
from experimental.ai_layer.evaluation import evaluate_case, EVALUATION_CASES

# Diagnostic only: print the ungrounded figures behind the first factual-consistency failure.
for case in EVALUATION_CASES:
    result = evaluate_case(runtime.assistant, case, runtime.retriever)
    if "factual_consistency" in result.metrics and not result.metrics["factual_consistency"]:
        payload = runtime.assistant.ask(case.question, case.mode).to_dict()
        from experimental.ai_layer.grounding import (
            check_numeric_grounding, collect_allowed_values)
        report_issues = check_numeric_grounding(
            payload["answer"], collect_allowed_values(list(payload["evidence"])))
        print("DIAG", case.case_id, [issue.detail for issue in report_issues.issues][:3])
        break

accepted, reason = report.acceptance()
print("-" * 78)
print("cases:", len(report.results), "passed:", len(report.passed), "failed:", len(report.failed))
print("categories:", len(report.categories_covered))
print("acceptance:", "PASS" if accepted else "FAIL", "-", reason)
write_golden_results(report, OUTPUT)
print("wrote", OUTPUT.relative_to(ROOT).as_posix())
sys.exit(0 if accepted else 1)