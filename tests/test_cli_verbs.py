from datetime import date

import typer
import yaml
from typer.testing import CliRunner

import runner_components  # noqa: F401  (importing registers the components)
from fake_package import write_fake_package
from rainspout.cli._mount import mount_package_verbs
from rainspout.cli.main import app
from rainspout.contracts.metadata import CatalogDocument
from roundtrip_handlers import write_example_cell

runner = CliRunner()


def write_run_config(tmp_path):
    src = tmp_path / "raw"
    write_example_cell(src, "2026-01-01", "s1")
    write_example_cell(src, "2026-01-02", "s1")
    cfg = {
        "run": {"name": "verbs_demo", "mode": "retrograde"},
        "dimensions": {"day": [date(2026, 1, 1), date(2026, 1, 2)], "sensor": ["s1"]},
        "iteration": {"order": ["day", "sensor"]},
        "seed": {
            "raw": {
                "handler": "rt_readings_csv",
                "resources": {"base_dir": str(src)},
                "dimensions": {"day": "day", "sensor": "sensor"},
            }
        },
        "handlers": {
            "out": {
                "handler": "rt_readings_csv",
                "resources": {"base_dir": str(tmp_path / "out")},
                "dimensions": {"day": "day", "sensor": "sensor"},
            },
            "aux": {
                "handler": "rt_readings_csv",
                "resources": {"base_dir": str(src)},
            },
        },
        "stages": {
            "scale": {
                "stage": "run_setup_probe",
                "dependencies": {"data": {"from": "raw"}},
                "settings": {},
                "save": {"handler": "out"},
            }
        },
    }
    path = tmp_path / "run.yml"
    path.write_text(yaml.safe_dump(cfg))
    return path


# -- spout catalog ---------------------------------------------------------------


def test_catalog_without_config_lists_registry():
    result = runner.invoke(app, ["catalog"])
    assert result.exit_code == 0, result.output
    assert "stages: " in result.output
    assert "handlers: " in result.output
    assert "rt_readings_csv" in result.output


def test_catalog_surveys_seed_window(tmp_path):
    path = write_run_config(tmp_path)
    result = runner.invoke(app, ["catalog", "--config", str(path)])
    assert result.exit_code == 0, result.output
    assert "seed raw: 2 cells cataloged" in result.output
    assert "day=2026-01-01" in result.output


def test_catalog_writes_catalog_file(tmp_path):
    path = write_run_config(tmp_path)
    out = tmp_path / "catalog.json"
    result = runner.invoke(app, ["catalog", "--config", str(path), "--write", str(out)])
    assert result.exit_code == 0, result.output
    document = CatalogDocument.model_validate_json(out.read_text())
    assert len(document.entries) == 2


def test_catalog_named_save_target(tmp_path):
    path = write_run_config(tmp_path)
    result = runner.invoke(app, ["catalog", "--config", str(path), "--handler", "out"])
    assert result.exit_code == 0, result.output
    assert "handler out: 0 cells cataloged" in result.output  # nothing saved yet


def test_catalog_rejects_mapless_instance(tmp_path):
    path = write_run_config(tmp_path)
    result = runner.invoke(app, ["catalog", "--config", str(path), "--handler", "aux"])
    assert result.exit_code == 1
    assert "no dimensions map" in result.output


# -- spout setup ------------------------------------------------------------------


def test_setup_runs_every_stage_hook(tmp_path):
    path = write_run_config(tmp_path)
    result = runner.invoke(app, ["setup", "--config", str(path)])
    assert result.exit_code == 0, result.output
    assert "setup: scale ✓" in result.output


# -- spout test-package -------------------------------------------------------------


def test_test_package_static_pass_and_full_run(tmp_path, monkeypatch):
    write_fake_package(tmp_path, "clipkg_ok")
    monkeypatch.syspath_prepend(str(tmp_path))
    static = runner.invoke(app, ["test-package", "clipkg_ok", "--static-only"])
    assert static.exit_code == 0, static.output
    assert "clipkg_ok_double ✓" in static.output
    assert "clipkg_ok_json_cell ✓" in static.output
    assert "unbounded str domain" in static.output  # the lint warning surfaces

    full = runner.invoke(app, ["test-package", "clipkg_ok"])
    assert full.exit_code == 0, full.output  # its pytest suite ran and passed


def test_test_package_nonconforming_fails(tmp_path, monkeypatch):
    write_fake_package(
        tmp_path, "clipkg_bad", {"stages/double_values/test_double_values.py": None}
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    result = runner.invoke(app, ["test-package", "clipkg_bad", "--static-only"])
    assert result.exit_code == 1
    assert "clipkg_bad_double ✗" in result.output
    assert "no mandated test file" in result.output


# -- package-contributed verbs ---------------------------------------------------------


class FakeVerbEntryPoint:
    def __init__(self, name, payload):
        self.name = name
        self.value = f"{name}.cli:app"
        self._payload = payload

    def load(self):
        return self._payload


def make_verb_app():
    sub = typer.Typer()

    @sub.command()
    def train() -> None:
        typer.echo("training!")

    return sub


def test_package_verbs_mount_and_run():
    host = typer.Typer()

    @host.callback()
    def _root() -> None:
        """host"""

    mounted = mount_package_verbs(host, entry_points=[FakeVerbEntryPoint("mypkg", make_verb_app())])
    assert mounted == ("mypkg",)
    result = runner.invoke(host, ["mypkg", "train"])
    assert result.exit_code == 0, result.output
    assert "training!" in result.output


def test_verb_mount_collision_names_both():
    import pytest

    from rainspout.errors import RegistrationError

    host = typer.Typer()
    entry_points = [
        FakeVerbEntryPoint("mypkg", make_verb_app()),
        FakeVerbEntryPoint("mypkg", make_verb_app()),
    ]
    with pytest.raises(RegistrationError, match="mypkg"):
        mount_package_verbs(host, entry_points=entry_points)


def test_verb_mount_requires_typer_app():
    import pytest

    from rainspout.errors import DefinitionError

    host = typer.Typer()
    with pytest.raises(DefinitionError, match="typer.Typer"):
        mount_package_verbs(host, entry_points=[FakeVerbEntryPoint("mypkg", object())])


# -- spout build-image --------------------------------------------------------------------


def test_build_image_writes_pinned_dockerfile(tmp_path):
    out = tmp_path / "Dockerfile.rainspout"
    result = runner.invoke(app, ["build-image", "--output", str(out)])
    assert result.exit_code == 0, result.output
    content = out.read_text()
    assert content.startswith("# Generated by `spout build-image`")
    assert "FROM python:" in content
    assert "rainspout==" in content
    assert 'ENTRYPOINT ["spout"]' in content
