#!/usr/bin/env python3
"""Run the no-network synthetic rehearsal for the complete study machinery.

This is intentionally cheap: it does not call model APIs or download benchmark
text. It exercises the deterministic source/casepack logic, cross-fitted physician
workflow, failure semantics, provider request serialization, and analysis code.
"""
from __future__ import annotations

import subprocess
import sys


TESTS = [
    "tests/test_provider_runtime.py",
    "tests/test_framework_adapter.py",
    "tests/test_casepack_workflows.py",
    "tests/test_calibration_selection.py",
    "tests/test_crossfit_review.py",
    "tests/test_judge_analysis.py",
]


def run(cmd: list[str]) -> None:
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)


def main() -> None:
    run([sys.executable, "-m", "compileall", "-q", "scripts", "analysis", "study_runtime", "tests"])
    run([sys.executable, "-m", "pytest", "-q", *TESTS])
    run([
        sys.executable, "analysis/precision_simulation.py",
        "--simulations", "20", "--bootstrap", "20",
        "--seed", "20260904", "--out", "/tmp/clinical_ai_eval_precision_smoke.csv",
    ])
    print("\nPASS: synthetic publication workflow rehearsal completed without network/API calls.")


if __name__ == "__main__":
    main()
