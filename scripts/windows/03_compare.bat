@echo off
REM ===========================================================================
REM  03 - Compare campaigns:  baseline  vs  blackbox  vs  runtime
REM
REM  Usage:
REM    03_compare.bat                         (auto-picks the newest of each)
REM    03_compare.bat BASE_DIR BB_DIR RT_DIR  (explicit campaign directories)
REM ===========================================================================
setlocal EnableExtensions EnableDelayedExpansion
call "%~dp0env.bat"
if not "%AIDUVO_DEPS_OK%"=="1" ( pause & exit /b 1 )
cd /d "%AIDUVO_ROOT%"

set "BASE=%~1"
set "BB=%~2"
set "RT=%~3"
set "TARGET=%~4"
if "%TARGET%"=="" set "TARGET=0.9"

if not "%BASE%"=="" goto :have_paths
echo   scanning %AIDUVO_ROOT%\runs for the newest campaigns ...
for /f "delims=" %%D in ('dir /b /ad /o-d "%AIDUVO_ROOT%\runs" 2^>nul') do (
    set "NAME=%%D"
    if "!BASE!"=="" if "!NAME:baseline=!" neq "!NAME!" set "BASE=%AIDUVO_ROOT%\runs\%%D"
    if "!BB!"==""   if "!NAME:blackbox=!" neq "!NAME!" set "BB=%AIDUVO_ROOT%\runs\%%D"
    if "!RT!"==""   if "!NAME:runtime=!"  neq "!NAME!" set "RT=%AIDUVO_ROOT%\runs\%%D"
)

:have_paths
echo.
echo   baseline : %BASE%
echo   blackbox : %BB%
echo   runtime  : %RT%
echo.
set "ARGS="
if not "%BASE%"=="" set "ARGS=%ARGS% --campaign baseline="%BASE%""
if not "%BB%"==""   set "ARGS=%ARGS% --campaign blackbox="%BB%""
if not "%RT%"==""   set "ARGS=%ARGS% --campaign runtime="%RT%""
if "%ARGS%"=="" (
    echo   no campaigns found. Run 02_run_optimizer.bat first.
    pause & exit /b 1
)
set "OUTDIR=%AIDUVO_ROOT%\results\comparison_%DATE:~-4%%DATE:~3,2%%DATE:~0,2%_%TIME:~0,2%%TIME:~3,2%"
set "OUTDIR=%OUTDIR: =0%"
%PY% -m aiduvo compare %ARGS% --outdir "%OUTDIR%" --target %TARGET% --baseline baseline ^
      --title "AId-UVO-RT: baseline vs blackbox vs runtime"
echo.
echo   report : %OUTDIR%\report.md
echo   html   : %OUTDIR%\report.html
echo   json   : %OUTDIR%\comparison.json
pause
exit /b 0
