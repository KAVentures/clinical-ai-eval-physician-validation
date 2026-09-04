#!/usr/bin/env python3
"""Execute the prespecified secondary/statistical analyses in the SAP.

This complements analyze_judge_validation.py (primary operating characteristics)
and produces human agreement, paired model robustness, McNemar tests, GEE models,
Holm-adjusted target contrasts, judge-family bias, cueing, selective automation,
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


def kappa(x: np.ndarray, y: np.ndarray) -> float:
    if len(x) == 0:
        return float("nan")
    agree = float((x == y).mean())
    px, py = float(x.mean()), float(y.mean())
    pe = px * py + (1 - px) * (1 - py)
    return float((agree - pe) / (1 - pe)) if pe < 1 else float("nan")


def agreement_row(g: pd.DataFrame, dimension: str, value: str) -> dict:
    z = g[
        g["physician_1_unsafe_overconfident"].isin(BINARY)
        & g["physician_2_unsafe_overconfident"].isin(BINARY)
    ].copy()
    if z.empty:
        return {"group_dimension": dimension, "group_value": value, "n": 0}
    a = z["physician_1_unsafe_overconfident"].astype(int).to_numpy()
    b = z["physician_2_unsafe_overconfident"].astype(int).to_numpy()
    return {
        "group_dimension": dimension,
        "group_value": value,
        "n": len(z),
        "percent_agreement": float((a == b).mean()),
        "discordance_rate": float((a != b).mean()),
        "cohen_kappa": kappa(a, b),
    }


def bootstrap_mean(values: np.ndarray, n_boot: int, seed: int) -> tuple[float, float]:
    if len(values) == 0:
        return float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    draws = np.empty(n_boot)
    for i in range(n_boot):
        draws[i] = rng.choice(values, size=len(values), replace=True).mean()
    return tuple(float(x) for x in np.percentile(draws, [2.5, 97.5]))


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
    rows = [agreement_row(ref, "overall", "all")]
    pair = ref["response_reviewer_1"].astype(str) + "+" + ref["response_reviewer_2"].astype(str)
    tmp = ref.assign(reviewer_pair=pair)
    for dim in ["reviewer_pair", "presentation", "primary_family", "target_id",
                "source_type", "source_difficulty", "specialty"]:
        if dim not in tmp:
            continue
        for value, g in tmp.groupby(dim, dropna=False):
            rows.append(agreement_row(g, dim, str(value)))
    pd.DataFrame(rows).to_csv(outdir / "human_human_agreement.csv", index=False)


def target_robustness(ref: pd.DataFrame, outdir: Path, n_boot: int, seed: int) -> None:
    rows = []
    for ei, endpoint in enumerate(ENDPOINTS):
        col = f"{endpoint}_reference"
        if col not in ref:
            continue
        endpoint_rows = []
        for ti, (target, g) in enumerate(ref.groupby("target_id", sort=True)):
            z = g[g[col].isin(BINARY)].copy()
            pivot = z.pivot_table(
                index=["source_id", "case_id", "primary_family"],
                columns="presentation", values=col, aggfunc="first",
            ).reset_index()
            if not {"original", "perturbed"}.issubset(pivot.columns):
                continue
            pivot = pivot.dropna(subset=["original", "perturbed"])
            if pivot.empty:
                continue
            o = pivot["original"].astype(int).to_numpy()
            p = pivot["perturbed"].astype(int).to_numpy()
            delta = p - o
            lo, hi = bootstrap_mean(delta.astype(float), n_boot, seed + ei * 10000 + ti * 101)
            b, c, pval = mcnemar_exact(o, p)
            endpoint_rows.append({
                "endpoint": endpoint,
                "target_id": target,
                "n_paired_cases": len(pivot),
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
                r["mcnemar_holm_p"] = float(padj)
            rows.extend(endpoint_rows)
    pd.DataFrame(rows).to_csv(outdir / "physician_target_robustness.csv", index=False)


def target_pairwise(ref: pd.DataFrame, outdir: Path, n_boot: int, seed: int) -> None:
    z = ref[ref["unsafe_overconfident_reference"].isin(BINARY)].copy()
    z["y"] = z["unsafe_overconfident_reference"].astype(int)
    pivot = z.pivot_table(
        index=["case_id", "target_id"], columns="presentation", values="y", aggfunc="first"
    ).reset_index()
    pivot = pivot.dropna(subset=["original", "perturbed"])
    pivot["delta"] = pivot["perturbed"] - pivot["original"]
    wide = pivot.pivot(index="case_id", columns="target_id", values="delta")
    rows = []
    for i, (a, b) in enumerate(combinations(sorted(wide.columns), 2)):
        pair = wide[[a, b]].dropna()
        diff = (pair[a] - pair[b]).to_numpy(float)
        lo, hi = bootstrap_mean(diff, n_boot, seed + i * 1009)
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
    return pd.DataFrame(rows)


def judge_bias_and_cueing(ref: pd.DataFrame, jdf: pd.DataFrame, cfg: dict, outdir: Path) -> None:
    binary = ref[ref["unsafe_overconfident_reference"].isin(BINARY)].copy()
    binary["reference"] = binary["unsafe_overconfident_reference"].astype(int)
    merged = binary.merge(jdf, on="response_id", how="inner")

    rows = []
    for (jid, jprov, tprov), g in merged.groupby(["judge_id", "judge_provider", "target_provider"]):
        m = metric_counts(g["reference"].to_numpy(), g["label"].to_numpy())
        rows.append({
            "judge_id": jid, "judge_provider": jprov, "target_provider": tprov,
            "same_provider_family": int(jprov == tprov), **m,
        })
    pd.DataFrame(rows).to_csv(outdir / "judge_target_provider_matrix.csv", index=False)

    all_judges = list(cfg.get("primary_judges") or []) + list(cfg.get("secondary_judges") or [])
    blinded = {(j["provider"], j["model"]): j["judge_id"] for j in all_judges if j.get("mode") == "blinded"}
    cue_rows = []
    for j in all_judges:
        if j.get("mode") != "rubric_aware":
            continue
        key = (j["provider"], j["model"])
        if key not in blinded:
            continue
        bid, cid = blinded[key], j["judge_id"]
        b = jdf[jdf["judge_id"] == bid][["response_id", "label"]].rename(columns={"label": "blinded"})
        c = jdf[jdf["judge_id"] == cid][["response_id", "label"]].rename(columns={"label": "cued"})
        g = binary.merge(b, on="response_id").merge(c, on="response_id")
        if g.empty:
            continue
        mb = metric_counts(g["reference"].to_numpy(), g["blinded"].to_numpy())
        mc = metric_counts(g["reference"].to_numpy(), g["cued"].to_numpy())
        cue_rows.append({
            "provider": j["provider"], "model": j["model"],
            "blinded_judge_id": bid, "cued_judge_id": cid, "n": len(g),
            "positive_rate_blinded": float(g["blinded"].mean()),
            "positive_rate_cued": float(g["cued"].mean()),
            "cueing_gap": float(g["cued"].mean() - g["blinded"].mean()),
            "sensitivity_blinded": mb["sensitivity"], "sensitivity_cued": mc["sensitivity"],
            "specificity_blinded": mb["specificity"], "specificity_cued": mc["specificity"],
        })
    pd.DataFrame(cue_rows).to_csv(outdir / "judge_cueing_analysis.csv", index=False)


def selective_automation(ref: pd.DataFrame, jdf: pd.DataFrame, cfg: dict, outdir: Path) -> None:
    binary = ref[ref["unsafe_overconfident_reference"].isin(BINARY)].copy()
    binary["reference"] = binary["unsafe_overconfident_reference"].astype(int)
    primary = [j["judge_id"] for j in cfg.get("primary_judges", [])]
    p = jdf[jdf["judge_id"].isin(primary)].pivot(index="response_id", columns="judge_id", values="label")
    g = binary.merge(p, on="response_id", how="inner").dropna(subset=primary)
    if g.empty:
        pd.DataFrame().to_csv(outdir / "selective_automation.csv", index=False)
        return
    votes = g[primary].astype(int)
    unanimous = (votes.nunique(axis=1) == 1)
    majority = (votes.sum(axis=1) >= 2).astype(int)
    unanimous_pred = (votes.sum(axis=1) == len(primary)).astype(int)
    rows = [{
        "rule": "unanimity_defer",
        "n_reference": len(g),
        "auto_covered": int(unanimous.sum()),
        "coverage": float(unanimous.mean()),
        "deferred": int((~unanimous).sum()),
        "error_among_auto": float((unanimous_pred[unanimous] != g.loc[unanimous, "reference"]).mean())
        if unanimous.any() else np.nan,
    }, {
        "rule": "majority_no_defer",
        "n_reference": len(g),
        "auto_covered": len(g),
        "coverage": 1.0,
        "deferred": 0,
        "error_among_auto": float((majority != g["reference"]).mean()),
    }]
    pd.DataFrame(rows).to_csv(outdir / "selective_automation.csv", index=False)


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

    primary = [j["judge_id"] for j in cfg.get("primary_judges", [])]
    p = jdf[jdf["judge_id"].isin(primary)].pivot(index="response_id", columns="judge_id", values="label")
    g = responses.merge(p, on="response_id", how="inner").dropna(subset=primary)
    if g.empty:
        pd.DataFrame().to_csv(outdir / "automated_full_cohort_model_estimates.csv", index=False)
        return
    g["panel_majority"] = (g[primary].astype(int).sum(axis=1) >= 2).astype(int)
    pivot = g.pivot_table(
        index=["case_id", "target_id"], columns="presentation", values="panel_majority", aggfunc="first"
    ).reset_index().dropna(subset=["original", "perturbed"])
    pivot["delta"] = pivot["perturbed"] - pivot["original"]
    rows = []
    for target, q in pivot.groupby("target_id"):
        rows.append({
            "target_id": target, "n_paired_cases": len(q),
            "automated_panel_majority_original_rate": float(q["original"].mean()),
            "automated_panel_majority_perturbed_rate": float(q["perturbed"].mean()),
            "automated_paired_risk_difference": float(q["delta"].mean()),
            "label": "AUTOMATED_ESTIMATE_NOT_PHYSICIAN_REFERENCE",
        })
    pd.DataFrame(rows).to_csv(outdir / "automated_full_cohort_model_estimates.csv", index=False)


def reference_missingness(ref: pd.DataFrame, outdir: Path) -> None:
    rows = [{
        "endpoint": "unsafe_overconfident",
        "total_cells": len(ref),
        "binary_resolved": int(ref["unsafe_overconfident_reference"].isin(BINARY).sum()),
        "cannot_determine": int((ref["unsafe_overconfident_reference"] == "CANNOT_DETERMINE").sum()),
        "consensus_used": int((ref.get("primary_consensus_used", pd.Series(dtype=str)) == "true").sum()),
    }]
    pd.DataFrame(rows).to_csv(outdir / "physician_reference_missingness.csv", index=False)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--physician-reference", required=True, type=Path)
    p.add_argument("--judge-scores", required=True, type=Path)
    p.add_argument("--target-responses", required=True, type=Path)
    p.add_argument("--models", required=True, type=Path)
    p.add_argument("--out-dir", required=True, type=Path)
    p.add_argument("--bootstrap", type=int, default=10000)
    p.add_argument("--seed", type=int, default=20260903)
    args = p.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    ref = pd.read_csv(args.physician_reference, dtype=str).fillna("")
    cfg = yaml.safe_load(args.models.read_text(encoding="utf-8"))
    jdf = judge_frame(args.judge_scores)

    reference_missingness(ref, args.out_dir)
    human_agreement(ref, args.out_dir)
    target_robustness(ref, args.out_dir, args.bootstrap, args.seed)
    target_pairwise(ref, args.out_dir, args.bootstrap, args.seed + 50000)
    gee_models(ref, args.out_dir)
    judge_bias_and_cueing(ref, jdf, cfg, args.out_dir)
    selective_automation(ref, jdf, cfg, args.out_dir)
    subgroup_summary(ref, args.out_dir)
    target_failures_and_automated(args.target_responses, jdf, cfg, args.out_dir)

    print(f"Wrote full SAP outputs to {args.out_dir}")


if __name__ == "__main__":
    main()
