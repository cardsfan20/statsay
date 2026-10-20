"""Readers for the base revision in diff mode: another directory or a Git revision."""

from __future__ import annotations

import subprocess
from pathlib import Path

from statsay import StatsayError
from statsay.adapters import Reader
from statsay.config import Config


def _relative(config: Config, path: Path) -> Path:
    try:
        return path.relative_to(config.root)
    except ValueError:
        raise StatsayError(f"diff mode needs files inside the config directory: {path}") from None


def directory_reader(config: Config, base_dir: Path) -> Reader:
    """Read each file from the same relative path under `base_dir`."""
    base_dir = Path(base_dir)
    if not base_dir.is_dir():
        raise StatsayError(f"base directory not found: {base_dir}")

    def read(path: Path) -> str:
        return (base_dir / _relative(config, path)).read_text(encoding="utf-8")

    return read


def git_reader(config: Config, revision: str) -> Reader:
    """Read each file as it was at `revision` in the repository holding the config."""
    verify = subprocess.run(
        ["git", "-C", str(config.root), "rev-parse", "--verify", "--quiet", f"{revision}^{{commit}}"],
        capture_output=True, text=True,
    )
    if verify.returncode != 0:
        raise StatsayError(f"not a Git commit in {config.root}: {revision}")
    commit = verify.stdout.strip()

    def read(path: Path) -> str:
        shown = subprocess.run(
            ["git", "-C", str(config.root), "show", f"{commit}:./{_relative(config, path).as_posix()}"],
            capture_output=True,
        )
        if shown.returncode != 0:
            raise FileNotFoundError(path)
        return shown.stdout.decode("utf-8")

    return read
