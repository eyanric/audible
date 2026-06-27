"""External data sources, each quarantined behind a clean internal interface.

Every adapter normalises its source into shared models (``PlayerProjection``) so the
rest of the engine never sees a vendor's field names. The ESPN adapter especially is
isolated -- it rides an unofficial API and should be a one-file fix when it breaks.
"""

from .base import PlatformAdapter
from .sleeper import SleeperAdapter

__all__ = ["PlatformAdapter", "SleeperAdapter"]
