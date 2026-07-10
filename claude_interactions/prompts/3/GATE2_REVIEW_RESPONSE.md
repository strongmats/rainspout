# Gate 2 Review — Response

Approved to proceed to implementation, **after** folding in the corrections below.
The authoring docs and tutorials are strong and the eleven proposed decisions are
sound — most are approved as-is, several with small clarifications. The substantive
changes are in Part B (the dimension / seed / coordinate model), which needs real
revision across STAGE_AUTHORING, HANDLER_AUTHORING, CONFIG_AUTHORING, and the tutorials
before you build.

---

## Part A — The eleven proposed decisions

**#1 (private handler hooks) — APPROVED.** Good pattern, consistent with un-bypassable
`Stage.__init__`. Requirement: the base-class public methods (`load`/`save`/`catalog`/
`preflight`) must DOCUMENT what they do around the hooks (range expansion, per-cell
iteration, error wrapping) so a blind author isn't confused by hidden behavior.

**#2 (driver expands ranges; handlers see explicit values) — APPROVED.** Right seam;
removes range-expansion burden from every handler. Lazy per-cell iterator is consistent
with the rest of the laziness model.

**#3 (role-mapping syntax) — APPROVED, and extended by the seed model in Part B.** The
`{handler_role: config_dimension}` mapping is correct. See Part B for how it applies to
the new `seed:` block and the seed-specific validation rule.

**#4 (pre-flight contract) — APPROVED in shape; scope clarified in Part B.** The probe
(role check → type check → structural probe on first cataloged cell → empty-catalog ⇒
skip with a loud logged notice) is good. Clarification: rigorous dimension/pre-flight
validation applies to the SEED handler (whose roles must match the iterated dimensions
exactly). Auxiliary handlers are not dimension-validated at startup (Part B).

**#5 (wiring kinds as type annotations) — APPROVED.** `LazyReference` ↔ `from:`,
`BoundHandler` ↔ `loader:`, mismatch fails loudly naming stage + field. Two notes:
(a) `from: seed` is a valid `LazyReference` wiring (the seed behaves like an upstream
producer — Part B); (b) `BoundHandler` stays simple — a stage calls `.load()` and gets
data; it does NOT drive the handler across derived coordinates (Part B).

**#6 (metadata embedding) — APPROVED WITH CHANGE: single-file, no sidecars.** Remove the
`.rainspout.json` sidecar fallback. Metadata should be embedded in the ONE data file.
Rules:
- Strong recommendation: use a metadata-capable format and embed the provenance chain
  in the data file itself. Discourage auxiliary metadata files.
