"""News ingestion: feeds in, filtered items out. Never touches a projection.

This package is deliberately inert with respect to the board. Nothing here imports from
`value/`, `scoring/`, `draft/` or `providers/`, and nothing it produces is read by them.
An item is stored, matched to a player, and given a coarse event type; what that means for
a lineup is a judgment a human makes, over MCP, reading the original text.
"""

from .classify import Classification, classify
from .entities import Match, PlayerIndex, load_index, normalize
from .store import NewsStore, StoredItem, news_dir

__all__ = [
    "Classification", "Match", "NewsStore", "PlayerIndex", "StoredItem",
    "classify", "load_index", "news_dir", "normalize",
]
