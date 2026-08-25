"""Cockpit HTTP surface: the /api/state contract the page codes against."""

from __future__ import annotations

import re
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from audible.config import LeagueConfig
from audible.draft.board import DraftBoard, DraftEntry
from audible.draft.live import Pick
from audible.draft.service import CockpitService
from audible.server import create_app
from audible.server.state import build_state

POSITIONS = ["RB", "WR", "QB", "WR", "RB", "TE", "WR", "QB", "LB", "K"]


def _entry(i: int) -> DraftEntry:
    pos = POSITIONS[(i - 1) % len(POSITIONS)]
    return DraftEntry(
        player_id=f"p{i:03d}", name=f"Player {i:03d}", position=pos,
        eligible_positions=frozenset({pos}), team="XX", model="consensus",
        points=400.0 - i, modeled_xfp=0.0, carried=0.0, consensus=400.0 - i,
        vorp=400.0 - i, vorp_rank=i, consensus_rank=i, opp_rank=i,
        deviation=(i % 17 == 0), scarcity=400.0 - i, scarcity_rank=i,
        adp=float(i), adp_rank=i, value=0, flags=("riser",) if i % 5 == 0 else (),
    )


@pytest.fixture
def service(tmp_path: Path, sleeper_config: LeagueConfig) -> CockpitService:
    svc = CockpitService(sleeper_config, state_dir=tmp_path, slot_override=4)
    svc.board = DraftBoard("sleeper_boyfun", [_entry(i) for i in range(1, 201)])
    svc.session.draft_id = "d1"
    svc.session.draft_status = "drafting"
    svc.session.slot = 4
    svc.session.slot_source = "override"
    svc.health.last_success = time.time()
    return svc


@pytest.fixture
def client(service: CockpitService) -> TestClient:
    return TestClient(create_app(service, warm=False))


def test_state_contract(client: TestClient, service: CockpitService) -> None:
    service.session.picks = [
        Pick(pick_no=n, round=1, draft_slot=n, player_id=f"p{n:03d}") for n in range(1, 4)
    ]
    body = client.get("/api/state").json()

    assert body["ok"] and body["board_ready"]
    assert body["league"]["superflex"] is True
    assert body["draft"]["started"] is True
    assert body["sync"]["status"] == "live"

    clock = body["clock"]
    assert clock["current_pick"] == 4
    assert clock["my_slot"] == 4
    assert clock["picks_until_me"] == 0  # slot 4 is on the clock at pick 4
    assert clock["survival_horizon"] == 17
    assert clock["opponent_picks_until_horizon"] == 12

    # drafted players are gone from the board
    ids = {p["id"] for p in body["best_available"]}
    assert "p001" not in ids and "p004" in ids


def test_three_ranks_are_three_columns(client: TestClient) -> None:
    """Collapsing them hides the disagreement, which is the whole signal."""
    body = client.get("/api/state").json()
    player = body["best_available"][0]
    for key in ("consensus_rank", "vorp_rank", "opp_rank", "survival", "deviation", "flags"):
        assert key in player, key
    assert any(p["deviation"] for p in body["best_available"]), "deviation must be surfaced"


def test_grab_now_populates_on_my_own_clock(client: TestClient, service: CockpitService) -> None:
    """The headline feature, and the one that was dark at every one of my own picks."""
    service.session.picks = [
        Pick(pick_no=n, round=1, draft_slot=n, player_id=f"p{n:03d}") for n in range(1, 4)
    ]
    body = client.get("/api/state").json()
    assert body["clock"]["picks_until_me"] == 0
    assert body["grab_now"], "grab-now must not be empty while I am on the clock"
    assert all(p["grab_now"] for p in body["grab_now"])
    assert len(body["grab_now"]) <= 5


def test_survival_falls_as_the_wait_grows(client: TestClient, service: CockpitService) -> None:
    service.session.picks = [
        Pick(pick_no=n, round=1, draft_slot=n, player_id=f"p{n:03d}") for n in range(1, 4)
    ]
    players = client.get("/api/state").json()["best_available"]
    early = next(p for p in players if p["id"] == "p005")   # ADP 5, 12 picks to survive
    late = next(p for p in players if p["id"] == "p060")    # ADP 60, comfortably safe
    assert early["survival"] < 0.2
    assert late["survival"] > 0.99


