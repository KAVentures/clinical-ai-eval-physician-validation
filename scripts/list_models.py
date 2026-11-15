#!/usr/bin/env python3
"""List the model IDs each configured provider offers this API key, and check that
every model named in the panel is among them.

Listing models generates no tokens; the built-in providers do not bill for it.
Use it to pick a newer model or confirm an ID before the paid smoke test. A
provider without a listing endpoint is reported, not treated as an error.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from study_runtime.panel import load_panel, require_valid, roles
from study_runtime.providers import list_models, load_keys


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--models", type=Path, default=Path("configs/model_panel.yaml"))
    p.add_argument("--keys", type=Path)
    p.add_argument("--provider", action="append", help="Only these providers (repeatable)")
    p.add_argument("--grep", default="", help="Only print IDs containing this text")
    args = p.parse_args()
    cfg = load_panel(args.models)
    registry = require_valid(cfg)
    keys = load_keys(args.keys, registry)
    wanted: dict[str, set[str]] = {}
    for _, e in roles(cfg):
        wanted.setdefault(e["provider"], set()).add(str(e["model"]))
    missing = []
    for provider in sorted(args.provider or wanted):
        print(f"\n== {provider}")
        try:
            ids = list_models(provider, keys, registry)
        except Exception as exc:  # no listing endpoint, missing key, network
            print(f"   could not list models: {exc}")
            continue
        for i in ids:
            if args.grep.lower() in i.lower():
                print(f"   {i}{'   <- in panel' if i in wanted.get(provider, set()) else ''}")
        for m in sorted(wanted.get(provider, set())):
            if m not in ids:
                missing.append(f"{provider}/{m}")
    if missing:
        sys.exit("\nNot offered to this key: " + ", ".join(missing))
    print("\nEvery model in the panel is offered by its provider.")


if __name__ == "__main__":
    main()
