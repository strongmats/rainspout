# Agent Prompt — Build the Rainspout Skeleton (documentation-first, gated)

## Your role and the ground rules

You are building **Rainspout**, a general-purpose, domain-agnostic scientific
data-processing pipeline **framework** (the "skeleton"). Its distribution/import name
is `rainspout` and its CLI command is `spout`. Rainspout hosts pluggable *content
packages*; **SkyCT** (VLF ionospheric tomography) is one such package built on top of
it, NOT the framework — do not bake any VLF/SkyCT-specific assumptions into the
skeleton. A companion design document, `RAINSPOUT_DESIGN.md`, is the authoritative
specification — read it in full before doing anything. It records
deliberate decisions; follow them exactly. Where it marks something as "left to the
agent to propose," propose a concrete answer for review — do not silently assume it in
code.

This build is **gated**. You will STOP at two checkpoints and wait for explicit human
approval before proceeding. Do not write implementation code until after Gate 2 is
approved. Producing code early, or blowing past a gate, is a failure of the task.

**Clean slate.** You are NOT given any existing repository, and you must not ask for or
reconstruct one. A prior mock implementation exists but is deliberately withheld because
it encodes reversed decisions and would bias your design. Build only from the design
document.

If any instruction here conflicts with the design document, the design document wins;
surface the conflict rather than guessing.

---

## GATE 1 — Plan and reflection (produce this, then STOP)

Read `RAINSPOUT_DESIGN.md` fully. Then produce a single planning document
containing:

1. **Architecture restatement in your own words** — enough to demonstrate you
   understood the core/content split, the handler model (combined handlers,
   load/save/catalog, the two independent range concepts, private lifecycle), the
   stage model (thin orchestrator, settings/dependencies/resources, seed-loader-as-
   stage, status/progress, versioning), the one-DAG-all-dimensions driver (work items,
   retrograde vs. real-time as a catalog−log delta with `poll_frequency`, sequential
   processing, per-work-item failure isolation), the two logging systems (operational
   log vs. provenance chain), config-designated saving, and un-bypassable validation.
   Restating it wrong here is the cheapest place to catch a misunderstanding — be
   thorough.

2. **Proposed repository / package structure** — the file and directory layout for
   `rainspout-core`, with the core/content seam clean (core never imports concrete
   stages/handlers; everything flows through the registry and entry points). Show where
   base contracts, the brain (registry/config/runner/driver/logging/CLI), the authoring
   docs, tests, and the trivial reference content will live.

3. **Proposed answers to the "left to the agent" items** (from the design doc's
   section O). For EACH, state your proposed decision and a one-line rationale:
   - exact config YAML schema (top-level shape)
   - how a stage receives its handler (runner injection vs. stage construction) and
     when in the lifecycle
   - whether a stage receives a lazy reference or materialized data (who materializes,
     when)
   - the error-vs-warning taxonomy and its effect on resume
   - `run_id` granularity (per-run vs. per-work-item)
   - the versioning-change detection mechanism (git diff vs. code-hash vs. both)
   - exact `catalog` output contents

4. **Proposed phase plan** for implementation (after Gate 2), with a clear "done"
   criterion per phase and the note that you will stop between phases.

5. **Any risks, ambiguities, or tensions** you see in the design, stated plainly.

Then **STOP** and wait for approval. Do not draft documentation or code yet.

---

## GATE 2 — Authoring documentation (after Gate 1 approved; produce, then STOP)

Only after the plan is approved: draft the **interface before the machinery**. Produce
the authoring standards and tutorials. These docs are the literal contract between the
skeleton and content packages — treat them as first-class deliverables that a person
with NO skeleton access could build a conforming component from.

Deliverables:

- `STAGE_AUTHORING.md` — how to write a conforming stage (settings/dependencies/
  resources, thin-orchestrator rule, seed-loader case, setup hook, status/progress,
  versioning, the required per-stage test format, what NOT to do, self-check list).
- `HANDLER_AUTHORING.md` — how to write a conforming handler (the combined-handler
  model; load/save/catalog contracts; the dimension-spec input with single=range-of-
  one; the two independent range capabilities and how they're declared; private
  lifecycle; the required shared metadata block; the required round-trip test +
  example-data-file format; what NOT to do; self-check list).
- `PACKAGE_AUTHORING.md` — the anatomy of a content package (what it ships: stages,
  handlers, configs, optional CLI verbs, optional lifecycle/artifact commands, tests;
  how it registers via entry points; how it declares package-contributed CLI verbs;
  its own CI + coverage expectations).
- `CONFIG_AUTHORING.md` — the `.yml` config structure (dimensions; iteration mode +
  `poll_frequency`; the DAG/stage wiring with `from:`/`loader:` dependencies;
  per-stage settings; config-designated saves via named handlers).
- Three tutorials, written to double as acceptance tests: **add a handler**, **add a
  stage**, **create a run (config)**.

Then **STOP** and wait for review of the documentation before writing any
implementation code.

---

## After Gate 2 — Phased implementation (against the approved docs)

Build in the approved phases, stopping between each to report. Throughout:

- **Tooling:** uv (commit `uv.lock`, gitignore `.venv`), Typer CLI, Pydantic v2,
  structlog, pytest + pytest-cov, ruff, mypy, GitHub Actions.
- **Coverage:** enforce a 90% floor (aim 95%+) via pytest-cov with a hard-failing CI
  gate; `# pragma: no cover` allowed only with justification.
- **Uniform registration** across every axis via the same `__init_subclass__` gesture.
- **Un-bypassable validation:** settings validated in base `__init__`; subclasses may
  not override `__init__`.
- **The trivial reference content** (in `tests/`) must include a mid-DAG extra
  dependency AND setup-time compilation (e.g. Cython) to prove the setup/compilation
  path. Keep it separate from the clean pedagogical example.
- Build the CLI: `run` (`--config`, `--mode`, dimension selection, `--dry-run`, resume),
  `validate`, `catalog`, `setup`, `build-image`, `test-package`, plus support for
  package-contributed verbs. No orchestration/parallelism.

The final phase must demonstrate the skeleton runs the trivial reference content
end-to-end, every specified failure mode breaks loudly with a specific message, and the
tutorials work as written.

Report at every stop. Do not skip gates.
