# STAGE_AUTHORING.md — How to write a conforming Rainspout stage

This document is the complete contract for authoring a stage. You do not need
access to the Rainspout source — only an environment with `rainspout`
installed. If you can't build a working stage from this document alone, that is
a bug in this document; report it.

---

## The short version

A stage is one processing step. You write a small class that declares three
things — its tunable settings (each with a valid range), its named data
inputs, and a version string — plus a short `run` method that hands the real
work to ordinary Python functions, where your science lives and stays
testable on its own. Rainspout calls `run` once per work item, giving your
declared inputs as handles you pull data from. Your stage never reads or
writes files (saving is decided in the run config, not in code), never
fetches anything it didn't declare, and returns exactly one result for the
next stage. If the output would be wrong, raise an exception — that fails
only the current work item, and the run moves on.

The rest of this document is the precise contract. New here? Skim §1–§5,
build [Tutorial 2](tutorials/02_add_a_stage.md), and come back for details
as you need them.

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

## 2. The shape of a stage — template first, then a worked example

*(Template — required shape; `contract:` lines are fixed, `yours:` lines you
fill in. See "How code is shown" in the docs README.)*

```python
from pydantic import Field           # contract-adjacent: the library you declare bounds with (§4)

from rainspout.contracts import (    # contract: the only Rainspout import you need
    Stage, StageSettings, StageDependencies, LazyReference,
)


class MyStageSettings(StageSettings):        # yours: the name; contract: the base class
    """Static config: the knobs of this step."""
    ...                                      # yours: bounded fields (§4)


class MyStageDependencies(StageDependencies):   # yours: the name; contract: the base class
    """Named data inputs, one field per input."""
    ...                                      # yours: fields typed LazyReference or Handler (§5)


class MyStage(Stage):                        # contract: subclassing Stage IS registration
    name = "my_stage"                        # contract: attribute must exist; yours: the value
    version = "1.0.0"                        # contract: attribute; bump on ANY code edit (§9)
    settings_model = MyStageSettings         # contract: must point at your settings model
    dependencies_model = MyStageDependencies # contract: must point at your dependencies model

    def run(self, deps):                     # contract: the hook the runner calls, once per work item
        ...                                  # yours: pull inputs, call your science, return ONE output


def my_science(...):
    ...                                      # yours: module-level functions — the actual computation,
                                             #   testable with no skeleton in sight (§1)
```

Line by line:

- **The `pydantic` import** is where bounds come from (`Field(ge=…)`,
  `Literal`, constrained strings). Declaring bounds with it is the contract;
  which bounds — always yours (§4).
- **The `rainspout.contracts` import** is the whole framework surface a
  stage touches: three base classes plus `LazyReference`, the handle a stage
  receives in place of raw data (§5, §7).
- **The settings model** holds every tunable of this step as a typed,
  bounded field. A config's `settings:` block is validated against it at
  startup; after construction it's read-only as `self.settings`.
- **The dependencies model** names each data input as a field, and the
  field's *type annotation* declares what kind of config wiring it accepts —
  `LazyReference` for upstream stage/seed output (`from:`), `Handler` for a
  handler instance the stage will call itself (`handler:`) (§5).
- **`name`** is the registry key configs use. **`version`** feeds the
  provenance chain and is enforced by CI: any edit to stage code without a
  bump fails the version check (§9).
- **`run(deps)`** is the only method the runner calls (after optional
  `setup()`, §6). It receives your validated dependencies, should pull each
  reference once, do a cheap shape check, hand off to the science functions,
  and return exactly one output object — no side effects, no saving (§1).
- **The module-level science functions** take plain Python values and return
  plain Python values. That's where the real work lives — the class is just
  the wiring (§1). They're testable directly, without any framework.

**Worked example** — the same shape filled in: a smoothing step for lists of
readings. The `window_len`/`method` knobs, the `Literal["mean", "median"]`
choice, and the smoothing itself are this *example's* domain:

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
    """Named data inputs. Wired in config via `from:` or `handler:` (§5)."""
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

Tutorial 2 builds this exact stage with the science filled in.

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

**Conditional settings — when one knob's shape depends on another.** Say a
`method` setting is either plain `mean` or `weighted`, and only `weighted`
takes a list of weights. Don't flatten that into optional fields with
prose rules ("`weights` required iff…"); make the shapes themselves the
rule with a **discriminated union** — ordinary Pydantic, fully supported.
(Worked example — `mean`/`weighted` and their fields are the example's
domain; the pattern is what's contractual: arm models with a shared literal
tag field, united under `Field(discriminator=…)`.)

```python
from typing import Annotated, Literal, Union
from pydantic import BaseModel, ConfigDict, Field

class MeanMethod(BaseModel):
    model_config = ConfigDict(frozen=True)
    kind: Literal["mean"]

class WeightedMethod(BaseModel):
    model_config = ConfigDict(frozen=True)
    kind: Literal["weighted"]
    weights: list[float] = Field(min_length=1, max_length=1000)

class MyStageSettings(StageSettings):
    method: Annotated[Union[MeanMethod, WeightedMethod], Field(discriminator="kind")]
```

In config it's just a nested block:

```yaml
settings:
  method:
    kind: weighted
    weights: [1.0, 2.0, 3.0]
```

Everything you already rely on extends to the arms: a wrong `kind` fails at
startup listing the expected tags; a bad field *inside* an arm fails with a
dotted path naming the arm (`setting 'method.weighted.weights': Field
required`); provenance records the fully resolved structure, defaults
included. Two rules carry over:

- **The bounded rule applies to every field of every arm** — the conformance
  lint walks nested models and unions and will flag e.g.
  `method[WeightedMethod].scale` if you leave it unbounded.
