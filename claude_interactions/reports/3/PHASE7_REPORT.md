# Phase 7 report — reference content, example package, CI

**Done.** 225 tests passing (17 new), coverage 93.7% against the 90% floor,
ruff + mypy clean. The system is now **complete to v1 scope** — this is the
suggested review-gate point from the roadmap, before the two verification
phases. Stopped at the end of the phase.

## 1. The adversarial reference package (`tests/reference_content/`)

Machinery-proving on purpose, exercising the paths nothing else stresses
together:

- **`ref_lines_txt`** — a metadata-IGNORING seed handler (bare .txt of
  floats): the conforming-but-provenance-severing posture, run end to end.
- **`ref_table_json`** — the auxiliary calibration handler whose role
  vocabulary (`station`) is deliberately unrelated to the run's dimensions.
- **`ref_grid_json`** — a metadata-capable save target on the run's grid.
- **`ref_snip`** — the coordinate-AWARE stage: reads its tick from
  `ref.coords` via the dimension-name-as-bounded-setting pattern.
- **`ref_enrich`** — both required exercises in one stage: the **mid-DAG
  auxiliary `handler:` dependency** called with stage-computed coordinates in
  the handler's own vocabulary, and the **observable setup hook** — `run()`
  refuses to work unless `setup()` fired, so a broken setup-before-work
  ordering fails the end-to-end run loudly (plus a direct test that trips the
  guard by bypassing `prepare_stages`).

The headline test runs the whole pipeline **through the CLI** (`spout
validate` → `spout run` on a 3×2 grid), asserts the value math through both
stages, the fresh-start provenance (severed by the ignoring seed; exactly
`[ref_snip, ref_enrich]` with settings recorded), canonical coords, and
resume (`0 to run, 6 done`). The reference package is also **itself
conforming**: `spout test-package reference_content --static-only` passes all
five components — and its mandated tests run as part of the skeleton's own
suite.

## 2. The pedagogical example package (`examples/rainspout-example/`)

Tutorials 1 and 2 **verbatim** (`readings_local_csv` with the embedded
`# rainspout-meta:` line; `smooth_readings` with `science.py`), plus Tutorial
3's config, a `pyproject.toml` with both entry-point groups, and a
package-contributed verb (`spout rainspout_example make-data`) that generates
sample readings. Verified the full seam **by actually installing it**:

```
$ uv pip install -e examples/rainspout-example
$ spout catalog                      → stages: smooth_readings
                                       handlers: readings_local_csv
$ spout rainspout_example make-data --base-dir ./data/raw   → wrote 6 cells
$ spout run --config …/example_run.yml                      → done: 6 succeeded, 0 failed
   (outputs carry the embedded metadata line with run_id + provenance)
$ spout test-package rainspout_example --static-only        → both components ✓
$ uv pip uninstall rainspout-example
$ spout catalog                      → (none registered)
```

Zero imports anywhere — discovery is entry points alone, exactly the
PACKAGE_AUTHORING promise. A skeleton test additionally guards the example's
conformance against regressions (without needing installation).

## 3. CI

- **`.github/workflows/ci.yml`** — uv sync → ruff → mypy → pytest (the 90%
  floor rides in `pyproject` addopts) → the stage **version-bump check** on
  PRs, diffing against the base branch.
- **`rainspout.devtools.version_bump`** — the check is shipped *inside*
  rainspout (`python -m rainspout.devtools.version_bump --base origin/main`)
  so package CI runs the identical logic. It applies the same code/test
  boundary as the provenance hash (tests/fixtures/example_data exempt).
  Tested against real temporary git repos: code change without bump fails
  naming the stage directory; with bump passes; test/fixture-only changes
  exempt; a NEW code file without a bump fails (the case the Phase 4 review
  asked to pin down, now enforced at CI level too).
- **`docs/templates/package_ci.yml`** — the template packages copy: ruff,
  mypy, `spout test-package <pkg>` (conformance + suite), the coverage floor,
  and the same version-bump module.

## A real bug the phase caught (docs amended)

Running ruff's auto-fix over the repo **deleted the collector-module
imports** as "unused" — silently unregistering every component: the exact
silent-failure mode PACKAGE §4 warns about, triggered by a linter rather than
a human. Fixed with `# noqa: F401` in both collectors, and PACKAGE §4 now
tells authors to do the same (linters *will* auto-remove registration imports
otherwise). This is precisely the class of finding the verification phases
exist to surface; one arrived early.

## Status at the suggested review gate

Phases 1–7 delivered: contracts, validation, data plane, runner, driver, full
CLI, package seam, reference + example content, CI. Remaining per the
roadmap: **Phase 8** (literal tutorial verification) and **Phase 9**
(blind-authorability verification). The consolidated design doc §M updated
status will be refreshed when the verification phases close.

**STOP — end of Phase 7.** Per the roadmap, this is the natural point for
your review of the complete system before the verification phases begin.
