"""GATES for B8, and the failure injections that prove each one can fail.

THE SESSION'S CLAIM IS THAT A MARKET IS DECLARATIVE. Before B8 the market was a string literal
inside `room.load_board` -- `f"ffc_adp_standard_8_{season}.json"` -- and every result this repo
has produced was measured against a TWELVE-team board served into an EIGHT-team room, which is
a confound nobody could size because there was no second market to size it against.

So the gates here are about the SEAM rather than about the answer. `b8-ffc.toml` and
`b8-mfl8.toml` are identical below their headers except for the run name and one `market =`
line; if that is true and both run, the abstraction holds. Everything else in this file exists
because a seam can be present and still be wrong in a way that quietly produces numbers:

  G2   the board JOINS. A market whose names do not resolve produces a full board, a full
       draft and a full artifact, with every player on the rookie path, and nothing says so.
       That is not hypothetical: it is what MFL did before `mfl.display_name` existed, at 7 of
       180 keys shared with FFC, and the run completed and reported an advantage.
  G3   the board is PRE-DRAFT BY CONTENT, not by an `asof` we chose. MFL publishes no window
       end, so its `asof` is a lower bound and cannot carry this on its own.
  G4   preflight names the market's OWN pins, so a missing board fails before a unit runs.
  G6   two markets cannot share a checkpoint or a filename.

WHAT THESE GATES DO NOT SAY. They do not say the MFL population is the right one. MFL drafters
self-select onto a dynasty-oriented host, its eight-team pool over-drafts quarterbacks against
the real 6012 drafts, and the raw 2024 board carries IDP rows. Those are reported as
limitations of the measurement in `sim/runs/b8-markets.md`; a gate that pretended to settle
them would be a gate that lies.
"""

from __future__ import annotations

import csv
import dataclasses
from pathlib import Path

import pytest

from . import artifact, markets, mfl, projection, room, runner

REPO = Path(__file__).resolve().parents[1]
CONFIGS = REPO / "sim" / "configs"

MFL_MARKETS = ("mfl_8_std", "mfl_12_std")
ALL_MARKETS = ("ffc_12_std", *MFL_MARKETS)


@pytest.fixture(scope="module")
def fit() -> dict[int, object]:
    """Prior-season totals: the table `projection._resolve` matches a board row against."""
    return {season: projection.season_totals(season) for season in range(2019, 2026)}


# --- G1: the market is declarative --------------------------------------------------------


def _body(path: Path) -> dict:
    """A config as PARSED, with the run name and market removed.

    PARSED, NOT SLICED. The first version of this compared the text below the `[run]` header,
    which meant any TOML table declared ABOVE `[run]` -- `[gates]`, say -- was invisible to it,
    and two configs whose gate settings genuinely differed compared equal. Comparing the loaded
    document has no such blind spot and is immune to comment and whitespace churn as well.
    """
    import tomllib

    blob = tomllib.loads(path.read_text(encoding="utf-8"))
    blob["run"] = {k: v for k, v in blob["run"].items() if k not in ("name", "market")}
    return blob


def test_g1_two_markets_differ_by_one_line() -> None:
    """G1. The MFL run is the FFC run plus a market name, and nothing else."""
    assert _body(CONFIGS / "b8-ffc.toml") == _body(CONFIGS / "b8-mfl8.toml"), (
        "b8-ffc.toml and b8-mfl8.toml differ in something other than the run name and the "
        "market. Every such difference is a candidate explanation for every difference between "
        "their numbers."
    )


def test_i0_a_config_that_differs_anywhere_else_fails_g1(tmp_path) -> None:
    """The comparison must see a difference ANYWHERE, including outside the `[run]` table."""
    import tomllib

    ffc = tomllib.loads((CONFIGS / "b8-ffc.toml").read_text(encoding="utf-8"))
    mfl8 = tomllib.loads((CONFIGS / "b8-mfl8.toml").read_text(encoding="utf-8"))
    for mutate in (
        lambda d: d["run"].__setitem__("seat", 3),
        lambda d: d.setdefault("gates", {}).__setitem__("require_shuffle_at_chance", True),
        lambda d: d["run"].__setitem__("arms", ["adp"]),
    ):
        victim = tomllib.loads((CONFIGS / "b8-mfl8.toml").read_text(encoding="utf-8"))
        mutate(victim)
        assert victim != mfl8
        for doc in (ffc, victim):
            doc["run"] = {k: v for k, v in doc["run"].items() if k not in ("name", "market")}
        assert ffc != victim


