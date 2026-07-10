# Rainspout — Complete Design Document

> **Rainspout** is a general-purpose scientific data-processing pipeline *framework*
> (the skeleton). It is domain-agnostic. **SkyCT** — the VLF ionospheric-tomography
> work — is one *content package* built on top of Rainspout, not the framework itself.
> The framework's distribution/import name is `rainspout`; its CLI command is `spout`.

> This document captures every design decision reached through discussion. It is the
> controlled artifact: the source of truth from which the documentation-first agent
> prompt will be built. It describes a **clean-slate skeleton** — the existing
> mock-skeleton repo is deliberately NOT carried forward (it encodes decisions since
> reversed, and would bias the build).

---

## A. Foundational philosophy

- A reusable **skeleton/shell** that scientific (or other) processing pipelines are
  built on top of. The skeleton contains **no science**.
- **Separate "what / where / how."** Each concern is independent and knows nothing
  about the others.
- **Break loudly, early.** Every misconfiguration fails at startup with a specific,
  actionable message naming the offender — never a silent wrong result or a deep
  runtime crash.
- **Declared-in-code, validated-against-config.** Everything a component needs is
  declared in code and checked against config before any data moves.
- **Blind-authorable contracts.** Someone with only an authoring doc (no skeleton
  access) can build a conforming component. The docs are the literal API boundary.
- **Documentation-driven design.** The authoring standards are written FIRST and
  define the interface; the machinery is then built to satisfy them.
- **Deep-validate cheap things (settings); cheap-check expensive things (data).**

---

## B. Core / content split (plugin architecture)

- **`rainspout-core` (the skeleton):** the brain (registry, config, runner, driver,
  logging, CLI), the base-class contracts for every axis, and the authoring
  standards. Stable, reusable across projects, depended-upon. No science, no real
  handlers, no real stages.
- **Content packages (e.g. `skyct`, the VLF science built on Rainspout):** concrete stages + handlers + example
  configs (+ optional package CLI verbs + optional lifecycle/artifact commands),
  obeying the core contracts and registering via **entry points**. Multiple packages
  may coexist.
- **Clean seam.** The two are logically separate; the two build-agents will never
  know about each other. The **authoring docs are the inter-repo contract** and a
  first-class deliverable.
- **Approach 1 — installable packages** (not literal drag-drop folders), via Python
  entry points, so installing a package makes its components discoverable with no
  manual imports or registry edits.
- **Editable installs** (`uv add --editable ./pkg`) allow live development of a
  package alongside the core; a package can be physically split into its own repo
  when its contracts stabilize. Editable installs are local-environment links only;
  git tracks/pushes the package code independently.

---

## C. Handlers (the collapsed IO axis)

- **Combined handlers** replace freely-mixed Storage×Codec. Each handler is ONE fixed
  combination of {file type, in-file data structure, filename, folder structure,
  access channel}. Rationale: avoid the N×M testing burden; most real use cases are a
  single fixed combination.
- **Naming convention:** `datatype_accesschannel.type` (e.g. `sferic_local.mat`),
  where `.type` is the file extension. **The name is purely conventional — never
  parsed by the skeleton for meaning.** It is a registry key; capabilities are
  declared explicitly in code.
- **Constructed with settings** for quick access: base directory, API keys, etc.
- **Three verbs:** `load`, `save`, `catalog`.
  - `load` / `save` operate on the data for a given **dimension spec**.
  - `catalog` surveys a range of available data and may optionally write a catalog
    file to a directory. Catalog output uses the same validated metadata shape as
    everything else (machine-readable by the driver for "what's available").
- **Consistent dimension-spec input.** A single value is the degenerate case of a
  range (one input format, no separate code path at the interface).
- **Two INDEPENDENT range concepts, each mandatory-simple / optional-powerful:**
  1. **Dimension-grid range** — one cell (mandatory/default) vs. a window of cells
     across the grid (optional, declared capability). A range returns a **lazy
     per-cell sequence** (never materializes all cells at once). A range asked of a
     non-range-capable handler fails loudly at startup.
  2. **Within-file windowing** — read a slice inside a single file without
     materializing the whole (optional, declared capability; the
     `supports_windowed_read` idea; matters for HDF5/memmap).
