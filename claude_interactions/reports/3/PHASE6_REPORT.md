# Phase 6 report — CLI complete + the package seam

**Done.** 208 tests passing (20 new), coverage 93.6% against the 90% floor,
ruff + mypy clean. Every planned verb exists and works against real content.
Stopped at the end of the phase.

## What was built

**`spout catalog`** — two modes, matching what the docs promised:
- No `--config`: lists the **registry** (every discovered stage and handler) —
  the "if it isn't listed, it isn't registered" check from PACKAGE §4.
- With `--config`: surveys the run window through the seed (default) or a
  named `--handler` instance *that carries a dimensions map* (save targets);
  asking to survey a stage-callable instance fails with the explanation that
  those are asked for coordinates by their stage, not by the run window.
  `--write` additionally emits the validated catalog file.

**`spout setup`** — full validation, then every stage's setup hook in
topological order, reported per stage.

**Package-contributed verbs** (`cli/_mount.py`) — the `rainspout.verbs`
entry-point group: each entry point must resolve to a Typer app, mounted as
`spout <entry-point-name> <verb>`. Mount-name collisions fail loudly naming
both packages; a non-Typer payload fails naming the entry point. Tested with
a fake entry point: `spout mypkg train` runs the package's command.

**`spout test-package <pkg>`** — the package seam made checkable:
- **Static conformance** (`conformance.py`): loads the package's collector
  (entry point, with a plain `<pkg>.components` import fallback for dev
  setups), finds every component the package registered, and shape-checks
  each one — mandated test file present in the component's directory;
  module-level `STAGE`+`EXAMPLE_SETTINGS` / `HANDLER`+`EXAMPLE_RESOURCES`+
  `EXAMPLE_COORDS` present and **validating through the real constructors**;
  `EXAMPLE_COORDS` keys matching the declared roles; example data committed;
  at least one `test_*` function. Plus the **bounded-settings lint warning**
  for bare unconstrained `int`/`float`/`str` fields, as the docs promised.
  A package whose collector imports nothing gets the dedicated message for
  the silent-failure mode ("registered no components — is every component
  imported in components.py?").
- **Then the package's own pytest suite** runs in a subprocess against the
  package directory (skippable with `--static-only`); exit code passes
  through. Verified end-to-end: the test builds a complete fake content
  package on disk — shaped exactly like PACKAGE_AUTHORING §2, one stage +
  one JSON-cell handler with example data and both mandated tests — and
  `spout test-package` conformance-checks it, surfaces the lint warning, and
  runs its 3-test suite green. Broken variants (missing test file, missing
  mandated names, invalid EXAMPLE_SETTINGS, wrong EXAMPLE_COORDS, missing
  example data) each fail with the specific named problem.

**`spout build-image`** — v1-minimal per Gate 1 Q6: writes a Dockerfile
pinning the current Python line, the installed `rainspout` version, and every
installed content package (anything providing a `rainspout.components`/
`rainspout.verbs` entry point) at its installed version, with a header noting
that editable/local packages need their pin swapped for a source line.
`ENTRYPOINT ["spout"]`. Deliberately nothing cleverer.

## Done-criterion check

Every verb works against real content ✓ (catalog surveys the same CSV-backed
run the driver tests use; setup reports hooks; build-image emits a valid
pinned Dockerfile). A package-contributed verb mounts and runs ✓.
`test-package` passes a conforming package — including actually running its
suite — and fails each nonconforming variant with a named offender ✓.

## A note worth recording

The fake package the tests build is, in effect, a first draft of Phase 7's
pedagogical example package — and building it from scratch against
`rainspout.contracts` + `rainspout.testing` alone required **zero** changes
to the skeleton, which is a small early signal for the blind-authorability
thesis before Phase 9 tests it for real.

**STOP — end of Phase 6.** Next on approval: Phase 7 — the adversarial
reference package under `tests/` (mid-DAG `handler:` dependency + observable
setup-hook exercise), the clean example package under `examples/` with
entry-point registration, and the skeleton's GitHub Actions CI (ruff + mypy +
pytest + coverage floor + the stage version-bump check, plus the CI template
packages copy). Suggested review gate after Phase 7, per the roadmap.
