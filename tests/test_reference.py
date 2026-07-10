import pytest

from rainspout.contracts import LazyReference, RainspoutError


def test_get_materializes_once():
    calls = []

    def fetch():
        calls.append(1)
        return [1.0, 2.0]

    ref = LazyReference(fetch)
    assert calls == []  # nothing happens until pulled
    assert ref.get() == [1.0, 2.0]
    assert ref.get() == [1.0, 2.0]
    assert calls == [1]


def test_from_value_wraps_live_object():
    obj = {"a": 1}
    assert LazyReference.from_value(obj).get() is obj


def test_coords_are_read_only():
    ref = LazyReference.from_value([], coords={"day": "2026-01-01", "sensor": "s1"})
    assert ref.coords["sensor"] == "s1"
    with pytest.raises(TypeError):
        ref.coords["sensor"] = "s2"


def test_coords_default_empty():
    assert dict(LazyReference.from_value(1).coords) == {}


def test_window_requires_capability():
    ref = LazyReference.from_value([1, 2, 3])
    assert ref.can_window is False
    with pytest.raises(RainspoutError, match="can_window"):
        ref.window(rows=(0, 1))


def test_window_delegates_when_capable():
    ref = LazyReference.from_value([1, 2, 3], windower=lambda rows: rows)
    assert ref.can_window is True
    assert ref.window(rows=(0, 1)) == (0, 1)
