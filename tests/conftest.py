import pytest

from rainspout import registry


@pytest.fixture(autouse=True)
def isolated_registry():
    """Snapshot and restore the registry around every test, so tests can
    define throwaway components freely without cross-contamination."""
    saved = {axis: dict(mapping) for axis, mapping in registry._AXES.items()}
    yield
    registry._AXES.clear()
    registry._AXES.update({axis: dict(mapping) for axis, mapping in saved.items()})
