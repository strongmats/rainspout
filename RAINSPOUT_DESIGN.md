# Rainspout — Consolidated Design Document (v2)

> **Rainspout** is a general-purpose scientific data-processing pipeline *framework*
> (the skeleton). It is domain-agnostic. **SkyCT** — the VLF ionospheric-tomography
> work — is one *content package* built on top of Rainspout, not the framework itself.
> The distribution/import name is `rainspout`; the CLI command is `spout`.

> This document is the **single consolidated source of truth**: the original design
> document with every decision from the Gate 1 review, the Gate 2 review, the Gate 2b
> question round, the Gate 2c corrections, and the Phase 1 review folded in. It
> supersedes the layered prompt-2 document + response stack. The authoring documents
> under `docs/` are the *normative developer-facing contract*; this document is the
> design rationale and decision record behind them. Where they could ever disagree,
> `docs/` governs component authors and this document governs the skeleton's builders —
> and the disagreement is a bug to be reported.

---

## A. Foundational philosophy

- A reusable **skeleton/shell** that scientific (or other) processing pipelines are
  built on top of. The skeleton contains **no science**.
- **Separate "what / where / how."** Stages (what computation), handlers (where data
  lives and how it is read/written), dimensions/driver (over what the run sweeps) —
  each independent, none leaking into the others.
- **Break loudly, early.** Every misconfiguration fails at startup with a specific,
  actionable message naming the offender — never a silent wrong result or a deep
  runtime crash.
- **Declared-in-code, validated-against-config.** Everything a component needs is
  declared in code and checked against config before any data moves.
- **Blind-authorable contracts.** Someone with only an authoring doc (no skeleton
  access) can build a conforming component. The docs are the literal API boundary.
- **Documentation-driven design.** The authoring standards were written FIRST (Gate 2)
  and define the interface; the machinery is built to satisfy them.
- **Deep-validate cheap things (settings); cheap-check expensive things (data).**
- **The skeleton is dimension-agnostic; stages are coordinate-aware.** No dimension
  name is hardcoded anywhere in Rainspout — names come from the run config. Stages
  *read* their work-item coordinate freely (position-dependent science is legitimate)
  but never forge or alter it. *(Gate 2 Part B, replacing the earlier
  "stages are dimension-blind" over-application.)*
- **Presence-and-wiring is the guarantee boundary for handler dependencies.** The
  skeleton guarantees a stage that its declared dependencies are satisfied and
  reference real, validly-configured components — exactly parallel to what it
  guarantees for settings. How the stage *uses* a handler it was handed is private
  and trust-based; misuse is an isolated runtime failure. *(Gate 2c.)*

---

## B. Core / content split (plugin architecture)

- **`rainspout` (the skeleton):** the brain (registry, config, validation, runner,
  driver, two logging systems, CLI), the base-class contracts, and the authoring
  standards. No science, no real handlers, no real stages.
- **Content packages** (e.g. `skyct`): concrete stages + handlers + example configs
  (+ optional package CLI verbs + lifecycle/artifact commands), obeying the contracts
  and registering via **entry points**. Multiple packages coexist without knowing
  about each other.
- **The authoring docs are the inter-repo contract** and a first-class deliverable;
  they live in `docs/` at the repo root (canonical home), written to be readable by a
  newcomer (plain-language overview + glossary in `docs/README.md`, a "short version"
  preamble on each standard).
