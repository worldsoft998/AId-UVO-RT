@echo off
REM ===========================================================================
REM  06 - Package the repository into a single downloadable ZIP
REM ===========================================================================
setlocal EnableExtensions
call "%~dp0env.bat"
if not "%AIDUVO_DEPS_OK%"=="1" ( pause & exit /b 1 )
cd /d "%AIDUVO_ROOT%"
%PY% -m aiduvo zip
echo.
echo   archives are written to %AIDUVO_ROOT%\dist
dir /b "%AIDUVO_ROOT%\dist\*.zip" 2>nul
pause
exit /b 0
