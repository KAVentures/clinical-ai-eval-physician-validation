"""The prospective study must install exactly the framework version it cites."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
COMMIT = re.compile(r"(?<![a-f0-9])[a-f0-9]{40}(?![a-f0-9])")


def test_framework_pin_agrees_across_install_and_protocol():
    texts = {path: (ROOT / path).read_text(encoding="utf-8")
             for path in ("ENGINE_PIN.md", "pyproject.toml", "requirements.txt")}
    extracted = {}
    for path, text in texts.items():
        if path == "ENGINE_PIN.md":
            match = re.search(r"- Commit: `([a-f0-9]{40})`", text)
        else:
            match = re.search(
                r"clinical-ai-eval\.git@([a-f0-9]{40})", text)
        assert match, f"{path} has no 40-character engine commit pin"
        extracted[path] = match.group(1)
    assert len(set(extracted.values())) == 1, extracted
    # Source-level changes after lock must be treated as protocol deviations,
    # not silently installed through a floating main branch.
    assert "git@main" not in texts["pyproject.toml"]
    assert "git@main" not in texts["requirements.txt"]
