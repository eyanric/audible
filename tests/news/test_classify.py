"""Classifier truth table. Rule-based by design: no NLP, no model call, no sentiment."""

from __future__ import annotations

import pytest

from audible.news.classify import EVENT_TYPES, NOISE, classify

# Headlines in the shape the live feeds actually serve them. Kept as one table so a new
# rule has to declare what it changes.
TABLE = [
    # --- out: the only label that should move a lineup by itself -------------------
    ("Puka Nacua ruled out for Sunday's game", "injury_out", 3),
    ("Report: Christian McCaffrey is out for Week 1", "injury_out", 3),
    ("Rashee Rice will not play against the Chargers", "injury_out", 3),
    ("Jordyn Tyson: Lands on IR, designated to return", "injury_out", 3),
    ("Nick Chubb placed on injured reserve", "injury_out", 3),
    ("J.K. Dobbins tore his ACL in practice", "injury_out", 3),
    ("Aidan Hutchinson carted off with a leg injury", "injury_out", 3),
    ("Star WR out for the season with a torn Achilles", "injury_out", 3),
    # --- suspension: must beat trade, and 'exempt list' is the 2026 phrasing --------
    ("Josh Jacobs placed on commissioner's exempt list", "suspension", 3),
    ("Receiver suspended six games for PED violation", "suspension", 3),
    # --- doubt --------------------------------------------------------------------
    ("Tee Higgins listed as doubtful", "injury_doubtful", 2),
    ("Garrett Wilson questionable with a knee issue", "injury_questionable", 2),
    ("Saquon Barkley a game-time decision Sunday", "injury_questionable", 2),
    ("Brock Bowers did not practice Wednesday", "injury_questionable", 2),
    # --- role and availability ----------------------------------------------------
    ("Trey Benson limited in practice Thursday", "practice_limited", 1),
    ("Puka Nacua: Back at practice Sunday", NOISE, 0),
    ("Bucky Irving activated off injured reserve", "activated", 2),
    ("Anthony Richardson cleared to play Week 1", "activated", 2),
    ("Tyrone Tracy named the starter in New York", "depth_chart_change", 2),
    ("Zach Charbonnet benched after fumble", "depth_chart_change", 2),
    ("Kaleb Johnson traded to the Packers", "trade", 2),
    ("Quinn Ewers acquired by Jacksonville", "trade", 2),
    ("Cowboys sign veteran running back", "signing", 1),
    ("Chiefs waive QB Chris Oladokun", "signing", 1),
    # --- the 80%: recaps, previews, ratings, betting -------------------------------
    ("Vikings win 24-10 behind three touchdowns", NOISE, 0),
    ("AFC West Predictions, Odds and NFL Best Picks for 2026", NOISE, 0),
    ("What's Aaron Donald's Madden 27 rating?", NOISE, 0),
    ("Ranking every NFL team's WR room", NOISE, 0),
    ("Week 1 fantasy football rankings", NOISE, 0),
]


@pytest.mark.parametrize(("title", "event_type", "severity"), TABLE)
def test_classifier_truth_table(title, event_type, severity):
    c = classify(title, "")
    assert (c.event_type, c.severity) == (event_type, severity), title


def test_every_label_is_declared():
    for _title, event_type, _sev in TABLE:
        assert event_type in EVENT_TYPES


def test_ordering_out_beats_questionable():
    """A headline carrying both facts must take the consequential one."""
    c = classify("Listed questionable Friday, then ruled out Sunday morning", "")
    assert c.event_type == "injury_out"


def test_ordering_suspension_beats_trade():
    c = classify("Packers trade for RB after Jacobs lands on the exempt list", "")
    assert c.event_type == "suspension"


def test_body_is_the_fallback_when_the_title_is_bare():
    c = classify("Bengals injury report", "Tee Higgins was ruled out for Sunday.")
    assert (c.event_type, c.severity) == ("injury_out", 3)


def test_title_wins_over_body():
    c = classify("Ja'Marr Chase ruled out", "Elsewhere, a lineman signs an extension.")
    assert c.event_type == "injury_out"


def test_unknown_text_is_noise_not_a_guess():
    assert classify("", "") == classify("aaaa bbbb cccc", "")
    assert classify("aaaa bbbb cccc", "").event_type == NOISE


def test_severity_is_bounded():
    for title, _e, _s in TABLE:
        assert 0 <= classify(title, "").severity <= 3


def test_classify_is_pure():
    """Same input, same answer -- it is called once per item per poll forever."""
    assert classify("Puka Nacua ruled out") == classify("Puka Nacua ruled out")
