# Measurement engine pin

This study is designed against:

- Repository: `KAVentures/clinical-ai-eval`
- Commit: `648ad23e8fb6b8a877217341a4bea9e4eb5bd9ca`

The pinned engine supplies shared scoring contracts and judge-schema parsing used by this study.

Study-specific execution behavior that requires stricter publication provenance is intentionally implemented in this repository under `study_runtime/`, including:

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
