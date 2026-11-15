# Measurement engine pin

This study is designed against:

- Repository: `KAVentures/clinical-ai-eval`
- Commit: `151cbce178ff2755a50b73db22085b43575cc519`

**Pin status: final for this study.** The pin is an exact commit, and pip installs
it by commit hash (`pyproject.toml`, `requirements.txt`), so it does not depend on
any branch being merged. The commit is engine `main` as of 2026-11-13 (`5fd7ab5`)
plus the v0.21.1 structural-gate fix and the v0.22.0 self-service and model-choice
work, and is reachable from the engine branch `claude/intelligent-wright-ia7wf7`.
Pinning this commit means the study validates the same engine version
organisations install. The study's own model calls still go through
`study_runtime/`, which is frozen with the study and simulated in its rehearsal.

Keep that commit reachable: do not delete the branch until the commit is part of
`main`. A normal merge commit keeps the hash; a squash or rebase merge does not, so
use a merge commit, or keep the branch. Do not re-pin to a later engine commit for
convenience: the lock records this commit and refuses to run against any other.

Why the pin moved from `cb2c551` (via `14371d9`):

- `cb2c551` rejected physician-valid variants for surface traits of the *source*
  query (an unpunctuated ending on a short word; the substrings `translate`,
  `summarize`, `icd-10`). Measured on the real pinned HealthBench Professional file,
  24 of the 236 consult sources (10%) would have been rejected before any physician
  judgement counted, and each rejection aborted casepack finalization. The fix
  applies those two heuristics to a preconstructed variant only when the edit
  introduced the trait (engine `CORRECTIONS.md`, v0.21.1).
- Engine `main` now parses judge output strictly: every 0/1 field must be a bare
  integer 0 or 1, and `correct_abstention` and `excessive_abstention` may not both
  be 1. Anything else is a judge parse failure, i.e. a missing measurement. The
  study judge prompt states both rules.

The pinned framework commit is the exact Clinical-AI-Eval version this study prospectively validates. The final physician-approved perturbations enter through its first-class preconstructed-variant family SDK path, so the study exercises framework code rather than a parallel study-only manifestation contract. It supplies the shared scoring contract and judge-schema parsing and, importantly, supports the study's evidence-based policies: one calibrated blinded judge may be used when explicitly configured, multi-provider judging remains an optional robustness mode, two independent clinicians may resolve ties by locked post-independent consensus, and source-level cross-fitted clinician roles are representable.

Study-specific orchestration that is not part of the reusable framework is intentionally implemented in this repository under `study_runtime/`, including:

- exact provider endpoint selection;
- exact reasoning-effort serialization;
- bounded retry semantics;
- transport/provider/model-output failure separation;
- configured/resolved model provenance;
- request hashes and attempt metadata.

The study-specific blinded judge prompt is also stored in this repository and is not implicitly inherited from a later `clinical-ai-eval` release.

## Lock rule

Before the first primary target-model call, `scripts/freeze_study.py` binds both:

- the exact study-repository commit; and
- this engine commit.

After that lock, advancing the engine commit—or changing study runtime behavior, judge parsing contracts, prompts, endpoint definitions, model IDs, inference settings, source manifests, casepack, or analysis code—is a protocol deviation and must be documented.

Do not silently update the engine because a newer version becomes available during the study.

## Install

~~~bash
python -m pip install -e .
~~~

The pinned dependency is also encoded in `pyproject.toml` and `requirements.txt`.
