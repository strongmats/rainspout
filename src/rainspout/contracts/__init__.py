"""The public contract surface content packages build against.

Everything imported here is API, documented in ``docs/`` (the authoring
documents are the authoritative reference). Nothing else in ``rainspout`` is.
"""

from ..errors import (
    ContractViolation,
    DefinitionError,
    HandlerError,
    RainspoutError,
    RegistrationError,
    ResourcesError,
    SettingsError,
    StageError,
)
from .dimension import CatalogEntry, Cell, Coords, DimensionSpec
from .handler import Handler
from .metadata import Meta, ProvenanceEntry
from .models import HandlerResources, StageDependencies, StageSettings
from .reference import LazyReference
from .stage import Stage

__all__ = [
    "CatalogEntry",
    "Cell",
    "ContractViolation",
    "Coords",
    "DefinitionError",
    "DimensionSpec",
    "Handler",
    "HandlerError",
    "HandlerResources",
    "LazyReference",
    "Meta",
    "ProvenanceEntry",
    "RainspoutError",
    "RegistrationError",
    "ResourcesError",
    "SettingsError",
    "Stage",
    "StageDependencies",
    "StageError",
    "StageSettings",
]
