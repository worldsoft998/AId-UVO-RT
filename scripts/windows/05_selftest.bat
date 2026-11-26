@echo off
REM ===========================================================================
REM  05 - Framework selftest (no simulator required)
REM  Exercises: coverage import, every RL algorithm, baseline/blackbox/runtime
REM             campaigns on the synthetic backend, reporting, compliance lint.
REM ===========================================================================
setlocal EnableExtensions
call "%~dp0env.bat"
if not "%AIDUVO_DEPS_OK%"=="1" ( pause & exit /b 1 )
cd /d "%AIDUVO_ROOT%"
echo ===========================================================================
echo   AId-UVO-RT selftest
echo ===========================================================================
%PY% -m aiduvo selftest --outdir "%AIDUVO_ROOT%\runs\_selftest"
set "RC=%ERRORLEVEL%"
echo.
if "%RC%"=="0" (
    echo [selftest] PASS - see runs\_selftest\report
) else (
    echo [selftest] FAIL - see runs\_selftest\selftest.log
)
pause
exit /b %RC%
