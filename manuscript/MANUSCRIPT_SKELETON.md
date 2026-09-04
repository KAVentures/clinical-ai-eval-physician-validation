# Human-Anchored Validation of Automated Evaluation for Clinical AI Under Missing and Conflicting Evidence

**Status:** preregistration-era manuscript skeleton; no study results inserted.

## Abstract

### Background
Clinical AI evaluations increasingly use LLMs as automated judges, but evaluator choice can materially affect measured performance. Static, fully specified cases may also under-test a clinically important failure mode: over-committing when decision-relevant evidence is absent or internally contradictory.

### Objective
To measure the operating characteristics of blinded automated clinical-AI judges against a cross-fitted blinded physician reference and to characterize model behavior under controlled information degradation.

### Methods
Prospective paired perturbation study using 150 physician-validated HealthBench Professional-derived care-consult source cases. Each source has one locked primary perturbation: missing information or conflicting evidence. Four provider-diverse target models answer original and perturbed presentations. Three provider-diverse automated judges form the blinded primary judge panel. A shared 60-source physician calibration cohort spans all four targets and both presentations, yielding 480 unique response cells. For each source, one of three physicians performs construct validation and the other two—who have not seen that source's original/perturbed pair—independently rate its AI responses. Discordant or indeterminate primary labels are resolved only after both independent ratings are locked. External replication uses 50 construct-valid Real-POCQi sources.

### Results
[LOCKED PLACEHOLDER — populate only from reproducible analysis outputs.]

### Conclusions
[LOCKED PLACEHOLDER — distinguish evaluator validity from target-model performance and avoid deployment-safety claims.]

## Introduction

1. Clinical generative AI is increasingly evaluated using model-based graders and rubric-driven automated judges.
2. Automated judges are measurement instruments and can exhibit error, disagreement, provider effects, and cue sensitivity.
3. Static fully specified cases under-test responses to missing or contradictory decision-relevant evidence.
4. Controlled perturbations can isolate these robustness failures, but the evaluator itself must be calibrated against physicians.
5. This study therefore separates three questions:
   - does the perturbation construct remain clinically valid?
   - does the automated judge measure the specified failure accurately enough for its intended use?
   - how do target models behave under that perturbation?

## Methods

### Study design
Describe the prospective paired perturbation study and explicitly distinguish:

- primary measurement validation of the automated judge;
- secondary target-model robustness comparisons;
- post-response construct-reliability audit;
- external Real-POCQi replication.

### Source datasets

#### HealthBench Professional-derived primary cohort
Report:

- source revision and file SHA-256;
- MIT license;
- 525 released examples;
- 236 care-consult source reservoir;
- deterministic within-stratum ordering;
- final quotas 53/38/59;
- source-maintainer request not to reproduce examples online.

Clarify that the study uses HealthBench Professional as source material with a stable role-labelled rendering and is **not** an official HealthBench Professional score.

#### Real-POCQi external cohort
Report:

- pinned revision and questions.parquet SHA-256;
- CC BY 4.0 attribution;
- 620-question source set;
- prespecified patient/decision lexical candidate filter;
- physician construct validation;
- first 50 construct-valid sources in deterministic order.

Keep all external estimates separate from the HealthBench-derived primary analysis.

### Perturbation construction
Describe:

- authoring model as construction tooling rather than ground truth;
- authoring-model/prompt lock before full drafting;
- missing-information and conflicting-evidence definitions;
- minimum-edit principle;
- immutable perturbation versioning;
- deterministic fallback review before target execution.

### Three-physician cross-fitted design
For each source case:

1. a deterministic hash assigns one physician as construct reviewer;
2. the other two physicians remain unexposed to the source pair during construction;
3. those two physicians independently rate all response cells for that source;
4. the construct reviewer never response-rates or adjudicates that source;
5. response consensus occurs only after both independent labels are locked.

State that this design preserves two genuinely blinded physician response ratings per cell with a three-physician team.

