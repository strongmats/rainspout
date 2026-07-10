# HANDLER_AUTHORING.md — How to write a conforming Rainspout handler

This document is the complete contract for authoring a handler. You do not need
access to the Rainspout source to follow it — only an environment with
`rainspout` installed. If you can't build a working handler from this document
alone, that is a bug in this document; report it.

---

## 1. What a handler is

A handler is **one fixed combination** of: file type + in-file data structure +
filename convention + folder structure + access channel. It is a black box that
maps a *dimension coordinate* to data (and back). Everything from the base
directory down — folders, filenames, in-file layout, connections — is your
private business; the skeleton never looks inside.

A handler is **not**: a general-purpose storage layer, a codec you mix and match,
or a place for processing logic. If you need the same data in two formats, write
two handlers.

## 2. Naming

The registry name is `datatype_channel_type`, underscores only, no dots —
e.g. `broadband_local_mat`, `cleaned_local_h5`, `readings_s3_parquet`. The
module file is named to match (`broadband_local_mat.py` or a directory —
see §12). The name is **purely conventional**: the skeleton never parses it for
meaning. It is a registry key; every capability is declared explicitly in code.

## 3. The skeleton of a handler

```python
from datetime import date
from pydantic import DirectoryPath

from rainspout.contracts import Handler, HandlerResources, Coords, Meta


class ReadingsLocalCsvResources(HandlerResources):
    """Everything this handler needs to reach its data. Bounded (§5)."""
    base_dir: DirectoryPath


class ReadingsLocalCsv(Handler):
    name = "readings_local_csv"                 # registry key (§2)
    resources_model = ReadingsLocalCsvResources
    dimension_roles = ("day", "sensor")         # §6 — the roles this handler resolves
    dimension_types = {"day": date, "sensor": str}

    supports_grid_range = False                 # §7.1
    supports_windowed_read = False              # §7.2

    def _load_cell(self, coords: Coords) -> tuple[object, Meta]: ...
    def _save_cell(self, coords: Coords, data: object, meta: Meta) -> None: ...
    def _catalog_cells(self, spec): ...          # yields CatalogEntry, §9
```

Rules that apply to the class itself:

- **Registration is automatic.** Subclassing `Handler` with a `name` attribute
  registers it (via `__init_subclass__`). A missing or duplicate `name` fails at
  import time with a message naming your class. Never edit any registry.
- **Do not define `__init__`.** The base `__init__` validates your resources
  against `resources_model` and cannot be bypassed; a subclass that defines
  `__init__` fails **at class-definition time**. There is no post-init hook on
  handlers — open connections lazily inside your verbs (§10).
- Avoid multiple inheritance with classes that define `__init__`; the
  definition-time check inspects your class and its non-`Handler` bases, and
  mixins providing `__init__` are rejected.
- After base `__init__`, your validated resources are available as
  `self.resources` (a frozen model instance).

## 4. The three verbs (what the skeleton calls)

You **implement the underscore hooks**; the public verbs live on the base class,
are final, and wrap your hooks with the capability and validation checks. Their
wrapping behavior is not hidden: each public verb's docstring documents exactly
what it does around your hook — range expansion, lazy per-cell iteration, the
single-cell-save check, error wrapping with coordinates — so nothing about the
call path is a surprise to you or your reviewer:

| Public verb (skeleton calls) | Your hook | Job |
|---|---|---|
| `load(spec)` | `_load_cell(coords)` | dimension spec → data |
| `save(spec, data, meta)` | `_save_cell(coords, data, meta)` | data → storage |
| `catalog(spec)` | `_catalog_cells(spec)` | what exists in the asked window |
| `preflight(coords)` | `_probe(coords)` *(optional)* | startup sanity (§8) |

**One input shape.** Every verb takes a *dimension spec*: a mapping from each of
your declared roles to an **ordered tuple of explicit values**. A single value
is always expressed as a tuple of one — there is no scalar special case at the
interface. The driver expands config ranges (`start/stop/step`) into explicit
values before you ever see them; you never parse range syntax.

- `Coords` is the degenerate case: every role maps to exactly one value.
- `load(spec)` returns a **lazy per-cell iterator** of `Cell(coords, data, meta)`.
  For a single-cell spec it yields one `Cell`. It must never materialize all
  cells of a range at once — the base class calls `_load_cell` one coordinate at
  a time, on demand.