- **All structural knowledge is the handler's private business.** From the base
  directory onward — folder structure, filename, AND in-file layout — is entirely
  inside the handler and opaque to the skeleton. The handler is a black box mapping a
  dimension-spec to data.
- **Compression on save** where the format supports it (e.g. HDF5).
- **Lifecycle is private.** Stages call `load`/`save`/`catalog` and never know whether
  a connection was opened per-call or kept alive. Default: **per-transaction** (open,
  fetch, done) for simple handlers; sophisticated handlers may keep a session
  internally.
- **Required shared metadata block** every handler looks for on load and writes on
  save (see F).
- Handlers are passed **into** stages as dependencies (each loadable dependency gets a
  handler instance).

---

## D. Stages

- **"Stage"** = one processing step. Never "Module" (reserved for a `.py` file).
- **Thin orchestrator principle.** The stage class is a thin declaration; the heavy
  mechanics/science live in **module-level functions** the stage calls. The class
  stays auditable at a glance; the science is testable in isolation.
- **Three strictly separated kinds of input:**
  - **Settings** — static config, deep-validated by Pydantic (`settings_model`,
    `extra="forbid"`, `Field` range constraints where applicable).
  - **Dependencies** — named data inputs (`dependencies_model`); each wired in config
    `from:` an upstream stage OR via a **handler** instance; validated against config.
  - **Resources** — a handler's own fetch config (dir/keys); the handler's concern.
- **Seed loader = a normal stage (Option B).** Its dependency is a handler rather than
  an upstream stage; its `run` calls `handler.load()` and passes data on. No special
  DAG entry node; loading and processing share one shape. There is exactly one way for
  data to enter a stage — through its dependencies.
- **Setup/initialization hook.** A stage may declare init-time code (e.g. compile a
  Cython/module, load a library) run once after validation, before processing. A
  **common setup command** runs every stage's setup (`spout setup`).
- **Progress reporting:** a **mandatory written status line** (`status() -> str`) and
  an **optional-but-recommended percentage** (`progress() -> float | None`, optional
  because streaming/unknown-total makes it sometimes uncomputable).
- **Post-run status** returning success / warnings / errors.
- **Required `version`** on every published stage, changing whenever the stage is
  edited. Enforcement: **CI check that a changed stage bumped its version**, plus a
  **code-hash recorded in provenance** as a tamper-evident backstop.
- **Validates all ingested settings with Pydantic before running** (un-bypassable —
  see G).
- **Cheap data checks only** (shape/type), never deep per-element validation of large
  data.
- **No side effects, no fetching outside declared dependencies, no calling other
  stages.**
- **One stage = one self-contained file** (settings model + dependencies model + stage
  + version + its test in the mandated format).

---

## E. DAG, driver, dimensions

- **The DAG** wires stages and is **validated before execution**: resolve every
  `from:`, assert acyclicity, assert every declared dependency satisfied.
- **One DAG, all dimensions.** Every stage runs at the same dimensional granularity.
  **No mid-DAG dimension collapsing** — any fan-in/aggregation across a dimension is a
  SEPARATE run with a different config. (A deliberate simplification.)
- **Generalized delineating dimensions.** Config declares named dimensions (date, RX,
  and arbitrary others — coordinates, etc.), each a set/range of values.
  - A **work item** = one point in the dimension space; the DAG runs once per work
    item.
  - **Iteration order** and **mode** are config-specified. Real-time and retrograde
    are UNIFIED via the same delta mechanism: `catalog` reports what data EXISTS
    across the dimension space; the operational log reports what's already PROCESSED;
    the driver processes the **delta** (exists − processed). Retrograde computes the
    delta once and works through it. Real-time computes the delta, works through it,
    then waits `poll_frequency` seconds (a config setting) and recomputes — forever,
    until stopped by the user. It only polls when NOT mid-run (no overlapping cycles;
    pairs with the no-parallelism decision). Requirement: the log and catalog must
    express work in the same named-dimension vocabulary so the delta is well-defined.
  - Dimensions are **opaque to stages**; only the driver (enumerates work items) and
    handlers (resolve a work item to data) know dimension names.
