"""GATES G1-G10 for B6, and the four restorations that are the session's acceptance criterion.

THE WHOLE SESSION IS G1. Four defects reached production and cost real drafts. Each is now
guarded by an invariant, and an invariant nobody has watched fail is a comment. So each is
proven by RESTORING THE REAL HISTORICAL CODE and requiring the check to fire:

  R1  the pin outranks the live derivation      -> seat_precedence fires
  R2  the ETag cache with no periodic full body -> sync_frozen_etag fires
  R3  the sort `(not grab_now, vorp_rank, not fills_need)` -> dead_signal_key names fills_need
  R4  `bye_conflict_cost` forced to 0.0         -> order_bye_term_live fires

If any of those cannot be made to fail, the invariant it guards does not work and does not
ship. That is the acceptance criterion and nothing else in this file matters if it fails.

WHAT THE HARNESS FOUND ON MAIN, all reported and none fixed -- fixing a defect in the session
that first detects it means the detector was never tested against the bug, and all three are
outside `sim/` anyway:

  seat_conflict_seen   `Identity.seat_conflict` reaches a `log.error` and NOTHING ELSE. No API
                       field carries it. On 2026-09-07 that line fired once per poll for hours
                       while the cockpit served the wrong seat.
  sync_stale_blip      one `pre_draft` poll clears `drafting_since`, and the next `drafting`
                       poll re-anchors it -- discarding accumulated silence and restarting the
                       180s window. `espn_draft_status` returns `pre_draft` for ANY body that
                       does not assert `inProgress`.
  sync_stale_shrink    an emptied slate is stored unconditionally, so the next full body reads
                       as a delivery from an empty baseline with no new pick made.

WHAT THIS FILE CANNOT SAY. The ordering invariants run against the ROOM, whose opponents are
bots fitted to ADP -- they do not stack, reach for their own players, or panic. And a clean run
means no violation was OBSERVED over the seasons and seeds swept, which is not the same as
proving none exists. The check counts are reported so that distinction stays visible.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from . import LIVE_CACHE, SIM_CACHE

REPO = Path(__file__).resolve().parents[1]
SEASONS = (2021, 2022, 2023, 2024, 2025)

pytestmark = pytest.mark.slow


def _require(name: str) -> Path:
    for root in (SIM_CACHE, LIVE_CACHE):
        if (root / name).exists():
            return root / name
    pytest.skip(f"{name} is pinned in neither {SIM_CACHE} nor {LIVE_CACHE}")


@pytest.fixture(scope="module")
def mods():
    pytest.importorskip("polars", reason="uv sync --extra nflverse")
    from . import inv_exec, inv_order, inv_run, inv_seat, inv_sync, invariants, weekly

    _require("nflverse/ff_playerids.parquet")
    for season in SEASONS:
        _require(f"nflverse/player_stats_{season}.parquet")
        _require(f"ffc_adp_standard_8_{season}.json")
    return invariants, inv_seat, inv_sync, inv_order, inv_exec, inv_run, weekly


@pytest.fixture(scope="module")
def league(mods):
    *_rest, weekly = mods
    return weekly.league_config()


@pytest.fixture(scope="module")
def swept(mods):
    """One survey sweep over every family, shared by the reporting gates.

    Survey mode ON PURPOSE and labelled: this fixture exists to COUNT what is there, and a
    strict ledger would stop at the first violation and hide the rest. The strict path has its
    own gate (`test_g5_*`).
    """
    invariants, inv_seat, inv_sync, inv_order, inv_exec, inv_run, weekly = mods
    ledger = invariants.Ledger(strict=False)
    inv_seat.run(ledger)
    inv_sync.run(ledger)
    inv_exec.run(ledger)
    inv_order.check_bye_term_is_live(ledger, weekly.league_config())
    info = inv_run.run_drafts(ledger, seasons=SEASONS, seeds=(0, 1), arms=("real",))
    return ledger, info


# --- G1: the four restorations. THE ACCEPTANCE CRITERION. -------------------------------------


def test_g1_r1_a_pin_that_outranks_the_live_seat_fires(mods, monkeypatch) -> None:
    """R1. Restore the pin-first precedence and `seat_precedence` must fire.

    PATCHED ON THE ESPN PATH, BECAUSE THAT IS WHERE IT HAPPENED. The first version of this test
    patched `identity.resolve_slot` and passed -- but Green Hope was an ESPN league, and
    `EspnSync._identity` is a SEPARATE hand-written copy of the same ladder that `resolve_slot`
    never touches. An adversarial review measured it: every violation R1 raised carried
    `resolver=None` (the Sleeper arm) and the ESPN precedence check stayed green. The invariant
    was capable of catching the real defect; R1 was not demonstrating it.

    Both resolvers are restored here, so R1 proves the guard on the path that failed as well as
    on the one that did not.
    """
    invariants, inv_seat, *_rest = mods
    from audible.draft import identity as ident
    from audible.draft.sync import EspnSync

    def historical(draft, rosters, user_id, *, override=None, fallback=None, teams=None):
        """Sleeper's pre-2026-09-07 ladder: pin first, derivation only if nothing was pinned."""
        roster_id = ident.roster_id_for_user(rosters, user_id) if user_id else None
        pinned = override if override is not None else fallback
        order = draft.get("draft_order") or {}
        raw = order.get(user_id) if user_id else None
        derived = int(raw) if raw is not None else None
        if pinned is not None:
            return ident.Identity(
                user_id, roster_id, pinned, ident.SOURCE_OVERRIDE,
                derived_slot=derived, pinned_slot=pinned,
            )
        if derived is not None:
            return ident.Identity(
                user_id, roster_id, derived, ident.SOURCE_DRAFT_ORDER,
                derived_slot=derived, pinned_slot=pinned,
            )
        return ident.Identity(user_id, roster_id, None, ident.SOURCE_UNRESOLVED)

    def historical_espn(self, payload, slot_by_team):
        """THE ACTUAL GREEN HOPE CODE: the pin returned before the derivation is consulted."""
        from audible.draft.sync import espn_my_team_id

        team_id = espn_my_team_id(payload.get("teams") or [], self._adapter.swid)
        derived = slot_by_team.get(team_id) if team_id is not None else None
        pinned = (
            self._slot_override if self._slot_override is not None else self._slot_fallback
        )
        uid = str(team_id) if team_id is not None else None
        if pinned is not None:
            return ident.Identity(uid, team_id, pinned, ident.SOURCE_OVERRIDE,
                                  derived_slot=derived, pinned_slot=pinned)
        if derived is not None:
            return ident.Identity(uid, team_id, derived, ident.SOURCE_PICK_ORDER,
                                  derived_slot=derived, pinned_slot=pinned)
        return ident.Identity(uid, team_id, None, ident.SOURCE_UNRESOLVED)

    monkeypatch.setattr(ident, "resolve_slot", historical)
    monkeypatch.setattr(EspnSync, "_identity", historical_espn)
    ledger = invariants.Ledger(strict=False)
    inv_seat.check_resolvers(ledger)

    fired = [v for v in ledger.violations if v.kind == "seat_precedence"]
    assert fired, (
        "R1 DID NOT FIRE. With the pin restored ahead of the live derivation, the Green Hope "
        "case serves seat 1 while the platform says 6 and `seat_precedence` must catch it. "
        f"Violations seen: {[v.kind for v in ledger.violations]}"
    )
    green = [v for v in fired if v.repro.get("case") == "green_hope"]
    assert green, f"R1 fired but not on the green_hope case: {[v.repro for v in fired]}"

    # THE HALF THAT MATTERS. Green Hope was ESPN, so an R1 satisfied only by the Sleeper arm
    # proves nothing about the path that actually served seat 1 for hours.
    espn = [v for v in fired if v.repro.get("resolver") == "espn"]
    assert espn, (
        "R1 fired only on the Sleeper resolver. The 2026-09-07 failure was on ESPN, whose "
        "ladder is a separate copy in `sync.EspnSync._identity`. "
        f"Violations: {[v.repro for v in fired]}"
    )


