# STAGE_AUTHORING.md — How to write a conforming Rainspout stage

This document is the complete contract for authoring a stage. You do not need
access to the Rainspout source — only an environment with `rainspout`
installed. If you can't build a working stage from this document alone, that is
a bug in this document; report it.

---

## 1. What a stage is

A **stage** is one processing step in a pipeline DAG. (Always "stage" — the
word "module" is reserved for a `.py` file.) The stage *class* is a **thin
orchestrator**: declarations plus a short `run` that calls module-level
functions where the actual science lives. If your `run` is more than roughly a
screen, you are writing science in the orchestrator — move it into functions.
The class stays auditable at a glance; the science stays testable without the
skeleton.

A stage runs once per **work item** (one point in the run's dimension space)
and is **coordinate-aware**: it can read *where it is* — the work item's
coordinate, stamped read-only on its references (§7) — because real science is
often position-dependent (snipping a record requires its start time). What
stays agnostic is the **skeleton**: no dimension name is hardcoded anywhere in
Rainspout; names come from the run config. A stage receives data only through
its declared dependencies, produces one output object, and has **no side
effects**: no writing files (saving is config-designated and done by the
skeleton through handlers), no fetching beyond declared dependencies, no
calling other stages, no globals.

## 2. The skeleton of a stage

```python
from typing import Literal
from pydantic import Field

from rainspout.contracts import (
    Stage, StageSettings, StageDependencies, LazyReference,
)


class SmoothReadingsSettings(StageSettings):
    """Static config. Every field bounded (§4)."""
    window_len: int = Field(ge=1, le=10_000)
    method: Literal["mean", "median"] = "mean"


class SmoothReadingsDependencies(StageDependencies):
    """Named data inputs. Wired in config via `from:` or `loader:` (§5)."""
    data: LazyReference


class SmoothReadings(Stage):
    name = "smooth_readings"          # registry key
    version = "1.0.0"                 # bump on ANY code edit (§9)
    settings_model = SmoothReadingsSettings
    dependencies_model = SmoothReadingsDependencies

    def run(self, deps: SmoothReadingsDependencies) -> object:
        raw = deps.data.get()
        self.set_status(f"smoothing {len(raw)} rows ({self.settings.method})")
        return smooth(raw, self.settings.window_len, self.settings.method)


def smooth(raw, window_len, method):
    """Module-level science — testable with no skeleton in sight."""
    ...
```

Rules that apply to the class itself:

- **Registration is automatic** via `__init_subclass__` on a `name` attribute —
  the same gesture as handlers. Missing/duplicate names fail at import time.
- **Do not define `__init__`.** The base `__init__` validates settings against
  `settings_model` and cannot be bypassed; a subclass defining `__init__` fails
  at class-definition time. Post-validation initialization goes in `setup()`
  (§6). Avoid mixins that define `__init__` — they are rejected too.
- After construction, validated settings are available as `self.settings`
  (frozen). Construction happens at **validation time**, before any data moves —
  so anything your constructor-era logic needs must come from settings alone.

## 3. The three kinds of input — strictly separated

| Kind | Declared in | Validated | Contains |
|---|---|---|---|
| **Settings** | `settings_model` | deeply, at startup | static config: thresholds, window lengths, method choices |
| **Dependencies** | `dependencies_model` | against config wiring, at startup | named data inputs |
| **Resources** | *(not yours)* | by the handler | a handler's fetch config — never a stage's concern |

Never smuggle one into another: no file paths in settings (that's a handler
resource), no tunable numbers arriving via dependency data, no reaching around
dependencies to fetch anything.

## 4. Settings — bounded, validated, forbidden to be loose

`settings_model` extends `StageSettings` (Pydantic v2, `extra="forbid"`
inherited — typos in config fail loudly, naming the field). **Every field must
declare a bounded valid domain**: numeric ranges via `Field(ge=…, le=…)`,
discrete choices via `Literal`/`Enum`, strings constrained by pattern or
length. An unbounded field is permitted only as a deliberate, justified
exception (comment on the field) and draws a lint-style warning from the
conformance check. An out-of-range value in config fails at startup like any
other bad setting, naming stage and field.

## 5. Dependencies — the only door for data

`dependencies_model` extends `StageDependencies`. Each field is a named input,
and its **type annotation declares what kind of wiring it accepts**:

- `LazyReference` — wired in config with `from: <upstream_stage>`. You receive
  a reference to the upstream stage's output (§7).
- `BoundHandler` — wired in config with `loader: <handler_instance>`. You
  receive a handler already bound by the skeleton; call `.load()` with **no
  arguments** to get `(data, meta)`. That is the whole interface:
  call-and-receive. A stage never steers a handler across coordinates — no
  passing coords, no deriving neighbors, no windows through a `loader:`. The
  loaded data may be a richer structure than you need (a whole events file, a
  full calibration table); using one piece of it is normal and legitimate.

The wiring is checked at startup: config wiring a `from:` into a
`BoundHandler` field (or vice versa), a missing dependency, an extra one, or a
misspelled name all fail loudly, naming stage and field.

**How data enters the DAG:** the run config's `seed:` block (CONFIG_AUTHORING
§6) defines a named seed entry — the handler that feeds the pipeline; the
driver loads the seed cell for each work item, stamps the coordinate on the
resulting reference, and offers it to stages under the entry's name. The
first stage simply declares a `LazyReference` dependency and the config wires
it `from: <seed_name>` — no package ever writes a pass-through "load the
data" stage. A **mid-DAG stage** needing an additional
input (a calibration table, an events file, a trained-model artifact) declares
an extra `BoundHandler` dependency wired `loader:` to an auxiliary handler
instance. Same shape, same rules, anywhere in the DAG.

