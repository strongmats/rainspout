# Rainspout — Gate 1 Planning Document

Status: **awaiting Gate 1 approval.** No documentation or implementation code has been
written. This document contains (1) the architecture restated in my own words,
(2) the proposed repository structure, (3) proposed answers to every "left to the
agent" item, (4) the phase plan, and (5) risks and tensions I see in the design.

---

## 1. Architecture restatement (my own words)

### 1.1 What Rainspout is

Rainspout is a shell for building data-processing pipelines, containing no processing
logic of its own. It answers three questions independently — *what* computation runs
(stages), *where* data lives and *how* it is read/written (handlers), and *over what*
the pipeline iterates (dimensions/driver) — and refuses to let any of those concerns
leak into the others. Its central promise is that every misconfiguration dies at
startup with a message naming the specific offender, and that a person holding only
the authoring docs — never the skeleton source — can write a component that works on
first contact. The authoring docs are not documentation *about* the API; they *are*
the API boundary between the core repo and content-package repos that will never see
each other.

### 1.2 Core / content split

`rainspout-core` ships the brain — registry, config loader/validator, DAG validator,
runner, driver, two logging systems, CLI — plus the abstract base contracts and the
authoring standards. It contains no concrete stage or handler except trivial
reference content living in `tests/` (adversarial, machinery-proving) and a clean
pedagogical example (separate, contributor-facing). Content packages (SkyCT being
the first real one) are ordinary installable Python packages that subclass the
contracts and become discoverable through entry points the moment they are installed
— no imports to add, no registry file to edit. Core never imports a concrete
component by name; everything is resolved through the registry at config-load time.

### 1.3 Handlers (the combined IO axis)

A handler is one **fixed** combination of file type + in-file structure + filename
convention + folder convention + access channel, collapsed into a single class to
kill the N×M storage-times-codec testing explosion. Its registry name follows the
`datatype_accesschannel.type` convention purely for human readability — the skeleton
never parses the name; every capability is declared explicitly in code.

A handler is constructed with **resources** (base dir, API keys) and exposes exactly
three verbs: `load`, `save`, `catalog`. All three take a **dimension spec**, and a
single value is expressed as a range of one, so there is one input shape and no
special-casing at the interface. Two *independent* optional powers exist, each with a
mandatory simple default:

1. **Dimension-grid range** — default is one grid cell; a handler may declare it can
   serve a window of cells, in which case it returns a *lazy per-cell sequence*
   (never all cells materialized at once). Asking a range of a non-range-capable
   handler is a startup failure, not a runtime surprise.
2. **Within-file windowing** — default is whole-file reads; a handler may declare it
   can read a slice inside one file without materializing it (HDF5/memmap territory).

Everything from the base directory down — folders, filenames, in-file layout — is the
handler's private business; to the rest of the system it is a black box from
dimension-spec to data. Connection lifecycle is equally private: stages call the
verbs and never learn whether a connection was per-call or pooled (per-transaction is
the default posture). Every handler reads and writes the one **required shared
metadata block** (which carries the provenance chain), in a format-agnostic shape.
`catalog` reports what exists across a dimension range using that same validated
metadata vocabulary, so the driver can consume it mechanically, and may optionally
write a catalog file.

### 1.4 Stages

A stage is one processing step ("stage" always; "module" is reserved for `.py`
files). The class itself is a **thin orchestrator**: declarations plus a `run` that
calls module-level functions where the actual science lives — so the class is
auditable at a glance and the science is testable without the skeleton. A stage's
inputs come in exactly three strictly separated kinds:

- **Settings** — static config, deep-validated by a Pydantic `settings_model` with
  `extra="forbid"` and range constraints. Cheap to validate, so validated hard.
- **Dependencies** — named data inputs declared in a `dependencies_model`, each wired
  in config either `from:` an upstream stage or via a named **handler**. There is
  exactly one door for data to enter a stage: its dependencies.
- **Resources** — the handler's own fetch config; not the stage's concern at all.

