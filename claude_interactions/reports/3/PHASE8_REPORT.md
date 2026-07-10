# Phase 8 report — literal tutorial verification

**Done.** All three tutorials were executed step for step against the built
system — in a **fresh virtual environment**, with a **new `my-package`**
created exactly per PACKAGE_AUTHORING §2/§4 and every tutorial code block
typed verbatim. Every stated expected output was compared against reality;
each divergence was fixed on whichever side was wrong. Final state: 228 tests
passing (3 new), coverage 93.73% against the 90% floor, ruff + mypy clean —
and a clean-room replay of Tutorial 3 whose config was **extracted from the
doc's own YAML block** reproduces every stated output exactly.

## Methodology

1. `uv venv` in scratch; `rainspout` installed editable; `my-package` built
   from PACKAGE_AUTHORING alone (layout §2, pyproject + entry points §4).
2. Tutorial 1 and Tutorial 2 code blocks copied byte-for-byte; every command
   in the tutorials run as written; outputs diffed against the stated ones.
3. Tutorial 3: raw grid laid out, one cell corrupted as instructed, all eight
   steps executed — including all **seven rows of the breakage table**, the
   dry-run, failure isolation, resume, `--retry-failed`, `--select`
   narrowing/subtraction, `--force-rewrite`, their composition, and realtime
   mode (background run, fresh CSV dropped mid-run and picked up on the next
   poll cycle, SIGINT → `(stopped cleanly)`).
4. Where a fix was applied, the affected step was re-run to confirm the doc
   and the system now agree.

## Skeleton fixes (reality was wrong)

1. **The documented dependency pin was unsatisfiable.** PACKAGE_AUTHORING §4
   tells authors `dependencies = ["rainspout>=1,<2"]` — and the whole v1
   stability commitment is phrased against that range — but the skeleton
   declared `version = "0.1.0"`, so a reader's package failed to install.
   The example package had quietly dodged its own doc with a bare
   `rainspout`. Fixed: **skeleton version is now 1.0.0** (the system is
   complete to v1 scope; the docs are the contract), and the example package
   now uses the documented pin. *This is a version-number decision — flag it
   at review if you'd rather hold 0.x until Phase 9 closes; the alternative
   is weakening the documented pin.*
2. **Breakage-table row 3 didn't produce its promised error.** Deleting the
   whole `data:` entry leaves `dependencies:` parsing as YAML `None`, and the
   reader got `key 'stages.smooth.dependencies': Input should be a valid
   dictionary` instead of the promised *missing dependency `data`*. Fixed:
   emptied mapping keys (`dependencies:`, `settings:`, `resources:`,
   `handlers:`) now read as the empty mapping they look like, so validation
   reaches the real check — `stage 'smooth' is missing dependencies:
   ['data']`. Three regression tests added.
3. **Breakage-table row 5 didn't name its owner.** A seed pointed at a bogus
   handler said `unknown handler 'bogus_handler' (known: …)` without naming
   `seed 'raw'` — against both the table and the named-offender rule.
   Fixed: registry lookups now carry their owner (`seed 'raw': unknown
   handler …`, `handler instance 'out': …`, `stage instance 'smooth':
   unknown stage …`). Existing tests strengthened to assert the prefixes.
4. **Runtime handler errors were unreadable.** The corrupt cell failed with
   ``load failed at {'day': datetime.date(2026, 1, 3), 'sensor': 's2'}:
   'value'`` — a raw dict repr and a bare `KeyError` payload. Fixed: load,
   save, and pre-flight errors now print canonical coordinates and the
   exception type — `load failed at day=2026-01-03, sensor=s2: KeyError:
   'value'`.

## Tutorial/doc fixes (the docs were wrong)

5. **Tutorials 1–2, Step 5:** the collector-import snippets lacked the
   `# noqa: F401` that PACKAGE §4 (post-Phase-7 ruff incident) mandates —
   the tutorials were teaching the exact mistake the docs warn about. Added,
   with the one-line why.
6. **Tutorials 1–2 expected `test-package` output** didn't match the CLI
   (invented `✓ (conformance + round-trip)` annotation; wrong component
   order — the report lists stages before handlers; missing the real pytest
   line). Updated to the true output.
7. **Tutorial 2, Step 6:** the check names the stage *directory*, not the
   bare stage name; and it diffs **committed** changes against the base ref —
   a stumble I hit myself (uncommitted edits are invisible to it, exactly as
   in CI). Both now stated, plus the local invocation
   (`python -m rainspout.devtools.version_bump --base main`).
8. **Tutorial 3 used absolute `/data/...` paths** most readers cannot write.
   Switched to relative `./data/...` from a chosen working directory, with an
   honest note: resource values are the handler's to interpret, so this
   handler resolves relative paths against the invocation directory — unlike
   `run.oplog:`, which the skeleton anchors to the config file. The same
   note added to CONFIG_AUTHORING §5, with "use absolute paths in configs
   you run from more than one place."
9. **Tutorial 3 output blocks reconciled with the real CLI**: the probe line
   (`probe day=2026-01-01, sensor=s1`), work-item prefixes in canonical
   `[day=…|sensor=…]` form, the failed line's true shape, and complete
   `done: N succeeded, M failed` lines. The old text showed a per-item
   `raw ✓` element that does not exist — the seed loads *lazily*, when the
   first stage pulls it — so a corrupt seed cell surfaces on the stage's
   line with the handler named inside the error. The tutorial now says
   exactly that. Resume/retry blocks updated (plan line included; oplog
   location cross-referenced).

