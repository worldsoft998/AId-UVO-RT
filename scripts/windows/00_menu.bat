@echo off
REM ===========================================================================
REM  AId-UVO-RT  -  top-level menu
REM ===========================================================================
setlocal EnableExtensions
call "%~dp0env.bat"
cd /d "%AIDUVO_ROOT%"
:MENU
cls
echo ===========================================================================
echo    AId-UVO-RT   AI-Driven Universal Verification Optimization
echo    Runtime / Instantaneous   -   QuestaSim + SystemVerilog/UVM
echo ===========================================================================
echo     root    : %AIDUVO_ROOT%
echo     python  : %PY%
echo     questa  : %HAS_VSIM%  ^(1 = vsim.exe found^)
echo ---------------------------------------------------------------------------
echo    1  Compile the design with coverage            [01_compile.bat]
echo    2  Run the optimizer (interactive menu)        [02_run_optimizer.bat]
echo    3  Compare baseline / blackbox / runtime       [03_compare.bat]
echo    4  Rebuild the comparison report               [04_build_report.bat]
echo    5  Framework selftest (no simulator needed)    [05_selftest.bat]
echo    6  Package repository as ZIP                   [06_package.bat]
echo    7  One-click mock demo (no licence needed)     [demo_mock.bat]
echo    8  Discover the design and write a config      [python -m aiduvo discover]
echo    9  Compliance lint (non-intrusiveness)         [python -m aiduvo lint]
echo    Q  Quit
echo ---------------------------------------------------------------------------
choice /c 123456789Q /n /m "   select > "
if errorlevel 10 exit /b 0
if errorlevel 9  ( cls & %PY% -m aiduvo lint & pause & goto :MENU )
if errorlevel 8  ( cls & %PY% -m aiduvo discover --config "%AIDUVO_CONFIG%" --out "%AIDUVO_ROOT%\config\discovered.json" --mock & pause & goto :MENU )
if errorlevel 7  ( call "%~dp0demo_mock.bat" & goto :MENU )
if errorlevel 6  ( call "%~dp0\06_package.bat" & goto :MENU )
if errorlevel 5  ( call "%~dp0\05_selftest.bat" & goto :MENU )
if errorlevel 4  ( call "%~dp0\04_build_report.bat" & goto :MENU )
if errorlevel 3  ( call "%~dp0\03_compare.bat" & goto :MENU )
if errorlevel 2  ( call "%~dp0\02_run_optimizer.bat" & goto :MENU )
if errorlevel 1  ( call "%~dp0\01_compile.bat" & goto :MENU )
goto :MENU
