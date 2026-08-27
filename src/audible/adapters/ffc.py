"""Fantasy Football Calculator ADP -- a real preseason consensus snapshot, per season.

    https://fantasyfootballcalculator.com/api/v1/adp/standard?teams=8&year=YYYY

Free for personal and commercial use, attribution requested (see README), and the docs ask
callers not to hit it frequently. So: ONE request per season, cached to disk, pinned. Every
later read comes off the cache and `from_network` returns to zero.

WHY THIS SOURCE AND NOT THE ONES ALREADY HERE. Every previous attempt to backtest a draft
foundered on the projection: ESPN serves ranks but no historical projected points, and
Sleeper's historical projections are contaminated -- Rodgers, Dobbins and Chubb all carry a
2023 "projection" of 0.0 because the endpoint returns the LAST state, zeroed for players
ruled out. FFC is different in kind: it is a record of what a room of real drafters DID
before the season, sampled from actual mock and real drafts, with the sample size and date
range published alongside. That makes it auditable in a way a projection is not -- you can
check whether the snapshot predates week one instead of trusting that it does.

It is still not a projection. It is consensus ORDER. What is built on it is consensus order
plus this league's replacement-level and roster-construction logic, and the report says so.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .cache import JsonCache

BASE = "https://fantasyfootballcalculator.com/api/v1/adp"
ATTRIBUTION = "ADP data courtesy of Fantasy Football Calculator (fantasyfootballcalculator.com)"


@dataclass(frozen=True, slots=True)
class AdpSnapshot:
    """One season's ADP, with the provenance needed to judge whether it is preseason."""

    year: int
    teams: int
    scoring: str
    draft_count: int          # how many drafts the consensus is pooled from
    start_date: str | None    # first draft in the sample
    end_date: str | None      # last draft in the sample -- the field that decides usability
    players: list[dict[str, Any]]

    @property
    def provenance(self) -> str:
        return (f"{self.draft_count} drafts, {self.start_date} .. {self.end_date}")


class FfcAdapter:
    """Read-only, cached, one call per season."""

    def __init__(self, cache: JsonCache | None = None, timeout: float = 20.0) -> None:
        self._cache = cache if cache is not None else JsonCache()
        self._timeout = timeout

    def snapshot(
        self, year: int, *, teams: int = 8, scoring: str = "standard", refresh: bool = False
    ) -> AdpSnapshot:
        key = f"ffc_adp_{scoring}_{teams}_{year}"
        payload = None if refresh else self._cache.get_stale(key)
        if payload is None:
            import httpx

            url = f"{BASE}/{scoring}"
            resp = httpx.get(url, params={"teams": teams, "year": year},
                             timeout=self._timeout)
            resp.raise_for_status()
            payload = resp.json()
            self._cache.set(key, payload)

        meta = payload.get("meta") or {}
        return AdpSnapshot(
            year=int(meta.get("year") or year),
            teams=int(meta.get("teams") or teams),
            scoring=str(meta.get("type") or scoring),
            draft_count=int(meta.get("total_drafts") or 0),
            start_date=meta.get("start_date"),
            end_date=meta.get("end_date"),
            players=list(payload.get("players") or []),
        )

    def cached_only(self, year: int, *, teams: int = 8, scoring: str = "standard") -> bool:
        return self._cache.get_stale(f"ffc_adp_{scoring}_{teams}_{year}") is not None