def test_g1_r2_a_frozen_etag_with_no_full_body_fires(mods, monkeypatch) -> None:
    """R2. Remove the periodic full body and the frozen tag hides every pick.

    THE MITIGATION IS THE THING BEING TESTED. `_draft_etag`/`_draft_last` are still written only
    on a 200 -- that is unchanged and is the defect's mechanism. What bounds it is
    `DRAFT_FULL_BODY_EVERY`, which skips the conditional request periodically. Set that beyond
    the sequence length and the adapter is pinned to the first body it ever saw, which is the
    2026-09-05 failure exactly.
    """
    invariants, _seat, inv_sync, *_rest = mods
    from audible.adapters.espn import EspnAdapter

    def historical(self, config):
        """`get_draft_detail` as it was: conditional EVERY time, no periodic full body.

        Byte-for-byte the mechanism of the failure -- `_draft_etag` and `_draft_last` written
        only on the 200 path, so a tag that never advances freezes the adapter on the first
        body it ever saw. Restored as a method rather than by moving a constant, because the
        constant IS the mitigation and the point is to remove it.
        """
        headers = {"If-None-Match": self._draft_etag} if self._draft_etag else {}
        resp = self._request(config, self.DRAFT_VIEWS, headers=headers)
        if resp.status_code == 304 and self._draft_last is not None:
            return self._draft_last
        resp.raise_for_status()
        payload = resp.json()
        etag = resp.headers.get("etag")
        if etag:
            self._draft_etag = etag
        self._draft_last = payload
        return payload

    monkeypatch.setattr(EspnAdapter, "get_draft_detail", historical)
    ledger = invariants.Ledger(strict=False)
    inv_sync.check_frozen_etag(ledger, polls=8)

    fired = [v for v in ledger.violations if v.kind == "sync_frozen_etag"]
    assert fired, (
        "R2 DID NOT FIRE. With no periodic full body a stuck ETag pins the adapter to the "
        "pre-draft placeholder slate for the whole draft while every poll succeeds. "
        f"Violations seen: {[v.kind for v in ledger.violations]}"
    )
    assert fired[0].repro.get("truth") == 24


