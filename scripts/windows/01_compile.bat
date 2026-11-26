@echo off
REM ===========================================================================
REM  01 - Compile the design with coverage instrumentation (Questasim)
REM  Coverage is enabled with simulator switches only: no source edits.
REM ===========================================================================
setlocal EnableExtensions
call "%~dp0env.bat"
if not "%AIDUVO_DEPS_OK%"=="1" ( pause & exit /b 1 )
if not "%HAS_VSIM%"=="1" (
    echo [compile] vsim.exe not found. Set QUESTA_ROOT or add QuestaSim to PATH.
    pause & exit /b 1
)
cd /d "%AIDUVO_ROOT%"
echo ===========================================================================
echo  Compiling with coverage  (+cover=bcestfx)
echo ===========================================================================
if "%1"=="--do-file" goto :dofile
vsim -c -quiet -do "do scripts/questa/compile.do"
set "RC=%ERRORLEVEL%"
goto :done

:dofile
REM Advanced: compile a different project by pointing at your own do-file.
REM  01_compile.bat --do-file path\to\my_compile.do
if "%2"=="" ( echo usage: 01_compile.bat --do-file ^<compile.do^> & pause & exit /b 2 )
vsim -c -quiet -do "do %2"
set "RC=%ERRORLEVEL%"

:done
echo.
if "%RC%"=="0" (
    echo [compile] OK - library "work" built with coverage.
    echo [compile] Next: 02_run_optimizer.bat
) else (
    echo [compile] FAILED with code %RC%. See the transcript above.
)
pause
exit /b %RC%
