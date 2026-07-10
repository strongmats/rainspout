# Phase 4 report — the runner

**Done.** 170 tests passing (16 new), coverage 96.1% against the 90% floor,
ruff + mypy clean. `load_one` naming retained per your call. Stopped at the
end of the phase.

## What was built

**`oplog.py`** — the operational log: append-only JSONL with two validated
record kinds — `StageRecord` per (stage × work item) execution (status,
status line, warnings, error, timestamps) and `WorkItemRecord` summaries.
Query helpers for Phase 5's delta are already in place: `attempted_cells()`
(success or failure alike — the delta's subtrahend) and `failed_cells()`
(latest summary failed — what `--retry-failed` re-queues).

**`provenance.py`** — the code hash and chain entries:
- `hash_component_dir` implements the code/test boundary exactly as
  documented: all `*.py` under the component directory, sorted, **excluding**
  `test_*.py`, `*_test.py`, `fixtures/`, `example_data/`. Tests prove the
  hash changes with code edits and new code files, and does NOT change when
  test files, fixtures, or example data change.
- `provenance_entry(stage, warnings=…)` builds the
  `{stage_name, stage_version, code_hash, settings_used, timestamp, warnings}`
  entry from a live stage (settings serialized in JSON mode).

**`runner.py`** — `run_work_item(validated, coords, run_id=…, oplog=…)`:
- **Seed path**: the seed cell is loaded lazily and at most once, through the
  role map, wrapped in a coordinate-stamped `LazyReference` offered under the
  seed entry's name — exactly the `from: raw` contract.
- **Injection**: per stage, `from:` fields get the upstream reference
  (coordinate stamped), `handler:` fields get the constructed instance;
  the dependencies model is built through its real constructor.
- **Provenance**: the chain base is the seed cell's block if it was pulled
  (foreign data ⇒ fresh), and each succeeding stage appends its entry; a
  config-designated save writes `Meta(run_id, coords, base + chain)` through
  the target's role map. Proven both ways: a mid-DAG save carries only the
  chain-so-far; the terminal save carries the full ordered chain; and a
  **second run seeding from the first run's output extends the existing
  chain rather than replacing it** (the cross-run reproducibility story,
  now a passing test).
- **Failure isolation**: any stage exception (or a failure saving its
  output — recorded as that stage's failure, since its contract didn't
  complete) fails this one work item: stage + work-item failure records,
  downstream skipped, result returned — never an exception out of the
  runner. A preceding stage's mid-DAG save survives, as it should.
- **Status/warnings surfacing**: the stage's status line and its *per-work-
  item* warnings land in the oplog record and the provenance entry — with a
  regression test proving warnings don't leak between work items (stage
  instances are reused; the runner tracks the offset).
- `prepare_stages` runs every `setup()` once, post-validation, pre-work;
  `cell_id(coords, order)` is the canonical `day=2026-01-01|sensor=s1` form
  used by both logging systems.

## Done-criterion check

"One work item runs end-to-end through a multi-stage DAG with a mid-DAG
save; provenance chain and oplog records verified" — the headline test does
exactly this: seed (Tutorial 1's CSV handler) → `scale` (saves mid-DAG) →
`total` (terminal save), then reads both outputs back through the handler and
asserts data, chain order, versions, settings, 64-char code hashes, `run_id`,
and canonical coords; a sibling test asserts the full oplog record sequence.

## Notes for Phase 5

- The runner deliberately catches `Exception`, not `BaseException` — Ctrl-C
  propagates, which is what the driver's clean-stop semantics need.
- OpLog placement (where the file lives per run) is a driver/CLI decision
  deferred to Phase 5, as is `run_id` generation.

**STOP — end of Phase 4.** Next on approval: Phase 5, the driver — work-item
enumeration in iteration order, the catalog−log delta, retrograde drain,
realtime poll loop, `--select`/`--retry-failed`/`--force-rewrite`, dry-run
planning, clean stop.
