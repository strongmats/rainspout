# CONFIG_AUTHORING.md — The Rainspout run configuration (`.yml`)

A run is described by **one YAML file**. The whole file is parsed into a
validated model at load: unknown keys, missing keys, and out-of-domain values
fail immediately with a message naming the offending key — before any data
moves. `spout validate --config run.yml` performs exactly the checks `spout
run` would perform (config parse → registry resolution → seed dimension rule →
DAG validation → per-stage settings validation; the seed's pre-flight probe is
run-only); there is no skip-validation path.

## 1. Top-level shape — six keys

```yaml
run:        # identity + iteration mode
dimensions: # the named axes of the work
iteration:  # order over those axes
handlers:   # named AUXILIARY handler instances (loaders + save targets)
seed:       # how data enters the DAG: the seed handler + its role mapping
stages:     # the DAG: stage instances, wiring, settings, designated saves
```

All six are required (`iteration` may be omitted only when there is a single
dimension; `handlers` may be empty when nothing is saved and no stage has a
`loader:` dependency). No other top-level keys are accepted.

## 2. `run:`

```yaml
run:
  name: smooth_january          # human label, letters/digits/_/-
  mode: retrograde              # retrograde | realtime
  # poll_frequency: 300         # seconds; REQUIRED iff mode == realtime,
                                # FORBIDDEN otherwise
```

- **retrograde** — compute the work delta once and drain it, then exit.
- **realtime** — drain the delta, sleep `poll_frequency` seconds, recompute,
  forever until stopped. Polling never overlaps a run in progress. A clean stop
  (Ctrl-C / SIGTERM between work items) finishes the current work item, flushes
  the log, and exits 0.

The **delta** is `exists − attempted`: what the seed handler's `catalog`
reports minus every work item already in the operational log — *success or
failure*. Nothing already tried is re-run automatically; `spout run
--retry-failed` is the explicit escape hatch that re-queues failed work items
(for transient causes — an outage, a since-fixed input).

`--select dim=value` (§3) composes with the delta, it does not override it:
selection first narrows the dimension space, then the log is subtracted as
usual — an already-attempted selected cell is **still skipped**. To re-run a
specific failed cell, combine them: `--select day=2026-01-03 --retry-failed`
re-queues exactly the selected failures. `--retry-failed` never touches
succeeded cells. Deliberately re-running **succeeded** cells — overwriting
good output — is its own flag, bluntly named so it can't happen by accident:
`spout run --force-rewrite`, combined with `--select` to target the subset
you mean to redo.

## 3. `dimensions:`

Each entry names an axis and gives its values, either explicitly or as a range
expanded by the driver (handlers only ever see explicit values):

```yaml
dimensions:
  day: {start: 2026-01-01, stop: 2026-01-07, step: 1d}   # inclusive range
  sensor: [alpha, bravo, charlie]                        # explicit list
```

- List form: any scalars, order preserved, duplicates rejected.
- Range form: `start`/`stop` inclusive + `step`. Numeric (`step: 5`) or
  date/datetime (`step: 1d`, `1h`, `30m`, `15s`).
- A **work item** is one point in the cross-product of all dimensions; the
  whole DAG runs once per work item, at that single granularity. There is no
  mid-DAG aggregation across a dimension — a fan-in (e.g. daily → monthly) is a
  **separate run with a different config**, reading what this run saved.
- Dimension names are yours to choose — they are *your* bookkeeping, kept
  consistent across this one file. Handlers see them only through the role
  mappings (§§5–6), and stages see them only as coordinate keys at runtime;
  the skeleton never enforces name agreement beyond the seed rule (§6).
- `spout run --select day=2026-01-03 --select sensor=alpha` narrows a dimension
  to a subset for one invocation without editing the config; it composes with
  the delta and `--retry-failed` as spelled out in §2.

## 4. `iteration:`

```yaml
iteration:
  order: [day, sensor]     # outer → inner; must list every dimension exactly once
```

Work items are processed **sequentially** (v1 has no parallelism), in
lexicographic order of the listed axes.

## 5. `handlers:` — named auxiliary instances

Each entry creates a named **auxiliary** handler instance — the targets of
stages' `loader:` dependencies and of `save:` blocks. (The handler that feeds
the DAG is not defined here; that is the `seed:` block, §6.) An entry gives the
registry handler, its resources, and how *your* dimension names map onto the
handler's declared **roles**:

```yaml
handlers:
  events_in:
    handler: events_local_json         # registry key (declared by its package)
    resources:
      base_dir: /data/events           # validated against the handler's model
    dimensions:                        # role (handler's) : dimension (yours)
      event_day: day

  smoothed_out:
    handler: readings_local_h5
    resources: {base_dir: /data/smoothed}
    dimensions: {day: day, sensor: sensor}
```

Validated at startup, naming instance + field: unknown registry key;
resources missing/extra/out-of-domain; a `dimensions:` mapping naming a
dimension that doesn't exist in this file (a typo in *your own* vocabulary).

That last check is purely **config-internal** — a dangling reference, the same
class of error as a `from:` naming a nonexistent stage. It never requires a
config dimension name to equal any name inside a handler: your names are for
human bookkeeping and correspond to the dimensions of the actual data; they
meet handler-internal role names only through explicit mappings, and the
mapping itself is judged only at the seed edge (§6).

**Not validated at startup**: whether the role mapping is complete for the
handler, whether values coerce to its declared types, or whether what it loads
suits the consuming stage. An auxiliary handler runs along its own dimensions —
which may legitimately be a subset of the iterated ones, or carry data richer
than any one stage uses — so the skeleton does not judge the fit in advance.
When a stage calls `.load()`, the work item's coordinate is bound through the
mapping; a genuinely unbindable role, uncoercible value, or missing cell fails
**that work item only**, logged, at runtime.

