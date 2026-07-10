"""The adversarial reference package's collector: import = registration.

(noqa: F401 keeps linters from auto-removing the imports that ARE the
registration mechanism.)
"""

from reference_content.handlers.ref_grid_json import handler as _grid  # noqa: F401
from reference_content.handlers.ref_lines_txt import handler as _lines  # noqa: F401
from reference_content.handlers.ref_table_json import handler as _table  # noqa: F401
from reference_content.stages.ref_enrich import stage as _enrich  # noqa: F401
from reference_content.stages.ref_snip import stage as _snip  # noqa: F401
