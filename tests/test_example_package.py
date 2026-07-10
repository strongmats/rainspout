"""Regression guard: the pedagogical example package stays conforming.

(The full entry-point discovery path — install via uv, `spout catalog` sees
the components with no imports anywhere — is verified manually per phase
report, since it requires actually installing into an environment.)
"""

import sys
from pathlib import Path

from rainspout.conformance import check_package

EXAMPLE_SRC = Path(__file__).parent.parent / "examples" / "rainspout-example" / "src"


def test_example_package_is_conforming(monkeypatch):
    monkeypatch.syspath_prepend(str(EXAMPLE_SRC))
    sys.modules.pop("rainspout_example", None)
    report = check_package("rainspout_example")
    assert report.ok, [(c.name, c.problems) for c in report.components]
    assert {c.name for c in report.components} == {"readings_local_csv", "smooth_readings"}
    # the only lint warning should be the documented, comment-justified base_dir
    warnings = [w for c in report.components for w in c.warnings]
    assert warnings == []  # Path fields are bounded enough; nothing bare
