# CONFIG_AUTHORING.md — The Rainspout run configuration (`.yml`)

A run is described by **one YAML file**. The whole file is parsed into a
validated model at load: unknown keys, missing keys, and out-of-domain values
fail immediately with a message naming the offending key — before any data
moves. `spout validate --config run.yml` performs exactly the checks `spout
run` would perform (config parse → registry resolution → seed dimension rule →
DAG validation → per-stage settings validation; the seed's pre-flight probe is
run-only); there is no skip-validation path.

## The short version

One YAML file describes one run: **which axes** the work sweeps over
(`dimensions:`), **in what order** (`iteration:`), **where data comes in**
(`seed:`), **which storage connections** are available (`handlers:`), and
**which processing steps run, with what settings, saving what**
(`stages:`) — plus a name and mode under `run:`. Rainspout checks the entire
file before touching any data, and every mistake it finds is reported with
the exact key at fault. `spout validate` runs those same checks on demand;
`spout run --dry-run` additionally shows the work plan without executing
anything. New here? [Tutorial 3](tutorials/03_create_a_run.md) writes one of
these files from scratch.

## 1. Top-level shape — six keys

```yaml
run:        # identity + iteration mode
dimensions: # the named axes of the work
iteration:  # order over those axes
handlers:   # named handler instances (stage-callable inputs + save targets)
seed:       # how data enters the DAG: the seed handler + its role mapping
stages:     # the DAG: stage instances, wiring, settings, designated saves
```

All six are required (`iteration` may be omitted only when there is a single
dimension; `handlers` may be empty when nothing is saved and no stage has a
`handler:`-wired dependency). No other top-level keys are accepted.

A note on YAML forms before the examples: `resources: {base_dir: /data/raw}`
and

```yaml
resources:
  base_dir: /data/raw
```

are the **same** YAML — braces are just the inline spelling of a nested
block. These docs write examples in block form so the structure stays
visible; when an inline one-liner of yours grows a second key, expand it the
same way.

And the framework/example split (docs README, "How code is shown") reads
naturally in YAML: the **key names** — the six top-level keys and the fixed
keys inside each block (`handler:`, `resources:`, `dimensions:`, `stage:`,
`from:`, `save:`, …) — are the contract. Every **name and value** — `day`,
`sensor`, `smooth_demo`, `readings_local_csv`, every path and number — is
the example's, standing in for yours.

## 2. `run:`

```yaml
run:
  name: smooth_january          # human label, letters/digits/_/-
  mode: retrograde              # retrograde | realtime
  # poll_frequency: 300         # seconds; REQUIRED iff mode == realtime,
                                # FORBIDDEN otherwise
  # oplog: logs/history.jsonl   # optional; see below
```

**Where the run's history lives.** Rainspout records every attempt in an
operational log, and re-running a config only processes what that log doesn't
already cover. The log **follows the run definition**: by default it is
`.rainspout/<name>.oplog.jsonl` next to this config file — never derived from
the directory you happen to run `spout` from, so a resumed run always finds
the history it must subtract. To put it elsewhere, set `oplog:` (a relative
path resolves against this config file's directory). Renaming `run.name`
starts a fresh history by design.

A sibling lives next to the log, keyed to the same run identity (config
location + `run.name`): a **lock file** that admits **one active run per
run definition** — a second `spout run` on the same config fails at startup
naming the process already holding it (two concurrent runs would drain the
same delta twice). Run the same pipeline concurrently by giving each run
its own `run.name` (which is its own history) — never by racing one name.
(Live progress needs no file at all: `spout run` redraws a one-line status
in its own terminal; see `--live/--no-live`.)

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
  day:                        # inclusive range, expanded by the driver
    start: 2026-01-01
    stop: 2026-01-07
    step: 1d
  sensor: [alpha, bravo, charlie]   # explicit list
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

## 5. `handlers:` — named handler instances

Each entry creates a named handler instance for the two places a stage chain
touches storage besides the seed: **stage-callable inputs** (a stage's
`handler:`-wired dependency) and **save targets** (`save:` blocks). An entry
gives the registry handler and its resources; a `dimensions:` role map is
needed **only when the instance is a save target**:

```yaml
handlers:
  events_in:                     # stage-callable input: NO dimensions map —
    handler: events_local_json   #   the consuming stage computes whatever
    resources:                   #   coordinates it asks this handler for
      base_dir: /data/events

  smoothed_out:
    handler: readings_local_h5
    resources:
      base_dir: /data/smoothed
    dimensions:                  # save target: the DRIVER writes each work
      day: day                   #   item's output here, so it must know
      sensor: sensor             #   role (handler's) : dimension (yours)
```

Validated at startup, naming instance + field: unknown registry key;
resources missing/extra/out-of-domain; a `dimensions:` map (wherever one
appears) naming a dimension that doesn't exist in this file; and, for any
instance referenced by a `save:`, a complete role map onto the iterated
dimensions — the driver saves at work-item granularity, so a save target's
mapping is held to the same standard as the seed's.

Resource *values* are the handler's to interpret — the skeleton only checks
them against the handler's declared resource fields. In particular, a
handler that treats a resource as a filesystem path will resolve a relative
one against wherever you run `spout` (unlike `run.oplog:`, which the skeleton
itself resolves against the config file). Use absolute paths in configs you
run from more than one place.

The dimension-name check is purely **config-internal** — a dangling
reference, the same class of error as a `from:` naming a nonexistent stage.
It never requires a config dimension name to equal any name inside a handler:
your names are for human bookkeeping and correspond to the dimensions of the
actual data; they meet handler-internal role names only through explicit
mappings (the seed's and a save target's).

**For stage-callable instances, the skeleton's whole guarantee is
presence-and-wiring**: the instance exists, its resources validate, and it
reaches the stage that declared it — exactly parallel to what validation
guarantees for settings. Everything about how the stage *uses* it is private
to the stage and trust-based (STAGE_AUTHORING §5): the stage computes the
coordinates it asks for, and those may be entirely unrelated to the run's
dimensions. A genuine mismatch — a wrong role, an uncoercible value, a
missing cell — fails **that work item only**, logged, at runtime.

The same instance may be referenced by any number of `handler:` dependencies
and `save:` blocks.

## 6. `seed:` — how data enters the DAG

The seed block defines the handler the driver itself coordinates with, as a
**named entry**: for each work item, the driver loads the seed cell, stamps
the work item's coordinate onto the resulting reference (read-only;
STAGE_AUTHORING §7), and offers it to stages under the name you gave the
entry:

