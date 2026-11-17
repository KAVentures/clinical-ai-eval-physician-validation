# Sample-size and precision justification

## Primary measurement-validity sample

The primary physician calibration cohort contains 60 source cases. Each source is represented by original and perturbed responses from four target models, producing 480 unique response cells. Each response cell receives two independent cross-fitted physician ratings, but the statistical unit of dependence remains the **source case**, not the individual rating.

The study is designed primarily for **precision of judge operating-characteristic estimates**, not for a binary superiority claim between target models.

## Prespecified simulation

The repository contains `analysis/precision_simulation.py`. It simulates:

- 60 source clusters;
- 8 response cells per source;
- reference prevalences of 15%, 25%, and 40%;
- judge sensitivity and specificity of 0.80;
- source-level heterogeneity in both the reference endpoint and judge error;
- source-cluster nonparametric bootstrap confidence intervals.

A deterministic implementation check using 300 simulated studies and 300 cluster-bootstrap replicates per study (base seed 20260904) produced:

| Reference prevalence | Median positive cells | Median sensitivity 95% CI half-width | 90th percentile sensitivity half-width | Median specificity half-width |
|---:|---:|---:|---:|---:|
| 15% | 84.5 | 0.085 | 0.104 | 0.039 |
| 25% | 131 | 0.069 | 0.083 | 0.041 |
| 40% | 198 | 0.056 | 0.067 | 0.046 |

These numbers are design simulations, not study results.

## Interpretation

The 60-source design is retained because it is expected to estimate sensitivity to roughly ±0.09 under a relatively low 15% endpoint prevalence and more tightly at higher prevalence, while keeping the physician workload feasible.

No minimum sensitivity threshold is declared after seeing data. If the realized number of physician-reference positive cells is substantially below the simulated low-prevalence scenario, sensitivity will be reported with its wider confidence interval and the paper will explicitly state that the study was under-informative for a precise sensitivity estimate.

The simulation must be rerun from the locked study commit before primary execution and its CSV retained with the study provenance package. Changing the source-case count after inspecting model or judge outcomes is prohibited.
