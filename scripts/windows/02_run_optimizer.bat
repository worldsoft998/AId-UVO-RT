@echo off
REM ===========================================================================
REM  02 - AId-UVO-RT interactive optimizer launcher
REM
REM  Menu options:
REM    M  mode      : baseline (no AI) | blackbox | runtime (SRIE)
REM    A  AI        : on / off
REM    L  algorithm : none|random|round_robin|linucb|thompson|epsilon_greedy|
REM                   qlearning|dqn|ppo|surrogate
REM    N  runs      : number of simulation runs
REM    S  seed      : base seed (sweep mode uses seed..seed+runs-1)
REM    T  target    : coverage goal in [0,1]
REM    B  backend   : questa | mock (synthetic, no licence needed)
REM    G  go        : run the selected campaign
REM    V  verify    : run baseline + blackbox + runtime and compare
REM    Q  quit
REM
REM  Non-interactive: pass any argument to skip the menu, e.g.
REM    02_run_optimizer.bat auto
REM  and set env vars MODE/AI/ALGO/RUNS/SEED/TARGET/BACKEND first if you like.
REM ===========================================================================
setlocal EnableExtensions EnableDelayedExpansion
call "%~dp0env.bat"
if not "%AIDUVO_DEPS_OK%"=="1" ( pause & exit /b 1 )
cd /d "%AIDUVO_ROOT%"

REM ---- defaults -------------------------------------------------------------
set "MODE=runtime"
set "AI=on"
set "ALGO=linucb"
set "INNER=ppo"
set "RUNS=8"
set "SEED=1"
set "TARGET=0.95"
set "BACKEND=mock"
set "MAXSTEPS=8"
set "TOPN="
set "LIB=work"
set "QUANTUM=500"
set "MAXFORCED=8"
set "RUNTIME=1000us"

if "%HAS_VSIM%"=="1" set "BACKEND=questa"
if not "%MODE%"=="" if not "%MODE_OVERRIDE%"=="" set "MODE=%MODE_OVERRIDE%"

if not "%~1"=="" goto :AUTO

:MENU
cls
echo ===========================================================================
echo   AId-UVO-RT  -  AI-Driven Universal Verification Optimization
echo ===========================================================================
echo    root      : %AIDUVO_ROOT%
echo    questa    : %HAS_VSIM%   (1 = found)
echo ---------------------------------------------------------------------------
if /i "%MODE%"=="runtime" (
    echo    M  mode      : [ %MODE% ]      <- live simulator steering ^(SRIE^)
) else if /i "%MODE%"=="blackbox" (
    echo    M  mode      : [ %MODE% ]      <- logs + coverage database only
) else (
    echo    M  mode      : [ %MODE% ]      <- no AI, sequential seeds
)
if /i "%AI%"=="on" (
    echo    A  AI        : [ on  ]   algorithm = %ALGO%   inner = %INNER%
) else (
    echo    A  AI        : [ off ]
)
echo    L  algorithm : [ %ALGO% ]
echo    N  runs      : [ %RUNS% ]
echo    S  seed      : [ %SEED% ]
echo    T  target    : [ %TARGET% ]
echo    B  backend   : [ %BACKEND% ]
echo ---------------------------------------------------------------------------
echo    G  GO    - run this campaign
echo    V  VERIFY- run baseline + blackbox + runtime, then compare
echo    Q  quit
echo ---------------------------------------------------------------------------
choice /c MALNSTBGVQ /n /m "   select > "
if errorlevel 10 goto :QUIT
if errorlevel 9 goto :VERIFY
if errorlevel 8 goto :GO
if errorlevel 7 goto :BACKEND
if errorlevel 6 goto :TARGET
if errorlevel 5 goto :SEED
if errorlevel 4 goto :RUNS
if errorlevel 3 goto :ALGO
if errorlevel 2 goto :TOGGLE_AI
if errorlevel 1 goto :MODE
goto :MENU

:MODE
if /i "%MODE%"=="runtime"  ( set "MODE=blackbox" & goto :MENU )
if /i "%MODE%"=="blackbox" ( set "MODE=baseline" & goto :MENU )
set "MODE=runtime"
if /i "%MODE%"=="runtime" if "%HAS_VSIM%"=="0" (
    echo.
    echo   NOTE: runtime mode needs QuestaSim. Backend is "%BACKEND%".
    echo         With the mock backend you can still exercise the whole SRIE loop.
    timeout /t 2 >nul
)
goto :MENU

:TOGGLE_AI
if /i "%AI%"=="on" ( set "AI=off" ) else ( set "AI=on" )
goto :MENU

