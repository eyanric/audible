# `qa-desktop.py` — known failures

Standing entries in the suite's third bucket: observations that are **true, reported on
every run, and accepted** — but not treated as failures.

## The rule that makes this bucket safe

`known()` is not a mute button. **If a known failure starts passing, the run goes red** and
names the entry to promote. A state change is the thing worth being told about, and a suite
that can quietly reclassify itself has stopped being an instrument.

This is the same asymmetry the `verify-offline.cmd` work landed: a guard that can only ever
be satisfied is not a guard. Before an entry is added here, it must be demonstrated that it
*can* fire — see the forced-failure demonstration in the PR that introduced it.

Nothing here is deleted from the suite. The observation still prints on every run; only its
verdict changed.

---

## `1920x1080: shows MORE recommend rows than mobile (DOM)`
## `2560x1440: shows MORE recommend rows than mobile (DOM)`

**Accepted:** 2026-08-31
**Observed:** `desktop rows=140 vs mobile rows=140` at both desktop viewports.

**Why it is accepted**

`MAX_ROWS` in `index.html` is a viewport-independent hard cap (140), so desktop width buys
no extra DOM rows by construction. The assertion encodes a *design opinion* — that width
should buy rows — rather than a defect, and the two sibling checks in the same block already
answer the underlying question better:

- `no stranded narrow column` tests whether the layout actually *uses* the width.
- `shows MORE rows without scrolling` tests the honest visible-row question, which is a
  viewport-**height** effect rather than a width one.

Both pass at both desktop sizes. Making this one green would mean implementing
viewport-aware `MAX_ROWS` — building a feature to satisfy a test, on a surface the C3/D
weekly-mode reframe may replace outright.

**What would justify promoting it back to `check()`**

Weekly mode keeps this board *and* a multi-column desktop layout is decided on. At that
point "more width should mean more rows" stops being an opinion and becomes the spec, and
the cap should become viewport-aware rather than the check becoming lenient.

---

## Retired from this list

### `digit keys switch sections with the search box focused (the eyes-off state)`

**Not accepted — fixed**, 2026-08-31, in the same change that introduced this file.

It was a genuine defect rather than a design opinion: `#legendDigits` advertises `0-6`, but
the search box holds focus on load and returns there after every Enter, so in the only state
the board is actually driven from, the advertised shortcut typed a character into the search
box instead.

The fix is a single guarded block in the typing branch of the keydown handler: **a digit
while the search box is focused and the query is empty switches sections; otherwise it
types.** The first character of any query is by definition typed into an empty box, so this
is only safe if no reachable name can begin with a digit. That was audited rather than
assumed:

```
board entries audited across both leagues : 10,928
names beginning with a digit              : 0
names containing a digit anywhere         : 0
full Sleeper catalog entries              : 12,225
catalog names beginning with a digit      : 0
```

Team defences are stored as abbreviations (`SF`, `LAR`, `HOU`), not `"San Francisco 49ers"`,
which is what would otherwise have made `4` a plausible first keystroke. The search matches
`p.name` only — no field with digits in it is searchable — so there is no reachable query
whose first character is a digit.

Both digit checks now pass: the search-focused one and the after-Escape one. The suite asks
the question twice on purpose and both were kept.
