# Clinical AI Eval — Physician Validation Study v1

**Status:** pre-results, pre-lock. The protocol and execution package are ready for technical dry-runs, but the primary experiment must not begin until the authoring/model locks, local ethics/governance determination, and three physician identities are frozen.

This repository is the canonical study repository. It pins KAVentures/clinical-ai-eval as the measurement engine while owning the study-specific provider runtime, provenance, source manifests, physician workflow, statistical plan, and manuscript.

This study is separate from clinical-branch-intersection-security (BISV).

## Overarching study question

> **Does Clinical-AI-Eval provide a clinically valid, reproducible, and actionable framework for stress-testing clinical AI under missing and conflicting evidence?**

The repository being validated is `KAVentures/clinical-ai-eval`. This study treats its major measurement layers as testable components rather than assuming the framework is useful because it runs.

The validation hierarchy is:

1. **Construct validity** — does Clinical-AI-Eval's first-class preconstructed-variant path correctly carry physician-reviewed missing-information and conflicting-evidence manifestations into the framework's manifest/validity/scoring pipeline?
2. **Criterion validity** — does its automated judge layer detect the prespecified unsafe-overconfidence failure relative to blinded physicians?
3. **Reliability / judge robustness** — how much do judgments vary across judge providers, cueing conditions, and provider-family relationships?
4. **Actionability** — can disagreement or unanimity be used to identify which cases may be safely automated versus deferred to physicians?
5. **External robustness** — do the framework's measurements reproduce on a separately frozen Real-POCQi cohort?

Target-model comparisons are deliberately secondary: GPT/Claude/Gemini/Grok are **subjects used to exercise the framework**, not the primary scientific object.

A successful study does not mean every automated score is correct. It means the framework's valid scope, measured error profile, and human-review boundary are empirically characterized.

## Cohorts

### Primary — HealthBench Professional

- source: openai/healthbench-professional
- pinned revision and file SHA-256 are enforced by scripts/select_cases.py
- 525 released examples
- 236 eligible care-consult source examples
- 150 physician-validated final cases:
  - good-faith / typical: 53
  - good-faith / difficult: 38
  - red-teaming / difficult: 59

HealthBench Professional examples are not reproduced publicly. Raw source text, reference responses, rubrics, transformed cases, target responses, and physician packets remain outside Git in the private study vault.

The study converts each multi-turn source conversation to one stable role-labelled text rendering and applies the same rendering to original and perturbed arms. This is intentionally **not** claimed to be an official HealthBench Professional score.

### External replication — Real-POCQi

- source: jjfenglab/Real-POCQi
- CC BY 4.0
- 620 real point-of-care physician questions
- pinned revision and questions.parquet SHA-256
- prespecified 50-case physician-valid external cohort
- analyzed separately from the HealthBench-derived primary cohort

## Relationship to Clinical-AI-Eval

This repository is a prospective validation study of the pinned Clinical-AI-Eval engine commit. Final physician-approved manifestations are imported through `YamlFamily.ingest_preconstructed_variant()`; the study does not silently replace the framework's manifest or structural-validity logic. Study-specific code adds the physician reference standard, immutable source/case selection, strict provider provenance, and preregistered statistics needed to test whether the reusable framework's outputs are scientifically trustworthy.

The framework is considered useful only to the extent supported by prespecified evidence in the five validation dimensions above. A negative result—such as poor physician alignment or very low safe automation coverage—is an informative validation result and would limit how Clinical-AI-Eval should be used.

## Three-physician cross-fitted design

The study uses physicians A, B, and C.

For each source case, exactly **one** physician is deterministically assigned as the construct reviewer. The other **two**, who never see that source's original/perturbed pair during construction, independently rate all response cells for that case.

This gives genuine response-level blinding with only three physicians:

1. one physician validates the perturbation construct;
2. the other two independently rate AI responses;
3. if those two disagree or use CANNOT_DETERMINE, they resolve the cell only after both independent submissions are locked;
4. the original construct reviewer never adjudicates that case's response;
5. after all primary response labels are locked, a deterministic 30-case post-response construct audit estimates second-physician confirmation of the perturbation construct without contaminating the primary response labels.

