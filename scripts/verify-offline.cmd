@echo off
REM ============================================================================
REM  audible - A3 offline re-proof, ON THE PINNED ARTIFACT
REM
REM  The offline property was proven in development. This proves it on the image
REM  that will actually run on draft night, which is the check most likely to
REM  catch a packaging difference - a missing file, a wrong path, a volume that
REM  is not where the code looks for it.
REM
REM  --network none removes the container's network namespace entirely. There is
REM  no interface to reach, so this is an OS-level block, not a mocked one.
REM
REM  Run this AFTER draft-day.cmd has pulled the image at least once.
REM ============================================================================

setlocal

set "AUDIBLE_IMAGE=ghcr.io/eyanric/audible@sha256:d3cdb2a101aaddfb88515956e93163d2f7bfa106273dd5da6e688d67339be570"

echo.
echo   audible - offline re-proof
echo   image : %AUDIBLE_IMAGE%
echo.

docker version >nul 2>&1
if errorlevel 1 (
  echo   [X] Docker is not running. Start Docker Desktop and run this again.
  pause
  exit /b 1
)

echo   [1/3] Pulling the pinned digest (this step needs the network)...
docker pull %AUDIBLE_IMAGE%
if errorlevel 1 (
  echo   [X] Pull failed. Cannot verify an artifact that is not here.
  pause
  exit /b 1
)

echo.
echo   [2/3] Filling the cache volume using the PINNED image itself...
echo         (same code writes the cache that will later read it)
docker run --rm --env-file .env -v audible-cache:/app/data %AUDIBLE_IMAGE% ^
  audible refresh-data
if errorlevel 1 (
  echo   [X] refresh-data failed. The cache is not populated; stop and fix.
  pause
  exit /b 1
)

echo.
echo   [3/3] Building both boards with NO NETWORK AT ALL...
echo.
echo   --- League B (espn_davis_drive) ---
docker run --rm --network none -v audible-cache:/app/data %AUDIBLE_IMAGE% ^
  audible draft espn_davis_drive --top 5
if errorlevel 1 goto failed

echo.
echo   --- League A (sleeper_boyfun) ---
docker run --rm --network none -v audible-cache:/app/data %AUDIBLE_IMAGE% ^
  audible draft sleeper_boyfun --top 5
if errorlevel 1 goto failed

echo.
echo   ============================================================
echo    PASS - both boards built inside the pinned image with the
echo    network namespace removed. Draft night survives a dead wifi.
echo   ============================================================
echo.
pause
exit /b 0

:failed
echo.
echo   ============================================================
echo    FAIL - a board did NOT build offline on the pinned image.
echo
echo    Do not freeze on this digest. Most likely causes:
echo      - the audible-cache volume is empty or mounted elsewhere
echo      - refresh-data did not cover the league that failed
echo    Re-run step 2, then this script again.
echo   ============================================================
echo.
pause
exit /b 1
