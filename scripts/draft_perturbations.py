#!/usr/bin/env python3
"""Draft controlled perturbations from private source records.

The authoring model is construction tooling, never clinical ground truth. Its exact
provider/model/reasoning settings are read from configs/model_panel.yaml and are
frozen before the full drafting run. Raw modified case text stays in the vault.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path


from study_runtime.journal import append_record, load_latest, refuse_overwrite
from study_runtime.panel import load_panel, require_valid
from study_runtime.providers import call_provider, load_keys


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def extract_json(text: str) -> dict:
    text = (text or "").strip()
    fence = chr(96) * 3
    if text.startswith(fence):
        lines = text.splitlines()
        if lines and lines[0].startswith(fence):
            lines = lines[1:]
        if lines and lines[-1].strip() == fence:
            lines = lines[:-1]
        text = "\n".join(lines)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("authoring model did not return a JSON object")
    return json.loads(text[start : end + 1])


def source_case_text(record: dict) -> str:
    """Stable role-labelled rendering used by both original and perturbed arms."""
    source = record.get("source_record") or {}
    conversation = source.get("conversation")
    messages = conversation.get("messages") if isinstance(conversation, dict) else conversation
    if isinstance(messages, list) and messages:
        rendered = []
        for m in messages:
            if not isinstance(m, dict):
                raise ValueError(f"non-object conversation message for {record.get('source_id')}")
            role = str(m.get("role", "")).strip().upper() or "MESSAGE"
            content = m.get("content", "")
            if isinstance(content, list):
                pieces = []
                for item in content:
                    if isinstance(item, dict):
                        pieces.append(str(item.get("text", item.get("content", ""))))
                    else:
                        pieces.append(str(item))
                content = "\n".join(p for p in pieces if p)
            rendered.append(f"{role}: {str(content)}")
        return "\n\n".join(rendered)
    if record.get("question_text"):
        return str(record["question_text"])
    raise ValueError(f"cannot find source case text for {record.get('source_id')}")


def load_private_sources(path: Path) -> list[dict]:
    out = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                out.append(json.loads(line))
    return out


def validate_payload(payload: dict, source_id: str, original_case: str = "") -> list[dict]:
    if str(payload.get("source_id")) != str(source_id):
        raise ValueError("source_id mismatch in authoring output")
    variants = payload.get("variants")
    if not isinstance(variants, list):
        raise ValueError("variants must be a list")
    seen, clean = set(), []
    for v in variants:
        family = v.get("family")
        if family not in {"missing_information", "conflicting_evidence"}:
            raise ValueError(f"unsupported family {family!r}")
        if family in seen:
            raise ValueError(f"duplicate family {family}")
        seen.add(family)
        applicable = bool(v.get("applicable"))
        modified = str(v.get("modified_case", ""))
        if applicable and not modified.strip():
            raise ValueError(f"applicable {family} missing modified_case")
        if applicable and original_case and modified.strip() == original_case.strip():
            # Caught here, not weeks later: the framework import rejects an
            # unchanged variant, which would otherwise surface only after a
            # physician had already reviewed it.
            raise ValueError(f"applicable {family} variant is identical to the source case")
        if applicable and not bool(v.get("same_patient_task_timepoint")):
            raise ValueError(f"authoring model self-reported task/timepoint drift for {family}")
        clean.append(v)
    return clean


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--sources", required=True, type=Path)
    p.add_argument("--vault", required=True, type=Path)
    p.add_argument("--models", type=Path, default=Path("configs/model_panel.yaml"))
    p.add_argument("--keys", type=Path)
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--resume", action="store_true")
    p.add_argument("--allow-unfrozen-author", action="store_true", help="Dry-run only")
    p.add_argument("--out-name", default="perturbations.private.jsonl",
                   help="Draft file name under <vault>/drafts/. The external cohort uses "
                        "real_pocqi_perturbations.private.jsonl so it can never touch the primary drafts.")
    p.add_argument(
        "--public-manifest",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "data" / "perturbation_drafts_manifest.csv",
    )
    args = p.parse_args()

    cfg = load_panel(args.models)
    registry = require_valid(cfg)
    if not cfg.get("authoring_frozen") and not args.allow_unfrozen_author:
        raise RuntimeError("authoring model/prompt is not frozen; dry-run with --allow-unfrozen-author, then freeze before full drafting")
    author = cfg.get("authoring_model") or {}
    provider, model = author.get("provider"), author.get("model")
    effort = str(author.get("reasoning_effort", "provider_default"))
    if not provider or not model:
        raise RuntimeError("authoring_model provider/model missing from model config")

    policy = cfg.get("inference_policy") or {}
    keys = load_keys(args.keys, registry)
    prompt_path = Path(__file__).resolve().parents[1] / "prompts" / "perturbation_author_prompt.txt"
    system = prompt_path.read_text(encoding="utf-8")
    rows = load_private_sources(args.sources)
    if args.limit:
        rows = rows[: args.limit]

    if not args.out_name.endswith(".private.jsonl") or "/" in args.out_name:
        raise RuntimeError("--out-name must be a bare file name ending in .private.jsonl")
    private_out = args.vault / "drafts" / args.out_name
    private_out.parent.mkdir(parents=True, exist_ok=True)
    args.public_manifest.parent.mkdir(parents=True, exist_ok=True)

    refuse_overwrite(private_out, args.resume, "perturbation drafts")
    drafted = load_latest(private_out, "perturbation_id")
    completed = {str(r.get("source_id")) for r in drafted.values()}
    failures: list[str] = []

    for i, source in enumerate(rows, start=1):
        source_id = str(source["source_id"])
        if source_id in completed:
            continue
        case = source_case_text(source)
        user = f"SOURCE_ID: {source_id}\n\nSOURCE CASE (preserve its clinical task and timepoint):\n{case}\n"
        text, status, meta = call_provider(
            provider, model, system, user, keys,
            reasoning_effort=effort,
            max_output_tokens=int(policy.get("author_max_output_tokens", 4500)),
            max_attempts=int(policy.get("max_attempts", 4)),
            retry_backoff_seconds=float(policy.get("retry_backoff_seconds", 1.0)),
            timeout_seconds=int(policy.get("timeout_seconds", 180)),
            registry=registry,
        )
        if status != "ok":
            raise RuntimeError(f"authoring call failed for {source_id}: status={status}, meta={meta}")
        try:
            payload = extract_json(text)
            variants = validate_payload(payload, source_id, case)
        except ValueError as exc:
            # One malformed draft must not discard the run. The source is left
            # undrafted; rerun with --resume to try it again.
            failures.append(f"{source_id}: {exc}")
            print(f"[{i}/{len(rows)}] UNUSABLE DRAFT {source_id}: {exc}")
            continue

        for v in variants:
            family = v["family"]
            applicable = bool(v.get("applicable"))
            modified = str(v.get("modified_case", ""))
            perturbation_id = f"{source_id}::{family}::v1"
            private_record = {
                "source_dataset": source.get("source_dataset"),
                "source_id": source_id,
                "perturbation_id": perturbation_id,
                "perturbation_version": 1,
                "family": family,
                "applicable_draft": applicable,
                "clinical_decision": payload.get("clinical_decision", ""),
                "original_case": case,
                "modified_case": modified,
                "changed_evidence": v.get("changed_evidence", ""),
                "why_potentially_load_bearing": v.get("why_potentially_load_bearing", ""),
                "safe_response_strategy": v.get("safe_response_strategy", ""),
                "same_patient_task_timepoint_author_claim": v.get("same_patient_task_timepoint"),
                "other_material_changes_author_claim": v.get("other_material_changes", []),
                "author_provider": provider,
                "author_model": model,
                "author_reasoning_effort": effort,
                "authoring_meta": meta,
                "status": "draft_requires_physician_validation",
            }
            append_record(private_out, private_record)
            drafted[perturbation_id] = private_record
        print(f"[{i}/{len(rows)}] drafted {source_id}")

    fields = [
        "source_dataset", "source_id", "perturbation_id", "perturbation_version", "family",
        "applicable_draft", "original_case_sha256", "modified_case_sha256",
        "changed_evidence_sha256", "author_provider", "author_model",
        "author_reasoning_effort", "resolved_model", "request_sha256", "status",
    ]
    # Rebuilt from the private record file every time, so an interrupted run can
    # never leave the public manifest missing rows that exist privately.
    dedup = {}
    for pid, r in drafted.items():
        meta = r.get("authoring_meta") or {}
        modified = str(r.get("modified_case", ""))
        dedup[pid] = {
            "source_dataset": r.get("source_dataset", ""),
            "source_id": r["source_id"],
            "perturbation_id": pid,
            "perturbation_version": r.get("perturbation_version", 1),
            "family": r["family"],
            "applicable_draft": str(bool(r.get("applicable_draft"))).lower(),
            "original_case_sha256": sha256_text(str(r["original_case"])),
            "modified_case_sha256": sha256_text(modified) if modified else "",
            "changed_evidence_sha256": sha256_text(str(r.get("changed_evidence", ""))),
            "author_provider": r.get("author_provider", ""),
            "author_model": r.get("author_model", ""),
            "author_reasoning_effort": r.get("author_reasoning_effort", ""),
            "resolved_model": meta.get("resolved_model") or "",
            "request_sha256": meta.get("request_sha256") or "",
            "status": r.get("status", ""),
        }
    with args.public_manifest.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(sorted(dedup.values(), key=lambda r: str(r["perturbation_id"])))

    print(f"Private draft content: {private_out}")
    print(f"Public ID/hash manifest: {args.public_manifest}")
    print("No draft is study-valid until physician construct review is complete.")
    if failures:
        print(f"\n{len(failures)} sources produced an unusable draft and are NOT drafted:")
        for line in failures:
            print("  " + line)
        raise SystemExit("Rerun with --resume to retry them before building review packets.")


if __name__ == "__main__":
    main()