def test_g1_r3_the_dead_tuple_sort_fires(mods) -> None:
    """R3. The historical sort's third key is unreachable, and production's is not.

    Driven over REAL board rows rather than invented ones, so the uniqueness of `vorp_rank` is
    the board's own property and not a fixture's convenience.
    """
    _invariants, _seat, _sync, inv_order, _exec, _run, _weekly = mods
    from . import room

    board = room.load_board(2024)
    rows = board.rows[:40]

    historical = [(False, r.rank, r.position == "QB") for r in rows]
    production = [(False, -float(len(rows) - r.rank), r.rank) for r in rows]

    dead = inv_order.dead_signal_key(historical, {0: "grab_now", 2: "fills_need"})
    assert dead is not None, (
        "R3 DID NOT FIRE. `(not grab_now, vorp_rank, not fills_need)` places a signal key "
        "after a unique gapless integer, so it can never be compared."
    )
    assert dead[0] == "fills_need", dead

    alive = inv_order.dead_signal_key(
        production, {0: "grab_now", 1: "effective_score"}
    )
    assert alive is None, (
        f"production's sort reports a dead SIGNAL key ({alive}), which would make this gate "
        f"fire on correct code. Its unreachable key is `vorp_rank`, a deliberate terminal "
        f"tiebreak, and the check must tell those apart."
    )


