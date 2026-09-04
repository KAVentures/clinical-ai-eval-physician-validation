# Source and case-selection strategy

Version: draft v0.2, 2026-09-04

## Scientific principle

Cases are selected for **construct suitability before any target-model output is observed**. A source case is useful here only if it contains a clinically meaningful decision and supports a controlled perturbation that changes the evidentiary state without changing the patient, clinical task, or decision timepoint.

No source case may enter or leave a confirmatory cohort because a target model performed well or badly on it.

## Primary source: HealthBench Professional

Dataset: `openai/healthbench-professional`.

The exact source revision and file SHA-256 are hard-pinned in `scripts/select_cases.py`. Retrieval fails closed if the file digest or expected counts change.

### Eligible source pool

Only `use_case == consult` examples are eligible for the primary cohort.

The released care-consult pool used here contains 236 examples in three source strata:

| source stratum | reservoir | final validated quota |
|---|---:|---:|
| good_faith / typical | 84 | 53 |
| good_faith / difficult | 59 | 38 |
| red_teaming / difficult | 93 | 59 |
| total | 236 | 150 |

Within each stratum, every source ID receives a deterministic SHA-256 priority based on the frozen study seed. Review proceeds in that order until the validated quota is filled.

A rejected source can only be replaced by the next prespecified source in the same stratum before target-model execution.

### Stable source rendering

HealthBench Professional conversations are converted to one deterministic role-labelled text rendering for this study.

The same rendering convention is used for original and perturbed presentations.

This is a controlled study representation and **not** an official HealthBench Professional scoring protocol. Native conversational delivery is not claimed.

### Clinical suitability

A source must support all of the following:

1. a concrete clinical decision, assessment, disposition, treatment, dose, or recommendation;
2. an identifiable decision timepoint;
3. at least one fact or evidence relationship whose status could change what can safely be concluded;
4. a transformation that leaves the patient and clinical task materially unchanged;
5. at least one safe response strategy after perturbation.

Examples that are essentially literature searches, prevalence questions, mechanisms, trial identification, or general education are excluded even if metadata labels them as consultation.

### Public-data rule

HealthBench Professional examples, physician responses, rubrics, source-derived transformed text, and target responses are not copied into the public repository.

Public artifacts may contain source IDs, source metadata, source-file revision/digest, content hashes, validation status, model/judge provenance, de-identified labels where release is appropriate, and aggregate results.

## Secondary source: Real-POCQi

Dataset: `jjfenglab/Real-POCQi`.

The study uses Real-POCQi only as an external replication cohort.

The exact `questions.parquet` revision and SHA-256 are pinned in `scripts/select_cases.py`; the source currently contains 620 point-of-care physician questions.

### Candidate filter

Many Real-POCQi questions are factual/research questions rather than patient-specific clinical decisions.

The source selector therefore applies a permissive prespecified lexical filter requiring both:

- patient/context signals; and
- decision/management signals.

Obvious prevalence, trial-identification, and research-style openings are excluded.

This filter is only a reproducible candidate screen. It cannot confer clinical eligibility.

The first 50 construct-valid sources in deterministic candidate order form the external replication cohort.

## Perturbation drafting

For each candidate source, the drafting stage may propose:

- one `missing_information` variant;
- one `conflicting_evidence` variant.

The authoring model is a case-construction tool only. Its output has **zero evidentiary status**.

The authoring model, prompt, provider interface, and reasoning setting are technically dry-run and then frozen before the full draft reservoir is generated.

The authoring model is not a primary automated judge. Provider-family overlap with a target model is declared rather than hidden.

## Missing-information drafting rules

A permissible draft removes only the minimum clinically load-bearing fact or compact fact group needed to change what can safely be concluded.

Preferred removable domains include:

- renal/hepatic function relevant to treatment;
- pregnancy/reproductive status;
- allergy/intolerance;
- anticoagulation or interacting medication;
- key vital sign or physiological instability;
- load-bearing examination finding;
- imaging result;
- diagnostic laboratory result/trend;
- symptom timing/duration;
- red-flag history feature.

Do not remove background facts merely to make the case shorter. Do not create obviously broken prose. Do not insert experiment markers such as `[removed]`.

## Conflicting-evidence drafting rules

A permissible draft creates or preserves two clinically plausible, decision-relevant signals that cannot safely be reconciled by silently choosing one.

Preferred conflict classes include:

- current versus prior laboratory trend;
- symptoms/examination versus imaging;
- medication/allergy/history versus proposed treatment;
- discordant diagnostic tests;
- clinically reassuring context versus a high-risk objective measurement;
- competing records describing the same decision-relevant fact.

The conflict may not change patient identity, action semantics, clinical task, or decision timepoint.

## Cross-fitted construct validation

The study uses three physicians A/B/C.

For each source, a deterministic hash assigns **one construct reviewer**. The two physicians who were not shown that source's original/perturbed pair are reserved as the blinded response reviewers for that source.

The construct reviewer evaluates six criteria defined in `PROTOCOL.md`:

1. original coherence;
2. perturbed coherence;
3. same patient/task/timepoint;
4. load-bearingness;
5. intended construct achieved;
6. safe response definable.

All six must be YES and the decision must be `valid`.

This one-reviewer construct design is a deliberate trade-off that preserves two independent response reviewers with only three physicians.

A separate 30-case second-physician construct reliability audit occurs **after primary response labels are locked**, so it cannot contaminate response blinding.

## Revision and fallback

A material change creates a new immutable perturbation version using `scripts/revise_perturbation.py`. Prior labels do not transfer to the new version.

If a first-choice perturbation is rejected, `scripts/make_construct_packets.py --mode fallback` exposes only a deterministic previously unreviewed alternative for unresolved sources.

Fallback review occurs before target outputs exist.

## Primary perturbation assignment

A source may have zero, one, or two construct-valid perturbation families.

- zero valid families -> source excluded;
- one valid family -> that family is primary;
- two valid families -> deterministic assignment balances the final cohort toward 75/75 while preserving source-stratum quotas.

The final primary cohort must contain at least 30 sources from each family so the prespecified 30/30 physician calibration frame is feasible.

No family assignment changes after target-model execution begins.

## Dataset lineage

The frozen public manifests and private casepack bind:

- source dataset and immutable revision;
- source file/corpus digest;
- source ID;
- source content digest;
- perturbation family/version/content digest;
- construct reviewer assignment and decision;
- primary perturbation assignment;
- deterministic selection priority;
- exclusion/rejection state where applicable.

The public manifest contains no protected benchmark text.
