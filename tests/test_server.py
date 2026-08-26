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


# --------------------------------------------------------------------------------------
# THE TURN, and the touch defects found driving it.
#
# Seat 8 of 8 does not pick once and wait -- the snake hands it two picks at a time (8 and
# 9, 24 and 25, 40 and 41, 56 and 57) and then goes quiet for fourteen. Everything below
# pins something that was silently wrong for a thumb on that seat.
# --------------------------------------------------------------------------------------

ESPN_TEAMS = 8


def _espn_slot(pick_no: int) -> int:
    rnd, idx = divmod(pick_no - 1, ESPN_TEAMS)
    return idx + 1 if rnd % 2 == 0 else ESPN_TEAMS - idx


def _espn_client_on_pick(
    tmp_path: Path, espn_config: LeagueConfig, current_pick: int, my_slot: int = 8
) -> TestClient:
    """League B at seat 8 with the clock parked on `current_pick`."""
    svc = CockpitService(espn_config, state_dir=tmp_path, slot_override=my_slot)
    svc.board = DraftBoard("espn_davis_drive", [_entry(i) for i in range(1, 201)])
    svc.session.draft_id = "d1"
    svc.session.draft_status = "drafting"
    svc.session.slot = my_slot
    svc.session.slot_source = "override"
    svc.health.last_success = time.time()
    svc.session.picks = [
        Pick(pick_no=n, round=(n - 1) // ESPN_TEAMS + 1,
             draft_slot=_espn_slot(n), player_id=f"p{n:03d}")
        for n in range(1, current_pick)
    ]
    return TestClient(create_app(svc, warm=False))


@pytest.mark.parametrize("pick,partner", [(8, 9), (24, 25), (40, 41), (56, 57)])
def test_the_turn_reports_zero_opponents_before_my_next_pick(
    tmp_path: Path, espn_config: LeagueConfig, pick: int, partner: int
) -> None:
    """The first pick of a turn: both picks are mine, nobody picks between them.

    This is the signal the header renders. `opponent_picks_until_horizon == 0` while on the
    clock is the only place the two-picks case is derivable from the payload.
    """
    clock = _espn_client_on_pick(tmp_path, espn_config, pick).get("/api/state").json()["clock"]
    assert clock["picks_until_me"] == 0, "seat 8 must be on the clock at the turn"
    assert clock["opponent_picks_until_horizon"] == 0
    assert clock["survival_horizon"] == partner


@pytest.mark.parametrize("pick", [9, 25, 41, 57])
def test_the_second_pick_of_the_turn_faces_the_full_gap(
    tmp_path: Path, espn_config: LeagueConfig, pick: int
) -> None:
    """The second pick of the turn is still mine, but fourteen rivals follow it.

    The pair must not read as two picks twice -- after the second one the wait is real, and
    that is exactly when survival matters most.
    """
    clock = _espn_client_on_pick(tmp_path, espn_config, pick).get("/api/state").json()["clock"]
    assert clock["picks_until_me"] == 0
    assert clock["opponent_picks_until_horizon"] == 14


def test_the_page_renders_the_turn_rather_than_one_pick_number(client: TestClient) -> None:
    """The payload carried the turn all along; the page printed one number and dropped it."""
    page = client.get("/").text
    assert "twoOnClock" in page, "the page must derive the two-picks case"
    assert "clock.opponent_picks_until_horizon === 0" in page
    assert "Two picks on the clock" in page
    assert 'clock.current_pick + "+" + clock.survival_horizon' in page, (
        "the header pick number must name BOTH picks, not just the one on the clock"
    )


def test_pressing_mark_gives_feedback_even_though_the_row_is_selected(
    client: TestClient,
) -> None:
    """`.prow.sel .mark` (0,3,0) is ungated and outranked `.mark:active` (0,2,0).

    The row is always `.sel` at press time -- the button's stopPropagation is on `click`, so
    pointerdown has already bubbled and painted the selection. The press therefore changed
    nothing on screen. Only a rule at (0,4,0) or better survives that.
    """
    page = client.get("/").text
    assert ".prow.sel .mark:active" in page, (
        "press feedback must outrank the ungated selection rule, or a tap looks like nothing"
    )

def test_cursor_help_does_not_promise_a_tooltip_a_finger_cannot_get(
    client: TestClient,
) -> None:
    """`cursor:help` on the column headers advertises `title=` text with no touch equivalent."""
    page = client.get("/").text
    style = page[page.index("<style>"): page.index("</style>")]
    style = re.sub(r"/\*.*?\*/", "", style, flags=re.S)
    assert "@media (hover:hover){.ptable thead th{cursor:help}}" in style
    assert "cursor:help" not in style.split("@media (hover:hover){.ptable thead th")[0], (
        "cursor:help must not be live on a touch device"
    )


