"""The Stage contract base. docs/STAGE_AUTHORING.md is the authoritative API.

Subclassing :class:`Stage` with the required class attributes registers the
stage automatically; every class-level contract violation fails at
class-definition time, naming the class.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, ClassVar

from pydantic import ValidationError

from ..errors import ContractViolation, SettingsError, StageError, named_offender
from . import _enforcement
from .models import StageDependencies, StageSettings


class Stage(metaclass=_enforcement.ContractMeta):
    """Base class for all stages: a thin orchestrator around module-level science.

    Authors declare ``name``, ``version``, ``settings_model``,
    ``dependencies_model`` and implement ``run`` (plus optionally ``setup``
    and ``progress``). The base ``__init__`` validates settings and cannot be
    bypassed or redefined.
    """

    name: ClassVar[str]
    version: ClassVar[str]
    settings_model: ClassVar[type[StageSettings]]
    dependencies_model: ClassVar[type[StageDependencies]]

    _RESERVED: ClassVar[tuple[str, ...]] = ("status", "set_status", "set_progress", "add_warning")

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        _enforcement.component_name(cls, "stage")  # name problems reported first
        _enforcement.check_no_init(cls, Stage)
        _enforcement.check_reserved(
            cls,
            Stage,
            Stage._RESERVED,
            "it is base-provided reporting machinery; call it, don't replace it "
            "(docs/STAGE_AUTHORING.md §8)",
        )
        version = getattr(cls, "version", None)
        if not isinstance(version, str) or not version:
            raise ContractViolation(
                f"{cls.__qualname__} must declare `version` as a non-empty string "
                "(docs/STAGE_AUTHORING.md §9)"
            )
        settings_model = getattr(cls, "settings_model", None)
        if not (isinstance(settings_model, type) and issubclass(settings_model, StageSettings)):
            raise ContractViolation(
                f"{cls.__qualname__} must declare `settings_model`, a StageSettings "
                "subclass (docs/STAGE_AUTHORING.md §4)"
            )
        dependencies_model = getattr(cls, "dependencies_model", None)
        if not (
            isinstance(dependencies_model, type)
            and issubclass(dependencies_model, StageDependencies)
        ):
            raise ContractViolation(
                f"{cls.__qualname__} must declare `dependencies_model`, a StageDependencies "
                "subclass (docs/STAGE_AUTHORING.md §5)"
            )
        if cls.run is Stage.run:
            raise ContractViolation(
                f"{cls.__qualname__} must implement run() (docs/STAGE_AUTHORING.md §2)"
            )
        _enforcement.register_component(cls, "stage")

    def __init__(self, settings: Mapping[str, Any] | None = None) -> None:
        model = getattr(type(self), "settings_model", None)
        if model is None:
            raise ContractViolation("Stage is an abstract contract base; instantiate a subclass")
        try:
            self.settings = model.model_validate(dict(settings or {}))
        except ValidationError as exc:
            raise SettingsError(
                named_offender("stage", type(self).name, "setting", exc)
            ) from exc
        self._status: str = ""
        self._progress: float | None = None
        self._warnings: list[str] = []

    # -- the author's surface -------------------------------------------------

    def setup(self) -> None:
        """One-time, idempotent initialization: after validation, before any work item."""
        return

    def run(self, deps: StageDependencies) -> Any:
        """Process one work item. Implemented by every concrete stage."""
        raise NotImplementedError

    def progress(self) -> float | None:
        """Fraction complete in [0, 1], or None where a total genuinely can't be known.

        Overridable; the default reports whatever ``set_progress`` recorded.
        """
        return self._progress

    # -- base-provided reporting (final; enforced at class definition) --------

    def status(self) -> str:
        """The stage's current one-line, human-readable status."""
        return self._status

    def set_status(self, status: str) -> None:
        """Update the status line. Mandatory at least once per run(). Cheap."""
        self._status = str(status)

    def set_progress(self, fraction: float) -> None:
        """Record progress; must lie in [0, 1]."""
        value = float(fraction)
        if not 0.0 <= value <= 1.0:
            raise StageError(f"progress must be within [0, 1], got {fraction!r}")
        self._progress = value

    def add_warning(self, message: str) -> None:
        """Record that output is valid but something is worth noting."""
        self._warnings.append(str(message))

    @property
    def warnings(self) -> tuple[str, ...]:
        """Warnings recorded so far (read-only view)."""
        return tuple(self._warnings)