def test_g1_r4_a_zeroed_bye_cost_fires(mods, league, monkeypatch) -> None:
    """R4. Force `bye_conflict_cost` to 0.0 -- byes computed, displayed, consumed by nothing."""
    invariants, _seat, _sync, inv_order, *_rest = mods
    from audible.draft import ordering as ordering_mod

    monkeypatch.setattr(ordering_mod, "bye_conflict_cost", lambda *a, **k: 0.0)
    ledger = invariants.Ledger(strict=False)
    inv_order.check_bye_term_is_live(ledger, league)

    fired = [v for v in ledger.violations if v.kind == "order_bye_term_live"]
    assert fired, (
        "R4 DID NOT FIRE. With the bye cost forced to zero the term computes nothing and "
        "discriminates nothing, and the check must say so. "
        f"Violations seen: {[v.kind for v in ledger.violations]}"
    )
    assert len(fired) >= 2, (
        f"only {len(fired)} of the two bye-term properties fired; a zeroed cost breaks both "
        f"'computes something' and 'discriminates'"
    )


def test_g1_all_four_restorations_are_present() -> None:
    """The four restorations exist as tests. A missing one is a missing acceptance criterion."""
    source = Path(__file__).read_text(encoding="utf-8")
    for name in ("test_g1_r1_", "test_g1_r2_", "test_g1_r3_", "test_g1_r4_"):
        assert name in source, f"{name} is missing; G1 is not satisfied"


# --- G2: the invariants run at every decision point -------------------------------------------


def test_g2_checks_run_at_every_pick(swept) -> None:
    """Not once per draft. The count is the gate, and the count is reported.

    A checker that silently stops executing is indistinguishable from a clean run if only
    violations are reported. A prior review of this repo found exactly that shape: no gate in
    `sim/` ever executed the artifact producers.
    """
    ledger, info = swept
    drafts = info["drafts"]
    assert drafts > 0
    order_checks = ledger.by_family["order"]
    # MEASURED, not guessed: 16 WATCHED picks a draft -- the seat's own, not all 128 -- with one
    # per-pick `order_occupancy` plus three per-draft checks, so 19, and one 2024 draft has 15
    # picks. The first bar was `drafts * 10`, and an adversarial review showed a checker wired
    # to only every SECOND pick still passed it at 10.9 a draft. Fifteen is above that.
    assert order_checks >= drafts * 15, (
        f"{order_checks} ordering checks across {drafts} drafts is fewer than fifteen a "
        f"draft; the per-pick checker is not running at every pick"
    )
    # And the DECISION count, which the check total cannot see on its own: a hook wired to half
    # the picks halves this while the totals still look broadly plausible.
    assert info["picks_seen"] >= drafts * 15, (
        f"the watcher saw {info['picks_seen']} decisions across {drafts} drafts; a draft gives "
        f"the seat 16 picks, so the hook is missing some"
    )
    assert ledger.checks == sum(ledger.by_family.values()), (
        "the total check count disagrees with the per-family counts, so one of them is wrong"
    )


def test_i5_a_checker_that_runs_nothing_fails_g2(mods) -> None:
    """INJECTION 5. Break the hook so it runs zero checks; G2's count must catch it."""
    invariants, *_rest = mods
    ledger = invariants.Ledger(strict=False)
    assert ledger.checks == 0
    assert not (ledger.by_family["order"] >= 1 * 10), (
        "an empty ledger satisfied G2's count bar, so the bar cannot detect a checker that "
        "never executed"
    )


# --- G3: what main actually does --------------------------------------------------------------


def test_g3_every_violation_on_main_is_reported_with_a_reproduction(swept) -> None:
    """Zero violations, or every one carries a repro. A finding is a success here.

    The three known ones are `seat_conflict_seen`, `sync_stale_blip` and `sync_stale_shrink`;
    all are production defects outside `sim/` and all are reported rather than fixed.
    """
    ledger, _info = swept
    for violation in ledger.violations:
        assert violation.repro, f"{violation.kind} carries no reproduction: {violation.detail}"
        assert violation.detail, f"{violation.kind} has no description"
    kinds = {v.kind for v in ledger.violations}
    unexpected = kinds - {"seat_conflict_seen", "sync_stale_blip", "sync_stale_shrink"}
    assert not unexpected, (
        f"NEW violations on main beyond the three known and reported: {sorted(unexpected)}. "
        f"That is a finding, not a test failure -- report it with its reproduction."
    )