- **Failure isolation per work item.** Each DAG cycle is wrapped in try/except; a
  failure kills only that ONE work item (e.g. one date+RX), is logged, and all other
  work items continue.
- **Sequential processing (no parallelism in v1).** The driver processes work items
  one at a time. Work items remain independent (so failure-isolation holds and future
  parallelism is possible), but the driver introduces no threading/multiprocessing.
- **Config-designated saving.** Any stage in the DAG may be wired (in config) to
  persist its output via a specified handler — at ANY point in the DAG, not just
  terminal stages. Only wired stages persist; all other outputs stay lazy/in-memory
  and are discarded after the work item. This is the output-symmetric counterpart to
  a dependency: a dependency wires data IN via a handler, a save wires data OUT via a
  handler.
- **Lazy inter-stage data passing (RAM-vs-disk "best of both worlds").**
  - Stages exchange **lazy references**, not materialized data. **Whole-object lazy
    fetch is universal** (works for numpy, pandas, dict, any type). **Windowing is an
    optional advertised capability** on a reference (only for windowable types).
  - Materialization happens on demand. Adjacent in-memory stages hand over the in-RAM
    object with no disk; large data stays lazy/windowed. Don't save after every stage
    unless needed; don't hold unbounded RAM.
  - Get the **contract** right first (stages pass references, consumers pull) even if
    the first implementation passes objects directly.

---

## F. Logging, provenance, resume

- **Two distinct-but-complementary systems (do NOT merge them):**
  - **Operational log** — keyed per **(stage, work item)**: did it run, succeed, fail,
    with warnings/errors and a timestamp. Its job is robustness and resume.
  - **Provenance chain** — travels WITH the data: an ordered list where each stage that
    touches the data appends `{stage_name, stage_version, settings_used, timestamp}`
    (+ code-hash backstop). Saved alongside the data on every save. Its job is
    scientific reproducibility.
- **Resume / no-repeat.** The operational log is the source of truth for "what's
  already processed": a (stage, work item) that already succeeded is skipped;
  erroneous data that produced no valid output is not blindly re-run.
- **Required, format-agnostic metadata category** every loader looks for and every
  saver writes (carries the provenance chain; consistent across all file types).
- **`run_id`** threaded through logs, results, and saved metadata.

---

## G. Settings & validation (cross-cutting)

- **Pydantic everywhere**, `extra="forbid"` to catch typos.
- **Validation forced in the base `__init__`, un-bypassable:** subclasses may not
  override `__init__` (enforced at class-definition time); post-validation init goes
  in a `setup()` hook.
- **The whole pipeline config is itself a validated Pydantic model** — a malformed
  pipeline fails loudly at load.
- **`run` implicitly validates before touching data**, through the same gates
  `validate` uses, in order: (1) config parse, (2) registry resolution, (3) DAG
  validation pass, (4) per-stage settings validation in `__init__`. There is no
  skip-validation path. `validate` is simply `run`'s front-half exposed standalone.
- **Two validation tiers:** definition/settings problems fail loudly up front
  (Pydantic + DAG pass); data problems (empty dir, corrupt file) surface per-work-item
  at runtime and are logged without sinking the whole run.
- **Distinct failure modes, each with a named-offender message:** bad setting; missing/
  extra/misspelled dependency; `from:` → nonexistent stage; DAG cycle; handler with
  bad resource config; malformed pipeline config; range asked of a non-range-capable
  handler; a changed stage that didn't bump its version.

---

## H. Registration & discovery

