@echo off
REM ============================================================================
REM  audible - diagnose a cockpit that renders but will not respond
REM
REM  Start the cockpit first (draft-day.cmd, or `uv run audible serve`), then
REM  double-click this. It launches its OWN throwaway browser, drives the page
REM  over the DevTools protocol, and writes everything to cockpit-report.txt.
REM
REM  It launches an ISOLATED browser on purpose. Never enable remote debugging
REM  on the browser you actually use - that port exposes every open tab.
REM ============================================================================

setlocal

set "AUDIBLE_PORT=8080"
set "CDP_PORT=9444"
set "PROFILE=%TEMP%\audible-diag-profile"
set "REPORT=%~dp0..\cockpit-report.txt"

set "BROWSER="
if exist "%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe" set "BROWSER=%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"
if exist "%ProgramFiles%\Microsoft\Edge\Application\msedge.exe" set "BROWSER=%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"
if exist "%ProgramFiles%\Google\Chrome\Application\chrome.exe" set "BROWSER=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if exist "%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe" set "BROWSER=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"

if "%BROWSER%"=="" (
  echo   [X] Found neither Edge nor Chrome. Cannot drive a browser.
  pause
  exit /b 1
)

echo.
echo   audible - cockpit diagnostic
echo   cockpit : http://127.0.0.1:%AUDIBLE_PORT%/
echo   browser : %BROWSER%
echo.

curl -s -o nul http://127.0.0.1:%AUDIBLE_PORT%/healthz
if errorlevel 1 (
  echo   [X] Nothing is serving on port %AUDIBLE_PORT%.
  echo       Start the cockpit first, then run this again.
  pause
  exit /b 1
)

echo   Launching an isolated browser...
rmdir /s /q "%PROFILE%" >nul 2>&1
start "" /b "%BROWSER%" --headless=new --disable-gpu --no-first-run --disable-extensions ^
  --remote-debugging-port=%CDP_PORT% --user-data-dir="%PROFILE%" ^
  "http://127.0.0.1:%AUDIBLE_PORT%/"

timeout /t 8 /nobreak >nul

echo   Driving the page...
echo.
uv run python "%~dp0diagnose_cockpit.py" --port %AUDIBLE_PORT% --cdp %CDP_PORT% > "%REPORT%" 2>&1
set "RESULT=%errorlevel%"

type "%REPORT%"

taskkill /f /im msedge.exe /fi "WINDOWTITLE eq *" >nul 2>&1
for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":%CDP_PORT%" ^| findstr LISTENING') do taskkill /f /pid %%P >nul 2>&1

echo.
echo   Report written to: %REPORT%
echo.
if "%RESULT%"=="0" (
  echo   The page IS interactive here. If it still will not respond for you,
  echo   the difference is your browser or the container - send this report.
) else (
  echo   The page is NOT interactive. The errors above are the cause; send
  echo   this report.
)
echo.
pause
endlocal
