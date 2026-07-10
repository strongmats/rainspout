# Gate 1 Review — Response

Approved to proceed to Gate 2, with the corrections, decisions, and clarifications
below. The architecture restatement is faithful and the §3 decisions are largely
right. Fold all of the following into the Gate 2 documentation, then STOP for review
before any implementation.

## Corrections (required)

**C1 — Handler naming: no dot; they are Python files.**
Handlers are Python modules, so the file is e.g. `broadband_local_mat.py`, and the
registry name uses underscores, not a filename-with-extension. Drop the
`datatype_accesschannel.type` convention with the dot. Use `datatype_channel_type`
(e.g. `broadband_local_mat`, `cleaned_local_h5`). The name stays purely conventional
and is never parsed.

## Decisions & answers

**Q1 (delta) — confirmed.** Delta = `exists − attempted`, where *attempted* is every
(stage, work item) already in the operational log, success or failure — nothing already
tried is re-run automatically. Keep an explicit `--retry-failed` flag as the deliberate
escape hatch for transient failures. (Resolves risk #1.)

**Q2 (catalog cost) — accepted, with a requirement.** v1 accepts per-poll cataloging.
Requirement for `HANDLER_AUTHORING.md`: a handler's `catalog` must survey only the
**windowed dimension range it is asked about**, never the entire dimension space in
storage.

**Q3 (dimension boundary) + startup pre-flight — approved and extended.** Your plan
(handlers declare the dimension *roles* they resolve; config maps names to them) is
right — give it the disproportionate attention you promised. ADD a **startup pre-flight
check**: beyond validating that config dimension names and handler-declared roles line
up (definition-time), the driver asks each handler to validate a **single probe
coordinate** at startup — cheaply confirming the dimension spec resolves to
structurally-sane data (right type/structure) without surveying all data. If the
furnished dimensions don't correspond to available data — even with correct names but a
type/structure mismatch — this fails loudly immediately. Genuine per-coordinate data
problems (one file missing/corrupt) still surface per-work-item at runtime and are
logged. Propose the exact pre-flight/probe contract in the docs for review — this is the
subtlest seam.

**Inter-stage structural check — DO NOT build it.** We considered checking stage→stage
data-structure compatibility at startup, but a useful version would require granular
per-input/output structural contracts on every stage — too heavy an authoring burden for
the value. Skip it. If a stage hands the wrong structure to the next stage, that surfaces
as a normal per-work-item runtime failure (isolated, logged, run continues). This is an
accepted tradeoff: validate the *edges* (data in from storage, via the pre-flight)
strictly and early; do not burden internal stage-to-stage seams with contracts.

**Q4 (stage packaging & version-bump) — REVISED: one stage = one self-contained
directory, not one file.** Drop the "one stage = one file" rule (it fought the
thin-orchestrator principle, since science functions need their own files anyway).
Instead: **one stage = one self-contained directory** — a self-contained unit that
can (and generally should) have whatever internal substructure it needs: subdirectories
for science functions, helpers, its test, any stage-local resources, etc. The point is
self-containment and NOT-one-file — not flatness; organize the interior however suits
the stage. The version-bump CI check (and the provenance code-hash) watches the **stage
code file(s) only**, so editing the test does not trip it. Document how the code/test
boundary is delineated for hashing.

**Q5 (un-bypassable `__init__`) — approved.** Enforce by inspecting the subclass at
definition time; document the mixin/multiple-inheritance restriction in the authoring
docs. (Enforcement mechanism for an existing rule; no scope change.)

**Q6 (`build-image`) — approved, minimal.** v1 = generate a Dockerfile from the current
`uv.lock` + the set of installed rainspout entry-point packages, and build it. Nothing
cleverer.

**Q7 (compilation in tests) — DROPPED.** Do not require setup-time compilation (Cython)
in the reference content, and do not pull a C toolchain into CI. Keep only a **trivial,
observable setup-hook exercise** in the reference content (e.g. the hook writes a marker
/ sets a flag) to prove the setup hook fires. This removes the biggest CI-flakiness risk.

**Q8 (two windowing layers) — approved.** Keep handler within-file windowing
(`supports_windowed_read`) and lazy-reference inter-stage `window()` visibly distinct in
the docs, each with a "not to be confused with" note.

**Q9 (real-time stop) — approved as described.** Clean stop between work items (finish
current item, flush oplog, exit 0); mid-item interrupt never records success, so resume
re-does that item.

## New requirements to fold in

**Settings must be bounded.** Beyond existence and type, every setting must constrain its
valid domain — numeric ranges via Pydantic `Field`, discrete choices via `Literal`/
`Enum`, constrained strings, etc. Unbounded settings are permitted only as a deliberately
justified exception, never the default. `STAGE_AUTHORING.md` and `HANDLER_AUTHORING.md`
must require authors to declare each setting's usable range/options; an out-of-range or
invalid-option value fails loudly at startup like any other bad setting. A bare
unconstrained numeric/string field should at least draw a lint-style warning requiring
justification.

## Package folder structure — YOU propose it, unbiased

The package folder layout is one of the things you must PROPOSE in `PACKAGE_AUTHORING.md`
and justify — make the final decision yourself, from first principles. No layout is
prescribed here deliberately, to avoid biasing your design. The only constraints: a
package holds multiple stages (each a self-contained directory as in Q4) and multiple
handlers (each with its example data file for round-trip tests), may contribute CLI
verbs and lifecycle/artifact code, and must ship conforming tests. Organize all of that
however you judge best.

Explicitly decide and justify: **does a stage's test live inside the stage's own
directory (self-contained) or in a shared package-level tests location?** Both are
defensible; pick one, explain why, and keep it consistent with the "self-contained stage
directory" decision above.

## Everything else approved

Repo structure for `rainspout-core`, the seam discipline, §3.1/3.2/3.3/3.5/3.7, and the
phase plan are approved as written (Phase 7 loses the Cython requirement per Q7).
Proceed to Gate 2 (authoring docs + tutorials), then STOP for review.
