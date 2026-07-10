# Response — Gate 2 answers folded in; docs/ built; holding before Phase 1

## The four answers, folded into the docs

1. **Named seed form — done.** CONFIG §6 now defines `seed:` as named entries
   (`seed: {raw: {handler…, resources…, dimensions…}}`) wired `from: raw`;
   seed names share the upstream namespace with stage instance names; exactly
   one entry in v1, a second failing loudly as "multiple seeds not supported
   in v1" — plural shape, singular rule. STAGE §5 and Tutorial 3 updated
   (config, validate-breakage table — which gained a "second seed entry" row —
   dry-run/run transcripts).

2. **`--force-rewrite` — done.** CONFIG §2: `--retry-failed` re-queues failed
   cells only and never touches succeeded ones; deliberately re-running
   succeeded cells (overwriting good output) is `--force-rewrite`, combinable
   with `--select`. Tutorial 3's resume step mentions it. The blunt name is
   documented as intentional.

3. **Coordinate keys via bounded setting — confirmed, already documented**
   (STAGE §7 + what-not-to-do; CONFIG §9). No changes needed beyond what the
   revision already said.

4. **Auxiliary typo check — kept, with the crux stated.** CONFIG §5 now says
   explicitly: the check is config-internal (a dangling reference, same class
   as `from:` naming a nonexistent stage) and **never** requires a config
   dimension name to equal any handler-internal name; names meet roles only
   through explicit mappings, judged only at the seed edge.

## docs/ — finalized documentation now lives at the repo root

Per your mid-turn request, `docs/` is built and is now the **canonical home**
of the contract (matching the Gate 1 repo layout, where `docs/` is a
first-class deliverable):

```
docs/
├── README.md              ← new: plain-words overview, reading map, glossary
├── HANDLER_AUTHORING.md   ┐
├── STAGE_AUTHORING.md     │ finalized contracts, each opening with a
├── CONFIG_AUTHORING.md    │ jargon-free "The short version" section
├── PACKAGE_AUTHORING.md   ┘
└── tutorials/01…03        ← the three runnable tutorials
```

For readability I added a newcomer-oriented README (what Rainspout is in
plain words, a one-paragraph mental model of a run, a glossary translating
every term of art — work item, cell, seed, role, delta, provenance…) and a
"short version" preamble on each authoring doc. The normative contract text
is byte-identical to the approved reports/2 versions — readability was added
*around* the contract, not by rewording it, so no drift was introduced right
before implementation. If you'd like the deep sections themselves rewritten
in plainer language too, say so and I'll do a full pass.

`claude_interactions/reports/2/` keeps its copies as the gate record; from
here on, `docs/` is what implementation and content packages build against.

## Phase 1 — approved but held, at your request

You asked to look over `docs/` before anything moves beyond documentation, so
no implementation code has been written. Phase 1 (contracts & registry)
begins on your go, from the `docs/` contracts exactly as they stand at that
point.

## Design-doc consolidation

Acknowledged: at the end of Phase 1 or 2 I'll produce a consolidated
`RAINSPOUT_DESIGN.md` folding the base doc plus all three response layers
into one source of truth, diffed against prompts/2. Not done this turn —
flagging that it remains open so it isn't lost.
