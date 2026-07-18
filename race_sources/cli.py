"""CLI for Phase 4 race source bundle capture and replay."""

from __future__ import annotations

import argparse
import json
import dataclasses
from pathlib import Path

from .fetch import capture_url
from .pipeline import build_race_source_bundle, replay_race_source_bundle
from .request_workflow import create_workflow_request
from .wechat import (
    capture_wechat_article,
    persist_wechat_visual_review,
    preserve_persisted_cp_evidence_rows,
    preserve_persisted_visual_reviews,
    select_wechat_visual_evidence,
)


def _as_race_source_capture(capture: object) -> dict:
    payload = dataclasses.asdict(capture)
    payload["meta_path"] = payload["manifest_path"]
    payload["sha256"] = payload["html_sha256"]
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    capture = sub.add_parser("capture", help="capture official and supplemental race sources")
    capture.add_argument("--evidence-dir", type=Path, required=True)
    capture.add_argument("--official-url", required=True)
    capture.add_argument("--aggregator-url", required=True)
    capture.add_argument("--wechat-url", action="append", required=True, help="repeat for normal public retries; every attempt is retained")
    capture.add_argument("--output", type=Path, required=True)

    replay = sub.add_parser("replay", help="build bundle from a previously captured evidence directory")
    replay.add_argument("--evidence-dir", type=Path, required=True)
    replay.add_argument("--output", type=Path, required=True)

    request = sub.add_parser("request", help="create an immutable three-input report request")
    request.add_argument("--name", required=True)
    request.add_argument("--runner-id", required=True)
    request.add_argument("--target-event", required=True)
    request.add_argument("--output-root", type=Path, required=True)

    wechat_capture = sub.add_parser("wechat-capture", help="capture a public WeChat article and rendered image evidence")
    wechat_capture.add_argument("--url", required=True)
    wechat_capture.add_argument("--evidence-dir", type=Path, required=True)
    wechat_capture.add_argument("--output", type=Path, required=True)
    wechat_capture.add_argument("--timeout-ms", type=int, default=15_000)

    wechat_review = sub.add_parser("wechat-review", help="atomically record one visual review in the current request manifest")
    wechat_review.add_argument("--manifest", type=Path, required=True)
    wechat_review.add_argument("--candidate-id", required=True)
    wechat_review.add_argument("--target-year", required=True)
    wechat_review.add_argument("--exact-group", required=True)
    wechat_review.add_argument("--reviewer-method", required=True)
    wechat_review.add_argument("--review-result", required=True, choices=["reviewed", "reviewed_no_cp", "reviewed_cp_transcribed", "completed"])
    wechat_review.add_argument("--transcription-status", required=True, choices=["not_required", "completed"])
    wechat_review.add_argument("--cp-transcription-json", help="JSON list; required for a CP transcription")

    args = parser.parse_args()
    if args.command == "wechat-capture":
        result = capture_wechat_article(args.url, args.evidence_dir, timeout_ms=args.timeout_ms)
        payload = dataclasses.asdict(result)
        args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        return
    if args.command == "wechat-review":
        cp_transcription = json.loads(args.cp_transcription_json) if args.cp_transcription_json else None
        result = persist_wechat_visual_review(
            args.manifest, candidate_id=args.candidate_id, target_year=args.target_year,
            exact_group=args.exact_group, reviewer_method=args.reviewer_method,
            review_result=args.review_result, transcription_status=args.transcription_status,
            cp_transcription=cp_transcription,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    if args.command == "capture":
        official = capture_url(args.official_url, args.evidence_dir, source_id="hudongba_html", source_kind="official")
        aggregator = capture_url(args.aggregator_url, args.evidence_dir, source_id="zuicool_event", source_kind="third_party_aggregator")
        wechat_attempts = []
        for attempt_index, wechat_url in enumerate(args.wechat_url, start=1):
            capture_result = capture_wechat_article(
                wechat_url, args.evidence_dir / "wechat" / f"attempt-{attempt_index:02d}"
            )
            wechat_attempts.append(_as_race_source_capture(capture_result))
        candidate_manifest_path = args.evidence_dir / "wechat" / "wechat_article.candidates.manifest.json"
        previous_manifest = {}
        if candidate_manifest_path.is_file():
            try:
                previous_manifest = json.loads(candidate_manifest_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                raise ValueError("existing_wechat_candidate_manifest_invalid")
        visual_selection = preserve_persisted_visual_reviews(
            previous_manifest, select_wechat_visual_evidence(wechat_attempts)
        )
        cp_evidence_rows = preserve_persisted_cp_evidence_rows(previous_manifest, visual_selection)
        candidate_manifest_path.write_text(
            json.dumps({"attempts": wechat_attempts, "visual_selection": visual_selection, "cp_evidence_rows": cp_evidence_rows}, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        wechat = dict(wechat_attempts[0])
        wechat["attempts"] = wechat_attempts
        wechat["visual_selection"] = visual_selection
        wechat["cp_evidence_rows"] = cp_evidence_rows
        wechat["meta_path"] = str(candidate_manifest_path)
        wechat["manifest_path"] = str(candidate_manifest_path)
        bundle = build_race_source_bundle(
            official_capture=dataclasses.asdict(official),
            aggregator_capture=dataclasses.asdict(aggregator),
            wechat_capture=wechat,
        )
    elif args.command == "replay":
        bundle = replay_race_source_bundle(evidence_dir=args.evidence_dir)
    else:
        result = create_workflow_request(
            name=args.name,
            runner_id=args.runner_id,
            target_event=args.target_event,
            output_root=args.output_root,
        )
        print(json.dumps({"request_id": result["request_id"], "request_dir": str(result["request_dir"])}, ensure_ascii=False, indent=2))
        return
    args.output.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(bundle, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
