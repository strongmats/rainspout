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
        except Exception as exc:
            # a broken installed package (moved source, bad import) must not
            # crash every command with a raw traceback — name the offender
            raise DefinitionError(
                f"entry point {ep.name!r} ({ep.value}) failed to load: "
                f"{type(exc).__name__}: {exc} — the package providing it is broken "
                "or its source is missing; re-install or uninstall that package"
            ) from exc
        loaded.append(ep.name)
    return tuple(loaded)