- `save` accepts only a single-cell spec (the base enforces this) and must
  persist the provided `meta` block (§11) alongside the data.
- Use **compression on save** where your format supports it (e.g. HDF5).

## 5. Resources — bounded, validated

`resources_model` is a Pydantic v2 model with `extra="forbid"` (inherited from
`HandlerResources`). **Every field must have a bounded valid domain**: paths as
`DirectoryPath`/`FilePath`, numbers with `Field(ge=…, le=…)`, choices as
`Literal[...]`/`Enum`, strings constrained (pattern / max length). A bare
unconstrained `str`/`int`/`float` is permitted only as a deliberate exception
with a justifying comment on the field — and will draw a lint-style warning from
the skeleton's conformance check. Out-of-range values fail loudly at startup,
naming the handler instance and field.

Secrets (API keys) are resources too; accept them as constrained strings and
document how they're sourced. Never read config, environment, or global state
from anywhere except your resources.

## 6. Dimension roles — how you stay blind to config names

You are written before any config exists, so you cannot know what the user will
call their dimensions. You declare **roles** — the axes your storage layout
resolves — in `dimension_roles`. The user's config maps each of their dimension
names onto your roles. Everything you receive (specs, coords) is keyed **by your
role names**; the skeleton does the translation in both directions. Your
`_catalog_cells` output is likewise keyed by role.

- Declare `dimension_types` for each role. Whether they are checked at startup
  or at runtime depends on the position you are wired into (below).
- Roles are the **whole** dimension vocabulary you know. Never infer axes from
  paths or filenames at the interface level.

**Two positions, one contract.** A config can wire a handler instance into two
different positions, and you author identically for both — you never know
which you'll be:

- **Seed handler** — named in the config's `seed:` block; it is how data
  enters the DAG, loading along the run's *iterated dimensions*, with the
  driver coordinating per work item. Validation is rigorous and at startup:
  every declared role mapped, every mapping to a real dimension, the
  dimensions corresponding **exactly** to the iterated set, values coercible
  to your `dimension_types` — any miss fails loudly before data moves, and the
  structural probe (§8) then confirms one real cell.
- **Auxiliary handler** — wired as some stage's `loader:` dependency (events
  files, calibration tables, artifacts); it loads along *its own* dimensions,
  which need not match the iterated set. It is **not dimension-validated at
  startup**: whether what it loads serves the consuming stage — including
  legitimate superset/subset relationships, where you load a rich structure
  and the stage uses one piece — proves out at runtime, and a genuine mismatch
  is an isolated, logged, per-work-item failure, never a startup one.

## 7. The two independent range concepts

These are separate capabilities. Declare each honestly; both default to off.

### 7.1 Dimension-grid range (`supports_grid_range`)

Off: `load` and `save` specs must be single-cell; the base class rejects a
multi-cell `load` spec **at startup pre-flight** (config wiring that could ask
you for a range fails before the run starts, naming you). `catalog` always
accepts ranges regardless — surveying windows is its job.

On: `load` may receive a multi-cell spec. You still only implement
`_load_cell(coords)`; the base iterates coordinates lazily. Only set this flag
if per-cell access through your layout is genuinely cheap (no re-opening a huge
archive per cell) — otherwise leave it off and let the driver iterate.

### 7.2 Within-file windowing (`supports_windowed_read`)

Off (default): `_load_cell(coords)` reads the whole cell.

On: implement `_load_cell(coords, window)` where `window` is a mapping of
window arguments **whose semantics you define and document** in your handler's
docstring (e.g. `{"rows": (0, 1000)}`, `{"t_start": …, "t_end": …}`). You must
be able to serve the slice **without materializing the whole file** — this
capability exists for HDF5/memmap-style formats; do not claim it for formats
(CSV, .mat v5) that force a full read anyway.

> **Not to be confused with:** the *lazy-reference* `window()` that stages use
> on inter-stage data (see STAGE_AUTHORING §7). That operates on in-flight data
> between stages; yours operates inside a stored file. They are independent
> layers that happen to rhyme.

## 8. Startup pre-flight — the probe contract

At startup, after config validation, the driver runs a **pre-flight** against
the **seed handler instance** — the handler the driver itself coordinates with
(§6). Auxiliary instances get their resources validated like everything else in
the config, but no dimension checks and no probe; their fitness proves out at
runtime. Pre-flight is cheap by design and must stay cheap:

1. **Role/name mapping check** (skeleton does this; you get it for free): every
   `dimension_roles` entry mapped, no unknown mappings, the mapped set exactly
   the iterated dimension set.
2. **Type check** (skeleton, from your `dimension_types`): the config's expanded
   dimension values coerce to your declared types.
3. **Structural probe** (yours): the base calls `_probe(coords)` with a single
   probe coordinate — the first cell your `catalog` reports within the run's
   dimension window. Your `_probe` must confirm the coordinate resolves to
   **structurally sane data** (right type/structure) *without loading it in
   full*: read a header, check a shape attribute, open-and-close. The default
   implementation calls `_load_cell` on the probe coordinate and passes the
   result to `_check_structure(data, meta)` (default: no-op) — acceptable for
   small-cell formats; override `_probe` for anything where a full cell load is
   expensive.
4. If your `catalog` reports **nothing** in the window, the structural probe is
   skipped and a loud notice is logged (legitimate in real-time mode, where a
   run may start before data arrives). Steps 1–2 still apply.

A probe failure raises with a message naming the handler instance, the role(s),
and the offending coordinate — and kills the run before any work item executes.
Genuine per-coordinate problems (one missing/corrupt file among thousands) are
**not** pre-flight's job; they surface per work item at runtime and are logged
without sinking the run.

## 9. `catalog` — the driver's eyes

`_catalog_cells(spec)` yields one `CatalogEntry(coords, extras)` per cell that
**exists** in storage, where `coords` is a single-cell mapping keyed by your
roles and `extras` is an optional, handler-private dict (size, mtime — never
interpreted by the skeleton).

Hard requirements:

- **Survey only the window you are asked about.** The spec bounds your search;
  never scan the entire dimension space in storage. In real-time mode the driver
  calls `catalog` every poll cycle — an unbounded survey makes polling
  unaffordable and is a conformance failure.
- Yield lazily where the channel allows (paginated APIs, large listings).
- Report a cell only if a subsequent `load` of it would plausibly succeed
  (exists and is non-empty by your cheapest test); do not deep-validate.

The public `catalog` verb can also write the survey to a **catalog file** (a
validated JSON document: handler name, roles, entries, generated-at) when the
caller requests it; the base class handles that serialization — your hook only
yields entries.

## 10. Lifecycle is private

Stages and the skeleton call your verbs and must never know whether you opened
a connection per call or kept a session. Default posture: **per-transaction**
(open, act, close) — correct for local files and simple APIs. If you keep a
session (connection pool, auth token), manage it entirely inside the handler,
lazily created on first use, and make each verb safe to call at any time.
Never require external setup ordering ("call X before load").

## 11. The metadata block — one file, no sidecars

The **shared metadata block** is the same shape across all file types: a `Meta`
model carrying schema version, `run_id`, the cell's coords, and the
**provenance chain** — an ordered list of `{stage_name, stage_version,
code_hash, settings_used, timestamp}` entries. On `save` you receive it; on
`load` you return what you find.

**A cell is one file, and the metadata lives in it.** Embed the block in the
data file itself — HDF5 attributes, a struct field in `.mat`, whatever your
format offers. Auxiliary metadata files are discouraged and the skeleton
defines no sidecar convention: a cell that is secretly two files breaks
copy/move/delete atomicity and is exactly the coupling handlers exist to hide.

**Handling metadata is optional — but skipping it has a price.** Choose one
posture and hold it:

- **Metadata-capable (strongly recommended).** `_save_cell` embeds the block;
  `_load_cell` recovers it intact — no dropped fields, no reordered chain.
  Everything computed through you keeps its provenance.
- **Metadata-ignoring (allowed, highly discouraged).** A plain-data handler
  (say, bare CSV for interchange with non-Rainspout consumers) may ignore
  `meta` entirely: save data only, return a fresh block on load. This is
  conforming — and it **severs the provenance chain** for everything passing
  through you. That is your accepted tradeoff; say so in your class docstring
  so config authors choose you knowingly.

**Plain-text formats can embed responsibly.** The recommended pattern is one
clearly delimited, machine-strippable section — e.g. a single comment line
`# rainspout-meta: {…json…}` at the top of a CSV. Any consumer that skips
`#`-comments (or a one-line `grep -v`) still reads pure data, and your
`_load_cell` recovers the block exactly. Tutorial 1 builds this pattern.