The **seed loader is a normal stage** whose dependency happens to be a handler; its
`run` calls the handler's load and passes data on. There is no special DAG entry-node
type — loading and processing share one shape.

Stages may declare a **setup hook** (compile Cython, download a library) run once
after validation and before processing; `spout setup` runs all of them. Every stage
must implement `status() -> str` (mandatory written status line) and should implement
`progress() -> float | None` (optional, because streaming/unknown totals make a
percentage sometimes uncomputable). A stage returns a post-run status of
success/warnings/errors. Every published stage carries a required `version` that must
change whenever the stage is edited — enforced by a CI check that a changed stage
file bumped its version, backstopped by a code-hash recorded in provenance so
tampering is evident even if CI is dodged. Stages perform only **cheap** checks on
data (shape/type — never deep per-element validation of large arrays), have no side
effects, fetch nothing outside their declared dependencies, and never call other
stages. One stage = one self-contained file: settings model, dependencies model,
stage class, version, and its mandated-format test together.

### 1.5 One DAG, all dimensions; the driver

Config declares named **dimensions** (date, receiver, or anything else), each a
set/range of values. A **work item** is one point in that dimension space, and the
whole DAG runs once per work item, at one uniform granularity — **no mid-DAG
dimension collapsing**; any fan-in across a dimension is a separate run with a
different config. Dimensions are opaque to stages; only the driver (which enumerates
work items) and handlers (which resolve a work item to actual data) speak dimension
names.

Retrograde and real-time are the **same mechanism**: `catalog` says what exists
across the dimension space, the operational log says what has already been processed,
and the driver processes the **delta** (exists − processed). Retrograde computes the
delta once and drains it. Real-time drains the delta, then sleeps `poll_frequency`
seconds and recomputes — forever, until the user stops it — and never polls mid-run
(no overlapping cycles, which pairs with the no-parallelism decision). This requires
the log and the catalog to express work in the same named-dimension vocabulary so the
subtraction is well-defined.

Each work item's DAG cycle is wrapped in try/except: a failure kills that one work
item, is logged, and every other work item proceeds. **v1 is strictly sequential** —
work items stay independent (preserving failure isolation and future parallelism)
but the driver introduces no threading or multiprocessing.

### 1.6 Data movement: lazy references and config-designated saving

Stages exchange **lazy references**, not materialized data. Whole-object fetch is
universal (any type); windowed fetch is an optional advertised capability on a
reference (only for windowable types). Materialization happens when a consumer pulls,
so adjacent in-memory stages hand over the live object with zero disk traffic while
large data can stay windowed. The design instruction is to get the *contract* right
first even if the v1 implementation passes objects directly under the hood.

Persistence is **config-designated**: any stage, anywhere in the DAG (not just
terminal ones), may be wired in config to save its output through a named handler.
This is the output-symmetric mirror of a dependency — a dependency wires data IN
through a handler, a save wires data OUT through one. Unwired outputs stay
lazy/in-memory and are discarded when the work item completes.

### 1.7 Two logging systems (never merged)

- The **operational log** is keyed per (stage, work item): ran/succeeded/failed,
  warnings/errors, timestamp. Its job is robustness and resume — it is the source of
  truth for "already processed," so a succeeded (stage, work item) is skipped and
  erroneous data that produced no valid output is not blindly re-run.
- The **provenance chain** travels *with the data*: an ordered list to which every
  stage that touches the data appends `{stage_name, stage_version, settings_used,
  timestamp}` plus the code-hash backstop, persisted inside the required metadata
  block on every save. Its job is scientific reproducibility.

