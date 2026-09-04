#!/usr/bin/env python3
"""Create a new immutable perturbation version after a physician requests revision.

This utility never edits an existing draft. The revised case text is supplied from
a private local file and the new version is appended to the private JSONL plus an
ID/hash-only public manifest.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def read_jsonl(path: Path) -> list[dict]:
    out = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                out.append(json.loads(line))
    return out


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--drafts", required=True, type=Path)
    p.add_argument("--source-id", required=True)
    p.add_argument("--family", required=True, choices=["missing_information", "conflicting_evidence"])
    p.add_argument("--modified-case-file", required=True, type=Path)
    p.add_argument("--changed-evidence", required=True)
    p.add_argument("--safe-response-strategy", required=True)
    p.add_argument("--public-manifest", required=True, type=Path)
    args = p.parse_args()

    rows = read_jsonl(args.drafts)
    same = [
        r for r in rows
        if str(r.get("source_id")) == args.source_id and str(r.get("family")) == args.family
    ]
    if not same:
        raise RuntimeError("no prior draft exists for this source/family")
    latest = max(same, key=lambda r: int(r.get("perturbation_version", 0)))
    version = int(latest.get("perturbation_version", 0)) + 1
    pid = f"{args.source_id}::{args.family}::v{version}"
    if any(str(r.get("perturbation_id")) == pid for r in rows):
        raise RuntimeError(f"version already exists: {pid}")

    modified = args.modified_case_file.read_text(encoding="utf-8").strip()
    if not modified:
        raise RuntimeError("revised case file is empty")

    rec = dict(latest)
    rec.update({
        "perturbation_id": pid,
        "perturbation_version": version,
        "applicable_draft": True,
        "modified_case": modified,
        "changed_evidence": args.changed_evidence,
        "safe_response_strategy": args.safe_response_strategy,
        "status": "revised_draft_requires_fresh_physician_validation",
        "revision_parent_id": latest["perturbation_id"],
    })
    with args.drafts.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    existing = []
    if args.public_manifest.exists():
        with args.public_manifest.open(newline="", encoding="utf-8") as f:
            existing = list(csv.DictReader(f))
    public = {
        "source_dataset": rec.get("source_dataset", ""),
        "source_id": args.source_id,
        "perturbation_id": pid,
        "perturbation_version": version,
        "family": args.family,
        "applicable_draft": "true",
        "original_case_sha256": sha(str(rec["original_case"])),
        "modified_case_sha256": sha(modified),
        "changed_evidence_sha256": sha(args.changed_evidence),
        "author_provider": "physician_revision",
        "author_model": "",
        "author_reasoning_effort": "",
        "resolved_model": "",
        "request_sha256": "",
        "status": "revised_draft_requires_fresh_physician_validation",
    }
    fields = list(public.keys())
    merged = {str(r["perturbation_id"]): r for r in existing}
    merged[pid] = public
    args.public_manifest.parent.mkdir(parents=True, exist_ok=True)
    with args.public_manifest.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for key in sorted(merged):
            w.writerow({field: merged[key].get(field, "") for field in fields})

    print(f"Created immutable revision {pid}; it has no validity until fresh construct review.")


if __name__ == "__main__":
    main()
