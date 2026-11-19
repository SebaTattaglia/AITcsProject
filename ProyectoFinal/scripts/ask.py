#!/usr/bin/env python
"""
scripts/ask.py
Ask the assistant from the terminal and print the answer, citations and graph trace.

Run: python scripts/ask.py "How do I roll back a bad deployment?"
     python scripts/ask.py --graph        (print the LangGraph as Mermaid)
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.assistant_service import get_assistant_service  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("question", nargs="?", help="Technical question for the knowledge assistant")
    parser.add_argument("--max-attempts", type=int, default=None)
    parser.add_argument("--doc-type", default=None)
    parser.add_argument("--graph", action="store_true", help="Print the graph as Mermaid and exit")
    args = parser.parse_args()

    service = get_assistant_service()

    if args.graph:
        print(service.graph_mermaid())
        return
    if not args.question:
        parser.error("a question is required")

    result = service.ask(args.question, max_attempts=args.max_attempts, doc_type=args.doc_type)

    print(f"\nSTATUS: {result['status']}  (attempts={result['attempts']}, best_score={result['best_score']})\n")
    print(result["answer"])
    print("\nCITATIONS:")
    for citation in result["citations"]:
        print(f"  [{citation['doc_id']}] {citation['title']} > {citation['section']} ({citation['score']:.2f})")
    print("\nTRACE:")
    for step in result["trace"]:
        print(f"  - {step}")
    for warning in result["warnings"]:
        print(f"  ! {warning}")


if __name__ == "__main__":
    main()
