"""The Handler contract base. docs/HANDLER_AUTHORING.md is the authoritative API.

Authors implement the underscore hooks (``_load_cell`` / ``_save_cell`` /
``_catalog_cells``, plus optionally ``_probe`` / ``_check_structure``); the
public verbs — ``load``, ``load_one``, ``save``, ``catalog``, ``preflight`` —
are final on this base and wrap the hooks with the capability and validation
checks documented on each verb: spec normalization, lazy per-cell iteration,
the single-cell-save rule, and error wrapping that names the handler and the
offending coordinate.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from datetime import UTC, datetime
from itertools import product
from math import prod
from pathlib import Path
from typing import Any, ClassVar

from pydantic import ValidationError

from ..errors import ContractViolation, HandlerError, ResourcesError, named_offender
from . import _enforcement
from .dimension import CatalogEntry, Cell
from .metadata import CatalogDocument, CatalogFileEntry, Meta
from .models import HandlerResources


def _coords_str(coords: Mapping[str, Any]) -> str:
    """The human-readable coordinate form used in error messages."""
    return ", ".join(f"{key}={value}" for key, value in coords.items())


class Handler(metaclass=_enforcement.ContractMeta):
    """Base class for all handlers: one fixed combination of format, layout, and channel.

    Authors declare ``name``, ``resources_model``, ``dimension_roles``,
    ``dimension_types`` and the capability flags, then implement the hooks.
    The base ``__init__`` validates resources and cannot be bypassed or
    redefined; connections are opened lazily inside verbs (lifecycle is
    private, per-transaction by default).
    """

    name: ClassVar[str]
    resources_model: ClassVar[type[HandlerResources]]
    dimension_roles: ClassVar[tuple[str, ...]]
    dimension_types: ClassVar[dict[str, type]]
    supports_grid_range: ClassVar[bool] = False
    supports_windowed_read: ClassVar[bool] = False

    _RESERVED: ClassVar[tuple[str, ...]] = ("load", "load_one", "save", "catalog", "preflight")
    _HOOKS: ClassVar[tuple[str, ...]] = ("_load_cell", "_save_cell", "_catalog_cells")

    # Internal escape hatch for rainspout.testing's fake handler only: lets a
    # fake accept whatever coordinates a stage under test computes. Real
    # handlers never touch this.
    _testing_accepts_any_coords: ClassVar[bool] = False

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        _enforcement.component_name(cls, "handler")  # name problems reported first
        _enforcement.check_no_init(cls, Handler)
        _enforcement.check_reserved(
            cls,
            Handler,
            Handler._RESERVED,
            "the public verbs are final on the base class; implement the underscore "
            "hooks instead (docs/HANDLER_AUTHORING.md §4)",
        )
        resources_model = getattr(cls, "resources_model", None)
        if not (
            isinstance(resources_model, type) and issubclass(resources_model, HandlerResources)
        ):
            raise ContractViolation(
                f"{cls.__qualname__} must declare `resources_model`, a HandlerResources "
                "subclass (docs/HANDLER_AUTHORING.md §5)"
            )
        roles = getattr(cls, "dimension_roles", None)
        if not (
            isinstance(roles, tuple)
            and roles
            and all(isinstance(role, str) and role for role in roles)
        ):
            raise ContractViolation(
                f"{cls.__qualname__} must declare `dimension_roles`, a non-empty tuple of "
                "role-name strings (docs/HANDLER_AUTHORING.md §6)"
            )
        if len(set(roles)) != len(roles):
            raise ContractViolation(
                f"{cls.__qualname__} declares duplicate dimension roles: {roles!r}"
            )
        types_ = getattr(cls, "dimension_types", None)
        if not (
            isinstance(types_, dict)
            and all(isinstance(key, str) for key in types_)
            and all(isinstance(value, type) for value in types_.values())
        ):
            raise ContractViolation(
                f"{cls.__qualname__} must declare `dimension_types`, a dict mapping each "
                "role to a type (docs/HANDLER_AUTHORING.md §6)"
            )
        if set(types_) != set(roles):
            missing = set(roles) - set(types_)
            extra = set(types_) - set(roles)
            raise ContractViolation(
                f"{cls.__qualname__}: `dimension_types` must cover exactly the declared "
                f"roles (missing: {sorted(missing) or 'none'}, extra: {sorted(extra) or 'none'})"
            )
        for flag in ("supports_grid_range", "supports_windowed_read"):
            if not isinstance(getattr(cls, flag), bool):
                raise ContractViolation(f"{cls.__qualname__}: `{flag}` must be a bool")
        for hook in Handler._HOOKS:
            if getattr(cls, hook) is getattr(Handler, hook):
                raise ContractViolation(
                    f"{cls.__qualname__} must implement {hook}() (docs/HANDLER_AUTHORING.md §4)"
                )
        _enforcement.register_component(cls, "handler")

    def __init__(self, resources: Mapping[str, Any] | None = None) -> None:
        model = getattr(type(self), "resources_model", None)
        if model is None:
            raise ContractViolation("Handler is an abstract contract base; instantiate a subclass")
        try:
            self.resources = model.model_validate(dict(resources or {}))
        except ValidationError as exc:
            raise ResourcesError(
                named_offender("handler", type(self).name, "resource", exc)
            ) from exc

    # -- the author's hooks ----------------------------------------------------

    def _load_cell(self, coords: Mapping[str, Any]) -> tuple[Any, Any]:
        """Read one cell: coords (keyed by role) -> (data, meta)."""
        raise NotImplementedError

    def _save_cell(self, coords: Mapping[str, Any], data: Any, meta: Any) -> None:
        """Write one cell, embedding the metadata block per the chosen posture."""
        raise NotImplementedError

    def _catalog_cells(self, spec: Mapping[str, tuple[Any, ...]]) -> Any:
        """Yield a CatalogEntry per existing cell — only within the asked window."""
        raise NotImplementedError

    def _check_structure(self, data: Any, meta: Any) -> None:
        """Optional structural sanity check used by the default probe. Default: no-op."""
        return

    def _probe(self, coords: Mapping[str, Any]) -> None:
        """Startup structural probe on one coordinate.

        The default loads the probe cell in full and passes it to
        ``_check_structure`` — fine for small-cell formats; override where a
        full load is expensive (read a header, check a shape attribute).
        """
        data, meta = self._load_cell(coords)
        self._check_structure(data, meta)

    # -- internal spec/coords plumbing (skeleton-private) -----------------------

    def _normalize_spec(self, spec: Mapping[str, Any]) -> dict[str, tuple[Any, ...]]:
        """Check a spec covers exactly the declared roles, values as ordered tuples."""
        roles = type(self).dimension_roles
        missing = set(roles) - set(spec)
        unknown = set(spec) - set(roles)
        if missing or unknown:
            raise HandlerError(
                f"{type(self).name}: a spec must cover exactly the declared roles "
                f"{roles!r} (missing: {sorted(missing) or 'none'}, "
                f"unknown: {sorted(unknown) or 'none'})"
            )
        normalized: dict[str, tuple[Any, ...]] = {}
        for role in roles:
            values = spec[role]
            if not isinstance(values, (tuple, list)) or not values:
                raise HandlerError(
                    f"{type(self).name}: role '{role}' must map to a non-empty ordered "
                    f"tuple of explicit values (a single value is a tuple of one), "
                    f"got {values!r}"
                )
            normalized[role] = tuple(values)
        return normalized

    def _normalize_coords(self, coords: Mapping[str, Any]) -> dict[str, Any]:
        """Check a single-cell coordinate covers exactly the declared roles."""
        if type(self)._testing_accepts_any_coords:
            return dict(coords)
        roles = type(self).dimension_roles
        missing = set(roles) - set(coords)
        unknown = set(coords) - set(roles)
        if missing or unknown:
            raise HandlerError(
                f"{type(self).name}: coords must cover exactly the declared roles "
                f"{roles!r} (missing: {sorted(missing) or 'none'}, "
                f"unknown: {sorted(unknown) or 'none'})"
            )
        return dict(coords)

    def _call_load(
        self, coords: dict[str, Any], window: Mapping[str, Any] | None
    ) -> tuple[Any, Any]:
        try:
            loaded = self._load_cell(coords) if window is None else self._load_cell(coords, window)  # type: ignore[call-arg]
        except HandlerError:
            raise
        except Exception as exc:
            raise HandlerError(
                f"{type(self).name}: load failed at {_coords_str(coords)}: "
                f"{type(exc).__name__}: {exc}"
            ) from exc
        try:
            data, meta = loaded
        except (TypeError, ValueError) as exc:
            raise HandlerError(
                f"{type(self).name}: _load_cell must return (data, meta), got "
                f"{type(loaded).__name__}"
            ) from exc
        return data, meta

    def _require_window_support(self, window: Mapping[str, Any] | None) -> None:
        if window is not None and not type(self).supports_windowed_read:
            raise HandlerError(
                f"{type(self).name} does not support within-file windowed reads "
                "(supports_windowed_read is off); load whole cells instead"
            )

    def _iter_cells(
        self, normalized: dict[str, tuple[Any, ...]], window: Mapping[str, Any] | None
    ) -> Iterator[Cell]:
        roles = type(self).dimension_roles
        for combo in product(*(normalized[role] for role in roles)):
            coords = dict(zip(roles, combo, strict=True))
            data, meta = self._call_load(coords, window)
            yield Cell(coords=coords, data=data, meta=meta)

    # -- final public verbs ----------------------------------------------------

    def load(
        self, spec: Mapping[str, Any], window: Mapping[str, Any] | None = None
    ) -> Iterator[Cell]:
        """Final. Load the spec'd cells as a lazy per-cell iterator of Cell.

        Around your ``_load_cell``: the spec is checked against your declared
        roles; a multi-cell spec requires ``supports_grid_range`` (the failure
        is immediate, not deferred to iteration); cells are produced one
        coordinate at a time, never materialized together; hook errors are
        wrapped naming this handler and the offending coordinate.
        """
        normalized = self._normalize_spec(spec)
        self._require_window_support(window)
        cell_count = prod(len(values) for values in normalized.values())
        if cell_count > 1 and not type(self).supports_grid_range:
            raise HandlerError(
                f"{type(self).name} does not support dimension-grid ranges "
                f"(supports_grid_range is off) but the spec names {cell_count} cells; "
                "call load_one per cell instead"
            )
        return self._iter_cells(normalized, window)

    def load_one(
        self, coords: Mapping[str, Any], window: Mapping[str, Any] | None = None
    ) -> tuple[Any, Meta]:
        """Final. Load exactly one cell: coords -> (data, meta).

        Exactly ``load`` with a one-value spec, returning directly instead of
        iterating — the call stages typically make on an auxiliary handler,
        in a loop when they need several cells.
        """
        normalized = self._normalize_coords(coords)
        self._require_window_support(window)
        return self._call_load(normalized, window)

    def save(self, spec: Mapping[str, Any], data: Any, meta: Meta) -> None:
        """Final. Persist one cell's data (+ metadata block, per your posture).

        Around your ``_save_cell``: the spec is checked against your roles and
        must be single-cell (the base enforces this for every handler); ``meta``
        must be a Meta block; hook errors are wrapped naming this handler and
        the coordinate.
        """
        normalized = self._normalize_spec(spec)
        oversize = {role: len(values) for role, values in normalized.items() if len(values) != 1}
        if oversize:
            raise HandlerError(
                f"{type(self).name}: save accepts only a single-cell spec "
                f"(got multiple values for {sorted(oversize)})"
            )
        if not isinstance(meta, Meta):
            raise HandlerError(
                f"{type(self).name}: save requires a Meta metadata block, "
                f"got {type(meta).__name__}"
            )
        coords = {role: values[0] for role, values in normalized.items()}
        try:
            self._save_cell(coords, data, meta)
        except HandlerError:
            raise
        except Exception as exc:
            raise HandlerError(
                f"{type(self).name}: save failed at {_coords_str(coords)}: "
                f"{type(exc).__name__}: {exc}"
            ) from exc

    def catalog(
        self, spec: Mapping[str, Any], write_path: Path | None = None
    ) -> Iterator[CatalogEntry]:
        """Final. Survey which spec'd cells exist, lazily.

        Around your ``_catalog_cells``: the spec is checked against your
        roles; every yielded entry is checked to be a CatalogEntry keyed by
        your roles; hook errors are wrapped. With ``write_path``, the survey
        is additionally written as a validated catalog file (the base handles
        serialization; your hook only yields entries).
        """
        normalized = self._normalize_spec(spec)
        entries = self._iter_catalog(normalized)
        if write_path is None:
            return entries
        materialized = list(entries)
        document = CatalogDocument(
            handler=type(self).name,
            roles=type(self).dimension_roles,
            entries=tuple(
                CatalogFileEntry(coords=entry.coords, extras=entry.extras)
                for entry in materialized
            ),
            generated_at=datetime.now(UTC),
        )
        write_path.write_text(json.dumps(json.loads(document.model_dump_json()), indent=2))
        return iter(materialized)

    def _iter_catalog(self, normalized: dict[str, tuple[Any, ...]]) -> Iterator[CatalogEntry]:
        roles = set(type(self).dimension_roles)
        iterator = self._catalog_cells(normalized)
        while True:
            try:
                entry = next(iterator)
            except StopIteration:
                return
            except HandlerError:
                raise
            except Exception as exc:
                raise HandlerError(f"{type(self).name}: catalog failed: {exc}") from exc
            if not isinstance(entry, CatalogEntry) or set(entry.coords) != roles:
                raise HandlerError(
                    f"{type(self).name}: _catalog_cells must yield CatalogEntry objects "
                    f"with coords keyed by the declared roles {sorted(roles)}, "
                    f"got {entry!r}"
                )
            yield entry

    def preflight(self, coords: Mapping[str, Any]) -> None:
        """Final. Run the structural probe; a failure names handler and coordinate."""
        try:
            self._probe(dict(coords))
        except Exception as exc:
            raise HandlerError(
                f"{type(self).name}: pre-flight probe failed at {_coords_str(coords)}: "
                f"{type(exc).__name__}: {exc}"
            ) from exc
