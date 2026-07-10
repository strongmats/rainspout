import json
from datetime import date

import pytest

from rainspout.contracts import (
    CatalogEntry,
    Cell,
    Handler,
    HandlerError,
    HandlerResources,
    Meta,
    ProvenanceEntry,
)
from rainspout.contracts.metadata import CatalogDocument
from roundtrip_handlers import RtReadingsCsv, write_example_cell


class MemResources(HandlerResources):
    pass


class GridMem(Handler):
    """In-memory grid-range handler; records every hook call for laziness checks."""

    name = "dp_grid_mem"
    resources_model = MemResources
    dimension_roles = ("i", "j")
    dimension_types = {"i": int, "j": str}
    supports_grid_range = True

    calls: list = []

    def _load_cell(self, coords):
        GridMem.calls.append(dict(coords))
        return coords["i"] * 10, Meta.fresh(coords=dict(coords))

    def _save_cell(self, coords, data, meta):
        pass

    def _catalog_cells(self, spec):
        for i in spec["i"]:
            for j in spec["j"]:
                yield CatalogEntry(coords={"i": i, "j": j})


class SingleMem(Handler):
    name = "dp_single_mem"
    resources_model = MemResources
    dimension_roles = ("i",)
    dimension_types = {"i": int}

    def _load_cell(self, coords):
        if coords["i"] < 0:
            raise ValueError("negative cell")
        return coords["i"], Meta.fresh(coords=dict(coords))

    def _save_cell(self, coords, data, meta):
        if data == "explode":
            raise OSError("disk full")

    def _catalog_cells(self, spec):
        yield "not-an-entry"


class WindowedMem(Handler):
    name = "dp_windowed_mem"
    resources_model = MemResources
    dimension_roles = ("i",)
    dimension_types = {"i": int}
    supports_windowed_read = True

    def _load_cell(self, coords, window=None):
        return {"window": dict(window) if window else None}, Meta.fresh(coords=dict(coords))

    def _save_cell(self, coords, data, meta):
        pass

    def _catalog_cells(self, spec):
        return iter(())


class BadReturnMem(Handler):
    name = "dp_bad_return_mem"
    resources_model = MemResources
    dimension_roles = ("i",)
    dimension_types = {"i": int}

    def _load_cell(self, coords):
        return 42  # not a (data, meta) pair

    def _save_cell(self, coords, data, meta):
        pass

    def _catalog_cells(self, spec):
        return iter(())


# -- load ---------------------------------------------------------------------


def test_load_single_cell_yields_one_cell():
    handler = GridMem({})
    cells = list(handler.load({"i": (3,), "j": ("a",)}))
    assert cells == [Cell(coords={"i": 3, "j": "a"}, data=30, meta=cells[0].meta)]
    assert cells[0].meta.coords == {"i": "3", "j": "a"}


def test_load_is_lazy_per_cell():
    GridMem.calls.clear()
    handler = GridMem({})
    iterator = handler.load({"i": (1, 2, 3), "j": ("a",)})
    assert GridMem.calls == []  # nothing loaded yet
    first = next(iterator)
    assert first.data == 10
    assert GridMem.calls == [{"i": 1, "j": "a"}]  # exactly one cell materialized


def test_load_iterates_product_in_role_order():
    handler = GridMem({})
    coords = [cell.coords for cell in handler.load({"i": (1, 2), "j": ("a", "b")})]
    assert coords == [
        {"i": 1, "j": "a"},
        {"i": 1, "j": "b"},
        {"i": 2, "j": "a"},
        {"i": 2, "j": "b"},
    ]


def test_multi_cell_spec_on_non_range_handler_fails_eagerly():
    handler = SingleMem({})
    with pytest.raises(HandlerError, match="supports_grid_range.*load_one"):
        handler.load({"i": (1, 2)})  # raises at call, not at first next()


def test_spec_must_cover_roles_exactly():
    handler = GridMem({})
    with pytest.raises(HandlerError, match="missing.*j"):
        handler.load({"i": (1,)})
    with pytest.raises(HandlerError, match="unknown.*k"):
        handler.load({"i": (1,), "j": ("a",), "k": (1,)})


def test_scalar_spec_value_rejected():
    handler = GridMem({})
    with pytest.raises(HandlerError, match="tuple of one"):
        handler.load({"i": 1, "j": ("a",)})


def test_empty_spec_value_rejected():
    handler = GridMem({})
    with pytest.raises(HandlerError, match="non-empty"):
        handler.load({"i": (), "j": ("a",)})


def test_load_hook_error_wrapped_with_handler_and_coordinate():
    handler = SingleMem({})
    with pytest.raises(HandlerError, match="dp_single_mem.*-1.*negative cell"):
        handler.load_one({"i": -1})


