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

import yaml

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


def validate_payload(payload: dict, source_id: str) -> list[dict]:
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
    p.add_argument(
        "--public-manifest",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "data" / "perturbation_drafts_manifest.csv",
    )
    args = p.parse_args()

    cfg = yaml.safe_load(args.models.read_text(encoding="utf-8"))
    if not cfg.get("authoring_frozen") and not args.allow_unfrozen_author:
        raise RuntimeError("authoring model/prompt is not frozen; dry-run with --allow-unfrozen-author, then freeze before full drafting")
    author = cfg.get("authoring_model") or {}
    provider, model = author.get("provider"), author.get("model")
    effort = str(author.get("reasoning_effort", "provider_default"))
    if not provider or not model:
        raise RuntimeError("authoring_model provider/model missing from model config")

    policy = cfg.get("inference_policy") or {}
    keys = load_keys(args.keys)
    prompt_path = Path(__file__).resolve().parents[1] / "prompts" / "perturbation_author_prompt.txt"
    system = prompt_path.read_text(encoding="utf-8")
    rows = load_private_sources(args.sources)
    if args.limit:
        rows = rows[: args.limit]

    private_out = args.vault / "drafts" / "perturbations.private.jsonl"
    private_out.parent.mkdir(parents=True, exist_ok=True)
    args.public_manifest.parent.mkdir(parents=True, exist_ok=True)

    completed: set[str] = set()
    public_rows = []
    if args.resume and private_out.exists():
        with private_out.open(encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    completed.add(str(json.loads(line).get("source_id")))
    if args.resume and args.public_manifest.exists():
        with args.public_manifest.open(newline="", encoding="utf-8") as f:
            public_rows.extend(csv.DictReader(f))

    mode = "a" if args.resume else "w"
    with private_out.open(mode, encoding="utf-8") as private_f:
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
            )
            if status != "ok":
                raise RuntimeError(f"authoring call failed for {source_id}: status={status}, meta={meta}")
            payload = extract_json(text)
            variants = validate_payload(payload, source_id)

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
                private_f.write(json.dumps(private_record, ensure_ascii=False) + "\n")
                public_rows.append({
                    "source_dataset": source.get("source_dataset", ""),
                    "source_id": source_id,
                    "perturbation_id": perturbation_id,
                    "perturbation_version": 1,
                    "family": family,
                    "applicable_draft": str(applicable).lower(),
                    "original_case_sha256": sha256_text(case),
                    "modified_case_sha256": sha256_text(modified) if modified else "",
                    "changed_evidence_sha256": sha256_text(str(v.get("changed_evidence", ""))),
                    "author_provider": provider,
                    "author_model": model,
                    "author_reasoning_effort": effort,
                    "resolved_model": meta.get("resolved_model") or "",
                    "request_sha256": meta.get("request_sha256") or "",
                    "status": "draft_requires_physician_validation",
                })
            print(f"[{i}/{len(rows)}] drafted {source_id}")

    fields = [
        "source_dataset", "source_id", "perturbation_id", "perturbation_version", "family",
        "applicable_draft", "original_case_sha256", "modified_case_sha256",
        "changed_evidence_sha256", "author_provider", "author_model",
        "author_reasoning_effort", "resolved_model", "request_sha256", "status",
    ]
    dedup = {str(r["perturbation_id"]): r for r in public_rows}
    with args.public_manifest.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(sorted(dedup.values(), key=lambda r: str(r["perturbation_id"])))

    print(f"Private draft content: {private_out}")
    print(f"Public ID/hash manifest: {args.public_manifest}")
    print("No draft is study-valid until physician construct review is complete.")


if __name__ == "__main__":
    main()
