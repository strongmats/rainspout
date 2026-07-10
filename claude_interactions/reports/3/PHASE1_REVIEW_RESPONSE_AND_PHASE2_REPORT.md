# Phase 1 review response + Phase 2 report

## Phase 1 review — required change, confirmations, and one discrepancy to flag

**Required change (negative-test coverage of the `__init__` enforcement) —
addressed, with a correction to the premise and a real strengthening.** The
premise in the review doesn't match what was delivered: Phase 1 shipped **no
coverage exclusions** anywhere (no `# pragma: no cover` in the codebase), and
the negative tests already existed (`test_defining_init_fails_at_class_definition`,
`test_mixin_with_init_rejected`, and the handler equivalents). I did not merely
confirm that, though — the review's spirit exposed a genuine remaining bypass:
`cls.__init__ = ...` **after** class definition, which `__init_subclass__`
never sees. That door is now closed by a contract **metaclass** whose
`__setattr__` rejects post-definition assignment of `__init__` and of every
final method (stage reporting machinery; handler public verbs), on subclasses
and on the bases themselves. Four new negative tests cover it, including an
explicit bypass-attempt test that then proves settings validation still fires.

**Confirmation 1 (one concept, two entry points) — yes.** HANDLER_AUTHORING §6
presents seed vs. auxiliary as "Two positions, one contract": the same class,
authored identically, never knowing which position it will be wired into. The
authoring surface (hooks, resources, roles, tests) is identical for both.

**Confirmation 2 (`run_id` + per-work-item sub-key) — yes**, as planned in
Gate 1 §3.5; lands with the operational log (Phase 4/5). Now recorded in the
consolidated design doc (§F).

**Discrepancy flagged, decision needed (cheap either way):** the review
describes the verb split as "`load()` (seed, no-arg) vs `load_cells(coords)`
(auxiliary)". What the docs and contracts actually specify: public
**`load(spec)`** — the general verb, spec = `{role: (values…)}`, used by the
driver for the seed and available to stages — plus final **`load_one(coords)`**,
the single-cell convenience stages typically call on auxiliaries. There is no
no-arg load anywhere (the driver always supplies each work item's coordinates),
and the *distinction being confirmed* — driver-driven seed vs. stage-called
auxiliary — is exactly what's implemented. If you specifically want the
stage-facing call named `load_cells` instead of `load_one`, say so — it's a
one-line rename in Phase 3 plus doc touch-ups; otherwise `load/load_one`
stands.

## Phase 2 — config & DAG validation: DONE

New modules (57 → **120 tests**, coverage **96.9%** against the 90% floor,
ruff + mypy clean):

- `src/rainspout/config.py` — the six-key Pydantic schema (`extra="forbid"`
  throughout), YAML loader with named-offender wrapping, dimension expansion
  (inclusive numeric / date / datetime ranges with `1d/6h/30m/15s` steps;
  list form with order preserved and duplicates rejected), iteration-order
  rules, `poll_frequency` iff realtime.
- `src/rainspout/dag.py` — **general** topological sort (cycles fail loudly
  naming members) plus the **separate** v1 linear-chain rule (every stage
  exactly one upstream, every producer at most one consumer, all stages
  reachable from the seed) — honoring B5: linearity is a validation rule, not
  an assumption in the machinery.
- `src/rainspout/validation.py` — the gate sequence (`validate` = `run`'s
  front half, no skip path): parse → dimension expansion → seed rule (one
  entry; construct through the real resources path; role map exact both ways;
  values coercible to declared types via TypeAdapter) → handler instances
  (dangling-name check on any `dimensions:` map; save targets required to
  carry seed-grade maps) → stages (constructed through the un-bypassable
  settings path; missing/extra/misspelled deps; wiring kinds read from the
  dependencies-model **annotations**, `LazyReference` ↔ `from:` / `Handler` ↔
  `handler:`; `from:` resolves to a stage or the seed entry; seed/stage name
  collision) → graph. Returns a `ValidatedRun` (expanded dimensions, iteration
  order, constructed seed/handler/stage instances, topological stage order)
  for the runner and driver to consume in Phases 4–5.
- `src/rainspout/cli/main.py` — the `spout` Typer app with `validate`
  (discovers entry-point components, runs the gates, `config ✓ registry ✓
  DAG ✓ settings ✓` or exit 1 with the named offender). `[project.scripts]`
  wired; verified end-to-end.

Done-criterion check: every definition-time failure mode in design §G has a
specific named-offender message **and a test asserting that message**
(~40 failure-mode tests across `test_config_models.py`, `test_dimensions.py`,
`test_validation.py`); a valid config validates instantly touching no data
(sample components use plain string resources; nothing on disk but the YAML).

One deliberately unexercised line: the "stages unreachable from the seed"
branch in the linearity check is defensive — under the preceding rules
(acyclic + one input each + one consumer each + `from:` must resolve) it is
provably unreachable, but it stays as a cheap invariant guard rather than a
pragma or a deletion.

## Design-doc consolidation — delivered

**`RAINSPOUT_DESIGN.md` now exists at the repo root**: the full v2
consolidated spec — the original document with Gate 1, Gate 2, 2b, 2c, and
the Phase 1 review folded in, plus §M (build status) and §N, a one-table
**decision record** mapping every changed decision to the review that settled
it. The five-layer prompt-2 stack is superseded; drift closed.

**STOP — end of Phase 2.** Next on approval: Phase 3, handlers & the data
plane (verb bodies for `load`/`load_one`/`save`/`catalog`, `Meta`/provenance
models, `Cell`/`CatalogEntry`, capability enforcement, `rainspout.testing`
with `assert_roundtrip`) — where, as the review predicts, the contracts meet
their first genuine stress test.
