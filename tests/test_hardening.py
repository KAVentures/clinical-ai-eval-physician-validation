"""Regressions found by running the study end to end instead of in fragments."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from study_runtime import journal, providers
from study_runtime.framework_adapter import FrameworkRejection, import_reviewed_variant

ROOT = Path(__file__).resolve().parents[1]


def load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_source_file_is_split_on_newline_only():
    """The pinned HealthBench Professional file has U+2028 inside JSON strings;
    str.splitlines() cut those records in half and Phase 1 could not run."""
    sc = load_script("select_cases")
    raw = (json.dumps({"id": 1, "t": "a b\x0cc\x85d"}, ensure_ascii=False) + "\n"
           + json.dumps({"id": 2}) + "\n").encode("utf-8")
    assert len(raw.decode().splitlines()) > 2          # the old behaviour
    rows = sc.parse_jsonl(raw)
    assert [r["id"] for r in rows] == [1, 2] and rows[0]["t"] == "a b\x0cc\x85d"


def test_journal_survives_a_killed_writer_and_never_overwrites(tmp_path):
    path = tmp_path / "out.private.jsonl"
    journal.append_record(path, {"id": "a", "status": "provider_failure"})
    journal.append_record(path, {"id": "b", "status": "ok"})
    journal.append_record(path, {"id": "a", "status": "ok"})          # the retry
    with path.open("a") as f:
        f.write('{"id": "c", "status": "o')                           # process killed mid-write
    records = journal.load_latest(path, "id")
    assert {k: v["status"] for k, v in records.items()} == {"a": "ok", "b": "ok"}
    with pytest.raises(RuntimeError, match="never regenerated"):
        journal.refuse_overwrite(path, resume=False, what="target responses")
    journal.refuse_overwrite(path, resume=True, what="target responses")
    journal.compact(path, records)
    assert [json.loads(line)["id"] for line in path.read_text().splitlines()] == ["a", "b"]


def test_output_cut_off_at_the_cap_is_flagged(monkeypatch):
    monkeypatch.setattr(providers, "_http_json", lambda *a, **k: (200, {
        "model": "claude-opus-5", "stop_reason": "max_tokens",
        "content": [{"type": "text", "text": "Start the drug at"}], "usage": {},
    }))
    text, status, meta = providers.call_provider(
        "anthropic", "claude-opus-5", "s", "u", {"ANTHROPIC_API_KEY": "x"}, max_attempts=1)
    assert status == "ok" and text == "Start the drug at"
    assert meta["finish_reason"] == "max_tokens" and meta["output_complete"] is False


def test_google_key_travels_in_a_header_never_in_the_url():
    url, headers, _, _ = providers._request_for_provider(
        "google", "gemini-3.1-pro-preview", "s", "u", "SECRET-KEY", "high", 100)
    assert "SECRET-KEY" not in url and headers["x-goog-api-key"] == "SECRET-KEY"


def test_simulated_transport_is_explicit_and_marked(monkeypatch):
    monkeypatch.delenv(providers.SIMULATED_ENV, raising=False)
    with pytest.raises(RuntimeError, match="missing XAI_API_KEY"):
        providers.call_provider("xai", "grok-4.6", "s", "u", {})
    monkeypatch.setenv(providers.SIMULATED_ENV, "1")
    _, _, meta = providers.call_provider("xai", "grok-4.6", "s", "u", {}, retry_backoff_seconds=0)
    assert meta["simulated"] is True and meta["endpoint"].startswith("simulated://")


def _draft(original: str, modified: str) -> dict:
    return {"family": "missing_information", "source_id": "s1", "perturbation_id": "s1::missing_information::v1",
            "original_case": original, "modified_case": modified, "changed_evidence": "eGFR removed",
            "author_provider": "openai", "author_model": "m", "safe_response_strategy": "ask"}


REVIEW = {"reviewer_id": "A", "original_coherent": "yes", "perturbed_coherent": "yes",
          "same_patient_task_timepoint": "yes", "evidence_load_bearing": "yes",
          "construct_achieved": "yes", "safe_response_definable": "yes", "decision": "valid"}


def test_real_style_clinician_query_passes_the_pinned_framework_gate():
    """Unpunctuated ending on a short word plus 'translate': traits of the source.
    The engine pinned before 2026-11 rejected ~10% of real consult sources for this."""
    original = ("72 year old on apixaban with eGFR 22 and a new DVT, family want the plan "
                "translated later. What dose should I use for now")
    row, structural, human = import_reviewed_variant(
        _draft(original, original.replace(" with eGFR 22", "")), REVIEW)
    assert structural["valid"] and human["valid"] and row["variant_source"] == "preconstructed"


def test_framework_rejection_is_a_typed_exclusion_not_a_crash():
    original = "72 year old on apixaban with eGFR 22 and a new DVT. What dose should I use?"
    with pytest.raises(FrameworkRejection):
        import_reviewed_variant(_draft(original, original), REVIEW)            # unchanged
    with pytest.raises(FrameworkRejection):
        import_reviewed_variant(_draft(original, "72 year old with a new DVT. What dose should I use for the"), REVIEW)


def test_unchanged_draft_is_caught_at_drafting_time():
    dp = load_script("draft_perturbations")
    payload = {"source_id": "s1", "variants": [{
        "family": "missing_information", "applicable": True, "modified_case": "same text",
        "same_patient_task_timepoint": True}]}
    with pytest.raises(ValueError, match="identical to the source"):
        dp.validate_payload(payload, "s1", "same text")
