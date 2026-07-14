"""Semantic validation: the front half of `spout run`, exposed as `spout validate`.

Order of gates (there is no skip path; `run` passes through exactly these):

1. config parse (:mod:`rainspout.config`)
2. registry resolution (every registry key exists)
3. seed rule (one entry; roles <-> iterated dimensions exactly; types coerce)
4. DAG validation (wiring kinds, dangling references, acyclic, v1 linearity)
5. per-component validation (settings and resources through the un-bypassable
   base constructors)

Everything here is definition-time: instant, touching no data. The seed's
pre-flight probe is run-only.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import UnionType
from typing import Any, Union, get_args, get_origin

from pydantic import TypeAdapter, ValidationError

from . import registry
from .config import RootConfig, expand_dimensions, iteration_order, load_config
from .contracts import Handler, LazyReference, Stage
from .dag import assert_linear_chain, topological_order
from .errors import ConfigError, DefinitionError, ResourcesError, SettingsError


@dataclass(frozen=True)
class ValidatedRun:
    """Everything downstream machinery needs, resolved and constructed."""

    config: RootConfig
    dimension_values: dict[str, tuple[Any, ...]]
    order: tuple[str, ...]
    seed_name: str
    seed_handler: Handler
    handler_instances: dict[str, Handler]
    stage_instances: dict[str, Stage]
    stage_order: tuple[str, ...]


def _construct_handler(owner: str, registry_key: str, resources: dict[str, Any]) -> Handler:
    try:
        handler_cls = registry.get("handler", registry_key)
    except DefinitionError as exc:
        raise ConfigError(f"{owner}: {exc}") from exc
    try:
        return handler_cls(resources)  # type: ignore[no-any-return]
    except ResourcesError as exc:
        raise ResourcesError(f"{owner}: {exc}") from exc


def _check_role_map(
    owner: str,
    handler: Handler,
    mapping: dict[str, str],
    dimension_values: dict[str, tuple[Any, ...]],
    *,
    exact: bool,
) -> None:
    """Dangling-name check always; the seed-grade exactness check where ``exact``.

    Never requires a config dimension name to equal any handler-internal
    name — only the mapping itself is judged.
    """
    for role, dimension in mapping.items():
        if dimension not in dimension_values:
            raise ConfigError(
                f"{owner}: role '{role}' is mapped to '{dimension}', which is not a "
                f"declared dimension (declared: {', '.join(dimension_values)})"
            )
    if not exact:
        return
    roles = set(type(handler).dimension_roles)
    unmapped_roles = roles - set(mapping)
    unknown_roles = set(mapping) - roles
    if unmapped_roles or unknown_roles:
        raise ConfigError(
            f"{owner}: the role map must cover the handler's roles exactly "
            f"(unmapped roles: {sorted(unmapped_roles) or 'none'}, "
            f"unknown roles: {sorted(unknown_roles) or 'none'})"
        )
    uncovered = set(dimension_values) - set(mapping.values())
    if uncovered or len(set(mapping.values())) != len(mapping):
        raise ConfigError(
            f"{owner}: every iterated dimension must be mapped by exactly one role "
            f"(uncovered dimensions: {sorted(uncovered) or 'none'})"
        )
    for role, dimension in mapping.items():
        declared_type = type(handler).dimension_types[role]
        adapter: TypeAdapter[Any] = TypeAdapter(declared_type)
        for value in dimension_values[dimension]:
            try:
                adapter.validate_python(value)
            except ValidationError as exc:
                raise ConfigError(
                    f"{owner}: dimension '{dimension}' value {value!r} does not coerce to "
                    f"{declared_type.__name__}, the declared type of role '{role}'"
                ) from exc


def dependency_annotation(annotation: Any) -> tuple[Any, bool]:
    """Unwrap an optional dependency: ``X | None`` -> ``(X, True)``, else ``(X, False)``.

    A dependency that only some settings need — a calibration file read solely by
    a frequency-dependent calibration, a table consulted in one mode — is declared
    ``Handler | None = None``. Such a dependency may be omitted from the config,
    and the stage is handed ``None``. Every other dependency stays mandatory.
    """
    if get_origin(annotation) in (Union, UnionType):
        args = get_args(annotation)
        non_none = [a for a in args if a is not type(None)]
        if len(args) == 2 and len(non_none) == 1:
            return non_none[0], True
    return annotation, False


def optional_dependencies(stage_cls: type[Stage]) -> set[str]:
    """Names of the stage's dependencies that a config may leave unwired."""
    return {
        name
        for name, field in stage_cls.dependencies_model.model_fields.items()
        if dependency_annotation(field.annotation)[1]
    }


def _wiring_kind(stage_instance: str, stage_cls: type[Stage], field_name: str) -> str:
    field = stage_cls.dependencies_model.model_fields.get(field_name)
    if field is None:
        declared = ", ".join(stage_cls.dependencies_model.model_fields) or "none"
        raise ConfigError(
            f"stage '{stage_instance}' wires unknown dependency '{field_name}' "
            f"(declared dependencies: {declared})"
        )
    annotation, _optional = dependency_annotation(field.annotation)
    if annotation is LazyReference:
        return "from"
    if isinstance(annotation, type) and issubclass(annotation, Handler):
        return "handler"
    raise ConfigError(
        f"stage '{stage_instance}': dependency '{field_name}' is annotated "
        f"{field.annotation!r}, which is not a wiring kind (LazyReference or "
        "Handler, either of which may be made optional as `| None`)"
    )