**Auxiliary inputs prove out at runtime.** An auxiliary (`loader:`) handler is
*not* dimension-validated at startup the way the seed is; whether what it loads
serves your science is settled when you use it. Check cheaply, and raise if a
genuine mismatch appears — an isolated per-work-item failure, logged (§8).

Artifacts produced by package lifecycle commands (a trained model, a simulation
grid) are just versioned inputs loaded this way — there is no separate
mechanism.

## 6. The setup hook

If your stage needs one-time initialization beyond validation — loading a
library, warming a lookup table, preparing anything expensive — implement
`setup(self)`. It runs **once, after validation, before any work item**, and is
also invoked by `spout setup` across all stages. `setup` must be idempotent
(safe to run twice) and must not touch pipeline data — it prepares the stage,
not the run. Anything `setup` produces for `run` to use goes on `self`.

## 7. Consuming data: lazy references

Dependencies wired `from:` an upstream stage arrive as a `LazyReference` — a
handle, not data. Nothing is materialized until you pull:

- `ref.get()` — materialize the whole object. Universal: works for any type.
- `ref.coords` — the current work item's **coordinate**: a read-only mapping
  of dimension name → value (e.g. `{"time": datetime(...), "receiver": "alpha"}`).
  The driver stamps it on the reference when the work item is seeded, and it
  flows downstream automatically as references pass from stage to stage.
- `ref.can_window` — `True` if this reference advertises windowed access
  (only for windowable types).
- `ref.window(**spec)` — materialize a slice, only if `can_window`; asking
  otherwise raises immediately.

**The coordinate is yours to read, never to write.** Position-dependent
science — a file's start time, which receiver produced it — reads
`ref.coords` freely. But the mapping is immutable and driver-set: stages do
not forge, alter, or re-stamp it, which is what keeps it trustworthy for
provenance. Its **keys are the config author's dimension names**, so a stage
that must read a particular axis should not hardcode the key; take the
dimension name as a bounded setting (e.g. `time_dim: str = "time"` with a
pattern constraint) and look it up — the stage then works under any config's
naming.

Pull once and reuse the result within `run`; don't call `get()` in a loop.
When adjacent stages run in memory, `get()` hands over the live object with no
disk involved — laziness costs you nothing.

> **Not to be confused with:** a handler's *within-file* windowed read
> (`supports_windowed_read`, HANDLER_AUTHORING §7.2). That happens inside a
> stored file, below a handler's `load`. `LazyReference.window()` operates on
> inter-stage, in-flight data. Independent layers.

Your `run` returns one output object. It is wrapped in a reference for
downstream consumers by the skeleton; whether it is ever persisted is not your
decision — **saving is config-designated** and performed by the skeleton
through a named handler. Never write output to disk yourself.

## 8. Status, progress, warnings, errors

- `self.set_status(str)` — **mandatory**: update a one-line, human-readable
  account of what the stage is doing, at least once per `run`. Cheap, no side
  effects. The skeleton may read `status()` at any time.
- `progress() -> float | None` — **optional but recommended**: fraction
  complete in `[0, 1]`, or `None` where a total genuinely can't be known
  (streaming). Implement it whenever a total exists; keep it cheap. The default
  `progress()` returns `None`; update via `self.set_progress(x)` as you go.
- `self.add_warning(str)` — the stage completed and its output is **valid**,
  but something is worth recording (fell back to a default, clipped outliers).
  Warnings land in the operational log and in provenance; a warned work item
  still counts as succeeded and is **not** re-run on resume.
- **Errors are exceptions.** If the output would be invalid, raise (any
  exception; prefer `rainspout.contracts.StageError` with a specific message
  including what data was bad). The skeleton catches it, marks this (stage,
  work item) failed, skips its downstream stages for this work item only, and
  continues with the next work item. Never return partial/garbage output
  instead of raising, and never catch-and-continue around your own science.

**Check data cheaply.** Assert shape/dtype/columns — the things that make your
science meaningless if wrong — and raise with a specific message. Never deep
per-element validation of large arrays; that is a runtime cost the design
explicitly rejects. (Settings are the opposite: cheap to check, so checked
deeply — §4.)

## 9. Versioning

Every published stage carries a required `version` string (`"MAJOR.MINOR.PATCH"`
recommended). **Any edit to stage code must bump it.** Two mechanisms hold you
to this:

