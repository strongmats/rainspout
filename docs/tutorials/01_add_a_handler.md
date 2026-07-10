# Tutorial 1 — Add a handler

*This tutorial doubles as an acceptance test: every step is runnable, and the
final step's expected output is stated. If a step doesn't behave as written,
file a bug against the skeleton or this tutorial.*

We'll build `readings_local_csv`: one CSV file per (day, sensor) cell under a
base directory. Prerequisite: a package skeleton as in PACKAGE_AUTHORING §2
(here: `my-package` with import name `my_package`), with `rainspout` installed.

## Step 1 — Make the handler directory

```
src/my_package/handlers/readings_local_csv/
├── __init__.py
├── handler.py
├── example_data/
└── test_roundtrip.py
```

## Step 2 — Write the handler

`handler.py` — as always, only the `rainspout.contracts` import is the
framework; `csv`, `io`, `datetime`, and `pathlib` are *this handler's* domain
choices (docs README, "How code is shown"):

```python
import csv, io
from datetime import date
from pathlib import Path

from rainspout.contracts import (
    Handler, HandlerResources, Coords, Meta, CatalogEntry,
)

META_PREFIX = "# rainspout-meta: "     # one strippable comment line, first in file


class ReadingsLocalCsvResources(HandlerResources):
    base_dir: Path                     # DirectoryPath once data exists; Path so
                                       # save can create it  # unbounded: root of tree


class ReadingsLocalCsv(Handler):
    """One CSV per cell: <base_dir>/<day>/<sensor>.csv, list-of-floats column
    'value'. Metadata-capable: the block is embedded as a single comment line
    ('# rainspout-meta: {...}') at the top of the file — strip lines starting
    with '#' and what remains is plain CSV."""

    name = "readings_local_csv"
    resources_model = ReadingsLocalCsvResources
    dimension_roles = ("day", "sensor")
    dimension_types = {"day": date, "sensor": str}
    supports_grid_range = False
    supports_windowed_read = False     # CSV can't slice without a full read

    # -- private layout ------------------------------------------------------
    def _cell_path(self, coords: Coords) -> Path:
        return self.resources.base_dir / str(coords["day"]) / f"{coords['sensor']}.csv"

    # -- the three hooks -----------------------------------------------------
    def _load_cell(self, coords: Coords) -> tuple[object, Meta]:
        text = self._cell_path(coords).read_text()
        first, _, rest = text.partition("\n")
        if first.startswith(META_PREFIX):          # a file we saved ourselves
            meta = Meta.model_validate_json(first.removeprefix(META_PREFIX))
            body = rest
        else:                                      # foreign data: fresh provenance
            meta = Meta.fresh(coords=coords)
            body = text
        data = [float(row["value"]) for row in csv.DictReader(io.StringIO(body))]
        return data, meta

    def _save_cell(self, coords: Coords, data: object, meta: Meta) -> None:
        path = self._cell_path(coords)
        path.parent.mkdir(parents=True, exist_ok=True)
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=["value"])
        w.writeheader()
        w.writerows({"value": v} for v in data)
        path.write_text(META_PREFIX + meta.model_dump_json() + "\n" + buf.getvalue())

    def _catalog_cells(self, spec):
        for day in spec["day"]:                    # only the asked window
            for sensor in spec["sensor"]:
                path = self._cell_path({"day": day, "sensor": sensor})
                if path.exists() and path.stat().st_size > 0:
                    yield CatalogEntry(
                        coords={"day": day, "sensor": sensor},
                        extras={"size_bytes": path.stat().st_size},
                    )
```

Note what we did **not** write: an `__init__` (forbidden), connection handling
(per-transaction file opens), any parsing of the handler's own name, any
knowledge of what the user's config will call these dimensions — we only speak
our two roles — or a **second file**: a cell is exactly one CSV, and the
metadata block rides inside it as one clearly delimited, strippable line
(HANDLER_AUTHORING §11). Any CSV consumer that skips `#`-comments (or a
one-line `grep -v '^#'`) reads pure data. We *could* have written a
metadata-ignoring handler instead — conforming, but it severs the provenance
chain, so we didn't.

## Step 3 — Ship example data

```
example_data/2026-01-01/s1.csv
```

```csv
value
1.0
4.0
1.5
```

Tiny, committed, and exactly the format `_load_cell` reads — it documents the
layout better than prose.

## Step 4 — The mandated round-trip test

`test_roundtrip.py`:

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

This loads the example cell, saves it to `tmp_path`, reloads it, asserts
equality (float-tolerant), and catalogs `tmp_path` asserting the cell is
reported — with the metadata block surviving intact.

## Step 5 — Register and verify

Add one import to `src/my_package/components.py`:

```python
from my_package.handlers.readings_local_csv import handler as _  # noqa: F401
```

(The `# noqa: F401` is load-bearing: linters see collector imports as unused
and will otherwise auto-remove them, silently unregistering your handler —
PACKAGE_AUTHORING §4.)

Then:

```
$ pytest src/my_package/handlers/readings_local_csv/ -q
1 passed

$ spout test-package my_package
components: readings_local_csv ✓
1 passed
```

(The first line is the static conformance check; the `1 passed` after it is
your package's own test suite, run for real.)

Both green means: your handler registers, validates, round-trips its own
example data, and catalogs correctly. It is now wireable from any config —
which is Tutorial 3.
