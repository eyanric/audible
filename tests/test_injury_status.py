"""Roster/injury status: extraction, and the structural guarantees that keep it display-only.

The point of this module is not that the extraction works -- that is the easy half. It is
that the value engine *cannot see it*, which is a property of the code's shape rather than
of anyone's discipline, and therefore has to be asserted rather than trusted.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest

from audible.adapters.sleeper import STATUS_FIELDS, PlayerStatus, SleeperAdapter
from audible.models.player import PlayerProjection, RawPlayerLine

SRC = Path(__file__).resolve().parents[1] / "src" / "audible"


class _FakeAdapter(SleeperAdapter):
    """SleeperAdapter with the catalog pinned, so nothing here touches the network."""

    def __init__(self, catalog: dict[str, Any]) -> None:  # noqa: D107 -- test double
        self._catalog = catalog

    def get_players_catalog(self, *, force: bool = False) -> dict[str, Any]:
        return self._catalog


# --- extraction -------------------------------------------------------------------

def test_extracts_every_declared_field(sample_catalog: dict[str, dict[str, Any]]) -> None:
    statuses = _FakeAdapter(sample_catalog).player_status()
    assert statuses, "the sample catalog should yield at least one status row"
    for st in statuses.values():
        assert isinstance(st, PlayerStatus)
        for field in STATUS_FIELDS:
            assert hasattr(st, field)


def test_player_id_is_carried_and_keyed_consistently(
    sample_catalog: dict[str, dict[str, Any]],
) -> None:
    for pid, st in _FakeAdapter(sample_catalog).player_status().items():
        assert st.player_id == pid


def test_values_come_through_verbatim() -> None:
    """Whatever the platform said, unmapped. `Questionable` must stay `Questionable`."""
    catalog = {
        "1": {
            "full_name": "A Player", "status": "Injured Reserve",
            "injury_status": "Questionable", "injury_body_part": "Knee",
            "injury_notes": "limited", "injury_start_date": "2026-08-20",
        },
    }
    st = _FakeAdapter(catalog).player_status()["1"]
    assert st.status == "Injured Reserve"
    assert st.injury_status == "Questionable"
    assert st.injury_body_part == "Knee"
    assert st.injury_notes == "limited"
    assert st.injury_start_date == "2026-08-20"


def test_an_entry_with_no_status_data_is_ABSENT_rather_than_null() -> None:
    """"We have no record of him" and "he is Active" must not collapse into one value.

    Team defences are the real case: Sleeper carries them as catalog entries with every
    status field null, because a defence is not a person and cannot be on IR. Emitting a
    row of nulls for them would let a chip report health it never observed.
    """
    catalog = {
        "1": {"full_name": "Real Player", "status": "Active"},
        "LAR": {"position": "DEF", "team": "LAR", "status": None, "injury_status": None},
        "2": {"full_name": "Blank", "status": "", "injury_status": ""},
    }
    statuses = _FakeAdapter(catalog).player_status()
    assert set(statuses) == {"1"}, "only the entry carrying something survives"


def test_empty_strings_normalise_to_none() -> None:
    catalog = {"1": {"status": "Active", "injury_status": "", "injury_body_part": None}}
    st = _FakeAdapter(catalog).player_status()["1"]
    assert st.status == "Active"
    assert st.injury_status is None
    assert st.injury_body_part is None


def test_filtering_by_ids_returns_only_those(sample_catalog: dict[str, dict[str, Any]]) -> None:
    everything = _FakeAdapter(sample_catalog).player_status()
    wanted = list(everything)[:2]
    narrowed = _FakeAdapter(sample_catalog).player_status(wanted)
    assert set(narrowed) == set(wanted)


def test_unknown_ids_are_simply_absent(sample_catalog: dict[str, dict[str, Any]]) -> None:
    assert _FakeAdapter(sample_catalog).player_status(["nope-not-a-player"]) == {}


def test_non_dict_entries_are_skipped() -> None:
    assert _FakeAdapter({"1": "junk", "2": None, "3": {"status": "Active"}}).player_status() == {
        "3": PlayerStatus(player_id="3", status="Active")
    }


# --- the structural guarantees ----------------------------------------------------

def test_status_is_not_a_field_on_the_value_engine_models() -> None:
    """Hard stop 2, asserted. Status must not reach what the value engine consumes."""
    for model in (RawPlayerLine, PlayerProjection):
        fields = set(getattr(model, "__dataclass_fields__", {}))
        leaked = fields & set(STATUS_FIELDS)
        assert not leaked, f"{model.__name__} carries status field(s): {sorted(leaked)}"
        assert "status" not in fields
        assert "injury_status" not in fields


def _imports_of(path: Path) -> set[str]:
    """Every name this module imports, as `module.name` and bare `name`."""
    names: set[str] = set()
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                names.add(alias.name)
                names.add(f"{node.module or ''}.{alias.name}")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
    return names


SIDECAR_NAMES = {"PlayerStatus", "player_status", "STATUS_FIELDS"}


@pytest.mark.parametrize("package", ["value", "scoring", "providers", "draft"])
def test_the_value_path_does_not_import_the_sidecar(package: str) -> None:
    """The guarantee is only worth as much as its guard.

    A sidecar the value path *could* import is a convention; one a test forbids it from
    importing is a structure. `draft/` is included because the board it builds is the thing
    every ranking is read off.
    """
    root = SRC / package
    if not root.is_dir():
        pytest.skip(f"no {package}/ package")
    offenders: list[str] = []
    for path in sorted(root.rglob("*.py")):
        if SIDECAR_NAMES & _imports_of(path):
            offenders.append(str(path.relative_to(SRC)))
        # Catch attribute access too: `sleeper.player_status(...)` after importing the module.
        text = path.read_text(encoding="utf-8")
        if ".player_status(" in text or "PlayerStatus" in text:
            offenders.append(f"{path.relative_to(SRC)} (textual reference)")
    assert not offenders, (
        f"{package}/ reaches the display-only status sidecar: {offenders}. "
        "That is the one thing this design exists to prevent."
    )


def test_the_sidecar_lives_outside_models() -> None:
    """PlayerStatus is declared in the adapter, not in models/player.py, on purpose."""
    model_src = (SRC / "models" / "player.py").read_text(encoding="utf-8")
    assert "PlayerStatus" not in model_src
    assert "injury_status" not in model_src