def test_the_panel_head_wraps_rather_than_overflowing_the_phone(client: TestClient) -> None:
    """Title + seven 44px tabs + the search box do not fit one row at 393px.

    Page-level horizontal overflow is not a scrollbar on a phone -- iOS shrinks the WHOLE
    page to fit, so a dense board silently renders at 63% with nothing looking broken.
    Measured at 393px: the head laid out 623px wide before this, 383px after.
    """
    page = client.get("/").text
    style = page[page.index("<style>"): page.index("</style>")]
    touch = style[style.index("@media (hover:none)"):]
    assert ".phead{height:auto;flex-wrap:wrap" in touch, (
        "the panel head must wrap on touch or the page overflows the viewport"
    )
    assert "flex:1 0 100%" in touch, "search must take its own line rather than push the row"


# --------------------------------------------------------------------------------------
# KEYBOARD-FIRST ENTRY. Eric drafts from the desktop and entry speed is the bottleneck on
# the night, so every one of these is about not having to reach for the mouse.
# --------------------------------------------------------------------------------------


def test_the_cursor_starts_in_the_search_box(client: TestClient) -> None:
    """No `/` to remember and no click to make -- the draft is typed, not clicked."""
    page = client.get("/").text
    # `$("q").focus()` already existed inside the "/" handler, so its mere presence proves
    # nothing. What matters is a focus at INIT -- assert it sits in the wiring block right
    # after buildTabs({}), not somewhere in a key handler.
    i = page.index("buildTabs({});")
    assert '$("q").focus();' in page[i:i + 400], (
        "the search box must be focused at init, not only reachable via '/'"
    )


def test_arrows_move_the_highlight_without_leaving_the_search_box(client: TestClient) -> None:
    """Type a partial name, arrow to the right man, Enter -- all without losing the caret.

    `select()` focuses the row it selects, which would drop the caret out of the box on the
    first arrow. keepFocus is what makes type-then-arrow possible.
    """
    page = client.get("/").text
    assert "function select(scope, id, scroll, keepFocus)" in page
    assert "if (!keepFocus) n.el.focus({ preventScroll: true });" in page
    assert "function moveSelection(delta, keepFocus)" in page
    assert 'e.key === "ArrowDown" || e.key === "ArrowUp"' in page, (
        "arrows must be handled inside the typing branch, not only outside it"
    )


def test_enter_marks_the_highlighted_row_not_whatever_sorted_first(client: TestClient) -> None:
    """With arrows live inside the box, the highlight is a choice -- Enter must honour it."""
    page = client.get("/").text
    assert 'if (S.sel && S.sel.scope === "best")' in page
    assert "if (!S.query) return null;" in page, (
        "Enter into an empty box must never mark anybody -- the box is focused on load"
    )


def test_every_action_has_a_key(client: TestClient) -> None:
    """mark, undo, and section switching must each be reachable with no pointer."""
    page = client.get("/").text
    for frag in ('case "t": case "T":',            # mark selected
                 'case "u": case "U":',            # undo
                 'case "Enter":',                  # mark selected, outside the box
                 'case "g": case "G":',            # grab now
                 'case "b": case "B":',            # best available
                 'case "r": case "R":',            # roster
                 'case "c": case "C":'):           # runs & cliffs
        assert frag in page, f"missing keyboard binding: {frag}"
    assert "function jumpToScope(scope)" in page
    assert "function showSection(view)" in page


def test_digit_shortcuts_are_contiguous_with_no_dead_keys(client: TestClient) -> None:
    """The digit was the index into the FULL tab array, so each league carried dead keys.

    League B showed an LB tab that could never match a player and swallowed 7 and 8 while
    stranding DEF on 9; League A swallowed 9. The index is now over the VISIBLE tabs, so
    both leagues get a contiguous run and an unmapped digit is left alone rather than eaten.
    """
    page = client.get("/").text
    assert "BASE_TABS" not in page and "EXTRA_TABS" not in page, "the split arrays are gone"
    assert "var TABS = [" in page
    assert "if (idx < S.tabKeys.length) { setFilter(S.tabKeys[idx]); e.preventDefault(); }" in page
    assert 'id="legendDigits"' in page, "the legend must report the real range, not a literal"


def test_a_tab_that_has_appeared_never_disappears(client: TestClient) -> None:
    """`present` is the served pool, which is the top N -- a position can drop out of it.

    If a tab vanished mid-draft every digit after it would renumber under the user's
    fingers between one pick and the next.
    """
    page = client.get("/").text
    assert "for (var key in present) { if (present[key]) S.seenPos[key] = true; }" in page
    assert "var hidden = !!t.opt && !S.seenPos[t.k];" in page
    assert 'if (sl && sl.indexOf("FLEX") === -1) present[sl] = true;' in page, (
        "seed from the league's own starting slots so DEF and K have tabs from render one"
    )
