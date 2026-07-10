# PACKAGE_AUTHORING.md — The anatomy of a Rainspout content package

A **content package** is an ordinary installable Python package that ships
concrete stages and handlers (plus configs, optional CLI verbs, optional
lifecycle/artifact code, and tests) conforming to the Rainspout contracts.
Installing it — including `uv add --editable ./my-package` during development —
makes its components discoverable with **no manual imports and no registry
edits**. The core never knows your package exists until entry points reveal it.

## The short version

Your stages and handlers live in a normal Python package that you own. Two
lines in its `pyproject.toml` tell Rainspout where to look; from then on,
installing your package is all it takes for `spout` to find every component
in it. Each stage and each handler is one self-contained directory — code,
test, and example data together — so a component can be reviewed, copied, or
deleted as a unit. Your package runs its own test suite and CI; Rainspout
only ever checks that the mandated tests exist and have the right shape.

## 1. What a package ships

| Contents | Required? |
|---|---|
| Stages (each one self-contained directory, STAGE_AUTHORING §10) | at least one stage or handler |
| Handlers (each one self-contained directory with example data, HANDLER_AUTHORING §12) | 〃 |
| Example/production configs | recommended |
| Package-contributed CLI verbs (`spout <package> <verb>`) | optional |
| Lifecycle commands + the artifacts they produce (§6) | optional |
| Conforming tests + its own CI enforcing coverage (§7) | required |

## 2. Proposed package layout

*(This layout is this document's decision, made from first principles; the
skeleton does not parse your layout — only entry points and the per-component
directory shapes are contractual.)*

```
my-package/
├── pyproject.toml                  # metadata + entry points (§4)
├── uv.lock                         # committed
├── README.md
├── .github/workflows/ci.yml       # from the skeleton's CI template (§7)
├── src/my_package/
│   ├── __init__.py
│   ├── components.py               # imports every stage/handler module (§4)
│   ├── stages/
│   │   ├── smooth_readings/        # one stage = one self-contained directory
│   │   │   ├── __init__.py
│   │   │   ├── stage.py
│   │   │   ├── science.py
│   │   │   └── test_smooth_readings.py
│   │   └── .../
│   ├── handlers/
│   │   ├── readings_local_csv/     # one handler = one self-contained directory
│   │   │   ├── __init__.py
│   │   │   ├── handler.py
│   │   │   ├── example_data/...
│   │   │   └── test_roundtrip.py
│   │   └── .../
│   ├── configs/
│   │   └── example_run.yml
│   ├── cli.py                      # Typer app with package verbs (optional)
│   └── lifecycle/                  # train/simulate/build implementations (optional)
└── tests/                          # package-LEVEL tests only (§3)
    └── test_integration.py
```

Rationale: `stages/` and `handlers/` mirror the two authoring contracts
one-to-one, so a contributor holding STAGE_AUTHORING or HANDLER_AUTHORING can
find and copy the right shape instantly; everything contractual is inside the
component directory, so the directory *is* the unit of review, copying, and
conformance-checking.

## 3. Where tests live — decided: inside the component's directory

A component's mandated test (the stage test, the handler round-trip test) lives
**inside that component's own directory**, not in a shared `tests/` tree.

Why: self-containment is the entire point of the one-directory rule — copying
`stages/smooth_readings/` must carry its contract, and the test *is* the
executable half of that contract (alongside `EXAMPLE_SETTINGS` /
`EXAMPLE_RESOURCES`, which double as working documentation). It also makes the
skeleton's static conformance check purely local (inspect one directory), and
makes orphaned tests impossible — deleting a component deletes its test. The
cost — test code shipping inside `src/` — is real but small at these sizes, and
the code-hash/version-bump boundary already excludes `test_*.py` files, so
test edits never force version bumps.

The package-level `tests/` directory is reserved for what genuinely spans
components: integration tests wiring several stages together, config
round-trips, verb tests. Pytest collects both locations; CI runs both.

## 4. Registration via entry points

Two entry-point groups, declared in `pyproject.toml`. The group names
(`"rainspout.components"`, `"rainspout.verbs"`) and the dependency pin are
the contract; every `my_package`/`my-package` is a placeholder for your
package's name:

```toml
[project]
name = "my-package"
dependencies = ["rainspout>=1,<2"]

[project.entry-points."rainspout.components"]
my_package = "my_package.components"

[project.entry-points."rainspout.verbs"]        # optional
my_package = "my_package.cli:app"
```