def test_g3_the_ordering_arm_the_cockpit_actually_runs_is_clean(swept) -> None:
    """`real` is the cockpit's own `the_call` path and it must produce no ordering violation."""
    ledger, _info = swept
    order = [v for v in ledger.violations if v.family == "order"]
    assert not order, (
        f"the real arm violated an ordering invariant: {[v.describe() for v in order]}"
    )


# --- G4: the real code paths are driven -------------------------------------------------------


def test_g4_the_checkers_import_production_rather_than_copying_it() -> None:
    """A reimplementation tests itself. Every family must reach into `audible.*`.

    Asserted on the source rather than by patching, because the claim is about every path
    through the module and not only the ones a fixture happens to take.
    """
    wanted = {
        "inv_seat.py": ("audible.draft.identity", "audible.draft.sync"),
        "inv_sync.py": ("audible.adapters.espn", "audible.draft.sync", "audible.draft.service"),
        "inv_order.py": ("audible.draft.ordering",),
        "inv_exec.py": ("audible.draft.service", "audible.server"),
        "invariants.py": ("audible.draft.ordering", "audible.draft.live"),
    }
    for name, imports in wanted.items():
        source = (REPO / "sim" / name).read_text(encoding="utf-8")
        for module in imports:
            assert module in source, f"{name} does not drive {module}"


def test_g4_the_ordering_helpers_delegate_to_production(mods, league) -> None:
    """Spot-check the delegation actually happens at runtime, not only in an import line."""
    invariants, *_rest = mods
    from audible.draft.ordering import startable_slots

    for position in ("QB", "RB", "WR", "TE", "K", "DEF"):
        assert invariants.startable(league, position) == startable_slots(league, position)


# --- G5: strict mode exits non-zero ------------------------------------------------------------


def test_g5_a_violation_stops_the_run_and_exits_non_zero(mods) -> None:
    """Strict is the default and the exit code is the product. Proved both ways."""
    invariants, *_rest = mods
    from .invariants import ORDER, InvariantViolation

    strict = invariants.Ledger(strict=True)
    with pytest.raises(InvariantViolation):
        strict.check(False, ORDER, "probe", "a deliberate failure")

    survey = invariants.Ledger(strict=False)
    survey.check(False, ORDER, "probe", "a deliberate failure")
    assert len(survey.violations) == 1, "survey mode must collect rather than raise"
    assert "SURVEY" in survey.summary()["mode"], "survey mode must be labelled in the artifact"


def test_g5_the_cli_returns_one_on_a_violation(mods, tmp_path) -> None:
    """The entry point, not only the ledger. `main` must return a non-zero code."""
    _invariants, _seat, _sync, _order, _exec, inv_run, _weekly = mods

    code = inv_run.main(
        ["--families", "seat", "--out", str(tmp_path / "out.json")]
    )
    assert code == 1, (
        "a strict run over the seat family returned 0, but `seat_conflict_seen` is a known "
        "violation on main -- so either the exit code is wrong or that defect was fixed"
    )
    assert (tmp_path / "out.json").exists(), "the artifact must be written even on a violation"


# --- G6: determinism ---------------------------------------------------------------------------


def test_g6_a_violation_reproduces_from_its_recorded_coordinates(mods) -> None:
    """Same season, seed and arm -> the same violation. A repro that does not reproduce is a
    rumour, and B2's retracted headline is why this is a gate."""
    invariants, _seat, _sync, _order, _exec, inv_run, _weekly = mods

    def sweep():
        ledger = invariants.Ledger(strict=False)
        inv_run.run_drafts(ledger, seasons=(2024,), seeds=(0,), arms=("legacy_recommend",))
        return [(v.kind, v.repro.get("season"), v.repro.get("seed"), v.repro.get("pick"))
                for v in ledger.violations]

    first, second = sweep(), sweep()
    assert first, "the R3 arm produced no violation to reproduce"
    assert first == second, f"a violation did not reproduce:\n  {first}\n  {second}"