def test_g1_the_configs_actually_name_different_markets() -> None:
    """The other half of G1: masking the market out must not mask a market that is the same."""
    got = {
        name: runner.load_config(CONFIGS / f"{name}.toml").market
        for name in ("b8-ffc", "b8-mfl8", "b8-mfl12")
    }
    assert got == {
        "b8-ffc": "ffc_12_std",
        "b8-mfl8": "mfl_8_std",
        "b8-mfl12": "mfl_12_std",
    }, got


def test_g1_selecting_a_market_actually_changes_the_data() -> None:
    """A market selects DATA, and this is the BEHAVIOURAL form of that claim.

    THIS REPLACED A SUBSTRING LINT that grepped every module for a registry key. That check
    could not do its job in either direction: it went red on a docstring that merely mentioned
    a market by name, and it stayed green against three hardcoded market branches written
    without the literal (`m.source == "mfl" and m.params["fcount"] == 8`, `m.name.startswith`,
    string concatenation). A grep for a name proves nothing about what the code does with it.

    What must be true is that the three markets produce three DIFFERENT boards, and that the
    difference reaches the thing the room drafts from -- the ordered top 128, not just the row
    count.
    """
    tops = {}
    for name in ALL_MARKETS:
        with markets.use(name):
            tops[name] = tuple(r.key for r in room.load_board(2024).rows[:128])
    assert len(set(tops.values())) == 3, "two markets produced the same top 128"
    for a, b in (("ffc_12_std", "mfl_8_std"), ("mfl_8_std", "mfl_12_std")):
        shared = sum(1 for x, y in zip(tops[a], tops[b], strict=False) if x == y)
        assert shared < 128, f"{a} and {b} agree on every one of the top 128 in order"


def test_g1_an_unknown_market_is_refused_in_preflight(tmp_path) -> None:
    """Named, not guessed at: a typo must not fall back to the default market."""
    source = (CONFIGS / "b8-mfl8.toml").read_text(encoding="utf-8")
    bad = tmp_path / "bad.toml"
    bad.write_text(source.replace('market = "mfl_8_std"', 'market = "mfl_8_stdd"'), "utf-8")
    with pytest.raises(SystemExit) as caught:
        runner.load_config(bad)
    assert "mfl_8_stdd" in str(caught.value)


# --- G2: the board joins ------------------------------------------------------------------


@pytest.mark.parametrize("market", ALL_MARKETS)
def test_g2_the_board_resolves_to_prior_evidence(market, fit) -> None:
    """G2. Nearly every drafted skill player must resolve to a real history.

    THE BAR IS 97% AND IT IS NOT A TUNING KNOB. A board that resolves at half still drafts,
    still scores and still writes an artifact -- the unresolved half arrives on the ROOKIE
    path carrying a draft-capital prior, which is a plausible-looking number for a player who
    is not a rookie. FFC's own rate over these five seasons is 628 of 629, so 97% sits far
    below what a working join produces and far above what a broken one can reach: MFL's
    surname-first spelling scored zero.
    """
    unresolved: list[str] = []
    total = 0
    with markets.use(market):
        for season in room.SEASONS:
            rows = [
                r for r in room.load_board(season).rows[:128] if r.position not in ("DEF", "K")
            ]
            total += len(rows)
            unresolved += [
                f"{season} {r.name}" for r in rows if projection._resolve(r, fit) is None
            ]
    rate = (total - len(unresolved)) / total
    assert rate >= 0.97, f"{market}: only {rate:.1%} of {total} resolve; {unresolved[:10]}"


def test_i1_surname_first_spelling_fails_g2(fit, monkeypatch) -> None:
    """INJECTION 1. Undo the name reorder and G2 must collapse, not merely dip.

    This is the defect as it actually was, restored: `mfl.display_name` returning its input.
    If G2 still passes with it, G2 is not measuring the join.
    """
    monkeypatch.setattr(mfl, "display_name", lambda raw: raw.strip())
    with markets.use("mfl_8_std"):
        rows = [r for r in room.load_board(2024).rows[:128] if r.position not in ("DEF", "K")]
        resolved = sum(1 for r in rows if projection._resolve(r, fit) is not None)
    assert resolved / len(rows) < 0.10, (
        f"surname-first spelling still resolved {resolved}/{len(rows)}; G2 cannot be relied on "
        f"to catch a broken crosswalk."
    )


def _nflverse_teams() -> set[str]:
    import polars as pl

    path, _root = room.resolve_input("nflverse/teams.parquet")
    return {str(a).upper() for a in pl.read_parquet(path)["team_abbr"]}


