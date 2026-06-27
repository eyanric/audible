"""Scoring-coverage registry (Metrics Addendum 01, A) -- verified, locked.

Every league scoring key resolves to one of three states so the carried tail is an
audited decision, never a silent zero:

  * ``modeled``  -- has a matching ff_opportunity expected component; scored through the
                    engine on those components -> league-correct xFP.
  * ``carried``  -- no expected component (distribution-dependent, or unmodeled by
                    ffopportunity); inherited additively from the consensus projection.
  * ``ignored``  -- not in the offense xFP context at all (ff_opportunity is offense-only):
                    first-down bonuses, kicker, team DEF, and IDP keys.

Classification was verified against the live 159 columns (pass_interception_exp EXISTS
-> the -2 INT is modeled; rush_40p/rec_40p/rec_30_39 and fum_lost have no _exp -> carried).
"""

from __future__ import annotations

from collections.abc import Mapping

# ff_opportunity expected-component column  ->  our (Sleeper) scoring stat key.
MODELED_COMPONENTS: dict[str, str] = {
    "receptions_exp": "rec",
    "rec_yards_gained_exp": "rec_yd",
    "rec_touchdown_exp": "rec_td",
    "rec_two_point_conv_exp": "rec_2pt",
    "rush_yards_gained_exp": "rush_yd",
    "rush_touchdown_exp": "rush_td",
    "rush_two_point_conv_exp": "rush_2pt",
    "pass_yards_gained_exp": "pass_yd",
    "pass_touchdown_exp": "pass_td",
    "pass_interception_exp": "pass_int",
    "pass_two_point_conv_exp": "pass_2pt",
}

# Scoring keys produced by these components (the modeled tail of any league's scoring).
MODELED_KEYS: frozenset[str] = frozenset(MODELED_COMPONENTS.values())

# Scoring keys with no expected component -> inherit from consensus additively.
# Big-play bonuses depend on play-length distribution, not mean expected yards; fumbles
# lost have no _exp counterpart in ffopportunity.
CARRIED_KEYS: frozenset[str] = frozenset(
    {"rush_40p", "rec_40p", "rec_30_39", "fum_lost"}
)


def classify_key(key: str) -> str:
    if key in MODELED_KEYS:
        return "modeled"
    if key in CARRIED_KEYS:
        return "carried"
    return "ignored"


def split_scoring(scoring: Mapping[str, float]) -> dict[str, list[str]]:
    """Bucket a league's scoring keys into modeled / carried / ignored (for inspection)."""
    buckets: dict[str, list[str]] = {"modeled": [], "carried": [], "ignored": []}
    for key in scoring:
        buckets[classify_key(key)].append(key)
    for names in buckets.values():
        names.sort()
    return buckets