- **Declare nested settings models frozen** (`model_config =
  ConfigDict(frozen=True)`, as above). `StageSettings` itself is frozen, but
  frozen-ness is per-model in Pydantic — an unfrozen arm could be mutated
  mid-run, and provenance would then record something the config never said.

## 5. Dependencies — the only door for data

`dependencies_model` extends `StageDependencies`. Each field is a named input,
and its **type annotation declares what kind of wiring it accepts**:

- `LazyReference` — wired in config with `from: <upstream_stage>`. You receive
  a reference to the upstream stage's output (§7).
- `Handler` — wired in config with `handler: <handler_instance>`. You receive
  a **constructed handler instance**, built by the driver from that entry's
  configured resources, and you call it yourself with coordinates **you
  compute**. Read your work-item coordinate (§7), derive whatever the
  handler's roles need, and ask:

  ```python
  data, meta = deps.events.load_one({"lat": lat, "lon": lon, "hour": hour})
  ```

  `load_one(coords)` is the single-cell call, keyed by the *handler's* role
  names; a stage that needs several cells calls it in a loop over the
  coordinates it computes. The handler's axes may be — and by default should
  be assumed to be — **completely unrelated** to the run's dimensions: an
  events source keyed by lat/lon/hour under a run iterating day × sensor is
  the normal case, not an edge case. The loaded data may also be richer than
  you need (a whole events file, a full calibration table); using one piece
  of it is normal and legitimate.

**How you use a handler dependency is private to your stage.** The config
specifies only *which* handler you get. The skeleton's whole guarantee for
handler dependencies is **presence-and-wiring** — every declared dependency
is satisfied and references a real, validly-configured handler instance —
exactly parallel to what it guarantees for settings. It does not bind,
project, or validate your coordinates against the work item; there is no
projection machinery between the run's dimensions and your handler's roles.
Correct use is yours to get right; misuse — a role you never supplied, a
value of the wrong type, a cell that isn't there — fails at **runtime**, for
that work item only, isolated and logged (§8). Loading is the only
legitimate stage-side use of a handler dependency: calling its save path
would be a side effect (§1).

**Construction and injection.** You construct nothing. The driver constructs
your stage (settings validated in the un-bypassable base `__init__`) and,
per work item, resolves your declared dependencies and injects them into
`run`: a `from:` field arrives as the upstream data reference, already
coordinate-stamped; a `handler:` field arrives as a ready-to-call handler
instance. This is also what makes stages testable — a test injects fakes
through the same door (§11).

The wiring is checked at startup: config wiring a `from:` into a `Handler`
field (or vice versa), a missing dependency, an extra one, or a misspelled
name all fail loudly, naming stage and field.

**How data enters the DAG:** the run config's `seed:` block (CONFIG_AUTHORING
§6) defines a named seed entry — the handler that feeds the pipeline; the
driver loads the seed cell for each work item, stamps the coordinate on the
resulting reference, and offers it to stages under the entry's name. The
first stage simply declares a `LazyReference` dependency and the config wires
it `from: <seed_name>` — no package ever writes a pass-through "load the
data" stage. A **mid-DAG stage** needing an additional input (a calibration
table, an events file, a trained-model artifact) declares an extra `Handler`
dependency wired `handler:` to an instance from the `handlers:` block — the
same gesture anywhere in the DAG. A worked example of the compute-and-call
pattern is in HANDLER_AUTHORING §6.

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

The two ALL-CAPS names and the use of `run_stage` are the contract; every
value is the example's:

```python
from rainspout.testing import run_stage      # contract: the shipped harness
from .stage import SmoothReadings

STAGE = SmoothReadings                       # contract: this exact name; yours: the class
EXAMPLE_SETTINGS = {"window_len": 3, "method": "mean"}
                                             # contract: the name; yours: valid settings

def test_smooths_known_input():              # contract: ≥1 known-output test
    out = run_stage(STAGE, EXAMPLE_SETTINGS, deps={"data": [1.0, 4.0, 1.0, 4.0]})
    assert out == [...]          # exact expected result on a tiny fixture

def test_rejects_wrong_shape():              # contract: ≥1 failure-path test
    with raises_stage_error():
        run_stage(STAGE, EXAMPLE_SETTINGS, deps={"data": "not-an-array"})
```

- `STAGE` and `EXAMPLE_SETTINGS` module-level names are **required**;
  `EXAMPLE_SETTINGS` must validate against your settings model (checked
  statically) — it doubles as documentation of a working configuration.
- `run_stage` is the skeleton-provided harness: it constructs the stage through
  the real validation path, wraps each `deps` value in a `LazyReference` (or a
  fake handler via `deps={"x": from_handler_data(obj)}`, whose `load_one`
  returns `obj` for any coordinates), runs `setup()` then `run()`, and returns
  the materialized output. If your stage reads
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
- Don't save through a handler dependency — loading is a stage's only
  legitimate use of one; saving is config-designated, never stage-decided.
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
      exceptions justified in a comment. Nested/conditional settings models
      (§4): every arm's fields bounded too, and the models frozen.
- [ ] Every dependency's annotation matches its intended wiring
      (`LazyReference` ↔ `from:`, `Handler` ↔ `handler:`).
- [ ] `run` pulls references once, checks shape/type cheaply, raises
      specifically on bad data, returns exactly one output.
- [ ] `set_status` called; `progress` implemented if a total exists.
- [ ] Warnings via `add_warning` only when output is still valid.
- [ ] Mandated test present in the stage directory with `STAGE`,
      `EXAMPLE_SETTINGS`, a known-output test, and a failure-path test.
- [ ] Directory is self-contained; no reach-out imports.
- [ ] `version` bumped if you changed any code file in the directory.