@pytest.mark.parametrize("market", MFL_MARKETS)
def test_g2_every_team_is_in_the_shared_vocabulary(market) -> None:
    """A defence joins on its ABBREVIATION, so a private spelling is a silent miss."""
    known = _nflverse_teams()
    strange: set[str] = set()
    with markets.use(market):
        for season in room.SEASONS:
            rows = room.load_board(season).rows
            strange |= {r.team for r in rows if r.team and r.team not in known}
            # NOT VACUOUS ON AN EMPTY TEAM FIELD. `{r.team for r in rows if r.team}` is empty
            # when nothing carries a team, so blanking every team would pass this silently --
            # and a blank team is what a defence joins on.
            named = sum(1 for r in rows if r.team)
            assert named >= 0.95 * len(rows), (
                f"{market} {season}: only {named}/{len(rows)} rows carry a team"
            )
    assert not strange, f"{market}: team code(s) nflverse never writes: {sorted(strange)}"


def test_i2_an_unaliased_team_code_fails_that_gate(monkeypatch) -> None:
    """INJECTION 2. Empty the alias table; GBP, KCC and the other six must be caught."""
    monkeypatch.setattr(mfl, "TEAM_ALIASES", {})
    known = _nflverse_teams()
    with markets.use("mfl_8_std"):
        rows = room.load_board(2024).rows
        strange = {r.team for r in rows if r.team and r.team not in known}
    assert strange, "an empty alias table produced no strange team codes; the gate is vacuous"


# --- G3: the board is pre-draft, by content -----------------------------------------------


def _draft_classes() -> dict[int, set[str]]:
    """NFL draft year -> normalised player names, from nflverse's id spine.

    THIS REPLACED A GITIGNORED SUBSCRIPTION FILE, and that is the whole point. The gate used to
    read `sim/data/ffa/raw_stats_<S+1>_wk0.csv`, which `.gitignore` excludes by design, so on a
    fresh clone it called `pytest.skip` -- and B8 recorded, in this same file, that a gate which
    skips is a gate that does not exist. It was skipping in exactly the situation it was written
    for: someone else's checkout.

    `nflverse/ff_playerids.parquet` carries `draft_year` for 12,391 players across the 2019-2026
    classes (356-409 players in each of the ones this gate needs). It is not committed either --
    every cache root is gitignored -- but it is RE-FETCHABLE FROM AN OPEN SOURCE, it is already
    the first entry in `runner.required_inputs`, and `sim/test_g_room.py` already requires it by
    name. So a checkout that can run any other sim gate can run this one.

    MEASURED EQUIVALENT: on all twelve market-seasons where the CSV is present, the two sources
    return the same verdict (zero leaks from both). The corroboration test below keeps the CSV
    in play whenever it happens to be on disk, so nothing is lost by switching the primary
    source; what is gained is that the primary no longer skips.
    """
    import polars as pl

    path, _root = room.resolve_input("nflverse/ff_playerids.parquet")
    frame = pl.read_parquet(path)
    out: dict[int, set[str]] = {}
    for name, year in frame.select(["name", "draft_year"]).iter_rows():
        if year is None or not name:
            continue
        out.setdefault(int(year), set()).add(room.normalize(str(name)))
    return out


@pytest.mark.parametrize("market", ALL_MARKETS)
def test_g3_no_board_carries_the_following_years_rookies(market) -> None:
    """G3. The vintage check that MFL's `asof` cannot carry on its own.

    `PERIOD=AUG15` selects drafts from 15 August ONWARD and MFL publishes no window end, so
    `Market.asof` is a lower bound rather than a measurement. What actually establishes that a
    2021 board was built before the 2021 season is that it contains no member of the 2022
    draft class.
    """
    classes = _draft_classes()
    for season in room.SEASONS[:-1]:
        rookies = classes.get(season + 1, set())
        assert len(rookies) >= 200, (
            f"only {len(rookies)} players in the {season + 1} draft class; a class that small "
            f"would make this gate pass by having nothing to find"
        )
        with markets.use(market):
            names = {room.normalize(r.name) for r in room.load_board(season).rows}
        leaked = sorted(names & rookies)
        assert not leaked, (
            f"{market} {season} board carries {len(leaked)} member(s) of the {season + 1} "
            f"draft class: {leaked[:8]}. That board was not built before that season."
        )


@pytest.mark.parametrize("market", ALL_MARKETS)
def test_i8_a_board_carrying_next_years_class_is_caught(market) -> None:
    """INJECTION. Ask the gate for the WRONG year and it must fire.

    Without this the gate is green whenever the draft-class lookup returns nothing useful, and
    the `>= 200` floor above only rules out one way of that happening. Every season's board is
    full of players from ITS OWN draft class and earlier, so comparing season S's board against
    class S must find someone -- if it does not, the join is broken rather than the board clean.
    """
    classes = _draft_classes()
    for season in room.SEASONS[:-1]:
        with markets.use(market):
            names = {room.normalize(r.name) for r in room.load_board(season).rows}
        assert names & classes.get(season, set()), (
            f"{market} {season} board shares no name with the {season} draft class, so the "
            f"name join is not working and the real check above cannot fire either"
        )


