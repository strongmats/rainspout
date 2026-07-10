"""Static package-conformance checking — the shape check behind `spout test-package`.

Cheap by design: verifies the mandated module-level names exist and validate
(`STAGE`/`EXAMPLE_SETTINGS`; `HANDLER`/`EXAMPLE_RESOURCES`/`EXAMPLE_COORDS`),
that each component directory carries its mandated test (and, for handlers,
example data), and emits lint-style warnings for unbounded settings/resources
fields. It does NOT run tests or measure coverage — that is the package's own
CI (and `spout test-package` without `--static-only`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from fnmatch import fnmatch
from importlib import import_module, metadata
from pathlib import Path
from types import ModuleType, UnionType
from typing import Any, Union, get_args, get_origin

from pydantic import BaseModel

from . import registry
from .contracts import Handler, Stage
from .errors import DefinitionError

TEST_FILE_PATTERNS = ("test_*.py", "*_test.py")


@dataclass
class ComponentCheck:
    axis: str
    name: str
    problems: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


@dataclass
class ConformanceReport:
    package: str
    components: list[ComponentCheck]

    @property
    def ok(self) -> bool:
        return bool(self.components) and all(check.ok for check in self.components)


def load_package_components(package: str) -> None:
    """Load the package's `rainspout.components` collector (registering everything)."""
    for entry_point in metadata.entry_points(group="rainspout.components"):
        if entry_point.name == package:
            entry_point.load()
            return
    # fall back to the conventional collector module for editable/dev setups
    try:
        import_module(f"{package}.components")
    except ImportError as exc:
        raise DefinitionError(
            f"package '{package}' exposes no rainspout.components entry point and "
            f"'{package}.components' is not importable: {exc}"
        ) from exc


def _package_components(package: str) -> list[tuple[str, type]]:
    found: list[tuple[str, type]] = []
    for axis in ("stage", "handler"):
        for name in registry.names(axis):
            cls = registry.get(axis, name)
            module = cls.__module__
            if module == package or module.startswith(f"{package}."):
                found.append((axis, cls))
    return found


def _component_dir(cls: type) -> Path | None:
    import sys

    module = sys.modules.get(cls.__module__)
    source = getattr(module, "__file__", None)
    return Path(source).parent if source else None


def _test_modules(cls: type, directory: Path) -> list[tuple[Path, ModuleType | Exception]]:
    package = cls.__module__.rsplit(".", 1)[0]
    loaded: list[tuple[Path, ModuleType | Exception]] = []
    for path in sorted(directory.iterdir()):
        if path.is_file() and any(fnmatch(path.name, pattern) for pattern in TEST_FILE_PATTERNS):
            try:
                loaded.append((path, import_module(f"{package}.{path.stem}")))
            except Exception as exc:  # noqa: BLE001 — reported as a conformance problem
                loaded.append((path, exc))
    return loaded


def _has_test_function(module: ModuleType) -> bool:
    return any(name.startswith("test_") and callable(getattr(module, name)) for name in dir(module))


def _nested_models(annotation: Any) -> list[tuple[str | None, type[BaseModel]]]:
    """BaseModel classes reachable inside a field annotation.

    A union arm is labeled with its class name (so a warning can say which
    arm the field lives in); a directly nested model, or one inside a
    container like ``list[...]``, is unlabeled.
    """
    if isinstance(annotation, type):
        return [(None, annotation)] if issubclass(annotation, BaseModel) else []
    origin = get_origin(annotation)
    if origin is None:
        return []
    found: list[tuple[str | None, type[BaseModel]]] = []
    if origin is Union or origin is UnionType:
        for arg in get_args(annotation):
            if isinstance(arg, type) and issubclass(arg, BaseModel):
                found.append((arg.__name__, arg))
            else:
                found.extend(_nested_models(arg))
        return found
    for arg in get_args(annotation):
        found.extend(_nested_models(arg))
    return found


def _unbounded_warnings(
    model: type[BaseModel],
    owner: str,
    prefix: str = "",
    seen: frozenset[type[BaseModel]] = frozenset(),
) -> list[str]:
    """Lint every field for an unbounded scalar domain, recursively.

    Nested settings models — union arms of a discriminated union, plain
    sub-models, models inside containers — are walked too, so the bounded
    rule applies to every field of every arm. ``seen`` breaks cycles in
    self-referential models.
    """
    if model in seen:
        return []
    seen = seen | {model}
    warnings = []
    for field_name, info in model.model_fields.items():
        path = f"{prefix}{field_name}"
        annotation = info.annotation
        if get_origin(annotation) is None and annotation in (int, float, str) and not info.metadata:
            warnings.append(
                f"{owner}: field '{path}' has an unbounded "
                f"{annotation.__name__} domain — add Field constraints, a Literal/Enum, "
                "or a justifying comment (docs, bounded-settings rule)"
            )
        for arm, nested in _nested_models(annotation):
            nested_prefix = f"{path}[{arm}]." if arm else f"{path}."
            warnings += _unbounded_warnings(nested, owner, nested_prefix, seen)
    return warnings