- **Public API surface = `rainspout.contracts` + `rainspout.testing`, nothing else.**
  Both carry a v1 **stability commitment** (packages pin `rainspout>=1,<2`); private
  modules may change without notice. *(Gate 2 #9.)*
- **Installable packages** via entry points (not drag-drop folders); editable installs
  (`uv add --editable ./pkg`) for live development; a package can move to its own repo
  unchanged once its contracts stabilize.

---

## C. Handlers (the collapsed IO axis)

- **Combined handlers** replace freely-mixed Storage×Codec: each handler is ONE fixed
  combination of {file type, in-file structure, filename convention, folder structure,
  access channel}, killing the N×M testing burden.
- **Naming:** `datatype_channel_type` — **underscores only, no dots** (e.g.
  `broadband_local_mat`) *(Gate 1 C1)*. Purely conventional, never parsed; the
  registry enforces `^[a-z][a-z0-9_]*$` on every axis.
- **Author surface = private hooks; public verbs are final.** *(Gate 2 #1.)* Authors
  implement `_load_cell` / `_save_cell` / `_catalog_cells` (+ optional `_probe`,
  `_check_structure`); the base class owns final `load`, `load_one`, `save`,
  `catalog`, `preflight`, whose docstrings document exactly what they do around the
  hooks (range expansion, lazy per-cell iteration, single-cell-save enforcement,
  error wrapping). Finality is enforced at class definition *and* against
  post-definition monkey-patching *(Phase 1 review)*.
- **One input shape.** Every verb takes a dimension spec `{role: (values…)}`; a
  single value is a tuple of one. **The driver expands config ranges before any
  handler call** — handlers never parse range syntax *(Gate 2 #2)*. `load(spec)`
  returns a lazy per-cell iterator of `Cell(coords, data, meta)`. **`load_one(coords)`**
  is a final base convenience — exactly `load` with a one-value spec, returning
  `(data, meta)` directly — and is what stages typically call on an auxiliary handler.
- **Dimension roles.** A handler declares `dimension_roles` + `dimension_types` — the
  whole dimension vocabulary it knows, named before any config exists. Configs map
  their dimension names onto roles; everything the handler receives is keyed by role.
- **Two positions, one contract.** *(Gate 2 Part B4; presentation confirmed in the
  Phase 1 review: one concept, two entry points, not two species.)*
  - **Seed handler** — named in the config's `seed:` block; the driver coordinates
    with it per work item. Rigorously validated at startup: mapped roles ↔ iterated
    dimensions exactly, types coercible, then the pre-flight probe.
  - **Auxiliary handler** — handed to a stage as a `handler:`-wired dependency; the
    **stage** computes the coordinates it asks for (via `load_one`/`load`), along
    axes that by default should be assumed **unrelated** to the run's dimensions.
    Not dimension-validated at startup; fitness proves out at runtime, isolated per
    work item. *(Gate 2c #4.)*
- **Two INDEPENDENT range concepts**, both default-off, declared honestly:
  1. **Dimension-grid range** (`supports_grid_range`) — multi-cell `load` specs;
     always served lazily per cell. A range asked of a non-range handler fails at
     startup when the ask comes from the run's own wiring, or at call time (that work
     item only) when a stage asks; `load_one` in a loop works against every handler.
  2. **Within-file windowing** (`supports_windowed_read`) — serve a slice inside one
     stored file without materializing it (HDF5/memmap territory); window-argument
     semantics are handler-defined and documented. Kept visibly distinct from
     `LazyReference.window()` (inter-stage, in-flight) — both docs carry "not to be
     confused with" notes *(Gate 1 Q8)*.
- **`catalog` surveys only the asked window** *(Gate 1 Q2)* — real-time polls make
  unbounded surveys unaffordable; report a cell only if a load would plausibly
  succeed (cheapest test, no deep validation); yield lazily; optional catalog file
  (validated JSON: handler, roles, entries `{coords, extras}`, generated-at) written
  by the base class.
- **All structural knowledge is handler-private.** Base directory down — folders,
  filenames, in-file layout, connections — opaque to the skeleton. **Lifecycle is
  private**: per-transaction by default; sessions managed internally; no external
  setup ordering.
- **Metadata: one file, no sidecars.** *(Gate 2 #6, replacing the sidecar fallback.)*
  The shared metadata block (schema version, `run_id`, coords, provenance chain) is
  embedded **in the data file itself**; the skeleton defines no sidecar convention
  and auxiliary metadata files are discouraged. Metadata handling is **optional**:
  a handler may deliberately ignore it (conforming, provenance-severing, must be
  stated in its docstring). Plain-text formats embed responsibly via one clearly
  delimited, strippable section (e.g. a single `# rainspout-meta: {…}` comment line —
  taught in Tutorial 1). Foreign/metadata-less data always loads with a fresh
  empty-provenance block.
- **Compression on save** where the format supports it.

---

## D. Stages

- **"Stage"** = one processing step (never "module", reserved for `.py` files).
- **Thin orchestrator.** Declarations + a short `run` calling module-level science
  functions (testable without the skeleton). More than ~a screen of `run` means
  science is leaking into the orchestrator.
- **Coordinate-aware, not dimension-blind.** *(Gate 2 Part B1/B2.)* Every reference a
  stage receives exposes `ref.coords`: the work item's read-only `{dimension: value}`
  mapping, stamped by the driver at seed time, flowing downstream automatically.
  Stages read it freely; they never forge or alter it (trustworthy provenance). Keys
  are the config author's dimension names, so a stage needing a specific axis takes
  the dimension name as a **bounded setting** (e.g. `time_dim: str = "time"`) rather
  than hardcoding it *(Gate 2b Q3)*.
- **Three strictly separated input kinds:**
  - **Settings** — static config, deep-validated (`settings_model`, `extra="forbid"`,
    frozen). **Every field bounded** (Field ranges / Literal / Enum / constrained
    strings); unbounded only as a justified, commented exception drawing a lint-style
    conformance warning. *(Gate 1 review addition.)*
  - **Dependencies** — named data inputs (`dependencies_model`); the field's **type
    annotation declares its wiring kind** *(Gate 2 #5)*: `LazyReference` ↔ `from:`
    (an upstream stage or the seed entry), `Handler` ↔ `handler:` (an instance from
    the `handlers:` block). Mismatches fail at startup naming stage + field.
  - **Resources** — a handler's fetch config; never a stage's concern.
- **Construction & injection.** *(Gate 2c #3.)* Stages construct nothing: the driver
  constructs each stage at validation time (settings through the un-bypassable base
  `__init__`), and per work item resolves and injects dependencies into `run` —
  `from:` fields as coordinate-stamped references, `handler:` fields as ready-to-call
  handler instances built from configured resources. This is also what makes stages
  testable (fakes injected through the same door).
- **No seed-loader stage.** *(Gate 2 Part B3.)* Data enters through the config's
  `seed:` block; the first stage wires `from: <seed_name>`. No package writes a
  pass-through loader.
- **Auxiliary handler use is private to the stage.** *(Gate 2c #4.)* The config says
  which handler; the stage decides what to load, deriving coordinates from
  `ref.coords`/settings as it sees fit — a window of cells is simply a loop over
  `load_one`. No skeleton binding, projection, or coordinate validation; loading is
  the only legitimate stage-side use (saving is config-designated). The formerly
  flagged "windowed loader" v1 limitation is dissolved by this model.
- **Setup hook** — `setup()`, idempotent, after validation, before any work item;
  `spout setup` runs all of them.
- **Status / progress / warnings / errors:** mandatory `set_status` (≥once per run);
  optional-but-recommended `progress()` (None where totals are unknowable); warnings
  via `add_warning` (output still valid; recorded; still counts as succeeded);
  errors are exceptions (prefer `StageError`) — fail this (stage, work item),
  skip its downstream for this work item only, continue the run. Cheap shape/type
  checks only; never deep per-element validation.
- **Versioning:** required `version`, bumped on ANY stage-code edit. Enforced by a
  CI diff check; backstopped by a code hash recorded in every provenance entry.
  **Code/test hash boundary** *(Gate 1 Q4 + Gate 2 #7)*: `test_*.py`, `*_test.py`,
  `fixtures/`, `example_data/` are excluded from the hash and the bump requirement.
- **One stage = one self-contained directory** *(Gate 1 Q4)* — class, science
  modules, fixtures, and its mandated test together; interior structure free;
  copying the directory into another package (plus a registration import) works
  unchanged.

---

## E. Config, DAG, driver, dimensions

- **One `.yml` file per run; six top-level keys** (`run`, `dimensions`, `iteration`,
  `seed`, `handlers`, `stages`); unknown keys rejected; examples written in YAML
  block form *(Gate 2c #2)*.
- **`seed:` — named entries.** *(Gate 2 Part B3 + Gate 2b Q1.)* Each entry gives a
  registry handler, resources, and a role map; the driver loads the seed cell per
  work item, stamps the coordinate, and offers it under the entry's name (`from:
  raw`). Seed names share the upstream namespace with stage instance names.
  **Exactly one entry in v1** — a second fails loudly — but the plural shape makes
  multiple seeds (future branching: sferic + transmitter → tomography) a non-breaking
  addition.
- **`handlers:` — named instances for the two other storage touchpoints:**
  stage-callable inputs (`handler:`-wired dependencies; **no role map** — the stage
  computes its own coordinates) and save targets (**role map required**, held to the
  seed's standard: complete, onto the iterated dimensions, startup-checked, because
  the driver writes at work-item granularity). A `dimensions:` map anywhere may only
  name declared dimensions — a pure dangling-reference check that **never** compares
  config names to handler-internal names *(Gate 2b Q4)*.
- **The same `handler:` key wires inputs and saves** — direction comes from
  `dependencies:` vs `save:`, never from the key name *(Gate 2c #1; `loader:` is
  dead vocabulary)*.
- **Dimensions**: named axes, list form (order preserved, duplicates rejected) or
  inclusive `start/stop/step` ranges (numeric, or date/datetime with `1d`/`6h`/`30m`/
  `15s` steps), expanded by the driver. Dimension names are the config author's
  bookkeeping *(Gate 2 Part B6)* — enforced only at the seed edge and save targets,
  via mappings; no stage-declared "expected dimensions" (deliberately rejected).
- **A work item** = one point in the dimension cross-product; the whole DAG runs once
  per work item at one granularity. **No mid-DAG collapsing** — aggregation across a
  dimension is a separate run with a different config reading what this one saved.
- **Linear chains in v1, general machinery underneath.** *(Gate 2 Part B5.)* The
  runner/validator use general graph machinery (topological sort, dependency
  resolution); the v1 single-chain restriction (seed → stage → … → stage) is a
  distinct, loud validation rule, not an assumption baked into the code — branching
  later is non-breaking.
- **Retrograde and real-time are one mechanism.** The **delta** =
  `exists − attempted` *(Gate 1 Q1)*: the seed's `catalog` minus every work item in
  the operational log, success **or** failure — poison inputs are not hammered.
  Retrograde drains the delta once; realtime drains, sleeps `poll_frequency`
  (required iff realtime, forbidden otherwise), recomputes, forever; never polls
  mid-run. Clean stop *(Gate 1 Q9)*: Ctrl-C/SIGTERM between work items finishes the
  current item, flushes the log, exits 0; a mid-item interrupt just never records
  success, so resume redoes it.
- **Re-run controls** *(Gate 2 #11 + Gate 2b Q2)*:
  - `--retry-failed` re-queues **failed** cells only; never touches succeeded ones.
  - `--select dim=value` narrows the space first, then the log is subtracted as
    usual (an attempted selected cell is still skipped); composes with
    `--retry-failed` to re-queue exactly the selected failures.
  - `--force-rewrite` — the separate, bluntly named flag that re-runs **succeeded**
    cells (overwriting good output), usually with `--select`. Never overloaded onto
    `--retry-failed`.
- **Failure isolation per work item**; **sequential in v1** (work items independent,
  future parallelism preserved).
- **Config-designated saving**: any stage, anywhere in the DAG, may carry
  `save: {handler: <instance>}`; only saved outputs persist; everything else stays
  lazy/in-memory and is discarded per work item. A save is the output-symmetric
  mirror of the seed (both driver-operated, both role-mapped).
- **Lazy inter-stage passing**: stages exchange `LazyReference`s; `get()` universal,
  `window()` an advertised capability; materialization on demand; contract first
  even where v1 passes in-memory objects underneath.

---

## F. Logging, provenance, resume

- **Two systems, never merged:**
  - **Operational log** — keyed per (stage, work item): ran/succeeded/failed,
    warnings/errors, timestamps. Source of truth for resume.
  - **Provenance chain** — travels WITH the data: ordered
    `{stage_name, stage_version, code_hash, settings_used, timestamp}` entries,
    persisted inside the metadata block on every save. Scientific reproducibility.
- **Identity:** `run_id` per run (`<name>-<UTC stamp>-<suffix>`) + a per-work-item
  sub-key (`cell_id`, the canonical serialized coordinate,
  `day=2026-01-01|sensor=s1`) threading through log records, provenance entries,
  and saved metadata. *(Gate 1 §3.5; confirmed in the Phase 1 review.)*
- **The log follows the run definition** *(Phase 4 review → Phase 5 decision)*:
  default location `.rainspout/<run.name>.oplog.jsonl` **next to the config
  file**, overridable with the optional `run.oplog:` key (relative paths resolve
  against the config's directory). Never derived from the working directory —
  the resume/delta story requires that a later run always finds the history it
  must subtract; anchoring to the run definition makes that automatic, and a
  deliberate `run.name` change starts a fresh history.
- Warnings ⇒ succeeded (skipped on resume). Failures ⇒ not re-run by default
  (`--retry-failed` is the escape hatch). Definition errors ⇒ fatal before any data.

---

## G. Settings & validation (cross-cutting)

- **Pydantic v2 everywhere**, `extra="forbid"`, frozen after validation.
- **Un-bypassable validation:** the base `__init__` validates; subclasses may not
  define `__init__` (class-definition-time check; mixins with `__init__` rejected);
  post-definition monkey-patching of `__init__` or final methods is blocked by the
  contract metaclass and covered by negative tests *(Phase 1 review)*. Post-validation
  init goes in `setup()`.
- **`run` = `validate` + execution; no skip path.** Gates in order: (1) config parse,
  (2) registry resolution, (3) seed rule, (4) DAG validation (wiring kinds, dangling
  references, acyclicity, v1 linearity), (5) per-component settings/resources
  validation. All definition-time, instant, touching no data.
- **Startup pre-flight probe — seed only.** *(Gate 1 review + Gate 2 #4.)* Steps:
  (1) role-map check, (2) type check from `dimension_types`, (3) structural probe on
  the first cataloged cell in the run window — default `_probe` = full load +
  `_check_structure`, overridable where loads are expensive, (4) empty catalog ⇒
  probe skipped with a loud logged notice (legitimate in realtime). Auxiliary
  instances get resources validation only. **Deliberately NO inter-stage structural
  checks** — a wrong structure between stages is an isolated per-work-item runtime
  failure; validate the storage edges strictly, never burden the internal seams.
- **Every failure mode has a named-offender message:** bad/out-of-range setting;
  missing/extra/misspelled dependency; wrong wiring kind; `from:` → nonexistent
  upstream; DAG cycle; branching in v1; bad handler resources; malformed config;
  unknown registry key (listing known keys); seed role-map miss; uncoercible
  dimension values; save target without/with-incomplete role map; multiple seeds;
  seed/stage name collision; `poll_frequency` misuse; range on a non-range handler;
  unbumped version.

---

## H. Registration & discovery

- **One uniform gesture on every axis:** subclass the contract base with a `name` —
  `__init_subclass__` validates the whole class-level contract and registers it.
  Missing/invalid/duplicate names fail at import naming the class (duplicates name
  both parties). The registry maps name → class per axis and is never hand-edited.
- **Entry points:** `rainspout.components` (one collector module per package;
  import = registration; collisions fail loudly naming both packages) and
  `rainspout.verbs` (a Typer app; mount name = entry-point name). *(Gate 2 #10.)*
  Two documented discovery facts: entry-point changes need `uv sync` (collector-module
  additions are live), and a component missing from the collector fails **silently** —
  verify with `spout catalog`.

---

## I. CLI

- **Philosophy:** clean, composable commands; the user's cron/sbatch/Docker
  orchestrates. Orchestration is out of scope.
- **Verbs:** `run` (with `--dry-run` planning, `--select`, `--retry-failed`,
  `--force-rewrite`), `validate` (definition-only, instant), `catalog`, `setup`,
  `build-image` (v1-minimal: Dockerfile from `uv.lock` + installed entry-point
  packages, nothing cleverer — *Gate 1 Q6*), `test-package`, plus
  **package-contributed verbs** (`spout <package> <verb>`).

---

## J. Lifecycle commands & artifacts (the dissolved "sims")

- Packages may ship lifecycle verbs (`train`, `simulate`, `build`, `calibrate`)
  producing **artifacts** — versioned inputs written **through a handler**, loaded by
  a consuming stage as an ordinary `handler:` dependency (artifact version via a
  bounded setting), its version landing in provenance. No separate machinery.

---

## K. Testing & coverage

- **Skeleton:** 90% coverage floor (aim 95%+), `--cov-fail-under=90`, hard-failing
  CI; `# pragma: no cover` only with justification — and enforcement paths are
  covered by **negative tests**, never exempted *(Phase 1 review)*.
- **`rainspout.testing` is public, stable API** *(Gate 2 #9)*: `run_stage` (real
  validation path; wraps deps; optional `coords=`), `from_handler_data` (fake handler
  whose `load_one` returns the object for any coordinates), `assert_roundtrip`
  (load → save → load → equal → catalog; float-tolerant; `equal=` escape hatch;
  checks **preservation of whatever exists** — data always, metadata iff the handler
  claims it; never fails a handler merely for ignoring metadata).
- **Mandated test shapes**, statically shape-checked at package load (cheap; no
  coverage measurement at load): stages ship `STAGE` + `EXAMPLE_SETTINGS` + a
  known-output test + a failure-path test; handlers ship `HANDLER` +
  `EXAMPLE_RESOURCES` + `EXAMPLE_COORDS` + the round-trip test + tiny committed
  example data. Tests live **inside the component's directory** *(Gate 2 #8)*;
  package-level `tests/` is integration-only. Package coverage is enforced in the
  package's own CI (skeleton CI template; `spout test-package` on demand).
- **Reference content vs example package:** skeleton `tests/` reference content is
  adversarial and machinery-proving — including a mid-DAG extra `handler:` dependency
  and a trivial, observable setup-hook exercise (**no Cython/C toolchain in CI** —
  *Gate 1 Q7*). The clean example package teaches a user and is the yardstick for
  **blind-agent verification**: a separate agent with only `docs/` + scientific code
  must produce a conforming, runnable package.

---

## L. Tooling

uv (lock committed) · Typer · Pydantic v2 · structlog (`run_id`-threaded) · pytest +
pytest-cov · ruff + mypy · GitHub Actions (lint, type, test, coverage, version-bump).
Content-package territory: h5py/scipy, ONNX Runtime, Docker (`build-image` target).

---

## M. Build status (the gated process, as executed)

1. **Gate 1** — plan + restatement + proposed answers: delivered, approved with
   corrections (reports/1, prompts/2).
2. **Gate 2** — authoring docs + tutorials: delivered (reports/2), approved with
   corrections (prompts/3), revised through 2b (question round) and 2c (config
   naming + auxiliary model); `docs/` at the repo root is the canonical set.
3. **Phase 1 — contracts & registry: DONE** (approved with one required change,
   satisfied: negative tests + metaclass guard for the `__init__` invariant).
4. **Phase 2 — config & DAG validation, `spout validate`: DONE** (this document
   accompanies its delivery).
5. **Phase 3 — handlers & data plane: DONE** (verb bodies, metadata/provenance
   models, `rainspout.testing`).
6. **Phase 4 — runner: DONE** (approved; oplog-location question answered in
   Phase 5: the log follows the run definition, §F).
7. **Phase 5 — driver + `spout run`: DONE**.
8. **Phase 6 — CLI complete (catalog/setup/test-package/build-image, package
   verbs): DONE**.
9. **Phase 7 — reference content + example package + CI: DONE** (system
   complete to v1 scope; review gate passed).
10. **Phase 8 — literal tutorial verification: DONE.** All three tutorials
    executed step-for-step in a clean environment against the built system;
    divergences fixed on whichever side was wrong (see the decision record).
    Skeleton version set to **1.0.0** — the docs' `rainspout>=1,<2` pin and
    stability commitment now resolve against the real package.
11. **Phase 9 — blind-authorability verification: PASSED** (run by an
    independent agent chosen by the project owner to avoid biasing; a
    docs-only build of a conforming package succeeded). The gated build is
    complete. Released under the MIT license; published to PyPI as
    `rainspout` from github.com/strongmats/rainpipe (tag-driven trusted
    publishing).

---

## N. Decision record (what changed at each review, in one place)

| Decision | Where settled |
|---|---|
| Handler names underscore-only, no dots | Gate 1 C1 |
| Delta = exists − **attempted**; `--retry-failed` escape hatch | Gate 1 Q1 |
| Window-bounded `catalog` | Gate 1 Q2 |
| Dimension roles + startup pre-flight probe (4 steps, empty-catalog notice) | Gate 1 Q3 / Gate 2 #4 |
| One stage = one self-contained **directory**; tests outside the code hash | Gate 1 Q4 / Gate 2 #7 |
| `__init__` ban incl. mixins, definition-time | Gate 1 Q5 (+ Phase 1 review: metaclass + negative tests) |
| `build-image` v1-minimal | Gate 1 Q6 |
| No Cython/C toolchain in CI; observable setup exercise instead | Gate 1 Q7 |
| Two windowing layers kept visibly distinct | Gate 1 Q8 |
| Clean realtime stop semantics | Gate 1 Q9 |
| Bounded settings mandatory | Gate 1 review |
| No inter-stage structural checks | Gate 1 review |
| Private hooks under final public verbs | Gate 2 #1 |
| Driver expands ranges; handlers see explicit values | Gate 2 #2 |
| Role-map syntax + seed exactness | Gate 2 #3/#4, Part B4 |
| Wiring kinds as type annotations | Gate 2 #5 |
| Single-file metadata, no sidecars; optional posture; preserves-what-exists | Gate 2 #6 |
| Tests inside the component directory | Gate 2 #8 |
| `rainspout.testing` = stable public API | Gate 2 #9 |
| Entry-point groups + discovery gotchas documented | Gate 2 #10 |
| `--select` × delta semantics | Gate 2 #11 |
| Stages coordinate-aware; skeleton name-agnostic | Gate 2 B1/B2 |
| `seed:` config block; no seed-loader stage | Gate 2 B3 |
| Seed vs auxiliary validation split | Gate 2 B4 |
| Linear v1 on general graph machinery | Gate 2 B5 |
| Dimension names = config bookkeeping; no stage-declared dims | Gate 2 B6 |
| **Named** seed entries (`from: raw`); one in v1 | Gate 2b Q1 |
| `--force-rewrite` as a separate flag | Gate 2b Q2 |
| Coordinate keys read via bounded settings | Gate 2b Q3 |
| Aux dangling-reference typo check (config-internal only) | Gate 2b Q4 |
| `handler:` key for both dependencies and saves (`loader:` retired) | Gate 2c #1 |
| Block-form YAML in all examples | Gate 2c #2 |
| Driver constructs stages, injects resolved dependencies | Gate 2c #3 |
| Auxiliary handlers stage-callable (`load_one(coords)`); presence-and-wiring guarantee; save targets alone carry role maps; windowed-loader limitation dissolved | Gate 2c #4 |
| `run_id` per-run + per-work-item sub-key | Gate 1 §3.5, confirmed Phase 1 review |
| Oplog follows the run definition (`.rainspout/<name>.oplog.jsonl` next to the config; `run.oplog:` override resolves against the config dir, never CWD) | Phase 4 review / Phase 5 |
| Collector imports carry `# noqa: F401` (linters auto-remove them otherwise) | Phase 7 |
| Skeleton version 1.0.0: the documented `rainspout>=1,<2` pin must resolve | Phase 8 |
| Emptied YAML mapping keys (`dependencies:` with nothing under it) read as empty, so validation reaches the real named-offender error | Phase 8 |
| Registry lookups name their owner (`seed 'raw': unknown handler …`) | Phase 8 |
| Handler runtime errors print canonical coords + the underlying exception type | Phase 8 |
| Tutorial 3 uses relative `./data` paths; resource values are handler-interpreted (relative paths resolve against the invocation directory, unlike `run.oplog:`) | Phase 8 |
| Conditional settings = Pydantic discriminated unions (supported natively); bounded rule applies inside every arm — the conformance lint recurses into nested models; nested settings models declared frozen | Phase 8 addendum |
| Docs code-display convention: annotated templates (`contract:`/`yours:` per line) + worked examples in one fixed made-up domain; framework imports are only `rainspout.contracts`/`rainspout.testing`, stated once in the docs README | Phase 8 addendum 2 |
