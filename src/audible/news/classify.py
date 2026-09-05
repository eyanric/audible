"""Rule-based classification. No NLP pipeline, no model call, no sentiment scoring.

PRECISION OVER COVERAGE, DELIBERATELY. Most sports-feed items are not about a fantasy
decision, and the honest label for them is `noise`. A classifier that strains to find
meaning in every headline produces confident nonsense on the 80% that are game recaps and
betting previews; one that says `noise` unless a pattern actually fires stays trustworthy
on the 20% that matter.

The severity scale is coarse for the same reason -- it is a filter for `--min-severity`,
not a score anyone should reason with:

    3  he is out
    2  his status is genuinely in doubt, or his role just changed
    1  worth reading, not yet actionable
    0  noise
"""

from __future__ import annotations

import re
from dataclasses import dataclass

NOISE = "noise"

EVENT_TYPES = (
    "injury_out", "injury_doubtful", "injury_questionable", "practice_limited",
    "activated", "depth_chart_change", "trade", "suspension", "signing", NOISE,
)


@dataclass(frozen=True, slots=True)
class Classification:
    event_type: str
    severity: int


# Ordered: the FIRST rule that fires wins, so the most consequential patterns come first.
# "out for the season" must beat "questionable", and a suspension must not read as a trade.
_RULES: tuple[tuple[str, int, re.Pattern[str]], ...] = (
    ("injury_out", 3, re.compile(
        r"\b(ruled out|is out|will not play|won'?t play|out for the (season|year)|"
        r"season[- ]ending|(placed|lands?|landed|goes|went) on "
        r"(injured reserve|ir|pup|the pup list)\b|to ir\b|"
        r"(reserve/)?pup list\b|carted off|"
        r"tore (his )?(acl|achilles|mcl)|torn (acl|achilles|mcl))", re.I)),
    ("suspension", 3, re.compile(
        r"\b(suspend(ed|s|ing)?|suspension|exempt list|banned for)\b", re.I)),
    ("injury_doubtful", 2, re.compile(r"\b(doubtful)\b", re.I)),
    ("injury_questionable", 2, re.compile(
        r"\b(questionable|game[- ]time decision|did not practice|dnp)\b", re.I)),
    ("practice_limited", 1, re.compile(
        r"\b(limited (in )?practice|limited participant|practiced? in a limited)\b", re.I)),
    ("activated", 2, re.compile(
        r"\b(activated|returns? to practice|cleared to (play|return)|"
        r"off (the )?(injured reserve|ir)|designated to return)\b", re.I)),
    ("depth_chart_change", 2, re.compile(
        r"\b(named (the )?starter|will start|benched|demoted|promoted|"
        r"takes over as|lead back|starting (job|role)|depth chart)\b", re.I)),
    ("trade", 2, re.compile(r"\b(traded?|trade[ds]? to|acquired? (by|from)|dealt to)\b", re.I)),
    ("signing", 1, re.compile(
        r"\b(signs?|signed|agrees? to terms|re[- ]signs?|waives?|waived|releases?|released|"
        r"claimed off waivers|cut by|cuts?)\b", re.I)),
)


def classify(title: str, body: str = "") -> Classification:
    """Title carries the fact in a player-news feed; body is the fallback."""
    for text in (title, body):
        if not text:
            continue
        for event_type, severity, pattern in _RULES:
            if pattern.search(text):
                return Classification(event_type, severity)
    return Classification(NOISE, 0)
