#!/usr/bin/env python3
"""Create a public cryptographic study-lock manifest before primary target calls."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import yaml

from study_runtime.lock import ROOT, code_files, installed_engine_commit, pinned_engine_commit, sha_file

DEFAULT_FILES = [
    "README.md",
    "ENGINE_PIN.md",
    "configs/model_panel.yaml",
    "prompts/perturbation_author_prompt.txt",
    "prompts/target_system_prompt.txt",
    "prompts/judge_prompt.txt",
    "protocol/PROTOCOL.md",
    "protocol/STATISTICAL_ANALYSIS_PLAN.md",
    "protocol/SOURCE_STRATEGY.md",
    "protocol/SAMPLE_SIZE_JUSTIFICATION.md",
    "protocol/FRAMEWORK_VALIDATION_SCOPE.md",
    "REPRODUCIBILITY.md",
    "data/environment_lock.txt",
    "data/environment_metadata.json",
    "review/REVIEW_INSTRUCTIONS.md",
]


def portable(path: Path) -> str:
    """Repo-relative when the file is in the repository, so the lock verifies on
    any checkout; absolute only for files deliberately kept elsewhere."""
    resolved = Path(path).resolve()
    try:
        return str(resolved.relative_to(ROOT))
    except ValueError:
        return str(resolved)


def csv_rows(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--git-commit", required=True, help="Exact study repository commit to lock")
    p.add_argument("--casepack-manifest", type=Path, default=Path("data/primary_casepack_manifest.csv"))
    p.add_argument("--hbp-candidates", type=Path, default=Path("data/healthbench_professional_candidate_queue.csv"))
    p.add_argument("--real-pocqi-candidates", type=Path, default=Path("data/real_pocqi_candidate_queue.csv"))
    p.add_argument("--response-validation-manifest", type=Path,
                   default=Path("data/response_validation_case_selection.csv"))
    p.add_argument("--out", type=Path, default=Path("data/study_lock.json"))
    p.add_argument("--models", type=Path, default=Path("configs/model_panel.yaml"))
    p.add_argument("--environment-dir", type=Path, default=Path("data"),
                   help="Directory holding environment_lock.txt and environment_metadata.json")
    p.add_argument("--rehearsal", action="store_true",
                   help="Lock a synthetic rehearsal. The manifest is marked and is not a study lock.")
    args = p.parse_args()

    if not re.fullmatch(r"[0-9a-f]{40}", args.git_commit):
        raise RuntimeError("--git-commit must be a full 40-character commit SHA")

    cfg_path = args.models
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    if cfg.get("authoring_frozen") is not True:
        raise RuntimeError("authoring_frozen must be true before study lock")
    if cfg.get("frozen") is not True:
        raise RuntimeError("frozen must be true before study lock")

    case_rows = csv_rows(args.casepack_manifest)
    if len(case_rows) != 150:
        raise RuntimeError(f"primary casepack manifest must contain exactly 150 cases, got {len(case_rows)}")
    bad_framework = [
        r for r in case_rows
        if r.get("framework_variant_source") != "preconstructed"
        or r.get("framework_structural_valid") != "true"
        or r.get("framework_human_confirmed") != "true"
        or not r.get("source_variant_id")
        or r.get("primary_perturbation_id") == r.get("source_variant_id")
    ]
    if bad_framework:
        raise RuntimeError(
            f"{len(bad_framework)} primary cases do not prove passage through the "
            "Clinical-AI-Eval preconstructed manifest/validity path"
        )
    strata = {}
    for r in case_rows:
        key = (r.get("type", ""), r.get("difficulty", ""))
        strata[key] = strata.get(key, 0) + 1
    expected = {
        ("good_faith", "typical"): 53,
        ("good_faith", "difficult"): 38,
        ("red_teaming", "difficult"): 59,
    }
    if strata != expected:
        raise RuntimeError(f"primary casepack strata mismatch: {strata}")

    files = {}
    resolved = {}
    for raw in DEFAULT_FILES:
        path = Path(raw)
        if raw == "configs/model_panel.yaml":
            path = cfg_path
        elif raw.startswith("data/environment_"):
            path = args.environment_dir / Path(raw).name
        if not path.exists():
            raise RuntimeError(f"required lock file missing: {path}")
        files[raw] = sha_file(path)
        resolved[raw] = portable(path)
    for raw in code_files():
        files[raw] = sha_file(ROOT / raw)
        resolved[raw] = raw

    synthetic = [
        str(path) for path in (args.casepack_manifest, args.hbp_candidates, args.real_pocqi_candidates)
        if path.exists() and any("SYNTHETIC" in str(r.get("source_dataset", "")) for r in csv_rows(path))
    ]
    if synthetic and not args.rehearsal:
        raise RuntimeError(
            f"refusing to write a study lock over synthetic rehearsal data: {synthetic}"
        )
    if args.rehearsal and not synthetic:
        raise RuntimeError("--rehearsal was given but the manifests are not synthetic rehearsal data")

    response_rows = csv_rows(args.response_validation_manifest)
    if len(response_rows) != 60 or len({r["case_id"] for r in response_rows}) != 60:
        raise RuntimeError("response-validation manifest must contain exactly 60 unique cases")
    family_counts = {}
    for r in response_rows:
        family_counts[r["primary_family"]] = family_counts.get(r["primary_family"], 0) + 1
    if family_counts != {"missing_information": 30, "conflicting_evidence": 30}:
        raise RuntimeError(f"response-validation family mix must be 30/30, got {family_counts}")

    for path in (args.casepack_manifest, args.hbp_candidates, args.real_pocqi_candidates,
                 args.response_validation_manifest):
        if not path.exists():
            raise RuntimeError(f"required data manifest missing: {path}")
        files[str(path)] = sha_file(path)
        resolved[str(path)] = portable(path)

    engine_commit = pinned_engine_commit()
    installed = installed_engine_commit()
    if not args.rehearsal and installed != engine_commit:
        raise RuntimeError(
            f"the installed clinical-ai-eval is {installed or 'a local/unversioned install'}, not the pinned "
            f"commit {engine_commit}. Install the study with `python -m pip install -e .` in a clean "
            "environment so the engine that runs is the engine that is locked."
        )

    lock = {
        "schema": "clinical-ai-eval-physician-validation.study-lock.v1"
                  + (".REHEARSAL-NOT-A-STUDY-LOCK" if args.rehearsal else ""),
        "rehearsal": bool(args.rehearsal),
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "study_git_commit": args.git_commit,
        "engine_git_commit": engine_commit,
        "authoring_frozen": True,
        "model_panel_frozen": True,
        "primary_case_count": 150,
        "response_validation_case_count": 60,
        "response_validation_family_counts": family_counts,
        "primary_strata": {f"{k[0]}/{k[1]}": v for k, v in sorted(strata.items())},
        "installed_engine_commit": installed,
        "files_sha256": files,
        "resolved_paths": resolved,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(lock, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote immutable study-lock manifest: {args.out}")
    print(f"study commit: {args.git_commit}")
    print(f"engine commit: {engine_commit}")


if __name__ == "__main__":
    main()
