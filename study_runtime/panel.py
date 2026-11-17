"""Read and check the model panel (configs/model_panel.yaml).

Every study script reads author, targets and judge through this module, so
changing a model means editing one YAML file and nothing else. `validate_panel`
is offline: it never contacts a provider and costs nothing. Run it with
`python scripts/validate_panel.py`.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from study_runtime.providers import (
    EFFORTS_BY_API, ProviderConfigError, entry_vendor, provider_registry, resolve_provider,
)

DEFAULT_DESIGN = {"target_count": 4, "distinct_target_vendors": True, "primary_judge_count": 1}


def load_panel(path: Path) -> dict:
    cfg = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not isinstance(cfg, dict):
        raise ProviderConfigError(f"{path}: the model panel must be a YAML mapping")
    return cfg


def design(cfg: dict) -> dict:
    return {**DEFAULT_DESIGN, **(cfg.get("design") or {})}


def roles(cfg: dict) -> list[tuple[str, dict]]:
    out = []
    if cfg.get("authoring_model"):
        out.append(("author", cfg["authoring_model"]))
    out += [(f"target:{t.get('target_id')}", t) for t in cfg.get("target_models") or []]
    out += [(f"judge:{j.get('judge_id')}", j) for j in cfg.get("primary_judges") or []]
    out += [(f"secondary_judge:{j.get('judge_id')}", j) for j in cfg.get("secondary_judges") or []]
    return out


def validate_panel(cfg: dict) -> tuple[list[str], list[str]]:
    """Return (errors, warnings). Errors block every study phase."""
    errors: list[str] = []
    warnings: list[str] = []
    try:
        registry = provider_registry(cfg)
    except ProviderConfigError as exc:
        return [str(exc)], []

    for role, entry in roles(cfg):
        for field in ("provider", "model"):
            if not str(entry.get(field, "")).strip():
                errors.append(f"{role}: `{field}` is required")
        if not entry.get("provider"):
            continue
        try:
            spec = resolve_provider(entry["provider"], registry)
        except ProviderConfigError as exc:
            errors.append(f"{role}: {exc}")
            continue
        effort = str(entry.get("reasoning_effort", "provider_default")).lower()
        if effort not in EFFORTS_BY_API[spec["api"]]:
            errors.append(
                f"{role}: reasoning_effort {effort!r} is not valid for provider "
                f"{entry['provider']!r} ({spec['api']}); allowed {sorted(EFFORTS_BY_API[spec['api']])}")
        if spec["api"] == "openai_chat_completions" and effort != "provider_default" \
                and not spec.get("effort_param", "reasoning_effort"):
            errors.append(f"{role}: provider {entry['provider']!r} has effort_param: null, so "
                          "reasoning_effort must be provider_default")
        if effort == "provider_default" and not role.startswith("secondary"):
            warnings.append(
                f"{role}: reasoning_effort is provider_default; the provider may change that default "
                "between model versions, so set it explicitly before freezing")
        if str(entry.get("tools", "disabled")) != "disabled":
            errors.append(f"{role}: tools must be disabled")

    d = design(cfg)
    targets = cfg.get("target_models") or []
    judges = cfg.get("primary_judges") or []
    target_ids = [t.get("target_id") for t in targets]
    judge_ids = [j.get("judge_id") for j in [*judges, *(cfg.get("secondary_judges") or [])]]
    if any(not x for x in target_ids) or len(set(target_ids)) != len(target_ids):
        errors.append("every target needs a unique target_id")
    if any(not x for x in judge_ids) or len(set(judge_ids)) != len(judge_ids):
        errors.append("every judge needs a unique judge_id")
    if len(targets) != int(d["target_count"]):
        errors.append(f"design.target_count is {d['target_count']} but {len(targets)} targets are listed")
    if len(judges) != int(d["primary_judge_count"]):
        errors.append(f"design.primary_judge_count is {d['primary_judge_count']} but "
                      f"{len(judges)} primary judges are listed")
    if any(j.get("mode", "blinded") != "blinded" for j in judges):
        errors.append("every primary judge must use mode: blinded")
    if not errors:
        vendors = [entry_vendor(t, registry) for t in targets]
        if d["distinct_target_vendors"] and len(set(vendors)) != len(vendors):
            errors.append(f"design.distinct_target_vendors is true but target vendors repeat: {vendors}")
        judge_vendors = {entry_vendor(j, registry) for j in judges}
        shared = judge_vendors & set(vendors)
        if shared:
            warnings.append(
                f"judge developer(s) {sorted(shared)} also built a target; the same-developer audit "
                "reports those cells separately (expected for this design, stated in the SAP)")
        author = cfg.get("authoring_model")
        if author and entry_vendor(author, registry) in judge_vendors:
            warnings.append("the perturbation author shares a developer with a primary judge; the "
                            "author prompt assumes the author is not the judge")
    if cfg.get("frozen") and errors:
        errors.append("the panel is marked frozen but is invalid")
    return errors, warnings


def require_valid(cfg: dict) -> dict:
    errors, _ = validate_panel(cfg)
    if errors:
        raise ProviderConfigError("invalid model panel:\n  - " + "\n  - ".join(errors)
                                  + "\nRun `python scripts/validate_panel.py` for details.")
    return provider_registry(cfg)


def key_envs(cfg: dict, role_prefixes: tuple[str, ...]) -> set[str]:
    registry = provider_registry(cfg)
    out = set()
    for role, entry in roles(cfg):
        if role.startswith(role_prefixes):
            env = resolve_provider(entry["provider"], registry).get("api_key_env")
            if env:
                out.add(env)
    return out
