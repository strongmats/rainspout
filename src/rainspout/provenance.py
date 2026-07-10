"""Provenance helpers: the code hash and per-stage chain entries.

The code hash is the tamper-evident backstop to the version-bump CI check: it
is computed over a stage's *code* files and recorded in every provenance
entry, so an unbumped edit is evident after the fact even if CI was dodged.

The code/test boundary (docs/STAGE_AUTHORING.md §9): within a component
directory, ``test_*.py`` / ``*_test.py`` and anything under ``fixtures/`` or
``example_data/`` are test territory — excluded from the hash. Every other
``*.py`` file is stage code, hashed as the sorted concatenation of file bytes.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from fnmatch import fnmatch
from hashlib import sha256
from pathlib import Path

from .contracts import ProvenanceEntry, Stage

TEST_FILE_PATTERNS = ("test_*.py", "*_test.py")
EXCLUDED_DIRS = ("fixtures", "example_data")

_HASH_CACHE: dict[type, str] = {}


def _is_test_territory(path: Path, root: Path) -> bool:
    relative = path.relative_to(root)
    if any(part in EXCLUDED_DIRS for part in relative.parts[:-1]):
        return True
    return any(fnmatch(relative.name, pattern) for pattern in TEST_FILE_PATTERNS)


def hash_component_dir(directory: Path) -> str:
    """Hash a component directory's code files (sorted, test territory excluded)."""
    digest = sha256()
    for path in sorted(directory.rglob("*.py")):
        if _is_test_territory(path, directory):
            continue
        digest.update(path.relative_to(directory).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()


def stage_code_hash(stage_cls: type[Stage]) -> str:
    """The code hash for a stage class: its module's directory, code files only."""
    cached = _HASH_CACHE.get(stage_cls)
    if cached is not None:
        return cached
    module = sys.modules.get(stage_cls.__module__)
    source = getattr(module, "__file__", None)
    computed = hash_component_dir(Path(source).parent) if source else "unhashable-source"
    _HASH_CACHE[stage_cls] = computed
    return computed


def provenance_entry(
    stage: Stage,
    *,
    warnings: Sequence[str] = (),
    timestamp: datetime | None = None,
) -> ProvenanceEntry:
    """One stage's mark on the data, ready to append to a chain."""
    stage_cls = type(stage)
    return ProvenanceEntry(
        stage_name=stage_cls.name,
        stage_version=stage_cls.version,
        code_hash=stage_code_hash(stage_cls),
        settings_used=stage.settings.model_dump(mode="json"),
        timestamp=timestamp or datetime.now(UTC),
        warnings=tuple(warnings),
    )
