# Rainspout documentation

Welcome. This folder is the complete, authoritative documentation for
**Rainspout** — everything you need to build on it, with no access to its
source code required.

## What Rainspout is, in plain words

Rainspout is a frame for building scientific data-processing pipelines. It
contains **no science of its own**. Instead, it answers three questions and
keeps them strictly apart:

1. **What computation runs?** — *Stages.* Each stage is one processing step
   (smooth this, clean that), written by you.
2. **Where does data live, and how is it read and written?** — *Handlers.*
   Each handler knows one specific way data is stored (this file format, this
   folder layout, this server) and hides all of it behind three actions:
   load, save, and catalog ("tell me what exists").
3. **Over what does the pipeline sweep?** — *Dimensions.* A run config names
   the axes of the work (days, sensors, whatever your data varies over).
   Rainspout runs your chain of stages once per point on that grid — each
   point is called a **work item** — and keeps track of what's already done,
   so re-running a pipeline only processes what's new.

You write stages and handlers in your own installable Python package (a
"content package"), describe a run in one YAML file, and start it with the
`spout` command. Rainspout checks the whole setup *before* touching any data:
if something is wrong — a typo, a missing connection, an out-of-range
setting — it stops immediately and names the exact offender.

Two promises shape everything here:

- **You can build on Rainspout from these documents alone.** If you follow an
  authoring guide and your component doesn't work, that's a bug in the guide.
  Report it.
- **Mistakes fail loudly and early.** Configuration problems kill a run at
  startup with a specific message. Data problems (one corrupt file among
  thousands) fail only the affected work item, are logged, and the run moves
  on.

## Where to start

| You want to… | Read |
|---|---|
| Teach Rainspout to read/write a data format or source | [HANDLER_AUTHORING.md](HANDLER_AUTHORING.md), then [Tutorial 1](tutorials/01_add_a_handler.md) |
| Add a processing step | [STAGE_AUTHORING.md](STAGE_AUTHORING.md), then [Tutorial 2](tutorials/02_add_a_stage.md) |
| Describe and launch a run | [CONFIG_AUTHORING.md](CONFIG_AUTHORING.md), then [Tutorial 3](tutorials/03_create_a_run.md) |
| Set up or organize your package | [PACKAGE_AUTHORING.md](PACKAGE_AUTHORING.md) |

If you're brand new, the fastest honest path is the three tutorials in order —
they build one tiny working pipeline from nothing, and every step states what
you should see when it works.

## How code is shown in these documents

The authoring guides show code in two distinct ways, and every block tells
you which it is:

- **Templates** show the *required shape* with placeholder names. Inside a
  template, each line's comment marks it either **contract:** (the framework
  requires this exact name or form — change it and things fail loudly) or
  **yours:** (you choose the name, the type, the body). A template is
  followed by a line-by-line walkthrough.
- **Worked examples** fill a template in for one concrete, made-up domain —
  daily CSV files of sensor readings. Everything domain-flavored in them —
  dates, sensors, file formats, folder layouts — is the *example's* choice,
  never the framework's. Rainspout itself has no idea what a "day" is.

Two import rules make the boundary easy to see in any snippet:

- The **only** imports that come from Rainspout are `rainspout.contracts`
  (for writing components) and `rainspout.testing` (for testing them).
  Anything else — `datetime`, `csv`, `pathlib`, a client library — belongs to
  the example's domain; in your own code you swap those for whatever *your*
  data needs.
- You will also import from **`pydantic`** (`Field`, `Literal`, path types):
  that's the validation library the contracts build on. *That* you declare
  bounds with it is the contract; *which* bounds is always yours.

## The mental model in one run-through

A run config (one YAML file) declares dimensions — say, 3 days × 2 sensors —
which makes six work items. A **seed** entry in the config names the handler
that brings data *into* the pipeline; for each work item, the driver asks the
seed handler for that cell of data, tags it with its coordinate (which day,
which sensor), and hands it to your first stage. Stages pass results down the
chain; any stage the config marks with `save:` has its output written out
through another handler. A log records every attempt, so running the same
config again does nothing until new data appears — or you explicitly ask to
retry failures. Every saved file carries a record of every stage that touched
it, with versions and settings, so you can always answer "where did this
number come from?"

## Glossary

- **Stage** — one processing step, written by you. Thin wrapper class + plain
  Python functions holding the science.
- **Handler** — the one piece of code that knows how a particular kind of
  data is stored. Verbs: `load`, `save`, `catalog`.
- **Dimension** — a named axis the run sweeps over (`day`, `sensor`…). You
  choose the names in your config.
- **Work item** — one point on the dimension grid (e.g. `2026-01-03` ×
  `s2`). The whole stage chain runs once per work item.
- **Cell** — one work item's worth of stored data, as a handler sees it.
- **Coordinate** — the position of a work item on the grid, e.g.
  `{day: 2026-01-03, sensor: s2}`. Stages can read theirs; only Rainspout
  sets it.
- **Seed** — the named config entry that says how data enters the pipeline:
  which handler feeds the first stage.
- **Role** — a handler's own name for an axis it needs (declared in code,
  before any config exists). Your config maps *your* dimension names onto the
  handler's roles.
- **Resources** — everything a handler needs to reach its data (base folder,
  server address, key). Declared and validated up front.
- **Settings** — a stage's tunable numbers and choices. Every one has a
  declared valid range; out-of-range fails at startup.
- **Dependency** — a stage's declared, named data input. The only door data
  can enter a stage through.
- **Lazy reference** — the handle a stage receives instead of raw data;
  nothing is actually loaded until the stage asks (`.get()`).
- **Delta** — the to-do list: work items whose data exists but that were
  never attempted. Re-runs process only the delta.
- **Operational log** — Rainspout's private record of every attempt
  (succeeded/failed, per stage, per work item). What makes resume work.
- **Status file** — the live state a running `spout run` publishes next to
  its log; `spout status --config <run.yml>` reads it from another terminal
  (current work item, stage status line, progress percentage).
- **Provenance chain** — the history that travels *with the data*: every
  stage that touched it, with version, settings, and timestamp. What makes
  results traceable.
- **Metadata block** — the standard little bundle (coordinates, run id,
  provenance chain) a handler stores inside each saved file.
- **Retrograde / realtime** — the two run modes: process everything that's
  waiting, then stop — or keep watching for new data on a timer.
- **Content package** — your installable Python package of stages, handlers,
  and configs. Installing it is all Rainspout needs to find them.
- **Skeleton / core** — Rainspout itself: the machinery with no science in
  it.

## One rule to remember

Each document ends with a self-check list. The lists are short on purpose:
if your component passes its list, it conforms — there are no unwritten
rules hiding in the source.
