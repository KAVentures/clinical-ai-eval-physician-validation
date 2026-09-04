"""Adapter that routes physician-approved study variants through Clinical-AI-Eval.

The study is allowed to author a clinically targeted manifestation outside the
framework, but a construct-valid variant is not admitted to the frozen casepack
until Clinical-AI-Eval itself has normalized it into the family manifest and run
its structural validity contract.

This makes the study a validation of a supported framework code path rather than
a parallel reimplementation of the same concepts.
"""
from __future__ import annotations

from caeval import family_sdk


def import_reviewed_variant(draft: dict, review: dict) -> tuple[dict, dict, dict]:
    family_id = str(draft["family"])
    reviewer_id = str(review.get("reviewer_id", "")).strip()
    if not reviewer_id:
        raise RuntimeError("framework import requires the completed construct review row")
    original = str(draft["original_case"])
    modified = str(draft["modified_case"])
    changed = str(draft.get("changed_evidence", "")).strip()

    if family_id == "missing_information":
        expected = changed or "clinically load-bearing information removed from the case"
        removed_fields = [changed] if changed else ["clinically_load_bearing_information"]
    elif family_id == "conflicting_evidence":
        expected = (
            "resolution of contradictory evidence"
            + (f": {changed}" if changed else "")
        )
        removed_fields = []
    else:
        raise RuntimeError(f"unsupported Clinical-AI-Eval family {family_id!r}")

    source_variant_id = str(draft["perturbation_id"])
    author_provider = str(draft.get("author_provider", "")).strip()
    author_model = str(draft.get("author_model", "")).strip()
    provenance = (
        f"study preconstructed variant {source_variant_id}; "
        f"author={author_provider or 'unspecified'}/{author_model or 'unspecified'}; "
        f"construct reviewer={reviewer_id}"
    )

    fam = family_sdk.load(family_id)
    case = {
        "item_id": str(draft["source_id"]),
        "input_text": original,
        "dataset": str(draft.get("source_dataset", "")),
        "ground_truth_label": "",
    }
    row = fam.ingest_preconstructed_variant(
        case,
        {
            "family_id": family_id,
            "input_text": modified,
            "expected_missing_evidence": expected,
            "removed_fields": removed_fields,
            "synthetic_added_text": "",
            "construction_provenance": provenance,
            "review_status": "clinician_reviewed",
            "reviewer_count": 1,
            "reviewer_role": "physician",
            "source_variant_id": source_variant_id,
            "safe_response_strategy": str(draft.get("safe_response_strategy", "")),
        },
        require_reviewed=True,
    )
    structural = fam.audit_variant(row, original)
    if not structural.valid:
        raise RuntimeError(
            f"Clinical-AI-Eval structural validity gate rejected reviewed variant "
            f"{source_variant_id}: {structural.reasons}"
        )
    human = fam.confirm_preconstructed_variant(row, original, review)
    if not human.valid or human.requires_human_validity_confirmation:
        raise RuntimeError(
            f"Clinical-AI-Eval human validity confirmation rejected reviewed variant "
            f"{source_variant_id}: {human.reasons}"
        )
    return row, structural.as_dict(), human.as_dict()
