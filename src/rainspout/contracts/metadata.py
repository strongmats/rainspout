"""The shared metadata block: one shape across every file type.

Every metadata-capable handler embeds a :class:`Meta` in the data file on
save and recovers it intact on load. It carries the provenance chain — the
record of every stage that touched the data — which is what makes results
scientifically traceable. Handlers may deliberately ignore metadata (a
documented, provenance-severing posture); foreign data always loads with a
fresh, empty-provenance block.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator

SCHEMA_VERSION = 1


class ProvenanceEntry(BaseModel):
    """One stage's mark on the data: who, which version, with what settings, when."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    stage_name: str
    stage_version: str
    code_hash: str
    settings_used: dict[str, Any]
    timestamp: datetime
    warnings: tuple[str, ...] = ()


class Meta(BaseModel):
    """The metadata block. Immutable; evolve it with :meth:`with_entry`.

    ``coords`` values are canonicalized to strings so the block survives any
    format's round-trip byte-exactly (the canonical serialized coordinate is
    also the per-work-item sub-key alongside ``run_id``).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = SCHEMA_VERSION
    run_id: str | None = None
    coords: dict[str, str] = {}
    provenance: tuple[ProvenanceEntry, ...] = ()

    @field_validator("coords", mode="before")
    @classmethod
    def _canonicalize(cls, value: Any) -> Any:
        if isinstance(value, dict):
            return {str(key): str(val) for key, val in value.items()}
        return value

    @classmethod
    def fresh(cls, coords: dict[str, Any] | None = None, run_id: str | None = None) -> Meta:
        """A new block with an empty provenance chain (foreign / first-entry data)."""
        return cls(coords=coords or {}, run_id=run_id)

    def with_entry(self, entry: ProvenanceEntry) -> Meta:
        """A copy with ``entry`` appended to the provenance chain (order preserved)."""
        return self.model_copy(update={"provenance": (*self.provenance, entry)})


class CatalogFileEntry(BaseModel):
    """One cataloged cell as it appears in a written catalog file."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    coords: dict[str, str]
    extras: dict[str, Any] = {}

    @field_validator("coords", mode="before")
    @classmethod
    def _canonicalize(cls, value: Any) -> Any:
        if isinstance(value, dict):
            return {str(key): str(val) for key, val in value.items()}
        return value


class CatalogDocument(BaseModel):
    """The validated shape of a catalog file (written by the base `catalog` verb)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    handler: str
    roles: tuple[str, ...]
    entries: tuple[CatalogFileEntry, ...]
    generated_at: datetime