- **Auto-registration of every axis via one uniform gesture** (`__init_subclass__`),
  identical across stages, handlers, savers, etc., so blind authoring feels the same
  everywhere.
- **Registry maps name → class**; never hand-edited by contributors.
- **Content packages register via entry points**, so installing a package makes its
  components discoverable without manual imports.

---

## I. CLI

- **Philosophy:** the skeleton exposes clean, composable commands; the USER (or their
  sbatch / Docker / cluster / cron) orchestrates them. The skeleton does not run
  clusters. **Orchestration is out of scope.**
- **Commands:**
  - `spout run --config <f> [--mode retrograde|realtime] [dimension selection]
    [--dry-run] [resume flags]` — execute the pipeline. `--dry-run` does all discovery
    + planning (enumerate work items, check the log for done work, report the plan)
    then stops without executing any stage.
  - `spout validate --config <f>` — definition-only check (config parses, names
    resolve, DAG resolves, settings valid). Touches no data. Instant.
  - `spout catalog ...` — survey available data via handlers; optional catalog file.
  - `spout setup` — run every stage's setup/compilation.
  - `spout build-image` — crystallize the current core + installed packages (+ their
    locked versions) into a reproducible Docker image the user can run anywhere
    (their sbatch/Fargate/etc. runs the image). **In scope for v1.**
  - `spout test-package <pkg>` — run a package's tests + coverage on demand.
  - **Package-contributed verbs** (`spout <package> <verb>`) — a package may contribute
    its own CLI commands (e.g. `spout vlf train --config ...`), discovered via
    entry points and mounted under the skeleton CLI.

---

## J. Sims → generalized "package lifecycle commands + versioned artifacts"

- **"Sims" as a distinct subsystem is dissolved.** Replaced by a general notion: some
  stages/packages need a **prepare phase** (train a model, run simulations to build a
  grid, compile something) before they can process data.
- A package/stage may declare **lifecycle commands beyond `run`** — e.g. `train`,
  `simulate`, `build`, `calibrate` — exposed as package-contributed CLI verbs. These
  produce **artifacts** (trained model, simulation grid, compiled binary).
- An **artifact is just a versioned input a stage depends on**, loaded at runtime via a
  handler, with its version recorded in the provenance chain. No separate sims
  machinery. (In-process ONNX inference, if used, is an implementation detail inside
  one such stage.)
- Requires a **`PACKAGE_AUTHORING.md`** standard — "the anatomy of a package" (what a
  package ships: stages, handlers, configs, CLI verbs, lifecycle commands, tests).

---

## K. Testing & coverage

- **Skeleton:** enforce **90% coverage floor** (aim 95%+) via **`pytest-cov` /
  `coverage.py`** with `--cov-fail-under=90`, hard-failing CI. Genuinely-untestable
  lines may be exempted with `# pragma: no cover` + justification.
- **Packages:** every package MUST ship tests in the mandated format. The skeleton
  **statically verifies tests exist and conform** (cheap); it does **NOT** measure
  coverage at load time (expensive, fragile, seam-breaking). Coverage is enforced in
  the **package's own CI** (skeleton provides a CI template) and runnable on demand via
  `spout test-package`.
- **Each stage ships a test in a strict mandated format**, auto-run by CI.
- **Each handler ships a round-trip test** in a mandated format, with its own
  **example data file**: load it → save it → load the saved copy → assert equal →
  catalog and assert the catalog reports it correctly. Equality uses appropriate
  tolerance (exact for integers/structure; near-equal within tolerance for floats),
  and the required metadata/provenance block must survive the round-trip. The example
  file ships with the handler (self-contained test + documents the format). Both stage
  and handler tests are statically verified to exist/conform and enforced in the
  package's own CI.
- **GitHub Actions** on every PR: ruff + mypy + pytest + coverage; the stage
  version-bump check; per-stage tests run on substantial GitHub interaction.

### Tests vs. example package (different jobs)

