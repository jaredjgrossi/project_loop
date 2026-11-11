"""Load secrets from .env (git-ignored; decision 025): the Claude API key and the Loop token.

Looks in the repo root, then, when running from a Claude Code worktree (.claude/worktrees/<name>), in the main
checkout's root. Variables already set in the environment win. Values are never printed or logged.
"""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _candidates() -> list[Path]:
    out = [ROOT / ".env"]
    if ROOT.parent.name == "worktrees" and ROOT.parents[1].name == ".claude":
        out.append(ROOT.parents[2] / ".env")
    return out


def load_env() -> Path | None:
    """Set variables from the first .env found; returns its path, or None."""
    for path in _candidates():
        if path.is_file():
            for line in path.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key, value = key.strip().removeprefix("export ").strip(), value.strip().strip("'\"")
                if key and key not in os.environ:
                    os.environ[key] = value
            return path
    return None