@pytest.mark.parametrize("market", ALL_MARKETS)
def test_the_ffa_drop_agrees_with_nflverse_when_it_is_present(market) -> None:
    """Corroboration, skipped by design when the subscription drop is absent.

    THIS ONE IS ALLOWED TO SKIP because it is not the gate -- it is a second opinion on the
    gate's source. The gate itself now runs off nflverse and cannot skip.
    """
    classes = _draft_classes()
    for season in room.SEASONS[:-1]:
        path = REPO / "sim" / "data" / "ffa" / f"raw_stats_{season + 1}_wk0.csv"
        if not path.exists():
            pytest.skip(f"{path.name} is not on disk; the FFA drop is gitignored by design")
        with path.open(encoding="utf-8", newline="") as handle:
            ffa = {
                room.normalize(row["player"])
                for row in csv.DictReader(handle)
                if str(row.get("draft_year") or "") == str(season + 1)
            }
        with markets.use(market):
            names = {room.normalize(r.name) for r in room.load_board(season).rows}
        assert bool(names & ffa) == bool(names & classes.get(season + 1, set())), (
            f"{market} {season}: the FFA drop and nflverse disagree about whether the board "
            f"carries the {season + 1} draft class"
        )


@pytest.mark.parametrize("market", ALL_MARKETS)
def test_g3_every_board_passes_the_leakage_guard(market) -> None:
    """The source allowlist and the kickoff date, on every market and every season."""
    with markets.use(market):
        for season in room.SEASONS:
            room.assert_pre_draft(room.load_board(season))


def test_i3_a_board_dated_after_kickoff_is_refused() -> None:
    """INJECTION 3. A board as of after the opener must be refused whatever its source."""
    board = room.SeasonBoard(
        season=2024,
        rows=(),
        provenance=("mfl_adp",),
        asof=room.date(2024, 9, 30),
        roots=("sim",),
    )
    with pytest.raises(ValueError, match="not before"):
        room.assert_pre_draft(board)


def test_i4_an_unlisted_provenance_is_refused() -> None:
    """INJECTION 4. G5's allowlist still governs: a market cannot smuggle a source past it."""
    board = room.SeasonBoard(
        season=2024,
        rows=(),
        provenance=("mfl_adp_endofseason",),
        asof=room.date(2024, 8, 15),
        roots=("sim",),
    )
    with pytest.raises(ValueError, match="non-pre-draft source"):
        room.assert_pre_draft(board)


def test_an_unrecognised_period_is_refused_rather_than_defaulted() -> None:
    """A PERIOD nobody has measured must not be stamped with a date nobody chose.

    THIS TEST USED TO ASSERT THE OPPOSITE, and that was the defect. `Market.asof` fell back to
    15 August for any unknown period, so `PERIOD=START` -- measured in `sim/mfl.py` as a
    different population with a different top three, partly in-season -- would have been
    stamped mid-August and walked straight through `room.assert_pre_draft`. The date check is
    the second of G5's two independent guards, and a fallback that always satisfies it leaves
    one.
    """
    for period in ("START", "DRAFT", "SEPT", ""):
        odd = dataclasses.replace(
            markets.get("mfl_8_std"), params={"fcount": 8, "period": period}
        )
        with pytest.raises(ValueError, match="no measured window start"):
            odd.asof(2024)
    ok = dataclasses.replace(markets.get("mfl_8_std"), params={"fcount": 8, "period": "JULY"})
    assert ok.asof(2024) == room.date(2024, 7, 1)


# --- G4: every response pinned, and named in preflight -------------------------------------


@pytest.mark.parametrize(
    "name,expected",
    [
        ("b8-ffc", "ffc_adp_standard_8_2024.json"),
        ("b8-mfl8", "mfl/mfl_adp_8_std_n_live_aug15_2024.json"),
    ],
)
def test_g4_preflight_names_the_markets_own_board(name, expected) -> None:
    """G4. The file the run drafts from is the file preflight checksums.

    Before B8 this list held the FFC filename unconditionally, so an MFL run would have
    checksummed five boards it never opened and none of the five it did. Preflight would then
    pass on a machine with no MFL pins at all and the run would die at the first `load_board`
    -- the exact mid-run failure preflight exists to prevent.
    """
    names = runner.required_inputs(runner.load_config(CONFIGS / f"{name}.toml"))
    assert expected in names, names
    # AND NOTHING FROM THE OTHER MARKET. A presence-only check passes on a preflight that
    # simply demands every market's pins, which would make a run fail for want of a board it
    # never opens -- and would still not prove the list follows the market.
    foreign = {
        "b8-ffc": "mfl/mfl_adp_8_std_n_live_aug15_2024.json",
        "b8-mfl8": "ffc_adp_standard_8_2024.json",
    }[name]
    assert foreign not in names, f"{name} preflights {foreign}, which it never opens"


