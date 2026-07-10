"""In-flight data handles.

A stage's ``from:``-wired dependencies arrive as :class:`LazyReference`
instances: handles that materialize data only when pulled, carrying the work
item's coordinate stamped by the driver. Phase 1 ships the contract surface
with in-memory backing; the full data plane (windowed access wiring,
handler-backed references) lands with later phases.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from types import MappingProxyType
from typing import Any

from ..errors import RainspoutError

_UNSET = object()


class LazyReference:
    """A handle to data that is not materialized until pulled.

    - ``get()`` materializes the whole object (universal; the fetch runs once
      and is cached).
    - ``coords`` is the current work item's coordinate — a read-only mapping
      of dimension name to value, stamped by the driver at seed time. Stages
      read it freely and can alter neither it nor what it means.
    - ``window(**spec)`` materializes a slice, only where ``can_window``.
    """

    def __init__(
        self,
        fetch: Callable[[], Any],
        *,
        coords: Mapping[str, Any] | None = None,
        windower: Callable[..., Any] | None = None,
    ) -> None:
        self._fetch = fetch
        self._value: Any = _UNSET
        self._coords: Mapping[str, Any] = MappingProxyType(dict(coords or {}))
        self._windower = windower

    @classmethod
    def from_value(
        cls,
        value: Any,
        *,
        coords: Mapping[str, Any] | None = None,
        windower: Callable[..., Any] | None = None,
    ) -> LazyReference:
        """Wrap an already-materialized object (adjacent in-memory stages)."""
        return cls(lambda: value, coords=coords, windower=windower)

    @property
    def coords(self) -> Mapping[str, Any]:
        """The work item's coordinate: dimension name -> value. Read-only."""
        return self._coords

    def get(self) -> Any:
        """Materialize (once) and return the whole object."""
        if self._value is _UNSET:
            self._value = self._fetch()
        return self._value

    @property
    def can_window(self) -> bool:
        """Whether this reference advertises windowed access."""
        return self._windower is not None

    def window(self, **spec: Any) -> Any:
        """Materialize a slice; raises unless ``can_window``."""
        if self._windower is None:
            raise RainspoutError(
                "this reference does not support windowed access; "
                "check ref.can_window before calling window()"
            )
        return self._windower(**spec)
