# Measurement engine pin

This study is designed against:

- Repository: `KAVentures/clinical-ai-eval`
- Commit: `6fc5b60b6cb1cb68f9748baea65d16f18ddc38c1`

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
