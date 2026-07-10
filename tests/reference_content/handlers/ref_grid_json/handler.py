"""Metadata-capable save target on the run's own grid (tick x node)."""

import json
from pathlib import Path

from rainspout.contracts import CatalogEntry, Handler, HandlerResources, Meta


class RefGridResources(HandlerResources):
    base_dir: Path


class RefGridJson(Handler):
    """<base_dir>/<tick>_<node>.json holding {"data": [...], "meta": {...}}."""

    name = "ref_grid_json"
    resources_model = RefGridResources
    dimension_roles = ("tick", "node")
    dimension_types = {"tick": int, "node": str}

    def _cell_path(self, coords) -> Path:
        return self.resources.base_dir / f"{coords['tick']}_{coords['node']}.json"

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
        for tick in spec["tick"]:
            for node in spec["node"]:
                if self._cell_path({"tick": tick, "node": node}).exists():
                    yield CatalogEntry(coords={"tick": tick, "node": node})