def _validate_seed(
    config: RootConfig, dimension_values: dict[str, tuple[Any, ...]]
) -> tuple[str, Handler]:
    if len(config.seed) > 1:
        raise ConfigError(
            f"multiple seeds are not supported in v1 (got: {', '.join(sorted(config.seed))})"
        )
    seed_name, entry = next(iter(config.seed.items()))
    owner = f"seed '{seed_name}'"
    handler = _construct_handler(owner, entry.handler, entry.resources)
    _check_role_map(owner, handler, entry.dimensions, dimension_values, exact=True)
    return seed_name, handler


def _validate_stage(
    instance_name: str,
    entry: Any,
    config: RootConfig,
    seed_name: str,
) -> tuple[Stage, tuple[str, ...]]:
    """Construct one stage through the real validation path and check its wiring."""
    try:
        stage_cls: type[Stage] = registry.get("stage", entry.stage)
    except DefinitionError as exc:
        raise ConfigError(f"stage instance '{instance_name}': {exc}") from exc
    try:
        stage = stage_cls(entry.settings)
    except SettingsError as exc:
        raise SettingsError(f"stage instance '{instance_name}': {exc}") from exc

    declared = set(stage_cls.dependencies_model.model_fields)
    # `X | None` dependencies are the stage's business to require or not — it
    # knows which of its settings actually read them; validation cannot.
    missing = declared - optional_dependencies(stage_cls) - set(entry.dependencies)
    if missing:
        raise ConfigError(f"stage '{instance_name}' is missing dependencies: {sorted(missing)}")

    froms: list[str] = []
    for field_name, wiring in entry.dependencies.items():
        kind = _wiring_kind(instance_name, stage_cls, field_name)
        if kind == "from":
            if wiring.from_ is None:
                raise ConfigError(
                    f"stage '{instance_name}': dependency '{field_name}' is a LazyReference "
                    "and must be wired with 'from:', not 'handler:'"
                )
            froms.append(wiring.from_)
        else:
            if wiring.handler is None:
                raise ConfigError(
                    f"stage '{instance_name}': dependency '{field_name}' is a Handler "
                    "and must be wired with 'handler:', not 'from:'"
                )
            if wiring.handler not in config.handlers:
                raise ConfigError(
                    f"stage '{instance_name}': dependency '{field_name}' names unknown "
                    f"handler instance '{wiring.handler}' "
                    f"(declared: {', '.join(config.handlers) or 'none'})"
                )
    for upstream in froms:
        if upstream != seed_name and upstream not in config.stages:
            raise ConfigError(
                f"stage '{instance_name}': 'from: {upstream}' names no stage instance or "
                f"seed entry (stages: {', '.join(config.stages)}; seed: {seed_name})"
            )
    return stage, tuple(froms)


def validate_config(path: Path) -> ValidatedRun:
    """Run every definition-time gate; return the resolved run or raise a named offender."""
    config = load_config(path)
    dimension_values = expand_dimensions(config)
    order = iteration_order(config)

    seed_name, seed_handler = _validate_seed(config, dimension_values)

    handler_instances: dict[str, Handler] = {}
    for name, entry in config.handlers.items():
        owner = f"handler instance '{name}'"
        handler_instances[name] = _construct_handler(owner, entry.handler, entry.resources)
        if entry.dimensions is not None:
            _check_role_map(
                owner, handler_instances[name], entry.dimensions, dimension_values, exact=False
            )

    if seed_name in config.stages:
        raise ConfigError(
            f"'{seed_name}' names both the seed entry and a stage instance; "
            "seed names share the upstream namespace with stage names"
        )

    stage_instances: dict[str, Stage] = {}
    from_edges: dict[str, tuple[str, ...]] = {}
    save_targets: set[str] = set()
    for instance_name, stage_entry in config.stages.items():
        stage_instances[instance_name], from_edges[instance_name] = _validate_stage(
            instance_name, stage_entry, config, seed_name
        )
        if stage_entry.save is not None:
            if stage_entry.save.handler not in config.handlers:
                raise ConfigError(
                    f"stage '{instance_name}': save names unknown handler instance "
                    f"'{stage_entry.save.handler}' "
                    f"(declared: {', '.join(config.handlers) or 'none'})"
                )
            save_targets.add(stage_entry.save.handler)

    # save targets are held to the seed's standard: complete map, startup-checked
    for target in sorted(save_targets):
        target_entry = config.handlers[target]
        if target_entry.dimensions is None:
            raise ConfigError(
                f"handler instance '{target}' is a save target and must carry a "
                "'dimensions:' role map (the driver writes at work-item granularity)"
            )
        _check_role_map(
            f"handler instance '{target}' (save target)",
            handler_instances[target],
            target_entry.dimensions,
            dimension_values,
            exact=True,
        )

    # general graph machinery first, then the distinct v1 rule
    stage_order = topological_order(from_edges)
    assert_linear_chain(seed_name, from_edges)

    return ValidatedRun(
        config=config,
        dimension_values=dimension_values,
        order=order,
        seed_name=seed_name,
        seed_handler=seed_handler,
        handler_instances=handler_instances,
        stage_instances=stage_instances,
        stage_order=stage_order,
    )
