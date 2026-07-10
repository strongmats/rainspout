"""Entry-point discovery of content packages.

A content package exposes one collector module under the
``rainspout.components`` entry-point group; importing that module triggers
registration of every component in the package (via ``__init_subclass__``).
Adding a component to an existing collector module is live; adding or
changing the entry point itself requires a re-install (``uv sync``) to be
discovered.
"""

from __future__ import annotations

from importlib import metadata

from .errors import DefinitionError

GROUP = "rainspout.components"


def discover_components() -> tuple[str, ...]:
    """Import every collector module; return the entry-point names loaded.

    A registration failure inside a package is re-raised with the offending
    entry point named, so collisions across packages are attributable.
    """
    loaded: list[str] = []
    for ep in metadata.entry_points(group=GROUP):
        try:
            ep.load()
        except DefinitionError as exc:
            raise DefinitionError(
                f"while loading components from entry point {ep.name!r} ({ep.value}): {exc}"
            ) from exc
        loaded.append(ep.name)
    return tuple(loaded)
