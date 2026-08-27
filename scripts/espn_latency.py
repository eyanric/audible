"""Measure how quickly ESPN's mDraftDetail endpoint reflects live draft picks.

Read-only. Polls one league's draft detail and records when each pick first
becomes visible. Run it BEFORE starting the draft, and leave it running.

    uv run python scripts/espn_latency.py --league-id 102010124

Ctrl+C to stop; a summary prints on exit.
"""

from __future__ import annotations

import argparse
import json
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

BASE = (
    "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl"
    "/seasons/{season}/segments/0/leagues/{league_id}"
)


def load_env(path: Path) -> dict[str, str]:
    """Minimal .env reader - avoids adding a dependency."""
    env: dict[str, str] = {}
    if not path.exists():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def now() -> float:
    return time.time()


def stamp(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone().strftime("%H:%M:%S.%f")[:-3]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--league-id", required=True)
    ap.add_argument("--season", default="2026")
    ap.add_argument("--interval", type=float, default=2.0)
    ap.add_argument("--out", default="data/cache/latency.jsonl")
    ap.add_argument("--env", default=".env")
    args = ap.parse_args()

    env = load_env(Path(args.env))
    s2 = env.get("ESPN_S2", "")
    swid = env.get("ESPN_SWID", "")
    if not s2 or not swid:
        print("ESPN_S2 / ESPN_SWID not found in .env - cannot authenticate.", file=sys.stderr)
        return 2

    url = BASE.format(season=args.season, league_id=args.league_id)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    seen: dict[int, float] = {}          # overall pick no -> first-seen wall clock
    arrivals: list[tuple[int, float]] = []
    batches: list[int] = []              # how many new picks appeared per poll
    out_of_order = 0
    dumped_shape = False
    polls = 0
    started = now()

    stop = {"flag": False}

    def handle_sigint(_sig, _frm):
        stop["flag"] = True

    signal.signal(signal.SIGINT, handle_sigint)

    print(f"Polling league {args.league_id} every {args.interval}s. Ctrl+C to stop.\n")

    with httpx.Client(
        cookies={"espn_s2": s2, "SWID": swid},
        headers={"Accept": "application/json"},
        timeout=10.0,
    ) as client, out_path.open("a", encoding="utf-8") as fh:
        etag: str | None = None

        while not stop["flag"]:
            t_req = now()
            headers = {"If-None-Match": etag} if etag else {}
            try:
                r = client.get(url, params={"view": "mDraftDetail"}, headers=headers)
            except httpx.HTTPError as exc:
                print(f"  [{stamp(now())}] request failed: {exc}")
                time.sleep(args.interval)
                continue

            polls += 1
            t_resp = now()

            if r.status_code == 304:
                time.sleep(max(0.0, args.interval - (t_resp - t_req)))
                continue
            if r.status_code != 200:
                print(f"  [{stamp(t_resp)}] HTTP {r.status_code}")
                time.sleep(args.interval)
                continue

            etag = r.headers.get("ETag") or etag
            detail = r.json().get("draftDetail", {}) or {}
            picks = [p for p in (detail.get("picks") or []) if p.get("playerId", -1) != -1]

            # One-time: dump a real pick's field names so we learn whether ESPN
            # gives us a server-side timestamp to measure against.
            if picks and not dumped_shape:
                dumped_shape = True
                print("  first real pick, field names:")
                print("   ", sorted(picks[0].keys()))
                print("  raw:", json.dumps(picks[0])[:400], "\n")

            new = 0
            for p in picks:
                no = p.get("overallPickNumber") or p.get("pickNumber") or 0
                if no in seen:
                    continue
                seen[no] = t_resp
                new += 1
                if arrivals and no < arrivals[-1][0]:
                    out_of_order += 1
                arrivals.append((no, t_resp))
                gap = t_resp - arrivals[-2][1] if len(arrivals) > 1 else 0.0
                print(
                    f"  [{stamp(t_resp)}] pick {no:>3}  "
                    f"player {p.get('playerId')}  team {p.get('teamId')}  "
                    f"+{gap:5.1f}s since previous"
                )
                fh.write(json.dumps({
                    "pick": no,
                    "player_id": p.get("playerId"),
                    "team_id": p.get("teamId"),
                    "round": p.get("roundId"),
                    "first_seen_epoch": t_resp,
                    "first_seen": stamp(t_resp),
                    "poll_rtt_s": round(t_resp - t_req, 3),
                    "raw": p,
                }) + "\n")
                fh.flush()

            if new:
                batches.append(new)
            if detail.get("drafted"):
                print("\n  draft reports complete.")
                break

            time.sleep(max(0.0, args.interval - (now() - t_req)))

    elapsed = now() - started
    gaps = [b[1] - a[1] for a, b in zip(arrivals, arrivals[1:])]
    print("\n--- summary ---")
    print(f"polls: {polls}   elapsed: {elapsed:.0f}s   picks observed: {len(seen)}")
    if gaps:
        srt = sorted(gaps)
        print(f"inter-arrival gap  median {srt[len(srt) // 2]:.1f}s   max {max(gaps):.1f}s")
    if batches:
        multi = [b for b in batches if b > 1]
        print(f"polls yielding >1 new pick: {len(multi)} of {len(batches)}"
              f"   largest batch: {max(batches)}")
    print(f"out-of-order arrivals: {out_of_order}")
    print(f"\nwritten to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
