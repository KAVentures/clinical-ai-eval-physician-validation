#!/usr/bin/env python3
"""Analyze post-response confirmation of the perturbation construct."""
from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path

import pandas as pd

YES = {"yes", "y", "1", "true"}
VALID = {"valid", "accept", "accepted"}


def read_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def confirmed(row: dict) -> int:
    fields = [
        "original_coherent", "perturbed_coherent", "same_patient_task_timepoint",
        "evidence_load_bearing", "construct_achieved", "safe_response_definable",
    ]
    ok = all(str(row.get(k, "")).strip().lower() in YES for k in fields)
    return int(ok and str(row.get("decision", "")).strip().lower() in VALID)


def wilson(success: int, n: int, z: float = 1.959963984540054) -> tuple[float, float]:
    if n == 0:
        return float("nan"), float("nan")
    p = success / n
    den = 1 + z * z / n
    center = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return center - half, center + half


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--review", action="append", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    args = p.parse_args()

    rows = []
    seen = set()
    for path in args.review:
        for r in read_csv(path):
            cid = str(r.get("case_id", ""))
            if not cid or cid in seen:
                raise RuntimeError(f"missing/duplicate audited case {cid!r}")
            seen.add(cid)
            r = dict(r)
            r["confirmed"] = confirmed(r)
            rows.append(r)
    df = pd.DataFrame(rows)
    out = []
    groups = [("overall", "all", df)]
    if not df.empty:
        for family, g in df.groupby("family"):
            groups.append(("family", str(family), g))
        for reviewer, g in df.groupby("reviewer_id"):
            groups.append(("reviewer", str(reviewer), g))
    for dim, value, g in groups:
        n, s = len(g), int(g["confirmed"].sum()) if n else 0
        lo, hi = wilson(s, n)
        out.append({
            "dimension": dim, "value": value, "n": n, "confirmed": s,
            "confirmation_rate": s / n if n else float("nan"),
            "wilson_95_ci_low": lo, "wilson_95_ci_high": hi,
        })
    args.out.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(out).to_csv(args.out, index=False)
    print(pd.DataFrame(out).to_string(index=False))


if __name__ == "__main__":
    main()
