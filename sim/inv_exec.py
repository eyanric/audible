"""EXECUTION invariants -- the failures that cost picks without touching the board.

The board can be perfect and the draft still go wrong: a double-marked player, an undo that
greys itself out while the pick is still reversible on the server, a manual mark and a synced
pick landing as two entries, a restart that loses the overrides. None of these is an ordering
question and none is visible to any arm comparison.

WHAT IS SERVER-SIDE AND WHAT IS NOT, stated rather than skipped silently, because the brief
asks and because the honest answer is a split:

  SERVER-SIDE, driven here through `TestClient` against the real FastAPI app --
    exec_double_mark      marking one id twice records exactly one pick
    exec_undo_roundtrip   undo restores exactly the prior state
    exec_undo_no_stack    undo works with NO local stack -- the server is the authority
    exec_mark_then_sync   a manual mark and the same player arriving via sync dedupe to one
    exec_restart          state written to the state dir survives being re-read

  BROWSER-ONLY, and NOT asserted here --
    `S.markPending`       the in-page guard that stops a second POST while one is in flight
    `S.takenStack`        the local undo stack; no localStorage, dies on reload
    `S.complete`          the client-side 129th-pick wall. The endpoint answers 200 regardless
    the Undo button's enabled state and label

  Those four live in `index.html` and need Playwright; `tests/test_ui_desktop.py` already
  drives a real browser and already covers the undo control. What this module can do is assert
  the SERVER half of each browser property, so a regression in the half that persists is
  caught even though the half that renders is not. `exec_undo_no_stack` is exactly that: the
  local stack is browser state, but "the pick is still undoable on the server" is not, and it
  is the half that made the original bug a bug.

MCP AND HTTP ARE THE SAME STATE. `mark_taken`/`undo_taken` are reachable over MCP as well, and
`app.py` notes that MCP rides the same process and the same service instance as the UI, so the
two are interchangeable ways to reach identical state. Only the HTTP surface is driven here;
that equivalence is recorded rather than re-asserted.
"""

from __future__ import annotations

from typing import Any

from .invariants import EXEC, Ledger


def _service(tmp: Any) -> Any:
    """A real `CockpitService` with a real board, writing to a scratch state dir.

    Modelled on `tests/test_server.py`'s fixture rather than invented, so this exercises the
    same construction the HTTP contract tests do.
    """
    from audible.draft.board import DraftBoard, DraftEntry
    from audible.draft.service import CockpitService

    from .inv_sync import league_config

    positions = ["RB", "WR", "QB", "WR", "RB", "TE", "WR", "QB", "K", "DEF"]

    def entry(i: int) -> DraftEntry:
        pos = positions[(i - 1) % len(positions)]
        return DraftEntry(
            player_id=f"p{i:03d}", name=f"Player {i:03d}", position=pos,
            eligible_positions=frozenset({pos}), team="XX", model="consensus",
            points=400.0 - i, modeled_xfp=0.0, carried=0.0, consensus=400.0 - i,
            vorp=400.0 - i, vorp_rank=i, consensus_rank=i, opp_rank=i,
            deviation=False, scarcity=400.0 - i, scarcity_rank=i,
            adp=float(i), adp_rank=i, value=0, flags=(),
        )

    svc = CockpitService(league_config(), state_dir=tmp, slot_override=4)
    svc.board = DraftBoard("espn_davis_drive", [entry(i) for i in range(1, 201)])
    svc.session.draft_id = "d1"
    svc.session.draft_status = "drafting"
    svc.session.slot = 4
    svc.session.slot_source = "override"
    return svc


def check_double_mark(ledger: Ledger, tmp: Any) -> None:
    """A second mark of the same id records nothing. The guard is server-side and real.

    The browser's `S.markPending` stops the second POST from being SENT; this asserts the other
    half -- that if one is sent anyway (a double-tap that beats the guard, a retry, a second
    tab, an MCP call racing the UI) the server still records one pick. `mark_taken` checks
    membership and appends inside one `RLock`, so two concurrent POSTs in FastAPI's threadpool
    serialize.
    """
    from fastapi.testclient import TestClient

    from audible.server import create_app

    svc = _service(tmp)
    client = TestClient(create_app(svc, warm=False))
    scope = ledger.scoped(surface="http")

    first = client.post("/api/taken", json={"player_id": "p001"})
    second = client.post("/api/taken", json={"player_id": "p001"})
    marked = [p for p in svc.session.manual_picks if p.player_id == "p001"]
    scope.check(
        len(marked) == 1, EXEC, "exec_double_mark",
        f"marking p001 twice recorded {len(marked)} picks. `S.markPending` is a browser guard "
        f"and cannot be relied on: a retry, a second tab, or an MCP call racing the UI all "
        f"reach this endpoint without it.",
        first=first.status_code, second=second.status_code, recorded=len(marked),
    )


