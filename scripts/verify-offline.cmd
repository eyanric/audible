@echo off
REM ============================================================================
REM  audible - offline re-proof, ON THE ARTIFACT YOU NAME
REM
REM  WHAT THIS PROVES. --network none removes the container's network namespace
REM  entirely, so there is no interface to reach. Building both boards inside
REM  that is an OS-level proof that draft night survives a dead wifi, not a
REM  mocked one. It is the check most likely to catch a packaging difference:
REM  a missing file, a wrong path, a volume that is not where the code looks.
REM
REM  WHY THERE IS NO PINNED DIGEST HERE ANY MORE.
REM  This script used to hardcode sha256:d3cdb2a1..., set in mid-August. Every
REM  "verify-offline PASS" reported after that - in PR bodies, in the runbook,
REM  in handbacks - was a true statement about a stale image and a false one
REM  about the artifact being verified. It failed GREEN, which is the worst way
REM  for a check to fail: nobody investigates a pass.
REM
REM  A verifier must not carry its own idea of what it is verifying. So:
REM
REM    verify-offline.cmd
REM        builds the image from THIS working tree and verifies that. This is
REM        the thing under test when you are about to ship.
REM
REM    verify-offline.cmd ghcr.io/eyanric/audible@sha256:<digest>
REM    verify-offline.cmd audible:sometag
REM        verifies exactly the artifact you name - use this to check a digest
REM        that is actually deployed. The reference comes from you, so it
REM        cannot silently go stale.
REM
REM  Either way the image and where its reference came from are printed at the
REM  top and the bottom, and step 2 proves the image really contains this tree.
REM ============================================================================

setlocal

set "REPO=%~dp0.."
pushd "%REPO%" || (echo   [X] Cannot reach the repo at "%REPO%". & pause & exit /b 1)

set "AUDIBLE_IMAGE=%~1"
set "IMAGE_SOURCE="
set "BUILT_HERE="

docker version >nul 2>&1
if errorlevel 1 (
  echo   [X] Docker is not running. Start Docker Desktop and run this again.
  popd & pause & exit /b 1
)

if "%AUDIBLE_IMAGE%"=="" goto build_local
set "IMAGE_SOURCE=named on the command line"
goto have_image

:build_local
set "AUDIBLE_IMAGE=audible:verify-offline"
set "IMAGE_SOURCE=built from this working tree"
set "BUILT_HERE=1"

:have_image
echo.
echo   audible - offline re-proof
echo   image  : %AUDIBLE_IMAGE%
echo   source : %IMAGE_SOURCE%
echo.

if not defined BUILT_HERE goto pull_it

echo   [1/4] Building the image from this working tree...
docker build -t %AUDIBLE_IMAGE% . || goto build_failed
goto provenance

:pull_it
REM  Only pull what is not already here. A locally built tag has no registry to
REM  pull from, and an unconditional pull made this script exit 1 at step 1 -
REM  looking like a failure of the artifact when it was a failure of the script.
docker image inspect %AUDIBLE_IMAGE% >nul 2>&1
if not errorlevel 1 (
  echo   [1/4] %AUDIBLE_IMAGE% is already present locally; not pulling.
  goto provenance
)
echo   [1/4] Pulling %AUDIBLE_IMAGE% (this step needs the network)...
docker pull %AUDIBLE_IMAGE%
if errorlevel 1 (
  echo   [X] Pull failed. Cannot verify an artifact that is not here.
  popd & pause & exit /b 1
)

:provenance
echo.
echo   [2/4] Checking the image really carries this tree's cockpit page...
REM  The page is the file that has actually differed between tree and image
REM  before. Comparing its hash is how we know WHICH artifact just passed,
REM  rather than trusting the tag or the digest to mean what we assume.
for /f %%H in ('powershell -NoProfile -Command "(Get-FileHash -Algorithm SHA256 'src\audible\server\static\index.html').Hash.ToLower()"') do set "TREE_HASH=%%H"
REM  tokens=1 rather than piping through cut: escaping a pipe inside for /f made
REM  sh receive a literal ^ as a filename, and the hash only matched by luck
REM  because the error went to stderr while the real line stayed first on stdout.
for /f "tokens=1" %%H in ('docker run --rm --entrypoint sh %AUDIBLE_IMAGE% -c "sha256sum /app/src/audible/server/static/index.html"') do set "IMAGE_HASH=%%H"
echo         tree  : %TREE_HASH%
echo         image : %IMAGE_HASH%
if /I not "%TREE_HASH%"=="%IMAGE_HASH%" (
  if defined BUILT_HERE (
    echo.
    echo   [X] The image was just built from this tree and does not match it.
    echo       That is a packaging bug. Stop and investigate.
    popd & pause & exit /b 1
  )
  echo         ^(differs - expected when verifying an image you named, not built.^)
  echo         This artifact is NOT the current working tree. That may be exactly
  echo         what you want; just be clear which one you are proving.
) else (
  echo         match - this image is the current working tree.
)

echo.
echo   [3/4] Filling the cache volume using THIS image...
echo         ^(same code writes the cache that will later read it^)
docker run --rm --env-file .env -v audible-cache:/app/data %AUDIBLE_IMAGE% ^
  audible refresh-data
if errorlevel 1 (
  echo   [X] refresh-data failed. The cache is not populated; stop and fix.
  popd & pause & exit /b 1
)

echo.
echo   [4/4] Building both boards with NO NETWORK AT ALL...
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
echo    PASS - both boards built with the network namespace removed.
echo    image  : %AUDIBLE_IMAGE%
echo    source : %IMAGE_SOURCE%
echo    Draft night survives a dead wifi.
echo   ============================================================
echo.
popd & pause & exit /b 0

:build_failed
echo.
echo   [X] docker build failed. Nothing to verify.
popd & pause & exit /b 1

:failed
echo.
echo   ============================================================
echo    FAIL - a board did NOT build offline.
echo    image  : %AUDIBLE_IMAGE%
echo    source : %IMAGE_SOURCE%
echo.
echo    Most likely causes:
echo      - the audible-cache volume is empty or mounted elsewhere
echo      - refresh-data did not cover the league that failed
echo      - this image genuinely cannot build a board offline
echo    Re-run step 3, then this script again.
echo   ============================================================
echo.
popd & pause & exit /b 1
