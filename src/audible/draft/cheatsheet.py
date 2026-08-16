"""Pre-draft cheat sheet (Draft-Day Tool, §1) -- the guaranteed, offline floor.

Takes the gate-validated board (consensus ranking + league-exact value) and turns it into
a printable, connectivity-free artifact: an overall board ranked by the league's value
metric (VORP for superflex A, scarcity/VONA for 1-QB B), plus per-position tiers with the
value cliffs marked, value-vs-ADP deltas (targets / reaches), and the advisory tilt flags.
No new modeling -- pure application of the validated layer.
"""

from __future__ import annotations

import csv
import html
import io
from dataclasses import dataclass

from ..config.schema import LeagueConfig
from .board import DraftBoard, DraftEntry

_POS_ORDER = ["QB", "RB", "WR", "TE", "K", "DEF", "DL", "LB", "DB"]
TARGET = 12  # value (adp_rank - value_rank) at/above which a player is a TARGET
REACH = -12  # at/below which a player is a REACH


@dataclass(frozen=True, slots=True)
class TieredPlayer:
    entry: DraftEntry
    tier: int


@dataclass(frozen=True, slots=True)
class CheatSheet:
    league_key: str
    league_name: str
    value_metric: str
    date: str
    overall: list[DraftEntry]  # ranked by the league value metric
    by_position: dict[str, list[TieredPlayer]]


def compute_tiers(
    points: list[float], gap_factor: float = 1.4, min_gap: float = 8.0, depth: int = 48
) -> list[int]:
    """Tier numbers per (points-desc) player; a new tier starts at a value cliff.

    A cliff is a drop larger than ``gap_factor`` x the average gap among the top ``depth``
    (with ``min_gap`` as a noise floor). Players past ``depth`` fall in the final tier.
    """
    if not points:
        return []
    head = points[:depth]
    gaps = [head[i] - head[i + 1] for i in range(len(head) - 1)]
    avg = sum(gaps) / len(gaps) if gaps else 0.0
    threshold = max(min_gap, gap_factor * avg)

    tiers = [1]
    tier = 1
    for i in range(1, len(points)):
        if i < depth and (points[i - 1] - points[i]) > threshold:
            tier += 1
        tiers.append(tier)
    return tiers


def build_cheatsheet(board: DraftBoard, config: LeagueConfig, date: str) -> CheatSheet:
    by_scarcity = config.value_metric == "scarcity"
    overall = sorted(
        board.entries, key=lambda e: e.scarcity_rank if by_scarcity else e.vorp_rank
    )

    ordered_positions = [p for p in _POS_ORDER if p in config.positions]
    by_position: dict[str, list[TieredPlayer]] = {}
    for pos in ordered_positions:
        players = [e for e in overall if e.position == pos]
        tiers = compute_tiers([e.points for e in players])
        by_position[pos] = [TieredPlayer(e, t) for e, t in zip(players, tiers, strict=True)]

    return CheatSheet(
        league_key=config.key, league_name=config.name, value_metric=config.value_metric,
        date=date, overall=overall, by_position=by_position,
    )


def _flags(entry: DraftEntry) -> str:
    return " ".join(f for f in entry.flags if not f.startswith("rookie:"))


def render_csv(cs: CheatSheet) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["overall", "pos", "pos_tier", "name", "team", "proj", "value_metric",
                "vorp", "scarcity", "adp", "value", "target", "flags"])
    tier_of = {tp.entry.player_id: tp.tier for tps in cs.by_position.values() for tp in tps}
    for i, e in enumerate(cs.overall, 1):
        tag = "TARGET" if (e.value or 0) >= TARGET else "REACH" if (e.value or 0) <= REACH else ""
        w.writerow([
            i, e.position, tier_of.get(e.player_id, ""), e.name, e.team or "",
            f"{e.points:.1f}", cs.value_metric, f"{e.vorp:.1f}", f"{e.scarcity:.1f}",
            f"{e.adp:.0f}" if e.adp is not None else "", e.value if e.value is not None else "",
            tag, _flags(e),
        ])
    return buf.getvalue()