- **`rainspout.components`** points at one module whose only job is to import
  every stage and handler module — importing triggers the `__init_subclass__`
  registration; nothing else is needed:

  ```python
  # src/my_package/components.py
  from my_package.stages.smooth_readings import stage as _
  from my_package.handlers.readings_local_csv import handler as _
  ```

  The skeleton loads this entry point at startup; a collision (two packages
  registering the same component name) fails loudly, naming both packages.

  Two discovery facts to internalize:

  - **Adding a component to an existing `components.py` is live** — the next
    `spout` invocation sees it. But adding or changing an *entry point* in
    `pyproject.toml` requires a re-install (`uv sync`) before the skeleton can
    discover it.
  - **A component missing from the collector module fails SILENTLY** — it
    simply never registers; nothing errors until a config asks for it. Every
    component in your package must be imported in `components.py`. Verify with
    `spout catalog` after adding one: if it isn't listed, it isn't registered.
    Mark each collector import `# noqa: F401` (or exempt the file in your
    linter config): linters see them as unused and will otherwise auto-remove
    them — deleting your registrations without a word.

- **`rainspout.verbs`** (optional) points at a Typer app. It is mounted as
  `spout <entry-point-name> <verb>` — e.g. `spout my_package train`. The
  entry-point name is the mount name; keep it equal to your package's import
  name.

## 5. Package-contributed CLI verbs

Verbs are for operations that belong to your domain but not inside a DAG run:
training, simulating, migrating a data layout, inspecting domain files. A verb
is a plain Typer command; it may use your package's code freely and load/save
through your own handlers. Verbs must not reach into skeleton internals — if a
verb needs pipeline execution, it should shell out to (or instruct the user to
run) `spout run` with a config.

## 6. Lifecycle commands and artifacts

Some stages need a **prepare phase** before they can process data — train a
model, run simulations to build a grid, calibrate. These are ordinary
package verbs (`spout my_package train --config …`), and their products are
**artifacts**: versioned inputs like any other data. The pattern:

1. The lifecycle verb writes the artifact **through a handler** (yours), with a
   version identifier in its dimension coordinate or its metadata.
2. The consuming stage declares a `Handler` dependency wired `handler:` to
   that artifact's instance and loads it at run time with coordinates the
   stage chooses (the artifact version can come from a bounded setting) —
   mid-DAG handler dependencies are normal (STAGE_AUTHORING §5).
3. The artifact's version thereby lands in the provenance chain of everything
   computed from it.

There is no other artifact machinery — no special registry, no special config
section. If you can load it through a handler, it's an artifact.

## 7. Tests, coverage, CI

- Every stage and handler ships its mandated test (formats in the two authoring
  docs). The skeleton **statically verifies these exist and conform** when your
  package is loaded and via `spout test-package my_package` — a cheap shape
  check, not a test run.
- **Coverage is enforced in your package's own CI**, not by the skeleton at
  load time. Use the skeleton's CI template: ruff + mypy + pytest with
  `--cov-fail-under=90` (aim 95%+), plus the stage version-bump check.
  `# pragma: no cover` only with a justifying comment.
- `spout test-package my_package` runs your full test suite + coverage on
  demand in the current environment — the same thing your CI runs.

## 8. Development workflow

```
uv add --editable ./my-package     # live-develop against a local core checkout
spout validate --config src/my_package/configs/example_run.yml
spout test-package my_package
```

Editable installs are local-environment links only; git tracks your package
independently, and the package can move to its own repository unchanged once
its contracts stabilize — nothing in the skeleton knows or cares where the
package lives.

## 9. What NOT to do

- Don't import from `rainspout` internals — only `rainspout.contracts` and
  `rainspout.testing` are yours. Both carry the same v1 **stability
  commitment**: the helpers (`run_stage`, `from_handler_data`,
  `assert_roundtrip`) and the mandated module-level names are an API your
  package may pin to for the life of `rainspout>=1,<2`. The authoring docs are
  the API; private modules can change under you without notice.
- Don't import from *other content packages* — packages must coexist without
  knowing about each other. Shared science belongs in an ordinary library both
  depend on.
- Don't hand-register anything, anywhere.
- Don't put science in `components.py`, verbs, or config — science lives in
  stages' module-level functions.
- Don't ship components whose mandated tests are missing or nonconforming —
  the static check will fail your package at load.
- Don't bypass handlers in lifecycle verbs by writing artifact files directly —
  an artifact that can't be loaded through a handler can't carry provenance.

## 10. Self-check

- [ ] Entry point `rainspout.components` present; importing it registers every
      component; `spout catalog`/`validate` can see them after `uv add`.
- [ ] Every stage: self-contained directory + mandated test inside it.
- [ ] Every handler: self-contained directory + example data + round-trip test.
- [ ] Verbs (if any) mounted under your package name and free of skeleton
      internals.
- [ ] Lifecycle artifacts (if any) written and read through handlers.
- [ ] CI: ruff, mypy, pytest, `--cov-fail-under=90`, version-bump check — green.
- [ ] `spout test-package my_package` passes in a clean environment.
- [ ] No imports of skeleton internals or other content packages anywhere.
