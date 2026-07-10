# Rainspout

A domain-agnostic frame for building scientific data-processing pipelines.
Rainspout contains no science of its own: content packages ship the stages
(processing steps) and handlers (storage adapters); one YAML config describes
a run; the `spout` command executes it, tracking what has already been done.

**Start with [`docs/README.md`](docs/README.md)** — the documentation is the
API: you can build a content package from the authoring guides alone, without
reading this repository's source.

## Development

```
uv sync            # create the environment
uv run pytest      # tests (coverage floor enforced)
uv run ruff check  # lint
uv run mypy        # types
```
