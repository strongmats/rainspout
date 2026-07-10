# Gate 2 — Cover note for review

Status: **awaiting Gate 2 approval.** Deliverables in this directory:

- `HANDLER_AUTHORING.md`, `STAGE_AUTHORING.md`, `CONFIG_AUTHORING.md`,
  `PACKAGE_AUTHORING.md`
- `tutorials/01_add_a_handler.md`, `02_add_a_stage.md`, `03_create_a_run.md`

All Gate 1 corrections and decisions are folded in: underscore handler names
(C1), delta = exists − attempted with `--retry-failed` (Q1), window-bounded
catalog (Q2), dimension roles + pre-flight probe (Q3), no inter-stage
structural checks, stage-as-directory with the code/test hash boundary (Q4),
definition-time `__init__` enforcement with the mixin restriction documented
(Q5), minimal `build-image` (Q6, in PACKAGE/CI territory only), no Cython —
observable setup-hook exercise noted for reference content (Q7), the two
windowing layers each carrying a "not to be confused with" note (Q8), clean
realtime stop (Q9), and bounded settings as a hard requirement in both
authoring docs.

## Decisions these docs newly propose (the review targets)

1. **Handler author surface = private hooks.** Authors implement `_load_cell` /
   `_save_cell` / `_catalog_cells` (+ optional `_probe`, `_check_structure`);
   the public `load`/`save`/`catalog`/`preflight` verbs are final on the base
   class and wrap the hooks with capability/validation checks. Makes the
   range-capability and single-cell-save rules un-bypassable and keeps the
   blind-author surface tiny.

2. **Driver expands ranges; handlers see only explicit values.** Config
   `start/stop/step` is expanded before any handler call; a dimension spec is
   `{role: (values…)}`, single value = tuple of one; `load` returns a lazy
   per-cell iterator of `Cell(coords, data, meta)`.

3. **Role mapping syntax:** `handlers.<instance>.dimensions: {handler_role:
   config_dimension}`, with completeness and type checks at startup
   (HANDLER §6, CONFIG §5).

4. **Exact pre-flight contract** (HANDLER §8): (1) role mapping check,
   (2) type check from `dimension_types`, (3) structural probe on the first
   cataloged cell in the run window — default `_probe` = load + `_check_structure`,
   overridable where a full load is expensive, (4) empty catalog ⇒ structural
   probe skipped with a loud logged notice (legitimate for realtime).

5. **Wiring kinds are type annotations.** A dependency field annotated
   `LazyReference` accepts only `from:`; `BoundHandler` accepts only `loader:`;
   mismatches fail at startup. `BoundHandler.load()` is no-arg, pre-bound to
   the work item's cell — dimensions stay invisible to stages.

6. **Metadata embedding is format-private; sidecar fallback allowed**
   (`<file>.rainspout.json`) when a format can't embed; loading foreign data
   returns a fresh empty-provenance block.

7. **Code/test hash boundary:** within a component directory, `test_*.py`,
   `*_test.py`, `fixtures/`, `example_data/` are excluded from the code hash
   and the version-bump requirement; all other `*.py` files are stage code.

8. **Test placement decided: inside the component's directory** (PACKAGE §3),
   with package-level `tests/` reserved for cross-component integration.
   Rationale: the test is the executable half of the self-containment contract;
   conformance checking stays directory-local; orphan tests impossible.

9. **`rainspout.testing` becomes public contract:** `run_stage`,
   `from_handler_data`, `assert_roundtrip` (float-tolerant equality, custom
   `equal=` escape hatch). Mandated test shapes require module-level `STAGE` +
   `EXAMPLE_SETTINGS` (stages) and `HANDLER` + `EXAMPLE_RESOURCES` +
   `EXAMPLE_COORDS` (handlers) so the static conformance check is a name/shape
   check and the examples double as documentation.

10. **Entry-point groups:** `rainspout.components` (one module importing all
    components; import = registration) and `rainspout.verbs` (Typer app; mount
    name = entry-point name). Seed loaders ship in packages, not the skeleton.

11. **CLI details assumed in the docs:** `--select dim=value` narrowing,
    `--retry-failed`, `poll_frequency` forbidden outside realtime, `--dry-run`
    reporting done/failed/to-run counts.

## Known v1 limitation flagged (not silently decided)

- A `loader:` dependency is always bound to the **exact work-item cell**. A
  stage wanting a grid *window* through a handler (e.g. previous N days as
  context) has no config syntax in v1 — grid ranges currently serve
  catalog/driver only. Extending `loader:` with a window spec is a clean future
  addition; saying so here so it's a decision, not an accident.

**STOP — Gate 2.** Awaiting documentation review before any implementation.