- **Tests (in the skeleton repo `tests/`)** prove the MACHINERY works — minimal,
  adversarial, eyeball-able, ugly-on-purpose. They exercise each mechanism and each
  failure mode. **The trivial reference content lives here** and must include: a
  **mid-DAG extra dependency** (a stage that loads an additional input partway
  through, via a handler) AND **setup-time compilation** (e.g. Cython) to prove the
  setup-sourcing/compilation path works.
- **Example package (`examples/` or its own repo)** teaches a USER — clean,
  well-commented, realistic-in-shape but trivial-in-content; the thing a contributor
  copies. The **blind-agent verification** is measured against this clean example (the
  blind agent learns from docs and should produce something like it).

---

## L. Tooling

- **uv** — packaging; commit `uv.lock`; `.venv` gitignored; editable installs.
- **Typer** — CLI (incl. package-contributed verbs).
- **Pydantic v2** — all settings/dependencies/result/config validation.
- **structlog** — structured logging with `run_id`.
- **pytest + pytest-cov** — tests + coverage enforcement.
- **ruff + mypy** — lint / type-check.
- **GitHub Actions** — CI (lint, type, test, coverage, version-bump enforcement).
- Content-package territory (not skeleton): **h5py / scipy** (HDF5 / .mat),
  **Cython** (compiled setup example), **ONNX Runtime** (if a package does inference),
  **Docker** (target of `build-image`).

---

## M. The build process (meta — how the agent proceeds)

1. **Documentation-first.** The agent drafts the authoring standards / docs FIRST
   (STAGE, HANDLER, PACKAGE, plus config authoring, and the tutorials) — defining the
   interface before any machinery. **We review and critique the docs before it builds
   anything.**
2. **Reflect-back-and-stop.** Before building machinery, the agent restates the design
   as its own design doc + proposed file/repo structure and STOPS for approval.
3. **Phased build** against the approved docs.
4. **Tutorials as acceptance tests:** "add a handler," "add a stage," "create a run /
   config."
5. **Blind-agent verification:** a SEPARATE agent, given scientific code + the authoring
   docs but **no skeleton access**, builds a conforming package and runs it in the
   skeleton — proving the docs are truly self-contained (the inter-repo contract holds).
6. **Clean slate:** the build agent is NOT given the existing mock repo.

---

## N. Open items to confirm before/while building

- Exact shape of the **dimension-spec** object (how a range vs. single value is
  expressed in config and passed to `load`/`save`).
- Exact **lazy-reference** interface (whole-object fetch + optional windowing
  capability flag) — contract first.
- Exact **package anatomy** (`PACKAGE_AUTHORING.md`) — including how lifecycle
  commands and CLI verbs are declared via entry points.
- Whether the trivial reference content and the clean example share code or are
  deliberately separate (leaning: separate — adversarial vs. pedagogical).

## O. Decisions locked since first draft

- **Config is a single `.yml` file.** The documentation-first phase must produce a
  `CONFIG_AUTHORING.md` defining its structure (dimensions, iteration mode +
  `poll_frequency`, the DAG/stage wiring, per-stage settings/dependencies, and
  config-designated saves).
- **Saving is config-designated, anywhere in the DAG, via a named handler.**
- **v1 is sequential (no parallelism).**
- **Real-time = retrograde-on-a-loop:** process the catalog−log delta, poll every
  `poll_frequency` seconds when idle, forever until stopped.
- **Each handler ships a round-trip test + example data file** (load/save/equal/
  catalog).

### Left to the build agent to propose (in the docs, for review)

These were discussed as genuine gaps but are fine for the agent to resolve and
document (surfaced for approval, not buried in code): exact config YAML schema; how a
stage receives its handler (runner injection vs. stage construction) and when in the
lifecycle; whether a stage receives a lazy reference or materialized data (who
materializes when); the error-vs-warning taxonomy and its effect on resume; `run_id`
granularity (per-run vs. per-work-item; leaning per-run with work-item sub-key);
versioning-change detection mechanism (git diff vs. code-hash); exact `catalog` output
contents.
