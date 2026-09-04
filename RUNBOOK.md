# End-to-end runbook

This is the operational source of truth for the preregistered study. Follow phases in order. Raw benchmark text, transformed cases, model responses, and physician packets live only in a private study vault outside this repository.

The study validates the scoped Clinical-AI-Eval framework described in `protocol/FRAMEWORK_VALIDATION_SCOPE.md`.

## Phase 0 — install, rehearse, governance, reviewers, secrets

Use Python 3.11.

~~~bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[test]"
python scripts/rehearse_study.py
~~~

Define the private vault:

~~~bash
export STUDY_VAULT=/secure/path/clinical-ai-eval-physician-validation-v1
mkdir -p "$STUDY_VAULT"
~~~

Store provider keys outside Git:

~~~bash
export MEDROBUST_KEYS_PATH=/secure/path/API_KEYS.local.md
~~~

Before physician data collection:

- document the applicable local ethics/research-governance determination;
- freeze physician identities A, B, and C;
- document reviewer participation/consent, compensation, conflicts and data retention.

Roles are cross-fitted by source case; no physician is globally “the construct doctor” or “the response doctor.”

## Phase 1 — reconstruct pinned source queues

~~~bash
python scripts/select_cases.py --vault "$STUDY_VAULT"
~~~

Expected:

- exactly 236 HealthBench Professional consult candidates in `data/healthbench_professional_candidate_queue.csv`;
- a deterministic Real-POCQi candidate reservoir in `data/real_pocqi_candidate_queue.csv`;
- raw source records only below `$STUDY_VAULT/sources/`.

Both sources are revision/file-hash pinned. Any digest or expected-count mismatch stops the run.

## Phase 2 — perturbation-author technical dry-run

The authoring model is construction tooling, not clinical ground truth.

While `authoring_frozen: false`, only a small dry-run is allowed:

~~~bash
python scripts/draft_perturbations.py \
  --sources "$STUDY_VAULT/sources/healthbench_professional_candidates.private.jsonl" \
  --vault "$STUDY_VAULT" \
  --models configs/model_panel.yaml \
  --allow-unfrozen-author \
  --limit 5
~~~

Inspect those drafts only for technical/schema/task-drift failures. Delete dry-run outputs before the full authoring run.

Then set:

~~~yaml
authoring_frozen: true
~~~

Commit the authoring config/prompt before generating the full reservoir.

~~~bash
python scripts/preflight.py --phase authoring
~~~

## Phase 3 — full primary perturbation drafting

~~~bash
python scripts/draft_perturbations.py \
  --sources "$STUDY_VAULT/sources/healthbench_professional_candidates.private.jsonl" \
  --vault "$STUDY_VAULT" \
  --models configs/model_panel.yaml
~~~

Drafts remain scientifically invalid until physician construct review.

## Phase 4 — cross-fitted construct validation and 150-case casepack

Generate the first construct-review wave:

~~~bash
python scripts/make_construct_packets.py \
  --drafts "$STUDY_VAULT/drafts/perturbations.private.jsonl" \
  --out-dir "$STUDY_VAULT/review/construct" \
  --mode first
~~~

Each source goes to one deterministic construct reviewer. The other two physicians must not see that source pair before response review.

After A/B/C return their assigned files:

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

If finalization reports `NEEDS_FALLBACK_REVIEW`, expose only deterministic unreviewed alternatives:

~~~bash
python scripts/make_construct_packets.py \
  --drafts "$STUDY_VAULT/drafts/perturbations.private.jsonl" \
  --out-dir "$STUDY_VAULT/review/construct/fallback1" \
  --mode fallback \
  --prior-review "$STUDY_VAULT/review/construct/construct_review_A.csv" \
  --prior-review "$STUDY_VAULT/review/construct/construct_review_B.csv" \
  --prior-review "$STUDY_VAULT/review/construct/construct_review_C.csv"
~~~

Pass completed fallback files as additional `--review` arguments to finalization.

A material physician edit creates a new immutable version:

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

The new version requires fresh review.

Expected primary construct-valid pack: exactly 150 sources with HBP quotas 53/38/59 and at least 30 sources in each perturbation family.

## Phase 5 — freeze the 60-source response-validation cohort BEFORE target calls

The 150-source pack validates construct generation and source breadth. The physician-powered criterion/model-response analysis uses a prespecified 60-source subset.

~~~bash
python scripts/select_response_validation_cases.py \
  --casepack "$STUDY_VAULT/casepack/primary_hbp_150.private.jsonl" \
  --vault "$STUDY_VAULT" \
  --public-manifest data/response_validation_case_selection.csv
~~~

Expected:

- 60 unique sources;
- 30 missing-information;
- 30 conflicting-evidence;
- private target casepack at `$STUDY_VAULT/casepack/response_validation_60.private.jsonl`.

