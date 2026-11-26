@echo off
REM ---------------------------------------------------------------------------
REM Build the optional SRIE FLI shim (reference implementation).
REM Requires a QuestaSim installation with the FLI headers and mtipli.lib.
REM ---------------------------------------------------------------------------
setlocal
if "%QUESTA_ROOT%"=="" (
  echo [build_fli] QUESTA_ROOT is not set. Point it at your QuestaSim install.
  exit /b 1
)
set INC=%QUESTA_ROOT%\include
set LIB=%QUESTA_ROOT%\win64\mtipli.lib
if not exist "%INC%\mti.h" (
  echo [build_fli] mti.h not found under %INC%
  exit /b 1
)
if not exist "%LIB%" (
  echo [build_fli] mtipli.lib not found under %QUESTA_ROOT%\win64
  exit /b 1
)
echo [build_fli] compiling srie_fli.dll ...
cl /nologo /LD /O2 srie_fli.c /I"%INC%" /link "%LIB%" ws2_32.lib /OUT:srie_fli.dll
if errorlevel 1 (
  echo [build_fli] build failed
  exit /b 1
)
echo [build_fli] done: %CD%\srie_fli.dll
echo [build_fli] load it with:
echo     vsim -foreign "srie_fli_init srie_fli.dll 7654" -c work.tb_top_opt
endlocal