def test_g4_a_missing_board_fails_in_preflight_naming_that_board(tmp_path, monkeypatch) -> None:
    """The failure must NAME THE MARKET'S OWN BOARD, not merely say `PREFLIGHT FAILED`.

    An earlier version asserted only the words `PREFLIGHT FAILED`, which the pre-B8 hardcoded
    FFC pin list produces just as readily -- the first missing input is `ff_playerids.parquet`
    and preflight stops there. So the test passed for exactly the defect its own docstring
    described. Here every OTHER input is present and only the MFL board is hidden, so the
    message can only name the board.
    """
    stage = tmp_path / "sim"
    stage.mkdir()
    for name in ("nflverse", "espn_draft_6012_2021.json"):
        source = room.SIM_CACHE / name
        if not source.exists():
            source = room.LIVE_CACHE / name
    # Point both roots at a tree holding everything except the MFL pins.
    monkeypatch.setattr(room, "SIM_CACHE", stage)
    monkeypatch.setattr(room, "LIVE_CACHE", tmp_path / "live")
    with pytest.raises(SystemExit) as caught:
        runner.preflight(runner.load_config(CONFIGS / "b8-mfl8.toml"))
    message = str(caught.value)
    assert "PREFLIGHT FAILED" in message
    missing = [n for n in runner.required_inputs(runner.load_config(CONFIGS / "b8-mfl8.toml"))]
    assert any(n in message for n in missing), message


@pytest.mark.parametrize("market", MFL_MARKETS)
def test_g4_every_declared_pin_is_on_disk_in_sims_own_root(market) -> None:
    """B8 fetched these. They must be present, and they must not be in the cockpit's cache."""
    for season in room.SEASONS:
        for name in markets.get(market).pins(season):
            _path, root = room.resolve_input(name)
            assert root == "sim", f"{name} resolved from the {root} root"


# --- G6: two markets cannot be confused ----------------------------------------------------


def test_g6_the_market_is_in_the_config_hash() -> None:
    """A checkpoint carries the config hash, so a hash blind to the market would let `--resume`
    append one market's units to another market's run and report the mixture as one config."""
    hashes = {
        runner.load_config(CONFIGS / f"{name}.toml").config_hash
        for name in ("b8-ffc", "b8-mfl8", "b8-mfl12")
    }
    assert len(hashes) == 3, "two of the three B8 configs hash the same"


def test_i5_the_market_alone_moves_the_hash(tmp_path) -> None:
    """INJECTION 5. Change ONLY the market and the hash must move.

    THE EARLIER VERSION OF THIS TEST PROVED NOTHING. It equalised `name` AND `market` together
    and asserted the hashes then collided -- which is true whether or not `market` is in the
    hash, because `name` alone carries the difference between the three B8 configs. Deleting
    `"market"` from `config_hash` left both this test and G6 green. Isolating the one field is
    the whole point of an injection.
    """
    mfl8 = runner.load_config(CONFIGS / "b8-mfl8.toml")
    moved = dataclasses.replace(mfl8, market="mfl_12_std")
    assert moved.config_hash != mfl8.config_hash, (
        "two runs differing ONLY in market hash the same, so `--resume` would append one "
        "market's units to the other market's checkpoint."
    )
    # And the same for the three fields that were silently missing before B8.
    for field, value in (
        ("projection", "walkforward"),
        ("historical_deltas", False),
        ("score_kickers", False),
    ):
        other = dataclasses.replace(mfl8, **{field: value})
        assert other.config_hash != mfl8.config_hash, f"{field} is not in the config hash"


def test_g6_two_markets_pin_to_different_files() -> None:
    """Eight-team and twelve-team are different experiments and cannot share a file on disk."""
    for season in room.SEASONS:
        eight = set(markets.get("mfl_8_std").pins(season))
        twelve = set(markets.get("mfl_12_std").pins(season))
        assert eight & twelve == {f"mfl/{mfl.players_pin(season)}"}, (
            f"{season}: the two MFL markets share {sorted(eight & twelve)}. Only the player "
            f"catalogue, which is not parameterised by FCOUNT, may be shared."
        )


