"""The only module that touches a browser.

WHY A BROWSER AT ALL. The download link's href is session-bound. MEASURED on a live logged-in
session, it is RELATIVE and carries no worker prefix:

    session/f8ef99aeb854208d8b1abc8914a0276b/download/
        projections_page-proj-download_projections-download?w=32ee825bd77448a6a38c279b8174d2a1

not the absolute `/newApp/_w_<worker>/session/<id>/...` form this module was first written
against. That matters: the first `session_token` split on "/session/", found nothing in a
perfectly good href, and returned None -- which would have made `assert_same_session` raise on
every job in the run.

There is no parameterised URL either way. The year, week, aggregation and file type are inputs
to a live Shiny session, and the file comes back from that session's own endpoint. A plain
HTTP loop cannot express it.

THE FIVE BEHAVIOURS THIS DRIVER IS SHAPED AROUND, each measured rather than documented by the
app, and each re-measured by `probe.py` before a run is trusted:

  1. CHANGING THE YEAR RESETS THE AGGREGATION TO `weighted` SERVER-SIDE. This is what produced
     36 mislabelled files. So the aggregation is set AFTER the year, never before, on every
     single job -- there is no "it is already set" fast path, because that assumption is the
     defect.
  2. AN AGGREGATION ONLY TAKES EFFECT AFTER A SETTINGS -> PROJECTIONS ROUND TRIP, with a long
     settle. Setting it while on the Projections page does nothing at all.
  3. `weighted` NEEDS NO SETTINGS TRIP *AFTER A REAL YEAR CHANGE*, because that is what
     leaves the app on weighted. Writing 2019 over 2019 is not a change and resets nothing --
     measured, and the live app served `robust` for a `weighted` request one job after a
     robust one in the same season. `prepare` therefore tracks the EFFECTIVE aggregation.
  4. RAW FILES SELF-VERIFY on their fifth column; `proj` files cannot. `verify.py` holds that.
  5. THE POSITION DROPDOWN FILTERS THE CHART ONLY. A download carries every position the app
     has FOR THAT SCOPE, which is not always nine: weekly 2015 carries only the six offensive
     and special-teams positions, and 2016 wk13-17 and 2017 wk7 lose IDP too. `verify.py`
     requires the six everywhere and records IDP rather than demanding it.

SESSIONS DROP. shinyapps.io reloads on idle or on a resource cap, and a reload resets the year
to 2026, the week to 0 and the file type to `proj` with no input from us. That is not an
exceptional path -- it is the expected one over a run of hundreds of files -- so every input is
READ BACK after it is set, and a read-back that disagrees is treated as a lost session rather
than as a slow one.

NO BROWSER DOWNLOADS. The payload is fetched from inside the page and written by Python under
the name `naming.filename` computed. Chrome's `(1)`/`(2)` suffixing is what made the prior
attempt's contamination unrecoverable, and the only way to be sure it cannot happen is for the
browser never to write a file at all.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

APP_URL = "https://ffashiny.shinyapps.io/newApp/"

# The public site embeds this app in a cross-origin iframe. Going direct is not a shortcut --
# a cross-origin frame cannot be reached by `page.evaluate` at all.
YEAR_INPUT = "sidebar-year-drop"
WEEK_INPUT = "sidebar-week-drop"
AVG_INPUT = "settings_page-data_aggregation_box-average_type-drop"
KIND_INPUT = "projections_page-proj-download_choice-drop"

TAB_PROJ = "tab_proj"
TAB_SETTINGS = "tab_settings"

DOWNLOAD_LINK = "a#projections_page-proj-download_projections-download"

# The link's text is the login state. "Subscribe to download" means the session is either
# logged out or has lost its subscription context, and every fetch from it would come back
# as HTML rather than CSV.
READY_TEXT = "Download"
LOCKED_TEXT = "Subscribe to download"

# Matches the relative form the app actually serves and an absolute one, so a
# change back to `/newApp/_w_<worker>/session/<id>/` does not silently read None.
_SESSION_RE = re.compile(r"(?:^|/)session/([^/?#]+)/")


class SessionLost(RuntimeError):
    """The Shiny session went away, or came back as a different one.

    Raised rather than papered over: the caller re-establishes and re-runs the job from the
    top, because a half-configured session is exactly the state that produced mislabelled
    files.
    """


class NotLoggedIn(RuntimeError):
    """The download control says `Subscribe to download`. A human has to fix this."""


@dataclass(frozen=True)
class Settles:
    """Empirical waits, in seconds. Not documented by the app; measured, and load-dependent.

    `probe.py` re-measures the two that matter before a run, and a job that fails
    verification is retried once with everything scaled by `RETRY_SCALE` -- because the most
    likely cause of a mismatch is a settle that was too short under load.
    """

    action: float = 1.0  # between any two UI actions; this is the politeness floor
    after_year: float = 2.5
    after_week: float = 2.0
    after_avg: float = 2.0
    after_tab_proj: float = 12.0  # measured working
    after_kind: float = 7.0  # measured working
    # After the app reports itself populated, before the idle baseline is taken. A baseline
    # captured any earlier carries outputs that are still genuinely working.
    after_load: float = 6.0
    idle_timeout: float = 20.0
    # How long an output may stay continuously busy before it is reclassified as one that
    # never resolves. Comfortably longer than a real recalculation and far shorter than the
    # idle timeout, so a genuinely slow output is still waited for.
    stuck_after: float = 4.0
    # The app is slow to populate its widgets on a cold worker; this is the wait for the
    # year dropdown to hold a real value, not for the DOM to exist.
    ready_timeout: float = 180.0

    def scaled(self, factor: float) -> Settles:
        return replace(
            self,
            action=self.action * factor,
            after_year=self.after_year * factor,
            after_week=self.after_week * factor,
            after_avg=self.after_avg * factor,
            after_tab_proj=self.after_tab_proj * factor,
            after_kind=self.after_kind * factor,
            after_load=self.after_load * factor,
        )


RETRY_SCALE = 2.0

# Read the value of a selectize widget. The instance hangs off the ORIGINAL select element,
# which selectize keeps in the DOM and hides.
_GET_JS = """
(id) => {
  const el = document.getElementById(id);
  if (!el) return {found: false, value: null};
  if (el.selectize) return {found: true, value: String(el.selectize.getValue())};
  return {found: true, value: el.value === null ? null : String(el.value)};
}
"""

_SET_JS = """
([id, value]) => {
  const el = document.getElementById(id);
  if (!el || !el.selectize) return false;
  el.selectize.setValue(value, false);
  return true;
}
"""

# MEASURED, and not what was assumed. Five outputs on tabs this run never opens
# (`settings_page-settings_tiering_ui`, `optimizer_page-optimizer-optimizer_display_ui`,
# `accuracy_page-acc_ui`, `account_page-user_subscription_box-cportal`,
# `controlbar-help_links`) carry `.recalculating` FOREVER -- Shiny never resolves an output
# that is never rendered. A predicate of "no element is recalculating" can therefore never
# be true on this app, and the first version of this driver burned its full 45s timeout on
# every single wait. Over 600 files that is seven hours of doing nothing.
#
# `document.documentElement.classList.contains('shiny-busy')` is likewise never true here,
# and `data-shiny-busy` is absent, so that half of the predicate was inert as well.
#
# So idle is BASELINE-RELATIVE: whatever was stuck when the session was established stays
# stuck and is not evidence of work. Anything recalculating BEYOND that baseline is.
_BUSY_JS = """
() => {
  const busy = Array.from(document.querySelectorAll('.recalculating'))
                    .map(e => e.id).filter(Boolean);
  const app = (typeof Shiny !== 'undefined') ? Shiny.shinyapp : null;
  const pending = (app && app.$pendingMessages) ? app.$pendingMessages.length : 0;
  return {busy: busy, pending: pending};
}
"""

# Populated, not merely present. The year dropdown holding a four-character value and the
# download control holding any text at all are what say the app has finished loading.
_READY_JS = f"""
() => {{
  const year = document.getElementById('{YEAR_INPUT}');
  const link = document.querySelector('{DOWNLOAD_LINK}');
  return !!(year && year.selectize
            && String(year.selectize.getValue() || '').length === 4
            && link && (link.textContent || '').trim().length > 0);
}}
"""

_HREF_JS = """
(selector) => {
  const el = document.querySelector(selector);
  if (!el) return {found: false, href: null, text: null};
  return {found: true, href: el.getAttribute('href'), text: (el.textContent || '').trim()};
}
"""

# credentials:'include' keeps the session cookie, which is what makes the href resolve to a
# file rather than to a login page. The response is returned as text and written by Python.
_FETCH_JS = """
async (href) => {
  try {
    const r = await fetch(href, {credentials: 'include'});
    const text = await r.text();
    return {ok: r.ok, status: r.status, type: r.headers.get('content-type') || '', text: text};
  } catch (err) {
    return {ok: false, status: 0, type: '', text: '', error: String(err)};
  }
}
"""


@dataclass
class FetchResult:
    ok: bool
    status: int
    content_type: str
    text: str
    error: str = ""


class ShinyDriver:
    """One live app session, with every input read back after it is written."""

    def __init__(self, page: Any, settles: Settles | None = None, log: Any = print) -> None:
        self.page = page
        self.settles = settles or Settles()
        self.log = log
        self._session_token: str | None = None
        self._idle_baseline: frozenset[str] = frozenset()
        # What the SERVER will serve, which is not what the widget reads.
        # None means unknown, and unknown pays for a Settings trip.
        self._effective_avg: str | None = None

    # -- primitives ---------------------------------------------------------------------

    def _pause(self, seconds: float) -> None:
        time.sleep(seconds)

    def busy_beyond_baseline(self) -> set[str]:
        """Output ids recalculating that are not in the known-stuck set."""
        state = self.page.evaluate(_BUSY_JS)
        busy = set(state["busy"]) - self._idle_baseline
        if state["pending"]:
            busy.add(f"$pendingMessages={state['pending']}")
        return busy

    def wait_idle(self) -> None:
        """Wait until Shiny has stopped doing work it started for US.

        THE STUCK SET GROWS. A baseline taken at establish time can only cover outputs that
        were already pending on the Projections tab. The first click to Settings renders
        outputs that were never requested before, and some of THOSE never resolve either --
        measured: after this was baseline-only, every Settings trip sat out the full idle
        timeout again. So an output that stays continuously busy for `stuck_after` seconds
        is reclassified as stuck and stops being waited on, for the rest of the session.

        NOT a substitute for the settles. Idle means no request is in flight; it does not
        mean the server has finished propagating an aggregation change through to the
        download handler. Behaviour 2 is precisely a case where the page is idle and the
        answer is still stale.
        """
        started = time.time()
        deadline = started + self.settles.idle_timeout
        since: dict[str, float] = {}
        while time.time() < deadline:
            try:
                busy = self.busy_beyond_baseline()
            except Exception as exc:  # noqa: BLE001 -- a navigation mid-poll is not fatal
                self.log(f"    idle poll interrupted: {exc}")
                time.sleep(0.25)
                continue
            if not busy:
                return
            now = time.time()
            for name in busy:
                since.setdefault(name, now)
            newly_stuck = {
                name
                for name, first in since.items()
                if name in busy
                and not name.startswith("$")
                and now - first >= self.settles.stuck_after
            }
            if newly_stuck:
                self._idle_baseline |= frozenset(newly_stuck)
                self.log(f"    {len(newly_stuck)} more output(s) never resolve; "
                         f"stuck set is now {len(self._idle_baseline)}")
            # SLEEP ON EVERY PATH, including the one that just grew the stuck set. This
            # used to `continue` instead, and that is a spin: `busy_beyond_baseline` adds
            # the `$pendingMessages` marker AFTER subtracting the baseline, so a marker can
            # never be subtracted out. Anything that keeps producing `newly_stuck` therefore
            # re-enters the loop immediately, forever, without pacing. Against the live app
            # the real clock still bounds it at `idle_timeout`, so it presents as a CPU spin
            # rather than a hang -- but a mutation that let the marker into the stuck set
            # froze the whole gate suite for nine minutes, which is how this surfaced.
            time.sleep(0.25)
        self.log(f"    still busy after {self.settles.idle_timeout}s; continuing")

    def read_input(self, input_id: str) -> str | None:
        result = self.page.evaluate(_GET_JS, input_id)
        if not result["found"]:
            raise SessionLost(f"input {input_id} is not on the page")
        return result["value"]

    def set_input(self, input_id: str, value: str, settle: float) -> None:
        """Set, wait, and READ BACK. A read-back that disagrees is a lost session."""
        ok = self.page.evaluate(_SET_JS, [input_id, value])
        if not ok:
            raise SessionLost(f"input {input_id} has no selectize instance")
        self._pause(self.settles.action)
        self.wait_idle()
        self._pause(settle)
        seen = self.read_input(input_id)
        if seen != value:
            raise SessionLost(f"{input_id} reads {seen!r} after being set to {value!r}")

    def click_tab(self, tab: str) -> None:
        self.page.click(f'a[data-value="{tab}"]')
        self._pause(self.settles.action)
        self.wait_idle()

    # -- session ------------------------------------------------------------------------

    def download_control(self) -> tuple[str | None, str | None]:
        result = self.page.evaluate(_HREF_JS, DOWNLOAD_LINK)
        if not result["found"]:
            return None, None
        return result["href"], result["text"]

    def session_token(self) -> str | None:
        """The session id out of the download href. A change means the session was replaced.

        MEASURED: the href is RELATIVE and has no worker prefix --

            session/f8ef99aeb854208d8b1abc8914a0276b/download/
                projections_page-proj-download_projections-download?w=32ee825b...

        not the absolute `/newApp/_w_<worker>/session/<id>/...` this was first written for.
        Splitting on "/session/" found nothing and returned None for a perfectly good
        session, which would have made `assert_same_session` raise on every job.
        """
        href, _ = self.download_control()
        if not href:
            return None
        match = _SESSION_RE.search(href)
        return match.group(1) if match else None

    def establish(self, *, expect_login: bool = True) -> None:
        """Navigate, wait for the app, and confirm the download control is unlocked."""
        self.page.goto(APP_URL, wait_until="domcontentloaded", timeout=120_000)
        self.page.wait_for_function("() => typeof Shiny !== 'undefined'", timeout=120_000)
        self.page.wait_for_selector(DOWNLOAD_LINK, timeout=120_000)

        # MEASURED: the link element appears long before the app is usable. A headless
        # session that read straight through here saw year='', week='' and a download
        # control whose text was the empty string -- the widgets exist and Shiny has not
        # populated them yet. Waiting on POPULATED state rather than on presence is the
        # difference between a probe that measures the app and one that measures its
        # loading screen.
        self.page.wait_for_function(
            _READY_JS, timeout=self.settles.ready_timeout * 1000
        )

        # Take the idle baseline only once the app is populated, and AFTER a settle -- a
        # baseline captured mid-load carries outputs that are still genuinely working, and
        # would then swallow real work for the rest of the session. Nine were captured that
        # way against the live app; the settled figure is five.
        self._idle_baseline = frozenset()
        self._pause(self.settles.after_load)
        self._idle_baseline = frozenset(self.page.evaluate(_BUSY_JS)["busy"])
        self.log(f"  idle baseline: {len(self._idle_baseline)} outputs never resolve")
        self.wait_idle()
        self._pause(self.settles.action)
        href, text = self.download_control()
        if expect_login and text == LOCKED_TEXT:
            raise NotLoggedIn(
                f"the download control reads {text!r}. Run the `login` command and sign in "
                "by hand -- this tool never handles the password."
            )
        self._session_token = self.session_token()
        # A re-established session is a new session. Nothing is remembered
        # about what it will serve.
        self._effective_avg = None
        self.log(f"  session {self._session_token}, control reads {text!r}")

    def assert_same_session(self) -> None:
        token = self.session_token()
        if token is None:
            raise SessionLost("the download control is gone")
        if self._session_token is not None and token != self._session_token:
            raise SessionLost(f"session changed {self._session_token} -> {token}")

    # -- the job sequence ---------------------------------------------------------------

    def prepare(
        self, kind: str, year: int, week: int, avg: str, *, force_settings_trip: bool = False
    ) -> None:
        """Put the live session into the state this job asks for.

        ORDER IS THE WHOLE POINT. Year first, because setting it resets the aggregation.
        Aggregation second and only via Settings, because setting it on the Projections page
        has no effect. File type last, because it is the only input whose settle is short.

        A YEAR CHANGE ONLY RESETS THE AGGREGATION WHEN THE YEAR ACTUALLY CHANGES. Writing
        2019 over 2019 is not a change and resets nothing -- measured against the live app,
        which served `robust` for a `weighted` request one job after a robust one in the same
        season. The first version of this method skipped the Settings trip for every weighted
        job on the strength of a reset that had not happened.

        So the driver tracks the EFFECTIVE aggregation -- what the SERVER will serve, which
        is not what the widget reads (behaviour 2) -- and takes the trip whenever that is not
        already what the job wants. Seventeen weekly jobs in one season still cost at most
        one trip between them, so the cost model that orders the stages survives.

        None means unknown, which is what a fresh or re-established session gets. Unknown
        takes the trip: a reload does leave the app on `weighted`, but believing that without
        checking is the same class of assumption that produced 36 mislabelled files.
        """
        self.click_tab(TAB_PROJ)
        year_before = self.read_input(YEAR_INPUT)
        self.set_input(YEAR_INPUT, str(year), self.settles.after_year)
        if year_before != str(year):
            self._effective_avg = "weighted"  # behaviour 1, and only on a real change
        self.set_input(WEEK_INPUT, str(week), self.settles.after_week)

        if force_settings_trip or self._effective_avg != avg:
            self.click_tab(TAB_SETTINGS)
            self.set_input(AVG_INPUT, avg, self.settles.after_avg)
            self.click_tab(TAB_PROJ)
            self._pause(self.settles.after_tab_proj)
            self.wait_idle()
            self._effective_avg = avg

        self.set_input(KIND_INPUT, kind, self.settles.after_kind)

        # Read every input back TOGETHER at the end. Each was checked when it was written,
        # but a session that dropped between two writes would have silently reset the first.
        seen = {
            YEAR_INPUT: self.read_input(YEAR_INPUT),
            WEEK_INPUT: self.read_input(WEEK_INPUT),
            KIND_INPUT: self.read_input(KIND_INPUT),
        }
        wanted = {YEAR_INPUT: str(year), WEEK_INPUT: str(week), KIND_INPUT: kind}
        drifted = {k: (seen[k], wanted[k]) for k in wanted if seen[k] != wanted[k]}
        if drifted:
            raise SessionLost(f"inputs drifted before the fetch: {drifted}")
        self.assert_same_session()

    def fetch_payload(self) -> FetchResult:
        href, text = self.download_control()
        if href is None:
            raise SessionLost("no download control to fetch from")
        if text == LOCKED_TEXT:
            raise NotLoggedIn(f"the download control reads {text!r} mid-run")
        result = self.page.evaluate(_FETCH_JS, href)
        return FetchResult(
            ok=bool(result.get("ok")),
            status=int(result.get("status") or 0),
            content_type=str(result.get("type") or ""),
            text=str(result.get("text") or ""),
            error=str(result.get("error") or ""),
        )


def open_context(playwright: Any, profile_dir: Path, *, headless: bool) -> Any:
    """A PERSISTENT context, so the human logs in once and the profile carries it forward.

    The profile holds a live session cookie for a paid account. It lives under
    `data/sim-cache/`, which is gitignored for the same reason the corpus is.
    """
    profile_dir.mkdir(parents=True, exist_ok=True)
    return playwright.chromium.launch_persistent_context(
        user_data_dir=str(profile_dir),
        headless=headless,
        viewport={"width": 1440, "height": 1000},
        args=["--disable-blink-features=AutomationControlled"],
    )
