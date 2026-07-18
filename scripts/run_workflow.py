#!/usr/bin/env python3
"""Fail-closed dispatcher for the bundled trail-race-strategist runtime.

Workflow modules are distributed with this Skill.  The dispatcher never falls
back to a machine-specific project checkout or to an arbitrary Python path.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import NoReturn


SKILL_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_RELATIVE = Path("runtime_manifest.json")
STATE_RELATIVE = Path("evaluation/phase8a-final-closeout-20260714-144117/phase8a_final_closeout_state.json")
WORKFLOWS = {
    "report": "report_workflow.cli",
    "runner": "itra_public_runner.cli",
    "race": "race_sources.cli",
    "course": "course_model.cli",
    "readiness": "runner_readiness.cli",
    "baseline": "baseline_prediction.cli",
    "reference": "reference_model.cli",
    "strategy": "race_strategy.cli",
    "support": "race_support.cli",
    "weather": "weather_scenario.cli",
    "live": "live_replanning.cli",
    "retro": "post_race.cli",
}
OUTPUT_FLAGS = {"--output", "--output-dir", "--output-root", "--evidence-dir"}
EXPECTED_STATE = {
    "validation_decision": "retain_distance_only",
    "full_model_status": "rejected",
    "retained_reference_model": "distance_only",
    "holdout_evaluation_run": False,
    "user_facing_prediction_allowed": False,
    "model_validated": False,
}


def fail(message: str) -> NoReturn:
    raise SystemExit(f"trail-race-strategist: {message}")


def resolve_root() -> Path:
    root = SKILL_ROOT.resolve()
    if root.drive.upper() != "E:":
        fail("bundled Skill must be installed on E:")
    return root


def load_manifest(root: Path) -> dict:
    path = root / MANIFEST_RELATIVE
    if not path.is_file():
        fail(f"bundled runtime manifest is missing: {path}")
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"cannot read bundled runtime manifest: {exc}")
    if manifest.get("schema_version") != 1 or not isinstance(manifest.get("packages"), list):
        fail("bundled runtime manifest has an unsupported schema")
    return manifest


def verify_runtime(root: Path, manifest: dict) -> None:
    for package in manifest["packages"]:
        relative = package.get("path") if isinstance(package, dict) else None
        if not isinstance(relative, str) or Path(relative).is_absolute() or ".." in Path(relative).parts:
            fail("bundled runtime manifest contains an unsafe package path")
        directory = root / relative
        if not (directory / "__init__.py").is_file() or not (directory / "cli.py").is_file():
            fail(f"bundled runtime package is incomplete: {relative}")
    contract = root / "reporting_contract.py"
    if not contract.is_file():
        fail("bundled runtime shared reporting contract is missing")
    if not (root / "requirements.txt").is_file():
        fail("bundled runtime dependency list is missing")
    expected = manifest.get("reporting_contract_sha256")
    if not isinstance(expected, str) or hashlib.sha256(contract.read_bytes()).hexdigest() != expected:
        fail("bundled runtime shared reporting contract hash mismatch")


def python_executable(root: Path) -> Path:
    candidate = root / ".venv" / "Scripts" / "python.exe"
    if not candidate.is_file():
        fail(f"Skill virtual environment not found: {candidate}; create it from the bundled requirements.txt")
    return candidate


def bootstrap_virtual_environment(root: Path, arguments: list[str]) -> int:
    if arguments:
        fail("bootstrap accepts no arguments")
    venv = root / ".venv"
    python = python_executable(root) if venv.is_dir() else None
    if python is None:
        created = subprocess.run([sys.executable, "-m", "venv", str(venv)], cwd=root, check=False)
        if created.returncode:
            return created.returncode
        python = python_executable(root)
    return subprocess.run(
        [str(python), "-m", "pip", "install", "-r", str(root / "requirements.txt")],
        cwd=root,
        check=False,
    ).returncode


def load_state(root: Path) -> dict:
    path = root / STATE_RELATIVE
    if not path.is_file():
        fail(f"audited Phase 8A closeout is missing: {path}")
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"cannot read audited Phase 8A closeout: {exc}")
    mismatches = {key: [state.get(key), expected] for key, expected in EXPECTED_STATE.items() if state.get(key) != expected}
    if mismatches:
        fail(f"evaluation state mismatch: {json.dumps(mismatches, ensure_ascii=False)}")
    return state


def check_output_paths(arguments: list[str]) -> None:
    for index, token in enumerate(arguments):
        if token not in OUTPUT_FLAGS:
            continue
        if index + 1 >= len(arguments):
            fail(f"{token} requires a path")
        target = Path(arguments[index + 1]).expanduser().resolve()
        if target.drive.upper() != "E:":
            fail(f"write target must be on E: ({token} {target})")


def parse(argv: list[str]) -> tuple[bool, str, list[str]]:
    dry_run = False
    index = 0
    while index < len(argv) and argv[index].startswith("--"):
        token = argv[index]
        if token == "--dry-run":
            dry_run = True
            index += 1
        elif token == "--list":
            print("\n".join(["bootstrap", "status", *WORKFLOWS]))
            raise SystemExit(0)
        elif token in {"--help", "-h"}:
            print(__doc__)
            print("usage: run_workflow.py [--dry-run] <bootstrap|status|workflow> [arguments ...]")
            print("workflows:", ", ".join(WORKFLOWS))
            raise SystemExit(0)
        else:
            fail(f"unknown wrapper option: {token}")
    if index >= len(argv):
        fail("missing workflow; use --list")
    return dry_run, argv[index], argv[index + 1 :]


def main(argv: list[str] | None = None) -> int:
    dry_run, workflow, arguments = parse(list(argv or sys.argv[1:]))
    root = resolve_root()
    manifest = load_manifest(root)
    verify_runtime(root, manifest)
    state = load_state(root)
    if workflow == "bootstrap":
        if dry_run:
            fail("--dry-run cannot be used with bootstrap")
        return bootstrap_virtual_environment(root, arguments)
    if workflow == "status":
        print(json.dumps({"runtime": "bundled", **{key: state.get(key) for key in EXPECTED_STATE}}, ensure_ascii=False, indent=2))
        return 0
    module = WORKFLOWS.get(workflow)
    if module is None:
        fail(f"unknown workflow: {workflow}")
    check_output_paths(arguments)
    command = [str(python_executable(root)), "-m", module, *arguments]
    if dry_run:
        print(json.dumps({"cwd": str(root), "command": command, "state": EXPECTED_STATE}, ensure_ascii=False, indent=2))
        return 0
    return subprocess.run(command, cwd=root, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
