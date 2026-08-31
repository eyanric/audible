# Draft night

Cockpit: **http://127.0.0.1:8080/**
Spare: **http://127.0.0.1:18080/**

---

## Players are not disappearing as picks happen

You mark someone, or ESPN picks someone, and he stays on the board.

1. Look at the sync chip, top right. If it is red or says stale, the feed is not
   reaching you — go to hand mirroring below.
2. If the feed is live and players still are not leaving, hand mirror.

**Hand mirroring.** Mark *every* pick as it happens — yours and everyone else's,
in order, no gaps.

This matters more than it sounds. Picks are attributed by position in the order,
not by name. Skip one and every pick after it goes to the wrong team, including
yours. If you fall behind, catch up in order before you do anything else.

---

## The board looks wrong, or the wrong player disappeared

Close the server window. Then run:

```
set AUDIBLE_ESPN_NAME_MATCH=0 && C:\dev\audible\scripts\draft-day.cmd
```

That turns off name-based ID matching and goes back to the older, narrower
matching. Fewer players will be matched from ESPN picks — so plan to hand mirror
— but nothing will be matched to the wrong man.

---

## You marked the wrong player

Click **Undo** at the top of Grab now. Or press `u`. Or `ctrl+z`.

The button names who it will undo. Check the name before you click.

It survives a page reload now. If you reload, Undo still works and still names
the right player.

Click it again to go back further, one pick at a time.

---

## The page froze or went blank

**Reload the page first.** F5.

Your picks live on the server, not in the page. Reloading loses nothing.

If reloading does not fix it, close the server window and run:

```
C:\dev\audible\scripts\draft-day.cmd
```

If that does not come back, open the spare: **http://127.0.0.1:18080/**

---

## The sync chip goes orange or red

Orange means the feed is slow. Keep going, watch it.

Red means the feed has stopped. The board is still correct — it is showing you
the last thing it knew. Start hand mirroring now and keep going until the chip
goes green again.

Do not restart anything just because the chip is red. A restart costs you a
minute and does not fix ESPN.

---

## It says DRAFT COMPLETE and the draft is not over

It thinks all 128 picks are in. Check the pick counter at the top left — it reads
`PICK n of 128`.

If it says 128 and fewer than 128 picks have really happened, you have marked
somebody twice. Press Undo until the count matches reality, then carry on.

---

## Start the cockpit from scratch

Close the server window first, then:

```
C:\dev\audible\scripts\draft-day.cmd
```

Leave that window open. Closing it stops the cockpit.

---

## The spare on 18080

It is a second copy on the same data, already running. Use it if the main one
will not come back.

**It does not have your picks.** Picks that came from ESPN will refill on its
first check. Anything you entered by hand will not — you would have to re-enter
those, in order.

Treat it as a way to keep looking at a board, not as a way to keep your draft.

---

## When to stop fighting it

If you are spending more than about a minute on the tool while the clock runs,
stop. Take the best player on the last board you trusted.

A board that is a few picks stale plus your own judgement beats a cockpit you are
arguing with. You know this league.

---

## After the draft

Close the "audible cockpit" window deliberately. Do not leave it running.

Then check the session is clean for next time:

```
type C:\dev\audible\data\cache\draft-state-espn_davis_drive.json
```

You want to see `"manual_picks": []`.

If it lists picks, open the cockpit and press Undo until the counter reads
`PICK 1 of 128`.

Every messy session this week came from one being left running.
