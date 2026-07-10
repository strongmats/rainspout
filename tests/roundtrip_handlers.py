"""File-backed sample handlers for the data-plane tests.

`RtReadingsCsv` mirrors Tutorial 1 exactly (one CSV per cell, metadata
embedded as a single strippable `# rainspout-meta:` comment line) — running
it here is the machinery-level proof that the tutorial's pattern works.
The variants deliberately misbehave so `assert_roundtrip`'s failure modes
are exercised.
"""

import csv
import io
from datetime import date
from pathlib import Path

from rainspout.contracts import CatalogEntry, Handler, HandlerResources, Meta

META_PREFIX = "# rainspout-meta: "


class CsvResources(HandlerResources):
    base_dir: Path


class RtReadingsCsv(Handler):
    """Metadata-capable: the block rides as one comment line atop the CSV."""

    name = "rt_readings_csv"
    resources_model = CsvResources
    dimension_roles = ("day", "sensor")
    dimension_types = {"day": date, "sensor": str}

    def _cell_path(self, coords) -> Path:
        return self.resources.base_dir / str(coords["day"]) / f"{coords['sensor']}.csv"

    def _load_cell(self, coords):
        text = self._cell_path(coords).read_text()
        first, _, rest = text.partition("\n")
        if first.startswith(META_PREFIX):
            meta = Meta.model_validate_json(first.removeprefix(META_PREFIX))
            body = rest
        else:  # foreign data: fresh provenance
            meta = Meta.fresh(coords=dict(coords))
            body = text
        data = [float(row["value"]) for row in csv.DictReader(io.StringIO(body))]
        return data, meta

    def _save_cell(self, coords, data, meta):
        path = self._cell_path(coords)
        path.parent.mkdir(parents=True, exist_ok=True)
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=["value"])
        writer.writeheader()
        writer.writerows({"value": v} for v in data)
        path.write_text(META_PREFIX + meta.model_dump_json() + "\n" + buf.getvalue())

    def _catalog_cells(self, spec):
        for day in spec["day"]:
            for sensor in spec["sensor"]:
                path = self._cell_path({"day": day, "sensor": sensor})
                if path.exists() and path.stat().st_size > 0:
                    yield CatalogEntry(
                        coords={"day": day, "sensor": sensor},
                        extras={"size_bytes": path.stat().st_size},
                    )


class RtIgnoringCsv(Handler):
    """Metadata-ignoring: conforming, provenance-severing — must still pass."""

    name = "rt_ignoring_csv"
    resources_model = CsvResources
    dimension_roles = ("day", "sensor")
    dimension_types = {"day": date, "sensor": str}

    def _cell_path(self, coords) -> Path:
        return self.resources.base_dir / str(coords["day"]) / f"{coords['sensor']}.csv"

    def _load_cell(self, coords):
        with self._cell_path(coords).open() as f:
            data = [float(row["value"]) for row in csv.DictReader(f)]
        return data, Meta.fresh(coords=dict(coords))

    def _save_cell(self, coords, data, meta):  # drops meta on purpose: allowed
        path = self._cell_path(coords)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["value"])
            writer.writeheader()
            writer.writerows({"value": v} for v in data)

    def _catalog_cells(self, spec):
        for day in spec["day"]:
            for sensor in spec["sensor"]:
                path = self._cell_path({"day": day, "sensor": sensor})
                if path.exists() and path.stat().st_size > 0:
                    yield CatalogEntry(coords={"day": day, "sensor": sensor})


class RtDataAlteringCsv(RtReadingsCsv):
    """Broken on purpose: rounds values on save. Must FAIL the round-trip."""

    name = "rt_data_altering_csv"

    def _save_cell(self, coords, data, meta):
        super()._save_cell(coords, [round(v) for v in data], meta)


class RtMetaAlteringCsv(RtReadingsCsv):
    """Broken on purpose: claims metadata handling but rewrites provenance
    entries on save. Must FAIL the round-trip."""

    name = "rt_meta_altering_csv"

    def _save_cell(self, coords, data, meta):
        mangled = meta.model_copy(
            update={
                "provenance": tuple(
                    entry.model_copy(update={"stage_version": "9.9.9"})
                    for entry in meta.provenance
                )
            }
        )
        super()._save_cell(coords, data, mangled)


def write_example_cell(base_dir: Path, day: str = "2026-01-01", sensor: str = "s1") -> None:
    """Lay down one plain (foreign, metadata-less) example cell."""
    path = base_dir / day / f"{sensor}.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("value\n1.0\n4.0\n1.5\n")
