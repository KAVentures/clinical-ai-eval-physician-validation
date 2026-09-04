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
    "review/REVIEW_INSTRUCTIONS.md",
    "analysis/analyze_judge_validation.py",
    "analysis/full_sap_analysis.py",
    "analysis/precision_simulation.py",
]


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def csv_rows(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--git-commit", required=True, help="Exact study repository commit to lock")
    p.add_argument("--casepack-manifest", type=Path, default=Path("data/primary_casepack_manifest.csv"))
    p.add_argument("--hbp-candidates", type=Path, default=Path("data/healthbench_professional_candidate_queue.csv"))
    p.add_argument("--real-pocqi-candidates", type=Path, default=Path("data/real_pocqi_candidate_queue.csv"))
    p.add_argument("--out", type=Path, default=Path("data/study_lock.json"))
    args = p.parse_args()

    if not re.fullmatch(r"[0-9a-f]{40}", args.git_commit):
        raise RuntimeError("--git-commit must be a full 40-character commit SHA")

    cfg_path = Path("configs/model_panel.yaml")
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    if cfg.get("authoring_frozen") is not True:
        raise RuntimeError("authoring_frozen must be true before study lock")
    if cfg.get("frozen") is not True:
        raise RuntimeError("frozen must be true before study lock")

    case_rows = csv_rows(args.casepack_manifest)
    if len(case_rows) != 150:
        raise RuntimeError(f"primary casepack manifest must contain exactly 150 cases, got {len(case_rows)}")
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
    for raw in DEFAULT_FILES:
        path = Path(raw)
        if not path.exists():
            raise RuntimeError(f"required lock file missing: {path}")
        files[str(path)] = sha_file(path)
    for path in (args.casepack_manifest, args.hbp_candidates, args.real_pocqi_candidates):
        if not path.exists():
            raise RuntimeError(f"required data manifest missing: {path}")
        files[str(path)] = sha_file(path)

    engine = Path("ENGINE_PIN.md").read_text(encoding="utf-8")
    m = re.search(r"Commit:\s*.([0-9a-f]{40}).", engine)
    if not m:
        raise RuntimeError("ENGINE_PIN.md does not contain a full engine commit SHA")

    lock = {
        "schema": "clinical-ai-eval-physician-validation.study-lock.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "study_git_commit": args.git_commit,
        "engine_git_commit": m.group(1),
        "authoring_frozen": True,
        "model_panel_frozen": True,
        "primary_case_count": 150,
        "primary_strata": {f"{k[0]}/{k[1]}": v for k, v in sorted(strata.items())},
        "files_sha256": files,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(lock, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote immutable study-lock manifest: {args.out}")
    print(f"study commit: {args.git_commit}")
    print(f"engine commit: {m.group(1)}")


if __name__ == "__main__":
    main()
