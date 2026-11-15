#!/usr/bin/env python3
"""Execute the prespecified secondary/statistical analyses in the SAP.

This complements analyze_judge_validation.py (primary operating characteristics)
and produces human agreement, paired model robustness, McNemar tests, GEE models,
Holm-adjusted target contrasts, same-provider judge audit, automated-screen coverage,
subgroup descriptions, target output failures, and all-150 automated estimates.
"""
from __future__ import annotations

import argparse
import json
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from scipy.stats import binomtest, wilcoxon
from statsmodels.genmod.cov_struct import Exchangeable
from statsmodels.genmod.families import Binomial
from statsmodels.genmod.generalized_estimating_equations import GEE
from statsmodels.stats.multitest import multipletests

from study_runtime.stats import cluster_bootstrap_mean, cohen_kappa

BINARY = {"0", "1"}
ENDPOINTS = [
    "unsafe_overconfident",
    "potentially_harmful_treatment",
    "recognizes_information_problem",
    "guideline_concordant_next_step",
    "excessive_abstention",
    "clinically_helpful",
]


def read_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def agreement_row(g: pd.DataFrame, dimension: str, value: str, endpoint: str = "unsafe_overconfident") -> dict:
    """Independent (pre-consensus) agreement where both physicians gave 0 or 1."""
    a_col, b_col = f"physician_1_{endpoint}", f"physician_2_{endpoint}"
    base = {"endpoint": endpoint, "group_dimension": dimension, "group_value": value}
    if a_col not in g or b_col not in g:
        return {**base, "n": 0}
    z = g[g[a_col].isin(BINARY) & g[b_col].isin(BINARY)]
    if z.empty:
        return {**base, "n": 0}
    a = z[a_col].astype(int).to_numpy()
    b = z[b_col].astype(int).to_numpy()
    return {
        **base,
        "n": len(z),
        "percent_agreement": float((a == b).mean()),
        "discordance_rate": float((a != b).mean()),
        "cohen_kappa": cohen_kappa(a, b),
    }


def mcnemar_exact(original: np.ndarray, perturbed: np.ndarray) -> tuple[int, int, float]:
    b = int(((original == 0) & (perturbed == 1)).sum())
    c = int(((original == 1) & (perturbed == 0)).sum())
    n = b + c
    p = float(binomtest(b, n, 0.5, alternative="two-sided").pvalue) if n else 1.0
    return b, c, p


def metric_counts(y: np.ndarray, pred: np.ndarray) -> dict:
    tp = int(((y == 1) & (pred == 1)).sum())
    tn = int(((y == 0) & (pred == 0)).sum())
    fp = int(((y == 0) & (pred == 1)).sum())
    fn = int(((y == 1) & (pred == 0)).sum())
    return {
        "n": len(y), "tp": tp, "tn": tn, "fp": fp, "fn": fn,
        "sensitivity": tp / (tp + fn) if tp + fn else np.nan,
        "specificity": tn / (tn + fp) if tn + fp else np.nan,
        "fpr": fp / (fp + tn) if fp + tn else np.nan,
        "fnr": fn / (fn + tp) if fn + tp else np.nan,
        "agreement": (tp + tn) / len(y) if len(y) else np.nan,
    }


def human_agreement(ref: pd.DataFrame, outdir: Path) -> None:
    pair = ref["response_reviewer_1"].astype(str) + "+" + ref["response_reviewer_2"].astype(str)
    tmp = ref.assign(reviewer_pair=pair)
    rows = []
    for endpoint in ENDPOINTS:
        rows.append(agreement_row(tmp, "overall", "all", endpoint))
        for dim in ["reviewer_pair", "presentation", "primary_family", "target_id",
                    "source_type", "source_difficulty", "specialty"]:
            if dim not in tmp:
                continue
            for value, g in tmp.groupby(dim, dropna=False):
                rows.append(agreement_row(g, dim, str(value), endpoint))
    pd.DataFrame(rows).to_csv(outdir / "human_human_agreement.csv", index=False)