:ALGO
cls
echo ===========================================================================
echo   RL / ANN algorithm
echo ===========================================================================
echo    1  none            no learning (control group)
echo    2  random          uniform random actions (control group)
echo    3  round_robin     deterministic sweep (control group)
echo    4  linucb          contextual linear UCB bandit   [recommended default]
echo    5  thompson        Beta-Bernoulli Thompson sampling
echo    6  epsilon_greedy  sample-average value bandit
echo    7  qlearning       tabular Q-learning
echo    8  dqn             double deep Q-network (numpy)
echo    9  ppo             PPO actor-critic (numpy)
echo    S  surrogate       ANN coverage surrogate (model based)
echo ---------------------------------------------------------------------------
choice /c 123456789SX /n /m "   algorithm > "
if errorlevel 11 goto :MENU
if errorlevel 10 ( set "ALGO=surrogate" & goto :ALGO_INNER )
if errorlevel 9 ( set "ALGO=ppo" & goto :ALGO_INNER )
if errorlevel 8 ( set "ALGO=dqn" & goto :ALGO_INNER )
if errorlevel 7 ( set "ALGO=qlearning" & goto :ALGO_INNER )
if errorlevel 6 ( set "ALGO=epsilon_greedy" & goto :ALGO_INNER )
if errorlevel 5 ( set "ALGO=thompson" & goto :ALGO_INNER )
if errorlevel 4 ( set "ALGO=linucb" & goto :ALGO_INNER )
if errorlevel 3 ( set "ALGO=round_robin" & goto :ALGO_INNER )
if errorlevel 2 ( set "ALGO=random" & goto :ALGO_INNER )
set "ALGO=none"
:ALGO_INNER
echo.
echo   inner (intra-run) algorithm for runtime mode [ppo]:
choice /c PDQLTX /n /m "   P=ppo D=dqn Q=qlearning L=linucb T=thompson X=keep > "
if errorlevel 6 goto :MENU
if errorlevel 5 ( set "INNER=thompson" & goto :MENU )
if errorlevel 4 ( set "INNER=linucb" & goto :MENU )
if errorlevel 3 ( set "INNER=qlearning" & goto :MENU )
if errorlevel 2 ( set "INNER=dqn" & goto :MENU )
if errorlevel 1 ( set "INNER=ppo" & goto :MENU )
goto :MENU

:RUNS
set "TMP="
set /p "TMP=   number of runs [%RUNS%]: "
if not "%TMP%"=="" set "RUNS=%TMP%"
goto :MENU

:SEED
set "TMP="
set /p "TMP=   base seed [%SEED%]: "
if not "%TMP%"=="" set "SEED=%TMP%"
goto :MENU

:TARGET
set "TMP="
set /p "TMP=   coverage goal 0..1 [%TARGET%]: "
if not "%TMP%"=="" set "TARGET=%TMP%"
goto :MENU

:BACKEND
if /i "%BACKEND%"=="questa" ( set "BACKEND=mock" ) else ( set "BACKEND=questa" )
if /i "%BACKEND%"=="questa" if "%HAS_VSIM%"=="0" (
    echo.
    echo   vsim.exe was not found. Set QUESTA_ROOT, or stay on the mock backend.
    timeout /t 3 >nul
    set "BACKEND=mock"
)
goto :MENU

:GO
call :BUILD_CONFIG
if errorlevel 1 ( pause & goto :MENU )
echo.
echo ===========================================================================
echo   running campaign ...
echo ===========================================================================
%PY% -m aiduvo run --config "%CFG%" --mode %MODE% --ai %AI% --algorithm %ALGO%
set "RC=%ERRORLEVEL%"
echo.
if "%RC%"=="0" (
    echo [done] results under %AIDUVO_ROOT%\%OUTDIR%
    echo [done] next: 03_compare.bat
) else (
    echo [error] campaign failed with code %RC%
)
pause
goto :MENU

:VERIFY
call :BUILD_CONFIG
if errorlevel 1 ( pause & goto :MENU )
echo.
%PY% -m aiduvo sweep --config "%CFG%" --runs %RUNS% --seed %SEED% --target %TARGET% ^
     --algorithm %ALGO% --outdir "%OUTDIR%\sweep" --tag "menu"
echo.
echo [done] comparison report: %OUTDIR%\sweep\report.md
pause
goto :MENU

:BUILD_CONFIG
set "OUTDIR=runs\%MODE%_%ALGO%_%DATE:~-4%%DATE:~3,2%%DATE:~0,2%_%TIME:~0,2%%TIME:~3,2%"
set "OUTDIR=%OUTDIR: =0%"
set "CFG=%AIDUVO_ROOT%\config\campaign_%MODE%.json"
set "MOCKFLAG="
if /i "%BACKEND%"=="mock" set "MOCKFLAG=--mock"
echo.
echo   generating config ...
%PY% "%AIDUVO_ROOT%\scripts\tools\make_config.py" ^
    --out "%CFG%" --mode %MODE% --ai %AI% --algorithm %ALGO% --inner-algorithm %INNER% ^
    --runs %RUNS% --seed %SEED% --target %TARGET% --max-steps %MAXSTEPS% ^
    --top "%TOPN%" --lib "%LIB%" --outdir "%OUTDIR%" --tag "%MODE%" ^
    --run-time %RUNTIME% --quantum %QUANTUM% --max-forced %MAXFORCED %MOCKFLAG%
if errorlevel 1 exit /b 1
exit /b 0

:AUTO
REM ---- non-interactive path -------------------------------------------------
call :BUILD_CONFIG
if errorlevel 1 exit /b 1
%PY% -m aiduvo run --config "%CFG%" --mode %MODE% --ai %AI% --algorithm %ALGO%
exit /b %ERRORLEVEL%

:QUIT
echo bye.
exit /b 0