_CSS = """
body{font-family:-apple-system,Segoe UI,Arial,sans-serif;margin:18px;color:#111;font-size:12px}
h1{font-size:18px;margin:0 0 2px} h2{font-size:14px;margin:16px 0 6px;border-bottom:2px solid #333}
h3{font-size:13px;margin:10px 0 3px} .sub{color:#555;font-size:11px;margin:0 0 8px}
table{border-collapse:collapse;width:100%} td,th{padding:2px 6px;text-align:left;white-space:nowrap}
th{background:#f0f0f0;font-size:10px;text-transform:uppercase;color:#444}
tr:nth-child(even){background:#fafafa}
.num{text-align:right} .target{background:#e3f5e3!important} .reach{background:#fbe4e4!important}
.tier{background:#333;color:#fff;font-weight:bold;font-size:10px}
.flag{color:#555;font-size:10px} .pos{break-inside:avoid}
.cols{column-count:2;column-gap:18px}
@media print{body{margin:8px;font-size:10px} .cols{column-count:3}}
"""


def _row_class(entry: DraftEntry) -> str:
    v = entry.value or 0
    if v >= TARGET:
        return "target"
    if v <= REACH:
        return "reach"
    return ""


def _cell(text: str, cls: str = "") -> str:
    return f'<td class="{cls}">{html.escape(text)}</td>' if cls else f"<td>{html.escape(text)}</td>"


def render_html(cs: CheatSheet) -> str:
    metric = "VORP (superflex)" if cs.value_metric == "vorp" else "scarcity / VONA (1-QB)"
    out: list[str] = [
        "<!doctype html><html><head><meta charset='utf-8'>",
        f"<title>{html.escape(cs.league_name)} cheat sheet</title>",
        f"<style>{_CSS}</style></head><body>",
        f"<h1>{html.escape(cs.league_name)} — Draft Cheat Sheet</h1>",
        f"<p class='sub'>Ranked by {metric}. Generated {cs.date}. "
        "Consensus projection of record; opportunity/tilt flags are advisory. "
        "<b style='background:#e3f5e3'>Target</b> = value &gt;&gt; ADP, "
        "<b style='background:#fbe4e4'>reach</b> = value &lt;&lt; ADP.</p>",
    ]

    # Overall board
    out.append("<h2>Top overall</h2><table>")
    out.append("<tr><th>#</th><th>player</th><th>pos</th><th>tm</th>"
               "<th class='num'>proj</th><th class='num'>adp</th>"
               "<th class='num'>val</th><th>flags</th></tr>")
    tier_of = {tp.entry.player_id: tp.tier for tps in cs.by_position.values() for tp in tps}
    for i, e in enumerate(cs.overall[:80], 1):
        cls = _row_class(e)
        adp = f"{e.adp:.0f}" if e.adp is not None else "-"
        val = f"{e.value:+d}" if e.value is not None else "-"
        pos = f"{e.position}{tier_of.get(e.player_id, '')}"
        out.append(
            f"<tr class='{cls}'><td class='num'>{i}</td>{_cell(e.name)}{_cell(pos)}"
            f"{_cell(e.team or '-')}<td class='num'>{e.points:.0f}</td>"
            f"<td class='num'>{adp}</td><td class='num'>{val}</td>"
            f"<td class='flag'>{html.escape(_flags(e))}</td></tr>"
        )
    out.append("</table>")

    # Per-position tiers
    out.append("<h2>By position — tiers</h2><div class='cols'>")
    for pos, players in cs.by_position.items():
        out.append(f"<div class='pos'><h3>{pos}</h3><table>")
        last_tier = 0
        for tp in players[:40]:
            e = tp.entry
            if tp.tier != last_tier:
                out.append(f"<tr class='tier'><td colspan='5'>Tier {tp.tier}</td></tr>")
                last_tier = tp.tier
            cls = _row_class(e)
            adp = f"{e.adp:.0f}" if e.adp is not None else "-"
            val = f"{e.value:+d}" if e.value is not None else "-"
            out.append(
                f"<tr class='{cls}'>{_cell(e.name)}{_cell(e.team or '-')}"
                f"<td class='num'>{e.points:.0f}</td><td class='num'>{val}</td>"
                f"<td class='flag'>{html.escape(_flags(e))}</td></tr>"
            )
        out.append("</table></div>")
    out.append("</div></body></html>")
    return "\n".join(out)