def _paired(z: pd.DataFrame, col: str) -> pd.DataFrame:
    pivot = z.pivot_table(
        index=["source_id", "case_id", "primary_family"],
        columns="presentation", values=col, aggfunc="first",
    ).reset_index()
    if not {"original", "perturbed"}.issubset(pivot.columns):
        return pivot.iloc[0:0]
    return pivot.dropna(subset=["original", "perturbed"])


def target_robustness(ref: pd.DataFrame, outdir: Path, n_boot: int, seed: int,
                      suffix: str = "_reference", out_name: str = "physician_target_robustness.csv") -> None:
    """Paired original-vs-perturbed change per target and endpoint, overall and
    within each perturbation family (SAP sections 9 and 12)."""
    rows = []
    for ei, endpoint in enumerate(ENDPOINTS):
        col = f"{endpoint}{suffix}"
        if col not in ref:
            continue
        for scope in ["all", *sorted(ref["primary_family"].unique())]:
            scoped = ref if scope == "all" else ref[ref["primary_family"] == scope]
            endpoint_rows = []
            for ti, (target, g) in enumerate(scoped.groupby("target_id", sort=True)):
                pivot = _paired(g[g[col].isin(BINARY)], col)
                if pivot.empty:
                    continue
                o = pivot["original"].astype(int).to_numpy()
                p = pivot["perturbed"].astype(int).to_numpy()
                delta = p - o
                lo, hi = cluster_bootstrap_mean(
                    pivot["source_id"], delta, n_boot,
                    seed + ei * 10000 + ti * 101 + (0 if scope == "all" else 7 + len(scope)),
                )
                b, c, pval = mcnemar_exact(o, p)
                endpoint_rows.append({
                    "endpoint": endpoint,
                    "primary_family": scope,
                    "target_id": target,
                    "n_paired_cases": len(pivot),
                    "n_cases_without_a_resolved_pair": int(g["source_id"].nunique() - len(pivot)),
                    "original_rate": float(o.mean()),
                    "perturbed_rate": float(p.mean()),
                    "paired_risk_difference": float(delta.mean()),
                    "ci_low": lo, "ci_high": hi,
                    "transition_0_to_1": b,
                    "transition_1_to_0": c,
                    "mcnemar_exact_p": pval,
                })
            if endpoint_rows:
                pvals = [r["mcnemar_exact_p"] for r in endpoint_rows]
                adjusted = multipletests(pvals, method="holm")[1]
                for r, padj in zip(endpoint_rows, adjusted):
                    # Holm across the four targets, within endpoint and family scope.
                    r["mcnemar_holm_p"] = float(padj)
                rows.extend(endpoint_rows)
    pd.DataFrame(rows).to_csv(outdir / out_name, index=False)


def target_arm_rates(ref: pd.DataFrame, outdir: Path, n_boot: int, seed: int) -> None:
    """Unpaired rate of every endpoint per target and presentation.

    Needed because some endpoints have no paired contrast by design:
    `recognizes_information_problem` is NA on an original case that has no
    information problem, so it can only be reported on the perturbed arm."""
    rows = []
    for ei, endpoint in enumerate(ENDPOINTS):
        col = f"{endpoint}_reference"
        if col not in ref:
            continue
        keys = ["target_id", "presentation"]
        for gi, (key, g) in enumerate(ref.groupby(keys, sort=True)):
            z = g[g[col].isin(BINARY)]
            y = z[col].astype(int).to_numpy()
            lo, hi = cluster_bootstrap_mean(z["source_id"], y, n_boot, seed + 90000 + ei * 1000 + gi)
            rows.append({
                "endpoint": endpoint, "target_id": key[0], "presentation": key[1],
                "cells": len(g), "binary_resolved": len(z), "unresolved": len(g) - len(z),
                "rate": float(y.mean()) if len(y) else np.nan, "ci_low": lo, "ci_high": hi,
            })
    pd.DataFrame(rows).to_csv(outdir / "physician_target_arm_rates.csv", index=False)


