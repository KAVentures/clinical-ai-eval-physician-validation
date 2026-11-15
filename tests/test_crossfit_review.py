from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(*args):
    subprocess.run([sys.executable, *map(str, args)], cwd=ROOT, check=True)


def read_csv(path: Path):
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows):
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def packets(outdir: Path, reviewers: str = "ABC") -> list[Path]:
    return sorted(p for r in reviewers for p in outdir.glob(f"response_review_{r}_wave*.csv"))


def rows_for(outdir: Path, reviewer: str) -> list[dict]:
    return [row for path in packets(outdir, reviewer) for row in read_csv(path)]


def review_args(outdir: Path) -> list:
    return [x for path in packets(outdir) for x in ("--review", path)]


def test_crossfit_packets_and_cannot_determine_consensus(tmp_path):
    units = [
        {
            "review_unit_id": "u1", "case_text": "case1", "response_text": "resp1",
            "construct_reviewer_internal": "A",
            "response_reviewers_internal": ["B", "C"],
            "source_id_internal": "s1", "case_id_internal": "c1",
            "primary_family_internal": "missing_information",
            "presentation_internal": "perturbed", "target_id_internal": "t1",
            "target_provider_internal": "p1", "response_id_internal": "r1",
            "source_type_internal": "good_faith", "source_difficulty_internal": "typical",
            "specialty_internal": "cardiology",
        },
        {
            "review_unit_id": "u2", "case_text": "case2", "response_text": "resp2",
            "construct_reviewer_internal": "B",
            "response_reviewers_internal": ["A", "C"],
            "source_id_internal": "s2", "case_id_internal": "c2",
            "primary_family_internal": "conflicting_evidence",
            "presentation_internal": "original", "target_id_internal": "t1",
            "target_provider_internal": "p1", "response_id_internal": "r2",
            "source_type_internal": "red_teaming", "source_difficulty_internal": "difficult",
            "specialty_internal": "neurology",
        },
    ]
    unit_path = tmp_path / "units.jsonl"
    unit_path.write_text("\n".join(json.dumps(x) for x in units) + "\n", encoding="utf-8")
    outdir = tmp_path / "reviews"

    run("scripts/make_response_packets.py", "--units", unit_path, "--out-dir", outdir)

    a, b, c = (rows_for(outdir, r) for r in "ABC")
    assert {r["review_unit_id"] for r in a} == {"u2"}
    assert {r["review_unit_id"] for r in b} == {"u1"}
    assert {r["review_unit_id"] for r in c} == {"u1", "u2"}

    labels = {
        ("u1", "B"): "0", ("u1", "C"): "1",
        ("u2", "A"): "CANNOT_DETERMINE", ("u2", "C"): "0",
    }
    for path in packets(outdir):
        rows = read_csv(path)
        if not rows:
            continue
        for r in rows:
            r["unsafe_overconfident"] = labels[(r["review_unit_id"], r["reviewer_id"])]
            for endpoint in ("potentially_harmful_treatment", "recognizes_information_problem",
                             "guideline_concordant_next_step", "excessive_abstention",
                             "clinically_helpful"):
                r[endpoint] = "0"
        write_csv(path, rows)

    consensus = outdir / "response_consensus.csv"
    run(
        "scripts/response_adjudication.py", "prepare",
        "--units", unit_path,
        *review_args(outdir),
        "--out", consensus,
    )
    rows = read_csv(consensus)
    assert {r["review_unit_id"] for r in rows} == {"u1", "u2"}
    for r in rows:
        r["consensus_unsafe_overconfident"] = "1" if r["review_unit_id"] == "u1" else "CANNOT_DETERMINE"
        r["consensus_rationale"] = "locked test consensus"
    write_csv(consensus, rows)

    ref = tmp_path / "reference.csv"
    run(
        "scripts/response_adjudication.py", "finalize",
        "--units", unit_path,
        *review_args(outdir),
        "--consensus", consensus,
        "--out", ref,
    )
    got = {r["review_unit_id"]: r for r in read_csv(ref)}
    assert got["u1"]["unsafe_overconfident_reference"] == "1"
    assert got["u2"]["unsafe_overconfident_reference"] == "CANNOT_DETERMINE"
    assert got["u1"]["construct_reviewer"] == "A"
    assert {got["u1"]["response_reviewer_1"], got["u1"]["response_reviewer_2"]} == {"B", "C"}


def test_blank_secondary_label_is_refused_not_treated_as_missing(tmp_path):
    unit = {
        "review_unit_id": "u1", "case_text": "case", "response_text": "resp",
        "construct_reviewer_internal": "A", "response_reviewers_internal": ["B", "C"],
        "source_id_internal": "s1", "case_id_internal": "c1",
        "primary_family_internal": "missing_information", "presentation_internal": "perturbed",
        "target_id_internal": "t1", "response_id_internal": "r1",
    }
    unit_path = tmp_path / "units.jsonl"
    unit_path.write_text(json.dumps(unit) + "\n", encoding="utf-8")
    outdir = tmp_path / "reviews"
    run("scripts/make_response_packets.py", "--units", unit_path, "--out-dir", outdir)
    paths = packets(outdir, "BC")
    for path in paths:
        rows = read_csv(path)
        for r in rows:
            r["unsafe_overconfident"] = "0"   # secondary endpoints left blank
        write_csv(path, rows)
    paths = [p for p in paths if read_csv(p)]
    result = subprocess.run(
        [sys.executable, "scripts/response_adjudication.py", "finalize", "--units", str(unit_path),
         *[x for p in paths for x in ("--review", str(p))], "--out", str(tmp_path / "ref.csv")],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert result.returncode != 0
    assert "A blank is not a rating" in result.stderr


def test_a_sources_two_presentations_never_share_a_wave(tmp_path):
    units = []
    for i in range(12):
        for presentation in ("original", "perturbed"):
            for t in ("t1", "t2"):
                units.append({
                    "review_unit_id": f"u{i}{presentation[0]}{t}", "case_text": "c", "response_text": "r",
                    "construct_reviewer_internal": "ABC"[i % 3],
                    "response_reviewers_internal": [x for x in "ABC" if x != "ABC"[i % 3]],
                    "source_id_internal": f"s{i}", "case_id_internal": f"c{i}",
                    "primary_family_internal": "missing_information", "presentation_internal": presentation,
                    "target_id_internal": t, "response_id_internal": f"r{i}{presentation}{t}",
                })
    unit_path = tmp_path / "units.jsonl"
    unit_path.write_text("\n".join(json.dumps(x) for x in units) + "\n", encoding="utf-8")
    outdir = tmp_path / "reviews"
    run("scripts/make_response_packets.py", "--units", unit_path, "--out-dir", outdir)
    by_id = {u["review_unit_id"]: u for u in units}
    firsts = set()
    for reviewer in "ABC":
        waves = [read_csv(outdir / f"response_review_{reviewer}_wave{w}.csv") for w in (1, 2)]
        for rows in waves:
            seen = {}
            for r in rows:
                u = by_id[r["review_unit_id"]]
                seen.setdefault(u["source_id_internal"], set()).add(u["presentation_internal"])
            assert all(len(v) == 1 for v in seen.values())
        for r in waves[0]:
            firsts.add(by_id[r["review_unit_id"]]["presentation_internal"])
    assert firsts == {"original", "perturbed"}      # which goes first is randomised
