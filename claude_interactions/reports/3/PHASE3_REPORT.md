# Phase 3 report — handlers & the data plane

**Done.** 154 tests passing (34 new), coverage 96.2% against the 90% floor,
ruff + mypy clean. Stopped at the end of the phase.

## What was built

**`contracts/metadata.py`** — the shared metadata block:
- `ProvenanceEntry` — `{stage_name, stage_version, code_hash, settings_used,
  timestamp, warnings}` (warnings included per STAGE §8: they land in
  provenance as well as the operational log).
- `Meta` — schema version, `run_id`, coords, provenance chain. Immutable;
  evolves via `with_entry` (order-preserving append). `Meta.fresh(coords=…)`
  for foreign/first-entry data. **Coords values are canonicalized to
  strings** so the block survives any format's JSON round-trip byte-exactly —
  the canonical serialized coordinate doubles as the per-work-item sub-key
  (`cell_id`) next to `run_id`. Proven: full JSON round-trip equality test.
- `CatalogDocument`/`CatalogFileEntry` — the validated shape of a written
  catalog file (handler, roles, entries, generated-at).

**`contracts/dimension.py`** — `Coords` and `DimensionSpec` aliases, frozen
`Cell(coords, data, meta)` and `CatalogEntry(coords, extras)`.

**Handler verb bodies** (`contracts/handler.py`) — the final public verbs now
do everything their docstrings promised:
- `load(spec)` — spec checked against declared roles (exactly; tuple-of-one,
  no scalar special case; empty tuples rejected); a multi-cell spec on a
  non-grid-range handler fails **eagerly at the call**, not at first
  iteration; cells stream as a lazy generator (proven: zero hook calls before
  the first `next()`, exactly one after), iterating the cross-product in
  declared role order; hook errors wrapped naming handler + coordinate; a
  hook returning something other than `(data, meta)` is a named failure.
- `load_one(coords)` — the single-cell call (what stages make on
  auxiliaries): exact-role check, direct `(data, meta)` return.
- `save(spec, data, meta)` — single-cell enforced for every handler; `meta`
  must be a `Meta`; errors wrapped.
- `catalog(spec)` — lazy; every yielded entry checked to be a `CatalogEntry`
  keyed by the declared roles; with `write_path=` the base additionally
  writes the validated catalog document (hook only yields entries, as
  documented).
- Within-file windowing — `window=` on `load`/`load_one` gated by
  `supports_windowed_read` and passed through to `_load_cell(coords, window)`.

**`rainspout.testing`** — the public, stability-committed helpers:
- `run_stage(STAGE, EXAMPLE_SETTINGS, deps=…, coords=…)` — real validation
  path (bad `EXAMPLE_SETTINGS` fails exactly like config would), values
  wrapped per the field's declared wiring kind, `coords=` stamped on the
  references, `setup()` then `run()`.
- `from_handler_data(obj)` — a fake handler serving `obj` for **any**
  coordinates the stage computes (via a private, testing-only escape hatch on
  the base's coords check; real handlers keep the strict exact-roles rule).
- `assert_roundtrip(...)` — load → save → load → equal → catalog, with
  **preservation-of-whatever-exists** semantics made real: a probe provenance
  entry is injected before saving so metadata preservation is genuinely
  exercised; a metadata-ignoring handler passes; a data-altering or
  claimed-metadata-altering handler fails with a named assertion. Float
  tolerance via a recursive `values_equal` (bools ≠ numbers; `equal=` escape
  hatch). Save side defaults to `EXAMPLE_RESOURCES` with `base_dir`
  retargeted; `save_resources=` for handlers shaped differently (one
  sentence added to HANDLER §12 documenting this — the only doc change).

## The stress test

The reference handler in `tests/roundtrip_handlers.py` is **Tutorial 1's CSV
handler verbatim** — one CSV per cell, metadata embedded as the single
strippable `# rainspout-meta:` comment line — so the tutorial's pattern is now
machinery-proven: it loads foreign (metadata-less) data with fresh provenance,
embeds and recovers the block intact through `assert_roundtrip`, and catalogs
only the asked window. Deliberately broken variants (rounds values on save;
mangles provenance entries) fail the round-trip with the right named messages,
and a metadata-*ignoring* variant passes, as the contract requires.

Phase-plan done-criterion check: reference handler passes the mandated
round-trip ✓; range-on-non-range fails loudly (eagerly at the call site, per
the Gate 2c scoping — startup for the run's own wiring, per-work-item when a
stage asks) ✓.

## Naming note

`load_one` remains the stage-facing single-cell verb per the docs; the
`load_cells` naming question from the Phase 1 review is still open — a rename
is trivial if wanted, and Phase 4 (runner) is the last cheap moment for it.

**STOP — end of Phase 3.** Next on approval: Phase 4, the runner — one work
item through the DAG end to end: dependency resolution/injection, the seed
path, config-designated saves, operational-log and provenance writes,
status/progress surfacing.