def test_grab_now_and_survival_never_contradict(
    client: TestClient, service: CockpitService
) -> None:
    """Caught by the 2025 replay: grab-now and survival were two different models, so the
    board rendered "GRAB NOW ... 100%". They are now two views of one model, and a row can
    never claim a player is both about to vanish and certain to last.
    """
    service.session.picks = [
        Pick(pick_no=n, round=1, draft_slot=n, player_id=f"p{n:03d}") for n in range(1, 4)
    ]
    body = client.get("/api/state").json()
    assert body["clock"]["opponent_picks_until_horizon"] == 12

    for p in body["best_available"]:
        if p["grab_now"]:
            assert p["survival"] < 0.5, f"{p['name']} is grab-now at {p['survival']:.0%} survival"
        else:
            assert p["survival"] >= 0.5, f"{p['name']} is safe at {p['survival']:.0%} survival"


def test_survival_is_ranked_not_raw_adp(client: TestClient, service: CockpitService) -> None:
    """A stale ADP must not read as safety. A player whose ADP has already been blown past --
    still on the board long after the market said he'd go -- is the MOST likely to go next,
    not the least."""
    service.session.picks = [
        Pick(pick_no=n, round=1, draft_slot=(n % 10) + 1, player_id=f"p{n + 20:03d}")
        for n in range(1, 60)
    ]
    body = client.get("/api/state").json()
    top = body["best_available"][0]
    assert top["survival"] < 0.5, "the best remaining player by ADP must read as at-risk"
    assert top["grab_now"] is True


def test_every_rosterable_position_is_servable(
    client: TestClient, service: CockpitService
) -> None:
    """Gate 13. A global top-N by value held 2 LBs and ZERO Ks out of 7,621 available, so
    every position filter downstream read a pool that had already been cut. Each rosterable
    position the board actually holds must reach the payload."""
    body = client.get("/api/state").json()
    served = {p["position"] for p in body["best_available"]}
    on_board = {e.position for e in service.board.entries}
    missing = on_board - served
    assert not missing, f"positions on the board but never served: {sorted(missing)}"


def test_position_depth_survives_a_lopsided_board(
    tmp_path: Path, sleeper_config: LeagueConfig
) -> None:
    """The real shape of the bug: one position dominating the value ranking must not squeeze
    the others out of the payload entirely."""
    entries = [_entry(i) for i in range(1, 400)]
    # Make every LB rank below every other position, as tackle-scoring IDP does in practice.
    entries.sort(key=lambda e: (e.position == "LB", e.vorp_rank))
    svc = CockpitService(sleeper_config, state_dir=tmp_path, slot_override=4)
    svc.board = DraftBoard("sleeper_boyfun", entries)
    svc.session.draft_status = "drafting"

    served = build_state(svc)["best_available"]
    lbs = [p for p in served if p["position"] == "LB"]
    assert len(lbs) >= 10, f"only {len(lbs)} LBs served from a board holding many"


def test_unpriced_players_are_available_not_absent(
    tmp_path: Path, sleeper_config: LeagueConfig
) -> None:
    """"Unpriced" must mean unknown survival, never high survival -- and never omitted."""
    import dataclasses

    entries = [
        e if i % 3 else dataclasses.replace(e, adp=None, adp_rank=None)
        for i, e in enumerate(_entry(i) for i in range(1, 60))
    ]
    svc = CockpitService(sleeper_config, state_dir=tmp_path, slot_override=4)
    svc.board = DraftBoard("sleeper_boyfun", entries)
    svc.session.draft_status = "drafting"
    svc.session.picks = [
        Pick(pick_no=n, round=1, draft_slot=n, player_id=f"p{n:03d}") for n in range(1, 4)
    ]

    served = build_state(svc)["best_available"]
    unpriced = [p for p in served if not p["adp_known"]]
    assert unpriced, "unpriced players must still be served"
    assert all(p["adp_known"] is False for p in unpriced)


def test_mark_taken_and_undo_round_trip(client: TestClient) -> None:
    before = {p["id"] for p in client.get("/api/state").json()["best_available"]}
    assert "p007" in before

    after = client.post("/api/taken", json={"player_id": "p007"}).json()
    assert "p007" not in {p["id"] for p in after["best_available"]}

    # survives a refresh
    assert "p007" not in {p["id"] for p in client.get("/api/state").json()["best_available"]}

    undone = client.post("/api/taken/undo", json={"player_id": "p007"}).json()
    assert "p007" in {p["id"] for p in undone["best_available"]}


def test_mark_taken_advances_the_clock(client: TestClient, service: CockpitService) -> None:
    """Reversal of the old contract, deliberately -- see test_service. A hand-entered pick is
    a pick: it is numbered, attributed to the team on the clock, and it moves the draft on."""
    service.session.picks = [
        Pick(pick_no=n, round=1, draft_slot=n, player_id=f"p{n:03d}") for n in range(1, 4)
    ]
    before = client.get("/api/state").json()["clock"]["current_pick"]
    body = client.post("/api/taken", json={"player_id": "p050"}).json()
    assert before == 4
    assert body["clock"]["current_pick"] == 5
    # ...and it landed on slot 4, whose pick it was -- not on slot 0.
    marked = next(p for p in body["recent_picks"] if p["name"].endswith("050"))
    assert marked["slot"] == 4


