# End-to-end runbook

This runbook is the operational source of truth for the preregistered study. Raw benchmark text, modified cases, target responses, and physician packets live only in a private study vault outside this repository.

## Phase 0 — install, governance, reviewers, secrets

Install:

~~~bash
python -m pip install -e ".[test]"
pytest -q
~~~

Define the private vault:

~~~bash
export STUDY_VAULT=/secure/path/clinical-ai-eval-physician-validation-v1
mkdir -p "$STUDY_VAULT"
~~~

Store keys outside Git:

~~~bash
export MEDROBUST_KEYS_PATH=/secure/path/API_KEYS.local.md
~~~

Before physician data collection, record the appropriate local ethics/research-governance determination described in protocol/ETHICS_AND_GOVERNANCE.md.

Freeze the identities A, B, and C before response unblinding. The cross-fitted role is assigned by source case, not permanently by physician.

## Phase 1 — pinned source queues

~~~bash
python scripts/select_cases.py --vault "$STUDY_VAULT"
~~~

Expected:

- exactly 236 HealthBench Professional consult candidates in data/healthbench_professional_candidate_queue.csv;
- a deterministic patient/decision Real-POCQi candidate reservoir in data/real_pocqi_candidate_queue.csv;
- raw source records only below $STUDY_VAULT/sources/.

Both source files are revision- and SHA-pinned. A mismatch stops execution.

## Phase 2 — authoring technical dry-run

The authoring model is construction tooling only. It is not ground truth and is not a primary judge.

While authoring_frozen is false, only a limited dry-run is permitted:

~~~bash
python scripts/draft_perturbations.py \
  --sources "$STUDY_VAULT/sources/healthbench_professional_candidates.private.jsonl" \
  --vault "$STUDY_VAULT" \
  --models configs/model_panel.yaml \
  --allow-unfrozen-author \
  --limit 5
~~~

Inspect the five outputs for schema adherence, minimal edits, and obvious task drift. Delete dry-run outputs before the full authoring run.

Then set:

~~~yaml
authoring_frozen: true
~~~

Commit the config and authoring prompt before generating the full reservoir.

Run author preflight:

~~~bash
python scripts/preflight.py --phase authoring
~~~

## Phase 3 — full perturbation drafting

~~~bash
python scripts/draft_perturbations.py \
  --sources "$STUDY_VAULT/sources/healthbench_professional_candidates.private.jsonl" \
  --vault "$STUDY_VAULT" \
  --models configs/model_panel.yaml
~~~

Drafts remain invalid until physician construct review.

## Phase 4 — cross-fitted construct review

Generate the first review wave:

~~~bash
python scripts/make_construct_packets.py \
  --drafts "$STUDY_VAULT/drafts/perturbations.private.jsonl" \
  --out-dir "$STUDY_VAULT/review/construct" \
  --mode first
~~~

Each source goes to exactly one prespecified construct reviewer A/B/C. The other two physicians must not see that source pair because they are reserved for blinded response review.

After completed review files are returned, attempt finalization:

~~~bash
python scripts/finalize_casepack.py \
  --drafts "$STUDY_VAULT/drafts/perturbations.private.jsonl" \
  --candidate-queue data/healthbench_professional_candidate_queue.csv \
  --review "$STUDY_VAULT/review/construct/construct_review_A.csv" \
  --review "$STUDY_VAULT/review/construct/construct_review_B.csv" \
  --review "$STUDY_VAULT/review/construct/construct_review_C.csv" \
  --vault "$STUDY_VAULT" \
  --public-out data/primary_casepack_manifest.csv
~~~

If the script reports NEEDS_FALLBACK_REVIEW, generate only unresolved alternate variants:

~~~bash
python scripts/make_construct_packets.py \
  --drafts "$STUDY_VAULT/drafts/perturbations.private.jsonl" \
  --out-dir "$STUDY_VAULT/review/construct/fallback1" \
  --mode fallback \
  --prior-review "$STUDY_VAULT/review/construct/construct_review_A.csv" \
  --prior-review "$STUDY_VAULT/review/construct/construct_review_B.csv" \
  --prior-review "$STUDY_VAULT/review/construct/construct_review_C.csv"
~~~

Add completed fallback files as additional --review arguments to finalization. Repeat deterministically if needed.

If a physician requests a material revision rather than rejection, create a new immutable perturbation version:

~~~bash
python scripts/revise_perturbation.py \
  --drafts "$STUDY_VAULT/drafts/perturbations.private.jsonl" \
  --source-id SOURCE_ID \
  --family missing_information \
  --modified-case-file /secure/path/revised_case.txt \
  --changed-evidence "..." \
  --safe-response-strategy "..." \
  --public-manifest data/perturbation_drafts_manifest.csv
~~~

The new version requires fresh construct review.

Expected final primary casepack: exactly 150 cases with source quotas 53/38/59 and at least 30 cases from each perturbation family.

## Phase 5 — target/judge endpoint dry-runs and full lock

Dry-run every configured provider/model using non-study prompts and confirm that resolved model IDs, endpoint, reasoning settings, HTTP status, and request hashes are populated.

Run the sample-size simulation and retain its output:

~~~bash
python analysis/precision_simulation.py --out results/precision_simulation.csv
~~~

When provider IDs/settings are confirmed, set:

~~~yaml
frozen: true
~~~

Commit the locked protocol/config/prompts/case manifest.

Run target preflight:

~~~bash
python scripts/preflight.py --phase targets
~~~

Create the study lock using the exact commit that contains the frozen materials:

~~~bash
python scripts/freeze_study.py \
  --git-commit FULL_40_CHARACTER_STUDY_COMMIT
~~~

Commit data/study_lock.json before any primary target call. Any later change to a locked artifact is a protocol deviation.

## Phase 6 — target execution

~~~bash
python scripts/run_targets.py \
  --casepack "$STUDY_VAULT/casepack/primary_hbp_150.private.jsonl" \
  --models configs/model_panel.yaml \
  --vault "$STUDY_VAULT" \
  --public-manifest data/target_response_manifest.csv
~~~

Expected: 150 × 2 × 4 = 1,200 response cells.

If transport_failure or provider_failure remains, correct the infrastructure problem and rerun with --resume. Do not proceed to physician calibration until those statuses are gone.

A successful API response containing no usable target text is model_output_failure and is retained as a separate target failure endpoint.

## Phase 7 — freeze physician calibration before judges

~~~bash
python scripts/select_physician_calibration.py \
  --responses "$STUDY_VAULT/responses/target_responses.private.jsonl" \
  --casepack "$STUDY_VAULT/casepack/primary_hbp_150.private.jsonl" \
  --vault "$STUDY_VAULT" \
  --public-manifest data/physician_calibration_selection.csv
~~~

Expected:

- 60 source cases: 30 missing-information + 30 conflict;
- 480 unique response cells;
- exactly two response reviewers per cell;
- construct reviewer excluded from both response reviewers.

Create reviewer packets:

~~~bash
python scripts/make_response_packets.py \
  --units "$STUDY_VAULT/review/physician_calibration_units.private.jsonl" \
  --out-dir "$STUDY_VAULT/review/responses"
~~~

Each physician gets only their assigned cells. Do not exchange packets.

## Phase 8 — automated judges

Run preflight:

~~~bash
python scripts/preflight.py --phase judges
~~~

Run primary blinded judges:

~~~bash
python scripts/run_judges.py \
  --responses "$STUDY_VAULT/responses/target_responses.private.jsonl" \
  --casepack "$STUDY_VAULT/casepack/primary_hbp_150.private.jsonl" \
  --models configs/model_panel.yaml \
  --vault "$STUDY_VAULT" \
  --public-manifest data/judge_manifest.csv
~~~

After primary outputs are frozen, run the prespecified secondary blinded/cued sensitivity conditions using --include-secondary.

Judge API/format failures remain explicit missing measurements. They are never coerced to 0.

## Phase 9 — independent physician response review and locked consensus

A/B/C independently complete only their assigned response_review_*.csv packet.

CANNOT_DETERMINE is allowed for the primary endpoint and is never equivalent to 0.

After all independent files are locked:

~~~bash
python scripts/response_adjudication.py prepare \
  --units "$STUDY_VAULT/review/physician_calibration_units.private.jsonl" \
  --review "$STUDY_VAULT/review/responses/response_review_A.csv" \
  --review "$STUDY_VAULT/review/responses/response_review_B.csv" \
  --review "$STUDY_VAULT/review/responses/response_review_C.csv" \
  --out "$STUDY_VAULT/review/responses/response_consensus.csv"
~~~

The generated consensus sheet contains only cells with disagreement or at least one CANNOT_DETERMINE. The two response reviewers for each cell resolve it together; the construct reviewer does not participate.

