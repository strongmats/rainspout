"""The collector module: importing it registers every component.

Every stage and handler in this package MUST be imported here — a component
missing from this list fails silently (it just never registers). Verify with
`spout catalog` after adding one. The `noqa: F401` matters: linters see these
imports as unused and will otherwise auto-remove them, silently unregistering
your components.
"""

from rainspout_example.handlers.readings_local_csv import handler as _handler  # noqa: F401
from rainspout_example.stages.smooth_readings import stage as _stage  # noqa: F401
