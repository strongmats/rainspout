"""Tutorial 1's handler, verbatim: one CSV per (day, sensor) cell, metadata
embedded as a single strippable comment line."""

import csv
import io
from datetime import date
from pathlib import Path

from rainspout.contracts import (
    CatalogEntry,
    Coords,
    Handler,
    HandlerResources,
    Meta,
)

META_PREFIX = "# rainspout-meta: "  # one strippable comment line, first in file


class ReadingsLocalCsvResources(HandlerResources):
    base_dir: Path  # DirectoryPath once data exists; Path so save can create it
    # unbounded: the root of a tree the user chooses


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
    supports_windowed_read = False  # CSV can't slice without a full read

    # -- private layout ------------------------------------------------------
    def _cell_path(self, coords: Coords) -> Path:
        return self.resources.base_dir / str(coords["day"]) / f"{coords['sensor']}.csv"

    # -- the three hooks -----------------------------------------------------
    def _load_cell(self, coords: Coords):
        text = self._cell_path(coords).read_text()
        first, _, rest = text.partition("\n")
        if first.startswith(META_PREFIX):  # a file we saved ourselves
            meta = Meta.model_validate_json(first.removeprefix(META_PREFIX))
            body = rest
        else:  # foreign data: fresh provenance
            meta = Meta.fresh(coords=dict(coords))
            body = text
        data = [float(row["value"]) for row in csv.DictReader(io.StringIO(body))]
        return data, meta

    def _save_cell(self, coords: Coords, data, meta: Meta) -> None:
        path = self._cell_path(coords)
        path.parent.mkdir(parents=True, exist_ok=True)
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=["value"])
        writer.writeheader()
        writer.writerows({"value": v} for v in data)
        path.write_text(META_PREFIX + meta.model_dump_json() + "\n" + buf.getvalue())

    def _catalog_cells(self, spec):
        for day in spec["day"]:  # only the asked window
            for sensor in spec["sensor"]:
                path = self._cell_path({"day": day, "sensor": sensor})
                if path.exists() and path.stat().st_size > 0:
                    yield CatalogEntry(
                        coords={"day": day, "sensor": sensor},
                        extras={"size_bytes": path.stat().st_size},
                    )
