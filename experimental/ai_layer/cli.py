"""Command-line entry point for the Phase 11 AI analytics assistant.

Renders the validated response in a readable form: answer, evidence strength, sources and
limitations. It adds no interpretation of its own and computes nothing.

Input: the question as command-line arguments. Output: the formatted answer on stdout.
"""

from __future__ import annotations

import sys
from pathlib import Path

from .runtime import create_runtime

MAX_EVIDENCE_ROWS = 8


def main() -> int:
    """Answer the question in argv; return 1 with usage text if none was given."""
    if len(sys.argv) < 2:
        print('Usage: python -m experimental.ai_layer.cli "<your question>"', file=sys.stderr)
        return 1

    question = " ".join(sys.argv[1:])
    project_root = Path(__file__).resolve().parents[2]
    # An empty environment forces the offline mock provider: the CLI never calls a live model.
    runtime = create_runtime(project_root, environ={})
    payload = runtime.assistant.ask(question).to_dict()

    print("QUESTION")
    print(f"  {question}")
    print()
    print("ANSWER")
    print(f"  {payload['answer']}")
    print()
    print("EXECUTIVE SUMMARY")
    print(f"  {payload['executive_summary']}")
    print()
    print(f"EVIDENCE STRENGTH: {payload['confidence']}")
    if payload["evidence"]:
        print(f"  {len(payload['evidence'])} governed record(s); first {MAX_EVIDENCE_ROWS}:")
        for item in payload["evidence"][:MAX_EVIDENCE_ROWS]:
            print(f"    [{item['evidence_type']}] {item['claim']}")
    print()
    print("SOURCES")
    for source in payload["sources"]:
        print(f"  {source['source_file']} ({source['phase']}, {source['retrieval_method']})")
    if not payload["sources"]:
        print("  none")
    if payload["limitations"]:
        print()
        print("LIMITATIONS")
        for note in payload["limitations"]:
            print(f"  - {note}")
    if payload["recommended_follow_up"]:
        print()
        print("SUGGESTED FOLLOW-UP")
        for note in payload["recommended_follow_up"]:
            print(f"  - {note}")
    return 0


if __name__ == "__main__":
    sys.exit(main())