Loading **foreign or metadata-less data** (raw instrument files, files from a
metadata-ignoring handler) is always legal and never an error: return a fresh
empty-provenance block with the coords filled in — provenance starts fresh
from that point.

## 12. Packaging, example data, and the mandated round-trip test

A handler ships as **one self-contained directory** inside your package (see
PACKAGE_AUTHORING §3):

```
handlers/readings_local_csv/
├── __init__.py            # exposes the handler class
├── handler.py             # the code above
├── example_data/          # a real, tiny, committed example of your format
│   └── day=2026-01-01/sensor=s1/readings.csv
└── test_roundtrip.py      # the mandated test, below
```

The **example data file** is required: it makes the test self-contained and
doubles as living documentation of your format. Keep it tiny (kilobytes).

The **round-trip test** is mandated in this exact shape — the skeleton's
conformance check verifies these module-level names exist and that the test
runs the shipped helper:

```python
from pathlib import Path
from rainspout.testing import assert_roundtrip
from .handler import ReadingsLocalCsv

HANDLER = ReadingsLocalCsv
EXAMPLE_RESOURCES = {"base_dir": Path(__file__).parent / "example_data"}
EXAMPLE_COORDS = {"day": "2026-01-01", "sensor": "s1"}

def test_roundtrip(tmp_path):
    assert_roundtrip(HANDLER, EXAMPLE_RESOURCES, EXAMPLE_COORDS, tmp_path)
```

`assert_roundtrip` performs: **load** the example cell → **save** it to a
temporary base dir → **load** the saved copy → **assert equal** → **catalog**
the temporary dir and assert the cell is reported. Equality is exact for
integers, strings, and structure; floats compare within tolerance
(`allclose`-style). It checks **preservation of whatever exists**: data always;
the metadata block too **if** your handler handles metadata (§11). A
metadata-ignoring handler is never failed merely for not handling metadata —
what fails a handler is *altering* data, or altering metadata it claims to
handle, across load→save→load. If your data needs a different equality (custom
container types), pass `equal=<callable>` to `assert_roundtrip` and justify it
in a comment.

## 13. What NOT to do

- Don't parse meaning out of your registry name, or anyone else's.
- Don't define `__init__`, touch the registry, or import other handlers/stages.
- Don't do processing in a handler — no filtering, resampling, unit conversion.
  Load faithfully; transformation is stage territory.
- Don't materialize a range: the per-cell iterator is lazy, keep it lazy.
- Don't write auxiliary metadata files — the block lives inside the one data
  file, or (deliberately, documented) nowhere (§11).
- Don't survey outside the catalog window you were given.
- Don't claim a capability flag you don't genuinely support; don't silently
  degrade (e.g. serving a "window" by reading the whole file).
- Don't read environment variables, global config, or the pipeline config —
  resources are your entire universe of configuration.
- Don't cache across coords in ways that can serve stale data; if you cache,
  key strictly by coordinate and document it.
- Don't swallow storage errors into empty results — raise, with the coordinate
  in the message; the skeleton handles per-work-item isolation.

## 14. Self-check before you ship

- [ ] Name is `datatype_channel_type`, underscores, registered by subclassing.
- [ ] No `__init__` defined; resources model bounded, `extra="forbid"` inherited.
- [ ] `dimension_roles` + `dimension_types` declared and complete.
- [ ] Both capability flags set honestly; windowed-read semantics documented if on.
- [ ] `_load_cell` / `_save_cell` / `_catalog_cells` implemented; lazy where required.
- [ ] `_probe` overridden if a full-cell load is expensive.
- [ ] Metadata posture chosen: embedded **in the data file** on save and
      recovered intact on load (recommended), or deliberately ignored with the
      tradeoff stated in the class docstring. No auxiliary metadata files.
- [ ] Compression used on save where the format supports it.
- [ ] `example_data/` committed, tiny, and loadable with `EXAMPLE_RESOURCES`.
- [ ] `test_roundtrip.py` present in the mandated shape and passing.
- [ ] `catalog` bounded to the asked window; tested against the example data.
- [ ] Directory is self-contained: copying it into another package's `handlers/`
      (plus registration import) would work unchanged.
