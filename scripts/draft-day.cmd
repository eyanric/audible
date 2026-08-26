@echo off
REM ============================================================================
REM  audible - draft day launcher (DESKTOP)
REM
REM  Double-click this. It starts the cockpit and opens the browser.
REM  Production quality for one operator means not remembering flags at 7pm.
REM
REM  RUNS FROM SOURCE, NOT FROM A CONTAINER. The old launcher pinned a Docker
REM  digest, and the digest it pinned - d3cdb2a1, main @ 39a13f3 - predates the
REM  replacement-level fix, so the top D/ST ranked 33rd overall on the board it
REM  served. Pinning is the right instinct for a thing you deploy and forget;
REM  it is the wrong one for the machine you are drafting on, where the repo IS
REM  the artifact and `git log` is the version. Source also means a fix found at
REM  7:45 is one restart away instead of one CI build away.
REM
REM  Docker is no longer required or used. The container path is gone rather
REM  than kept as a fallback: two ways to start the cockpit is two things to be
REM  wrong about at kickoff. If this will not run, the fallback is the runbook's
REM  ladder, not a second launcher.
REM
REM  LOCALHOST ONLY. Eric drafts at this desk; the phone is a fallback surface
REM  now, and 0.0.0.0 was only ever there to reach it. 127.0.0.1 keeps the
REM  cockpit off the LAN entirely.
REM ============================================================================

setlocal

REM Repo root is derived from THIS FILE's location, so the launcher works from
REM any working directory - including C:\, which is where a double-click from a
REM pinned shortcut can land you.
set "REPO=%~dp0.."
pushd "%REPO%" || (echo   [X] Cannot reach the repo at "%REPO%". & pause & exit /b 1)
set "REPO=%CD%"

set "AUDIBLE_PORT=8080"
set "AUDIBLE_LEAGUE=espn_davis_drive"

echo.
echo   audible cockpit
echo   league : %AUDIBLE_LEAGUE%
echo   source : %REPO%
echo   url    : http://127.0.0.1:%AUDIBLE_PORT%/
echo.

REM ---------------------------------------------------------------------------
REM  uv is the only prerequisite. Check it by running it: on PATH is not the
REM  same as working, and a broken uv at 7pm should say so here rather than in
REM  a window that has already scrolled past.
REM ---------------------------------------------------------------------------
uv --version >nul 2>&1
if errorlevel 1 (
  echo   [X] uv is not installed, or not on PATH for this shell.
  echo.
  echo       Install:  winget install --id=astral-sh.uv -e
  echo       Or see :  https://docs.astral.sh/uv/getting-started/installation/
  echo.
  echo       Expected at: %%USERPROFILE%%\.local\bin\uv.exe
  echo       If it is there but this failed, the installer's PATH entry did not
  echo       survive - open a NEW terminal, or add that folder to PATH.
  echo.
  popd
  pause
  exit /b 1
)
for /f "tokens=*" %%V in ('uv --version 2^>nul') do set "UVVER=%%V"
echo   uv     : %UVVER%

REM ---------------------------------------------------------------------------
REM  Sync once, up front. `uv run` would do this implicitly, but doing it here
REM  means a slow or failed dependency resolve reports itself now - before the
REM  server window opens and the browser starts polling a port nothing is on.
REM
REM  --extra nflverse IS LOAD-BEARING, on BOTH lines. The board is built by the
REM  nflverse adapter, and a plain `uv sync` does not just skip the extra - it
REM  UNINSTALLS it, so the server comes up, answers, and serves /healthz 503
REM  forever with "the nflverse adapter needs the optional dependency". A cockpit
REM  that starts and never becomes ready is the worst failure shape there is: it
REM  looks like a slow board build right up until the draft starts.
REM ---------------------------------------------------------------------------
echo   syncing dependencies...
uv sync --quiet --extra nflverse
if errorlevel 1 (
  echo.
  echo   [X] uv sync failed. The cockpit cannot start until it does.
  echo       Run it by hand to see why:  uv sync
  echo.
  popd
  pause
  exit /b 1
)

REM  THE WAIT LOOP SLEEPS WITH `ping`, NOT `timeout`, AND THAT IS DELIBERATE.
REM  `timeout` has two failure modes here: a bare `timeout` resolves to GNU
REM  coreutils when anything git-related sits earlier on PATH (GNU rejects `/t`,
REM  so the loop stops sleeping and burns all 90 tries in two seconds), and even
REM  the real timeout.exe refuses to run at all when stdin is redirected -- which
REM  it is from a shortcut or a scheduled task. `ping` has neither problem.
REM ---------------------------------------------------------------------------
REM  The server runs in ITS OWN window, deliberately. It is a foreground
REM  process - unlike the old detached container, closing its window stops the
REM  cockpit - so it gets a window that says so in the title bar rather than
REM  sharing one with this script's output.
REM ---------------------------------------------------------------------------
echo   starting server...
start "audible cockpit - LEAVE THIS WINDOW OPEN" /d "%REPO%" cmd /k ^
  uv run --extra nflverse audible serve --host 127.0.0.1 --port %AUDIBLE_PORT% --league %AUDIBLE_LEAGUE%

echo.
echo   Waiting for the board to build (a minute or two on a cold cache)...
set /a tries=0

:wait
set /a tries+=1
set "CODE="
for /f %%C in ('curl -s -o nul -w "%%{http_code}" http://127.0.0.1:%AUDIBLE_PORT%/healthz 2^>nul') do set "CODE=%%C"
if "%CODE%"=="200" goto ready
if %tries% GEQ 90 goto slow
ping -n 6 127.0.0.1 >nul
echo     still warming... (%tries%/90, /healthz=%CODE%)
goto wait

:slow
echo.
echo   [!] The board is taking longer than expected. Opening anyway - the page
echo       will say what it is waiting on. Check the server window for errors.
goto open

:ready
echo   Board ready.
REM /healthz reports where the board's inputs came from. `disk` means the
REM cockpit is network-independent from here on, which is the property that
REM matters once the draft starts.
set "ORIGIN="
for /f %%O in ('curl -s http://127.0.0.1:%AUDIBLE_PORT%/healthz ^| findstr /C:"disk" 2^>nul') do set "ORIGIN=disk"
if "%ORIGIN%"=="disk" (
  echo   Data   : from DISK - this cockpit does not need the network.
) else (
  echo   [!] Data did NOT come from the disk cache. If the network drops you lose
  echo       the board on the next restart. Fix now:  uv run audible refresh-data
)

:open
start "" http://127.0.0.1:%AUDIBLE_PORT%/
echo.
echo   Cockpit  : http://127.0.0.1:%AUDIBLE_PORT%/
echo   MCP      : http://127.0.0.1:%AUDIBLE_PORT%/mcp
echo   Health   : http://127.0.0.1:%AUDIBLE_PORT%/healthz
echo.
echo   Stop     : close the "audible cockpit" window, or Ctrl+C in it.
echo   Restart  : run this script again.
echo.
echo   THE SERVER IS THE OTHER WINDOW. Closing it stops the cockpit; closing
echo   THIS one is harmless.
echo.
popd
pause
endlocal
