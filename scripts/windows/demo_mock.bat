@echo off
REM ===========================================================================
REM  One-click demo: baseline vs blackbox vs runtime on the SYNTHETIC backend.
REM
REM  No QuestaSim licence needed.  Numbers are illustrative only - they prove
REM  the pipeline learns and that all three modes are measured identically.
REM ===========================================================================
setlocal EnableExtensions
call "%~dp0env.bat"
if not "%AIDUVO_DEPS_OK%"=="1" ( pause & exit /b 1 )
cd /d "%AIDUVO_ROOT%"
set "OUT=%AIDUVO_ROOT%\results\demo_mock"
echo ===========================================================================
echo   AId-UVO-RT mock demo   (synthetic simulator, no licence required)
echo ===========================================================================
%PY% -m aiduvo sweep --mock --algorithm linucb --runs 10 --seed 1 --target 0.9 ^
      --outdir "%OUT%" --tag demo
set "RC=%ERRORLEVEL%"
echo.
if exist "%OUT%\report.md" (
    echo   report : %OUT%\report.md
    echo   html   : %OUT%\report.html
    start "" "%OUT%\report.html"
)
pause
exit /b %RC%