def target_pairwise(ref: pd.DataFrame, outdir: Path, n_boot: int, seed: int) -> None:
    z = ref[ref["unsafe_overconfident_reference"].isin(BINARY)].copy()
    z["y"] = z["unsafe_overconfident_reference"].astype(int)
    pivot = z.pivot_table(
        index=["source_id", "target_id"], columns="presentation", values="y", aggfunc="first"
    ).reset_index()
    pivot = pivot.dropna(subset=["original", "perturbed"])
    pivot["delta"] = pivot["perturbed"] - pivot["original"]
    wide = pivot.pivot(index="source_id", columns="target_id", values="delta")
    rows = []
    for i, (a, b) in enumerate(combinations(sorted(wide.columns), 2)):
        pair = wide[[a, b]].dropna()
        diff = (pair[a] - pair[b]).to_numpy(float)
        lo, hi = cluster_bootstrap_mean(pair.index.to_numpy(), diff, n_boot, seed + i * 1009)
        if len(diff) == 0 or np.all(diff == 0):
            pval = 1.0
        else:
            try:
                pval = float(wilcoxon(diff, zero_method="pratt", alternative="two-sided").pvalue)
            except ValueError:
                pval = 1.0
        rows.append({
            "target_a": a, "target_b": b, "n_shared_cases": len(diff),
            "difference_in_perturbation_risk_difference_a_minus_b": float(diff.mean()) if len(diff) else np.nan,
            "ci_low": lo, "ci_high": hi, "wilcoxon_p": pval,
        })
    if rows:
        adjusted = multipletests([r["wilcoxon_p"] for r in rows], method="holm")[1]
        for r, padj in zip(rows, adjusted):
            r["holm_p"] = float(padj)
    pd.DataFrame(rows).to_csv(outdir / "physician_target_pairwise_contrasts.csv", index=False)


def gee_models(ref: pd.DataFrame, outdir: Path) -> None:
    z = ref[ref["unsafe_overconfident_reference"].isin(BINARY)].copy()
    z["y"] = z["unsafe_overconfident_reference"].astype(int)
    formulas = {
        "primary": "y ~ C(target_id) * C(presentation) + C(primary_family)",
        "family_interaction": "y ~ C(target_id) * C(presentation) * C(primary_family)",
    }
    rows, errors = [], []
    for name, formula in formulas.items():
        try:
            model = GEE.from_formula(
                formula, groups="source_id", data=z, family=Binomial(), cov_struct=Exchangeable()
            )
            fit = model.fit()
            ci = fit.conf_int()
            for term in fit.params.index:
                rows.append({
                    "model": name, "formula": formula, "term": term,
                    "estimate_log_odds": float(fit.params[term]),
                    "std_error": float(fit.bse[term]),
                    "p_value": float(fit.pvalues[term]),
                    "ci_low": float(ci.loc[term, 0]),
                    "ci_high": float(ci.loc[term, 1]),
                    "n_observations": int(fit.nobs),
                    "n_source_clusters": int(z["source_id"].nunique()),
                })
        except Exception as exc:
            errors.append({"model": name, "formula": formula, "error": repr(exc)})
    pd.DataFrame(rows).to_csv(outdir / "gee_models.csv", index=False)
    if errors:
        (outdir / "gee_errors.json").write_text(json.dumps(errors, indent=2), encoding="utf-8")


def judge_frame(path: Path) -> pd.DataFrame:
    rows = []
    for r in read_jsonl(path):
        score = r.get("score") or {}
        value = score.get("unsafe_overconfident")
        if r.get("status") == "ok" and value in (0, 1, False, True):
            rows.append({
                "response_id": str(r["response_id"]),
                "judge_id": str(r["judge_id"]),
                "judge_provider": str(r["judge_provider"]),
                "judge_model": str(r["judge_model"]),
                "judge_mode": str(r["judge_mode"]),
                "label": int(value),
            })
    return pd.DataFrame(
        rows,
        columns=["response_id", "judge_id", "judge_provider", "judge_model", "judge_mode", "label"],
    )


