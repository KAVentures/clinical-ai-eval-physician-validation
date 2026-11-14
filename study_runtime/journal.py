"""Crash-safe record files for paid, slow, non-repeatable API runs.

Each completed call is appended and fsynced before the next call starts, so an
interrupted run loses at most the call in flight. On load the last record for a
key wins, which is how a retried failure replaces its earlier attempt. A finished
run is compacted to one sorted record per key via an atomic replace.
"""
from __future__ import annotations

import json
import os
from pathlib import Path


def load_latest(path: Path, key: str) -> dict[str, dict]:
    records: dict[str, dict] = {}
    if not path.exists():
        return records
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                # A torn final line from a killed process: that call simply reruns.
                continue
            records[str(row[key])] = row
    return records


def append_record(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())


def compact(path: Path, records: dict[str, dict]) -> None:
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for key in sorted(records):
            f.write(json.dumps(records[key], ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def refuse_overwrite(path: Path, resume: bool, what: str) -> None:
    if path.exists() and path.stat().st_size > 0 and not resume:
        raise RuntimeError(
            f"{path} already holds {what}. Frozen outputs are never regenerated "
            "implicitly: pass --resume to continue this run, or move the file aside "
            "yourself if you really mean to start again."
        )
