# Clinical-AI-Eval validation scope

This study is a **prospective validation of a defined slice of Clinical-AI-Eval**, not a certification of every feature in the repository.

## Framework under test

Repository: `KAVentures/clinical-ai-eval`

The exact framework commit is pinned in `ENGINE_PIN.md` and bound into the final study lock.

## In-scope framework claims

### 1. Missing-information stress testing

Family: `missing_information`

Manifestation path under test: `YamlFamily.ingest_preconstructed_variant()`.

Question: can the framework admit, content-address, structurally validate and evaluate clinically targeted preconstructed cases in which a genuinely load-bearing fact is absent, and can those cases reveal unsafe over-commitment without simply rewarding blanket refusal?

Evidence:

- physician construct validation on the frozen source cohort;
- post-response second-physician construct confirmation audit;
- paired physician-rated original-versus-perturbed target behavior.

### 2. Conflicting-evidence stress testing

Family: `conflicting_evidence`

Manifestation path under test: `YamlFamily.ingest_preconstructed_variant()`.

Question: can the framework admit, content-address, structurally validate and evaluate clinically targeted preconstructed cases containing a consequential unresolved contradiction while preserving patient, task and decision timepoint?

Evidence:

- physician construct validation;
- post-response construct confirmation;
- paired physician-rated target behavior.

### 3. Safety/helpfulness separation

Question: does the framework avoid treating abstention as automatically safe/useful?

Evidence:

- physician ratings of unsafe overconfidence;
- potentially harmful treatment;
- excessive abstention;
- clinically helpful response;
- guideline-concordant/clinically reasonable next step.

No composite safety score is used.

### 4. Automated scoring layer

Question: can one version-pinned automated evaluator, instantiated here as Grok 4.6, reproduce the physician reference sufficiently well for the specified unsafe-overconfidence endpoint?

Prespecified framework targets inherited from the pre-existing Clinical-AI-Eval validation protocol:

- sensitivity >= 0.80;
- specificity >= 0.80 (equivalent to false-alert rate <= 0.20).

All operating characteristics and confidence intervals are reported even if the targets are missed.

The study explicitly audits Grok judging Grok target responses versus judging other providers. Grok 4.6 is not assumed unbiased.

### 5. Human calibration / review mechanics

Question: can the framework maintain independent physician labels, quantify human agreement, preserve indeterminate cases, and resolve disagreements without silently converting them to safe?

Evidence:

- two independent cross-fitted response ratings per cell;
- CANNOT_DETERMINE retained;
- locked post-independent consensus;
- original labels preserved.

## Out of scope

This study does **not** validate or mature the following Clinical-AI-Eval capabilities:

- `patient_red_flag` or patient-episode evaluation;
- RAG/retrieval families such as `retrieval_failure`;
- citation verification;
- certificate/decision-certifiability machinery;
- procurement decision workflows;
- release gates;
- surveillance/drift monitoring;
- browser/UI/IAM functionality;
- arbitrary future perturbation families;
- the built-in deterministic helper transforms themselves (`remove_labs`,
  `remove_imaging`, `remove_exam`, `make_minimal_hpi`, and the generic
  `add_conflict` implementation). They remain development/smoke-test helpers
  unless separately studied.
- every possible clinical specialty, language, modality, or deployment setting.

No paper or repository metadata should state that “Clinical-AI-Eval as a whole is clinically validated.”

## External replication

Real-POCQi tests whether the **same scoped framework methods** generalize to a different public clinical source dataset.

Under Clinical-AI-Eval's current maturity terminology, this is external-dataset replication by the same research team. It is **not** the `externally_replicated` maturity level, which requires reproduction by another organization.

## How results map back to framework maturity

A successful study can support evidence for calibration/validation of the tested families and endpoint within the audited scope. Any maturity-file change in Clinical-AI-Eval must:

1. name the exact study artifact/commit;
2. name the tested family and endpoint;
3. retain all limitations;
4. avoid upgrading unrelated families;
5. avoid claiming external-organizational replication.

A negative result is equally informative: the family or automated evaluator remains experimental/calibrated with explicit human-review requirements.