def test_i6_every_query_parameter_reaches_the_pin_filename() -> None:
    """INJECTION 6. Change any ONE parameter and the pin must move -- every one, not just FCOUNT.

    `MflParams.slug` is the only thing keeping two markets off one file, and `fetch` skips the
    request when the file already exists. So a parameter missing from the slug means the second
    market silently ADOPTS the first one's board and measures a difference of exactly zero,
    while `meta()` reports the parameter it asked for rather than the one the file was fetched
    with. Two were missing: `is_keeper` and `is_mock`. The earlier version of this test proved
    the property for `fcount` alone, which is exactly why it did not catch them.

    `is_keeper` is the one that would have hurt. `sim/mfl.py` measures it as load-bearing --
    262 drafts against 287 unfiltered, the extra 25 being keeper and dynasty leagues whose ADP
    is a different ordering entirely.
    """
    base = mfl.MflParams()
    variants = {
        "fcount": dataclasses.replace(base, fcount=12),
        "is_ppr": dataclasses.replace(base, is_ppr=1),
        "is_mock": dataclasses.replace(base, is_mock=1),
        "is_keeper": dataclasses.replace(base, is_keeper="Y"),
        "period": dataclasses.replace(base, period="JULY"),
    }
    collisions = [
        field
        for field, other in variants.items()
        if mfl.adp_pin(2024, other) == mfl.adp_pin(2024, base)
    ]
    assert not collisions, (
        f"{collisions} do not reach the pin filename, so two markets differing only in "
        f"{collisions} would share one file on disk and measure no difference between them."
    )
    assert len({mfl.adp_pin(2024, v) for v in variants.values()}) == len(variants)


def test_the_query_and_the_filename_cannot_disagree_on_case() -> None:
    """`slug` lower-cases the period and `query` upper-cases it, so two params that fold to one
    filename cannot send two different requests."""
    lower, upper = mfl.MflParams(period="aug15"), mfl.MflParams(period="AUG15")
    assert mfl.adp_pin(2024, lower) == mfl.adp_pin(2024, upper)
    assert lower.query() == upper.query()


# --- what the board actually is -------------------------------------------------------------


@pytest.mark.parametrize("market", ALL_MARKETS)
def test_the_board_carries_only_positions_the_league_can_start(market) -> None:
    """MFL's raw pool carries IDP rows because some MFL leagues start defenders. A room with no
    IDP slot cannot draft one, so they are dropped at the adapter rather than renamed."""
    startable = {p for slot in room.STARTING_SLOTS for p in room.SLOT_ELIGIBILITY[slot]}
    with markets.use(market):
        for season in room.SEASONS:
            seen = {r.position for r in room.load_board(season).rows}
            assert seen <= startable, f"{market} {season}: undraftable {sorted(seen - startable)}"
            # BOTH DIRECTIONS. A subset check alone passes on a board that has silently LOST a
            # position -- dropping TE from the adapter's draftable set keeps `seen <= startable`
            # true, and the only thing that catches it today is an unrelated KeyError in
            # `fit_room`. A league that starts a position must be able to draft one.
            assert seen == startable, f"{market} {season}: no rows at {sorted(startable - seen)}"


@pytest.mark.parametrize("market", ALL_MARKETS)
def test_every_board_can_fill_the_draft(market) -> None:
    with markets.use(market):
        for season in room.SEASONS:
            assert len(room.load_board(season).rows) >= room.PICKS


def test_the_mfl_join_report_is_clean() -> None:
    """`mfl.join_rate` separates a CROSSWALK FAILURE from a DELIBERATE DROP, and only the first
    is a defect. The first version of that function conflated them and reported 2022 at 96.0%
    when all ten misses were team-aggregate rows that `NON_PLAYER` correctly excludes."""
    for season in room.SEASONS:
        report = mfl.join_rate(season, mfl.MflParams())
        assert report["unknown"] == 0, (
            f"{season}: {report['unknown']} ADP id(s) the catalogue cannot name, e.g. "
            f"{report['unknown_ids']}"
        )
        # EVERY ROW ACCOUNTED FOR, so a row cannot be lost by being counted in no bucket, and
        # matched cannot quietly collapse while `unknown` stays zero -- dropping ids from
        # `catalogue` moves them to `excluded`, which the bare `unknown == 0` check ignores.
        assert report["matched"] + report["excluded"] + report["unknown"] == report["rows"]
        assert report["rate"] >= 0.95, f"{season}: only {report['rate']:.1%} matched"


