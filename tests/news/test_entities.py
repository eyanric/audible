"""Entity matching. Synthetic catalog so the expectations are readable and offline.

THE ASYMMETRY UNDER TEST. A missed match is invisible and recoverable. A wrong match puts
another player's injury on your guy's row. So most of these assert a *refusal*, and the
refusal tests are the ones that matter.
"""

from __future__ import annotations

import pytest

from audible.news.entities import (
    CONF_EXACT_BODY,
    CONF_EXACT_TITLE,
    CONF_NONE,
    CONF_SURNAME_TEAM,
    PlayerIndex,
    normalize,
)

CATALOG = {
    "1": {"full_name": "D.J. Moore", "position": "WR", "team": "CHI"},
    "2": {"full_name": "Ja'Marr Chase", "position": "WR", "team": "CIN"},
    "3": {"full_name": "Amon-Ra St. Brown", "position": "WR", "team": "DET"},
    "4": {"full_name": "Odell Beckham Jr.", "position": "WR", "team": "NYG"},
    "5": {"full_name": "Michael Pittman Jr.", "position": "WR", "team": "IND"},
    # Two Chases: a surname alone must never resolve between them.
    "6": {"full_name": "Chase Brown", "position": "RB", "team": "CIN"},
    # Same surname, SAME team: no amount of team corroboration can separate these.
    "13": {"full_name": "Marquise Brown", "position": "WR", "team": "CIN"},
    # Two Johnsons on different teams: team corroboration is the only way through.
    "7": {"full_name": "Diontae Johnson", "position": "WR", "team": "BAL"},
    "8": {"full_name": "Jaxson Smith-Njigba", "position": "WR", "team": "SEA"},
    "9": {"full_name": "Kaleb Johnson", "position": "RB", "team": "PIT"},
    # Same full name, two players -- the hard case.
    "10": {"full_name": "Mike Williams", "position": "WR", "team": "NYJ"},
    "11": {"full_name": "Mike Williams", "position": "WR", "team": "LAC"},
    "12": {"full_name": "Terry McLaurin", "position": "WR", "team": "WSH"},
    "DET": {"full_name": "Detroit Lions", "position": "DEF", "team": "DET"},
}


@pytest.fixture()
def index():
    return PlayerIndex(CATALOG)


# --- normalisation ----------------------------------------------------------------

@pytest.mark.parametrize(("raw", "expected"), [
    ("D.J. Moore", "dj moore"),
    ("DJ Moore", "dj moore"),
    ("D J Moore", "dj moore"),
    ("Ja'Marr Chase", "jamarr chase"),
    ("Ja’Marr Chase", "jamarr chase"),          # curly apostrophe, as feeds serve it
    ("Amon-Ra St. Brown", "amon ra st brown"),
    ("Odell Beckham Jr.", "odell beckham"),
    ("Odell Beckham Jr", "odell beckham"),
    ("Michael Pittman Jr.", "michael pittman"),
    ("Marvin Harrison III", "marvin harrison"),
    ("  Extra   Spaces  ", "extra spaces"),
    ("", ""),
    (None, ""),
])
def test_normalize_folds_the_variants_feeds_actually_serve(raw, expected):
    assert normalize(raw) == expected


def test_suffix_variants_all_reach_the_same_player(index):
    for spelling in ("Odell Beckham Jr.", "Odell Beckham Jr", "Odell Beckham"):
        assert index.lookup_full(spelling) == "4"


def test_initial_variants_all_reach_the_same_player(index):
    for spelling in ("D.J. Moore", "DJ Moore", "D J Moore"):
        assert index.lookup_full(spelling) == "1"


# --- matching that should succeed -------------------------------------------------

def test_full_name_in_title_wins(index):
    m = index.match("Ja'Marr Chase ruled out for Sunday", "")
    assert (m.player_id, m.confidence) == ("2", CONF_EXACT_TITLE)


