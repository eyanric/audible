@echo off
REM ============================================================================
REM  audible - draft day launcher
REM
REM  Double-click this. It starts the cockpit container and opens the browser.
REM  Production quality for one operator means not remembering flags at 8pm.
REM
REM  PINNED for draft week to an explicit DIGEST, not a tag. `latest` can move
REM  under you the night before; a digest cannot. This one is main @ 39a13f3.
REM
REM  The image bakes --league sleeper_boyfun as its default command. Draft night is
REM  LEAGUE B, so the command is overridden below rather than rebuilt - one image
REM  serves either league, and the league you are drafting is visible right here
REM  instead of buried in a layer.
REM ============================================================================

setlocal

set "AUDIBLE_IMAGE=ghcr.io/eyanric/audible@sha256:d3cdb2a101aaddfb88515956e93163d2f7bfa106273dd5da6e688d67339be570"
set "AUDIBLE_PORT=8080"
set "AUDIBLE_NAME=audible-cockpit"
set "AUDIBLE_LEAGUE=espn_davis_drive"

echo.
echo   audible cockpit
echo   league: %AUDIBLE_LEAGUE%
echo   image : %AUDIBLE_IMAGE%
echo   port  : %AUDIBLE_PORT%
echo.

docker version >nul 2>&1
if errorlevel 1 (
  echo   [X] Docker is not running. Start Docker Desktop and run this again.
  echo.
  echo   Fallback while you wait - from the repo, this needs no container:
  echo       uv run audible serve --league %AUDIBLE_LEAGUE%
  echo.
  pause
  exit /b 1
)

REM Replace any previous container so a re-run is always safe.
docker rm -f %AUDIBLE_NAME% >nul 2>&1

echo   pulling...
docker pull %AUDIBLE_IMAGE%
if errorlevel 1 (
  echo   [!] Pull failed - falling back to whatever copy is already local.
)

echo   starting...
docker run -d --restart unless-stopped --name %AUDIBLE_NAME% ^
  -p %AUDIBLE_PORT%:8080 ^
  --env-file .env ^
  -v audible-cache:/app/data ^
  %AUDIBLE_IMAGE% ^
  audible serve --league %AUDIBLE_LEAGUE% --host 0.0.0.0 --port 8080
if errorlevel 1 (
  echo   [X] Container failed to start. Logs:
  docker logs %AUDIBLE_NAME% 2>&1
  pause
  exit /b 1
)

echo.
echo   Waiting for the board to build (a minute or two on a cold cache)...
set /a tries=0
:wait
set /a tries+=1
curl -s -o nul -w "" http://127.0.0.1:%AUDIBLE_PORT%/healthz >nul 2>&1
for /f %%C in ('curl -s -o nul -w "%%{http_code}" http://127.0.0.1:%AUDIBLE_PORT%/healthz 2^>nul') do set "CODE=%%C"
if "%CODE%"=="200" goto ready
if %tries% GEQ 90 goto slow
timeout /t 5 /nobreak >nul
echo     still warming... (%tries%/90, /healthz=%CODE%)
goto wait

:slow
echo.
echo   [!] The board is taking longer than expected. Opening anyway - the page
echo       will say what it is waiting on. Check: docker logs %AUDIBLE_NAME%
goto open

:ready
echo   Board ready.
set "ORIGIN="
for /f %%O in ('curl -s http://127.0.0.1:%AUDIBLE_PORT%/healthz ^| findstr /C:"disk" 2^>nul') do set "ORIGIN=disk"
if "%ORIGIN%"=="disk" (
  echo   Data   : from DISK - this cockpit does not need the network.
) else (
  echo   [!] Data did NOT come from the disk cache. If the network drops you lose the
  echo       board on the next restart. Fix now:  uv run audible refresh-data
)

:open
start "" http://127.0.0.1:%AUDIBLE_PORT%/
echo.
echo   Cockpit  : http://127.0.0.1:%AUDIBLE_PORT%/
echo   MCP      : http://127.0.0.1:%AUDIBLE_PORT%/mcp
echo   Health   : http://127.0.0.1:%AUDIBLE_PORT%/healthz
echo   Logs     : docker logs -f %AUDIBLE_NAME%
echo   Stop     : docker rm -f %AUDIBLE_NAME%
echo.
echo   Leave this window closed or open, the container keeps running either way.
echo.
pause
endlocal
