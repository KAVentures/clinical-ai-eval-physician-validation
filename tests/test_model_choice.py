"""Choosing models is a config change: these pin that contract down."""
from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from study_runtime import providers
from study_runtime.panel import load_panel, validate_panel

ROOT = Path(__file__).resolve().parents[1]
PANEL = load_panel(ROOT / "configs" / "model_panel.yaml")


def test_shipped_panel_is_valid():
    errors, _ = validate_panel(PANEL)
    assert errors == []


def test_a_provider_defined_in_yaml_is_called_with_the_openai_compatible_shape(monkeypatch):
    cfg = {"providers": {"local": {"api": "openai_chat_completions", "base_url": "http://localhost:8000/v1/",
                                   "api_key_env": None, "effort_param": None}}}
    registry = providers.provider_registry(cfg)
    seen = {}

    def fake(url, headers, payload, timeout):
        seen.update(url=url, headers=headers, payload=payload)
        return 200, {"model": "org/open-model-7b", "usage": {},
                     "choices": [{"message": {"content": "answer"}, "finish_reason": "length"}]}

    monkeypatch.setattr(providers, "_http_json", fake)
    text, status, meta = providers.call_provider("local", "org/open-model-7b", "sys", "user", {},
                                                 registry=registry, max_attempts=1)
    assert (text, status) == ("answer", "ok")
    assert seen["url"] == "http://localhost:8000/v1/chat/completions"
    assert "Authorization" not in seen["headers"]                 # keyless local server
    assert seen["payload"]["messages"][0] == {"role": "system", "content": "sys"}
    assert "reasoning_effort" not in seen["payload"]
    assert meta["finish_reason"] == "length" and meta["output_complete"] is False
    with pytest.raises(ValueError, match="effort_param"):
        providers.call_provider("local", "m", "s", "u", {}, registry=registry, reasoning_effort="high")


def test_builtin_can_be_redirected_without_code(monkeypatch):
    registry = providers.provider_registry({"providers": {"anthropic": {"base_url": "https://gw.example.org/a/v1"}}})
    url, headers, payload, _ = providers._request_for_provider(
        "anthropic", "claude-opus-5-5", "s", "u", "k", "high", 100, registry)
    assert url == "https://gw.example.org/a/v1/messages" and headers["x-api-key"] == "k"
    assert payload["thinking"] == {"type": "adaptive"} and payload["output_config"] == {"effort": "high"}
    assert "fallbacks" not in payload and "temperature" not in payload


def test_effort_is_checked_per_api_style():
    with pytest.raises(ValueError, match="not supported"):
        providers._request_for_provider("google", "gemini-x", "s", "u", "k", "xhigh", 100)
    providers._request_for_provider("anthropic", "claude-opus-5-5", "s", "u", "k", "max", 100)
    with pytest.raises(ValueError):
        providers._request_for_provider("openai", "gpt-x", "s", "u", "k", "max", 100)


def test_refusal_is_the_configured_models_outcome_not_a_fallback(monkeypatch):
    monkeypatch.setattr(providers, "_http_json", lambda *a: (200, {
        "model": "claude-opus-5-5", "content": [], "stop_reason": "refusal",
        "stop_details": {"type": "refusal", "category": "bio"}, "usage": {}}))
    text, status, meta = providers.call_provider(
        "anthropic", "claude-opus-5-5", "s", "u", {"ANTHROPIC_API_KEY": "x"}, max_attempts=1)
    assert status == "model_output_failure" and text == ""
    assert meta["refusal"]["category"] == "bio" and "declined" in meta["error_detail"]


def test_a_substituted_model_is_flagged():
    assert providers.model_matches("gpt-5.6-sol", "gpt-5.6-sol-2026-09-01")
    assert providers.model_matches("gemini-3.1-pro-preview", "models/gemini-3.1-pro-preview")
    assert not providers.model_matches("claude-opus-5-5", "claude-opus-4-8")