def test_title_beats_body_when_both_name_someone(index):
    m = index.match("D.J. Moore returns to practice", "Ja'Marr Chase also practised.")
    assert m.player_id == "1", "the title is the subject; the body is context"


def test_body_is_used_when_the_title_names_nobody(index):
    m = index.match("Bears injury report", "D.J. Moore was a full participant.")
    assert (m.player_id, m.confidence) == ("1", CONF_EXACT_BODY)


def test_hyphen_and_period_names_match_from_prose(index):
    assert index.match("Amon-Ra St. Brown scores twice", "").player_id == "3"
    assert index.match("Jaxson Smith-Njigba leads the team", "").player_id == "8"


def test_surname_plus_team_resolves_when_it_is_unambiguous(index):
    m = index.match("Steelers trade Johnson at the deadline", "Pittsburgh moves on.")
    assert (m.player_id, m.confidence) == ("9", CONF_SURNAME_TEAM)


def test_team_alias_is_honoured(index):
    """ESPN writes WSH, the catalog says WAS. Same bridge as the ESPN id matcher."""
    assert index.match("Terry McLaurin extends with Washington", "").player_id == "12"


def test_duplicate_full_name_is_resolved_by_team(index):
    assert index.match("Mike Williams shines for the Chargers", "").player_id == "11"
    assert index.match("Mike Williams shines for the Jets", "").player_id == "10"


# --- matching that must REFUSE ----------------------------------------------------

def test_bare_surname_with_no_team_is_refused(index):
    m = index.match("Chase expected to play Sunday", "")
    assert (m.player_id, m.confidence) == (None, CONF_NONE)


def test_ambiguous_surname_within_one_team_is_refused(index):
    """Two Browns on Cincinnati. The team corroborates and still cannot choose."""
    m = index.match("Bengals list Brown as questionable", "Cincinnati did not elaborate.")
    assert m.player_id is None


def test_surname_shared_with_someone_elses_first_name_still_resolves(index):
    """'Chase' is Ja'Marr's surname and Chase Brown's first name -- not a surname clash."""
    assert index.match("Bengals list Chase as questionable", "").player_id == "2"


def test_duplicate_full_name_with_no_team_is_refused(index):
    m = index.match("Mike Williams has a big day", "")
    assert m.player_id is None, "two Mike Williamses and no team: refuse, do not pick one"


def test_unknown_person_matches_nothing(index):
    assert index.match("Sean McVay addresses the media", "").player_id is None


def test_empty_input_matches_nothing(index):
    assert index.match("", "").player_id is None


def test_roster_narrowing_disambiguates_a_shared_name():
    """Only one Mike Williams is on the board, so the board is the tiebreak."""
    narrowed = PlayerIndex(CATALOG, roster={"10", "1", "2"})
    assert narrowed.match("Mike Williams has a big day", "").player_id == "10"


def test_team_defense_matches_only_with_a_defense_word(index):
    assert index.match("Lions defense dominates", "").player_id == "DET"
    assert index.match("Lions win 24-10", "").player_id is None


# --- known defect, recorded rather than tuned away --------------------------------

@pytest.mark.xfail(
    strict=True,
    reason="G2 FAILURE, 2026-08-30. The Sleeper catalog carries 135 junk entries such as "
           "'Duplicate Player'. Its surname 'Player' plus any team word produces a false "
           "match -- observed on 'NFL waiver wire rules and the Eagles' position...'. "
           "Recorded, NOT fixed: the gate was pre-registered and the first measurement is "
           "the reported one. The fix belongs to a follow-up, not to this PR.",
)
def test_junk_catalog_entries_must_not_be_matchable():
    junk = dict(CATALOG)
    junk["99"] = {"full_name": "Duplicate Player", "position": "CB", "team": "PHI"}
    idx = PlayerIndex(junk)
    m = idx.match(
        "NFL waiver wire rules and the Eagles' position in the claiming order",
        "Teams have their initial 53-man roster. Every player waived on Sunday now enters "
        "the claiming order, and Philadelphia sits mid-pack.",
    )
    assert m.player_id is None
