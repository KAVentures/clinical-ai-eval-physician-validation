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

    freeze = subprocess.run(
        [sys.executable, "-m", "pip", "freeze", "--all"],
        check=True, capture_output=True, text=True,
    ).stdout
    if "clinical-ai-eval" not in freeze.lower().replace("_", "-"):
        raise RuntimeError("clinical-ai-eval is not present in pip freeze; install the study package first")

    args.requirements_out.parent.mkdir(parents=True, exist_ok=True)
    args.requirements_out.write_text(
        "# Exact environment captured for the locked study run.\n"
        "# Recreate with the Python version in environment_metadata.json, then:\n"
        "#   python -m pip install -r data/environment_lock.txt\n"
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