def test_load_cell_must_return_pair():
    handler = BadReturnMem({})
    with pytest.raises(HandlerError, match=r"must return \(data, meta\)"):
        handler.load_one({"i": 1})


# -- load_one -------------------------------------------------------------------


def test_load_one_returns_data_meta():
    handler = SingleMem({})
    data, meta = handler.load_one({"i": 7})
    assert data == 7
    assert isinstance(meta, Meta)


def test_load_one_coords_must_cover_roles():
    handler = GridMem({})
    with pytest.raises(HandlerError, match="coords must cover exactly"):
        handler.load_one({"i": 1})


# -- windowing --------------------------------------------------------------------


def test_window_requires_capability():
    handler = SingleMem({})
    with pytest.raises(HandlerError, match="supports_windowed_read"):
        handler.load_one({"i": 1}, window={"rows": (0, 10)})
    with pytest.raises(HandlerError, match="supports_windowed_read"):
        handler.load({"i": (1,)}, window={"rows": (0, 10)})


def test_window_passed_through_to_hook():
    handler = WindowedMem({})
    data, _ = handler.load_one({"i": 1}, window={"rows": (0, 10)})
    assert data == {"window": {"rows": (0, 10)}}
    data, _ = handler.load_one({"i": 1})
    assert data == {"window": None}


# -- save --------------------------------------------------------------------------


def test_save_rejects_multi_cell_spec():
    handler = GridMem({})
    with pytest.raises(HandlerError, match="single-cell"):
        handler.save({"i": (1, 2), "j": ("a",)}, 0, Meta.fresh())


def test_save_requires_meta_block():
    handler = SingleMem({})
    with pytest.raises(HandlerError, match="Meta"):
        handler.save({"i": (1,)}, 0, {"not": "a meta"})


def test_save_hook_error_wrapped():
    handler = SingleMem({})
    with pytest.raises(HandlerError, match="dp_single_mem.*save failed.*disk full"):
        handler.save({"i": (1,)}, "explode", Meta.fresh())


# -- catalog ------------------------------------------------------------------------


def test_catalog_entries_validated():
    handler = SingleMem({})
    with pytest.raises(HandlerError, match="must yield CatalogEntry"):
        list(handler.catalog({"i": (1,)}))


def test_catalog_write_path_produces_validated_document(tmp_path):
    handler = GridMem({})
    out = tmp_path / "catalog.json"
    entries = list(handler.catalog({"i": (1, 2), "j": ("a",)}, write_path=out))
    assert len(entries) == 2
    document = CatalogDocument.model_validate_json(out.read_text())
    assert document.handler == "dp_grid_mem"
    assert document.roles == ("i", "j")
    assert [entry.coords for entry in document.entries] == [
        {"i": "1", "j": "a"},
        {"i": "2", "j": "a"},
    ]
    json.loads(out.read_text())  # plain JSON on disk


def test_file_handler_catalog_surveys_only_asked_window(tmp_path):
    write_example_cell(tmp_path, "2026-01-01", "s1")
    write_example_cell(tmp_path, "2026-01-02", "s1")
    handler = RtReadingsCsv({"base_dir": tmp_path})
    entries = list(handler.catalog({"day": (date(2026, 1, 1),), "sensor": ("s1", "s2")}))
    assert [entry.coords for entry in entries] == [{"day": date(2026, 1, 1), "sensor": "s1"}]
    assert entries[0].extras["size_bytes"] > 0


# -- Meta ---------------------------------------------------------------------------


def test_meta_fresh_canonicalizes_coords():
    meta = Meta.fresh(coords={"day": date(2026, 1, 3), "sensor": "s2"})
    assert meta.coords == {"day": "2026-01-03", "sensor": "s2"}
    assert meta.provenance == ()


def test_meta_with_entry_appends_in_order():
    entry1 = ProvenanceEntry(
        stage_name="a", stage_version="1", code_hash="x", settings_used={},
        timestamp="2026-01-01T00:00:00Z",
    )
    entry2 = entry1.model_copy(update={"stage_name": "b"})
    meta = Meta.fresh().with_entry(entry1).with_entry(entry2)
    assert [entry.stage_name for entry in meta.provenance] == ["a", "b"]


def test_meta_survives_json_roundtrip_exactly():
    entry = ProvenanceEntry(
        stage_name="smooth", stage_version="1.0.0", code_hash="abc123",
        settings_used={"window_len": 3, "method": "mean"},
        timestamp="2026-01-01T06:00:00Z", warnings=("clipped",),
    )
    meta = Meta.fresh(coords={"day": date(2026, 1, 1)}, run_id="run-42").with_entry(entry)
    assert Meta.model_validate_json(meta.model_dump_json()) == meta