They answer different questions ("what has the pipeline done?" vs. "where did this
file come from?") and stay separate. A `run_id` threads through logs, results, and
saved metadata.

### 1.8 Validation (un-bypassable) and registration

All settings validation happens in the base class `__init__`, and subclasses are
forbidden (at class-definition time) from overriding `__init__` — post-validation
initialization goes in `setup()`. The pipeline config is itself a Pydantic model, so
a malformed config fails loudly at load. `spout run` implicitly passes through the
exact same gates as `spout validate` — (1) config parse, (2) registry resolution,
(3) DAG validation (every `from:` resolves, acyclic, every declared dependency
satisfied), (4) per-stage settings validation — with no skip path; `validate` is just
`run`'s front half exposed standalone. Two tiers: definition/settings problems fail
the whole run up front; data problems (empty dir, corrupt file) surface per work item
at runtime, logged, without sinking the run. Every specified failure mode (bad
setting, missing/extra/misspelled dependency, `from:` a nonexistent stage, DAG cycle,
bad handler resources, malformed config, range on a non-range handler, unbumped
version) produces a named-offender message.

Registration is one uniform gesture — `__init_subclass__` on the base contract —
identical for every axis, so blind authoring feels the same everywhere; the registry
maps name → class and is never hand-edited. Cross-package discovery is via entry
points.

### 1.9 CLI and lifecycle commands

The skeleton exposes composable commands and refuses to orchestrate: the user's
cron/sbatch/Docker does that. Verbs: `run` (with `--mode`, dimension selection,
`--dry-run` that plans and reports without executing, resume flags), `validate`
(definition-only, touches no data, instant), `catalog`, `setup`, `build-image`
(crystallize core + installed packages + locked versions into a reproducible Docker
image — in scope for v1), `test-package`, plus **package-contributed verbs**
(`spout <package> <verb>`) discovered via entry points. The old "sims" idea is
dissolved into this: a package may declare lifecycle commands (`train`, `simulate`,
`build`) that produce **artifacts**, and an artifact is just a versioned input a
stage depends on through a handler, its version recorded in provenance.

---

## 2. Proposed repository / package structure

Distribution and import name `rainspout`, CLI `spout`. Single repo `rainspout-core`.

```
rainspout-core/
├── pyproject.toml              # uv-managed; [project.scripts] spout = "rainspout.cli.main:app"
├── uv.lock                     # committed
├── .gitignore                  # .venv, build artifacts
├── README.md
├── .github/workflows/ci.yml   # ruff + mypy + pytest --cov-fail-under=90 + version-bump check
│
├── docs/                       # THE CONTRACT — first-class deliverables (Gate 2)
│   ├── STAGE_AUTHORING.md
│   ├── HANDLER_AUTHORING.md
│   ├── PACKAGE_AUTHORING.md
│   ├── CONFIG_AUTHORING.md
│   └── tutorials/
│       ├── 01_add_a_handler.md
│       ├── 02_add_a_stage.md
│       └── 03_create_a_run.md
│
├── src/rainspout/
│   ├── __init__.py
│   ├── contracts/              # base classes ONLY — imports nothing from the brain
│   │   ├── __init__.py
│   │   ├── stage.py            # Stage base: __init_subclass__ registration,
│   │   │                       #   un-bypassable __init__, setup/status/progress/run
│   │   ├── handler.py          # Handler base: load/save/catalog, capability flags
│   │   ├── reference.py        # LazyReference: get(), optional window(), capability flag
│   │   ├── dimension.py        # DimensionSpec (single = range-of-one)
│   │   ├── metadata.py         # required shared metadata block + provenance entry models
│   │   └── result.py           # post-run StageResult (success/warnings/errors)
│   │
│   ├── registry.py             # name → class maps for every axis; uniform registration
│   ├── discovery.py            # entry-point loading of content packages
│   ├── config.py               # pipeline-config Pydantic models + YAML loader
│   ├── dag.py                  # DAG resolution + validation (cycles, from:, deps)
│   ├── runner.py               # one work item through the DAG; injection; designated saves
│   ├── driver.py               # work-item enumeration; catalog−log delta;
│   │                           #   retrograde drain + realtime poll loop; failure isolation
│   ├── oplog.py                # operational log (per stage × work item)
│   ├── provenance.py           # chain append helpers; code-hash computation
│   ├── errors.py               # error taxonomy; named-offender exception types
│   └── cli/
│       ├── __init__.py
│       ├── main.py             # Typer app; mounts package-contributed verbs
│       ├── run.py, validate.py, catalog.py, setup.py,
│       ├── build_image.py, test_package.py
│       └── _mount.py           # entry-point verb discovery/mounting
│
├── tests/                      # proves the MACHINERY — adversarial, ugly-on-purpose
│   ├── reference_content/      # trivial reference package (registered for tests only)
│   │   ├── stages/             # incl. mid-DAG-extra-dependency stage
│   │   │                       #   and a setup-time Cython-compiled stage
│   │   ├── handlers/           # + example data files for round-trip tests
│   │   └── configs/
│   ├── test_registry.py, test_config.py, test_dag.py, test_runner.py,
│   ├── test_driver.py, test_oplog.py, test_provenance.py, test_handlers.py,
│   ├── test_validation_failures.py   # one test per named failure mode
│   └── test_cli.py
│
└── examples/                   # teaches a USER — clean, commented, pedagogical
    └── rainspout-example/      # a complete minimal content package
        ├── pyproject.toml      # shows entry-point registration
        └── src/rainspout_example/{stages,handlers,configs}/
```

The seam discipline: `contracts/` imports only Pydantic/stdlib (so authoring docs can
describe it without reference to the brain); the brain (`registry` … `cli`) imports
`contracts/` but never any concrete component; concrete components exist only under
`tests/reference_content/` and `examples/`, reached exclusively through the registry.

---

## 3. Proposed answers to the "left to the agent" items (section O)

**3.1 Exact config YAML schema (top-level shape).** Five top-level keys:

```yaml
run:                       # run identity + iteration mode
  name: my_run
  mode: retrograde         # or realtime
  poll_frequency: 300      # seconds; required iff mode == realtime

dimensions:                # named dimension → values (list or range form)
  date: {start: 2026-01-01, stop: 2026-01-31, step: 1d}
  rx: [alpha, bravo]

iteration:
  order: [date, rx]        # outer → inner loop order

handlers:                  # NAMED handler instances: registry key + resources
  sferic_in:
    handler: sferic_local.mat
    resources: {base_dir: /data/sferics}
  cleaned_out:
    handler: cleaned_local.h5
    resources: {base_dir: /data/cleaned}

stages:                    # DAG: stage instances, wiring, settings, designated saves
  load:
    stage: seed_loader
    dependencies: {data: {loader: sferic_in}}
    settings: {}
  clean:
    stage: clean_sferics
    dependencies: {data: {from: load}}
    settings: {threshold: 0.7}
    save: {handler: cleaned_out}
```

*Rationale:* handler instances are declared once under `handlers:` and referenced by
name from both `loader:` dependencies and `save:` blocks, which makes the
dependency/save symmetry (design E) literal in the config and gives validation a
single place to check every resource block.

**3.2 How a stage receives its handler — runner injection, at work-item execution
time.** Stages are constructed at validation time with settings only (keeping
`__init__` pure and un-bypassable); when the runner executes a work item, it resolves
each declared dependency — an upstream lazy reference for `from:`, or a handler
instance *pre-bound to the current work item's dimension spec* for `loader:` — and
injects them as the validated dependencies object passed to `run`.
*Rationale:* construction stays config-only (validatable before any data moves), and
pre-binding the dimension spec preserves "dimensions are opaque to stages."

**3.3 Lazy reference or materialized data — lazy references, consumer materializes.**
Every dependency arrives as a `LazyReference`; the consuming stage materializes on
demand via `ref.get()` (universal) or `ref.window(...)` (only if the reference
advertises windowability). The v1 implementation may back references with in-memory
objects, but the contract is reference-passing from day one.
*Rationale:* design E explicitly says get the contract right first; consumer-pulls is
the only placement that lets adjacent in-RAM stages skip disk while large data stays
windowed.

**3.4 Error-vs-warning taxonomy and effect on resume.**
- *Warning:* the stage completed and produced valid output; recorded in the oplog and
  provenance; the (stage, work item) counts as SUCCEEDED and is skipped on resume.
- *Error (runtime, per-work-item):* the stage failed with no valid output; the work
  item is marked FAILED at that stage, its downstream stages are skipped, the run
  continues with the next work item. On resume, FAILED items are **not** re-run by
  default (design F: don't blindly re-run erroneous data); an explicit
  `--retry-failed` flag re-queues them.
- *Definition error (config/settings/DAG/registry):* always fatal to the whole run,
  before any data moves.
*Rationale:* the succeeded/failed/definition triage is the minimal taxonomy that
makes both "resume skips done work" and "don't hammer poison inputs" precise —
including in the real-time delta (see risk 5.1).

**3.5 `run_id` granularity — per-run**, with the work item as a sub-key: every oplog
record and provenance entry carries `(run_id, work_item_key)` where `work_item_key`
is the canonical serialized dimension coordinates.
*Rationale:* the design doc leans this way; one id per invocation matches how humans
reason about "that Tuesday run," while the sub-key keeps per-work-item traceability.

**3.6 Versioning-change detection — both mechanisms, in the roles the design doc
assigns.** Enforcement is a CI check that git-diffs the PR: any changed stage file
must contain a `version` bump (the one-stage-one-file rule makes file→stage mapping
trivial). The backstop is a code-hash (hash of the stage module's source) computed at
run time and recorded in every provenance entry, so an unbumped edit is tamper-evident
after the fact even if CI was bypassed.
*Rationale:* git-diff is cheap and catches the mistake at review time; the hash makes
provenance self-verifying without needing git at run time.

**3.7 Exact `catalog` output contents.** A validated Pydantic model, serialized to
JSON when written to a file:

```json
{
  "handler": "sferic_local.mat",
  "dimensions": ["date", "rx"],
  "entries": [
    {"coords": {"date": "2026-01-01", "rx": "alpha"},
     "extras": {"size_bytes": 1048576, "modified": "2026-01-01T06:00:00Z"}}
  ],
  "generated_at": "...", "run_id": "..."
}
```

`entries[].coords` uses the config's named-dimension vocabulary — this is the field
the driver subtracts the oplog from. `extras` is optional, handler-private, and never
interpreted by the skeleton.
*Rationale:* the delta requires exactly one thing — coordinates in the shared
dimension vocabulary — so that is the required core, and everything else is opaque
extra.

---

## 4. Proposed phase plan (post-Gate 2; I stop between every phase)

| Phase | Scope | "Done" criterion |
|---|---|---|
| **1. Contracts & registry** | `contracts/` base classes, uniform `__init_subclass__` registration, un-bypassable `__init__` enforcement, error taxonomy, entry-point discovery | Unit tests prove: registration works identically per axis; overriding `__init__` fails at class definition; bad settings fail with named offender |
| **2. Config & DAG validation** | Config Pydantic models, YAML loader, DAG resolution/validation, `spout validate` | Every definition-time failure mode in G produces its specific named-offender message; a valid config validates instantly touching no data |
| **3. Handlers & data plane** | DimensionSpec, LazyReference, metadata/provenance block models, handler verbs + capability flags, round-trip test harness | Reference handler passes the mandated round-trip (load→save→load→equal→catalog); range-on-non-range fails at startup |
| **4. Runner** | Single-work-item execution: dependency resolution/injection, seed-loader path, config-designated saves, oplog + provenance writes, status/progress surfacing | One work item runs end-to-end through a multi-stage DAG with a mid-DAG save; provenance chain and oplog records verified |
| **5. Driver** | Work-item enumeration, catalog−log delta, retrograde drain, realtime poll loop, per-item failure isolation, resume semantics, `--dry-run` | Delta/resume/retry-failed tests pass; a mid-run failure kills exactly one work item; dry-run reports the plan and executes nothing |
| **6. CLI complete** | `run`, `catalog`, `setup`, `build-image`, `test-package`, package-verb mounting | Every verb works against the reference content; a package-contributed verb mounts and runs |
| **7. Reference content, example, tutorials, CI** | Adversarial reference content (mid-DAG extra dependency + Cython setup stage), clean example package, tutorials verified by following them literally, CI with 90% coverage floor + version-bump check | Skeleton runs the reference content end-to-end; every specified failure mode breaks loudly; all three tutorials work exactly as written; CI green with ≥90% coverage |

---

## 5. Risks, ambiguities, and tensions

1. **Failed work items vs. the real-time delta.** If the delta is `exists −
   succeeded`, a permanently corrupt input ("poison item") re-enters the delta every
   poll cycle and is retried forever. My taxonomy (3.4) therefore defines the delta as
   `exists − (succeeded ∪ failed)`, with `--retry-failed` to re-queue. This is a real
   semantic decision hiding inside "catalog − log" and should be explicitly approved.

2. **Catalog cost in real-time mode.** Recomputing "what exists" every
   `poll_frequency` may be expensive for remote/API handlers (full survey per poll).
   v1 accepts this (sequential, simple); the handler's `catalog` taking a dimension
   range at least lets configs bound the survey window. Flagging that there is no
   incremental-catalog contract in v1.

3. **Dimension vocabulary at the handler boundary.** The delta requires handlers to
   report availability in the *config's* dimension names, but handlers are written
   blind, before any particular config exists. The dimension-spec contract must
   therefore define how a handler declares which dimensions it resolves (e.g. the
   handler declares dimension *roles* it needs, and config maps names to them — to be
   pinned down precisely in `HANDLER_AUTHORING.md`/`CONFIG_AUTHORING.md`). This is the
   subtlest contract in the system and the likeliest place for blind-authoring to
   fail; I will give it disproportionate attention in the docs.

4. **One-file-per-stage vs. the version-bump CI check.** The stage's test lives in the
   same file as the stage; a test-only edit will trip "changed stage file must bump
   version," forcing meaningless bumps. Options: accept the noise (safest,
   simplest) or split the test into a sibling file (weakens "one self-contained
   file"). I propose accepting the noise for v1 and noting it in
   `STAGE_AUTHORING.md`; flagging the tension for your call.

5. **Un-bypassable `__init__` mechanics.** Enforcing "subclasses may not override
   `__init__`" via `__init_subclass__` is straightforward for direct subclasses but
   has edge cases (multiple inheritance, `__init__` inherited from a mixin). I'll
   enforce it by inspecting the subclass `__dict__` at definition time, and document
   the mixin restriction explicitly in the authoring docs.

6. **`build-image` scope.** "Crystallize the current core + installed packages" can
   balloon (introspecting arbitrary environments). I propose the v1 semantics be:
   generate a Dockerfile from the current `uv.lock` + the set of installed
   rainspout-entry-point packages and build it — nothing cleverer. In scope, but
   minimal.

7. **Cython in `tests/`.** Setup-time compilation in the reference content means CI
   needs a C toolchain and the test suite gains a build step. Required by the design
   (proves the setup path); accepted, but it is the most likely source of CI
   flakiness and will be isolated so a compiler-less environment skips only that
   marked test with a loud notice — with CI always running it.

8. **Lazy-reference windowing vs. handler windowing are two different layers.** A
   reference's `window()` (inter-stage, in-memory or handler-backed) and a handler's
   `supports_windowed_read` (within-file) are independent capabilities that happen to
   rhyme. The docs must keep them visibly distinct or blind authors will conflate
   them; `HANDLER_AUTHORING.md` and `STAGE_AUTHORING.md` will each carry a "not to be
   confused with" note.

9. **Realtime stop semantics.** "Forever until stopped by the user" — v1 will treat
   Ctrl-C/SIGTERM between work items as a clean stop (finish current work item, flush
   oplog, exit 0). Mid-work-item interrupt kills that item; the oplog simply never
   records success, so resume re-does it. Cheap to implement, but stating it so it's
   an approved behavior rather than an accident.

---

**STOP — Gate 1.** Awaiting your review of this plan (especially §3's proposed
decisions and §5's flagged calls) before drafting the Gate 2 authoring documentation.