def check_undo(ledger: Ledger, tmp: Any) -> None:
    """Undo restores exactly the prior state -- and works with no local stack.

    THE ORIGINAL BUG WAS THE RELOAD. `takenStack` lives in one page session with no
    localStorage behind it, so a refresh emptied it and greyed out the Undo control while the
    pick was still perfectly undoable on the server. The button is browser state; the
    reversibility is not, and this asserts the half that is not.
    """
    from fastapi.testclient import TestClient

    from audible.server import create_app

    svc = _service(tmp)
    client = TestClient(create_app(svc, warm=False))
    scope = ledger.scoped(surface="http")

    before = list(svc.session.taken_ids())
    client.post("/api/taken", json={"player_id": "p002"})
    client.post("/api/taken/undo", json={"player_id": "p002"})
    after = list(svc.session.taken_ids())
    scope.check(
        sorted(after) == sorted(before), EXEC, "exec_undo_roundtrip",
        f"undo did not restore the prior state: {sorted(before)} -> {sorted(after)}",
        before=sorted(before), after=sorted(after),
    )

    # A FRESH CLIENT, standing in for a reloaded page: no local stack at all. The pick must
    # still be undoable, because the server is where it lives.
    client.post("/api/taken", json={"player_id": "p003"})
    reloaded = TestClient(create_app(svc, warm=False))
    undone = reloaded.post("/api/taken/undo", json={})
    scope.check(
        "p003" not in svc.session.taken_ids(), EXEC, "exec_undo_no_stack",
        "undo with no local stack failed to reverse the pick. `takenStack` is browser state "
        "that dies on reload; the server is the authority and a reloaded page must still be "
        "able to undo.",
        status=undone.status_code, taken=sorted(svc.session.taken_ids()),
    )


def check_mark_then_sync(ledger: Ledger, tmp: Any) -> None:
    """A manual mark and the same player arriving via sync are ONE taken entry, not two."""
    from audible.draft.live import Pick

    svc = _service(tmp)
    scope = ledger.scoped(surface="service")

    svc.mark_taken("p004")
    # The same player, now arriving from the platform. `_reconcile_manual` is the real dedup
    # and `_apply` is its only caller, so BOTH are asserted: calling the function alone would
    # prove a helper works while the wiring that reaches it could be gone.
    #
    # (Assigning `session.picks` and reading `effective_picks()` without this reported a
    # duplicate on my first run. That was the harness bypassing production, not a defect:
    # `taken_ids()` is a set union and dedupes regardless, while `effective_picks()` is a plain
    # concatenation that relies on reconciliation having already happened.)
    svc.session.picks = [Pick(pick_no=1, round=1, draft_slot=1, player_id="p004")]
    svc._reconcile_manual()  # noqa: SLF001 -- the production dedup, driven not reimplemented
    ids = list(svc.session.taken_ids())
    scope.check(
        ids.count("p004") <= 1, EXEC, "exec_mark_then_sync",
        f"p004 appears {ids.count('p004')} times after being marked by hand and then arriving "
        f"via sync. A duplicate taken entry double-advances the clock and removes a player "
        f"who was only ever taken once.",
        taken=ids,
    )
    effective = [p.player_id for p in svc.session.effective_picks()]
    scope.check(
        effective.count("p004") <= 1, EXEC, "exec_mark_then_sync",
        f"p004 appears {effective.count('p004')} times in effective_picks(). A duplicate here "
        f"double-advances the clock even though `taken_ids()` looks right, because that is a "
        f"set union and this is a concatenation.",
        effective=effective,
    )
    # THE WIRING, not only the helper, and DRIVEN rather than grepped. `_reconcile_manual` has
    # exactly one caller; if that call is dropped, every check above still passes while live
    # sync stops deduping. The first version of this check searched `_apply`'s SOURCE for the
    # call and an adversarial review turned it green by COMMENTING THE CALL OUT -- the
    # substring survives the `#`. So a whole update goes through `_apply` instead.
    from audible.draft.identity import SOURCE_PICK_ORDER, Identity
    from audible.draft.sync import DraftUpdate
    from audible.draft.sync import Pick as SyncPick

    fresh = _service(tmp)
    fresh.mark_taken("p006")
    fresh._apply(  # noqa: SLF001 -- the production path, driven not read
        DraftUpdate(
            draft_id="d1",
            picks=[SyncPick(pick_no=1, round=1, draft_slot=1, player_id="p006")],
            rounds=16, status="drafting", draft_type="snake",
            identity=Identity("4", 4, 4, SOURCE_PICK_ORDER, derived_slot=4, pinned_slot=4),
        )
    )
    after = [p.player_id for p in fresh.session.effective_picks()]
    scope.check(
        after.count("p006") == 1, EXEC, "exec_mark_then_sync",
        f"a hand-entered pick that later arrived from the platform stayed as "
        f"{after.count('p006')} picks after a real `_apply`. `_reconcile_manual` is the only "
        f"thing that supersedes it and `_apply` is its only caller.",
        effective=after,
    )


