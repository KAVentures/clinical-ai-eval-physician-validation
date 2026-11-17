#!/usr/bin/env python3
"""Prepare cross-fitted physician consensus and finalize reference labels.

Every response cell is independently rated by exactly two physicians who were not
that case's construct reviewer. If their primary labels disagree, or either uses
CANNOT_DETERMINE, they resolve the cell only AFTER both independent submissions
are locked. Consensus may remain CANNOT_DETERMINE; it is never coerced to "safe".

Modes:
  prepare  -> generate the joint consensus sheet for non-resolved cells.
  finalize -> combine independent reviews + consensus into the physician reference.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

REVIEWERS = {"A", "B", "C"}
PRIMARY = "unsafe_overconfident"
BINARY = {"0", "1"}
CANNOT = "CANNOT_DETERMINE"
PRIMARY_ALLOWED = BINARY | {CANNOT}
SECONDARY_ALLOWED = BINARY | {CANNOT, "NA"}
SECONDARY = [
    "potentially_harmful_treatment", "recognizes_information_problem",
    "guideline_concordant_next_step", "excessive_abstention", "clinically_helpful",
]


def norm(value: object) -> str:
    s = str(value or "").strip().upper()
    if s in {"0", "NO", "FALSE"}:
        return "0"
    if s in {"1", "YES", "TRUE"}:
        return "1"
    if s in {"CANNOT_DETERMINE", "CANNOT DETERMINE", "UNABLE", "UNKNOWN"}:
        return CANNOT
    if s in {"NA", "N/A", "NOT_APPLICABLE"}:
        return "NA"
    return s


def read_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def read_jsonl(path: Path) -> list[dict]:
    out = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                out.append(json.loads(line))
    return out


def load_reviews(paths: list[Path]) -> dict[tuple[str, str], dict]:
    out: dict[tuple[str, str], dict] = {}
    for path in paths:
        for row in read_csv(path):
            reviewer = str(row.get("reviewer_id", "")).strip()
            uid = str(row.get("review_unit_id", "")).strip()
            if reviewer not in REVIEWERS:
                raise ValueError(f"{path}: invalid reviewer_id {reviewer!r}")
            if not uid:
                raise ValueError(f"{path}: missing review_unit_id")
            key = (uid, reviewer)
            if key in out:
                raise ValueError(f"duplicate response review {uid}/{reviewer}")
            value = norm(row.get(PRIMARY))
            if value not in PRIMARY_ALLOWED:
                raise ValueError(
                    f"{path}: {reviewer} primary label for {uid} must be 0, 1, or {CANNOT}; got {value!r}"
                )
            for endpoint in SECONDARY:
                sec = norm(row.get(endpoint))
                if sec not in SECONDARY_ALLOWED:
                    raise ValueError(
                        f"{path}: {reviewer} label for {endpoint} on {uid} must be one of "
                        f"0/1/NA/{CANNOT}; got {sec!r}. A blank is not a rating: it would "
                        "silently shrink that endpoint's denominator."
                    )
            out[key] = row
    return out


def expected_pair(unit: dict) -> tuple[str, str]:
    construct = str(unit.get("construct_reviewer_internal", ""))
    pair = tuple(str(x) for x in (unit.get("response_reviewers_internal") or []))
    if construct not in REVIEWERS or len(pair) != 2 or set(pair) != (REVIEWERS - {construct}):
        raise RuntimeError(f"{unit.get('review_unit_id')}: invalid cross-fit reviewer mapping")
    return tuple(sorted(pair))


def label_for(reviews: dict, uid: str, reviewer: str) -> str:
    row = reviews.get((uid, reviewer))
    if row is None:
        raise RuntimeError(f"missing locked independent review for {uid}/{reviewer}")
    return norm(row.get(PRIMARY))


ENDPOINTS = [PRIMARY, *SECONDARY]


def allowed(endpoint: str) -> set[str]:
    return PRIMARY_ALLOWED if endpoint == PRIMARY else SECONDARY_ALLOWED


def agreed(endpoint: str, a: str, b: str) -> bool:
    """Independent labels that need no discussion. NA/NA is agreement for a
    secondary endpoint (genuinely not applicable); it is never valid for the
    primary endpoint, and CANNOT_DETERMINE always goes to consensus."""
    if a != b:
        return False
    return a in BINARY or (endpoint != PRIMARY and a == "NA")


def coverage(units: dict, reviews: dict) -> None:
    expected_keys = {(uid, r) for uid, u in units.items() for r in expected_pair(u)}
    extra = set(reviews) - expected_keys
    missing = expected_keys - set(reviews)
    if extra:
        raise RuntimeError(
            f"{len(extra)} response reviews fall outside the cross-fit assignment "
            f"(e.g. {sorted(extra)[:3]}); a construct reviewer must never rate their own source")
    if missing:
        raise RuntimeError(f"independent reviews missing for {len(missing)} assignments, e.g. {sorted(missing)[:3]}")


def labels(reviews: dict, uid: str, r1: str, r2: str, endpoint: str) -> tuple[str, str]:
    return norm(reviews[(uid, r1)].get(endpoint)), norm(reviews[(uid, r2)].get(endpoint))


def prepare(args) -> None:
    """One row per cell with ANY endpoint unresolved. Every endpoint shows both
    locked labels; endpoints already agreed are prefilled and must not change."""
    units = {str(u["review_unit_id"]): u for u in read_jsonl(args.units)}
    reviews = load_reviews(args.review)
    coverage(units, reviews)

    fields = ["review_unit_id", "case_text", "response_text", "response_reviewer_pair", "needs_consensus"]
    for e in ENDPOINTS:
        fields += [f"{e}_label_1", f"{e}_label_2", f"consensus_{e}"]
    fields += ["consensus_rationale", "reviewed_at_utc"]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    n_cells, per_endpoint = 0, {e: 0 for e in ENDPOINTS}
    with args.out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for uid in sorted(units):
            u = units[uid]
            r1, r2 = expected_pair(u)
            row = {"review_unit_id": uid, "case_text": u["case_text"], "response_text": u["response_text"],
                   "response_reviewer_pair": f"{r1}+{r2}"}
            needs = []
            for e in ENDPOINTS:
                a, b = labels(reviews, uid, r1, r2, e)
                row[f"{e}_label_1"], row[f"{e}_label_2"] = a, b
                if agreed(e, a, b):
                    row[f"consensus_{e}"] = a
                else:
                    row[f"consensus_{e}"] = ""
                    needs.append(e)
            if not needs:
                continue
            row.update({"needs_consensus": ";".join(needs), "consensus_rationale": "", "reviewed_at_utc": ""})
            w.writerow(row)
            n_cells += 1
            for e in needs:
                per_endpoint[e] += 1
    print(f"Prepared {n_cells} joint-consensus cells: {args.out}")
    print("Endpoints to resolve: " + ", ".join(f"{e}={n}" for e, n in per_endpoint.items()))
    print("Fill only the blank consensus_ columns. Prefilled values are the reviewers' agreed labels and "
          "are rejected if changed. Consensus occurs only after independent labels are locked.")


def load_consensus(path: Path | None) -> dict[str, dict]:
    if path is None or not path.exists():
        return {}
    out = {}
    for row in read_csv(path):
        uid = str(row.get("review_unit_id", "")).strip()
        if not uid or uid in out:
            raise ValueError(f"missing/duplicate consensus review_unit_id {uid!r}")
        for e in ENDPOINTS:
            column = f"consensus_{e}"
            if column not in row:
                continue          # older sheets carried the primary endpoint only
            value = norm(row.get(column))
            if value not in allowed(e):
                raise ValueError(
                    f"consensus {e} for {uid} must be one of {sorted(allowed(e))}; got {value!r}. "
                    "A blank is not a decision.")
        out[uid] = row
    return out


def finalize(args) -> None:
    units = {str(u["review_unit_id"]): u for u in read_jsonl(args.units)}
    reviews = load_reviews(args.review)
    consensus = load_consensus(args.consensus)
    coverage(units, reviews)
    stray = set(consensus) - set(units)
    if stray:
        raise RuntimeError(f"consensus sheet references unknown units: {sorted(stray)[:3]}")

    out_rows = []
    counts = {e: {"consensus": 0, "cannot": 0} for e in ENDPOINTS}
    for uid in sorted(units):
        u = units[uid]
        r1, r2 = expected_pair(u)
        out = {
            "review_unit_id": uid,
            "source_id": u["source_id_internal"],
            "case_id": u["case_id_internal"],
            "primary_family": u["primary_family_internal"],
            "presentation": u["presentation_internal"],
            "target_id": u["target_id_internal"],
            "target_provider": u.get("target_provider_internal", ""),
            "target_status": u.get("target_status_internal", ""),
            "response_id": u["response_id_internal"],
            "source_type": u.get("source_type_internal", ""),
            "source_difficulty": u.get("source_difficulty_internal", ""),
            "specialty": u.get("specialty_internal", ""),
            "construct_reviewer": u["construct_reviewer_internal"],
            "response_reviewer_1": r1,
            "response_reviewer_2": r2,
        }
        for e in ENDPOINTS:
            a, b = labels(reviews, uid, r1, r2, e)
            given = norm(consensus.get(uid, {}).get(f"consensus_{e}")) if f"consensus_{e}" in consensus.get(uid, {}) else None
            if agreed(e, a, b):
                if given not in (None, a):
                    raise RuntimeError(
                        f"{uid}: consensus sheet changes the agreed {e} label {a!r} to {given!r}; "
                        "independent agreement is final")
                reference, used, value = a, False, ""
            else:
                if given is None:
                    raise RuntimeError(f"{uid}: {e} needs a locked consensus label "
                                       f"(independent labels {a!r} / {b!r})")
                reference, used, value = given, True, given
                counts[e]["consensus"] += 1
            if reference == CANNOT:
                counts[e]["cannot"] += 1
            out[f"physician_1_{e}"] = a
            out[f"physician_2_{e}"] = b
            out[f"consensus_{e}"] = value
            out[f"{e}_reference"] = reference
            out[f"{e}_consensus_used"] = str(used).lower()
            # Prespecified sensitivity analysis: the reference built from
            # independent agreement alone, before any discussion.
            out[f"{e}_reference_agreement_only"] = a if agreed(e, a, b) else "UNRESOLVED"
        out["primary_consensus_used"] = out[f"{PRIMARY}_consensus_used"]
        out_rows.append(out)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    fields = list(out_rows[0].keys()) if out_rows else []
    with args.out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(out_rows)

    print(f"Finalized {len(out_rows)} physician reference rows: {args.out}")
    for e, c in counts.items():
        print(f"  {e}: consensus used {c['consensus']}, final CANNOT_DETERMINE {c['cannot']}")


def add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--units", required=True, type=Path)
    parser.add_argument("--review", required=True, action="append", type=Path,
                        help="Completed response-review CSV; repeat for A/B/C")


def main() -> None:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("prepare")
    add_common(s)
    s.add_argument("--out", required=True, type=Path)

    s = sub.add_parser("finalize")
    add_common(s)
    s.add_argument("--consensus", type=Path)
    s.add_argument("--out", required=True, type=Path)

    args = p.parse_args()
    prepare(args) if args.command == "prepare" else finalize(args)


if __name__ == "__main__":
    main()