def judge_frame_empty() -> pd.DataFrame:
    return pd.DataFrame(
        columns=["response_id", "judge_id", "judge_provider", "judge_model", "judge_mode", "label"])


def judge_provider_audit(ref: pd.DataFrame, jdf: pd.DataFrame, outdir: Path) -> None:
    """Audit the only provider-bias question relevant to this study: Grok judging Grok."""
    binary = ref[ref["unsafe_overconfident_reference"].isin(BINARY)].copy()
    binary["reference"] = binary["unsafe_overconfident_reference"].astype(int)
    merged = binary.merge(jdf, on="response_id", how="inner")

    rows = []
    for (jid, jprov, tprov), g in merged.groupby(["judge_id", "judge_provider", "target_provider"]):
        m = metric_counts(g["reference"].to_numpy(), g["label"].to_numpy())
        rows.append({
            "judge_id": jid,
            "judge_provider": jprov,
            "target_provider": tprov,
            "same_provider_target_judge": int(jprov == tprov),
            **m,
        })
    pd.DataFrame(rows).to_csv(outdir / "judge_target_provider_audit.csv", index=False)

    if not merged.empty:
        summary = []
        for same, g in merged.groupby(merged["judge_provider"] == merged["target_provider"]):
            m = metric_counts(g["reference"].to_numpy(), g["label"].to_numpy())
            summary.append({
                "same_provider_target_judge": int(bool(same)),
                **m,
            })
        pd.DataFrame(summary).to_csv(outdir / "same_provider_judge_summary.csv", index=False)


def automated_screen_operating_point(ref: pd.DataFrame, jdf: pd.DataFrame, outdir: Path) -> None:
    """Describe usable automated coverage without inventing confidence-based defer rules."""
    binary = ref[ref["unsafe_overconfident_reference"].isin(BINARY)].copy()
    binary["reference"] = binary["unsafe_overconfident_reference"].astype(int)
    g = binary.merge(jdf[["response_id", "label"]], on="response_id", how="left")
    available = g["label"].notna()
    if available.any():
        m = metric_counts(
            g.loc[available, "reference"].to_numpy(),
            g.loc[available, "label"].astype(int).to_numpy(),
        )
        error = float((g.loc[available, "reference"].astype(int) != g.loc[available, "label"].astype(int)).mean())
    else:
        m = metric_counts(np.array([], dtype=int), np.array([], dtype=int))
        error = np.nan
    rows = [{
        "rule": "single_prespecified_judge_no_confidence_defer",
        "n_binary_physician_reference": len(g),
        "automated_measurements_available": int(available.sum()),
        "coverage": float(available.mean()) if len(g) else np.nan,
        "missing_or_failed_judge_measurements": int((~available).sum()),
        "error_among_available": error,
        "sensitivity": m["sensitivity"],
        "specificity": m["specificity"],
        "note": "No post-hoc judge-confidence threshold is used; failure boundaries are reported from physician comparison.",
    }]
    pd.DataFrame(rows).to_csv(outdir / "automated_screen_operating_point.csv", index=False)

def subgroup_summary(ref: pd.DataFrame, outdir: Path) -> None:
    z = ref[ref["unsafe_overconfident_reference"].isin(BINARY)].copy()
    z["y"] = z["unsafe_overconfident_reference"].astype(int)
    rows = []
    for dim in ["presentation", "primary_family", "target_id", "source_type", "source_difficulty", "specialty"]:
        if dim not in z:
            continue
        for value, g in z.groupby(dim, dropna=False):
            rows.append({
                "dimension": dim, "value": str(value), "n": len(g),
                "unsafe_overconfident_rate": float(g["y"].mean()),
                "n_source_cases": int(g["source_id"].nunique()),
            })
    pd.DataFrame(rows).to_csv(outdir / "physician_subgroup_descriptives.csv", index=False)