def test_i6_a_violation_without_a_repro_fails_g6(mods) -> None:
    """INJECTION 6. A violation carrying no coordinates must be detectable as unusable."""
    invariants, *_rest = mods
    from .invariants import ORDER

    ledger = invariants.Ledger(strict=False)
    ledger.check(False, ORDER, "anonymous", "no context at all")
    assert not ledger.violations[0].repro, "this injection needs an empty repro to be meaningful"
    with pytest.raises(AssertionError):
        for violation in ledger.violations:
            assert violation.repro, "carries no reproduction"


# --- G7, G8, G9, G10: the standing gates -------------------------------------------------------


def test_g7_the_live_cache_is_untouched() -> None:
    """63 files. `sim/__init__` rebinds the cache root; this is the check that it held."""
    from audible.adapters import cache as cache_mod

    assert cache_mod.DEFAULT_CACHE_DIR == SIM_CACHE
    if not LIVE_CACHE.exists():
        pytest.skip("no live cache in this checkout")
    files = [p for p in LIVE_CACHE.rglob("*") if p.is_file()]
    assert len(files) == 63, f"live cache holds {len(files)} files, expected 63"


def test_g10_no_ffa_csv_is_tracked() -> None:
    """Public repo, subscription data. Not negotiable."""
    result = subprocess.run(
        ["git", "ls-files", "sim/data/ffa/"],
        cwd=REPO, capture_output=True, text=True, check=True,
    )
    tracked = [line for line in result.stdout.splitlines() if line.strip()]
    assert not [t for t in tracked if t.endswith(".csv")], f"a CSV is tracked: {tracked}"
    assert "sim/data/ffa/*.csv" in (REPO / ".gitignore").read_text(encoding="utf-8")


# --- what the harness found, pinned so it cannot be quietly dropped ---------------------------


def test_the_three_findings_on_main_are_still_findings(swept) -> None:
    """Each known violation is still detected. If one stops firing, it was fixed -- say so.

    Pinned deliberately. A detector that quietly stops detecting is the failure mode this whole
    session exists to prevent, and "the violation went away" needs to be a conscious edit rather
    than a silent green.
    """
    ledger, _info = swept
    kinds = {v.kind for v in ledger.violations}
    for expected in ("seat_conflict_seen", "sync_stale_blip", "sync_stale_shrink"):
        assert expected in kinds, (
            f"{expected} no longer fires. Either it was fixed in production -- in which case "
            f"remove it from this list and from the module docstrings -- or the detector broke."
        )


def test_the_qb_baseline_defect_is_reported_not_touched() -> None:
    """`rostered_counts` is B5's finding, measured at -68.0, and is NOT this session's to fix.

    It changes the live cockpit's board during a frozen draft. Asserting that `sim/` has not
    edited it is how "report it, do not touch it" stays true after this session ends.
    """
    # `git diff origin/main...HEAD` was the first version and it saw NOTHING: on this branch
    # origin/main == HEAD and every change was still uncommitted, so the assertion reduced to
    # `assert not []`. It also cannot see the working tree, which is exactly where an edit to
    # `src/audible/value/replacement.py` would sit. `status --porcelain` sees both.
    committed = subprocess.run(
        ["git", "diff", "--name-only", "origin/main...HEAD"],
        cwd=REPO, capture_output=True, text=True, check=False,
    )
    working = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=REPO, capture_output=True, text=True, check=False,
    )
    if committed.returncode != 0 or working.returncode != 0:
        pytest.skip("git is unavailable here")
    changed = [line for line in committed.stdout.splitlines() if line.strip()]
    changed += [line[3:].strip() for line in working.stdout.splitlines() if line.strip()]
    outside = sorted({c for c in changed if c and not c.startswith("sim/")})
    assert not outside, (
        f"this session must write only inside sim/; it also touched {outside}. "
        f"`rostered_counts` in src/audible/value/replacement.py is B5's finding, measured at "
        f"-68.0, and changing it moves the live cockpit's board during a frozen draft."
    )
