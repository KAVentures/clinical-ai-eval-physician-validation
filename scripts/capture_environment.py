#!/usr/bin/env python3
"""Capture the exact execution environment immediately before the primary lock."""
from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--requirements-out", type=Path, default=Path("data/environment_lock.txt"))
    p.add_argument("--metadata-out", type=Path, default=Path("data/environment_metadata.json"))
    args = p.parse_args()

    raw_freeze = subprocess.run(
        [sys.executable, "-m", "pip", "freeze", "--all"],
        check=True, capture_output=True, text=True,
    ).stdout
    if "clinical-ai-eval" not in raw_freeze.lower().replace("_", "-"):
        raise RuntimeError("clinical-ai-eval is not present in pip freeze; install the study package first")

    # An editable install of THIS repository can be serialized as an absolute local
    # path (e.g. -e /home/user/...); that is not reproducible elsewhere. The study
    # repository itself is already fixed by study_git_commit in study_lock.json, so
    # remove only local editable lines and reinstall the checkout separately.
    kept = []
    for line in raw_freeze.splitlines():
        stripped = line.strip()
        if stripped.startswith("-e ") and "clinical-ai-eval-physician-validation" in stripped:
            continue
        if stripped.startswith("-e /") or stripped.startswith("-e file:"):
            continue
        if stripped.startswith("# Editable install with no version control"):
            continue
        kept.append(line)
    freeze = "\n".join(kept).rstrip() + "\n"

    args.requirements_out.parent.mkdir(parents=True, exist_ok=True)
    args.requirements_out.write_text(
        "# Exact third-party environment captured for the locked study run.\n"
        "# Check out the study_git_commit from data/study_lock.json, create the Python\n"
        "# version in environment_metadata.json, install this file, then install the\n"
        "# checked-out study package with: python -m pip install -e .\n"
        + freeze,
        encoding="utf-8",
    )

    meta = {
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "python_version": sys.version,
        "python_executable": sys.executable,
        "implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "pip_version": subprocess.run(
            [sys.executable, "-m", "pip", "--version"],
            check=True, capture_output=True, text=True,
        ).stdout.strip(),
    }
    args.metadata_out.write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote {args.requirements_out}")
    print(f"Wrote {args.metadata_out}")


if __name__ == "__main__":
    main()