def target_failures_and_automated(responses_path: Path, jdf: pd.DataFrame, cfg: dict, outdir: Path) -> None:
    responses = pd.DataFrame(read_jsonl(responses_path))
    fail = responses.groupby(["target_id", "status"], dropna=False).size().reset_index(name="n")
    totals = responses.groupby("target_id").size().rename("target_total").reset_index()
    fail = fail.merge(totals, on="target_id")
    fail["rate"] = fail["n"] / fail["target_total"]
    fail.to_csv(outdir / "target_output_status.csv", index=False)

    # A response with text that did not finish normally (output cap, refusal) is
    # still the model's output and stays in every analysis; it is counted here.
    meta = responses["provider_meta"].apply(lambda m: m or {})
    responses["finish_reason"] = meta.apply(lambda m: str(m.get("finish_reason", "")))
    responses["output_complete"] = meta.apply(lambda m: bool(m.get("output_complete", True)))
    (responses[responses["status"] == "ok"]
     .groupby(["target_id", "output_complete", "finish_reason"], dropna=False).size()
     .reset_index(name="n").to_csv(outdir / "target_output_completeness.csv", index=False))
    if jdf.empty:
        return

    # Automated model estimates are deliberately limited to the 60-source
    # physician-reference cohort; the other 90 construct-valid sources are not sent
    # to target APIs in the primary study.
    g = responses.merge(jdf[["response_id", "label"]], on="response_id", how="inner")
    if g.empty:
        pd.DataFrame().to_csv(outdir / "automated_calibration_cohort_target_estimates.csv", index=False)
        return
    pivot = g.pivot_table(
        index=["case_id", "target_id"], columns="presentation", values="label", aggfunc="first"
    ).reset_index().dropna(subset=["original", "perturbed"])
    pivot["delta"] = pivot["perturbed"] - pivot["original"]
    rows = []
    for target, q in pivot.groupby("target_id"):
        rows.append({
            "target_id": target,
            "n_paired_cases": len(q),
            "automated_judge_original_rate": float(q["original"].mean()),
            "automated_judge_perturbed_rate": float(q["perturbed"].mean()),
            "automated_paired_risk_difference": float(q["delta"].mean()),
            "label": "AUTOMATED_ESTIMATE_ON_PHYSICIAN_CALIBRATION_COHORT_NOT_HUMAN_TRUTH",
        })
    pd.DataFrame(rows).to_csv(outdir / "automated_calibration_cohort_target_estimates.csv", index=False)

def reference_missingness(ref: pd.DataFrame, outdir: Path) -> None:
    """Exact denominators for every endpoint, split by reason. Every endpoint is
    resolved by the same locked consensus; NA is a legitimate secondary value
    (e.g. no information problem exists on an original case)."""
    rows = []
    for endpoint in ENDPOINTS:
        col = f"{endpoint}_reference"
        if col not in ref:
            continue
        a, b = ref.get(f"physician_1_{endpoint}"), ref.get(f"physician_2_{endpoint}")
        row = {
            "endpoint": endpoint,
            "total_cells": len(ref),
            "binary_resolved": int(ref[col].isin(BINARY).sum()),
            "not_applicable": int((ref[col] == "NA").sum()),
            "cannot_determine": int((ref[col] == "CANNOT_DETERMINE").sum()),
            "unresolved_other": int((~ref[col].isin(BINARY | {"CANNOT_DETERMINE", "NA"})).sum()),
            "consensus_used": int((ref.get(f"{endpoint}_consensus_used", pd.Series(dtype=str)) == "true").sum()),
        }
        agreement_only = ref.get(f"{endpoint}_reference_agreement_only")
        if agreement_only is not None:
            row["binary_resolved_by_agreement_alone"] = int(agreement_only.isin(BINARY).sum())
        if a is not None and b is not None:
            both = a.isin(BINARY) & b.isin(BINARY)
            row["independent_both_binary"] = int(both.sum())
            row["independent_discordant"] = int((both & (a != b)).sum())
            row["independent_either_na"] = int(((a == "NA") | (b == "NA")).sum())
            row["independent_either_cannot_determine"] = int(
                ((a == "CANNOT_DETERMINE") | (b == "CANNOT_DETERMINE")).sum())
        if "target_status" in ref:
            row["cells_with_no_model_output"] = int((ref["target_status"] == "model_output_failure").sum())
        rows.append(row)
    pd.DataFrame(rows).to_csv(outdir / "physician_reference_missingness.csv", index=False)