def test_board_not_ready_explains_itself(
    tmp_path: Path, sleeper_config: LeagueConfig
) -> None:
    svc = CockpitService(sleeper_config, state_dir=tmp_path)
    with TestClient(create_app(svc, warm=False)) as c:
        body = c.get("/api/state").json()
    assert body["board_ready"] is False
    assert body["message"] and "Building" in body["message"]
    assert "best_available" not in body  # never serve a partial board silently


def test_board_failure_is_reported_not_swallowed(
    tmp_path: Path, sleeper_config: LeagueConfig
) -> None:
    svc = CockpitService(sleeper_config, state_dir=tmp_path)
    svc.board_error = "RuntimeError: nflverse unreachable"
    with TestClient(create_app(svc, warm=False)) as c:
        body = c.get("/api/state").json()
    assert body["ok"] is False
    assert "nflverse unreachable" in body["message"]


def test_healthz_asserts_the_board_not_just_liveness(
    client: TestClient, service: CockpitService, tmp_path: Path, sleeper_config: LeagueConfig
) -> None:
    ok = client.get("/healthz")
    assert ok.status_code == 200
    assert ok.json()["players"] == 200

    starved = CockpitService(sleeper_config, state_dir=tmp_path)
    with TestClient(create_app(starved, warm=False)) as c:
        bad = c.get("/healthz")
    assert bad.status_code == 503
    assert bad.json()["ok"] is False


def test_stale_sync_is_visible(client: TestClient, service: CockpitService) -> None:
    service.health.last_success = time.time() - 45
    body = client.get("/api/state").json()
    assert body["sync"]["status"] == "failing"
    assert body["sync"]["age_s"] >= 45


def test_superflex_qb_run_outranks_other_runs(
    client: TestClient, service: CockpitService
) -> None:
    """In a superflex league a QB run is the most consequential thing between your picks."""
    qbs = [e.player_id for e in service.board.entries if e.position == "QB"][:4]
    wrs = [e.player_id for e in service.board.entries if e.position == "WR"][:5]
    ids = wrs + qbs
    service.session.picks = [
        Pick(pick_no=n + 1, round=1, draft_slot=(n % 10) + 1, player_id=pid)
        for n, pid in enumerate(ids)
    ]
    runs = client.get("/api/state").json()["runs"]
    assert runs, "a 4-QB burst in the last 10 must raise a run"
    assert runs[0]["position"] == "QB"
    assert runs[0]["severity"] == "high"
    assert "SUPERFLEX" in runs[0]["text"]


def test_index_page_is_served(client: TestClient) -> None:
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


def test_the_page_is_drivable_with_a_thumb(client: TestClient) -> None:
    """A phone is the draft-night fallback, so the touch layer is part of the contract.

    This cannot test layout -- there is no browser in CI -- but it can stop the pieces
    from being deleted. Each assertion below is one thing that was measured broken in a
    real browser at iPhone width: the mark button was 18x18 with a transparent border
    revealed only by :hover, which a finger never fires; the roster sat 970px down the
    page with no way to reach it but scrolling; and Undo existed only inside a panel that
    was itself off-screen.
    """
    page = client.get("/").text

    # The bar is the only navigation on a phone. All four controls, or none of them work.
    for control in ("thumbBar", "thumbBoard", "thumbRoster", "thumbRuns", "thumbUndo"):
        assert f'id="{control}"' in page, control

    # Touch sizing is keyed on hover:none, not on width -- the question is whether a
    # finger is driving, not how wide the glass is.
    assert "@media (hover:none)" in page
    assert "width:44px;height:44px" in page, "the mark button must be a real touch target"

    # The bar's own display:none MUST be declared before the media query that turns it on.
    # It was not, and an unlayered rule later in the file won on source order -- the bar
    # rendered 0x0 and every tap went to the board behind it.
    assert page.index("#thumbBar{") < page.index("#thumbBar{display:flex}")

    # iOS synthesises mouse events late and drops them when a touch becomes a scroll.
    assert 'tr.addEventListener("pointerdown"' in page
    assert 'tr.addEventListener("mousedown"' not in page


