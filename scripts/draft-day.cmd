@echo off
REM ============================================================================
REM  audible - draft day launcher
REM
REM  Double-click this. It starts the cockpit container and opens the browser.
REM  Production quality for one operator means not remembering flags at 8pm.
REM
REM  BEFORE DRAFT WEEK: set AUDIBLE_IMAGE below to a pinned DIGEST, not a tag.
REM  `latest` can move under you; a digest cannot. Get it from the image workflow
REM  summary on the merge commit you want.
REM ============================================================================

setlocal

set "AUDIBLE_IMAGE=ghcr.io/eyanric/audible:latest"
set "AUDIBLE_PORT=8080"
set "AUDIBLE_NAME=audible-cockpit"

echo.
echo   audible cockpit
echo   image : %AUDIBLE_IMAGE%
echo   port  : %AUDIBLE_PORT%
echo.

docker version >nul 2>&1
if errorlevel 1 (
  echo   [X] Docker is not running. Start Docker Desktop and run this again.
  echo.
  echo   Fallback while you wait - from the repo, this needs no container:
  echo       uv run audible serve --league sleeper_boyfun
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
  %AUDIBLE_IMAGE%
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
