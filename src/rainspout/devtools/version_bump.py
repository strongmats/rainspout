"""The stage version-bump CI check.

Any change to stage CODE must bump that stage's `version`; test territory
(``test_*.py`` / ``*_test.py`` / ``fixtures/`` / ``example_data/``) is exempt —
the same boundary the provenance code hash uses. Run against a git base ref:

    python -m rainspout.devtools.version_bump --base origin/main

The stage-directory heuristic is deliberately simple and documented: any
directory sitting directly under a ``stages/`` path segment is a stage
directory. The check passes when the diff for an affected stage directory
adds or changes a ``version = "..."`` line.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from fnmatch import fnmatch
from pathlib import Path, PurePosixPath

TEST_FILE_PATTERNS = ("test_*.py", "*_test.py")
EXCLUDED_DIRS = ("fixtures", "example_data")


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout


def changed_files(repo: Path, base: str) -> list[str]:
    output = _git(repo, "diff", "--name-only", f"{base}...HEAD")
    return [line for line in output.splitlines() if line.strip()]


def stage_dir_of(path: str) -> str | None:
    """The stages/<name>/ directory containing `path`, if any."""
    parts = PurePosixPath(path).parts
    if "stages" not in parts[:-1]:
        return None
    index = parts.index("stages")
    if len(parts) < index + 3:  # needs stages / <name> / <file inside>
        return None
    return "/".join(parts[: index + 2])


def is_stage_code(path: str) -> bool:
    pure = PurePosixPath(path)
    if pure.suffix != ".py":
        return False
    if any(part in EXCLUDED_DIRS for part in pure.parts[:-1]):
        return False
    return not any(fnmatch(pure.name, pattern) for pattern in TEST_FILE_PATTERNS)


def has_version_bump(repo: Path, base: str, stage_dir: str) -> bool:
    diff = _git(repo, "diff", f"{base}...HEAD", "--", stage_dir)
    return any(
        line.startswith("+") and not line.startswith("+++") and "version" in line and "=" in line
        for line in diff.splitlines()
    )


def check_repo(repo: Path, base: str) -> list[str]:
    """Stage directories whose CODE changed without a version bump."""
    affected: set[str] = set()
    for path in changed_files(repo, base):
        stage_dir = stage_dir_of(path)
        if stage_dir is not None and is_stage_code(path):
            affected.add(stage_dir)
    return sorted(
        stage_dir for stage_dir in affected if not has_version_bump(repo, base, stage_dir)
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="origin/main", help="Git ref to diff against")
    parser.add_argument("--repo", default=".", help="Repository root")
    args = parser.parse_args(argv)
    offenders = check_repo(Path(args.repo), args.base)
    if offenders:
        for stage_dir in offenders:
            print(
                f"version-bump check FAILED: {stage_dir} changed stage code without "
                "bumping `version` (test files/fixtures/example_data are exempt)",
                file=sys.stderr,
            )
        return 1
    print("version-bump check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
