"""The poller inside `serve`: gated off by default, and never able to fail a request."""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from audible.config import LeagueConfig
from audible.draft.board import DraftBoard, DraftEntry
from audible.draft.service import CockpitService
from audible.news.poll import ENV_POLL_ENABLED
from audible.server import create_app
from audible.server.app import _build_news_poller


def _entry(i: int) -> DraftEntry:
    return DraftEntry(
        player_id=f"p{i:03d}", name=f"Player {i:03d}", position="RB",
        eligible_positions=frozenset({"RB"}), team="XX", model="consensus",
        points=400.0 - i, modeled_xfp=0.0, carried=0.0, consensus=400.0 - i,
        vorp=400.0 - i, vorp_rank=i, consensus_rank=i, opp_rank=i,
        deviation=False, scarcity=400.0 - i, scarcity_rank=i,
        adp=float(i), adp_rank=i, value=0, flags=(),
    )


@pytest.fixture
def service(tmp_path: Path, sleeper_config: LeagueConfig) -> CockpitService:
    svc = CockpitService(sleeper_config, state_dir=tmp_path, slot_override=4)
    svc.board = DraftBoard("sleeper_boyfun", [_entry(i) for i in range(1, 21)])
    svc.session.draft_id = "d1"
    svc.health.last_success = time.time()
    return svc


def test_poller_is_not_built_unless_the_env_gate_is_set(monkeypatch, service):
    monkeypatch.delenv(ENV_POLL_ENABLED, raising=False)
    assert _build_news_poller(service) is None


def test_a_missing_catalog_disables_news_instead_of_breaking_startup(monkeypatch, service):
    """No cached catalog on a fresh box must not stop the cockpit from serving."""
    monkeypatch.setenv(ENV_POLL_ENABLED, "1")
    monkeypatch.setattr("audible.news.entities.load_index",
                        lambda roster=None: (_ for _ in ()).throw(RuntimeError("no catalog")))
    assert _build_news_poller(service) is None


def test_healthz_reports_news_as_disabled_and_stays_ok(monkeypatch, service):
    monkeypatch.delenv(ENV_POLL_ENABLED, raising=False)
    with TestClient(create_app(service, warm=False)) as client:
        resp = client.get("/healthz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["news"] == {"enabled": False}
    assert body["ok"] is True


def test_news_never_contributes_to_problems(monkeypatch, service):
    """A dead news website must not be able to make the cockpit look unhealthy."""
    monkeypatch.setenv(ENV_POLL_ENABLED, "1")

    class Exploding:
        def start(self): pass
        def stop(self): pass
        def health(self): raise RuntimeError("news store is on fire")

    monkeypatch.setattr("audible.server.app._build_news_poller", lambda svc: Exploding())
    with TestClient(create_app(service, warm=False)) as client:
        resp = client.get("/healthz")

    assert resp.status_code == 200, "news must never change the status code"
    body = resp.json()
    assert body["ok"] is True
    assert body["problems"] == []
    assert "news store is on fire" in body["news"]["error"]


def test_board_numbers_are_identical_with_news_on_and_off(monkeypatch, service):
    """Hard stop 4, asserted: turning news on must not move a single board number."""
    monkeypatch.delenv(ENV_POLL_ENABLED, raising=False)
    with TestClient(create_app(service, warm=False)) as client:
        off = client.get("/api/state").json()

    monkeypatch.setenv(ENV_POLL_ENABLED, "1")
    monkeypatch.setattr("audible.server.app._build_news_poller", lambda svc: None)
    with TestClient(create_app(service, warm=False)) as client:
        on = client.get("/api/state").json()

    assert off == on
