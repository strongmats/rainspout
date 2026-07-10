"""Public testing helpers for content packages — a v1 API stability commitment.

Alongside ``rainspout.contracts``, this module is the only other public
surface: packages pin to `run_stage`, `from_handler_data`, and
`assert_roundtrip` for the life of ``rainspout>=1,<2``.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any

from .contracts import Handler, HandlerResources, LazyReference, Meta, Stage
from .contracts.metadata import ProvenanceEntry
from .errors import RainspoutError


class _FakeDataHandler(Handler):
    """Serves one fixed payload for ANY coordinates; save is refused.

    What `from_handler_data` hands to a stage under test in place of a real
    auxiliary handler.
    """

    name = "rainspout_testing_fake"
    resources_model = HandlerResources
    dimension_roles = ("key",)
    dimension_types = {"key": str}  # noqa: RUF012 — ClassVar declared on the base
    _testing_accepts_any_coords = True
    _payload: Any

    def _load_cell(self, coords: Mapping[str, Any]) -> tuple[Any, Meta]:
        return self._payload, Meta.fresh(coords=dict(coords))

    def _save_cell(self, coords: Mapping[str, Any], data: Any, meta: Meta) -> None:
        raise RainspoutError("the rainspout.testing fake handler is read-only")

    def _catalog_cells(self, spec: Mapping[str, Any]) -> Any:
        return iter(())


def from_handler_data(obj: Any) -> Handler:
    """A fake handler whose ``load_one``/``load`` serve ``obj`` for any coordinates.

    Use it as the value of a Handler-annotated dependency in ``run_stage``'s
    ``deps`` — the stage under test computes whatever coordinates it likes and
    always receives ``obj`` (with a fresh metadata block).
    """
    handler = _FakeDataHandler({})
    handler._payload = obj
    return handler


def run_stage(
    stage_cls: type[Stage],
    settings: Mapping[str, Any],
    deps: Mapping[str, Any] | None = None,
    coords: Mapping[str, Any] | None = None,
) -> Any:
    """Run one stage the way the runner would, returning its output.

    Constructs the stage through the real validation path (so
    ``EXAMPLE_SETTINGS`` is proven valid), wraps each ``deps`` value per the
    field's declared wiring kind — plain values become coordinate-stamped
    ``LazyReference``s (``coords`` sets ``ref.coords``, default empty); Handler
    fields take a handler instance or ``from_handler_data(...)`` — then runs
    ``setup()`` and ``run()``.
    """
    stage = stage_cls(dict(settings))
    provided = dict(deps or {})
    field_values: dict[str, Any] = {}
    for name, field in stage_cls.dependencies_model.model_fields.items():
        if name not in provided:
            raise RainspoutError(f"run_stage: missing a value for dependency '{name}'")
        value = provided.pop(name)
        annotation = field.annotation
        if annotation is LazyReference:
            if not isinstance(value, LazyReference):
                value = LazyReference.from_value(value, coords=dict(coords or {}))
            field_values[name] = value
        elif isinstance(annotation, type) and issubclass(annotation, Handler):
            if not isinstance(value, Handler):
                raise RainspoutError(
                    f"run_stage: dependency '{name}' is Handler-annotated; pass a handler "
                    "instance or from_handler_data(obj)"
                )
            field_values[name] = value
        else:
            raise RainspoutError(
                f"run_stage: dependency '{name}' has unsupported annotation {annotation!r}"
            )
    if provided:
        raise RainspoutError(
            f"run_stage: deps has values for undeclared dependencies: {sorted(provided)}"
        )
    deps_obj = stage_cls.dependencies_model(**field_values)
    stage.setup()
    return stage.run(deps_obj)


def values_equal(a: Any, b: Any, *, rel_tol: float = 1e-9, abs_tol: float = 1e-12) -> bool:
    """The default round-trip equality: exact for structure/ints/strings,
    tolerance-based for floats, recursive for lists/tuples/dicts."""
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return math.isclose(a, b, rel_tol=rel_tol, abs_tol=abs_tol)
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(values_equal(x, y) for x, y in zip(a, b, strict=True))
    if isinstance(a, dict) and isinstance(b, dict):
        return set(a) == set(b) and all(values_equal(a[key], b[key]) for key in a)
    result = a == b
    return bool(result)


def assert_roundtrip(
    handler_cls: type[Handler],
    example_resources: Mapping[str, Any],
    example_coords: Mapping[str, Any],
    tmp_base: Any,
    *,
    save_resources: Mapping[str, Any] | None = None,
    equal: Callable[[Any, Any], bool] | None = None,
) -> None:
    """The mandated handler round-trip: load -> save -> load -> equal -> catalog.

    Checks **preservation of whatever exists**: data always; the metadata
    block too *if* the handler handles metadata (a probe provenance entry is
    injected before saving, so preservation is genuinely exercised). A
    metadata-ignoring handler is never failed for ignoring it — only altering
    data, or altering metadata the handler claims to handle, fails.

    By default the save-side handler is constructed with ``example_resources``
    but ``base_dir`` swapped for ``tmp_base``; handlers whose resources have
    no ``base_dir`` field pass ``save_resources=`` explicitly. Custom
    container types pass ``equal=``.
    """
    compare = equal or values_equal

    if save_resources is None:
        if "base_dir" not in dict(example_resources):
            raise RainspoutError(
                "assert_roundtrip: resources have no 'base_dir' field to retarget; "
                "pass save_resources= explicitly"
            )
        save_resources = {**dict(example_resources), "base_dir": tmp_base}

    source = handler_cls(dict(example_resources))
    data, meta = source.load_one(example_coords)

    probe = ProvenanceEntry(
        stage_name="roundtrip_probe",
        stage_version="0.0.0",
        code_hash="0" * 12,
        settings_used={},
        timestamp=datetime.now(UTC),
    )
    meta_in = meta.with_entry(probe)
    target = handler_cls(dict(save_resources))

    spec = {role: (example_coords[role],) for role in handler_cls.dimension_roles}
    target.save(spec, data, meta_in)
    data_back, meta_back = target.load_one(example_coords)

    if not compare(data, data_back):
        raise AssertionError(
            f"{handler_cls.name}: data was altered across load->save->load "
            f"(loaded {data!r}, got back {data_back!r})"
        )
    # a handler that handles metadata must return it intact; an ignoring one
    # (empty provenance back) is never failed for that
    if meta_back.provenance and list(meta_back.provenance) != list(meta_in.provenance):
        raise AssertionError(
            f"{handler_cls.name}: the metadata block was altered across the "
            "round-trip (provenance chain does not match what was saved)"
        )

    canonical = {role: str(example_coords[role]) for role in handler_cls.dimension_roles}
    entries = list(target.catalog(spec))
    if not any(
        {key: str(val) for key, val in entry.coords.items()} == canonical for entry in entries
    ):
        raise AssertionError(
            f"{handler_cls.name}: catalog does not report the saved cell at "
            f"{canonical!r} (reported: {[entry.coords for entry in entries]!r})"
        )
