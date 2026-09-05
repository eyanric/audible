"""Resolve a news item to a Sleeper `player_id`.

The gate this is measured against was pre-registered in `docs/news-matcher-gate.md`
BEFORE this file existed. See that document for the rules; the short version is that the
first measurement is the reported one.

THE ASYMMETRY THAT SHAPES EVERY DECISION HERE. A missed match means an item is stored and
not surfaced -- invisible, recoverable, and the item is still in the store for a human
reading raw text over MCP. A WRONG match attributes an injury to the wrong player and shows
it on his row. One is a gap, the other is disinformation, and they are not comparable. So
every ambiguous case resolves to no match:

  * two rostered players share a surname and the text names no team -> no match
  * a surname appears with no team corroboration at all -> no match
  * a name index entry that maps to more than one player_id is dropped from the index

Confidence is recorded, never used to break a tie.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)

# Ordered strongest first; `match()` returns on the first hit.
CONF_EXACT_TITLE = "exact_title"
CONF_EXACT_BODY = "exact_body"
CONF_SURNAME_TEAM = "surname_team"
CONF_NONE = "none"

_SUFFIXES = {"jr", "jr.", "sr", "sr.", "ii", "iii", "iv", "v"}

# Team abbreviations as the Sleeper catalog spells them, plus the spellings news feeds use.
# ESPN writes Washington WSH; Sleeper writes WAS. Same trick as the ESPN id bridge.
TEAM_ALIASES: dict[str, str] = {
    "WSH": "WAS", "JAC": "JAX", "LAR": "LAR", "LA": "LAR", "TB": "TB", "SF": "SF",
    "NO": "NO", "NE": "NE", "GB": "GB", "KC": "KC", "LV": "LV", "OAK": "LV", "SD": "LAC",
    "STL": "LAR",
}

# Full team names / cities as they appear in prose, mapped to the catalog abbreviation.
TEAM_WORDS: dict[str, str] = {
    "cardinals": "ARI", "falcons": "ATL", "ravens": "BAL", "bills": "BUF",
    "panthers": "CAR", "bears": "CHI", "bengals": "CIN", "browns": "CLE",
    "cowboys": "DAL", "broncos": "DEN", "lions": "DET", "packers": "GB",
    "texans": "HOU", "colts": "IND", "jaguars": "JAX", "chiefs": "KC",
    "raiders": "LV", "chargers": "LAC", "rams": "LAR", "dolphins": "MIA",
    "vikings": "MIN", "patriots": "NE", "saints": "NO", "giants": "NYG",
    "jets": "NYJ", "eagles": "PHI", "steelers": "PIT", "seahawks": "SEA",
    "49ers": "SF", "niners": "SF", "buccaneers": "TB", "bucs": "TB",
    "titans": "TEN", "commanders": "WAS",
}

_WORD = re.compile(r"[A-Za-z0-9'.\-]+")


def normalize(name: str | None) -> str:
    """Lowercase, de-accented, suffix-stripped, punctuation-folded.

    Folds the three shapes that actually differ across feeds:
      `D.J. Moore` / `DJ Moore` / `D J Moore`   -> `dj moore`
      `Ja'Marr Chase`  -> `jamarr chase`
      `Amon-Ra St. Brown` -> `amon ra st brown`  (hyphen splits; both sides fold alike)
    """
    if not name:
        return ""
    text = unicodedata.normalize("NFKD", name)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower().replace("'", "").replace("’", "").replace("-", " ")
    text = text.replace(".", " ")
    parts = [p for p in text.split() if p and p not in _SUFFIXES]
    # Collapse split initials: ["d","j","moore"] -> ["dj","moore"]
    collapsed: list[str] = []
    initials: list[str] = []
    for part in parts:
        if len(part) == 1 and part.isalpha():
            initials.append(part)
            continue
        if initials:
            collapsed.append("".join(initials))
            initials = []
        collapsed.append(part)
    if initials:
        collapsed.append("".join(initials))
    return " ".join(collapsed)


def _team_of(entry: dict[str, Any]) -> str | None:
    team = entry.get("team")
    if not team:
        return None
    abbr = str(team).upper()
    return TEAM_ALIASES.get(abbr, abbr)


@dataclass(slots=True)
class Match:
    player_id: str | None
    confidence: str


class PlayerIndex:
    """Name -> player_id, built from the cached Sleeper catalog already on disk.

    Ambiguity is removed at build time rather than resolved at match time: a full name or
    surname that maps to more than one rostered player is dropped from the unique index and
    kept only in the ambiguous map, where it can be disambiguated by team or refused.
    """

    def __init__(self, catalog: dict[str, Any], *, roster: set[str] | None = None) -> None:
        self._full: dict[str, set[str]] = defaultdict(set)
        self._surname: dict[str, set[str]] = defaultdict(set)
        self._team: dict[str, str | None] = {}
        self._name: dict[str, str] = {}
        self._defense: dict[str, str] = {}

        for pid, entry in catalog.items():
            if not isinstance(entry, dict):
                continue
            position = entry.get("position")
            if position == "DEF":
                # Team defences key on the abbreviation, which is also the catalog key.
                abbr = str(pid).upper()
                self._defense[abbr] = str(pid)
                for word, mapped in TEAM_WORDS.items():
                    if mapped == abbr:
                        self._defense[word] = str(pid)
                continue
            full = normalize(entry.get("full_name"))
            if not full:
                continue
            pid_s = str(pid)
            self._full[full].add(pid_s)
            self._name[pid_s] = str(entry.get("full_name") or "")
            self._team[pid_s] = _team_of(entry)
            parts = full.split()
            if len(parts) > 1:
                self._surname[parts[-1]].add(pid_s)

        # `roster` narrows ambiguity to players we actually care about. Two players sharing
        # a surname is common league-wide and rare within one roster.
        self._roster = roster

    def _candidates(self, ids: set[str]) -> set[str]:
        if self._roster is None:
            return ids
        narrowed = ids & self._roster
        return narrowed or ids

    def lookup_full(self, name: str) -> str | None:
        ids = self._candidates(self._full.get(normalize(name), set()))
        return next(iter(ids)) if len(ids) == 1 else None

    def teams_in(self, text: str) -> set[str]:
        """Every team abbreviation the text corroborates, by abbreviation or by nickname."""
        found: set[str] = set()
        lowered = text.lower()
        for word, abbr in TEAM_WORDS.items():
            if re.search(rf"\b{re.escape(word)}\b", lowered):
                found.add(abbr)
        for token in _WORD.findall(text):
            upper = token.upper()
            if 2 <= len(upper) <= 3 and upper.isalpha() and token.isupper():
                # `.get(upper, upper)` is what this means, but ruff and pyright
                # disagree about that call's type; an alias is never empty, so `or` is exact.
                found.add(TEAM_ALIASES.get(upper) or upper)
        return found

    # --- the matcher ----------------------------------------------------------------
    def match(self, title: str, body: str = "") -> Match:
        """Title first, body second. Ambiguity always loses."""
        for text, confidence in ((title, CONF_EXACT_TITLE), (body, CONF_EXACT_BODY)):
            if not text:
                continue
            pid = self._scan_full_names(text)
            if pid:
                return Match(pid, confidence)

        # Surname only -- allowed ONLY with team corroboration, and only when that leaves
        # exactly one candidate. This is where a guess would do the most damage.
        combined = f"{title}\n{body}"
        pid = self._scan_surname_with_team(combined)
        if pid:
            return Match(pid, CONF_SURNAME_TEAM)

        pid = self._scan_defense(title) or self._scan_defense(body)
        if pid:
            return Match(pid, CONF_SURNAME_TEAM)
        return Match(None, CONF_NONE)

    def _scan_full_names(self, text: str) -> str | None:
        tokens = _WORD.findall(text)
        norm = [normalize(t) for t in tokens]
        # Names run two to four tokens once suffixes are stripped ("Amon-Ra St. Brown").
        for size in (4, 3, 2):
            for i in range(len(norm) - size + 1):
                candidate = " ".join(p for p in norm[i:i + size] if p)
                if not candidate:
                    continue
                ids = self._candidates(self._full.get(candidate, set()))
                if len(ids) == 1:
                    return next(iter(ids))
                if len(ids) > 1:
                    # Same name, two players. Try the team before giving up.
                    resolved = self._by_team(ids, text)
                    if resolved:
                        return resolved
                    log.debug("ambiguous full name %r -> %s; no match", candidate, sorted(ids))
        return None

    def _scan_surname_with_team(self, text: str) -> str | None:
        teams = self.teams_in(text)
        if not teams:
            return None
        for token in _WORD.findall(text):
            key = normalize(token)
            if not key or " " in key:
                continue
            ids = self._candidates(self._surname.get(key, set()))
            if not ids:
                continue
            resolved = self._by_team(ids, text, teams=teams)
            if resolved:
                return resolved
            if len(ids) > 1:
                log.debug("surname %r ambiguous across %s with no team; no match",
                          key, sorted(ids))
        return None

    def _by_team(self, ids: set[str], text: str, teams: set[str] | None = None) -> str | None:
        teams = teams if teams is not None else self.teams_in(text)
        if not teams:
            return None
        hits = {pid for pid in ids if self._team.get(pid) in teams}
        return next(iter(hits)) if len(hits) == 1 else None

    def _scan_defense(self, text: str) -> str | None:
        if not text:
            return None
        lowered = text.lower()
        if not re.search(r"\b(defense|defence|d/st|dst)\b", lowered):
            return None
        for word, pid in self._defense.items():
            if re.search(rf"\b{re.escape(word.lower())}\b", lowered):
                return pid
        return None

    def display_name(self, player_id: str) -> str:
        return self._name.get(player_id, player_id)


def load_index(roster: set[str] | None = None) -> PlayerIndex:
    """Build from the Sleeper catalog already cached on disk -- no network."""
    from ..adapters.cache import JsonCache
    from ..adapters.sleeper import PLAYERS_CACHE_KEY

    catalog = JsonCache().get_stale(PLAYERS_CACHE_KEY)
    if not catalog:
        raise RuntimeError(
            f"no cached Sleeper catalog ({PLAYERS_CACHE_KEY}). Run `audible refresh-data`."
        )
    return PlayerIndex(catalog, roster=roster)
