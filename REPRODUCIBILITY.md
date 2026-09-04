# Reproducing the study

This repository is designed so another research group can reproduce the study from public source datasets without receiving any private case files from the authors.

## What is public versus recreated locally

Public repository:

- protocol, SAP and framework-validation scope;
- source revisions and file hashes;
- deterministic selection algorithms/seeds;
- prompts and model configuration;
- physician packet schemas;
- execution/analysis code;
- public ID/hash manifests;
- study and engine commit hashes;
- aggregate/de-identified results when released.

Recreated locally in a private vault:

- HealthBench Professional source text;
- transformed source text;
- target responses;
- physician review packets;
- raw judge responses.

This separation is intentional because HealthBench Professional asks researchers not to reproduce its examples publicly.

## Supported reference environment

Use Python 3.11 for the publication run.

Initial installation:

~~~bash
git clone https://github.com/KAVentures/clinical-ai-eval-physician-validation.git
cd clinical-ai-eval-physician-validation
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[test]"
~~~

Before the primary study lock, the exact installed environment is captured with:

~~~bash
python scripts/capture_environment.py
~~~

This creates:

- `data/environment_lock.txt`
- `data/environment_metadata.json`

Both are hashed into `data/study_lock.json`.

For exact post-publication reproduction, create the Python version recorded in the metadata and install:

~~~bash
python -m pip install -r data/environment_lock.txt
~~~

## No-network synthetic rehearsal

After installation, verify the complete deterministic machinery without API keys:

~~~bash
python scripts/rehearse_study.py
~~~

It compiles the code and exercises synthetic tests covering:

- provider request/retry semantics;
- 150-case primary casepack finalization;
- deterministic fallback review;
- 50-case Real-POCQi finalization;
- 60-source response-validation selection;
- 480-cell four-target response frame;
- cross-fitted physician packet assignment;
- CANNOT_DETERMINE and locked consensus;
- single-judge missingness/threshold analysis;
- clustered precision simulation.

A failed rehearsal is a stop condition.

## Credentials

Copy `.env.example` only as a reference. Do not put secrets in the repository.

Supported environment variables:

- `OPENAI_API_KEY`
- `ANTHROPIC_API_KEY`
- `GOOGLE_API_KEY`
- `XAI_API_KEY`

or use an external KEY=VALUE file:

~~~bash
export MEDROBUST_KEYS_PATH=/secure/path/API_KEYS.local.md
~~~

Define a private vault outside the repository:

~~~bash
export STUDY_VAULT=/secure/path/clinical-ai-eval-physician-validation-v1
mkdir -p "$STUDY_VAULT"
~~~

## Rebuild the public-source queues

~~~bash
python scripts/select_cases.py --vault "$STUDY_VAULT"
~~~

The script downloads immutable source revisions and verifies exact file SHA-256 values and expected row counts. A changed source fails closed.

## Execute the study

Follow `RUNBOOK.md` in order. The high-level immutable sequence is:

1. source queue reconstruction;
2. small authoring technical dry-run;
3. authoring lock;
4. full perturbation drafting;
5. cross-fitted construct validation;
6. freeze the 150-case construct-valid casepack;
7. deterministically select 60 response-validation sources (30/30 families);
8. live endpoint/model smoke tests;
9. capture exact Python/package environment;
10. freeze models, prompts, source/case manifests and analysis code;
11. create/commit `data/study_lock.json`;
12. run 480 target cells (60 × 2 presentations × 4 targets);
13. create 480 cross-fitted physician review cells;
14. run Grok 4.6 on exactly those same 480 cells;
15. lock independent physician submissions and consensus;
16. run the preregistered analyses;
17. perform the post-response construct-reliability audit;
18. run the separately frozen Real-POCQi replication.

No outcome-dependent model, threshold, prompt or case-selection change is permitted after lock.

## Live API reproducibility

Commercial models can change even under stable aliases. Therefore every call records:

- configured model ID;
- provider-returned model/version where available;
- endpoint;
- reasoning setting;
- output limit;
- request SHA-256;
- attempt count;
- HTTP status;
- timestamps;
- usage metadata.

A reproduction should report both the configured ID and the provider-resolved ID/date. Exact behavioral replication cannot be guaranteed if a provider no longer serves the historical model; this limitation is explicit rather than hidden.

## Physician reproduction

The primary design requires three physicians but uses cross-fitting so each response cell still has two independent blinded physician ratings:

- one physician construct-validates a source;
- the other two response-rate that source;
- disagreements/indeterminate labels are resolved only after independent ratings are locked.

Reviewer identities may differ in a replication; role-assignment logic, blinding, endpoint definitions and packet schemas must remain unchanged.

## Validation scope

Read `protocol/FRAMEWORK_VALIDATION_SCOPE.md` before interpreting a reproduction.

The study validates only the declared Clinical-AI-Eval families and measurement layers. It does not validate every capability in the upstream framework.
