"""CLI for safe offline Phase 7B/8B research runs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .graph import build_reference_graph
from .predictor import build_multipath_prediction
from .writer import write_reference_outputs


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Phase 7B/8B internal reference model")
    sub = parser.add_subparsers(dest="command", required=True)
    graph = sub.add_parser("build-graph", help="Build reference_graph.json from approved offline inputs")
    graph.add_argument("--target", type=Path, required=True)
    graph.add_argument("--records", type=Path, required=True)
    graph.add_argument("--exclusions", type=Path)
    graph.add_argument("--output", type=Path, required=True)
    predict = sub.add_parser("predict", help="Build graph and internal multipath candidate")
    predict.add_argument("--target", type=Path, required=True)
    predict.add_argument("--records", type=Path, required=True)
    predict.add_argument("--baseline", type=Path, required=True)
    predict.add_argument("--modifiers", type=Path)
    predict.add_argument("--exclusions", type=Path)
    predict.add_argument("--require-two-independent-paths", action="store_true")
    predict.add_argument("--output-dir", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    target = _load(args.target)
    records_payload = _load(args.records)
    records = records_payload.get("records", records_payload) if isinstance(records_payload, dict) else records_payload
    exclusions = _load(args.exclusions) if args.exclusions else []
    graph = build_reference_graph(target=target, records=records, manual_exclusions=exclusions)
    if args.command == "build-graph":
        args.output.parent.mkdir(parents=True, exist_ok=True)
        if args.output.exists():
            raise FileExistsError(args.output)
        args.output.write_text(json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8")
        return 0
    prediction = build_multipath_prediction(
        reference_graph=graph,
        distance_only_baseline=_load(args.baseline),
        verified_modifiers=_load(args.modifiers) if args.modifiers else None,
        require_two_independent_reference_paths=args.require_two_independent_paths,
    )
    write_reference_outputs(graph=graph, prediction=prediction, output_dir=args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