# Hover cannot be a prerequisite for anything a finger has to do. iOS resolves a first tap to
# a hover state and then LEAVES it there, so an ungated :hover rule does two bad things: it
# hides an affordance until a wasted tap reveals it, and it then sticks, painting a control
# that is not active as though it were. The original P0 was the first of those. The second is
# live in the position tabs, where `.tab:hover` and `.tab[aria-pressed="true"]` differ only by
# a border -- so after tapping RB then WR, both look selected.
HOVER_ALLOWED_UNGATED = frozenset({
    # A scrollbar thumb has no touch affordance to reveal and no state to be confused with.
    "::-webkit-scrollbar-thumb:hover",
})


def _hover_rules_outside_a_hover_gate(page: str) -> list[str]:
    """Every selector carrying :hover that is not inside `@media (hover:hover)`.

    Comments are stripped first -- this file explains the hover problem in prose that
    mentions the very selectors being checked -- and braces are counted rather than the
    sheet regexed, so a rule nested deeper inside the gate still counts as gated.
    """
    style = page[page.index("<style>"): page.index("</style>")].replace(chr(13), "")
    style = re.sub(r"/\*.*?\*/", "", style, flags=re.S)

    out: list[str] = []
    gate_depth = 0
    for raw in style.split(chr(10)):
        line = raw.strip()
        if not line:
            continue
        opens_gate = "@media (hover:hover)" in line
        if ":hover" in line and not opens_gate and gate_depth == 0:
            selector = line.split("{")[0].strip()
            if selector and selector not in HOVER_ALLOWED_UNGATED:
                out.append(selector)
        if opens_gate:
            gate_depth = line.count("{") - line.count("}")
            continue
        if gate_depth > 0:
            gate_depth += line.count("{") - line.count("}")
    return out


def test_no_control_depends_on_hover(client: TestClient) -> None:
    """Every :hover rule must sit behind `@media (hover:hover)`.

    Keyed on the media feature rather than on width, because the question is whether a
    pointer that can hover is driving -- not how wide the glass is.
    """
    leaked = _hover_rules_outside_a_hover_gate(client.get("/").text)
    assert not leaked, f"hover rules reachable on a touch device: {leaked}"


def test_the_mark_button_is_styled_without_hover(client: TestClient) -> None:
    """The touch rule must stand alone, not tie with a hover rule that outweighs it.

    `.prow:hover .mark` is specificity (0,3,0); the touch rule is (0,1,0). While both are
    live on a phone the button only looks right because the two happen to set identical
    values -- change one and the phone silently loses the button again. Selection stays
    ungated on purpose: it is a real state a finger can reach.
    """
    page = client.get("/").text
    assert ".prow.sel .mark{" in page, "selection must style the mark button on any device"
    assert ".prow:hover .mark" not in _hover_rules_outside_a_hover_gate(page), (
        "the hover rule outweighs the touch rule on specificity; it must not be live on touch"
    )


def test_other_teams_appear_as_manual_picks_land(
    tmp_path: Path, sleeper_config: LeagueConfig
) -> None:
    """Reported symptom: "no other teams ever appear". With every pick attributed to slot 0
    there was only ever one team."""
    svc = CockpitService(sleeper_config, state_dir=tmp_path, slot_override=4)
    svc.board = DraftBoard("sleeper_boyfun", [_entry(i) for i in range(1, 60)])
    svc.session.draft_status = "drafting"
    svc.session.slot, svc.session.slot_source = 4, "override"
    for i in range(1, 13):
        svc.mark_taken(f"p{i:03d}")

    teams = build_state(svc)["teams"]
    assert len(teams) == 10
    populated = [t for t in teams if t["picks"]]
    assert len(populated) == 10, "all ten teams should hold a pick after 12 marks"
    mine = next(t for t in teams if t["is_me"])
    assert mine["slot"] == 4
    assert len(mine["picks"]) == 1, "I own exactly my own pick, not all twelve"


def test_unresolved_slot_claims_nobody(tmp_path: Path, sleeper_config: LeagueConfig) -> None:
    """Absence of information must not render as slot 0 -- the same class of error as
    survival=1.0 for an unpriced player."""
    svc = CockpitService(sleeper_config, state_dir=tmp_path)  # no override
    svc.board = DraftBoard("sleeper_boyfun", [_entry(i) for i in range(1, 60)])
    svc.session.draft_status = "drafting"
    for i in range(1, 13):
        svc.mark_taken(f"p{i:03d}")

    state = build_state(svc)
    assert state["clock"]["my_slot"] is None
    assert state["clock"]["my_slot_source"] == "unresolved"
    assert sum(s["filled"] for s in state["roster"]["slots"]) == 0
    assert not any(t["is_me"] for t in state["teams"])
