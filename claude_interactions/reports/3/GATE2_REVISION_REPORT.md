# Gate 2 revision report — response to prompts/3/GATE2_REVIEW_RESPONSE.md

All corrections are folded into the Gate 2 deliverables **in place** (the
files in `claude_interactions/reports/2/` are the living contract that
implementation will build from; this report is the record of what changed).
Four questions surfaced during the revision are at the end — none blocks
Phase 1, but #1 and #2 shape config schema and CLI semantics, so I'd like
answers before those parts are built.

---

## Part A corrections applied

- **#1** — HANDLER §4 now states that each public verb's docstring documents
  its wrapping behavior (range expansion, lazy per-cell iteration, the
  single-cell-save check, error wrapping with coordinates). This is also now a
  requirement on the base-class implementation.
- **#6 (single-file metadata)** — HANDLER §11 rewritten: the block lives **in
  the one data file**; no sidecar convention exists; auxiliary metadata files
  are called out as a "what not to do." Metadata handling is now explicitly
  **optional** with two documented postures (metadata-capable, strongly
  recommended / metadata-ignoring, allowed, provenance-severing, must be
  stated in the class docstring). Round-trip semantics (HANDLER §12) are now
  *preserves-what-exists*: data always; metadata iff the handler claims it; a
  handler is never failed merely for ignoring metadata. The
  plain-text embedding pattern (one strippable `# rainspout-meta: {…}` comment
  line) is taught in HANDLER §11 and **built for real in Tutorial 1**, whose
  CSV handler now embeds instead of writing a sidecar.
- **#7** — STAGE §9's hash-boundary now names `example_data/` alongside
  `fixtures/` and the test-file patterns (matching the approved rule).
- **#9** — PACKAGE §9 now states the v1 **stability commitment** for
  `rainspout.testing` (helpers + mandated module-level names), same weight as
  `rainspout.contracts`.
- **#10** — PACKAGE §4 adds the two discovery notes: entry-point changes need
  `uv sync` (while collector-module additions are live), and a component
  missing from `components.py` fails **silently** — verify with `spout
  catalog`.
- **#11** — `--select` semantics spelled out in CONFIG §2 (and echoed in §3
  and Tutorial 3): selection narrows the space *first*, then the log is
  subtracted — an attempted selected cell is still skipped; `--select` +
  `--retry-failed` re-queues exactly the selected failures. See question #2 on
  the "done cell" reading.
- **Windowed-`loader:` limitation** — left as a documented v1 boundary
  (STAGE §5 now states `.load()` is call-and-receive; no window syntax built).

## Part B revisions applied

- **B1/B2 (coordinate-aware stages)** — STAGE §1 rewritten: stages are
  coordinate-aware; the *skeleton* is what stays dimension-agnostic. STAGE §7
  adds `ref.coords`: the work item's read-only `{dimension: value}` mapping,
  driver-stamped at seed time, flowing downstream automatically. "Don't look
  for coordinates" is replaced by "read freely, never forge or alter"
  (trustworthy provenance). `run_stage` grew an optional `coords=` parameter
  so coordinate-reading stages are testable. Tutorial 2 shows the read path
  exists even though smoothing doesn't need it.
- **B3 (`seed:` block)** — CONFIG gains a sixth top-level key, `seed:`
  (new §6): registry handler + resources + role mapping; the driver loads the
  seed cell per work item, stamps the coordinate, and offers it as the
  reserved upstream name `seed`; first stage wires `from: seed`. The
  boilerplate seed-loader stage is **gone everywhere**: STAGE §5 rewritten,
  Tutorial 3's Step 0 (the hand-written `load_readings` stage) deleted, its
  config/outputs redone with the seed block. One seed per config in v1.
- **B4 (seed vs. auxiliary)** — HANDLER §6 now defines the two wiring
  positions ("two positions, one contract" — authors never know which they'll
  be). Seed: exact-match role/dimension/type validation at startup + the §8
  probe. Auxiliary: **not dimension-validated at startup**; superset/subset
  data relationships explicitly legitimate; mismatch = isolated, logged,
  per-work-item runtime failure. HANDLER §8 pre-flight is now scoped to the
  seed instance. CONFIG §5 reframed as *auxiliary* instances with the
  startup/runtime validation split spelled out.
