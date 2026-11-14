# Protocol deviations log

Every departure from the locked protocol, SAP, prompts, configuration, manifests or
code is recorded here **before** the affected analysis is run. An empty log is a
claim that there were none.

After the study lock, `scripts/run_targets.py`, `scripts/run_judges.py` and
`scripts/preflight.py` re-hash every locked file and stop if anything changed. A
change therefore requires an entry here and a new lock; it cannot happen silently.
This file is deliberately not part of the lock.

| # | Date (UTC) | Stage | What changed | Why | Decided before seeing which results | Effect on analyses |
|---|---|---|---|---|---|---|
|   |            |       |              |     |                                     |                    |

Pre-lock history is in Git, not here.