- **CI check**: a pull request that changes stage code without bumping that
  stage's `version` fails.
- **Code hash**: at run time the skeleton hashes your stage's code files and
  records the hash in every provenance entry — a tamper-evident backstop.

**The code/test boundary for both:** within your stage directory (§10), files
matching `test_*.py` / `*_test.py` and anything under `fixtures/` or
`example_data/` are *test territory* — excluded from the hash and exempt from
the bump requirement.
Every other `*.py` file in the directory is *stage code* (hashed as the sorted
concatenation of file bytes). Editing only your test does not force a bump;
editing science functions, helpers, or the class does.

## 10. Packaging: one stage = one self-contained directory

A stage ships as one directory that contains everything it is (NOT one file —
and not necessarily flat; organize the interior however suits the stage):

```
stages/smooth_readings/
├── __init__.py               # exposes the stage class
├── stage.py                  # settings + dependencies models, the class, version
├── science.py                # module-level science functions (more files/subdirs fine)
├── fixtures/                 # optional small test inputs
└── test_smooth_readings.py   # the mandated test (§11) — lives IN the stage directory
```

Self-containment is the point: copying this directory into another package's
`stages/` (plus the registration import) must work unchanged. No imports that
reach *out* of the directory except `rainspout.contracts`, your package's
shared utility module(s), and third-party libraries.

## 11. The mandated stage test

Every stage ships a test, **inside its directory**, in this shape — the
skeleton statically verifies these names exist and conform (it does not measure
your coverage at load time; your package CI does that):

```python
from rainspout.testing import run_stage
from .stage import SmoothReadings

STAGE = SmoothReadings
EXAMPLE_SETTINGS = {"window_len": 3, "method": "mean"}

def test_smooths_known_input():
    out = run_stage(STAGE, EXAMPLE_SETTINGS, deps={"data": [1.0, 4.0, 1.0, 4.0]})
    assert out == [...]          # exact expected result on a tiny fixture

def test_rejects_wrong_shape():
    with raises_stage_error():
        run_stage(STAGE, EXAMPLE_SETTINGS, deps={"data": "not-an-array"})
```

- `STAGE` and `EXAMPLE_SETTINGS` module-level names are **required**;
  `EXAMPLE_SETTINGS` must validate against your settings model (checked
  statically) — it doubles as documentation of a working configuration.
- `run_stage` is the skeleton-provided harness: it constructs the stage through
  the real validation path, wraps each `deps` value in a `LazyReference` (or a
  fake bound handler via `deps={"x": from_handler_data(obj)}`), runs `setup()`
  then `run()`, and returns the materialized output. If your stage reads
  `ref.coords`, pass `coords={"time": ..., ...}` and the harness stamps it on
  every wrapped reference (default: empty mapping).
- At least one test must assert a **known output on a tiny fixture**, and at
  least one must exercise a **failure path** (bad data raises with a message).
- Test your science functions directly too — they're module-level precisely so
  you can.

## 12. What NOT to do

- Don't put science in the class — thin orchestrator, always.
- Don't define `__init__`; don't bypass or re-implement validation.
- Don't save, write files, or produce any side effect — saving is
  config-designated, not stage-decided.
- Don't fetch anything outside declared dependencies (no paths from settings,
  no network, no environment).
- Don't call other stages, import their internals, or share mutable state.
- Don't alter or forge the work-item coordinate — read `ref.coords` freely,
  but it is driver-set and read-only.
- Don't hardcode a config dimension name when your science needs a specific
  axis — take the name as a bounded setting (§7).
- Don't try to steer a `BoundHandler` — `.load()` is no-arg, call-and-receive.
- Don't deep-validate large data; don't skip the cheap shape/type checks either.
- Don't catch exceptions to keep a doomed work item alive; raise specifically.
- Don't edit stage code without bumping `version`.
- Don't let `status()`/`progress()` do work — they are for reporting, not
  computing.

## 13. Self-check before you ship

- [ ] Class is thin; science lives in module-level functions.
- [ ] `name`, `version`, `settings_model`, `dependencies_model` all declared.
- [ ] No `__init__`; setup logic (if any) in idempotent `setup()`.
- [ ] Every setting bounded (`Field` ranges / `Literal` / constrained str);
      exceptions justified in a comment.
- [ ] Every dependency's annotation matches its intended wiring
      (`LazyReference` ↔ `from:`, `BoundHandler` ↔ `loader:`).
- [ ] `run` pulls references once, checks shape/type cheaply, raises
      specifically on bad data, returns exactly one output.
- [ ] `set_status` called; `progress` implemented if a total exists.
- [ ] Warnings via `add_warning` only when output is still valid.
- [ ] Mandated test present in the stage directory with `STAGE`,
      `EXAMPLE_SETTINGS`, a known-output test, and a failure-path test.
- [ ] Directory is self-contained; no reach-out imports.
- [ ] `version` bumped if you changed any code file in the directory.
