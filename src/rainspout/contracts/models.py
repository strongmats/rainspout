"""Base Pydantic models that content packages extend.

Every field an author adds to these models must declare a bounded valid
domain (``Field(ge=..., le=...)``, ``Literal``/``Enum``, constrained
strings); an unbounded field is a deliberate, comment-justified exception.
See docs/STAGE_AUTHORING.md §4 and docs/HANDLER_AUTHORING.md §5.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class StageSettings(BaseModel):
    """Base for a stage's settings model: static, deep-validated config.

    ``extra="forbid"`` makes config typos loud; ``frozen=True`` keeps
    validated settings immutable for the life of the run.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)


class StageDependencies(BaseModel):
    """Base for a stage's dependencies model: its named data inputs.

    Each field's type annotation declares the wiring it accepts —
    ``LazyReference`` for ``from:``, ``Handler`` for ``handler:``.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, arbitrary_types_allowed=True)


class HandlerResources(BaseModel):
    """Base for a handler's resources model: everything it needs to reach its data."""

    model_config = ConfigDict(extra="forbid", frozen=True)
