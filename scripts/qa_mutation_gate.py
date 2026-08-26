"""Phase 0: prove the QA suite can actually fail.

A green suite means nothing until you have watched it go red for a reason you planted.
This breaks the cockpit in five specific ways and asserts that scripts/qa-cockpit.py
notices each one -- by ASSERTION, not by crashing. A mutation the harness crashes on is
not a mutation the harness detects; both exit 1, and only one of them is an oracle.

    uv run --extra nflverse python scripts/qa_mutation_gate.py
    uv run --extra nflverse python scripts/qa_mutation_gate.py --only iife_throw

Every mutation is applied to a file, measured, and reverted from an in-memory backup in a
finally block, with the bytes re-verified afterwards. If a revert ever fails the run stops
immediately rather than leaving a mutated tree behind.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

for _stream in (sys.stdout, sys.stderr):
    with contextlib.suppress(Exception):
        _stream.reconfigure(encoding="utf-8", errors="replace")

COCKPIT = "src/audible/server/static/index.html"
BOARD = "scripts/fixtures/qa-board-espn_davis_drive.json"

MUTATIONS = [
    {
        "key": "iife_throw",
        "desc": "throw new Error() at the top of the cockpit IIFE",
        "path": COCKPIT,
        "find": '"use strict";\n(function () {',
        "repl": '"use strict";\n(function () {\nthrow new Error("MUTANT: the IIFE is dead");',
        "expect_fail": ["no uncaught JS exceptions"],
    },
    {
        "key": "no_focus",
        "desc": "remove the load-time focus call",
        "path": COCKPIT,
        "find": '\n$("q").focus();\nrenderSync();',
        "repl": "\nrenderSync();",
        "expect_fail": ["search box focused on load"],
    },
    {
        "key": "detach_mark",
        "desc": "detach the mark button's click handler",
        "path": COCKPIT,
        "find": 'btn.addEventListener("click", function (ev) {',
        "repl": 'btn.addEventListener("click-MUTANT", function (ev) {',
        "expect_fail": ["clicking X marked a player"],
    },
    {
        "key": "corrupt_rank",
        "desc": "corrupt one rank in the board fixture",
        "path": BOARD,
        "mutate": "corrupt_rank",
        "expect_fail": ["board vorp ranks are a clean 1..N sequence"],
    },
    {
        "key": "console_error",
        "desc": "force a console.error at load",
        "path": COCKPIT,
        "find": "var POLL_MS = 2000;",
        "repl": 'console.error("MUTANT: a real console error");\nvar POLL_MS = 2000;',
        "expect_fail": ["no console errors"],
    },
]


def corrupt_rank(text: str) -> str:
    """Give two different players the same vorp_rank.

    Deliberately a rank COLLISION rather than a wild value: a board that skips a number is
    obvious, while two players quietly sharing rank 11 is the shape a real off-by-one bug
    takes, and it is the one a suite that only eyeballs the top of the board will miss.
    """
    blob = json.loads(text)
    target = next(e for e in blob["entries"] if e["vorp_rank"] == 12)
    target["vorp_rank"] = 11
    return json.dumps(blob, separators=(",", ":"), sort_keys=True)


def run_suite() -> dict:
    with tempfile.TemporaryDirectory(prefix="audible-mut-") as td:
        out = Path(td) / "verdict.json"
        proc = subprocess.run(
            [sys.executable, str(REPO / "scripts" / "qa-cockpit.py"), "--json", str(out)],
            cwd=REPO, capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        if not out.exists():
            tail = (proc.stdout or "")[-2000:]
            return {"aborted": True, "failed": [], "passed": 0,
                    "abort_traceback": f"no verdict written; rc={proc.returncode}\n{tail}"}
        return json.loads(out.read_text(encoding="utf-8"))


def apply_mutation(m: dict) -> tuple[Path, bytes]:
    path = REPO / m["path"]
    original = path.read_bytes()
    text = original.decode("utf-8")
    if m.get("mutate") == "corrupt_rank":
        new = corrupt_rank(text)
    else:
        count = text.count(m["find"])
        if count != 1:
            raise SystemExit(
                f"mutation {m['key']!r} expected exactly 1 anchor in {m['path']}, found {count}.\n"
                "The file moved under the gate -- fix the anchor, do not skip the mutation."
            )
        new = text.replace(m["find"], m["repl"])
    if new == text:
        raise SystemExit(f"mutation {m['key']!r} was a no-op")
    path.write_bytes(new.encode("utf-8"))
    return path, original


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--only", default=None, help="run a single mutation by key")
    args = ap.parse_args()

    wanted = [m for m in MUTATIONS if args.only in (None, m["key"])]
    if not wanted:
        raise SystemExit(f"no mutation named {args.only!r}")

    print("=" * 100)
    print("PHASE 0 -- baseline: the suite must be GREEN before any mutation means anything")
    print("=" * 100)
    base = run_suite()
    if base.get("aborted") or base.get("failed"):
        print("  baseline is NOT green -- fix that first:")
        print("   aborted:", base.get("aborted"))
        for f in base.get("failed", []):
            print(f"   FAILED: {f['name']}  {f['detail']}")
        return 1
    print(f"  baseline GREEN: {base['passed']} checks passed\n")

    rows = []
    for m in wanted:
        print("=" * 100)
        print(f"MUTATION {m['key']}: {m['desc']}")
        print("=" * 100)
        path, original = apply_mutation(m)
        try:
            verdict = run_suite()
        finally:
            path.write_bytes(original)
            if path.read_bytes() != original:
                raise SystemExit(f"FAILED TO REVERT {path} -- stopping with a dirty tree")

        failed_names = [f["name"] for f in verdict.get("failed", [])]
        aborted = bool(verdict.get("aborted"))
        detected = any(n in failed_names for n in m["expect_fail"]) and not aborted

        if aborted:
            observed = "SUITE ABORTED (a crash, not a detection)"
        elif failed_names:
            observed = f"{len(failed_names)} failed: " + ", ".join(failed_names[:3])
        else:
            observed = "GREEN -- the mutation went unnoticed"

        rows.append({
            "key": m["key"],
            "expected": ", ".join(m["expect_fail"]),
            "observed": observed,
            "detected": detected,
        })
        print(f"  -> {'DETECTED' if detected else 'MISSED'}: {observed}\n")

    print("=" * 100)
    print("PHASE 0 RESULT")
    print("=" * 100)
    print(f"  {'mutation':<14} {'expected failure':<44} {'observed':<46} verdict")
    print("  " + "-" * 116)
    for r in rows:
        mark = "PASS" if r["detected"] else "**GAP**"
        print(f"  {r['key']:<14} {r['expected'][:44]:<44} {r['observed'][:46]:<46} {mark}")
    gaps = [r for r in rows if not r["detected"]]
    print("  " + "-" * 116)
    print(f"  {len(rows) - len(gaps)}/{len(rows)} mutations detected by assertion")
    if gaps:
        print("\n  Each GAP is a hole in the oracle. Fix the SUITE, not the app, then re-run.")
    return 1 if gaps else 0


if __name__ == "__main__":
    raise SystemExit(main())
