"""The component registry: name -> class, one map per axis.

The registry is never hand-edited. Components register themselves by
subclassing a contract base with a ``name`` attribute (the uniform
``__init_subclass__`` gesture); cross-package discovery is entry points
(:mod:`rainspout.discovery`).
"""

from __future__ import annotations

from .errors import DefinitionError, RegistrationError

_AXES: dict[str, dict[str, type]] = {}


def register(axis: str, name: str, cls: type) -> None:
    """Register ``cls`` under ``name`` on ``axis``; duplicates fail loudly.

    Re-registering the *same* class object is a no-op, so a module imported
    twice does not trip the duplicate check.
    """
    axis_map = _AXES.setdefault(axis, {})
    existing = axis_map.get(name)
    if existing is not None and existing is not cls:
        raise RegistrationError(
            f"duplicate {axis} name {name!r}: already registered by "
            f"{existing.__module__}.{existing.__qualname__}, re-registered by "
            f"{cls.__module__}.{cls.__qualname__}"
        )
    axis_map[name] = cls


def get(axis: str, name: str) -> type:
    """Resolve a registered class, or fail naming the unknown key and the known ones."""
    axis_map = _AXES.get(axis, {})
    try:
        return axis_map[name]
    except KeyError:
        known = ", ".join(sorted(axis_map)) or "none registered"
        raise DefinitionError(f"unknown {axis} {name!r} (known: {known})") from None


def names(axis: str) -> tuple[str, ...]:
    """All registered names on an axis, sorted."""
    return tuple(sorted(_AXES.get(axis, {})))
