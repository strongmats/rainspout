"""Dimension-facing value types shared across the data plane."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from .metadata import Meta

# A single-cell coordinate: role name -> one value.
Coords = Mapping[str, Any]

# A dimension spec: role name -> ordered tuple of explicit values
# (a single value is a tuple of one; there is no scalar special case).
DimensionSpec = Mapping[str, tuple[Any, ...]]


@dataclass(frozen=True)
class Cell:
    """One cell as served by `load`: where it is, its data, its metadata block."""

    coords: dict[str, Any]
    data: Any
    meta: Meta


@dataclass(frozen=True)
class CatalogEntry:
    """One existing cell as reported by `catalog`.

    ``extras`` is handler-private (size, mtime, ...) and never interpreted by
    the skeleton.
    """

    coords: dict[str, Any]
    extras: dict[str, Any] = field(default_factory=dict)
