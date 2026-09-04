# Ethics and governance checklist

This file is operational guidance, not an ethics-board determination.

## Materials and scope

The planned source cohorts are publicly released/de-identified benchmark materials. The study does not recruit patients, intervene in care, or use study outputs to manage patients.

Physicians A/B/C participate as study reviewers/collaborators. Their participation may still trigger local requirements concerning ethics review, research governance, consent, compensation, conflicts of interest, or data handling.

## Before physician data collection

Obtain and archive the appropriate determination from the institution/jurisdiction under which the study is conducted. Depending on local rules, this may be formal ethics approval, exemption/non-human-subject determination, another research-governance approval, or a documented statement that formal review is not required.

Do not infer the correct category from this repository.

Record:

- responsible institution/sponsor;
- ethics/research-governance authority contacted;
- determination/reference number if applicable;
- date;
- whether physician reviewer consent is required and how obtained;
- reviewer compensation, if any;
- conflicts of interest;
- funding/API credits;
- data-retention plan;
- provider API data-use/retention settings used in the study.

## Cross-fitted reviewer independence

The study uses three physicians with source-level role separation.

For each source case:

- exactly one physician is the construct reviewer;
- the other two physicians are the blinded response reviewers;
- the construct reviewer does not response-rate or adjudicate that source's response cells;
- the response reviewers submit independently before any consensus;
- consensus occurs only between those two response reviewers after their independent labels are locked;
- individual labels are permanently retained.

This prevents a physician who has seen an original/perturbed pair during construction from being presented later as a blinded response reviewer for the same source.

The deterministic role assignment varies across cases so the workload is shared among A/B/C.

## Construct-reliability audit

Initial construct validity is assessed by one physician per source in order to preserve two blinded response reviewers with a three-physician team.

Only after the response reference is locked, a deterministic 30-case subset receives a second construct review by one physician who had previously been a blinded response reviewer for that source.

This post-response audit estimates construct confirmation without contaminating primary response labels.

## Reviewer conduct

Before locking independent labels, physicians should not:

- discuss individual response cells with each other;
- use an LLM to generate physician labels;
- search for source benchmark answers;
- deliberately identify the target model by style.

Case-specific ambiguities may be documented in the review form.

## Data minimization

The public repository stores only source identifiers, metadata, hashes, code, configuration, aggregate results, and de-identified labels when release is appropriate.

The private study vault stores:

- source text;
- transformed text;
- target responses;
- judge raw outputs where needed;
- physician reviewer packets;
- reviewer identity mapping;
- unpublished study outputs.

The vault should be access-controlled and encrypted according to the team's institutional policy even though source cases are public/de-identified.

Do not store API secrets in the repository. Use environment variables or an external key file.

## HealthBench Professional contamination request

HealthBench Professional examples should not be reproduced publicly in plaintext or images. This study follows that request.

Raw or transformed HealthBench Professional case text, source physician responses, and rubrics remain private and are never committed to the public repository.

## Real-POCQi attribution

Real-POCQi is CC BY 4.0. Preserve source attribution in the manuscript and repository metadata.

Any redistributed derived material must comply with the license and the study's separate privacy/contamination controls.

## Commercial API data handling

Before sending source-derived material to a commercial API, record:

- provider;
- exact API product/endpoint;
- account/workspace used;
- data-use/training policy applicable to that API traffic;
- retention settings where configurable;
- region/project controls where relevant.

Prefer configurations in which API submissions are not used for provider model training when available.

Do not assume consumer-chat privacy terms apply to API traffic.

## Conflicts and funding

Predeclare:

- relationships with evaluated AI/model vendors;
- ownership or commercial interest in `clinical-ai-eval` or related products;
- study funding;
- API/model credits;
- whether a vendor reviewed the manuscript.

Vendor review must not include undisclosed veto rights or control over analysis/reporting.

## Clinical claim boundary

The study validates a measurement procedure within a stated source/task/model/time scope.

It does not:

- certify a model as safe for deployment;
- replace prospective clinical validation;
- establish regulatory compliance;
- prove patient benefit;
- authorize clinical use.
