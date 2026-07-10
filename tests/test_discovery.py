from types import SimpleNamespace

import pytest

from rainspout import discovery
from rainspout.errors import DefinitionError, RegistrationError


class FakeEntryPoint:
    def __init__(self, name, loader):
        self.name = name
        self.value = f"{name}.components"
        self._loader = loader

    def load(self):
        return self._loader()


def fake_metadata(monkeypatch, entry_points):
    def fake_entry_points(group):
        return entry_points if group == discovery.GROUP else []

    monkeypatch.setattr(discovery, "metadata", SimpleNamespace(entry_points=fake_entry_points))


def test_discovers_every_entry_point(monkeypatch):
    imported = []
    fake_metadata(
        monkeypatch,
        [
            FakeEntryPoint("pkg_a", lambda: imported.append("a")),
            FakeEntryPoint("pkg_b", lambda: imported.append("b")),
        ],
    )
    assert discovery.discover_components() == ("pkg_a", "pkg_b")
    assert imported == ["a", "b"]


def test_no_entry_points_is_fine(monkeypatch):
    fake_metadata(monkeypatch, [])
    assert discovery.discover_components() == ()


def test_registration_failure_names_the_package(monkeypatch):
    def explode():
        raise RegistrationError("duplicate handler name 'x'")

    fake_metadata(monkeypatch, [FakeEntryPoint("bad_pkg", explode)])
    with pytest.raises(DefinitionError, match="bad_pkg.*duplicate handler name 'x'"):
        discovery.discover_components()