def _check_stage(cls: type[Stage]) -> ComponentCheck:
    check = ComponentCheck("stage", cls.name)
    check.warnings += _unbounded_warnings(cls.settings_model, f"stage '{cls.name}'")
    directory = _component_dir(cls)
    if directory is None:
        check.problems.append("component module has no locatable directory")
        return check
    modules = _test_modules(cls, directory)
    if not modules:
        check.problems.append(
            f"no mandated test file (test_*.py / *_test.py) in {directory}"
        )
        return check
    conforming = False
    for path, module in modules:
        if isinstance(module, Exception):
            check.problems.append(f"{path.name}: import failed: {module}")
            continue
        stage_obj = getattr(module, "STAGE", None)
        settings_obj = getattr(module, "EXAMPLE_SETTINGS", None)
        if stage_obj is None or settings_obj is None:
            continue
        if stage_obj is not cls:
            check.problems.append(f"{path.name}: STAGE is not the {cls.name} class")
            continue
        try:
            cls(dict(settings_obj))
        except Exception as exc:  # noqa: BLE001
            check.problems.append(f"{path.name}: EXAMPLE_SETTINGS does not validate: {exc}")
            continue
        if not _has_test_function(module):
            check.problems.append(f"{path.name}: no test_* functions found")
            continue
        conforming = True
    if not conforming and not check.problems:
        check.problems.append(
            "no test module declares module-level STAGE and EXAMPLE_SETTINGS"
        )
    return check


def _check_handler(cls: type[Handler]) -> ComponentCheck:
    check = ComponentCheck("handler", cls.name)
    check.warnings += _unbounded_warnings(cls.resources_model, f"handler '{cls.name}'")
    directory = _component_dir(cls)
    if directory is None:
        check.problems.append("component module has no locatable directory")
        return check
    if not any((directory / "example_data").glob("**/*")):
        check.problems.append(
            f"no committed example data under {directory / 'example_data'}"
        )
    modules = _test_modules(cls, directory)
    if not modules:
        check.problems.append(
            f"no mandated round-trip test (test_*.py / *_test.py) in {directory}"
        )
        return check
    conforming = False
    for path, module in modules:
        if isinstance(module, Exception):
            check.problems.append(f"{path.name}: import failed: {module}")
            continue
        handler_obj = getattr(module, "HANDLER", None)
        resources_obj = getattr(module, "EXAMPLE_RESOURCES", None)
        coords_obj = getattr(module, "EXAMPLE_COORDS", None)
        if handler_obj is None or resources_obj is None or coords_obj is None:
            continue
        if handler_obj is not cls:
            check.problems.append(f"{path.name}: HANDLER is not the {cls.name} class")
            continue
        try:
            cls(dict(resources_obj))
        except Exception as exc:  # noqa: BLE001
            check.problems.append(f"{path.name}: EXAMPLE_RESOURCES does not validate: {exc}")
            continue
        if set(coords_obj) != set(cls.dimension_roles):
            check.problems.append(
                f"{path.name}: EXAMPLE_COORDS keys {sorted(coords_obj)} do not match "
                f"the declared roles {sorted(cls.dimension_roles)}"
            )
            continue
        if not _has_test_function(module):
            check.problems.append(f"{path.name}: no test_* functions found")
            continue
        conforming = True
    if not conforming and not check.problems:
        check.problems.append(
            "no test module declares module-level HANDLER, EXAMPLE_RESOURCES "
            "and EXAMPLE_COORDS"
        )
    return check


def check_package(package: str) -> ConformanceReport:
    """Load a package's components and shape-check every one of them."""
    load_package_components(package)
    components = _package_components(package)
    if not components:
        raise DefinitionError(
            f"package '{package}' registered no components — is every component "
            "imported in its components.py collector module? (a missing import "
            "fails silently; this check is how it gets caught)"
        )
    checks: list[ComponentCheck] = []
    for axis, cls in components:
        checker: Any = _check_stage if axis == "stage" else _check_handler
        checks.append(checker(cls))
    return ConformanceReport(package=package, components=checks)