- **B5 (linear now, general machinery)** — CONFIG §7 states the v1
  linear-chain limit while noting the wiring syntax stays general (no
  one-input assumption to migrate off). The Phase-plan consequence: the
  runner keeps topological-sort/graph machinery; no branching features built.
- **B6 (names as bookkeeping)** — CONFIG §3 now says dimension names are the
  config author's bookkeeping, enforced only at the seed edge; no
  stage-declared "expected dimensions" anywhere (deliberately rejected —
  noted so it isn't re-proposed later).

## Errata fixed while revising (not in the review)

- **Tutorial 3's failure-isolation demo was internally inconsistent**: it
  deleted a raw cell and then showed that cell *failing at load*. But a
  deleted cell is never reported by the seed's `catalog`, so it never enters
  the delta and never becomes a work item — it can't fail. The demo now
  **corrupts** the cell instead (exists and non-empty ⇒ cataloged ⇒ fails at
  load ⇒ isolated per-work-item failure), with a note explaining exactly this
  distinction, and the resume step fixes the file rather than restoring it.

## Questions surfaced (answers wanted before the affected parts are built)

1. **Shape of `seed:` vs. "multiple named seeds later."** I implemented the
   review's literal example — `seed:` holds `handler`/`resources`/`dimensions`
   directly, wired as `from: seed` (with `resources:` added, since the block
   defines its own handler rather than referencing a `handlers:` instance).
   But that shape makes multiple seeds a schema *change* (the block would
   have to become named entries, and `from: seed` would become
   `from: <seed_name>`). If truly non-breaking growth is wanted, the named
   form — `seed: {raw: {handler: …}}` wired `from: raw` — should be the v1
   shape instead. Which do you want? (Docs currently say the literal form;
   switching is a small edit if done before Phase 2.)

2. **"Force re-running a selected failed/done cell."** #11's wording includes
   *done* cells. I documented the conservative reading — `--select` +
   `--retry-failed` re-queues selected **failed** cells only, and *no* flag
   re-runs a succeeded cell (a wrong result means a code/config change and a
   new run, not a re-queue). If you do want a targeted redo of *succeeded*
   cells, I'd argue for a separate, explicit flag (e.g. `--force`) rather
   than overloading `--retry-failed` — confirm which behavior you intend.

3. **Coordinate key vocabulary.** Per B1/B3, `ref.coords` is keyed by the
   **config author's dimension names**. A stage hardcoding `coords["time"]`
   therefore couples itself to one config's naming. The docs now recommend:
   a stage needing a specific axis takes the dimension name as a bounded
   setting (e.g. `time_dim: str = "time"`), keeping the stage portable and
   the skeleton name-agnostic. Confirm that's the intended resolution — the
   alternatives (coords keyed by *seed roles*, or a reserved conventional
   name like `time`) trade portability differently.

4. **How much auxiliary-handler checking at startup.** B4 says auxiliaries
   are "not dimension-validated at startup." I kept exactly one startup check
   for them: a `dimensions:` mapping that names a **nonexistent config
   dimension** still fails `spout validate` — that's a typo in the config's
   own vocabulary, detectable without judging handler fit. Role completeness,
   type coercion, and data fit are all runtime, per the review. Keep that one
   typo check, or make auxiliary mappings entirely runtime?

---

Design doc note: prompts/3 shipped no updated `RAINSPOUT_DESIGN.md`; the
authoritative spec remains prompts/2's copy **plus** this review response —
if a consolidated design doc lands with prompt 4, I'll diff against prompts/2
as usual.

**Next: Phase 1 implementation** (contracts & registry) per the approved
plan, stopping at the end of the phase — beginning when you've seen this
report (questions #1/#2 ideally answered before config-schema and CLI work,
which is Phases 3–5 territory, so Phase 1 need not wait on them).
