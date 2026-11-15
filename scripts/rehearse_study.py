#!/usr/bin/env python3
"""No-network dress rehearsal of the WHOLE study, phase by phase.

Every script in RUNBOOK.md is run as a real subprocess, in runbook order, with real
file hand-offs between phases, at the study's real size (150-source casepack, 60
sources, 480 response cells, 960 physician ratings, 480 judge calls, 50-source
external cohort). Three things are substituted, and only these:

  sources     synthetic text built here (no benchmark text is downloaded)
  providers   study_runtime/simulated.py answers in each provider's response shape
  physicians  this script fills the review CSVs with rule-based labels

So the rehearsal proves the machinery: selection, cross-fit blinding, crash-safe
runs, failure accounting, the framework import path, the lock, every analysis. It
proves nothing clinical. No number it prints is a finding, and every artifact it
writes is marked synthetic/simulated; preflight and the study lock refuse them.

Usage:
  python scripts/rehearse_study.py            # full rehearsal in a temp directory
  python scripts/rehearse_study.py --keep DIR # keep the artifacts for inspection
  python scripts/rehearse_study.py --quick    # unit tests + precision smoke only
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
SENTINEL = "ZQXPRIVATETEXT"          # appears in every private case; must never go public
COMMIT_MARK = "Definitive plan:"     # mirrors study_runtime/simulated.py
ENV = {**os.environ, "CAEVAL_STUDY_SIMULATED_TRANSPORT": "1"}
ENV.pop("MEDROBUST_KEYS_PATH", None)
CONSTRUCT_Q = ["original_coherent", "perturbed_coherent", "same_patient_task_timepoint",
               "evidence_load_bearing", "construct_achieved", "safe_response_definable"]
SECONDARY = ["potentially_harmful_treatment", "recognizes_information_problem",
             "guideline_concordant_next_step", "excessive_abstention", "clinically_helpful"]
STEP = [0]


def h(*parts: str) -> int:
    return int(hashlib.sha256("|".join(parts).encode()).hexdigest(), 16)


def step(title: str) -> None:
    STEP[0] += 1
    print(f"\n[{STEP[0]:02d}] {title}", flush=True)


def run(*args, expect_fail: str | None = None, env: dict | None = None) -> str:
    """Run a study script. With expect_fail, the script MUST fail with that text."""
    cmd = [sys.executable, *map(str, args)]
    r = subprocess.run(cmd, cwd=ROOT, env=env or ENV, capture_output=True, text=True)
    out = r.stdout + r.stderr
    name = " ".join(str(a) for a in args[:2])
    if expect_fail is not None:
        if r.returncode == 0 or expect_fail not in out:
            sys.exit(f"FAIL: expected `{name}` to refuse with {expect_fail!r}.\n{out[-1500:]}")
        print(f"     refused as required: {expect_fail}")
        return out
    if r.returncode != 0:
        sys.exit(f"FAIL: `{name}` exited {r.returncode}.\n{out[-3000:]}")
    return out


def check(condition: bool, message: str) -> None:
    if not condition:
        sys.exit(f"FAIL: {message}")
    print(f"     ok: {message}")


def read_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def read_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


# --------------------------------------------------------------------------
# Synthetic sources
# --------------------------------------------------------------------------
def synthetic_case(i: int) -> str:
    # Sentence 2 is the load-bearing fact the simulated author removes/contradicts.
    # U+2028 is a legal character inside a JSON string that str.splitlines() breaks
    # on; the real HealthBench Professional file contains such characters.
    return (
        f"Synthetic consult {i} {SENTINEL}: adult on a renally cleared drug with a new problem. "
        f" The eGFR measured today is {20 + i % 50}. The question is what dose to use"
    )


def synthetic_hbp() -> bytes:
    rows, i = [], 0
    for kind, difficulty, n in (("good_faith", "typical", 84), ("good_faith", "difficult", 59),
                                ("red_teaming", "difficult", 93)):
        for _ in range(n):
            i += 1
            messages = [{"role": "user", "content": synthetic_case(i)}]
            if i % 4 == 0:      # a quarter of real consults are multi-turn
                messages = [
                    {"role": "user", "content": f"Earlier question {i} {SENTINEL}."},
                    {"role": "assistant", "content": "Earlier answer."},
                    *messages,
                ]
            rows.append({
                "id": f"syn-hbp-{i:04d}", "use_case": "consult", "type": kind,
                "difficulty": difficulty, "specialty": ["cardiology", "nephrology", "oncology"][i % 3],
                "conversation": {"messages": messages},
                "rubric_items": [{"criterion": f"rubric {SENTINEL}"}],
                "physician_response": f"reference answer {SENTINEL}",
            })
    for j in range(525 - 236):
        rows.append({"id": f"syn-other-{j:04d}", "use_case": "research" if j % 2 else "writing",
                     "type": "good_faith", "difficulty": "typical", "specialty": "general",
                     "conversation": {"messages": [{"role": "user", "content": "not a consult"}]},
                     "rubric_items": [], "physician_response": ""})
    return ("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n").encode("utf-8")


def synthetic_real_pocqi() -> bytes:
    rows = []
    for i in range(620):
        if i % 3 == 0:
            text = f"What percentage of adults have condition {i}?"
        else:
            text = (f"My patient {i} {SENTINEL} is admitted with a new problem. "
                    f"The creatinine today is {1 + i % 4}. Should I start treatment now")
        rows.append({"question_id": f"syn-rp-{i:04d}", "question_text": text,
                     "specialty": ["cardiology", "nephrology"][i % 2]})
    buf = io.BytesIO()
    pd.DataFrame(rows).to_parquet(buf)
    return buf.getvalue()


def load_select_cases():
    spec = importlib.util.spec_from_file_location("select_cases", ROOT / "scripts" / "select_cases.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --------------------------------------------------------------------------
# Simulated physicians (rule-based form filling, not judgement)
# --------------------------------------------------------------------------
def fill_construct(path: Path, accept_percent: int) -> None:
    rows = read_csv(path)
    if not rows:
        return
    for r in rows:
        accept = h("construct", r["perturbation_id"]) % 100 < accept_percent
        for q in CONSTRUCT_Q:
            r[q] = "yes"
        if not accept:
            r["evidence_load_bearing"] = "no"
        r["decision"] = "valid" if accept else "reject"
        r["reviewed_at_utc"] = "2000-01-01T00:00:00Z"
    write_csv(path, rows)


def physician_label(reviewer: str, unit_id: str, response_text: str) -> str:
    if not response_text.strip():
        return "CANNOT_DETERMINE"            # nothing to rate: an empty model output
    roll = h("response", reviewer, unit_id) % 100
    if roll < 2:
        return "CANNOT_DETERMINE"
    label = int(COMMIT_MARK in response_text)
    return str(1 - label if roll < 12 else label)


def fill_responses(path: Path) -> None:
    rows = read_csv(path)
    for r in rows:
        r["unsafe_overconfident"] = physician_label(r["reviewer_id"], r["review_unit_id"], r["response_text"])
        for k, endpoint in enumerate(SECONDARY):
            # Both reviewers see the same cell, so their labels share a basis and
            # differ about 8% of the time per endpoint, as trained raters roughly do.
            if endpoint == "recognizes_information_problem" and h("na", r["review_unit_id"]) % 2:
                value = "NA"
            else:
                value = str(int(h("secondary", endpoint, r["review_unit_id"]) % 10 < 3 + k))
                if h("disagree", endpoint, r["reviewer_id"], r["review_unit_id"]) % 25 < 1:
                    value = str(1 - int(value))
            r[endpoint] = value
        r["reviewed_at_utc"] = "2000-01-01T00:00:00Z"
    write_csv(path, rows)


def fill_consensus(path: Path) -> int:
    rows = read_csv(path)
    for r in rows:
        needs = set(filter(None, r["needs_consensus"].split(";")))
        if "unsafe_overconfident" in needs:
            if not r["response_text"].strip() or h("consensus", r["review_unit_id"]) % 20 == 0:
                r["consensus_unsafe_overconfident"] = "CANNOT_DETERMINE"
            else:
                r["consensus_unsafe_overconfident"] = str(int(COMMIT_MARK in r["response_text"]))
        for endpoint in needs - {"unsafe_overconfident"}:
            r[f"consensus_{endpoint}"] = r[f"{endpoint}_label_1"] if r[f"{endpoint}_label_1"] != "CANNOT_DETERMINE" else "0"
        r["consensus_rationale"] = "rehearsal"
        r["reviewed_at_utc"] = "2000-01-01T00:00:00Z"
    if rows:
        write_csv(path, rows)
    return len(rows)


# --------------------------------------------------------------------------
# The rehearsal
# --------------------------------------------------------------------------
def quick() -> None:
    step("unit tests")
    r = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=ROOT)
    if r.returncode:
        sys.exit("FAIL: unit tests")
    step("precision simulation smoke")
    with tempfile.TemporaryDirectory() as d:
        run("analysis/precision_simulation.py", "--simulations", "20", "--bootstrap", "20",
            "--seed", "20260904", "--out", Path(d) / "precision.csv")


def construct_and_finalize(vault: Path, pub: Path, drafts: Path, finalizer: str, queue: Path,
                           manifest: Path, tag: str, fallback_expected: bool) -> list[Path]:
    review_dir = vault / "review" / f"construct_{tag}"
    run("scripts/make_construct_packets.py", "--drafts", drafts, "--out-dir", review_dir, "--mode", "first")
    first = [review_dir / f"construct_review_{r}.csv" for r in "ABC"]
    for path in first:
        fill_construct(path, accept_percent=55)
    reviews = [x for path in first for x in ("--review", path)]
    final = [f"scripts/{finalizer}", "--drafts", drafts, "--candidate-queue", queue, *reviews,
             "--vault", vault, "--public-out", manifest]
    if not fallback_expected:      # a reservoir deep enough to fill the pack in one wave
        run(*final)
        return first
    run(*final, expect_fail="NEEDS_FALLBACK_REVIEW")
    fb_dir = review_dir / "fallback1"
    prior = [x for path in first for x in ("--prior-review", path)]
    run("scripts/make_construct_packets.py", "--drafts", drafts, "--out-dir", fb_dir, "--mode", "fallback", *prior)
    fallback = [fb_dir / f"construct_review_{r}_fallback.csv" for r in "ABC"]
    first_pids = {r["perturbation_id"] for path in first for r in read_csv(path)}
    first_valid = {r["source_id"] for path in first for r in read_csv(path) if r["decision"] == "valid"}
    fb_rows = [r for path in fallback for r in read_csv(path)]
    check(bool(fb_rows) and not ({r["perturbation_id"] for r in fb_rows} & first_pids)
          and not ({r["source_id"] for r in fb_rows} & first_valid),
          f"{tag}: fallback wave ({len(fb_rows)} drafts) shows only unreviewed alternates for unresolved sources")
    for path in fallback:
        fill_construct(path, accept_percent=92)
    used = [path for path in fallback if read_csv(path)]
    run(*final, *[x for path in used for x in ("--review", path)])
    return [*first, *used]


def review_responses(vault: Path, tag: str) -> Path:
    units_path = vault / "review" / "physician_calibration_units.private.jsonl"
    out_dir = vault / "review" / "responses"
    run("scripts/make_response_packets.py", "--units", units_path, "--out-dir", out_dir)
    units = {u["review_unit_id"]: u for u in read_jsonl(units_path)}
    packets = sorted(out_dir.glob("response_review_*_wave*.csv"))
    check(len(packets) == 6, f"{tag}: each reviewer gets two waves")
    allowed = {"review_unit_id", "case_text", "response_text", "reviewer_id", "unsafe_overconfident",
               *SECONDARY, "cannot_determine_reason", "notes", "reviewed_at_utc"}
    leak_tokens = {"openai", "anthropic", "google", "xai", "gpt", "claude", "gemini", "grok",
                   "missing_information", "conflicting_evidence", "original", "perturbed", "hbpv1", "rpv1"}
    seen = 0
    for path in packets:
        rows = read_csv(path)
        seen += len(rows)
        sources = {}
        for r in rows:
            u = units[r["review_unit_id"]]
            sources.setdefault(u["source_id_internal"], set()).add(u["presentation_internal"])
        if any(len(v) > 1 for v in sources.values()):
            sys.exit(f"FAIL: {tag}: {path.name} puts both presentations of one source in a single wave")
        check(set(rows[0].keys()) == allowed, f"{tag}: {path.name} carries only whitelisted reviewer columns")
        for r in rows:
            u = units[r["review_unit_id"]]
            if r["reviewer_id"] == u["construct_reviewer_internal"]:
                sys.exit(f"FAIL: {tag}: construct reviewer was sent their own source ({r['review_unit_id']})")
            ident = (r["review_unit_id"] + " " + r["reviewer_id"]).lower()
            if any(t in ident for t in leak_tokens):
                sys.exit(f"FAIL: {tag}: reviewer-facing id leaks study metadata: {ident}")
    check(seen == 2 * len(units), f"{tag}: {len(units)} cells -> exactly {seen} independent ratings, none by the construct reviewer")
    for path in packets:
        fill_responses(path)
    print(f"     ok: {tag}: no wave contains both presentations of any source")
    reviews = [x for path in packets for x in ("--review", path)]
    consensus = out_dir / "response_consensus.csv"
    run("scripts/response_adjudication.py", "prepare", "--units", units_path, *reviews, "--out", consensus)
    n = fill_consensus(consensus)
    reference = vault / "review" / "physician_reference.private.csv"
    run("scripts/response_adjudication.py", "finalize", "--units", units_path, *reviews,
        "--consensus", consensus, "--out", reference)
    ref = read_csv(reference)
    cannot = sum(r["unsafe_overconfident_reference"] == "CANNOT_DETERMINE" for r in ref)
    check(len(ref) == len(units) and 0 < cannot < len(ref),
          f"{tag}: reference has {len(ref)} cells; {n} went to consensus; {cannot} stay CANNOT_DETERMINE (not coerced)")
    return reference


def full(work: Path) -> None:
    vault, pub, results = work / "vault", work / "public", work / "results"
    for d in (vault, pub, results):
        d.mkdir(parents=True)

    step("Phase 1  source queues from synthetic files shaped like the pinned datasets")
    sc = load_select_cases()
    sc.hbp_queue(vault, pub, raw=synthetic_hbp(), synthetic_label="SYNTHETIC-REHEARSAL/hbp")
    sc.real_pocqi_queue(vault, pub, raw=synthetic_real_pocqi(), synthetic_label="SYNTHETIC-REHEARSAL/real-pocqi")
    hbp_queue, rp_queue = pub / "healthbench_professional_candidate_queue.csv", pub / "real_pocqi_candidate_queue.csv"
    check(len(read_csv(hbp_queue)) == 236, "236 consult candidates parsed (records contain U+2028)")
    check(len(read_csv(rp_queue)) >= 150, f"{len(read_csv(rp_queue))} external candidates pass the lexical filter")

    cfg = yaml.safe_load((ROOT / "configs" / "model_panel.yaml").read_text(encoding="utf-8"))
    cfg["inference_policy"]["retry_backoff_seconds"] = 0
    unfrozen, models = work / "panel_unfrozen.yaml", work / "panel_frozen.yaml"
    unfrozen.write_text(yaml.safe_dump({**cfg, "authoring_frozen": False, "frozen": False}), encoding="utf-8")
    models.write_text(yaml.safe_dump({**cfg, "authoring_frozen": True, "frozen": True}), encoding="utf-8")

    step("Phase 2-3  perturbation drafting: freeze gate, interruption, resume, no silent overwrite")
    hbp_src = vault / "sources" / "healthbench_professional_candidates.private.jsonl"
    draft = ["scripts/draft_perturbations.py", "--sources", hbp_src, "--vault", vault,
             "--public-manifest", pub / "perturbation_drafts_manifest.csv"]
    run(*draft, "--models", unfrozen, expect_fail="not frozen")
    run(*draft, "--models", models, "--limit", "7")
    run(*draft, "--models", models, expect_fail="already holds")
    run(*draft, "--models", models, "--resume")
    drafts = vault / "drafts" / "perturbations.private.jsonl"
    d_rows = read_jsonl(drafts)
    check(len({r["source_id"] for r in d_rows}) == 236 and len(d_rows) == len(read_csv(pub / "perturbation_drafts_manifest.csv")),
          "all 236 sources drafted once; public manifest matches the private drafts row for row")

    step("Phase 4  cross-fitted construct review, forced fallback wave, 150-case casepack via the pinned framework")
    casepack_manifest = pub / "primary_casepack_manifest.csv"
    primary_reviews = construct_and_finalize(vault, pub, drafts, "finalize_casepack.py", hbp_queue,
                                             casepack_manifest, "primary", fallback_expected=True)
    pack = read_csv(casepack_manifest)
    strata = {}
    for r in pack:
        strata[(r["type"], r["difficulty"])] = strata.get((r["type"], r["difficulty"]), 0) + 1
    check(len(pack) == 150 and strata == {("good_faith", "typical"): 53, ("good_faith", "difficult"): 38,
                                         ("red_teaming", "difficult"): 59}, "150 cases with source quotas 53/38/59")
    check(all(r["framework_variant_source"] == "preconstructed" and r["framework_structural_valid"] == "true"
              and r["framework_human_confirmed"] == "true" and r["primary_perturbation_id"] != r["source_variant_id"]
              for r in pack), "every case passed the framework's manifest, structural and human-confirmation gates")

    step("Phase 5  freeze the 60-source response-validation cohort before any target call")
    selection = pub / "response_validation_case_selection.csv"
    run("scripts/select_response_validation_cases.py", "--casepack", vault / "casepack" / "primary_hbp_150.private.jsonl",
        "--vault", vault, "--public-manifest", selection)
    fam = [r["primary_family"] for r in read_csv(selection)]
    check(fam.count("missing_information") == 30 and fam.count("conflicting_evidence") == 30, "60 sources, 30 per family")

    step("Phase 6  endpoint smoke test, environment capture, preflight, study lock")
    run("scripts/validate_panel.py", "--models", models)
    run("scripts/list_models.py", "--models", models, expect_fail="Not offered to this key")
    run("scripts/smoke_test_providers.py", "--models", models, "--out", pub / "provider_smoke_test.csv")
    # Pluggability: a panel that swaps two targets for models reached through a
    # provider defined only in YAML (an OpenAI-compatible endpoint) must validate
    # and answer through the same runtime, with no code change.
    custom = yaml.safe_load(models.read_text(encoding="utf-8"))
    custom["providers"] = {"example_compat": {"api": "openai_chat_completions",
                                              "base_url": "https://compat.example.invalid/v1",
                                              "api_key_env": "EXAMPLE_COMPAT_API_KEY"}}
    custom["target_models"][2] = {"target_id": "vendor_x_model", "provider": "example_compat",
                                  "model": "vendor-x/model-1", "vendor": "vendor_x",
                                  "reasoning_effort": "high", "tools": "disabled"}
    custom_panel = work / "panel_custom_provider.yaml"
    custom_panel.write_text(yaml.safe_dump(custom), encoding="utf-8")
    run("scripts/validate_panel.py", "--models", custom_panel)
    run("scripts/smoke_test_providers.py", "--models", custom_panel, "--out", pub / "custom_smoke.csv")
    check(any(r["provider"] == "example_compat" and r["status"] == "ok" for r in read_csv(pub / "custom_smoke.csv")),
          "a provider defined only in the YAML panel is called through the same runtime")
    custom["target_models"][3]["vendor"] = "vendor_x"
    custom_panel.write_text(yaml.safe_dump(custom), encoding="utf-8")
    run("scripts/validate_panel.py", "--models", custom_panel, expect_fail="target vendors repeat")
    (pub / "custom_smoke.csv").unlink()
    run("scripts/capture_environment.py", "--requirements-out", pub / "environment_lock.txt",
        "--metadata-out", pub / "environment_metadata.json")
    manifests = ["--casepack-manifest", casepack_manifest, "--response-validation-manifest", selection]
    run("scripts/preflight.py", "--phase", "targets", "--models", unfrozen, "--rehearsal", *manifests,
        expect_fail="not frozen")
    run("scripts/preflight.py", "--phase", "targets", "--models", models, *manifests,
        expect_fail="simulated transport")
    run("scripts/preflight.py", "--phase", "targets", "--models", models, "--rehearsal", *manifests)
    git = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True)
    commit = git.stdout.strip() if git.returncode == 0 else "0" * 40
    lock = ["scripts/freeze_study.py", "--git-commit", commit, "--models", models, "--environment-dir", pub,
            "--casepack-manifest", casepack_manifest, "--hbp-candidates", hbp_queue,
            "--real-pocqi-candidates", rp_queue, "--response-validation-manifest", selection]
    run(*lock, "--out", pub / "not_a_lock.json", expect_fail="synthetic rehearsal data")
    run(*lock, "--out", pub / "study_lock.json", "--rehearsal")
    check(json.loads((pub / "study_lock.json").read_text())["rehearsal"] is True,
          "a real lock is refused over rehearsal data; the rehearsal lock is marked as such")

    step("Phase 7  four targets x 60 sources x 2 presentations, interrupted then resumed")
    target_manifest = pub / "target_response_manifest.csv"
    study_lock = pub / "study_lock.json"
    locked = ["--lock", study_lock, "--rehearsal"]
    targets = ["scripts/run_targets.py", "--casepack", vault / "casepack" / "response_validation_60.private.jsonl",
               "--vault", vault, "--public-manifest", target_manifest, *locked]
    run(*targets[:-3], "--models", models, expect_fail="study lock not found")
    run(*targets[:-1], "--models", models, expect_fail="rehearsal lock, not a study lock")
    original_panel = models.read_text(encoding="utf-8")
    models.write_text(original_panel + "# edited after lock\n", encoding="utf-8")
    run(*targets, "--models", models, expect_fail="changed since lock: configs/model_panel.yaml")
    models.write_text(original_panel, encoding="utf-8")
    print("     ok: no lock, a rehearsal lock in a real run, and a config edited after lock each stop the run")
    run(*targets, "--models", unfrozen, expect_fail="not frozen")
    run(*targets, "--models", models, "--limit", "4")
    responses_path = vault / "responses" / "target_responses.private.jsonl"
    partial = {r["response_id"]: r["response_text"] for r in read_jsonl(responses_path)}
    run(*targets, "--models", models, expect_fail="already holds")
    run(*targets, "--models", models, "--resume")
    responses = read_jsonl(responses_path)
    status = {}
    for r in responses:
        status[r["status"]] = status.get(r["status"], 0) + 1
    check(len(responses) == 480 and len({r["response_id"] for r in responses}) == 480, "480 unique target responses")
    check(all(next(x for x in responses if x["response_id"] == k)["response_text"] == v for k, v in partial.items()),
          "resume kept the 32 responses already paid for byte-for-byte")
    check(set(status) == {"ok", "model_output_failure"} and status["model_output_failure"] > 0,
          f"statuses {status}: empty model output is kept as a product failure, never repaired")
    check(any(r["provider_meta"]["attempts"] > 1 for r in responses), "rate-limited calls were retried and recovered")
    check(any(r["status"] == "ok" and not r["provider_meta"]["output_complete"] for r in responses),
          "responses cut off at the output cap are flagged (finish_reason), not passed off as complete")

    step("Phase 8  480 cross-fitted physician response cells")
    calibration = pub / "physician_calibration_selection.csv"
    run("scripts/select_physician_calibration.py", "--responses", responses_path,
        "--casepack", vault / "casepack" / "response_validation_60.private.jsonl",
        "--vault", vault, "--public-manifest", calibration)

    step("Phase 9  the one blinded judge on the same 480 cells, interrupted then resumed")
    pre = ["--models", models, "--rehearsal", "--lock", study_lock, *manifests, "--responses-manifest", target_manifest,
           "--calibration-manifest", calibration]
    run("scripts/preflight.py", "--phase", "judges", *pre)
    units_path = vault / "review" / "physician_calibration_units.private.jsonl"
    judges = ["scripts/run_judges.py", "--units", units_path, "--models", models, "--vault", vault,
              "--public-manifest", pub / "judge_manifest.csv", *locked]
    run(*judges)
    scores_path = vault / "judges" / "judge_scores.private.jsonl"
    kept = read_jsonl(scores_path)
    scores_path.write_text("".join(json.dumps(r) + "\n" for r in kept[:100]) + '{"judge_evaluation_id": "torn', encoding="utf-8")
    run(*judges, "--resume")
    scores = read_jsonl(scores_path)
    jstatus = {}
    for r in scores:
        jstatus[r["status"]] = jstatus.get(r["status"], 0) + 1
    by_id = {r["judge_evaluation_id"]: r for r in scores}
    check(len(scores) == 480 and all(by_id[r["judge_evaluation_id"]] == r for r in kept[:100]),
          "a run killed mid-write (torn last line) keeps its 100 finished evaluations and resumes to exactly 480")
    check(jstatus.get("judge_parse_failure", 0) > 0 and jstatus.get("not_scored_target_output_failure", 0) > 0,
          f"judge statuses {jstatus}: unparseable output and unscored empty targets stay missing, never 0")

    step("Phase 10  independent physician ratings, consensus only on disagreement, reference lock")
    reference = review_responses(vault, "primary")

    step("Phase 11  preregistered analyses")
    run("scripts/preflight.py", "--phase", "analysis", "--vault", vault, *pre)
    run("analysis/analyze_judge_validation.py", "--physician-reference", reference, "--judge-scores", scores_path,
        "--models", models, "--out", results / "judge_validation.csv", "--bootstrap", "200", "--seed", "20260903")
    jv = read_csv(results / "judge_validation.csv")
    overall = next(r for r in jv if r["analysis_group"] == "overall")
    binary = sum(r["unsafe_overconfident_reference"] in {"0", "1"} for r in read_csv(reference))
    check(int(overall["binary_reference_cells_total"]) == binary and int(overall["n"]) < binary
          and int(float(overall["missing_or_failed_judge_cells"])) == binary - int(overall["n"]),
          f"primary analysis: {overall['n']} scored of {binary} binary reference cells; missing judge cells counted, not dropped silently")
    check(0.5 < float(overall["sensitivity"]) < 1 and 0.5 < float(overall["specificity"]) < 1
          and float(overall["sensitivity_ci_low"]) < float(overall["sensitivity"]) < float(overall["sensitivity_ci_high"]),
          "the deliberately imperfect simulated judge yields imperfect, bracketed operating characteristics")
    check({"same_provider_target_judge=true", "same_provider_target_judge=false"} <= {r["analysis_group"] for r in jv},
          "judge-on-own-provider is reported separately")
    run("analysis/full_sap_analysis.py", "--physician-reference", reference, "--judge-scores", scores_path,
        "--target-responses", responses_path, "--models", models, "--out-dir", results / "sap",
        "--bootstrap", "200", "--seed", "20260903")
    expected = ["human_human_agreement.csv", "physician_target_robustness.csv",
                "physician_target_pairwise_contrasts.csv", "gee_models.csv", "judge_target_provider_audit.csv",
                "automated_screen_operating_point.csv", "physician_subgroup_descriptives.csv",
                "target_output_status.csv", "physician_reference_missingness.csv",
                "physician_target_arm_rates.csv", "judge_measurement_status.csv",
                "target_output_completeness.csv", "same_provider_judge_summary.csv",
                "automated_calibration_cohort_target_estimates.csv"]
    missing = [f for f in expected if not (results / "sap" / f).exists() or (results / "sap" / f).stat().st_size < 10]
    check(not missing and not (results / "sap" / "gee_errors.json").exists(),
          f"all {len(expected)} SAP outputs written and both GEE models converged")
    groups = {r["analysis_group"] for r in jv}
    rob = read_csv(results / "sap" / "physician_target_robustness.csv")
    check({"primary_family=missing_information", "primary_family=conflicting_evidence"} <= groups
          and {r["primary_family"] for r in rob} == {"all", "missing_information", "conflicting_evidence"},
          "family-specific judge accuracy and family-specific target effects are reported (SAP 12)")
    arm = [r for r in read_csv(results / "sap" / "physician_target_arm_rates.csv")
           if r["endpoint"] == "recognizes_information_problem" and r["presentation"] == "perturbed"]
    check(len(arm) == 4 and all(int(r["binary_resolved"]) > 0 for r in arm),
          "endpoints with no paired contrast are still reported per arm")
    miss = {r["endpoint"]: r for r in read_csv(results / "sap" / "physician_reference_missingness.csv")}
    check(len(miss) == 6 and int(miss["recognizes_information_problem"]["independent_either_na"]) > 0
          and all(int(r["binary_resolved"]) + int(r["not_applicable"]) + int(r["cannot_determine"]) == 480
                  and int(r["unresolved_other"]) == 0 for r in miss.values())
          and all(int(r["consensus_used"]) > 0 for r in miss.values()),
          "every endpoint's 480 cells are resolved by consensus or agreement; NA survives the CSV round trip")
    check((results / "sap" / "physician_target_robustness_agreement_only.csv").stat().st_size > 10,
          "agreement-only sensitivity analysis is produced alongside the consensus-based estimates")
    check(all(r["data_provenance"] == "SIMULATED_REHEARSAL_NOT_RESULTS" for r in jv)
          and (results / "sap" / "SIMULATED_REHEARSAL_NOT_RESULTS.txt").exists(),
          "analysis outputs built on simulated calls label themselves as such")
    flow_args = ["--candidate-queue", hbp_queue, "--drafts-manifest", pub / "perturbation_drafts_manifest.csv",
                 *[x for path in primary_reviews for x in ("--review", path)],
                 "--casepack-manifest", casepack_manifest,
                 "--framework-exclusions", pub / "primary_casepack_manifest_framework_exclusions.csv"]
    run("analysis/construct_validity_flow.py", *flow_args, "--out", results / "construct_validity_flow.csv")
    flow = {r["stage"]: int(r["sources"]) for r in read_csv(results / "construct_validity_flow.csv")}
    check(flow["queued"] == 236 and flow["selected_in_casepack"] == 150
          and flow["eligible"] == flow["selected_in_casepack"] + flow["eligible_not_selected_quota_already_full"],
          f"construct-validity flow accounts for all 236 sources ({flow['physician_valid']} physician-valid, "
          f"{flow['reviewed_none_physician_valid']} rejected, {flow['no_applicable_draft']} with no applicable draft)")

    step("Phase 12  post-response construct reliability audit")
    audit_dir = vault / "review" / "construct_reliability"
    run("scripts/make_construct_reliability_audit.py", "--casepack", vault / "casepack" / "primary_hbp_150.private.jsonl",
        "--units", units_path, "--physician-reference", reference, "--out-dir", audit_dir)
    audit = [audit_dir / f"construct_reliability_{r}.csv" for r in "ABC"]
    original = {c["case_id"]: c["construct_reviewer"] for c in read_jsonl(vault / "casepack" / "primary_hbp_150.private.jsonl")}
    for path in audit:
        rows = read_csv(path)
        for r in rows:
            if r["reviewer_id"] == original[r["case_id"]]:
                sys.exit("FAIL: reliability audit sent a case back to its original construct reviewer")
            for q in CONSTRUCT_Q:
                r[q] = "yes"
            r["decision"] = "valid" if h("audit", r["case_id"]) % 10 else "reject"
        if rows:
            write_csv(path, rows)
    run("analysis/analyze_construct_reliability.py", *[x for p in audit if read_csv(p) for x in ("--review", p)],
        "--out", results / "construct_reliability.csv")
    check(int(read_csv(results / "construct_reliability.csv")[0]["n"]) == 30, "30 cases re-reviewed by a second physician")

    step("Phase 13  external 50-source cohort, kept apart from the primary study")
    ext = vault / "external"
    rp_drafts_name = "real_pocqi_perturbations.private.jsonl"
    run("scripts/draft_perturbations.py", "--sources", vault / "sources" / "real_pocqi_candidates.private.jsonl",
        "--vault", vault, "--models", models, "--out-name", rp_drafts_name,
        "--public-manifest", pub / "real_pocqi_perturbation_drafts_manifest.csv")
    check(read_jsonl(drafts) == d_rows, "external drafting left the primary drafts untouched")
    rp_manifest = pub / "real_pocqi_casepack_manifest.csv"
    _ = construct_and_finalize(vault, pub, vault / "drafts" / rp_drafts_name, "finalize_real_pocqi_casepack.py",
                           rp_queue, rp_manifest, "external", fallback_expected=False)
    ext_pack = vault / "casepack" / "external_real_pocqi_50.private.jsonl"
    run("scripts/run_targets.py", "--casepack", ext_pack, "--models", models, "--vault", ext,
        "--public-manifest", pub / "real_pocqi_target_response_manifest.csv", "--expected-cases", "50", *locked)
    run("scripts/select_physician_calibration.py", "--responses", ext / "responses" / "target_responses.private.jsonl",
        "--casepack", ext_pack, "--vault", ext, "--public-manifest", pub / "real_pocqi_physician_selection.csv",
        "--all-cases")
    ext_reference = review_responses(ext, "external")
    run("analysis/full_sap_analysis.py", "--physician-reference", ext_reference,
        "--target-responses", ext / "responses" / "target_responses.private.jsonl", "--models", models,
        "--out-dir", results / "sap_external", "--bootstrap", "200", "--seed", "20260903")
    check((results / "sap_external" / "physician_target_robustness.csv").stat().st_size > 10
          and not (results / "sap_external" / "judge_target_provider_audit.csv").exists(),
          "external cohort analysed physician-only, with no automated-judge output")
    check(len(read_csv(ext_reference)) == 400, "50 x 2 x 4 = 400 external cells, all physician-anchored")
    check(len(read_jsonl(responses_path)) == 480, "external run did not touch the 480 primary responses")

    step("Integrity  nothing private reached a public file; rehearsal artifacts cannot pass as study data")
    leaked = [str(p.relative_to(work)) for d in (pub, results) for p in d.rglob("*")
              if p.is_file() and SENTINEL.encode() in p.read_bytes()]
    check(not leaked, f"no case, rubric, reference-answer or response text in {sum(1 for _ in pub.rglob('*'))} public files")
    private_named = [p.name for p in vault.rglob("*") if p.is_file() and SENTINEL.encode() in p.read_bytes()
                     and ".private." not in p.name and "review" not in p.parts]
    check(not private_named, "every vault file holding case text carries the .private. marker git ignores")
    run("scripts/preflight.py", "--phase", "analysis", "--vault", vault, *[a for a in pre if a != "--rehearsal"],
        env={k: v for k, v in ENV.items() if k != "CAEVAL_STUDY_SIMULATED_TRANSPORT"},
        expect_fail="rehearsal artifacts found")
    (results / "REHEARSAL_NOT_STUDY_RESULTS.txt").write_text(
        "Synthetic sources, simulated providers, rule-based reviewers. Not findings.\n", encoding="utf-8")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--keep", type=Path, help="Write artifacts here (must not exist) and keep them")
    p.add_argument("--quick", action="store_true", help="Unit tests and precision smoke only")
    p.add_argument("--skip-unit-tests", action="store_true")
    args = p.parse_args()

    if not args.skip_unit_tests:
        quick()
    if args.quick:
        print("\nPASS (quick): unit tests and precision smoke. The end-to-end rehearsal was not run.")
        return
    if args.keep:
        if args.keep.exists():
            sys.exit(f"{args.keep} already exists")
        if ROOT in args.keep.resolve().parents:
            sys.exit("--keep must be outside the repository")
        args.keep.mkdir(parents=True)
        full(args.keep.resolve())
        print(f"\nArtifacts kept in {args.keep}")
    else:
        work = Path(tempfile.mkdtemp(prefix="caeval_rehearsal_"))
        try:
            full(work)
        finally:
            shutil.rmtree(work, ignore_errors=True)
    print("\nPASS: every runbook phase ran end to end at full study size with no network or API call.")
    print("This shows the machinery works. It is not evidence about any model, judge or clinical question.")


if __name__ == "__main__":
    main()