- Metadata handling is OPTIONAL — a handler may ignore metadata entirely (e.g. a plain
  CSV author's choice). This breaks the provenance chain for data through that handler;
  that's the author's accepted tradeoff, highly discouraged but allowed.
- The round-trip test checks PRESERVATION of whatever exists: data always, plus metadata
  IF the handler handles it. It never fails a handler merely for not handling metadata;
  it fails one that ALTERS data or metadata across load→save→load.
- Foreign / metadata-less data loads fine; provenance starts fresh from that point (no
  failure).
- Docs should teach responsible in-file embedding for plain-text formats (a clearly
  delimited, strippable section) for authors who choose to embed.

**#7 (code/test hash boundary) — APPROVED.** `test_*.py`/`*_test.py`/`fixtures/`/
`example_data/` excluded from the code hash and bump requirement; all other `*.py` are
stage code. Safe default (over-hash rather than under-hash). State the rule plainly in
STAGE_AUTHORING.

**#8 (test inside the component directory) — APPROVED.** Correct call — the test is the
executable half of the self-containment contract; keeps conformance checks local, makes
orphan tests impossible, supports copy-as-unit. Package-level `tests/` reserved for
cross-component integration. The cost (test code in `src/`) is acceptable.

**#9 (`rainspout.testing` public helpers) — APPROVED.** `run_stage`, `from_handler_data`,
`assert_roundtrip` (float-tolerant, `equal=` escape hatch), plus the required module-level
names (`STAGE`/`EXAMPLE_SETTINGS`; `HANDLER`/`EXAMPLE_RESOURCES`/`EXAMPLE_COORDS`).
Requirement: treat these signatures as a v1 API STABILITY COMMITMENT — packages will pin
to them — so keep them minimal and design them to last, same weight as
`rainspout.contracts`.

**#10 (entry-point groups) — APPROVED.** `rainspout.components` (one collector module
importing all components; import = registration) and `rainspout.verbs` (Typer app; mount
name = entry-point name). Collision fails loudly naming both packages. Two doc notes:
(a) adding a component to an existing `components.py` is live, but adding/changing an
entry point needs `uv sync` to be discovered; (b) a component missing from the collector
module fails SILENTLY (just doesn't register) — tell authors every component must be
listed, verifiable via `spout catalog`.

**#11 (CLI details) — APPROVED, one clarification.** `--retry-failed`, `--dry-run`
done/failed/to-run counts, and `poll_frequency` forbidden outside realtime are all good
(the last is a correct loud-failure tightening). For `--select dim=value`: spell out its
interaction with the delta and `--retry-failed` — default behavior is that `--select`
still RESPECTS the log (an already-done selected cell is skipped), and combines with
`--retry-failed` to force re-running a selected failed/done cell. Make this explicit in
the docs so there's no ambiguity.

**Flagged `loader:`-window limitation — RESOLVED / dissolved.** Given the Part B decisions
(linear DAGs, aggregation via separate runs, stages don't drive handlers across derived
coordinates), a stage does not need to pull a window of cells through a `loader:`
dependency. Leave this as a documented v1 boundary; do not build windowed-`loader:` syntax.

---

## Part B — Dimension / seed / coordinate model (substantive revision)

This corrects an over-application in the current docs: they state stages are
"dimension-blind / never see coordinates." That is too strict and would make real science
impossible (e.g. snipping sferics requires knowing the file's start time — its position in
the time dimension). The correct principle is: **the SKELETON is dimension-agnostic (it
hardcodes no dimension names); STAGES are coordinate-aware.** Revise as follows.

**B1 — Stages are coordinate-aware, not blind.** A stage receives its current work-item
coordinate as a generic role→value mapping (e.g. `{"time": ..., "receiver": ...}`), tagged
onto the reference alongside data and metadata. It reads this freely for position-dependent
science (file start time, etc.). The skeleton hardcodes no dimension names — they come from
config. Remove all "stages never see dimensions / don't look for coordinates" language;
replace with "stages read their current coordinate but the skeleton is agnostic about what
the dimensions are."

**B2 — The coordinate is driver-set and read-only.** The driver stamps the coordinate onto
the reference at seed time (see B3). It flows downstream automatically as references pass
stage to stage. Stages READ it; they do not forge or alter it (keeps it trustworthy for
provenance).

**B3 — Seeding via a `seed:` config block; no boilerplate seed-loader stage.** Data enters
the DAG through a `seed:` block in config, not through a hand-written pass-through stage.
The block names the seed handler and maps the iterated dimensions to its roles:

```yaml
dimensions:
  time: {start: ..., stop: ..., step: 1h}
  receiver: [alpha, bravo]

seed:
  handler: broadband_local_mat
  dimensions: {file_time: time, rx: receiver}   # handler_role: config_dimension
```

The driver, per work-item cell, calls the seed handler, stamps the coordinate onto the
resulting reference, and feeds it to the first stage, which consumes it via ordinary
`from: seed` (a valid `LazyReference` wiring). No package writes a boilerplate seed stage.
Shape `seed:` as a map so multiple named seeds is a clean future addition, but only ONE
seed is used for now (single linear branch — B5).

**B4 — Two handler categories.**
- **Seed handler** (in `seed:`) loads along the ITERATED dimensions; the driver coordinates
  with it. Startup rule: its mapped roles must correspond EXACTLY to the iterated dimension
  set (every role mapped, to a real dimension, types coercible) — checked loudly at startup,
  then the pre-flight probe (#4) confirms structural sanity on one cell.
- **Auxiliary handler** (a stage's `loader:` dependency, e.g. Vaisala events) loads along
  its own dimensions. It is configured in `handlers:` and wired to the stage; the stage
  calls `.load()` and gets data. NOT dimension-validated at startup. Whether the loaded data
  serves the stage (including legitimate SUPERSET/SUBSET relationships — the handler may load
  a rich structure the stage uses one piece of) proves out at RUNTIME; a genuine mismatch is
  an isolated per-work-item runtime failure, logged.

**B5 — Linear DAGs only for now.** Support linear stage chains, but keep the runner on
GENERAL graph machinery (topological sort, dependency resolution) so branching is a later
non-breaking addition — do NOT hardcode linearity (no "each stage has exactly one input"
assumption). Do NOT build branching / convergence / fan-in / aggregation features now.
Aggregation or collapsing across a dimension is done by running a SEPARATE process/config at
a different granularity that reads what a prior run saved (consistent with the existing
no-mid-DAG-collapsing rule).

**B6 — Dimension names are config-author bookkeeping, not enforced contracts** — except at
the one edge where they must be exact: the seed handler's roles vs. the iterated dimensions
(B4). Everywhere else, names exist so the config author can track which dimension is which
across the file; the skeleton does not enforce name matching between an auxiliary handler
and a stage. Do not add stage-declared "expected dimensions" — deliberately rejected, because
real handler↔stage data relationships are rich (superset/subset) and over-constraining them
would reject valid configurations.

---

## What to revise before implementing

- **STAGE_AUTHORING:** remove dimension-blindness language; add coordinate-awareness
  (read-only, tagged on the reference); clarify `BoundHandler` is call-and-receive (no
  stage-driven coordinate steering).
- **HANDLER_AUTHORING:** seed vs. auxiliary categories and their different validation;
  single-file metadata (remove sidecar); round-trip preserves-what-exists.
- **CONFIG_AUTHORING:** add the `seed:` block + its role mapping + the seed-specific startup
  rule; `from: seed` wiring; `--select` × delta × `--retry-failed` semantics; drop sidecar
  mentions.
- **Tutorials:** replace the hand-written seed-loader stage (Tutorial 3 Step 0) with the
  `seed:` block; keep everything else.
- Keep the runner graph-general (B5).

Proceed to phased implementation once these are folded in. Continue to STOP between phases
per the original plan.
