"""Metadata-capable auxiliary handler: one JSON calibration table per station.

Its role vocabulary ('station') is deliberately unrelated to the run's
dimensions — the consuming stage computes the coordinates it asks for."""

import json
from pathlib import Path

from rainspout.contracts import CatalogEntry, Handler, HandlerResources, Meta


class RefTableResources(HandlerResources):
    base_dir: Path


class RefTableJson(Handler):
    """<base_dir>/<station>.json holding {"data": {...}, "meta": {...}}."""

    name = "ref_table_json"
    resources_model = RefTableResources
    dimension_roles = ("station",)
    dimension_types = {"station": str}

    def _cell_path(self, coords) -> Path:
        return self.resources.base_dir / f"{coords['station']}.json"

    def _load_cell(self, coords):
        payload = json.loads(self._cell_path(coords).read_text())
        raw = payload.get("meta")
        meta = Meta.model_validate(raw) if raw else Meta.fresh(coords=dict(coords))
        return payload["data"], meta

    def _save_cell(self, coords, data, meta):
        path = self._cell_path(coords)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"data": data, "meta": json.loads(meta.model_dump_json())}))

    def _catalog_cells(self, spec):
        for station in spec["station"]:
            if self._cell_path({"station": station}).exists():
                yield CatalogEntry(coords={"station": station})