def check_restart(ledger: Ledger, tmp: Any) -> None:
    """What survives a restart, and what does not. The emptyDir is the whole answer.

    A container restart re-reads the state dir, so manual overrides survive. A POD ROLL gets a
    fresh `emptyDir` and loses everything -- the warm board and every `mark-taken` override
    alike. That distinction is asserted here rather than described, because "the board survives
    a restart" is true of one of those two and false of the other, and the difference is the
    whole of what an operator needs to know before rolling a pod mid-draft.
    """
    from audible.draft.service import CockpitService

    from .inv_sync import league_config

    svc = _service(tmp)
    scope = ledger.scoped(surface="service")
    svc.mark_taken("p005")
    svc.save()

    # A CONTAINER RESTART: same emptyDir, fresh process.
    restarted = CockpitService(league_config(), state_dir=tmp, slot_override=4)
    restarted.restore()
    scope.check(
        "p005" in restarted.session.taken_ids(), EXEC, "exec_restart",
        "a manual mark did not survive a restart that kept the state dir. Every hand-entered "
        "pick would have to be re-typed mid-draft.",
        taken=sorted(restarted.session.taken_ids()),
    )

    # A POD ROLL: a fresh emptyDir. Nothing survives, and the check is that this is TRUE --
    # asserting the loss rather than hoping about it, so nobody rolls a pod expecting otherwise.
    import tempfile

    with tempfile.TemporaryDirectory() as fresh:
        from pathlib import Path

        rolled = CockpitService(league_config(), state_dir=Path(fresh), slot_override=4)
        rolled.restore()
        scope.check(
            "p005" not in rolled.session.taken_ids(), EXEC, "exec_restart",
            "a fresh state dir somehow carried state, which means the state dir is not the "
            "only place overrides live and the restart story is wrong",
            taken=sorted(rolled.session.taken_ids()),
        )


def check_browser_only_is_declared(ledger: Ledger) -> None:
    """Two browser-only symbols still live in the page, and are NOT claimed here.

    A WEAK CHECK, and labelled as one. It greps `index.html` for two identifiers, so it
    detects their deletion and nothing subtler -- an adversarial review turned it green by
    replacing the whole page with a one-line comment containing both names. It covers
    `markPending` and `takenStack` only; `S.complete` and the Undo button state are declared
    browser-only above and are not checked here at all. `tests/test_ui_desktop.py` drives a
    real browser and is where those actually live.

    An honest negative. If `S.markPending` ever moved server-side this check would go red and
    the module's split would be rewritten -- which is the point: the boundary is asserted, so
    it cannot drift silently into a coverage claim this module does not earn.
    """
    from pathlib import Path

    repo = Path(__file__).resolve().parents[1]
    candidates = list((repo / "src" / "audible" / "server").rglob("*.html"))
    page = next((p for p in candidates if "index" in p.name), None)
    if page is None:
        ledger.check(
            False, EXEC, "exec_browser_boundary",
            f"no index.html found under src/audible/server; the browser-only boundary this "
            f"module documents cannot be verified. Looked at {[p.name for p in candidates]}",
        )
        return
    text = page.read_text(encoding="utf-8", errors="replace")
    for symbol in ("markPending", "takenStack"):
        ledger.check(
            symbol in text, EXEC, "exec_browser_boundary",
            f"{symbol} is no longer in the page. This module declares it browser-only and "
            f"asserts only its server-side half; if it moved, that split is now wrong.",
            page=page.name,
        )


def run(ledger: Ledger) -> Ledger:
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        check_double_mark(ledger, root / "a")
        check_undo(ledger, root / "b")
        check_mark_then_sync(ledger, root / "c")
        check_restart(ledger, root / "d")
    check_browser_only_is_declared(ledger)
    return ledger
