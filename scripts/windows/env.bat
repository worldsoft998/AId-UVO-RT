@echo off
REM ===========================================================================
REM  AId-UVO-RT  --  shared environment for the Windows batch workflow
REM  Call this first:  call "%~dp0env.bat"
REM  It sets:  AIDUVO_ROOT, PY, PYTHONPATH, HAS_VSIM, AIDUVO_DEPS_OK
REM  No setlocal here on purpose: the caller needs these variables.
REM ===========================================================================
set "AIDUVO_ROOT=%~dp0..\.."
pushd "%AIDUVO_ROOT%" >nul 2>&1
set "AIDUVO_ROOT=%CD%"
popd >nul 2>&1
set "PYTHONPATH=%AIDUVO_ROOT%;%PYTHONPATH%"

REM ---- Python -------------------------------------------------------------
set "PY=python"
where py >nul 2>&1 && set "PY=py -3"
%PY% -c "import sys; print(sys.version.split()[0])" >nul 2>&1
if errorlevel 1 (
    echo [env] ERROR: Python not found on PATH. Install Python 3.9+ and retry.
    set "AIDUVO_DEPS_OK=0"
    goto :questasim
)
%PY% -c "import numpy" >nul 2>&1
if errorlevel 1 (
    echo [env] numpy is missing. Install with:
    echo        %PY% -m pip install -r "%AIDUVO_ROOT%\requirements.txt"
    set "AIDUVO_DEPS_OK=0"
) else (
    set "AIDUVO_DEPS_OK=1"
)

:questasim
REM ---- QuestaSim ----------------------------------------------------------
set "HAS_VSIM=0"
where vsim >nul 2>&1 && set "HAS_VSIM=1"
if "%HAS_VSIM%"=="0" if not "%QUESTA_ROOT%"=="" if exist "%QUESTA_ROOT%\win64\vsim.exe" (
    set "PATH=%QUESTA_ROOT%\win64;%PATH%"
    set "HAS_VSIM=1"
)
if "%HAS_VSIM%"=="0" if not "%QUESTA_ROOT%"=="" if exist "%QUESTA_ROOT%\bin\vsim.exe" (
    set "PATH=%QUESTA_ROOT%\bin;%PATH%"
    set "HAS_VSIM=1"
)
if "%HAS_VSIM%"=="0" if exist "C:\questasim64_2024.1\win64\vsim.exe" (
    set "PATH=C:\questasim64_2024.1\win64;%PATH%"
    set "HAS_VSIM=1"
)

set "AIDUVO_CONFIG=%AIDUVO_ROOT%\config\campaign.json"
if not exist "%AIDUVO_ROOT%\config" mkdir "%AIDUVO_ROOT%\config" >nul 2>&1
if not exist "%AIDUVO_ROOT%\runs" mkdir "%AIDUVO_ROOT%\runs" >nul 2>&1

if "%AIDUVO_VERBOSE%"=="1" (
    echo [env] root      = %AIDUVO_ROOT%
    echo [env] python    = %PY%
    echo [env] deps ok   = %AIDUVO_DEPS_OK%
    echo [env] vsim      = %HAS_VSIM%
)
exit /b 0
