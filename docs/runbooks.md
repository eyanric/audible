# Runbooks live in haven, not here

The draft-night runbook is `docs/runbooks/draft-night.md` in **`eyanric/haven`**. It is the
current one and the only one.

Two runbooks used to live here and were deleted on 2026-09-05: `draft-night-runbook.md` and
`runbook-draft-day.md`. Both had gone dangerously stale:

- three dead addresses between them: `127.0.0.1:8080`, `127.0.0.1:18080` and `192.168.1.110`;
- a `draft_id 6012` and a `draft-state-espn_davis_drive.json` post-draft check, for a league
  that finished on 2026-08-30 and that no cockpit serves;
- a `PICK n of 128` counter, for an 8-team draft; tonight's are 190 and 160;
- a T-24h / T-30m clock built around a draft on Sunday 30 August.

They were deleted rather than archived: a stale runbook in the repo is a runbook someone opens
at 20:15.

**One correction to what was believed about them.** `scripts/draft-day.cmd` still exists and
still works — it was the *spare cockpit on `127.0.0.1:18080` and its volume* that the DDAFFL
close-out removed, not the launcher. Both ports are free.
