"""Optional paid-product application boundary.

The package is intentionally not composed by the local analyzer.  Development
adapters are synthetic and production readiness is structurally false.
"""

from .contracts import *  # noqa: F403
from .errors import *  # noqa: F403
from .ports import *  # noqa: F403
from .services import *  # noqa: F403
