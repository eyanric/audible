# Capturing a draft for offline replay

**Do this Saturday night, before anything restarts the pod.** The cockpit's `/app/data` is an
`emptyDir` — it is wiped with the pod, and the Tuesday league flip restarts it. Once that
happens Saturday's draft cannot be replayed, because the pick history lives only there.

## The command

```bash
POD=$(kubectl -n audible get pod -o jsonpath='{.items[0].metadata.name}')
MSYS_NO_PATHCONV=1 kubectl -n audible exec "$POD" -- tar cf - -C /app data > draft-2026-09-05.tar
```

`MSYS_NO_PATHCONV=1` is **not optional on Git Bash.** Without it MSYS rewrites the `/app`
argument on its way to `kubectl.exe` and the command fails with:

```
tar: C\:/Program Files/Git/app: Cannot open: No such file or directory
```

which produces a 0-byte file and an exit code that is easy to miss at 11pm. This is the same
path-mangling trap documented in haven's `verify-audible-league.sh`.

`kubectl cp` does **not** work here for the same reason — it rejects the remote path as
"one of src or dest must be a local file specification".

## Verifying the capture, before you trust it

```bash
python -c "import tarfile; t=tarfile.open('draft-2026-09-05.tar'); n=t.getnames(); \
print(len(n),'entries'); print([x for x in n if 'draft-state' in x])"
```

Expect ~17 entries and one `data/cache/draft-state-<league>.json`.

**Do not verify with `tar tf` against a Windows path.** GNU tar reads the `C:` as a remote
host and reports `Cannot connect to C: resolve failed` — an alarming error from a perfectly
good archive. Either use a relative path (`cd` to the directory first, then `tar tf ./x.tar`)
or use Python as above.

## What the replay actually needs

Verified 2026-09-02 by replaying DDAFFL offline: the board rebuilt in 0.8s from disk, all 128
picks resolved to board entries, and pick 57 came back as Joe Burrow at value rank 109 —
matching the known figure exactly.

| what | where | needed because |
|---|---|---|
| pick history | `data/cache/draft-state-<key>.json` | the picks, in order, with slot and round. **Only in the pod.** |
| league config | `leagues/<key>.toml` | in git; nothing to capture |
| projections | `data/cache/sleeper_projections_<season>_<pos>.json` | drives points, so drives VORP |
| opportunity frames | `data/cache/nflverse/` | drives the usage model |
| player catalog | `data/cache/sleeper_players_nfl.json` | names, positions, teams, eligibility |
| ESPN pool / ranks | `data/cache/espn_*_<league_id>_*.json` | the vs-ESPN column |

The whole directory is ~22 MB, so capture all of it rather than picking files.

**No new code is required.** Everything the replay needs is either in git or already written
to `/app/data` by the running cockpit.

## The one caveat, worth knowing before it bites

The capture reconstructs *what the board would say from that cache*, which is exact only if
the cache still holds the inputs the board was built from on the night.

For DDAFFL that is nearly true but not entirely: projections (2026-08-25) and nflverse
frames (2026-08-27) both predate the 2026-08-30 draft, but **`sleeper_players_nfl.json` was
refreshed on 2026-09-01**, after it. The catalog carries names, positions and eligibility
rather than projections, so it does not move VORP — but it is not the draft-night copy, and a
replay that depends on eligibility should say so.

Capturing the pod's directory Saturday night avoids this for Saturday's draft: nothing will
have refreshed it in between.
