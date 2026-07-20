"""The `spout` Typer app: composable pipeline commands.

`validate`, `run`, `catalog`, `setup`, `test-package`, `build-image`, plus
package-contributed verbs mounted from the `rainspout.verbs` entry-point
group. Orchestration (cron/sbatch/Docker) is deliberately out of scope.
"""

from __future__ import annotations

import signal
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any

import typer

from .. import conformance, discovery, registry, validation
from ..driver import (
    Plan,
    StopFlag,
    acquire_run_lock,
    drive,
    new_run_id,
    parse_selects,
    resolve_oplog_path,
)
from ..errors import RainspoutError
from ..oplog import OpLog
from ..runner import WorkItemResult
from ..status import LiveStatus
from ._mount import mount_package_verbs
from .build_image import generate_dockerfile

app = typer.Typer(
    name="spout",
    help="Rainspout: composable pipeline commands. Orchestration belongs to cron/sbatch/Docker.",
    no_args_is_help=True,
)


@app.callback()
def _root() -> None:
    """Rainspout's composable pipeline commands."""


@app.command()
def validate(
    config: Annotated[
        Path, typer.Option("--config", help="Path to the run configuration (.yml)")
    ],
) -> None:
    """Check a run configuration completely, instantly, touching no data."""
    try:
        discovery.discover_components()
        validation.validate_config(config)
    except RainspoutError as exc:
        typer.echo(f"validation failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo("config ✓  registry ✓  DAG ✓  settings ✓")


def _echo_event(kind: str, payload: Any) -> None:
    if kind == "preflight_ok":
        seed_name, handler_name, coords = payload
        probe = ", ".join(f"{k}={v}" for k, v in coords.items())
        typer.echo(f"pre-flight: seed {seed_name} ✓ ({handler_name}, probe {probe})")
    elif kind == "preflight_empty":
        typer.echo(f"NOTICE: {payload}", err=True)
    elif kind == "plan":
        plan: Plan = payload
        typer.echo(
            f"plan: {plan.existing} work items — {len(plan.items)} to run, "
            f"{plan.done} done, {plan.failed} previously failed"
        )
    elif kind == "work_item":
        result: WorkItemResult = payload
        parts = []
        for stage in result.stages:
            mark = "✓" if stage.status == "succeeded" else "✗"
            parts.append(f"{stage.instance} {mark}")
            if stage.saved_to:
                parts.append(f"saved → {stage.saved_to}")
        line = f"[{result.cell_id}] " + "  ".join(parts)
        if result.status == "failed":
            failed = result.stages[-1]
            line += f"  FAILED ({failed.error}) — continuing"
        typer.echo(line)
    elif kind == "cycle_end":
        typer.echo(f"cycle {payload} drained; polling…")


@app.command()
def run(
    config: Annotated[
        Path, typer.Option("--config", help="Path to the run configuration (.yml)")
    ],
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Plan and report; execute nothing")
    ] = False,
    select: Annotated[
        list[str] | None,
        typer.Option("--select", help="Narrow a dimension: dim=value (repeatable)"),
    ] = None,
    retry_failed: Annotated[
        bool, typer.Option("--retry-failed", help="Re-queue previously FAILED cells")
    ] = False,
    force_rewrite: Annotated[
        bool,
        typer.Option(
            "--force-rewrite",
            help="Re-run previously SUCCEEDED cells, overwriting their output",
        ),
    ] = False,
    live: Annotated[
        bool | None,
        typer.Option(
            "--live/--no-live",
            help="Redraw a one-line live status in this terminal "
            "(default: on when attached to one)",
        ),
    ] = None,
) -> None:
    """Execute the run: drain the delta (retrograde) or keep polling (realtime)."""
    try:
        discovery.discover_components()
        validated = validation.validate_config(config)
        selected = parse_selects(select or [], validated)
        oplog_path = resolve_oplog_path(config, validated.config)
        oplog = OpLog(oplog_path)
        run_name = validated.config.run.name
        run_id = new_run_id(run_name)

        # one active run per run definition; dry runs only read, so no lock
        release_lock: Callable[[], None] | None = None
        reporter: LiveStatus | None = None
        if not dry_run:
            release_lock = acquire_run_lock(oplog_path, run_name=run_name, run_id=run_id)
            if live if live is not None else sys.stderr.isatty():
                reporter = LiveStatus(sys.stderr)

        stop = StopFlag()

        def interrupt(signum: int, frame: Any) -> None:
            """Ctrl-C aborts now; a second one is an OS-level kill.

            The graceful stop only lands between work items, so on a long item
            a caught SIGINT looks like a hang — the keypress registers and
            nothing happens for minutes. Interactive Ctrl-C therefore abandons
            the in-flight item instead of finishing it. That is safe: the oplog
            is appended per work item, so everything already finished is on
            disk, and the interrupted item was never marked done, so a rerun
            redoes just that one. The flock is released by the OS on exit.

            Restoring the default handler first means a second Ctrl-C
            terminates at the OS level, which is the only thing that can
            interrupt a long call inside a C extension — where Python cannot
            run this handler at all until the call returns.
            """
            signal.signal(signal.SIGINT, signal.SIG_DFL)
            stop.set()
            raise KeyboardInterrupt

        signal.signal(signal.SIGINT, interrupt)
        # SIGTERM keeps the graceful contract: schedulers and `kill` expect a
        # clean stop at the next work-item boundary, not an abandoned item.
        signal.signal(signal.SIGTERM, stop.set)

        def notify(kind: str, payload: Any) -> None:
            # blank the live line so permanent output never collides with it
            if reporter is not None:
                reporter.clear()
            _echo_event(kind, payload)

        try:
            summary = drive(
                validated,
                oplog=oplog,
                run_id=run_id,
                select=selected,
                retry_failed=retry_failed,
                force_rewrite=force_rewrite,
                dry_run=dry_run,
                notify=notify,
                stop=stop,
                reporter=reporter,
            )
        finally:
            if release_lock is not None:
                release_lock()
            if reporter is not None:
                reporter.clear()
    except KeyboardInterrupt:
        # the finally above already released the lock and cleared the live line
        typer.echo("\ninterrupted — the in-flight work item was abandoned.", err=True)
        typer.echo("Everything already finished is recorded; rerun to resume.", err=True)
        raise typer.Exit(code=130) from None
    except RainspoutError as exc:
        typer.echo(f"run failed to start: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    if not summary.dry_run:
        suffix = " (stopped cleanly)" if summary.stopped else ""
        typer.echo(f"done: {summary.succeeded} succeeded, {summary.failed} failed{suffix}")


@app.command()
def catalog(
    config: Annotated[
        Path | None,
        typer.Option("--config", help="Survey this run's data; omit to list the registry"),
    ] = None,
    handler: Annotated[
        str | None,
        typer.Option("--handler", help="Survey a named handler instance instead of the seed"),
    ] = None,
    write: Annotated[
        Path | None, typer.Option("--write", help="Also write a catalog file here")
    ] = None,
) -> None:
    """Survey what exists: registered components (no --config) or a run's data."""
    try:
        discovery.discover_components()
        if config is None:
            for axis in ("stage", "handler"):
                names = registry.names(axis)
                typer.echo(f"{axis}s: " + (", ".join(names) if names else "(none registered)"))
            return
        validated = validation.validate_config(config)
        if handler is None or handler == validated.seed_name:
            instance = validated.seed_handler
            role_map = validated.config.seed[validated.seed_name].dimensions
            label = f"seed {validated.seed_name}"
        else:
            if handler not in validated.handler_instances:
                raise RainspoutError(
                    f"unknown handler instance '{handler}' "
                    f"(declared: {', '.join(validated.handler_instances) or 'none'})"
                )
            role_map_or_none = validated.config.handlers[handler].dimensions
            if role_map_or_none is None:
                raise RainspoutError(
                    f"handler instance '{handler}' has no dimensions map to survey "
                    "along — stage-callable instances are asked for coordinates by "
                    "their stage, not by the run window"
                )
            instance = validated.handler_instances[handler]
            role_map = role_map_or_none
            label = f"handler {handler}"
        spec = {
            role: validated.dimension_values[dimension]
            for role, dimension in role_map.items()
        }
        count = 0
        for entry in instance.catalog(spec, write_path=write):
            count += 1
            coords = ", ".join(f"{k}={v}" for k, v in entry.coords.items())
            extras = f"  {entry.extras}" if entry.extras else ""
            typer.echo(f"  {coords}{extras}")
        typer.echo(f"{label}: {count} cells cataloged" + (f" → {write}" if write else ""))
    except RainspoutError as exc:
        typer.echo(f"catalog failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc


@app.command()
def setup(
    config: Annotated[
        Path, typer.Option("--config", help="Path to the run configuration (.yml)")
    ],
) -> None:
    """Run every stage's setup hook (idempotent), after full validation."""
    try:
        discovery.discover_components()
        validated = validation.validate_config(config)
        for instance_name in validated.stage_order:
            validated.stage_instances[instance_name].setup()
            typer.echo(f"setup: {instance_name} ✓")
    except RainspoutError as exc:
        typer.echo(f"setup failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc


@app.command("test-package")
def test_package(
    package: Annotated[str, typer.Argument(help="The package's import name")],
    static_only: Annotated[
        bool,
        typer.Option("--static-only", help="Conformance shape-check only; skip pytest"),
    ] = False,
) -> None:
    """Shape-check a package's components, then run its test suite."""
    try:
        report = conformance.check_package(package)
    except RainspoutError as exc:
        typer.echo(f"test-package failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    marks = []
    for check in report.components:
        marks.append(f"{check.name} {'✓' if check.ok else '✗'}")
        for problem in check.problems:
            typer.echo(f"  ✗ {check.axis} {check.name}: {problem}", err=True)
        for warning in check.warnings:
            typer.echo(f"  warning: {warning}", err=True)
    typer.echo("components: " + "  ".join(marks))
    if not report.ok:
        raise typer.Exit(code=1)
    if static_only:
        return
    package_dir = Path(str(sys.modules[package].__file__)).parent
    outcome = subprocess.run(  # noqa: S603 — running the package's own tests is the point
        [sys.executable, "-m", "pytest", str(package_dir), "-q"], check=False
    )
    if outcome.returncode != 0:
        raise typer.Exit(code=outcome.returncode)


@app.command("build-image")
def build_image(
    output: Annotated[
        Path, typer.Option("--output", help="Where to write the Dockerfile")
    ] = Path("Dockerfile.rainspout"),
) -> None:
    """Crystallize the current environment into a reproducible Dockerfile."""
    output.write_text(generate_dockerfile())
    typer.echo(f"wrote {output} — build with: docker build -f {output} -t <tag> .")


mount_package_verbs(app)
