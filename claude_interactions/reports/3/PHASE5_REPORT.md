# Phase 5 report — the driver + `spout run`

**Done.** 188 tests passing (18 new), coverage 95.8% against the 90% floor,
ruff + mypy clean. Rainspout now **runs**: Tutorial 3's whole arc — validate,
dry-run, run with failure isolation, resume, retry — is a passing CLI test.
Stopped at the end of the phase.

## The load-bearing decision: where the operational log lives

**The log follows the run definition, never the working directory.**

- Default: `.rainspout/<run.name>.oplog.jsonl` **next to the config file**.
  The config file *is* the identity of a run definition, so anchoring there
  means a resumed run — from any CWD, any shell, any cron entry — always
  finds the history it must subtract. The failure mode you flagged (run N
  can't find run N−1's log, delta breaks, everything reprocesses) is
  structurally impossible under this rule.
- Override: an optional `run.oplog:` config key (relative paths resolve
  against the config's directory). The override lives **in the run
  definition itself**, not on the CLI — a resume can't "forget the flag" and
  silently split the history.
- Corollaries, documented in CONFIG §2: renaming `run.name` deliberately
  starts a fresh history; different configs (e.g. the separate-run
  aggregation pattern) get separate logs, which is exactly right since the
  delta is per-run-definition. `run_id` generation also landed here:
  `<name>-<UTC stamp>-<6-hex>`, unique per invocation, threaded through
  every oplog record and provenance entry.

Both documented (CONFIG_AUTHORING §2, design doc §F) and covered by tests
(default location, relative override, absolute override).

## What was built

**`driver.py`**
- `compute_plan` — the delta, literally: enumerate the (possibly
  `--select`-narrowed) cross-product in iteration order; ask the seed's
  `catalog` what exists; subtract `attempted`. Uncataloged cells are counted
  `missing` and never become work items (the Tutorial 3 corrupt-vs-delete
  distinction, now executable). Flags compose exactly as documented:
  `--retry-failed` adds latest-failed cells, `--force-rewrite` adds
  succeeded ones, `--select` narrows *first* and still respects the log.
- `drive` — retrograde drains one plan; realtime loops plan → drain → sleep
  `poll_frequency` → recompute, forever (or `max_cycles` for tests). One
  subtlety worth flagging: **the re-queue flags apply to the first cycle
  only** — recomputing them every poll would re-run the same failed/succeeded
  cells forever (a poison loop hiding inside flag composition; now a test:
  realtime never re-attempts an attempted cell).
- **Pre-flight** at run start: structural probe on the first cataloged cell
  in the window; probe failure kills the run before any work item; an empty
  catalog skips the probe with a loud notice (legitimate in realtime) —
  both tested.
- **Clean stop**: a `StopFlag` checked between work items and during the
  poll sleep; the CLI wires it to SIGINT/SIGTERM. The in-flight work item
  finishes, the log is flushed (it's append-per-record anyway), the summary
  says `stopped`. The runner's Exception-not-BaseException choice pays off
  here exactly as intended.
- Dry-run: pre-flight + plan, executes nothing, logs nothing (tested: no
  output dir, empty log).

**`spout run`** — `--config`, `--dry-run`, `--select dim=value` (repeatable,
validated with named offenders), `--retry-failed`, `--force-rewrite`; prints
the tutorial's exact vocabulary (`pre-flight: seed raw ✓ (…, probe …)`,
`plan: N work items — X to run, Y done, Z previously failed`,
`[cell] stage ✓ saved → out … FAILED (…) — continuing`,
`done: X succeeded, Y failed`). Exit 0 with isolated failures reported in the
counts (failures are data problems, not run problems); exit 1 only when the
run can't start (validation/pre-flight).

## Done-criterion check (Gate 1 phase table)

Delta/resume/retry-failed tests pass ✓; a mid-run failure kills exactly one
work item ✓ (5 of 6 complete around a corrupt cell); dry-run reports the plan
and executes nothing ✓; realtime picks up data that arrives between polls ✓;
clean stop between work items ✓.

## Remaining phase roadmap to full v1 (as requested)

| # | Phase | Scope | Done criterion |
|---|---|---|---|
| **6** | **CLI complete + package seam** | `spout catalog` (survey via a config's handlers, optional catalog file); `spout setup` (all stages' setup hooks); package-contributed verb mounting via the `rainspout.verbs` entry-point group; `spout test-package` = static conformance shape-check (mandated test names/shapes, bounded-settings lint warning) + the package's pytest/coverage run; `spout build-image` (v1-minimal: Dockerfile from `uv.lock` + installed entry-point packages) | Every verb works against real content; a package-contributed verb mounts under `spout <package> <verb>`; `test-package` fails a package with a missing/nonconforming mandated test and passes a conforming one; `build-image` emits a buildable Dockerfile |
| **7** | **Reference content, example package, CI** | The adversarial reference package under `tests/` (mid-DAG `handler:` dependency + observable setup-hook exercise — no Cython, per Q7); the clean pedagogical example package under `examples/` with entry-point registration; the skeleton's GitHub Actions CI (ruff + mypy + pytest + 90% floor + the stage version-bump check) and the CI template packages copy | Skeleton runs the reference content end-to-end through `spout run`; the example package installs via `uv add --editable` and is discovered purely through entry points; CI green |
| **8** | **Tutorial verification + docs closeout** | Execute all three tutorials *literally, step by step* against the built system; fix skeleton or tutorial wherever reality diverges (each divergence reported); reconcile `docs/` with anything Phases 4–6 taught us | All three tutorials work exactly as written, expected outputs included; zero known doc↔behavior gaps |
| **9** | **Blind-authorability verification** | A separate agent gets scientific code + `docs/` only — no skeleton source, no tutorials-as-crutch beyond what docs include — and must produce a conforming content package; its package is installed and run through the skeleton; every point where it guessed wrong becomes a docs fix | The blind-built package passes `spout test-package` and runs end-to-end via `spout run`; docs amended for every stumble; the inter-repo contract is demonstrated, not assumed |

Ordering rationale: 6 before 7 because the reference/example packages should
be *verified through* `test-package` and verb mounting, not built alongside
them; 8 after 7 because tutorial verification needs the full CLI surface the
tutorials mention; 9 last and separately staffed by design (M.5) — it is the
acceptance test of everything before it. Suggested gate: your review after
Phase 7 (system complete) before the two verification phases.

**STOP — end of Phase 5.** Next on approval: Phase 6.