@pytest.mark.parametrize("market", ALL_MARKETS)
def test_g7_which_room_each_market_actually_produces(market) -> None:
    """G7. The scheduled set is DERIVED per market, and B8 found a market where it changes.

    `room.fit_room` puts a position on the SCHEDULE clock when the room drafts more of it than
    the board's top 128 supplies, and `room._best` then removes every scheduled position from
    the board the bots pick off. B1 validated a room whose scheduled set is exactly {DEF, K}.

    B8 RECORDED `{DEF, K, RB, WR}` FOR mfl_8_std HERE and called it a measurement to be
    reported rather than tuned away. That was right about the reporting and wrong about the
    measurement: the number came from the supply ratio, whose numerator is a whole eight-team
    draft and whose denominator is the market board's top 128, so the two windows coincide
    exactly when the market's team count matches the room's and every ratio collapses toward
    1.0. It was not measuring the room; it was measuring the mismatch between two windows.

    B9's clock ratio -- sd(pick) / sd(pick - rank) -- conditions on nothing and reads no
    window, and derives {DEF, K} in all three markets. So the assertion is now the same in
    every market, and it is checked against `expected_scheduled()`, which reads the league's
    own starting slots and shares no input with the classifier.
    """
    with markets.use(market):
        fit = room.fit_room()
    assert set(fit.scheduled) == set(room.expected_scheduled()) == {"DEF", "K"}


def test_g7_a_wider_scheduled_set_fails_the_run() -> None:
    """The gate must fire on the artifact, so a mis-specified room cannot exit zero."""
    payload = artifact.read(REPO / "sim" / "runs" / "b8-ffc.json")
    payload["fit"] = {
        "scheduled": ["DEF", "K", "RB", "WR"],
        "supply_ratio": {"RB": 1.047, "WR": 1.111},
    }
    assert any("G7 room-fidelity" in f for f in runner.gate_failures(payload)), (
        "a room that has taken RB and WR off the bots' board still passes every gate"
    )
    payload["fit"] = {"scheduled": ["DEF", "K"], "supply_ratio": {}}
    assert not any("G7 room-fidelity" in f for f in runner.gate_failures(payload))


def test_g7_a_real_fit_block_carries_the_field_the_gate_reads() -> None:
    """The dict-mutation test above proves `gate_failures` READS `fit.scheduled`. This proves a
    real run WRITES it -- without both, `artifact.fit_block` could stop emitting the key and
    G7 would never fire on anything again while every test stayed green.

    B8 ASSERTED `{DEF, K, RB, WR}` HERE, which was the defect rather than the design: its
    classifier was the supply ratio, whose numerator is an eight-team draft and whose
    denominator is the market board's top 128, so it collapsed toward 1.0 exactly when the
    market matched the room and scheduled two skill positions on mfl_8_std. B9 replaced it with
    the clock ratio and this now reads `{DEF, K}` in every market. The retired ratio is still
    emitted, and still says WR 1.111, which is why the second assertion below is kept -- it is
    the evidence that the number changed because the CLASSIFIER changed and not because the
    board did.
    """
    with markets.use("mfl_8_std"):
        block = artifact.fit_block(room.fit_room())
    assert set(block["scheduled"]) == {"DEF", "K"}
    assert set(block["scheduled"]) == set(room.expected_scheduled())
    assert block["supply_ratio"]["WR"] > room.SUPPLY_RATIO_CUT, (
        "the retired supply ratio no longer mis-classifies WR on mfl_8_std, so the defect B9 "
        "fixed is no longer reproducible from this artifact"
    )
    assert block["clock_ratio"]["WR"] > room.CLOCK_RATIO_CUT


def test_g7_the_shipped_mfl8_artifact_carries_the_failure() -> None:
    """It is IN the committed artifact, so the finding cannot be lost by rewriting the prose."""
    path = REPO / "sim" / "runs" / "b8-mfl8.json"
    if not path.exists():
        pytest.skip("b8-mfl8.json has not been produced yet")
    assert any("G7 room-fidelity" in f for f in runner.gate_failures(artifact.read(path)))


@pytest.mark.parametrize("season", room.SEASONS)
def test_an_unmapped_position_cannot_hide_among_the_deliberate_drops(season) -> None:
    """`catalogue` drops a NON_PLAYER row and an UNMAPPED row identically, and `join_rate`
    reports both as `excluded` -- so a vocabulary gap is invisible to the `unknown == 0` gate.

    Measured: removing `PK` from `POSITION_MAP` takes every kicker off the board, and `unknown`
    stays 0, `len(rows) >= PICKS` still holds, and the position-subset check still passes,
    because a smaller position set is still a subset. Every exclusion must be a DECLARED one.
    """
    report = mfl.join_rate(season, mfl.MflParams())
    unexplained = sorted(set(report["excluded_positions"]) - mfl.NON_PLAYER)
    assert not unexplained, (
        f"{season}: position(s) {unexplained} were dropped without being declared non-players. "
        f"A gap in POSITION_MAP looks exactly like a deliberate exclusion."
    )