def test_validator_catches_the_mistakes_people_make():
    def errors(mutate):
        cfg = copy.deepcopy(PANEL)
        mutate(cfg)
        return " | ".join(validate_panel(cfg)[0])

    assert "unknown provider" in errors(lambda c: c["target_models"][0].update(provider="opnai"))
    assert "not valid" in errors(lambda c: c["target_models"][2].update(reasoning_effort="xhigh"))
    assert "vendors repeat" in errors(lambda c: c["target_models"][1].update(provider="openai", model="gpt-x"))
    assert "target_count" in errors(lambda c: c["target_models"].pop())
    assert "blinded" in errors(lambda c: c["primary_judges"][0].update(mode="rubric_aware"))
    assert "api must be one of" in errors(lambda c: c.update(providers={"p": {"api": "soap", "base_url": "https://x"}}))
    assert "unique target_id" in errors(lambda c: c["target_models"][1].update(target_id=c["target_models"][0]["target_id"]))
    # an aggregator is fine as long as each model names its developer
    def via_aggregator(c):
        c["providers"] = {"agg": {"api": "openai_chat_completions", "base_url": "https://agg.example/v1",
                                  "api_key_env": "AGG_KEY"}}
        c["target_models"][0].update(provider="agg", vendor="openai")
        c["target_models"][1].update(provider="agg", vendor="anthropic")
    assert errors(via_aggregator) == ""


def test_validate_panel_script_runs_offline():
    r = subprocess.run([sys.executable, "scripts/validate_panel.py"], cwd=ROOT, capture_output=True, text=True,
                       env={"PATH": "/usr/bin:/bin", "PYTHONPATH": str(ROOT)})
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Panel is valid" in r.stdout


def _judge_units(tmp_path: Path) -> Path:
    unit = {"review_unit_id": "cal-x", "case_text": "c", "response_text": "Definitive plan: x",
            "response_id_internal": "r1", "case_id_internal": "c1", "source_id_internal": "s1",
            "presentation_internal": "perturbed", "primary_family_internal": "missing_information",
            "target_id_internal": "t1", "target_provider_internal": "openai", "target_status_internal": "ok"}
    path = tmp_path / "units.jsonl"
    path.write_text(json.dumps(unit) + "\n")
    return path


def test_judge_reasks_only_unparseable_output(tmp_path, monkeypatch):
    """Load run_judges in-process and feed it: unparseable, then valid, then a
    second valid answer that must never be requested."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("run_judges", ROOT / "scripts" / "run_judges.py")
    rj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rj)
    answers = iter([
        "I think it is unsafe.",
        json.dumps({"unsafe_overconfident": 1, "correct_abstention": 0, "asks_for_missing_info": 0,
                    "identifies_removed_evidence": 0, "potentially_harmful_treatment": 1,
                    "guideline_concordant_next_step": 0, "excessive_abstention": 0,
                    "confidence_level": "high", "rationale_short": "", "quote_support": ""}),
        "SHOULD NEVER BE REQUESTED",
    ])
    calls = []

    def fake_call(*a, **k):
        calls.append(1)
        return next(answers), "ok", {"simulated": True}

    monkeypatch.setattr(rj, "call_provider", fake_call)
    monkeypatch.setattr(rj, "require_lock", lambda *a, **k: {})
    cfg = yaml.safe_load((ROOT / "configs" / "model_panel.yaml").read_text())
    cfg.update(frozen=True, authoring_frozen=True)
    cfg["automated_judge_selection"]["expected_primary_cells"] = 1
    panel = tmp_path / "panel.yaml"
    panel.write_text(yaml.safe_dump(cfg))
    monkeypatch.setattr(sys, "argv", ["run_judges", "--units", str(_judge_units(tmp_path)), "--models", str(panel),
                                      "--vault", str(tmp_path / "v"), "--public-manifest", str(tmp_path / "m.csv")])
    rj.main()
    rec = json.loads((tmp_path / "v" / "judges" / "judge_scores.private.jsonl").read_text())
    assert len(calls) == 2
    assert rec["status"] == "ok" and rec["score"]["unsafe_overconfident"] == 1
    assert [a["status"] for a in rec["provider_meta"]["format_attempts"]] == ["judge_parse_failure", "ok"]
