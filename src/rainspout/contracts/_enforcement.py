"""Definition-time contract enforcement shared by every contract base.

One uniform gesture per axis: subclass the base with a ``name`` attribute and
the class registers itself; break a class-level rule and the class fails to
*define* — loudly, naming itself — long before anything runs.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

from .. import registry
from ..errors import ContractViolation, RegistrationError

_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")


class ContractMeta(type):
    """Blocks post-definition monkey-patching of ``__init__`` and final methods.

    ``__init_subclass__`` catches contract violations in the class *body*;
    this metaclass closes the remaining door — assigning ``cls.__init__ = ...``
    (or a reserved final method) after the class exists.
    """

    def __setattr__(cls, name: str, value: object) -> None:
        guarded = ("__init__", *getattr(cls, "_RESERVED", ()))
        if name in guarded:
            raise ContractViolation(
                f"cannot assign {name!r} on {cls.__qualname__}: validation and the final "
                "base methods cannot be replaced, before or after class definition"
            )
        super().__setattr__(name, value)


def foreign_bases(cls: type, contract_base: type) -> Iterator[type]:
    """Bases of ``cls`` that are neither ``object`` nor on the contract-base chain."""
    for base in cls.__mro__[1:]:
        if base is object:
            continue
        if issubclass(base, contract_base) or base in contract_base.__mro__:
            continue
        yield base


def check_no_init(cls: type, contract_base: type) -> None:
    """The base ``__init__`` validates and cannot be bypassed — nobody redefines it."""
    if "__init__" in cls.__dict__:
        raise ContractViolation(
            f"{cls.__qualname__} defines __init__, which contract subclasses may not: "
            "validation lives in the base __init__ and cannot be bypassed "
            "(use setup() on stages, or lazy per-verb initialization in handlers)"
        )
    for base in foreign_bases(cls, contract_base):
        if "__init__" in base.__dict__:
            raise ContractViolation(
                f"{cls.__qualname__} mixes in {base.__qualname__}, which defines __init__; "
                "mixins that define __init__ are rejected"
            )


def check_reserved(cls: type, contract_base: type, reserved: tuple[str, ...], why: str) -> None:
    """Final base methods may not be shadowed, directly or via a mixin."""
    for attr in reserved:
        if attr in cls.__dict__:
            raise ContractViolation(
                f"{cls.__qualname__} overrides final method {attr!r}: {why}"
            )
        for base in foreign_bases(cls, contract_base):
            if attr in base.__dict__:
                raise ContractViolation(
                    f"{cls.__qualname__} inherits {attr!r} from mixin "
                    f"{base.__qualname__}: {why}"
                )


def component_name(cls: type, axis: str) -> str:
    """Validate and return the class's own ``name``; checked before anything else
    so a nameless class is reported as such, not as its first missing attribute."""
    name = cls.__dict__.get("name")
    if not isinstance(name, str) or not name:
        raise RegistrationError(
            f"{cls.__qualname__} must declare its own class-level `name` string; "
            f"every concrete {axis} is registered automatically by that name"
        )
    if not _NAME_RE.fullmatch(name):
        raise RegistrationError(
            f"{axis} name {name!r} (on {cls.__qualname__}) is invalid: "
            "lowercase letters, digits and underscores only — no dots"
        )
    return name


def register_component(cls: type, axis: str) -> None:
    """Register the class on ``axis`` — called last, so invalid classes never register."""
    registry.register(axis, component_name(cls, axis), cls)