```yaml
seed:
  raw:                             # your name for it — wired `from: raw`
    handler: readings_local_csv    # registry key
    resources:
      base_dir: /data/raw
    dimensions:                    # role (handler's) : dimension (yours)
      day: day
      sensor: sensor
```

There is no boilerplate "load the data" stage to write — the first stage
simply wires a `LazyReference` dependency `from: raw` (§7). Seed names share
the upstream namespace with stage instance names: no stage may reuse one.

The block is **plural by design, singular by rule**: exactly one seed entry is
allowed in v1 — a second fails loudly at validate as "multiple seeds not
supported in v1" — but because entries are named, adding more later (branching
DAGs fed by several sources) is a non-breaking addition, not a schema
migration.

Unlike stage-callable instances, the seed is **rigorously validated at
startup**:
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
      data:
        from: raw                # the seed entry's cell for this work item
    settings:
      window_len: 5
      method: mean

  detect:
    stage: detect_events
    dependencies:
      data:
        from: smooth             # stage-wired: upstream output
      events:
        handler: events_in       # handler-wired: an instance the stage calls
    settings:
      threshold: 3.5
    save:
      handler: smoothed_out      # config-designated save (§8)
```

Rules, all enforced at startup with named offenders:

- Every dependency field declared by the stage must be wired, with the matching
  wiring kind: `from:` for `LazyReference` fields, `handler:` for `Handler`
  fields. Missing, extra, or misspelled dependencies fail. (Note the
  symmetry: a handler-wired dependency and a `save:` block use the same
  `handler:` key — both simply name an instance from `handlers:`; direction
  is already told by `dependencies:` vs `save:`.)
- A dependency the stage declares **optional** (annotated `Handler | None` /
  `LazyReference | None` — see STAGE_AUTHORING §5) may be omitted: the stage
  reads it only under some settings and is handed `None` otherwise. If you do
  wire it, the wiring kind is checked as usual. The stage's docs tell you which
  settings need it; a stage that needs one and hasn't got it fails at startup
  or on the work item, naming the setting.
- Every `from:` must name an existing stage instance in this file — or a seed
  entry (§6). The graph must be acyclic.
- `settings:` is validated by the stage's own model — unknown keys, missing
  keys, and out-of-range values fail, naming stage instance and field.
- There is no ordering to declare beyond the wiring: execution order is derived
  from the DAG.
- v1 supports **linear chains** — each stage consuming one upstream via
  `from:` (plus any number of `handler:`-wired inputs). Branching and fan-in
  are not v1 features; aggregation across a dimension is a separate run (§3).
  The wiring syntax is general on purpose, so this is a current limit, not a
  schema you'll have to migrate off.

## 8. `save:` — config-designated persistence

Any stage instance — **anywhere** in the DAG, not just the ends — may carry a
`save:` block naming a handler instance. After that stage succeeds for a work
item, the skeleton persists its output through that handler, with the
provenance chain embedded in the metadata block. A save is the
output-symmetric mirror of the seed: the seed brings each work item's cell
in, a save writes a stage's output out at the same coordinate — both operated
by the driver, which is why both need a role map (§5, §6).

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
      every save target carries a complete role map onto iterated dimensions;
      any `dimensions:` map names only real dimensions (how a stage *uses* a
      stage-callable instance is proven at runtime, not here).
- [ ] Every stage dependency wired with the right kind (`from:` / `handler:`);
      first stage wired `from:` the seed entry's name; no cycles; linear
      chain and exactly one seed entry in v1.
- [ ] Every tunable lives in some stage's `settings:`, in that stage's declared
      domain.
- [ ] Outputs you need later have a `save:`; nothing else does.
- [ ] `spout validate` passes; `--dry-run` reports the plan you expect.