The shared primary physician calibration frame contains 60 source cases — 30 missing-information and 30 conflicting-evidence — across four targets and both presentations:

60 × 4 × 2 = **480 unique response cells**

Each cell has two independent blinded physician ratings:

480 × 2 = **960 physician ratings**

## Study workflow

1. Retrieve the two pinned source datasets and create ID/hash-only public queues.
2. Technical dry-run the perturbation author on a handful of cases.
3. Freeze authoring model + prompt before full perturbation drafting.
4. Generate drafts; drafts have zero validity until physician review.
5. Cross-fit construct review across A/B/C; use deterministic fallback waves if quotas are not filled.
6. Finalize the 150-case primary pack.
7. Deterministically freeze the 60-source response-validation cohort (30 missing-information, 30 conflict) before any target call.
8. Dry-run every target and Grok-4.6 judge endpoint.
9. Capture the exact Python/package environment.
10. Freeze model IDs, inference settings, protocol, prompts, engine pin, 150-case construct manifest, 60-case response cohort and analysis code; create the cryptographic study lock.
11. Run 480 target cells (60 sources × 2 presentations × 4 targets); resolve transport/provider failures before physician packets are frozen.
12. Create the 480 cross-fitted physician response-review cells.
13. Run Grok 4.6 on exactly those same 480 physician-reference cells.
14. Complete independent cross-fitted physician response review and locked consensus.
15. Run the primary framework-validation and prespecified SAP analyses.
16. Perform the post-response construct reliability audit.
17. Repeat the scoped framework validation on 50 Real-POCQi cases as external replication.

## Failure semantics

Infrastructure errors are not model errors:

- transport_failure — timeout/network failure after bounded retries;
- provider_failure — API/HTTP failure after bounded retries;
- model_output_failure — successful API response but no usable target text;
- judge parse/API failures — explicit missing judge measurements, never converted to negative labels.

Primary physician calibration cannot be frozen while transport/provider target failures remain.

CANNOT_DETERMINE is a real physician-reference state. It is never coerced to safe/negative and is excluded from binary operating-characteristic denominators with its count reported.

## Reproducibility

Every provider call records, without secrets:

- configured model;
- provider-resolved model/version where returned;
- endpoint;
- exact reasoning effort;
- max output tokens;
- request SHA-256;
- attempt count;
- HTTP status;
- timestamps;
- usage metadata.

The study lock binds the study commit, engine commit, protocol, prompts, model configuration, source manifests, 150-case construct-valid manifest, frozen 60-case response-validation cohort, and exact Python/package environment.

## Installation

~~~bash
python -m pip install -e ".[test]"
pytest -q
~~~

Store API keys only in environment variables or a key file outside the repository, for example:

~~~bash
export MEDROBUST_KEYS_PATH=/secure/path/API_KEYS.local.md
~~~

API_KEYS.local.md and .env files are ignored and CI rejects tracked secret/private artifact names.

## Start safely

Dataset selection can be run immediately:

~~~bash
export STUDY_VAULT=/secure/path/clinical-ai-eval-physician-validation-v1
python scripts/select_cases.py --vault "$STUDY_VAULT"
~~~

Do not run the irreversible primary target experiment until RUNBOOK.md phases 0–5 are complete and scripts/freeze_study.py has produced the locked manifest.

## Core documents

- protocol/PROTOCOL.md
- protocol/STATISTICAL_ANALYSIS_PLAN.md
- protocol/SAMPLE_SIZE_JUSTIFICATION.md
- protocol/SOURCE_STRATEGY.md
- protocol/ETHICS_AND_GOVERNANCE.md
- review/REVIEW_INSTRUCTIONS.md
- RUNBOOK.md
- REPRODUCIBILITY.md
- protocol/FRAMEWORK_VALIDATION_SCOPE.md
- manuscript/MANUSCRIPT_SKELETON.md


### Important manifestation boundary

The study validates Clinical-AI-Eval's **preconstructed qualification-study path** for
`missing_information` and `conflicting_evidence`. It does not establish clinical
validity of the framework's generic deterministic helper functions such as
`remove_labs()` or generic `add_conflict()`; those are not the transforms used to
create the physician-reviewed study cases.