def test_i7_a_vocabulary_gap_is_caught_where_the_join_gate_cannot_see_it(monkeypatch) -> None:
    """INJECTION 7. Remove one mapping; `unknown` stays 0 and the new check fires."""
    monkeypatch.setattr(
        mfl, "POSITION_MAP", {k: v for k, v in mfl.POSITION_MAP.items() if k != "PK"}
    )
    report = mfl.join_rate(2024, mfl.MflParams())
    assert report["unknown"] == 0, "the join gate still passes, which is the whole point"
    assert sorted(set(report["excluded_positions"]) - mfl.NON_PLAYER) == ["PK"]


def test_the_provenance_names_the_board_that_was_actually_read() -> None:
    """`projection.assert_pre_draft` allows a line to carry its OWN season only for the market
    board. Both sides used to be the FFC filename -- written by the code and checked by the
    code -- so on an MFL run that check was true by construction and blind to the real file.
    """
    with markets.use("mfl_8_std"):
        prefix = projection.same_season_sources()[0]
        source = markets.active().board_source(2024)
        assert not source.startswith("ffc_adp")
        assert source.startswith(prefix)
        assert f"{source}.json" == markets.active().pins(2024)[0].removeprefix("mfl/")
        # THE PREFIX MUST DISCRIMINATE. `"".startswith` is true of everything, and a prefix as
        # short as `mfl_adp_` would let a TWELVE-team board satisfy an eight-team run -- both
        # of which leave the whole leak gate green while switching it off.
        assert prefix, "an empty prefix makes projection.assert_pre_draft accept anything"
        assert not markets.get("mfl_12_std").board_source(2024).startswith(prefix)
        assert not "ffc_adp_standard_8_2024".startswith(prefix)
    with markets.use("ffc_12_std"):
        assert markets.active().board_source(2024) == "ffc_adp_standard_8_2024"
        assert not markets.get("mfl_8_std").board_source(2024).startswith(
            projection.same_season_sources()[0]
        )


def test_the_market_and_the_league_must_agree(tmp_path) -> None:
    """A market is a PAIR, and running one half against a different market's league is not one."""
    source = (CONFIGS / "b8-mfl8.toml").read_text(encoding="utf-8")
    bad = tmp_path / "bad.toml"
    bad.write_text(
        source.replace('league = "espn_davis_drive"', 'league = "espn_green_hope"'), "utf-8"
    )
    with pytest.raises(SystemExit, match="is declared for"):
        runner.load_config(bad)


def test_the_board_reports_every_root_it_was_built_from(monkeypatch) -> None:
    """An MFL board is built from TWO pins, and must report both roots.

    ON THIS MACHINE BOTH PINS RESOLVE FROM `sim`, so comparing the reported set against the
    computed set is true whether the code reads one pin or two -- the check was vacuous. So the
    roots are FORCED APART here: the catalogue is made to answer `live`, and the board must
    then say it was built from both. Reporting one root for a board half-read from the cockpit
    cache is the exact thing `room.resolve_input`'s docstring forbids.
    """
    real = room.resolve_input

    def split(name: str):
        path, root = real(name)
        return path, ("live" if "players" in name else root)

    monkeypatch.setattr(room, "resolve_input", split)
    with markets.use("mfl_8_std"):
        board = room.load_board(2024)
    assert set(board.roots) == {"sim", "live"}, board.roots


def test_the_generated_at_stamp_is_not_treated_as_provenance() -> None:
    """MFL stamps the response when it BUILDS it, so a 2019 request reads as today. It is
    recorded under a name that cannot be mistaken for the ADP window."""
    meta = mfl.meta(2021, mfl.MflParams())
    assert "generated_at" in meta
    assert "asof" not in meta and "end_date" not in meta


def test_the_artifact_records_which_market_it_was_measured_in() -> None:
    """Every number in an artifact is conditional on the market; two compared without it are
    two experiments compared as if they were one."""
    for name in ("b8-ffc", "b8-mfl8", "b8-mfl12"):
        path = REPO / "sim" / "runs" / f"{name}.json"
        if not path.exists():
            pytest.skip(f"{name}.json has not been produced yet")
        payload = artifact.read(path)
        expected = runner.load_config(CONFIGS / f"{name}.toml").market
        assert payload["market"]["name"] == expected
