# Gate 2c response + Phase 1 report

## Part 1 — The four Gate 2c corrections, folded into `docs/`

All four are in the canonical `docs/` set (the `reports/2` copies now stand
as the historical gate record only).

1. **`loader:` → `handler:` unified.** Zero occurrences of `loader:` (or the
   word "loader") remain anywhere in `docs/`. A handler-wired dependency and
   a `save:` block now use the same `handler:` key; CONFIG §7 notes the
   symmetry explicitly — direction comes from `dependencies:` vs `save:`,
   never from the key. The wiring-kind rule is now `LazyReference` ↔ `from:`,
   `Handler` ↔ `handler:` (the annotation type is the `Handler` base itself —
   `BoundHandler` is gone, see #4).

2. **Block-form YAML everywhere.** Every example in CONFIG and Tutorial 3 is
   expanded (dimensions ranges, seed entries, resources, dependencies,
   settings, save). Inline `[a, b]` lists for scalar dimension values remain,
   inline `{}` mappings do not. CONFIG §1 gained the one-line note that
   `{a: b}` and the indented block are the same YAML, with the advice to
   expand a one-liner when it grows a second key.

3. **Construction/injection stated.** STAGE §5 has a new "Construction and
   injection" block: the driver constructs the stage (settings through the
   un-bypassable base `__init__`), and per work item resolves and injects
   dependencies into `run` — `from:` fields as coordinate-stamped references,
   `handler:` fields as ready-to-call handler instances built from configured
   resources. Stages construct nothing; noted as what makes them testable.

4. **Auxiliary handlers are stage-callable, not pre-bound.** `BoundHandler`
   is deleted from the docs. STAGE §5 now says: a `handler:` dependency
   arrives as a constructed handler instance the stage calls **with
   coordinates the stage computes**, keyed by the *handler's* role names,
   which by default should be assumed **unrelated** to the run's dimensions.
   Documented consequences, all in: no binding/projection/validation by the
   skeleton; **presence-and-wiring is the skeleton's whole guarantee, exactly
   parallel to settings** (your mid-turn phrasing, stated in both STAGE §5
   and CONFIG §5); misuse fails at runtime per work item; a window is a loop.
   The single-cell call is specified as **`load_one(coords)`** — final on the
   base, exactly `load` with a one-value spec, returning `(data, meta)`
   directly; nothing extra for handler authors to implement. The worked
   auxiliary example landed in HANDLER §6 (run iterating day × sensor, an
   events handler keyed by lat/lon/hour, the stage deriving coordinates from
   `ref.coords` + a bounded setting and looping over hours).

   Knock-on corrections this forced:
   - **CONFIG §5**: a `dimensions:` role map on a `handlers:` entry is now
     required **only for save targets** (the driver writes at work-item
     granularity, so a save target's map is held to the seed's standard —
     complete, onto iterated dimensions, checked at startup). Stage-callable
     entries carry no map at all. The dangling-reference typo check survives
     wherever a map appears; names are still never matched to handler
     internals.
   - **CONFIG §8**: a save is now described as the mirror of the *seed* (both
     driver-operated, hence both mapped), not of a `loader:` dependency.
   - **HANDLER §7.1**: the "range on a non-range handler fails at startup"
     rule is scoped — startup for the run's own wiring (seed), call-time
     per-work-item failure when a stage asks; `load_one` in a loop always
     works.
   - The previously flagged windowed-`loader:` v1 limitation is dissolved, as
     the review says — the STAGE-side language now shows the loop pattern
     instead of flagging a limitation.
   - PACKAGE §6 (artifacts) rewired to `Handler` + `handler:`, with the
     artifact version arriving via a bounded setting.

## Part 2 — Phase 1 (contracts & registry) delivered

Repo scaffold at the root (matching the Gate 1 layout): `pyproject.toml`
(uv, pydantic v2; dev group with pytest/pytest-cov/ruff/mypy), `README.md`
pointing at `docs/`, `src/rainspout/`, `tests/`.

```
src/rainspout/
├── __init__.py
├── errors.py            # taxonomy: DefinitionError tree (ContractViolation,
│                        #   RegistrationError, SettingsError, ResourcesError)
│                        #   vs runtime StageError/HandlerError + named_offender()
├── registry.py          # name → class per axis; duplicate names both parties;
│                        #   unknown name lists known names
├── discovery.py         # rainspout.components entry-point loading; failures
│                        #   re-raised naming the offending package
└── contracts/
    ├── __init__.py      # THE public surface (contracts = API)
    ├── _enforcement.py  # the uniform definition-time gesture, shared by axes
    ├── models.py        # StageSettings / StageDependencies / HandlerResources
    │                    #   (extra="forbid", frozen)
    ├── reference.py     # LazyReference: get() once-cached, read-only .coords,
    │                    #   can_window/window()
    ├── stage.py         # Stage base
    └── handler.py       # Handler base
```

Behavior proven by the 57 tests (all passing; coverage 95.6% against the 90%
floor; ruff and mypy clean):

- **Registration is one uniform gesture per axis** — subclass with `name`;
  missing/invalid/dotted/duplicate names fail at import naming the class (and
  both parties on a duplicate); axes are independent; re-import of the same
  class is idempotent; unknown lookups list what *is* registered.
- **Un-bypassable `__init__`** — a subclass (or mixin) defining `__init__`
  fails at class-definition time; settings/resources validate in the base
  with named-offender messages (`stage 'smooth_readings': setting
  'window_len': …`); validated models are frozen.
- **Definition-time completeness** — missing `version`, `settings_model`,
  `dependencies_model`, `run`, hooks, `dimension_roles`/`dimension_types`
  mismatches, non-bool capability flags: each a specific `ContractViolation`.
- **Final-method enforcement** — stage reporting machinery
  (`status`/`set_status`/`set_progress`/`add_warning`) and handler public
  verbs (`load`, `load_one`, `save`, `catalog`, `preflight`) cannot be
  shadowed, directly or via mixin; `progress()` is overridable as documented.
- **Probe path** — default `_probe` = `_load_cell` + `_check_structure`;
  overridable; `preflight` failures name handler and coordinate.
- **LazyReference** — fetch-once laziness, read-only driver-stamped
  `.coords`, window gating.
- **Entry-point discovery** — loads every `rainspout.components` collector;
  a registration failure inside a package is re-raised naming the entry
  point.

Decisions made in Phase 1 worth review (all small):
- Name pattern enforced as `^[a-z][a-z0-9_]*$` on **both** axes (C1
  generalized to stages).
- `load_one` added to the reserved-final verb list now, so no package can
  ever shadow it before its body lands in Phase 3.
- Handler/stage class-attribute checks accept inherited attributes except
  `name`, which must be declared on the class itself — subclassing a concrete
  component therefore forces a fresh name (or fails), keeping registration
  identity unambiguous.
- Verb *bodies* for `load`/`load_one`/`save`/`catalog` are deliberately not
  implemented (Phase 3 scope, per the plan); `preflight` is implemented since
  the probe contract is pure and self-contained.

Not done yet, on the books: consolidated `RAINSPOUT_DESIGN.md` (due end of
Phase 2 at the latest), and the blind-authorability verification you plan
against the now-final authoring set.

**STOP — end of Phase 1.** Next on approval: Phase 2, config & DAG validation
(config Pydantic models, YAML loader, seed rule, DAG resolution,
`spout validate`).