### Physician construct validation
The construct reviewer evaluates six criteria:

- original coherence;
- perturbed coherence;
- same patient/task/timepoint;
- changed evidence is load-bearing;
- intended construct achieved;
- at least one safe response is definable.

All six must be YES with a valid decision.

Acknowledge that one initial construct reviewer per source is a trade-off. Describe the prespecified post-response 30-case second-physician construct-reliability audit.

### Target models
Insert exact frozen:

- provider;
- API model identifier;
- provider-resolved model/version where returned;
- reasoning setting;
- endpoint;
- maximum output tokens;
- neutral target prompt hash;
- tool-disabled policy;
- execution date;
- provider data-use/retention configuration.

Distinguish:

- transport_failure;
- provider_failure;
- model_output_failure;
- successful model response.

Transport/provider failures must be resolved before the physician calibration frame is frozen.

### Automated judges
Describe:

- three-provider blinded primary panel;
- panel ANY and panel MAJORITY as separate endpoints;
- study-specific blinded judge prompt;
- fourth-provider blinded sensitivity judge;
- matching rubric-aware/cued secondary conditions;
- explicit judge API/format failure handling.

Judge failures are missing measurements and never become negative labels.

### Physician response-reference cohort
Describe the shared 60-source sample:

- 30 missing-information;
- 30 conflict;
- 4 targets;
- original + perturbed;
- 480 unique response cells;
- 960 independent physician ratings.

Reviewer-facing packets contain only opaque unit ID, case text, target response, and endpoint fields.

They omit target identity, source stratum, presentation type, perturbation family, changed evidence, judge outputs, and the other physician's label.

### Physician reference endpoint
Primary:

`unsafe_overconfident`

Allowed physician values:

- 1;
- 0;
- CANNOT_DETERMINE.

If the two independent response reviewers agree on the same binary value, that value is the reference. Otherwise they complete a post-independent consensus step and may still return CANNOT_DETERMINE.

CANNOT_DETERMINE is never coerced to 0 and is excluded from binary operating-characteristic denominators.

### Secondary outcomes
Keep separate:

- potentially harmful treatment;
- information-problem recognition;
- guideline-concordant useful next step;
- excessive abstention;
- clinical helpfulness;
- model-output failure.

No composite safety score.

### Statistical analysis
Follow `protocol/STATISTICAL_ANALYSIS_PLAN.md`.

Primary judge validity:

- sensitivity;
- specificity;
- balanced accuracy;
- PPV;
- NPV;
- agreement;
- Cohen kappa;
- source-case cluster-bootstrap 95% CIs.

Secondary:

- human-human agreement;
- paired target risk differences;
- McNemar tests;
- Holm-adjusted target contrasts;
- binomial GEE;
- target × presentation × perturbation-family interaction;
- judge-provider × target-provider matrix;
- blinded-versus-cued comparison;
- selective automation;
- subgroup descriptives;
- target output failures;
- automated full-cohort estimates labeled separately from physician-rated estimates.

### Sample-size rationale
Reference `protocol/SAMPLE_SIZE_JUSTIFICATION.md`.

State that the 60-source physician calibration sample is precision-driven rather than powered for a model-ranking superiority claim.

### Study lock and provenance
Describe the two-stage lock:

1. authoring lock before full perturbation drafting;
2. complete primary study lock before the first target-model call.

The public study lock binds:

- study commit;
- engine commit;
- source manifests;
- 150-case public casepack manifest;
- model panel;
- prompts;
- protocol/SAP;
- sample-size rationale;
- analysis code.

### Ethics and governance
Insert:

- institutional determination;
- physician reviewer participation/consent requirements;
- compensation;
- conflicts/funding;
- provider data-use/retention settings;
- private-vault access/retention controls.

## Results

### Source and construct flow
Report:

- 236 HealthBench consult candidates;
- number drafted;
- construct-valid/rejected/revised counts;
- fallback waves;
- final 150 cases;
- reasons for source exclusion;
- final perturbation-family distribution;
- source specialty/stratum distribution.

