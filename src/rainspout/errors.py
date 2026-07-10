"""Rainspout's error taxonomy.

Three tiers, mirroring the validation design:

- ``DefinitionError`` (and subclasses): something is *defined* wrong — a
  component class, a registration, a setting, a config. Always fatal to the
  whole run, always raised before any data moves, always naming the specific
  offender.
- ``StageError`` / ``HandlerError``: runtime failures scoped to one work
  item. The driver logs them, fails that work item only, and continues.
- ``RainspoutError``: the common base, so callers can catch everything
  Rainspout raises deliberately.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pydantic import ValidationError


class RainspoutError(Exception):
    """Base class for every error Rainspout raises on purpose."""


class DefinitionError(RainspoutError):
    """A component, registration, or configuration is wrongly defined.

    Fatal to the whole run; raised before any data moves; the message names
    the specific offender.
    """


class ContractViolation(DefinitionError):
    """A component class breaks an authoring-contract rule.

    Raised at class-definition time, so a nonconforming component cannot even
    be imported.
    """


class ConfigError(DefinitionError):
    """A run configuration is malformed or inconsistent; the message names the key."""


class RegistrationError(DefinitionError):
    """A component could not be registered (missing, invalid, or duplicate name)."""


class SettingsError(DefinitionError):
    """A stage's settings failed validation; the message names stage and field."""


class ResourcesError(DefinitionError):
    """A handler's resources failed validation; the message names instance and field."""


class StageError(RainspoutError):
    """A stage failed at runtime, for the current work item only."""


class HandlerError(RainspoutError):
    """A handler failed at runtime, for the current work item only."""


def named_offender(kind: str, owner: str, noun: str, exc: ValidationError) -> str:
    """Format a pydantic ValidationError into a named-offender message.

    Produces e.g. ``stage 'smooth_readings': setting 'window_len': Input
    should be less than or equal to 10000``.
    """
    issues = "; ".join(
        f"{noun} '{'.'.join(str(part) for part in err['loc']) or '<root>'}': {err['msg']}"
        for err in exc.errors()
    )
    return f"{kind} '{owner}': {issues}"
