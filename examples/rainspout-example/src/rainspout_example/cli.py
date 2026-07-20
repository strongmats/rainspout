"""Package-contributed verbs, mounted as `spout rainspout_example <verb>`.

Verbs are for domain operations that don't belong inside a DAG run — here, a
sample-data generator so the example run has something to chew on.
"""

from datetime import date, timedelta
from pathlib import Path
from typing import Annotated

import typer

app = typer.Typer(help="rainspout-example's own commands")


@app.callback()
def _root() -> None:
    """Commands contributed by the rainspout-example package."""


@app.command("make-data")
def make_data(
    base_dir: Annotated[Path, typer.Option("--base-dir", help="Where to write raw CSVs")],
    days: Annotated[int, typer.Option("--days", min=1, max=31)] = 3,
    sensors: Annotated[int, typer.Option("--sensors", min=1, max=10)] = 2,
) -> None:
    """Generate plain (foreign, metadata-less) sample readings."""
    start = date(2026, 1, 1)
    for day_offset in range(days):
        day = start + timedelta(days=day_offset)
        for sensor_number in range(1, sensors + 1):
            path = base_dir / str(day) / f"s{sensor_number}.csv"
            path.parent.mkdir(parents=True, exist_ok=True)
            rows = [1.0 + day_offset + 0.5 * i * sensor_number for i in range(5)]
            path.write_text("value\n" + "".join(f"{v}\n" for v in rows))
    typer.echo(f"wrote {days * sensors} cells under {base_dir}")
