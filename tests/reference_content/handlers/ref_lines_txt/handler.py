"""Metadata-IGNORING seed handler: one bare .txt of floats per (tick, node)
cell. Deliberately severs provenance — the conforming-but-discouraged posture
must work end to end."""

from pathlib import Path

from rainspout.contracts import CatalogEntry, Handler, HandlerResources, Meta


class RefLinesResources(HandlerResources):
    base_dir: Path


class RefLinesTxt(Handler):
    """<base_dir>/<node>/<tick>.txt, one float per line. Ignores metadata."""

    name = "ref_lines_txt"
    resources_model = RefLinesResources
    dimension_roles = ("tick", "node")
    dimension_types = {"tick": int, "node": str}

    def _cell_path(self, coords) -> Path:
        return self.resources.base_dir / str(coords["node"]) / f"{coords['tick']}.txt"

    def _load_cell(self, coords):
        lines = self._cell_path(coords).read_text().splitlines()
        return [float(line) for line in lines if line.strip()], Meta.fresh(coords=dict(coords))

    def _save_cell(self, coords, data, meta):  # meta deliberately dropped
        path = self._cell_path(coords)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(f"{value}\n" for value in data))

    def _catalog_cells(self, spec):
        for node in spec["node"]:
            for tick in spec["tick"]:
                path = self._cell_path({"tick": tick, "node": node})
                if path.exists() and path.stat().st_size > 0:
                    yield CatalogEntry(coords={"tick": tick, "node": node})