This happens before any target response exists.

## Phase 6 — live endpoint smoke tests, environment capture and full study lock

Using non-study prompts, technically verify every configured author/target/judge endpoint and credential. Confirm that provider-resolved model IDs, reasoning settings, HTTP status and request hashes are populated.

Run the design simulation:

~~~bash
python analysis/precision_simulation.py --out results/precision_simulation.csv
~~~

Capture the exact execution environment:

~~~bash
python scripts/capture_environment.py
~~~

This creates `data/environment_lock.txt` and `data/environment_metadata.json`.

When the live IDs/settings are confirmed, set:

~~~yaml
frozen: true
~~~

Commit the frozen protocol/config/prompts, 150-case public manifest, 60-case response-selection manifest, environment lock and analysis code.

Run target preflight:

~~~bash
python scripts/preflight.py --phase targets
~~~

Create the cryptographic study lock using the exact 40-character commit containing those frozen materials:

~~~bash
python scripts/freeze_study.py \
  --git-commit FULL_40_CHARACTER_STUDY_COMMIT
~~~

Commit `data/study_lock.json` **before the first primary target call**.

Any change afterward to a locked artifact is a protocol deviation.

## Phase 7 — run four targets on the 60-source cohort

~~~bash
python scripts/run_targets.py \
  --casepack "$STUDY_VAULT/casepack/response_validation_60.private.jsonl" \
  --models configs/model_panel.yaml \
  --vault "$STUDY_VAULT" \
  --public-manifest data/target_response_manifest.csv
~~~

Expected:

60 sources × 2 presentations × 4 targets = **480 target response cells**.

If `transport_failure` or `provider_failure` remains, fix infrastructure and rerun with `--resume`. Do not freeze physician packets until those infrastructure failures are resolved.

A successful API response with no usable text is `model_output_failure` and remains a separate product failure endpoint.

## Phase 8 — create the 480 cross-fitted physician response cells

~~~bash
python scripts/select_physician_calibration.py \
  --responses "$STUDY_VAULT/responses/target_responses.private.jsonl" \
  --casepack "$STUDY_VAULT/casepack/response_validation_60.private.jsonl" \
  --vault "$STUDY_VAULT" \
  --public-manifest data/physician_calibration_selection.csv
~~~

Because the target casepack already contains the frozen 30/30 cohort, all 60 sources are selected.

Expected:

- 480 unique response cells;
- two blinded response reviewers per cell;
- the source's construct reviewer excluded from both response reviewers;
- 960 independent physician ratings total.

Create reviewer packets:

~~~bash
python scripts/make_response_packets.py \
  --units "$STUDY_VAULT/review/physician_calibration_units.private.jsonl" \
  --out-dir "$STUDY_VAULT/review/responses"
~~~

A/B/C complete only their assigned packets and do not discuss cells before independent submissions are locked.

## Phase 9 — run the one automated evaluator on the SAME 480 cells

The confirmatory automated layer is **Grok 4.6 only**. It is being validated, not treated as ground truth.

~~~bash
python scripts/preflight.py --phase judges
~~~

~~~bash
python scripts/run_judges.py \
  --units "$STUDY_VAULT/review/physician_calibration_units.private.jsonl" \
  --models configs/model_panel.yaml \
  --vault "$STUDY_VAULT" \
  --public-manifest data/judge_manifest.csv
~~~

Expected: exactly 480 Grok-4.6 evaluations.

Judge API/format failures remain explicit missing measurements and are never coerced to 0.

No other proprietary judge is part of the confirmatory study. An open-weight clinical judge may be added only if it satisfied the prespecified public/version-pinnable rule before study lock.

## Phase 10 — lock physician reference and resolve only disagreements/indeterminacy

After all three independent physician packet files are locked:

~~~bash
python scripts/response_adjudication.py prepare \
  --units "$STUDY_VAULT/review/physician_calibration_units.private.jsonl" \
  --review "$STUDY_VAULT/review/responses/response_review_A.csv" \
  --review "$STUDY_VAULT/review/responses/response_review_B.csv" \
  --review "$STUDY_VAULT/review/responses/response_review_C.csv" \
  --out "$STUDY_VAULT/review/responses/response_consensus.csv"
~~~

Only cells where the two assigned response reviewers disagree or use `CANNOT_DETERMINE` appear in the consensus file. The same two reviewers resolve those cells after their independent ratings are locked. The construct reviewer does not participate.

Finalize:

~~~bash
python scripts/response_adjudication.py finalize \
  --units "$STUDY_VAULT/review/physician_calibration_units.private.jsonl" \
  --review "$STUDY_VAULT/review/responses/response_review_A.csv" \
  --review "$STYDY_VAULT/review/responses/response_review_B.csv" \
  --review "$STUDY_VAULT/review/responses/response_review_C.csv" \
  --consensus "$STUDY_VAULT/review/responses/response_consensus.csv" \
  --out "$STUDY_VAULT/review/physician_reference.private.csv"
~~~

**Before running:** correct the environment-variable spelling in every command if manually copied; the canonical variable is `STUDY_VAULT`.

Consensus may remain `CANNOT_DETERMINE`. Such cells are reported and excluded from binary operating-characteristic denominators.

## Phase 11 — preregistered analyses

~~~bash
python scripts/preflight.py --phase analysis --vault "$STUDY_VAULT"
~~~

Primary automated-layer validation:

~~~bash
python analysis/analyze_judge_validation.py \
  --physician-reference "$STUDY_VAULT/review/physician_reference.private.csv" \
  --judge-scores "$STUDY_VAULT/judges/judge_scores.private.jsonl" \
  --models configs/model_panel.yaml \
  --out results/judge_validation.csv \
  --bootstrap 10000 \
  --seed 20260903
~~~

Full SAP:

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

Primary automated-layer outputs include sensitivity, specificity, PPV/NPV, balanced accuracy, agreement, kappa, clustered CIs, framework-threshold comparison, and Grok-on-Grok versus Grok-on-other-provider performance.

Target-model comparisons remain physician-anchored.

## Phase 12 — post-response construct reliability audit

Only after the response reference is frozen:

~~~bash
python scripts/make_construct_reliability_audit.py \
  --casepack "$STUDY_VAULT/casepack/primary_hbp_150.private.jsonl" \
  --units "$STUDY_VAULT/review/physician_calibration_units.private.jsonl" \
  --physician-reference "$STUDY_VAULT/review/physician_reference.private.csv" \
  --out-dir "$STUDY_VAULT/review/construct_reliability"
~~~

Analyze:

~~~bash
python analysis/analyze_construct_reliability.py \
  --review "$STUDY_VAULT/review/construct_reliability/construct_reliability_A.csv" \
  --review "$STUDY_VAULT/review/construct_reliability/construct_reliability_B.csv" \
  --review "$STUDY_VAULT/review/construct_reliability/construct_reliability_C.csv" \
  --out results/construct_reliability.csv
~~~

This audit occurs after response blinding can no longer be contaminated.

## Phase 13 — Real-POCQi external-dataset replication

Use the already pinned Real-POCQi candidate queue and the same frozen definitions. Freeze the external 50-case pack **before inspecting primary outcome results**.

Draft, cross-fit construct-review and finalize:

~~~bash
python scripts/finalize_real_pocqi_casepack.py \
  --drafts "$STUDY_VAULT/drafts/real_pocqi_perturbations.private.jsonl" \
  --candidate-queue data/real_pocqi_candidate_queue.csv \
  --review REVIEW_FILE_1 --review REVIEW_FILE_2 --review REVIEW_FILE_3 \
  --vault "$STUDY_VAULT" \
  --public-out data/real_pocqi_casepack_manifest.csv
~~~

Run the same four frozen target models on all 50 external sources:

50 × 2 × 4 = **400 target response cells**.

Create physician review units with:

~~~bash
python scripts/select_physician_calibration.py \
  --responses "$STUDY_VAULT/responses/real_pocqi_target_responses.private.jsonl" \
  --casepack "$STUDY_VAULT/casepack/external_real_pocqi_50.private.jsonl" \
  --vault "$STUDY_VAULT/external" \
  --public-manifest data/real_pocqi_physician_selection.csv \
  --all-cases
~~~

The external replication is physician-anchored and analyzed separately. Grok automated scoring is **not required** for the external cohort; omitting it saves cost and does not alter the primary automated-layer validation.

Do not tune prompts, thresholds, model configuration or endpoint definitions from primary results.

## Non-negotiable checks

- no raw HealthBench Professional text or physician packets in Git;
- no API keys in Git;
- 150-case construct-valid casepack frozen before response-cohort selection;
- 60-source 30/30 response-validation cohort frozen before target calls;
- no primary target calls before full study lock;
- no physician packet freeze while target infrastructure failures remain;
- exactly 480 primary target cells;
- exactly 480 primary Grok judge cells;
- construct reviewer never response-rates the same source;
- exactly two independent blinded physician ratings per response cell;
- consensus only after independent submissions are locked;
- `CANNOT_DETERMINE` is never coerced negative;
- judge failures are never coerced negative;
- safety and helpfulness remain separate;
- Grok judging Grok is reported separately from Grok judging other providers;
- exact environment/model/provider provenance is locked and reported;
- deviations are timestamped and disclosed.

See `REPRODUCIBILITY.md` for clean-room reproduction instructions.