## Verified exactly as written (no change needed)

- Tutorial 1: handler code, example data, round-trip test — `1 passed`;
  conformance ✓.
- Tutorial 2: science/stage/test split — `3 passed`; `run_stage` semantics
  as described.
- Tutorial 3: `spout validate` line **character-for-character**; five of
  seven breakage rows named their offenders precisely (rows 3 and 5 fixed
  above, then re-verified); dry-run plan line; failure isolation (exactly one
  work item dead, five saved); the embedded `# rainspout-meta:` provenance
  line with version, settings, timestamp, code hash; resume
  (`0 to run, 5 done, 1 previously failed`); `--retry-failed` (1 re-queued,
  succeeded); `--select` narrowing and subtraction; `--force-rewrite`
  (2 succeeded cells redone under `--select`); retry×select composition;
  realtime (initial drain skips the missing cell, fresh CSV picked up on the
  next poll, Ctrl-C → `(stopped cleanly)`, nothing re-done); oplog at
  `.rainspout/smooth_demo.oplog.jsonl` next to the config.

## Design doc

§M build status brought current (Phases 3–8, version 1.0.0 decision); §N
decision record extended with the Phase 8 rows.

## Addendum — conditional settings (discriminated unions), on request

Question raised at the gate: does the setup support conditional settings —
e.g. a `method` field that is `{kind: mean}` or `{kind: weighted, weights:
[...]}` as a Pydantic discriminated union?

**Verified: the pattern works end to end with no skeleton changes** — proven
live with a probe stage in the walkthrough package. Nested YAML `settings:`
blocks flow through the real constructor; named offenders compose with the
union machinery (`setting 'method': Input tag 'quadratic' … expected tags:
'mean', 'weighted'`; failures inside an arm get dotted paths —
`setting 'method.weighted.weights': Field required`); `run_stage`,
`EXAMPLE_SETTINGS`, and conformance accept nested dicts; provenance records
the fully resolved structure, defaults included.

Two gaps found and fixed:

1. **The bounded-settings lint had a nesting blind spot** — it inspected only
   top-level bare-scalar fields, so an unbounded `scale: float` planted
   inside the `weighted` arm drew no warning. `_unbounded_warnings` now
   recurses through union arms (both `Union[…]` and `X | Y` spellings),
   plain nested models, and containers, naming the arm in the warning
   (`field 'method[WeightedMethod].scale' has an unbounded float domain`),
   with cycle protection for self-referential models. Three regression tests.
2. **STAGE_AUTHORING §4 was silent on the pattern.** Added a "conditional
   settings" subsection with the canonical example, the two carried-over
   rules — the bounded rule applies to every field of every arm (the lint
   now enforces it), and nested settings models should declare
   `model_config = ConfigDict(frozen=True)`, since frozen-ness is per-model
   and an unfrozen arm mutated mid-run would make provenance drift from the
   config — plus the §11 self-check line. The frozen recommendation was
   verified live (nested mutation raises ValidationError).

Gates after the addendum: **231 tests passing (3 new), coverage 93.85%,
ruff + mypy clean.**

## Addendum 2 — code-display convention (framework vs. example; template-then-walkthrough)

Two presentation requests at the gate, applied across `docs/` (contract
content unchanged):

1. **Framework vs. example, made explicit everywhere code is shown.** The
   docs README gains a "How code is shown in these documents" section
   defining the convention once: *templates* (required shape, placeholder
   names, each line commented `contract:` or `yours:`) vs. *worked examples*
   (one concrete made-up domain — daily CSV sensor readings — whose dates,
   sensors, and formats are never the framework's). Plus the two import
   rules that make the boundary visible in any snippet: only
   `rainspout.contracts`/`rainspout.testing` are Rainspout; everything else
   (`datetime`, `csv`, `pathlib`, client libraries) is the example's domain;
   `pydantic` is contract-adjacent (that you declare bounds with it is the
   contract, which bounds is yours).
2. **Template first, then a worked example, with a line-by-line
   walkthrough.** HANDLER_AUTHORING §3 and STAGE_AUTHORING §2 are
   restructured: an annotated generic template (`MyHandler`/`MyStage`, every
   line marked contract/yours), a prose walkthrough explaining what each
   line does and who calls it, then the previous concrete skeleton reframed
   as the worked example with its domain choices called out. The mandated
   test templates (HANDLER §12, STAGE §11) got the same per-line
   contract/yours annotations; CONFIG_AUTHORING states the split for YAML
   (key names = contract, names and values = example's); PACKAGE_AUTHORING
   §4 marks the entry-point group names as the contract and `my_package` as
   placeholder; Tutorials 1–2 note which imports are framework vs. domain at
   the first code block.

Docs-only change; no gates affected.

**STOP — end of Phase 8.** Remaining: **Phase 9**, blind-authorability
verification (a separate agent gets science code + `docs/` only — no skeleton
source, no tutorials-as-crutch beyond what docs/ contains — and must build
and run a conforming package; every stumble becomes a docs fix).
