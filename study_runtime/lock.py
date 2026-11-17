"""The study lock, and its enforcement.

`freeze_study.py` writes the lock before the first primary target call. From then
on the scripts that produce or analyse study data call `require_lock`, which
recomputes every locked hash. A protocol, prompt, configuration, manifest or code
file that changed after lock stops the run with the list of what changed, so a
deviation is a visible decision and cannot happen by accident.
"""
from __future__ import annotations

import hashlib
import json
import re
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Everything that determines what the study does. Hashed in addition to the
# documents, prompts and manifests named in freeze_study.py.
CODE_GLOBS = ("scripts/*.py", "study_runtime/*.py", "analysis/*.py", "pyproject.toml", "requirements.txt")


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def code_files(root: Path = ROOT) -> list[str]:
    out: list[str] = []
    for pattern in CODE_GLOBS:
        out.extend(sorted(str(p.relative_to(root)) for p in root.glob(pattern)))
    return out


def pinned_engine_commit(root: Path = ROOT) -> str:
    m = re.search(r"Commit:\s*.([0-9a-f]{40}).", (root / "ENGINE_PIN.md").read_text(encoding="utf-8"))
    if not m:
        raise RuntimeError("ENGINE_PIN.md does not contain a full engine commit SHA")
    return m.group(1)


def installed_engine_commit() -> str | None:
    """The git commit pip recorded for the installed engine, or None when it was
    installed from a local directory (which carries no verifiable commit)."""
    try:
        raw = metadata.distribution("clinical-ai-eval").read_text("direct_url.json")
    except metadata.PackageNotFoundError:
        return None
    if not raw:
        return None
    return (json.loads(raw).get("vcs_info") or {}).get("commit_id")


def lock_problems(lock_path: Path, root: Path = ROOT) -> list[str]:
    if not Path(lock_path).exists():
        return [f"study lock not found: {lock_path}"]
    lock = json.loads(Path(lock_path).read_text(encoding="utf-8"))
    problems: list[str] = []
    for label, expected in sorted(lock.get("files_sha256", {}).items()):
        path = Path(lock.get("resolved_paths", {}).get(label, label))
        if not path.is_absolute():
            path = root / path
        if not path.exists():
            problems.append(f"locked file is missing: {label}")
        elif sha_file(path) != expected:
            problems.append(f"changed since lock: {label}")
    for label in code_files(root):
        if label not in lock.get("files_sha256", {}):
            problems.append(f"code file not covered by the lock (added after lock?): {label}")
    if lock.get("engine_git_commit") != pinned_engine_commit(root):
        problems.append("ENGINE_PIN.md no longer names the locked engine commit")
    if not lock.get("rehearsal"):
        installed = installed_engine_commit()
        if installed != lock.get("engine_git_commit"):
            problems.append(
                f"installed clinical-ai-eval is {installed or 'a local/unversioned install'}, "
                f"not the locked engine commit {lock.get('engine_git_commit')}"
            )
    return problems


def require_lock(lock_path: Path, *, allow_rehearsal: bool = False, root: Path = ROOT) -> dict:
    problems = lock_problems(lock_path, root)
    if problems:
        raise RuntimeError(
            "STUDY LOCK VIOLATION. Nothing was run.\n  - " + "\n  - ".join(problems)
            + "\nIf a change is intended, record it in protocol/DEVIATIONS.md and create a new lock."
        )
    lock = json.loads(Path(lock_path).read_text(encoding="utf-8"))
    if lock.get("rehearsal") and not allow_rehearsal:
        raise RuntimeError(f"{lock_path} is a rehearsal lock, not a study lock")
    return lock
