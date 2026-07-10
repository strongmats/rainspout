# Tutorial 2 — Add a stage

*This tutorial doubles as an acceptance test: every step is runnable, and the
final step's expected output is stated.*

We'll build `smooth_readings`: moving-window smoothing of a list of floats.
Same package as Tutorial 1.

## Step 1 — Make the stage directory

```
src/my_package/stages/smooth_readings/
├── __init__.py
├── stage.py
├── science.py
└── test_smooth_readings.py
```

## Step 2 — Science first, in a module-level function

`science.py` — no skeleton imports, testable by itself:

```python
def smooth(values: list[float], window_len: int, method: str) -> list[float]:
    if not values or not all(isinstance(v, float) for v in values):
        raise ValueError("expected a non-empty list of floats")
    half = window_len // 2
    out = []
    for i in range(len(values)):
        window = values[max(0, i - half): i + half + 1]
        out.append(sorted(window)[len(window) // 2] if method == "median"
                   else sum(window) / len(window))
    return out
```

## Step 3 — The thin orchestrator

`stage.py`:

```python
from typing import Literal
from pydantic import Field

from rainspout.contracts import (
    Stage, StageSettings, StageDependencies, LazyReference, StageError,
)
from .science import smooth


class SmoothReadingsSettings(StageSettings):
    window_len: int = Field(ge=1, le=10_000)
    method: Literal["mean", "median"] = "mean"


class SmoothReadingsDependencies(StageDependencies):
    data: LazyReference


class SmoothReadings(Stage):
    name = "smooth_readings"
    version = "1.0.0"
    settings_model = SmoothReadingsSettings
    dependencies_model = SmoothReadingsDependencies

    def run(self, deps: SmoothReadingsDependencies) -> list[float]:
        values = deps.data.get()                      # pull once
        if not isinstance(values, list):              # cheap shape check only
            raise StageError(f"smooth_readings expected list, got {type(values).__name__}")
        self.set_status(f"smoothing {len(values)} values ({self.settings.method})")
        try:
            return smooth(values, self.settings.window_len, self.settings.method)
        except ValueError as e:
            raise StageError(f"smooth_readings: {e}") from e
```

Everything bounded, no `__init__`, no side effects, no saving (that's config's
call). Smoothing is position-independent, so this stage never touches its
work-item coordinate — but it could: `deps.data.coords` is the read-only
`{dimension: value}` mapping for the current work item, there for science that
needs to know *where* it is (a file's start time, say). The class fits on half
a screen — if yours doesn't, push more into `science.py`.

## Step 4 — The mandated test

`test_smooth_readings.py` — in the stage directory, with the two required
module-level names, a known-output test and a failure-path test:

```python
import pytest
from rainspout.testing import run_stage
from .stage import SmoothReadings
from .science import smooth

STAGE = SmoothReadings
EXAMPLE_SETTINGS = {"window_len": 3, "method": "mean"}

def test_smooths_known_input():
    out = run_stage(STAGE, EXAMPLE_SETTINGS, deps={"data": [1.0, 4.0, 1.0]})
    assert out == [2.5, 2.0, 2.5]

def test_rejects_non_list():
    with pytest.raises(Exception, match="expected list"):
        run_stage(STAGE, EXAMPLE_SETTINGS, deps={"data": "nope"})

def test_science_directly():                 # module-level functions: test them raw
    assert smooth([1.0, 1.0], 1, "mean") == [1.0, 1.0]
```

`run_stage` constructs the stage through the real validation path (so
`EXAMPLE_SETTINGS` is proven valid), wraps each `deps` value in a
`LazyReference`, runs `setup()` then `run()`, and returns the output.

## Step 5 — Register and verify

Add to `components.py`:

```python
from my_package.stages.smooth_readings import stage as _
```

Then:

```
$ pytest src/my_package/stages/smooth_readings/ -q
3 passed

$ spout test-package my_package
components: readings_local_csv ✓  smooth_readings ✓
```

## Step 6 — Prove the version rule bites

Edit `science.py` (change anything), commit, and open a PR **without** touching
`version` in `stage.py`: the CI version-bump check fails, naming
`smooth_readings`. Bump to `1.0.1`; it passes. Editing only
`test_smooth_readings.py` requires no bump — tests are outside the code-hash
boundary.