def judge_status(path: Path, outdir: Path) -> bool:
    """Every judge attempt by outcome (SAP section 6). Returns True if simulated."""
    records = read_jsonl(path)
    counts: dict[str, int] = {}
    for r in records:
        counts[str(r.get("status"))] = counts.get(str(r.get("status")), 0) + 1
    pd.DataFrame(
        [{"judge_status": k, "n": v, "share": v / len(records)} for k, v in sorted(counts.items())]
    ).to_csv(outdir / "judge_measurement_status.csv", index=False)
    return any((r.get("provider_meta") or {}).get("simulated") for r in records)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--physician-reference", required=True, type=Path)
    p.add_argument("--judge-scores", type=Path,
                   help="Omit for the external cohort, which has no automated scoring")
    p.add_argument("--target-responses", required=True, type=Path)
    p.add_argument("--models", required=True, type=Path)
    p.add_argument("--out-dir", required=True, type=Path)
    p.add_argument("--bootstrap", type=int, default=10000)
    p.add_argument("--seed", type=int, default=20260903)
    args = p.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    ref = pd.read_csv(args.physician_reference, dtype=str, keep_default_na=False)
    cfg = yaml.safe_load(args.models.read_text(encoding="utf-8"))
    simulated = any(
        (r.get("provider_meta") or {}).get("simulated") for r in read_jsonl(args.target_responses))
    reference_missingness(ref, args.out_dir)
    human_agreement(ref, args.out_dir)
    target_robustness(ref, args.out_dir, args.bootstrap, args.seed)
    if "unsafe_overconfident_reference_agreement_only" in ref:
        # Prespecified sensitivity analysis: the same estimands using only labels
        # the two physicians agreed on independently, before any discussion.
        target_robustness(ref, args.out_dir, args.bootstrap, args.seed + 70000,
                          suffix="_reference_agreement_only",
                          out_name="physician_target_robustness_agreement_only.csv")
    target_arm_rates(ref, args.out_dir, args.bootstrap, args.seed)
    target_pairwise(ref, args.out_dir, args.bootstrap, args.seed + 50000)
    gee_models(ref, args.out_dir)
    subgroup_summary(ref, args.out_dir)
    if args.judge_scores is not None:
        jdf = judge_frame(args.judge_scores)
        simulated = judge_status(args.judge_scores, args.out_dir) or simulated
        judge_provider_audit(ref, jdf, args.out_dir)
        automated_screen_operating_point(ref, jdf, args.out_dir)
    else:
        jdf = judge_frame_empty()
    target_failures_and_automated(args.target_responses, jdf, cfg, args.out_dir)
    marker = args.out_dir / "SIMULATED_REHEARSAL_NOT_RESULTS.txt"
    if simulated:
        marker.write_text(
            "These files come from simulated provider calls. They are not study results." + chr(10),
            encoding="utf-8")
    elif marker.exists():
        marker.unlink()
    print(f"Wrote full SAP outputs to {args.out_dir}" + ("  [SIMULATED REHEARSAL DATA]" if simulated else ""))


if __name__ == "__main__":
    main()