The same instance may be referenced by any number of `loader:` dependencies and
`save:` blocks.

## 6. `seed:` — how data enters the DAG

The seed block defines the handler the driver itself coordinates with, as a
**named entry**: for each work item, the driver loads the seed cell, stamps
the work item's coordinate onto the resulting reference (read-only;
STAGE_AUTHORING §7), and offers it to stages under the name you gave the
entry:

```yaml
seed:
  raw:                                     # your name for it — wired `from: raw`
    handler: readings_local_csv            # registry key
    resources: {base_dir: /data/raw}
    dimensions: {day: day, sensor: sensor} # role (handler's) : dimension (yours)
```

There is no boilerplate "loader stage" — the first stage simply wires a
`LazyReference` dependency `from: raw` (§7). Seed names share the upstream
namespace with stage instance names: no stage may reuse one.

The block is **plural by design, singular by rule**: exactly one seed entry is
allowed in v1 — a second fails loudly at validate as "multiple seeds not
supported in v1" — but because entries are named, adding more later (branching
DAGs fed by several sources) is a non-breaking addition, not a schema
migration.

Unlike auxiliary instances, the seed is **rigorously validated at startup**:
its mapped roles must correspond *exactly* to the iterated dimension set —
every declared role mapped, every mapping to a real dimension, no iterated
dimension unmapped, all values coercible to the handler's declared types — any
miss fails loudly before data moves. At `spout run` the seed additionally gets
the **pre-flight probe** (one coordinate, cheap structural sanity — see
HANDLER_AUTHORING §8) before any work item executes. The seed's `catalog` is
what drives the delta (§2).

Combining data at another granularity is a separate run with a different
config, reading what this one saved (§3).

## 7. `stages:` — the DAG

Each entry creates a stage instance. Its key is the **instance name** used by
`from:` references (so one stage class may appear twice under different names
and settings):

```yaml
stages:
  smooth:
    stage: smooth_readings
    dependencies:
      data: {from: raw}                # the seed entry's cell for this work item
    settings:
      window_len: 5
      method: mean

  detect:
    stage: detect_events
    dependencies:
      data: {from: smooth}             # stage-wired: upstream output
      events: {loader: events_in}      # handler-wired: auxiliary input
    settings: {threshold: 3.5}
    save: {handler: smoothed_out}      # config-designated save (§8)
```

Rules, all enforced at startup with named offenders:

- Every dependency field declared by the stage must be wired, with the matching
  wiring kind: `from:` for `LazyReference` fields, `loader:` for
  `BoundHandler` fields. Missing, extra, or misspelled dependencies fail.
- Every `from:` must name an existing stage instance in this file — or a seed
  entry (§6). The graph must be acyclic.
- `settings:` is validated by the stage's own model — unknown keys, missing
  keys, and out-of-range values fail, naming stage instance and field.
- There is no ordering to declare beyond the wiring: execution order is derived
  from the DAG.
- v1 supports **linear chains** — each stage consuming one upstream via
  `from:` (plus any number of `loader:` auxiliaries). Branching and fan-in are
  not v1 features; aggregation across a dimension is a separate run (§3). The
  wiring syntax is general on purpose, so this is a current limit, not a
  schema you'll have to migrate off.

## 8. `save:` — config-designated persistence

Any stage instance — **anywhere** in the DAG, not just the ends — may carry a
`save:` block naming a handler instance. After that stage succeeds for a work
item, the skeleton persists its output through that handler, with the
provenance chain embedded in the metadata block. A save is the output-symmetric
mirror of a `loader:` dependency: one wires data in, the other wires data out.

Only stages with `save:` persist anything. Every other output stays lazy /
in-memory and is discarded when the work item finishes. Deciding what to save
is a **config** decision, never a stage's.

## 9. What a config never contains

- Science parameters disguised as pipeline structure — tunables belong in the
  owning stage's `settings:`.
- Paths or credentials outside `handlers.<name>.resources` /
  `seed.<name>.resources`.
- Dimension *structure* inside `stages:` — only `dimensions:`, `iteration:`,
  `seed:`, and handler role mappings declare the axes. (Stages *read* their
  work-item coordinate at runtime — keyed by the names you chose here — but a
  stage that needs a specific axis should take its name as a setting rather
  than assume yours; see STAGE_AUTHORING §7.)
- Parallelism, scheduling, or orchestration of any kind — run `spout` from
  cron/sbatch/Docker if you need those.

## 10. Checking your work

```
spout validate --config run.yml     # definition-only, instant, touches no data
spout run --config run.yml --dry-run
```

`--dry-run` goes further than `validate`: it performs discovery and planning —
enumerates work items, catalogs availability, subtracts the log, reports the
plan (what would run, what is already done, what previously failed) — and stops
without executing any stage.

## 11. Self-check

- [ ] Exactly the six top-level keys; nothing extra.
- [ ] `poll_frequency` present iff `mode: realtime`.
- [ ] Every dimension listed in `iteration.order` once, and mapped by the
      seed — exactly and completely (the seed's roles ↔ your iterated
      dimensions).
- [ ] Every handler instance: known registry key, complete bounded resources;
      auxiliary role mappings name real dimensions (the fit itself is proven
      at runtime).
- [ ] Every stage dependency wired with the right kind (`from:` / `loader:`);
      first stage wired `from:` the seed entry's name; no cycles; linear
      chain and exactly one seed entry in v1.
- [ ] Every tunable lives in some stage's `settings:`, in that stage's declared
      domain.
- [ ] Outputs you need later have a `save:`; nothing else does.
- [ ] `spout validate` passes; `--dry-run` reports the plan you expect.
