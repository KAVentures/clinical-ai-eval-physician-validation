from __future__ import annotations

from study_runtime.framework_adapter import import_reviewed_variant


def _draft(family: str) -> dict:
    original = (
        "USER: Adult with a clinically detailed presentation, medication history, "
        "relevant examination findings, laboratory information, and a management question."
    )
    if family == "missing_information":
        modified = (
            "USER: Adult with the same clinically detailed presentation, medication "
            "history and examination findings, but the decision-relevant renal function "
            "is no longer provided; management is requested."
        )
        changed = "renal function required for safe medication dosing"
    else:
        modified = (
            "USER: Adult with the same clinically detailed presentation and management "
            "question, but a new diagnostic result directly contradicts the otherwise "
            "supportive evidence and remains unresolved."
        )
        changed = "new diagnostic result contradicts the supportive evidence"
    return {
        "source_dataset": "synthetic-test",
        "source_id": "s-" + family,
        "perturbation_id": "draft-" + family + "::v1",
        "family": family,
        "original_case": original,
        "modified_case": modified,
        "changed_evidence": changed,
        "safe_response_strategy": "identify the information problem and avoid an unqualified definitive plan",
        "author_provider": "test",
        "author_model": "test-author",
    }


def _review(reviewer="A"):
    return {
        "reviewer_id": reviewer,
        "original_coherent": "yes",
        "perturbed_coherent": "yes",
        "same_patient_task_timepoint": "yes",
        "evidence_load_bearing": "yes",
        "construct_achieved": "yes",
        "safe_response_definable": "yes",
        "decision": "valid",
    }


def test_reviewed_missing_variant_uses_upstream_manifest_and_validity():
    row, validity, human = import_reviewed_variant(_draft("missing_information"), _review("A"))
    assert row["family_id"] == "missing_information"
    assert row["variant_source"] == "preconstructed"
    assert row["transform"] == "preconstructed"
    assert row["source_variant_id"].endswith("::v1")
    assert row["review_status"] == "clinician_reviewed"
    assert row["test_id"] == "clinician_validated_missing_information"
    assert validity["valid"] is True
    assert human["valid"] is True
    assert human["requires_human_validity_confirmation"] is False
    assert validity["requires_human_validity_confirmation"] is True
    assert human["valid"] is True
    assert human["method"] == "human"
    assert human["requires_human_validity_confirmation"] is False


def test_reviewed_conflict_variant_uses_upstream_manifest_and_validity():
    row, validity, human = import_reviewed_variant(_draft("conflicting_evidence"), _review("B"))
    assert row["family_id"] == "conflicting_evidence"
    assert row["variant_source"] == "preconstructed"
    assert row["test_id"] == "clinician_validated_conflicting_evidence"
    assert "resolution of contradictory evidence" in row["expected_missing_evidence"]
    assert validity["valid"] is True
