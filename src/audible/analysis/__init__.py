"""Analysis gates -- read-only studies over completed seasons.

Nothing here feeds the draft board. These answer questions about the room and about the
model's own record; the deterministic core stays untouched by them.
"""

from .anchoring import AnchoringReport, SeatVerdict, build_report

__all__ = ["AnchoringReport", "SeatVerdict", "build_report"]
