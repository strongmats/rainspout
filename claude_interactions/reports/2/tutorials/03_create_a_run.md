# Tutorial 3 — Create a run (write a config)

*This tutorial doubles as an acceptance test: every step is runnable, and each
step's expected behavior is stated.*

We'll wire Tutorials 1–2 into a pipeline: seed CSV readings into the DAG →
smooth them → save as CSV elsewhere — for three days × two sensors. There is
no loader stage to write: data enters through a named entry in the config's
`seed:` block (CONFIG_AUTHORING §6), and the driver hands each work item's
cell to the first stage under that entry's name.

## Step 1 — Lay out some raw data

```
/data/raw/2026-01-01/s1.csv     (and s2.csv, and the same for 01-02, 01-03)
```

each file shaped like the example data from Tutorial 1. Corrupt one cell on
purpose — overwrite `/data/raw/2026-01-03/s2.csv` with a few lines of garbage
text — to watch failure isolation work later. (Corrupt, don't delete: a
missing cell is simply never cataloged, so it never becomes a work item; a
*corrupt* cell catalogs fine and fails at load, which is the interesting
case.)

## Step 2 — Write `smooth_run.yml`

```yaml
run:
  name: smooth_demo
  mode: retrograde

dimensions:
  day: {start: 2026-01-01, stop: 2026-01-03, step: 1d}
  sensor: [s1, s2]

iteration:
  order: [day, sensor]

seed:
  raw:                                         # this run's one seed entry —
    handler: readings_local_csv                #   wired below as `from: raw`
    resources: {base_dir: /data/raw}
    dimensions: {day: day, sensor: sensor}     # role: your-dimension — must
                                               # match the iterated set EXACTLY

handlers:
  smoothed_out:
    handler: readings_local_csv
    resources: {base_dir: /data/smoothed}
    dimensions: {day: day, sensor: sensor}

stages:
  smooth:
    stage: smooth_readings
    dependencies:
      data: {from: raw}           # the seed cell, coordinate already stamped
    settings: {window_len: 3, method: mean}
    save: {handler: smoothed_out}
```

Six work items (3 days × 2 sensors); per work item the driver loads the seed
cell and the one-stage DAG runs; only `smooth`'s output is persisted, because
only it has `save:`.

## Step 3 — Validate (instant, touches no data)

```
$ spout validate --config smooth_run.yml
config ✓  registry ✓  DAG ✓  settings ✓
```

Now break it on purpose and watch the named offenders:

| Edit | Expected failure names |
|---|---|
| `method: meen` | stage instance `smooth`, field `method`, allowed options |
| `from: rew` | stage instance `smooth`, unknown upstream `rew` (no such stage or seed entry) |
| delete the `data:` line under `smooth` | stage `smooth`, missing dependency `data` |
| `poll_frequency: 60` while `mode: retrograde` | `run.poll_frequency` forbidden for retrograde |
| point seed entry `raw` at a bogus handler name | seed `raw`, unknown handler |
| delete `sensor: sensor` from `seed.raw.dimensions` | seed `raw`, role `sensor` unmapped — the seed must map the iterated dimensions exactly |
| add a second entry under `seed:` | multiple seeds not supported in v1 |

Undo the breakage.

## Step 4 — Dry-run (plans, executes nothing)

```
$ spout run --config smooth_run.yml --dry-run
pre-flight: seed raw ✓ (readings_local_csv, probe 2026-01-01/s1)
plan: 6 work items — 6 to run, 0 done, 0 previously failed
```

(The corrupt cell still counts: it exists and is non-empty, so `catalog`
reports it — `catalog` promises only its cheapest existence test, not
deep validation.)

## Step 5 — Run

```
$ spout run --config smooth_run.yml
[2026-01-01|s1] raw ✓  smooth ✓  saved → smoothed_out
...
[2026-01-03|s2] raw ✗  FAILED (readings_local_csv: could not parse 2026-01-03/s2) — continuing
done: 5 succeeded, 1 failed
```

The corrupt cell killed exactly one work item; the other five completed. Check
an output cell: open `/data/smoothed/2026-01-01/s1.csv` and its first line is
the embedded `# rainspout-meta:` block carrying the provenance chain —
`smooth_readings` with version, settings, timestamp, and code hash — followed
by plain CSV.

## Step 6 — Resume semantics

Run it again, unchanged:

```
$ spout run --config smooth_run.yml
plan: 6 work items — 0 to run, 5 done, 1 previously failed
```

Nothing re-runs: the delta is *exists − attempted*, and the failure was
attempted. Now fix `/data/raw/2026-01-03/s2.csv` (restore real CSV content)
and re-queue failures explicitly:

```
$ spout run --config smooth_run.yml --retry-failed
[2026-01-03|s2] raw ✓  smooth ✓  saved → smoothed_out
done: 1 succeeded
```

(`--retry-failed` composes with `--select` too: `--select day=2026-01-03
--retry-failed` re-queues only the selected failures — and it never touches
succeeded cells. Deliberately redoing a *succeeded* cell, overwriting its
output, takes the bluntly named `--force-rewrite`, usually with `--select`
to target exactly the cells you mean.)

## Step 7 — Real-time mode (optional)

```yaml
run:
  name: smooth_live
  mode: realtime
  poll_frequency: 60
```

`spout run` now drains the delta, then re-catalogs every 60 s and processes
whatever is new — drop a fresh CSV into `/data/raw/...` and watch it get picked
up on the next poll. Ctrl-C between work items stops cleanly; already-processed
cells are never re-done.

## Step 8 — Where to go next

- Narrow a run without editing config: `spout run --config smooth_run.yml
  --select day=2026-01-02`.
- Aggregating across a dimension (say, all sensors per day)? That is a
  **separate config** at daily granularity reading `/data/smoothed` — one DAG
  runs at one granularity, always.
