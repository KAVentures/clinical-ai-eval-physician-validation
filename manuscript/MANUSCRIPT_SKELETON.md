# Physician-Anchored Validation of Clinical-AI-Eval: A Framework for Stress-Testing Clinical AI Under Missing and Conflicting Evidence

**Status:** preregistration-era manuscript skeleton; no study results inserted.

## Abstract

### Background
Clinical AI evaluations increasingly use LLMs as automated judges, but evaluator choice can materially affect measured performance. Static, fully specified cases may also under-test a clinically important failure mode: over-committing when decision-relevant evidence is absent or internally contradictory.

### Objective
To validate Clinical-AI-Eval as a reproducible clinical-AI assurance framework by testing the clinical validity of its perturbations, the criterion validity and robustness of its automated judge layer against blinded physicians, the usefulness of its defer-to-human logic, and external reproducibility; target-model robustness is a secondary application of the validated framework.

### Methods
Prospective framework-validation study using a 150-source physician-validated HealthBench Professional-derived construct cohort and a deterministic 60-source response-validation subset. Four provider-diverse target models answer original and perturbed presentations only for the 60-source subset, yielding 480 response cells. Every response cell receives two independent cross-fitted physician ratings and one blinded Grok 4.6 automated-evaluator score. Grok 4.6 is prospectively validated against physicians rather than treated as ground truth. External replication uses 50 construct-valid Real-POCQi sources with physician-anchored target evaluation.

### Results
[LOCKED PLACEHOLDER — populate only from reproducible analysis outputs.]

### Conclusions
[LOCKED PLACEHOLDER — distinguish evaluator validity from target-model performance and avoid deployment-safety claims.]

## Introduction

1. Clinical generative AI is increasingly evaluated using model-based graders and rubric-driven automated judges.
2. Automated judges are measurement instruments and can exhibit error, disagreement, provider effects, and cue sensitivity.
3. Static fully specified cases under-test responses to missing or contradictory decision-relevant evidence.
4. Controlled perturbations can isolate these robustness failures, but the evaluator itself must be calibrated against physicians.
5. Clinical-AI-Eval is a reusable framework, but its usefulness cannot be inferred from engineering completeness alone.
6. This study therefore validates five framework properties:
   - construct validity of the perturbation layer;
   - criterion validity of automated judging against physicians;
   - reliability across evaluator/provider conditions;
   - actionability of disagreement-based defer-to-human logic;
   - external robustness on an independent clinical source cohort.
7. Target-model behavior is a secondary application used to exercise the framework, not the primary scientific object.

## Methods

### Study design
Describe the prospective validation of the pinned Clinical-AI-Eval framework and explicitly map each component to a validation question:

- perturbation layer -> construct validity;
- automated judge layer -> criterion validity versus physicians;
- same-provider Grok-target versus other-provider scoring -> evaluator robustness;
- unanimity/disagreement routing -> actionability and safe defer-to-human coverage;
- Real-POCQi -> external robustness;
- target-model comparisons -> secondary application of the validated measurement system.

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

- one prespecified blinded automated evaluator: Grok 4.6;
- study-specific blinded judge prompt;
- exact 480-cell overlap with the physician-reference cohort;
- same-provider Grok-on-Grok audit;
- explicit judge API/format failure handling;
- no proprietary multi-judge panel in the confirmatory study.

Judge failures are missing measurements and never become negative labels.

If an eligible open-weight clinical judge is publicly released and version-pinnable before study lock, include it only as a prespecified secondary sensitivity analysis. It does not replace physicians or Grok 4.6. If no eligible public release exists at lock, omit this analysis rather than selecting a post-hoc substitute.

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
- Grok-on-Grok versus Grok-on-other-provider operating-characteristic audit;
- successful automated-measurement coverage and failure rate;
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
| Grok 4.6 | | | | | | | |

Report judge failures/missing cells and automated-measurement coverage. Grok 4.6 is compared directly with the physician reference.

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
Report Grok-4.6 judge performance on Grok target responses versus non-Grok target responses and by target provider.

### Cueing


### Automated scoring coverage
Report successful Grok-4.6 measurement coverage, missing/failed measurements, sensitivity, specificity and error among available automated measurements. Do not create a post-hoc self-confidence defer threshold.
### Model/API failure accounting
Report target model_output_failure separately.

Infrastructure/provider failures should have been resolved before calibration selection; any exception is a protocol deviation and must be reported.

### External replication
Report the 50-source Real-POCQi cohort separately using the same endpoint definitions and frozen model/judge configuration.

## Discussion

### Principal findings
[RESULT-DEPENDENT]

### Interpretation
Interpret the results first as validation of Clinical-AI-Eval:

1. **construct validity** — are the framework's stressors clinically real?
2. **criterion validity** — can the automated layer reproduce physician judgments within a measured error profile?
3. **reliability** — are conclusions stable enough across judge/provider conditions?
4. **actionability** — does defer-to-human routing reduce automated error at useful coverage?
5. **external robustness** — do these findings reproduce on Real-POCQi?
6. **secondary target-model findings** — what the framework reveals about GPT/Claude/Gemini/Grok.

Evidence for one framework component does not substitute for another.

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

> Within the audited task and case-mix scope, Clinical-AI-Eval generated clinically valid stress tests and its automated evaluation layer achieved measured [operating characteristics] relative to the cross-fitted physician reference, with [coverage/error] under the prespecified defer-to-human rule and [external replication finding] on Real-POCQi.

A mixed or negative study may instead support a bounded conclusion such as:

> Clinical-AI-Eval's perturbation layer was clinically valid, but its automated judge layer was insufficiently reliable for unattended scoring; the framework should therefore retain physician adjudication for [specified conditions].

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
