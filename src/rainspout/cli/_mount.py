"""Mounting package-contributed verbs: the `rainspout.verbs` entry-point group.

Each entry point resolves to a Typer app, mounted as
`spout <entry-point-name> <verb>`. Collisions and non-Typer payloads fail
loudly naming the offending entry point(s).
"""

from __future__ import annotations

from importlib import metadata
from typing import Any

import typer

from ..errors import DefinitionError, RegistrationError

GROUP = "rainspout.verbs"


def mount_package_verbs(app: typer.Typer, entry_points: Any = None) -> tuple[str, ...]:
    """Mount every discovered verb app onto `app`; return the mount names."""
    discovered = (
        entry_points if entry_points is not None else metadata.entry_points(group=GROUP)
    )
    seen: dict[str, str] = {}
    for entry_point in discovered:
        if entry_point.name in seen:
            raise RegistrationError(
                f"two packages contribute verbs under the same mount name "
                f"{entry_point.name!r}: {seen[entry_point.name]} and {entry_point.value}"
            )
        loaded = entry_point.load()
        if not isinstance(loaded, typer.Typer):
            raise DefinitionError(
                f"rainspout.verbs entry point {entry_point.name!r} ({entry_point.value}) "
                f"must resolve to a typer.Typer app, got {type(loaded).__name__}"
            )
        app.add_typer(loaded, name=entry_point.name)
        seen[entry_point.name] = entry_point.value
    return tuple(seen)
