#!/usr/bin/env python3
"""Check configs/model_panel.yaml without contacting any provider. Free.

Prints the resolved panel (who serves each model, which API style, which key it
needs, which developer it is attributed to) and every error or warning. Exits
non-zero on any error. Run it after every edit to the panel.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from study_runtime.panel import design, load_panel, roles, validate_panel
from study_runtime.providers import ProviderConfigError, entry_vendor, provider_registry, resolve_provider


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--models", type=Path, default=Path("configs/model_panel.yaml"))
    args = p.parse_args()
    cfg = load_panel(args.models)
    errors, warnings = validate_panel(cfg)
    try:
        registry = provider_registry(cfg)
    except ProviderConfigError:
        registry = None
    if registry:
        print(f"{'role':38} {'provider/model':48} {'api':24} {'effort':16} {'key':20} developer")
        for role, e in roles(cfg):
            try:
                spec = resolve_provider(e.get("provider", ""), registry)
            except ProviderConfigError:
                print(f"{role:38} {e.get('provider')}/{e.get('model')}  <unknown provider>")
                continue
            print(f"{role:38} {(e.get('provider', '') + '/' + str(e.get('model', ''))):48} {spec['api']:24} "
                  f"{str(e.get('reasoning_effort', 'provider_default')):16} {str(spec.get('api_key_env') or '-'):20} "
                  f"{entry_vendor(e, registry)}")
    d = design(cfg)
    print(f"\ndesign: {d['target_count']} targets, distinct developers={d['distinct_target_vendors']}, "
          f"{d['primary_judge_count']} primary judge(s); authoring_frozen={cfg.get('authoring_frozen')}, "
          f"frozen={cfg.get('frozen')}")
    for w in warnings:
        print(f"WARNING: {w}")
    for e in errors:
        print(f"ERROR:   {e}")
    if errors:
        sys.exit(f"{len(errors)} error(s) in {args.models}")
    print("Panel is valid. Next: `python scripts/list_models.py` (free) to confirm the IDs exist, "
          "then `python scripts/smoke_test_providers.py` (one tiny paid call per model).")


if __name__ == "__main__":
    main()
