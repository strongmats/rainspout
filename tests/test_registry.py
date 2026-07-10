import pytest

from rainspout import registry
from rainspout.errors import DefinitionError, RegistrationError


class Alpha:
    pass


class Beta:
    pass


def test_register_and_get_roundtrip():
    registry.register("stage", "alpha", Alpha)
    assert registry.get("stage", "alpha") is Alpha


def test_axes_are_independent():
    registry.register("stage", "alpha", Alpha)
    registry.register("handler", "alpha", Beta)  # same name, different axis: fine
    assert registry.get("stage", "alpha") is Alpha
    assert registry.get("handler", "alpha") is Beta


def test_duplicate_name_names_both_parties():
    registry.register("stage", "alpha", Alpha)
    with pytest.raises(RegistrationError, match="Alpha.*Beta"):
        registry.register("stage", "alpha", Beta)


def test_reregistering_same_class_is_idempotent():
    registry.register("stage", "alpha", Alpha)
    registry.register("stage", "alpha", Alpha)  # module imported twice
    assert registry.get("stage", "alpha") is Alpha


def test_unknown_name_lists_known_names():
    registry.register("stage", "alpha", Alpha)
    with pytest.raises(DefinitionError, match="unknown stage 'gamma'.*alpha"):
        registry.get("stage", "gamma")


def test_unknown_axis_reports_none_registered():
    with pytest.raises(DefinitionError, match="none registered"):
        registry.get("verb", "anything")


def test_names_sorted():
    registry.register("stage", "zeta", Alpha)
    registry.register("stage", "alpha", Beta)
    assert registry.names("stage")[:2] != ("zeta", "alpha")
    assert list(registry.names("stage")) == sorted(registry.names("stage"))