### Construct reliability
Report the post-response 30-case second-physician confirmation rate with 95% Wilson CI overall and by perturbation family.

### Physician response agreement
Report:

- independent physician percent agreement;
- Cohen kappa;
- discordance;
- CANNOT_DETERMINE frequency;
- post-independent consensus frequency;
- reviewer-pair descriptives.

Do not hide independent disagreement behind consensus.

### Automated judge validity
Primary table:

| Endpoint | Available n | Sensitivity | Specificity | Balanced accuracy | PPV | NPV | Kappa |
|---|---:|---:|---:|---:|---:|---:|---:|
| Judge 1 | | | | | | | |
| Judge 2 | | | | | | | |
| Judge 3 | | | | | | | |
| Panel ANY | | | | | | | |
| Panel MAJORITY | | | | | | | |

Report judge failures/missing cells. Panel endpoints require a complete three-judge trio.

### Target-model robustness on physician labels
For each target report:

- original unsafe-overconfident rate;
- perturbed rate;
- paired risk difference;
- cluster-bootstrap CI;
- 0→1 and 1→0 transitions;
- McNemar test.

### Pairwise target comparison
Report paired differences in perturbation risk difference and Holm-adjusted pairwise tests.

### Missing-information versus conflict
Report family-specific effects and the prespecified GEE interaction.

### Judge/provider effects
Report the judge-provider × target-provider error matrix and same-provider indicator descriptively.

### Cueing
Report blinded-versus-cued positive-rate difference and change in sensitivity/specificity.

### Selective automation
Report the prespecified unanimity-defer operating point:

- coverage;
- number deferred;
- error among auto-judged cells.

### Model/API failure accounting
Report target model_output_failure separately.

Infrastructure/provider failures should have been resolved before calibration selection; any exception is a protocol deviation and must be reported.

### External replication
Report the 50-source Real-POCQi cohort separately using the same endpoint definitions and frozen model/judge configuration.

## Discussion

### Principal findings
[RESULT-DEPENDENT]

### Interpretation
Keep distinct:

1. construct validity/reliability;
2. judge measurement validity;
3. target-model robustness.

Evidence for one does not substitute for another.

### Comparison with prior work
Discuss HealthBench/HealthBench Professional, Real-POCQi, clinical LLM-as-judge studies, evaluator-bias literature, and missing/conflicting evidence robustness.

Do not claim the study creates a universal benchmark or regulatory standard.

### Practical implications
Potential use as a regression/stress-testing layer is justified only to the extent supported by the measured judge error profile and defer-to-human policy.

### Limitations
Prespecified limitations:

- public benchmark-derived text cases do not represent all clinical encounters;
- stable text rendering is not native HealthBench delivery;
- constructed perturbations may not mirror all real EHR omissions/conflicts;
- initial construct validity is assessed by one physician per source;
- only three physicians contribute;
- post-response construct reliability is assessed only on a 30-case subset;
- model/API behavior is version-specific;
- public benchmark contamination may affect target behavior;
- judge calibration is endpoint- and prevalence-dependent;
- Real-POCQi remains a curated public dataset;
- no patient outcomes are measured.

## Conclusion
Use the narrowest wording supported by the data.

A successful study may support:

> Within the audited task and case-mix scope, [judge/panel] achieved measured [operating characteristics] for detecting the prespecified unsafe-overconfidence endpoint relative to the cross-fitted physician reference.

It may not support:

> The harness proves medical AI is safe.

## Reproducibility statement
Release:

- protocol/SAP;
- source IDs and source-file hashes;
- study/engine commits;
- prompt hashes;
- target/judge model IDs and inference settings;
- public case/response/judge manifests;
- de-identified physician labels where permitted;
- aggregate analysis outputs;
- analysis code.

Do not release HealthBench Professional case text, transformations, source physician answers, or rubrics.
