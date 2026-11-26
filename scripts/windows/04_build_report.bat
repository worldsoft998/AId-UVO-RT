@echo off
REM ===========================================================================
REM  04 - Rebuild the comparison report from existing campaigns
REM
REM  Usage:
REM    04_build_report.bat                       (auto-pick newest campaigns)
REM    04_build_report.bat RESULTS_DIR            (rebuild a results folder)
REM ===========================================================================
setlocal EnableExtensions EnableDelayedExpansion
call "%~dp0env.bat"
if not "%AIDUVO_DEPS_OK%"=="1" ( pause & exit /b 1 )
cd /d "%AIDUVO_ROOT%"

if not "%~1"=="" (
    echo   rebuilding %~1 ...
    %PY% -c "import sys,glob,os; sys.path.insert(0,r'%AIDUVO_ROOT%'); from aiduvo.reporting import compare, build_report, load_campaign; d=r'%~1'; cs={}; [cs.setdefault(os.path.basename(p.rstrip('\\/')).split('_')[0], load_campaign(p)) for p in sorted(glob.glob(os.path.join(d,'*'))) if os.path.isdir(p) and os.path.exists(os.path.join(p,'campaign_result.json'))]; c=compare(cs, target=0.9); print(build_report(c, d, title='AId-UVO-RT report (rebuilt)')); print('report:', os.path.join(d,'report.md'))"
    pause & exit /b 0
)

echo   scanning for campaigns ...
set "BASE="
set "BB="
set "RT="
for /f "delims=" %%D in ('dir /b /ad /o-d "%AIDUVO_ROOT%\runs" 2^>nul') do (
    set "NAME=%%D"
    if "!BASE!"=="" if "!NAME:baseline=!" neq "!NAME!" set "BASE=%AIDUVO_ROOT%\runs\%%D"
    if "!BB!"==""   if "!NAME:blackbox=!" neq "!NAME!" set "BB=%AIDUVO_ROOT%\runs\%%D"
    if "!RT!"==""   if "!NAME:runtime=!"  neq "!NAME!" set "RT=%AIDUVO_ROOT%\runs\%%D"
)
set "ARGS="
if not "%BASE%"=="" set "ARGS=%ARGS% --campaign baseline="%BASE%""
if not "%BB%"==""   set "ARGS=%ARGS% --campaign blackbox="%BB%""
if not "%RT%"==""   set "ARGS=%ARGS% --campaign runtime="%RT%""
if "%ARGS%"=="" ( echo   nothing to report on. & pause & exit /b 1 )
set "OUTDIR=%AIDUVO_ROOT%\results\report_%DATE:~-4%%DATE:~3,2%%DATE:~0,2%_%TIME:~0,2%%TIME:~3,2%"
set "OUTDIR=%OUTDIR: =0%"
%PY% -m aiduvo compare %ARGS% --outdir "%OUTDIR%" --baseline baseline --target 0.9
echo.
echo   report : %OUTDIR%\report.md
echo   html   : %OUTDIR%\report.html
pause
exit /b 0