Finalize:

~~~bash
python scripts/response_adjudication.py finalize \
  --units "$STUDY_VAULT/review/physician_calibration_units.private.jsonl" \
  --review "$STUDY_VAULT/review/responses/response_review_A.csv" \
  --review "$STUDY_VAULT/review/responses/response_review_B.csv" \
  --review "$STUDY_VAULT/review/responses/response_review_C.csv" \
  --consensus "$STUDY_VAULT/review/responses/response_consensus.csv" \
  --out "$STUDY_VAULT/review/physician_reference.private.csv"
~~~

Consensus may remain CANNOT_DETERMINE. Those cells are reported and excluded from binary judge operating-characteristic denominators.

## Phase 10 — primary and full SAP analyses

~~~bash
python scripts/preflight.py --phase analysis --vault "$STUDY_VAULT"
~~~

Primary judge validation:

~~~bash
python analysis/analyze_judge_validation.py \
  --physician-reference "$STUDY_VAULT/review/physician_reference.private.csv" \
  --judge-scores "$STUDY_VAULT/judges/judge_scores.private.jsonl" \
  --models configs/model_panel.yaml \
  --out results/judge_validation.csv \
  --bootstrap 10000 \
  --seed 20260903
~~~

Full preregistered secondary analyses:

~~~bash
python analysis/full_sap_analysis.py \
  --physician-reference "$STUDY_VAULT/review/physician_reference.private.csv" \
  --judge-scores "$STUDY_VAULT/judges/judge_scores.private.jsonl" \
  --target-responses "$STUDY_VAULT/responses/target_responses.private.jsonl" \
  --models configs/model_panel.yaml \
  --out-dir results/sap \
  --bootstrap 10000 \
  --seed 20260903
~~~

## Phase 11 — post-response construct reliability audit

Only after the physician response reference is frozen:

~~~bash
python scripts/make_construct_reliability_audit.py \
  --casepack "$STUDY_VAULT/casepack/primary_hbp_150.private.jsonl" \
  --units "$STUDY_VAULT/review/physician_calibration_units.private.jsonl" \
  --physician-reference "$STUDY_VAULT/review/physician_reference.private.csv" \
  --out-dir "$STUDY_VAULT/review/construct_reliability"
~~~

After completion:

~~~bash
python analysis/analyze_construct_reliability.py \
  --review "$STUDY_VAULT/review/construct_reliability/construct_reliability_A.csv" \
  --review "$STUDY_VAULT/review/construct_reliability/construct_reliability_B.csv" \
  --review "$STUDY_VAULT/review/construct_reliability/construct_reliability_C.csv" \
  --out results/construct_reliability.csv
~~~

This audit estimates second-physician confirmation of the perturbation construct after response blinding can no longer be contaminated.

## Phase 12 — Real-POCQi external replication

Use the pinned private Real-POCQi candidate file as input to the same drafting and cross-fitted construct-review process.

Finalize:

~~~bash
python scripts/finalize_real_pocqi_casepack.py \
  --drafts "$STUDY_VAULT/drafts/real_pocqi_perturbations.private.jsonl" \
  --candidate-queue data/real_pocqi_candidate_queue.csv \
  --review REVIEW_FILES_REPEATED_AS_NEEDED \
  --vault "$STUDY_VAULT" \
  --public-out data/real_pocqi_casepack_manifest.csv
~~~

Run the same four frozen targets and judges without tuning from primary results.

For external physician response review, call select_physician_calibration.py with --all-cases. All 50 external source cases are reviewed:

50 × 2 × 4 = 400 unique response cells and 800 cross-fitted physician ratings.

Analyze the external cohort separately. Do not alter primary thresholds, prompts, panels, or endpoint definitions based on external results.

## Non-negotiable checks

- no raw HBP text or physician packets in Git;
- no API keys in Git;
- no target calls before construct-valid casepack and full study lock;
- no calibration selection with unresolved transport/provider target failures;
- calibration selection before automated judge results are inspected;
- target responses frozen before judges;
- no construct reviewer response-rates the same source case;
- exactly two independent blinded physician ratings per response cell;
- consensus only after independent submissions are locked;
- CANNOT_DETERMINE is never coerced negative;
- cued judges never enter the primary blinded quorum;
- judge failures never become negative labels;
- safety/helpfulness remain separate;
- every provider setting and model identifier is frozen and reported;
- deviations are timestamped and reported.
